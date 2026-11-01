from copy import deepcopy

import pytest
from openpyxl import Workbook, load_workbook
from werkzeug.security import check_password_hash, generate_password_hash

from portal.allocations import HEADERS, read_allocations, provision_accounts, PASSWORD_POOL, generate_password, shorten_staff_passwords
from portal.form_layout import BLOCKS
from portal.models import db, User, Region, Assignment, SourceRecord, Grant, Supervision


@pytest.fixture
def allocation_file(app, tmp_path):
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(HEADERS)
    with app.app_context():
        for index, region in enumerate(db.session.query(Region).order_by(Region.code)):
            widths = (2, 2, 3, 3, 4, 2)
            parts, offset = [], 0
            for width in widths:
                parts.append(region.code[offset:offset + width])
                offset += width
            sheet.append([*parts, f'pml{0 if index < 6 else 1}@example.test', f'ppl{index // 2}@example.test'])
    path = tmp_path / 'allocation.xlsx'
    workbook.save(path)
    return path


def plan_for(app, allocation_file):
    with app.app_context():
        return read_allocations(allocation_file, {region.code for region in db.session.query(Region)})


@pytest.fixture
def provisioned(app, allocation_file, tmp_path):
    plan = plan_for(app, allocation_file)
    target = tmp_path / 'private' / 'accounts.xlsx'
    with app.app_context():
        report = provision_accounts(plan, 'root@example.test', 'Synthetic-admin-6502!', target)
    workbook = load_workbook(target, read_only=True, data_only=True)
    passwords = {row[0]: row[2] for row in list(workbook['Akun petugas'].values)[1:]}
    workbook.close()
    return report, passwords, plan


def login(app, username, password):
    client = app.test_client()
    assert client.post('/login', data={'username': username, 'password': password}).status_code == 302
    assert client.post('/commitment', data={'decision': 'accept'}).status_code == 302
    return client


def test_workbook_leading_zero_codes_and_team_coverage(app, allocation_file):
    plan = plan_for(app, allocation_file)
    assert plan.summary() == {'rows': 14, 'sls': 14, 'ppl': 7, 'pml': 2,
                              'sls_per_ppl': [2] * 7, 'sls_per_pml': [6, 8], 'ppl_per_pml': [3, 4]}
    assert '6502000000000001' in plan.ppl['ppl0@example.test']


@pytest.mark.parametrize('bad', ['duplicate', 'different_pml', 'unknown', 'role_collision', 'missing_email', 'incomplete'])
def test_invalid_allocation_fails_before_account_mutation(app, allocation_file, bad):
    workbook = load_workbook(allocation_file)
    sheet = workbook.active
    if bad == 'duplicate':
        sheet.append([cell.value for cell in sheet[2]])
    elif bad == 'different_pml':
        sheet.cell(3, 7, 'pml1@example.test')
    elif bad == 'unknown':
        sheet.cell(2, 1, '99')
    elif bad == 'role_collision':
        sheet.cell(2, 7, 'ppl0@example.test')
        sheet.cell(3, 7, 'ppl0@example.test')
    elif bad == 'missing_email':
        sheet.cell(2, 8).value = None
    else:
        sheet.delete_rows(15)
    workbook.save(allocation_file)
    with app.app_context():
        before = db.session.query(User).count()
        with pytest.raises(ValueError):
            read_allocations(allocation_file, {region.code for region in db.session.query(Region)})
        assert db.session.query(User).count() == before


def test_generated_passwords_unique_hashed_and_reimport_refused(app, provisioned, tmp_path):
    report, passwords, plan = provisioned
    assert report['active_accounts'] == 10 and len(set(passwords.values())) == 9
    assert all(value in PASSWORD_POOL for value in passwords.values())
    with app.app_context():
        users = db.session.query(User).filter_by(active=True).all()
        assert len(users) == 10
        assert db.session.query(Supervision).count() == 7
        assert db.session.query(Grant).filter(Grant.user_id.in_([u.id for u in users])).count() == 14
        for user in users:
            password = passwords.get(user.username, 'Synthetic-admin-6502!')
            assert user.password_hash != password and check_password_hash(user.password_hash, password)
        snapshot = {u.id: u.password_hash for u in users}
        with pytest.raises(ValueError, match='sudah ada'):
            provision_accounts(plan, 'root@example.test', 'Synthetic-admin-6502!', tmp_path / 'retry.xlsx')
        assert {u.id: u.password_hash for u in db.session.query(User).filter_by(active=True)} == snapshot


