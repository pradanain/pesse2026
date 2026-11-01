from datetime import datetime

import pytest
from openpyxl import load_workbook
from openpyxl.utils.datetime import to_excel, MAC_EPOCH

from portal.analysis import normalize_date
from portal.importer import import_dataset, valid_coordinates
from portal.models import db, Region, Assignment, SourceRecord, Dataset
from portal.presentation import display_value
from portal.form_layout import BLOCKS


def test_date_formats():
    d = datetime(2026, 10, 17, 10, 29, 6, 897000)
    expected = '2026-10-17T10:29:06.897'
    assert normalize_date(d) == normalize_date('2026-10-17 10:29:06.897') == normalize_date(to_excel(d)) == expected
    assert normalize_date(to_excel(d, MAC_EPOCH), MAC_EPOCH) == expected
    assert normalize_date('2026-10-17T18:29:06.897+08:00') == expected
    for invalid in (None, '', 'nonsense', True):
        with pytest.raises((ValueError, TypeError)):
            normalize_date(invalid)


def test_counts_and_idempotency(app, source_dir):
    with app.app_context():
        before = db.session.query(SourceRecord).count()
        report = import_dataset(source_dir)
        assert report['unchanged'] is True
        assert db.session.query(Region).count() == 14
        assert db.session.query(SourceRecord).count() == before == report['stored_records']
        assert sum(s['rows'] for s in report['sheets']) == before
        assert report['unmatched_records'] == 0
        assert db.session.query(Assignment).count() == 3
        family = db.session.query(Assignment).filter_by(source_id='contoh-keluarga').one()
        assert family.members == 3 and family.businesses == 2
        assert not family.issues


def test_independent_rosters_render_without_multiplication(client):
    art = client.get('/assignment/1/i/block').get_data(as_text=True)
    social = client.get('/assignment/1/iii/block').get_data(as_text=True)
    businesses = client.get('/assignment/1/ii/block').get_data(as_text=True)
    assert art.count('class="roster-card"') == 3
    assert businesses.count('class="roster-card"') == 2
    assert social.count('class="roster-card"') == 3
    assert social.count('SMA CONTOH') == 6
    assert 'PEKERJAAN CONTOH' in social and 'Rp 0' in social
    assert 'SMA CONTOH' not in art and 'Rp ' not in art
    assert '9999999999991234' in art
    assert '8888888888885678' in client.get('/assignment/1/p/block').get_data(as_text=True)


def test_zero_empty_and_codes():
    assert display_value('pend_gaji', 0) == 'Rp 0'
    assert display_value('umur_ak', 0) == '0'
    assert display_value('pend_gaji', None).startswith('Belum terisi')
    assert display_value('usaha_online_value', '2') == 'Tidak (kode 2)'


def test_all_blocks_and_edge_cases(client):
    for pk in (1, 2, 3):
        assert client.get(f'/assignment/{pk}').status_code == 200
        for block in BLOCKS:
            response = client.get(f'/assignment/{pk}/{block}/block')
            assert response.status_code == 200, (pk, block)
    assert 'instrumen lain' in client.get('/assignment/2/ii/block').get_data(as_text=True)
    assert 'Isian root keluarga' in client.get('/assignment/3/sumber/block').get_data(as_text=True)
    assert 'dari 0 objek' in client.get('/sls/6502000000000002').get_data(as_text=True)


def test_search_filter_sort(client):
    assert client.get('/').get_data(as_text=True).count('class="region-card"') == 14
    assert client.get('/?q=tidak-ada').get_data(as_text=True).count('class="region-card"') == 0
    assert client.get('/sls/6502000000000001?kind=BKU').get_data(as_text=True).count('class="assignment-card"') == 1
    assert client.get('/sls/6502000000000001?q=KELUARGA').get_data(as_text=True).count('class="assignment-card"') == 1
    assert client.get('/sls/6502000000000001?q=10').get_data(as_text=True).count('class="assignment-card"') == 1
    assert client.get('/sls/6502000000000001?q=contoh-bku').get_data(as_text=True).count('class="assignment-card"') == 1
    assert client.get('/sls/6502000000000001?q=%25').status_code == 200
    assert client.get('/sls/6502000000000001?review=1').get_data(as_text=True).count('class="assignment-card"') == 2
    assert client.get('/sls/6502000000000001?sort=name').status_code == 200
    assert client.get('/sls/6502000000000001?existence=Kode+1').get_data(as_text=True).count('class="assignment-card"') == 2
    assert 'q=CONTOH' in client.get('/assignment/1?q=CONTOH').get_data(as_text=True)


def mutate_file(folder, filename, mutation):
    path = folder / filename
    wb = load_workbook(path); mutation(wb.active); wb.save(path); wb.close()


