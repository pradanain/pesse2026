"""Read-only production profiling plus isolated synthetic security probes.

Never outputs user emails, passwords, respondent data, SQL parameters, or URLs.
"""
import json
import os
import statistics
import sys
import time
import sqlite3
from contextlib import closing
from collections import Counter
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sqlalchemy import event
from werkzeug.security import generate_password_hash

from portal import create_app
from portal.auth import start_session
from portal.form_layout import BLOCKS
from portal.metadata import describe
from portal.models import db, User, Region, Assignment, SourceRecord

root = Path(__file__).resolve().parents[1]
report = {'date': '2026-11-01', 'scope': 'read-only local audit; synthetic authentication probes'}

settings = {}
for value in ('1', '0', 'true', 'yes', ''):
    with patch.dict(os.environ, {'AUTH_REQUIRED': value}):
        try:
            app = create_app({'TESTING': True, 'SECRET_KEY': 'audit-synthetic', 'SQLALCHEMY_DATABASE_URI': 'sqlite://'})
            settings[repr(value)] = app.config['AUTH_REQUIRED']
        except ValueError:
            settings[repr(value)] = 'rejected'
report['auth_configuration_probe'] = settings
empty_app = create_app({'TESTING': True, 'AUTH_REQUIRED': True, 'SECRET_KEY': 'audit-synthetic', 'SQLALCHEMY_DATABASE_URI': 'sqlite://'})
report['empty_schema_health_probe'] = {'health_status_without_tables': empty_app.test_client().get('/health').status_code, 'ready_status_without_tables': empty_app.test_client().get('/ready').status_code}

app = create_app({'TESTING': True, 'AUTH_REQUIRED': True, 'SECRET_KEY': 'audit-synthetic',
                  'SQLALCHEMY_DATABASE_URI': 'sqlite://', 'WTF_CSRF_ENABLED': False})
with app.app_context():
    db.create_all()
    for name in ('first@example.test', 'second@example.test'):
        db.session.add(User(username=name, password_hash=generate_password_hash('Synthetic-only-password!'), role='admin'))
    db.session.commit()
    client = app.test_client()
    failures = [client.post('/login', data={'username': 'first@example.test', 'password': 'incorrect-synthetic'}).status_code for _ in range(8)]
    blocked = client.post('/login', data={'username': 'second@example.test', 'password': 'Synthetic-only-password!'}).status_code
    other_ip = client.post('/login', data={'username': 'second@example.test', 'password': 'Synthetic-only-password!'}, environ_overrides={'REMOTE_ADDR': '127.0.0.2'}).status_code
    report['shared_ip_lockout_probe'] = {'failed_attempts': len(failures), 'valid_other_account_same_ip_status': blocked,
                                         'valid_other_account_other_ip_status': other_ip}
    old_cookie = client.get_cookie('session').value
    client.post('/logout')
    replay = app.test_client()
    replay.set_cookie('session', old_cookie)
    report['logout_cookie_replay_probe'] = {'normal_client_after_logout': client.get('/').status_code,
                                             'copied_prelogout_cookie': replay.get('/').status_code,
                                             'scope': 'isolated synthetic users; no production cookies copied'}
    mixed = User(username='Mixed@example.test', role='admin', password_hash=generate_password_hash('Synthetic-only-password!'))
    db.session.add(mixed)
    db.session.commit()
    mixed_response = app.test_client().post('/login', data={'username': mixed.username, 'password': 'Synthetic-only-password!'}, environ_overrides={'REMOTE_ADDR': '127.0.0.3'})
    report['mixed_case_account_probe'] = {'login_status_with_correct_password': mixed_response.status_code,
                                         'generic_login_error': 'tidak sesuai' in mixed_response.get_data(as_text=True)}
    db.session.remove()
    db.engine.dispose()