def test_every_role_is_scoped_in_backend_and_masking_remains(app, provisioned):
    _, passwords, plan = provisioned
    with app.app_context():
        for code in ('6502000000000003', '6502000000000007'):
            assignment = Assignment(source_id='outside-' + code, version='synthetic', latest=True,
                region=code, name='OUTSIDE', building='42', kind='BKU', existence='Kode 1', status='OPEN')
            db.session.add(assignment)
        db.session.commit()
        outside = {a.region: a.id for a in db.session.query(Assignment).filter_by(name='OUTSIDE')}
    for username, password in passwords.items():
        client = login(app, username.upper(), password)
        allowed = plan.ppl[username] if username in plan.ppl else set().union(*(plan.ppl[ppl] for ppl in plan.pml[username]))
        home = client.get('/').get_data(as_text=True)
        assert home.count('class="region-card"') == len(allowed)
        assert 'href="/dataset"' not in home
        assert client.get('/dataset').status_code == 403
        for code in [r['region'] for r in plan.rows]:
            assert client.get('/sls/' + code).status_code == (200 if code in allowed else 404)
        for code, pk in outside.items():
            if code not in allowed:
                assert client.get(f'/assignment/{pk}').status_code == 404
                for block in BLOCKS:
                    assert client.get(f'/assignment/{pk}/{block}/block').status_code == 404
        if '6502000000000001' in allowed:
            html = client.get('/assignment/1/iv/block').get_data(as_text=True)
            assert '2500000' not in html and '2.500.000' not in html
            assert 'Rp 1 juta – kurang dari Rp 5 juta' in html
            assert '9999999999991234' in client.get('/assignment/1/i/block').get_data(as_text=True)
    admin = login(app, 'root@example.test', 'Synthetic-admin-6502!')
    assert admin.get('/').get_data(as_text=True).count('class="region-card"') == 14
    assert admin.get('/dataset').status_code == 200


def test_supervisor_access_follows_ppl_grants_without_own_grants(app, provisioned):
    _, passwords, _ = provisioned
    client = login(app, 'pml0@example.test', passwords['pml0@example.test'])
    with app.app_context():
        pml = db.session.query(User).filter_by(username='pml0@example.test').one()
        ppl = db.session.query(User).filter_by(username='ppl0@example.test').one()
        assert db.session.query(Grant).filter_by(user_id=pml.id).count() == 0
        db.session.query(Grant).filter_by(user_id=ppl.id, region='6502000000000001').delete()
        db.session.commit()
    assert client.get('/sls/6502000000000001').status_code == 404
    assert client.get('/sls/6502000000000002').status_code == 200


def test_password_change_and_disable_invalidate_old_sessions(app, provisioned):
    _, passwords, _ = provisioned
    client = login(app, 'ppl0@example.test', passwords['ppl0@example.test'])
    with app.app_context():
        user = db.session.query(User).filter_by(username='ppl0@example.test').one()
        user.password_hash = generate_password_hash('Replacement-synthetic-6502!')
        db.session.commit()
    assert client.get('/').status_code == 302
    assert client.get('/assignment/1/iv/block').status_code == 403
    client = login(app, 'ppl0@example.test', 'Replacement-synthetic-6502!')
    with app.app_context():
        db.session.query(User).filter_by(username='ppl0@example.test').update({'active': False})
        db.session.commit()
    assert client.get('/').status_code == 302


