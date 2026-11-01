from portal.models import db, AuditEvent
from portal.commitment import EVENT


def sign_in(app):
    client = app.test_client()
    assert client.post('/login', data={'username': 'admin', 'password': 'test-strong-pass-2026'}).status_code == 302
    return client


def test_commitment_gates_data_until_explicit_acceptance(app):
    client = sign_in(app)
    for path in ('/', '/assignment/1', '/dataset', '/sls/6502000000000001'):
        response = client.get(path)
        assert response.status_code == 302 and '/commitment?' in response.location
        assert b'KELUARGA CONTOH' not in response.data
    assert client.get('/assignment/1/i/block').status_code == 403
    assert client.get('/', headers={'X-Portal-Request': '1'}).status_code == 403
    html = client.get('/commitment').get_data(as_text=True)
    assert 'Komitmen kerahasiaan data' in html and 'KELUARGA CONTOH' not in html
    assert client.post('/commitment').status_code == 400
    assert client.get('/').status_code == 302
    assert client.post('/commitment', data={'decision': 'accept'}).location == '/'
    assert client.get('/').status_code == 200
    assert client.get('/assignment/1/i/block').status_code == 200
    assert client.get('/commitment').status_code == 302
    client.post('/commitment', data={'decision': 'accept'})
    with app.app_context():
        assert db.session.query(AuditEvent).filter_by(event=EVENT).count() == 1


def test_new_login_requires_fresh_commitment_and_cancel_logs_out(app):
    client = sign_in(app)
    client.post('/commitment', data={'decision': 'accept'})
    client.post('/logout')
    client.post('/login', data={'username': 'admin', 'password': 'test-strong-pass-2026'})
    assert '/commitment?' in client.get('/').location
    cookie = client.get_cookie('session').value
    assert client.post('/logout').location == '/login'
    replay = app.test_client()
    replay.set_cookie('session', cookie)
    assert replay.get('/assignment/1/i/block').status_code == 403


def test_commitment_return_path_and_csrf(app):
    client = sign_in(app)
    app.config['WTF_CSRF_ENABLED'] = True
    assert client.post('/commitment', data={'decision': 'accept'}).status_code == 400
    assert '/commitment?' in client.get('/').location
    app.config['WTF_CSRF_ENABLED'] = False
    response = client.post('/commitment?next=//example.test', data={'decision': 'accept'})
    assert response.location == '/'
    second = sign_in(app)
    assert second.post('/commitment?next=/assignment/1%23block-i', data={'decision': 'accept'}).location == '/assignment/1#block-i'
