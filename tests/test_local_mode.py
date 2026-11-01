from portal import create_app
from portal.models import db, User, Grant
from portal.form_layout import BLOCKS


def test_default_configuration_requires_login(monkeypatch):
    monkeypatch.delenv('AUTH_REQUIRED', raising=False)
    app = create_app({'TESTING': True, 'SECRET_KEY': 'local-mode-test', 'SQLALCHEMY_DATABASE_URI': 'sqlite://'})
    assert app.config['AUTH_REQUIRED'] is True


def test_local_mode_all_pages_and_blocks_without_user_table(app):
    app.config['AUTH_REQUIRED'] = False
    # Prove that local viewing no longer depends on the old login tables at all.
    with app.app_context():
        Grant.__table__.drop(db.engine)
        User.__table__.drop(db.engine)
    c = app.test_client()
    for path in ('/', '/dataset', '/sls/6502000000000001', '/assignment/1'):
        response = c.get(path)
        assert response.status_code == 200
        assert 'name="password"' not in response.get_data(as_text=True)
        assert '>Keluar<' not in response.get_data(as_text=True)
    for block in BLOCKS:
        assert c.get(f'/assignment/1/{block}/block').status_code == 200
    assert c.get('/login').status_code == 302
    assert c.get('/login').location == '/'
    assert c.get('/static/images/logo-se2026.jpg').status_code == 200
    assert c.get('/master_assignment.xlsx').status_code == 404
    assert c.get('/private/akses_awal.txt').status_code == 404


def test_stale_login_session_does_not_affect_local_mode(app):
    app.config['AUTH_REQUIRED'] = False
    c = app.test_client()
    with c.session_transaction() as session:
        session['user_id'] = {'invalid': 'legacy-cookie'}
    assert c.get('/').status_code == 200
    assert c.get('/assignment/1/i/block').status_code == 200