def test_duplicate_supplement_preserved_but_not_joined(app, source_dir):
    mutate_file(source_dir, 'PENDIDIKAN_PEKERJAAN_ART.xlsx', lambda ws: ws.append([c.value for c in ws[2]]))
    with app.app_context():
        report = import_dataset(source_dir)
        records = db.session.query(SourceRecord).filter_by(source='education', ambiguous=True).all()
        assert len(records) == 2 and report['duplicates']['education'] == 2
        assert db.session.query(Assignment).filter_by(id=1).one().members == 3
        assert db.session.query(SourceRecord).count() == report['stored_records']
        db.session.expire_all()
        assert db.session.get(Dataset, 1).report['stored_records'] == report['stored_records']


def test_bad_master_rolls_back(app, source_dir):
    mutate_file(source_dir, 'master_assignment.xlsx', lambda ws: ws.append([c.value for c in ws[2]]))
    with app.app_context():
        previous = db.session.get(Dataset, 1).fingerprint
        with pytest.raises(ValueError, match='ganda'):
            import_dataset(source_dir)
        assert db.session.get(Dataset, 1).fingerprint == previous
        assert db.session.query(Assignment).count() == 3


def test_unknown_region_rolls_back_transaction(app, source_dir):
    def mutation(ws):
        col = [c.value for c in ws[1]].index('level_6_full_code') + 1
        ws.cell(2, col).value = '999999'
    mutate_file(source_dir, 'master_assignment.xlsx', mutation)
    with app.app_context():
        previous = db.session.get(Dataset, 1).fingerprint
        with pytest.raises(ValueError, match='Kode SLS'):
            import_dataset(source_dir)
        assert db.session.get(Dataset, 1).fingerprint == previous
        assert db.session.query(Region).count() == 14
        assert db.session.query(Assignment).count() == 3


def test_unmatched_version_is_retained(app, source_dir):
    def mutation(ws):
        col = [c.value for c in ws[1]].index('assignment_date_modified') + 1
        ws.cell(2, col).value = '2026-01-01 00:00:00.000'
    mutate_file(source_dir, 'PENDAPATAN_PER_ART.xlsx', mutation)
    with app.app_context():
        report = import_dataset(source_dir)
        assert report['unmatched_records'] == 1
        assert db.session.query(SourceRecord).filter_by(source='income', assignment_pk=None).count() == 1


def test_missing_file_does_not_replace_dataset(app, source_dir):
    (source_dir / 'ASET_KELUARGA.xlsx').unlink()
    with app.app_context():
        with pytest.raises(ValueError, match='File wajib'):
            import_dataset(source_dir)
        assert db.session.query(Assignment).count() == 3


def test_coordinates_validation():
    assert valid_coordinates({'geotag_latitude': 2, 'geotag_longitude': 117})
    for lat, lon in [(0, 0), (91, 117), (2, 181), (float('nan'), 117), (None, 117), ('abc', 117)]:
        assert not valid_coordinates({'geotag_latitude': lat, 'geotag_longitude': lon})


def test_old_links_never_point_to_new_objects(app, client, source_dir):
    def mutation(ws):
        col = [c.value for c in ws[1]].index('assignment_id') + 1
        ws.cell(2, col).value = 'assignment-baru-contoh'
    mutate_file(source_dir, 'master_assignment.xlsx', mutation)
    with app.app_context():
        import_dataset(source_dir)
        new = db.session.query(Assignment).filter_by(source_id='assignment-baru-contoh').one()
        assert new.id > 3
        assert db.session.get(Assignment, 1) is None
    assert client.get('/assignment/1').status_code == 404


def test_historical_versions_and_orphan_supplement(app, source_dir):
    def mutation(ws):
        row = [c.value for c in ws[2]]
        row[[c.value for c in ws[1]].index('assignment_date_modified')] = '2026-01-01 00:00:00.000'
        ws.append(row)
    mutate_file(source_dir, 'master_assignment.xlsx', mutation)
    with app.app_context():
        report = import_dataset(source_dir)
        assert report['historical_assignments'] == 1
        versions = db.session.query(Assignment).filter_by(source_id='contoh-keluarga').all()
        assert len(versions) == 2 and sum(a.latest for a in versions) == 1


def test_unlabeled_codes_are_not_lost():
    from portal.presentation import fields
    result = fields({'ijazah_label': None, 'ijazah_value': '9'}, sensitive=True)
    assert len(result) == 1 and 'Kode 9' in result[0]['value']


def test_repeated_field_conflict_is_reported(app, source_dir):
    def mutation(ws):
        col = [c.value for c in ws[1]].index('jumlah_ak') + 1
        ws.cell(2, col).value = 8
    mutate_file(source_dir, 'identitas_keluarga.xlsx', mutation)
    with app.app_context():
        import_dataset(source_dir)
        a = db.session.get(Assignment, 1)
        assert any('sumber 8, roster 3' in issue for issue in a.issues)
        assert a.members == 3