app = create_app({'AUTH_REQUIRED': True, 'TESTING': True, 'SECRET_KEY': 'isolated-audit-snapshot-only', 'SQLALCHEMY_DATABASE_URI': 'sqlite://'})
with app.app_context():
    # Profile an in-memory snapshot. Authentication/audit writes never touch production.
    with closing(sqlite3.connect(f'file:{(root / "instance/portal.sqlite3").as_posix()}?mode=ro', uri=True)) as source:
        connection = db.engine.raw_connection()
        try:
            source.backup(connection.driver_connection)
        finally:
            connection.close()
    admin = db.session.query(User).filter_by(role='admin', active=True).one()
    records = db.session.query(SourceRecord).filter_by(source='master').all()
    regions = {r.code: r for r in db.session.query(Region)}
    comparisons = Counter()
    for record in records:
        region = regions.get(str(record.raw.get('level_6_full_code', '')))
        if not region:
            continue
        for key in ('level_3_name', 'level_4_name', 'level_5_name', 'level_6_name'):
            value = record.raw.get(key)
            if value in (None, ''):
                continue
            comparisons[key + '_present'] += 1
            for name, expected in [('district', region.district), ('village', region.village), ('sls', region.name)]:
                if str(value).strip().casefold() == str(expected).strip().casefold():
                    comparisons[key + '_equals_' + name] += 1
    report['geography_label_probe'] = {'labels': {key: describe(key).get('label') for key in ('level_3_name', 'level_4_name', 'level_5_name', 'level_6_name')},
                                        'counts_only': dict(comparisons)}
    report['data_counts'] = {'regions': len(regions), 'active_assignments': db.session.query(Assignment).filter_by(latest=True).count(),
                              'source_rows': db.session.query(SourceRecord).count()}
    selected = db.session.query(Assignment).filter_by(latest=True).order_by(Assignment.members.desc(), Assignment.businesses.desc()).first()
    report['profile_fixture_roster_counts'] = {'members': selected.members, 'businesses': selected.businesses}
    client = app.test_client()
    with app.test_request_context():
        from flask import session
        start_session(admin)
        cookie_session = dict(session)
    with client.session_transaction() as session:
        session.update(cookie_session)
        from portal.commitment import VERSION
        session['privacy_commitment'] = VERSION
    query_counter = [0]

    def count_query(*args):
        query_counter[0] += 1

    event.listen(db.engine, 'before_cursor_execute', count_query)
    paths = {'regions': '/', 'assignment_list': '/sls/' + selected.region,
             'detail_shell': f'/assignment/{selected.id}', 'member_identity': f'/assignment/{selected.id}/i/block',
             'business_block': f'/assignment/{selected.id}/ii/block', 'member_social': f'/assignment/{selected.id}/iii/block',
             'household_block': f'/assignment/{selected.id}/iv/block'}
    timings = {}
    for name, path in paths.items():
        samples, sql_counts = [], []
        for _ in range(6):
            db.session.remove()
            query_counter[0] = 0
            start = time.perf_counter()
            response = client.get(path)
            elapsed = (time.perf_counter() - start) * 1000
            assert response.status_code == 200
            samples.append(elapsed)
            sql_counts.append(query_counter[0])
        timings[name] = {'cold_ms': round(samples[0], 2), 'warm_median_ms': round(statistics.median(samples[1:]), 2),
                         'sql_count': sql_counts[-1], 'response_bytes': len(response.data)}
    report['local_test_client_profile'] = timings
    asset = client.get('/static/images/pelatihan-pes-se2026-web.jpg?v=web1')
    report['asset_headers'] = {'photo_bytes': len(asset.data), 'cache_control': asset.headers.get('Cache-Control'),
                                'etag_present': 'ETag' in asset.headers}
    report['schema_indexes'] = {name: [row[1] for row in db.session.execute(db.text(f'PRAGMA index_list({name})'))]
                                for name in ('assignment', 'source_record')}
    event.remove(db.engine, 'before_cursor_execute', count_query)
    db.session.remove()
    db.engine.dispose()

report['source_metrics'] = {p.name: {'lines': len(p.read_text(encoding='utf-8').splitlines()), 'bytes': p.stat().st_size}
                           for p in [root / 'portal/static/app.css', root / 'portal/static/app.js', root / 'portal/static/controls.js', root / 'portal/static/block-viewer.js']}
target = root / 'docs/IMPLEMENTATION_METRICS_2026-11-01.json'
target.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
print(json.dumps(report, ensure_ascii=True, indent=2))