def test_failed_export_rolls_back_accounts_and_preserves_data(app, allocation_file, tmp_path):
    plan = plan_for(app, allocation_file)
    blocker = tmp_path / 'not-a-directory'
    blocker.write_text('synthetic')
    with app.app_context():
        before_users = [(u.id, u.active, u.password_hash) for u in db.session.query(User)]
        before_data = {r.id: deepcopy(r.raw) for r in db.session.query(SourceRecord)}
        with pytest.raises(OSError):
            provision_accounts(plan, 'root@example.test', 'Synthetic-admin-6502!', blocker / 'accounts.xlsx')
        assert [(u.id, u.active, u.password_hash) for u in db.session.query(User)] == before_users
        assert {r.id: r.raw for r in db.session.query(SourceRecord)} == before_data


def test_short_password_pool_and_rotation_preserve_admin_and_allocations(app, provisioned, tmp_path):
    _, _, _ = provisioned
    target = tmp_path / 'private' / 'accounts.xlsx'
    with app.app_context():
        admin = db.session.query(User).filter_by(role='admin', active=True).one()
        admin_before = admin.password_hash
        grants = [(g.user_id, g.region) for g in db.session.query(Grant)]
        result = shorten_staff_passwords(target)
        assert result['staff_passwords_updated'] == 9 and result['passwords_unique']
        assert admin.password_hash == admin_before
        assert [(g.user_id, g.region) for g in db.session.query(Grant)] == grants
        workbook = load_workbook(target, read_only=True, data_only=True)
        rows = list(workbook['Akun petugas'].values)[1:]
        assert len({r[2] for r in rows}) == 9
        for row in rows:
            assert row[2] in PASSWORD_POOL
            assert check_password_hash(db.session.query(User).filter_by(username=row[0]).one().password_hash, row[2])
        workbook.close()
    with pytest.raises(ValueError, match='tidak cukup'):
        generate_password(PASSWORD_POOL)


def test_password_reset_requires_and_updates_distribution(app, provisioned, tmp_path):
    _, _, _ = provisioned
    runner = app.test_cli_runner()
    target = tmp_path / 'private' / 'accounts.xlsx'
    result = runner.invoke(args=['set-password', 'PPL0@example.test'], input='Survey1234\nSurvey1234\n')
    assert result.exit_code != 0
    result = runner.invoke(args=['set-password', 'PPL0@example.test', '--credentials-file', str(target)], input='Survey1234\nSurvey1234\n')
    assert result.exit_code == 0, result.output
    workbook = load_workbook(target, read_only=True, data_only=True)
    row = next(row for row in list(workbook['Akun petugas'].values)[1:] if row[0] == 'ppl0@example.test')
    assert row[2] == 'Survey1234'
    workbook.close()
    with app.app_context():
        assert check_password_hash(db.session.query(User).filter_by(username='ppl0@example.test').one().password_hash, 'Survey1234')


def test_update_allocations_preview_and_apply_preserve_passwords(app, provisioned, allocation_file):
    _, _, _ = provisioned
    workbook = load_workbook(allocation_file)
    for line in (2, 3):
        workbook.active.cell(line, 8, 'ppl1@example.test')
    for line in (4, 5):
        workbook.active.cell(line, 8, 'ppl0@example.test')
    workbook.save(allocation_file)
    with app.app_context():
        passwords = {u.id: u.password_hash for u in db.session.query(User)}
        grants = {(r.user_id, r.region) for r in db.session.query(Grant)}
    runner = app.test_cli_runner()
    preview = runner.invoke(args=['update-allocations', str(allocation_file)])
    assert preview.exit_code == 0, preview.output
    with app.app_context():
        assert {(r.user_id, r.region) for r in db.session.query(Grant)} == grants
    result = runner.invoke(args=['update-allocations', str(allocation_file), '--apply'])
    assert result.exit_code == 0, result.output
    with app.app_context():
        assert {u.id: u.password_hash for u in db.session.query(User)} == passwords
        assert {(r.user_id, r.region) for r in db.session.query(Grant)} != grants
