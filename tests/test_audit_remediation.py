import os
from unittest.mock import patch

import pytest
from werkzeug.security import generate_password_hash

from portal import create_app
from portal.auth import failed_login, throttle_keys
from portal.migrations import migrate_schema
from portal.models import db, User, AuditEvent, AuthSession
from portal.presentation import label


@pytest.mark.parametrize('value', ['1', 'true', 'yes', 'on', 'TRUE'])
def test_auth_true_values_require_login(value):
    with patch.dict(os.environ, {'AUTH_REQUIRED': value}):
        app = create_app({'TESTING': True, 'SECRET_KEY': 'test', 'SQLALCHEMY_DATABASE_URI': 'sqlite://'})
        assert app.config['AUTH_REQUIRED']


@pytest.mark.parametrize('value', ['', 'treu', '2', 'enabled'])
def test_invalid_auth_configuration_stops_startup(value):
    with patch.dict(os.environ, {'AUTH_REQUIRED': value}):
        with pytest.raises(ValueError, match='AUTH_REQUIRED'):
            create_app({'TESTING': True, 'SECRET_KEY': 'test', 'SQLALCHEMY_DATABASE_URI': 'sqlite://'})


def test_no_login_mode_refuses_non_loopback(app):
    app.config.update(TESTING=False, AUTH_REQUIRED=False)
    assert app.test_client().get('/', environ_overrides={'REMOTE_ADDR': '192.0.2.10'}).status_code == 403
    assert app.test_client().get('/').status_code == 200


def test_logout_revokes_copied_cookie_but_other_session_survives(app, client):
    old = client.get_cookie('session').value
    other = app.test_client()
    other.post('/login', data={'username': 'admin', 'password': 'test-strong-pass-2026'})
    other.post('/commitment', data={'decision': 'accept'})
    assert client.post('/logout').status_code == 302
    replay = app.test_client()
    replay.set_cookie('session', old)
    assert replay.get('/assignment/1/i/block').status_code == 403
    assert other.get('/assignment/1/i/block').status_code == 200
    with app.app_context():
        assert db.session.query(AuthSession).count() == 1
        assert db.session.query(AuditEvent).filter_by(event='logout').count() == 1


def test_shared_ip_does_not_lock_other_valid_account(app):
    client = app.test_client()
    for _ in range(8):
        assert client.post('/login', data={'username': 'admin', 'password': 'wrong'}).status_code == 200
    rejected = client.post('/login', data={'username': 'admin', 'password': 'test-strong-pass-2026'})
    assert rejected.status_code == 429 and int(rejected.headers['Retry-After']) > 0
    assert client.post('/login', data={'username': 'petugas', 'password': 'test-strong-pass-2026'}).status_code == 302
    assert client.post('/login', data={'username': 'admin', 'password': 'test-strong-pass-2026'}, environ_overrides={'REMOTE_ADDR': '127.0.0.2'}).status_code == 429


def test_ip_global_limit_is_not_removed_by_successful_login(app):
    import time
    with app.app_context():
        keys = throttle_keys('synthetic', '127.0.0.1')
        for _ in range(100):
            failed_login({'ip': keys['ip']}, time.time())
    response = app.test_client().post('/login', data={'username': 'admin', 'password': 'test-strong-pass-2026'})
    assert response.status_code == 429


def test_readiness_checks_schema_dataset_and_admin(app):
    empty = create_app({'TESTING': True, 'AUTH_REQUIRED': True, 'SECRET_KEY': 'test', 'SQLALCHEMY_DATABASE_URI': 'sqlite://'})
    assert empty.test_client().get('/health').status_code == 200
    assert empty.test_client().get('/ready').status_code == 503
    with app.app_context():
        migrate_schema()
    assert app.test_client().get('/ready').status_code == 200
    with app.app_context():
        db.session.query(User).filter_by(role='admin').update({'active': False})
        db.session.commit()
    assert app.test_client().get('/ready').status_code == 503


def test_asset_cache_separated_from_private_data(client):
    assert client.get('/assignment/1/iii/block').headers['Cache-Control'] == 'no-store'
    assert client.get('/static/controls.js?v=test').headers['Cache-Control'] == 'public, max-age=31536000, immutable'
    assert client.get('/static/controls.js').headers['Cache-Control'] == 'public, max-age=3600'


def test_verified_source_region_labels_and_builder():
    from scripts.build_metadata_catalog import OVERRIDES
    expected = {'level_3_name': 'Kecamatan', 'level_4_name': 'Desa/kelurahan', 'level_5_name': 'SLS', 'level_6_name': 'Sub-SLS'}
    assert {key: label(key) for key in expected} == expected
    assert {key: OVERRIDES[key] for key in expected} == expected


def test_mixed_case_accounts_and_open_redirect_are_handled(app):
    with app.app_context():
        db.session.add(User(username='Mixed@example.test', role='admin', password_hash=generate_password_hash('Synthetic-mixed-case!')))
        db.session.commit()
    for destination in ['https://example.test', '//example.test', '/\\example.test', '//[invalid']:
        response = app.test_client().post('/login', query_string={'next': destination}, data={'username': 'MIXED@example.test', 'password': 'Synthetic-mixed-case!'})
        assert response.status_code == 302 and response.location == '/'
    response = app.test_client().post('/login', query_string={'next': '/assignment/1#block-i'}, data={'username': 'Mixed@example.test', 'password': 'Synthetic-mixed-case!'})
    assert response.location == '/assignment/1#block-i'
