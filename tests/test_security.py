import re

from portal.models import db, User
from portal.form_layout import BLOCKS, ACTIVE_BLOCKS


def login_as(client, name):
    client.post('/logout')
    response = client.post('/login', data={'username': name, 'password': 'test-strong-pass-2026'})
    client.post('/commitment', data={'decision': 'accept'})
    return response


def test_every_data_endpoint_requires_login(app):
    c = app.test_client()
    for path in ['/', '/dataset', '/sls/6502000000000001', '/assignment/1', '/assignment/1/p/block']:
        assert c.get(path).status_code in (302, 403)
    assert c.get('/health').json == {'status': 'ok'}
    assert c.get('/master_assignment.xlsx').status_code == 404
    assert c.get('/private/akses_awal.txt').status_code == 404


def test_region_authorization_and_sensitive_fields(client):
    login_as(client, 'petugas')
    assert client.get('/').get_data(as_text=True).count('class="region-card"') == 1
    assert client.get('/sls/6502000000000002').status_code == 404
    assert client.get('/dataset').status_code == 403
    assert client.get('/assignment/1/catatan/block').status_code == 403
    assert client.get('/assignment/1/pemberi/block').status_code == 403
    for block in ('p', 'i', 'ii', 'iii', 'iv', 'sumber'):
        html = client.get(f'/assignment/1/{block}/block').get_data(as_text=True)
        assert 'Rp ' not in html and 'CATATAN RAHASIA' not in html
    login_as(client, 'terbatas')
    assert client.get('/assignment/1').status_code == 404
    for block in BLOCKS:
        assert client.get(f'/assignment/1/{block}/block').status_code == 404
    login_as(client, 'berizin')
    reference = client.get('/assignment/1/iv/block').get_data(as_text=True)
    assert 'Rp 1 juta – kurang dari Rp 5 juta' in reference
    assert 'Rp 2.500.000' not in reference and '2500000' not in reference


def test_csrf_and_rate_limit(app):
    app.config['WTF_CSRF_ENABLED'] = True
    c = app.test_client()
    assert c.post('/login', data={'username': 'admin', 'password': 'test-strong-pass-2026'}).status_code == 400
    for _ in range(8):
        html = c.get('/login').get_data(as_text=True)
        token = re.search(r'name="csrf_token" value="([^"]+)"', html).group(1)
        assert c.post('/login', data={'csrf_token': token, 'username': 'admin', 'password': 'incorrect'}).status_code == 200
    assert c.post('/login', data={'csrf_token': token, 'username': 'admin', 'password': 'test-strong-pass-2026'}).status_code == 429


def test_safe_headers_and_cookie_flags(client):
    response = client.get('/')
    assert response.headers['Cache-Control'] == 'no-store'
    assert response.headers['Referrer-Policy'] == 'no-referrer'
    assert "frame-ancestors 'none'" in response.headers['Content-Security-Policy']
    assert 'HttpOnly' in response.headers.get('Set-Cookie', '')
    assert 'SameSite=Lax' in response.headers.get('Set-Cookie', '')


def test_detail_loads_no_rosters_before_open(client):
    html = client.get('/assignment/1').get_data(as_text=True)
    assert 'ANGGOTA CONTOH' not in html and 'Rp 2.500.000' not in html
    assert html.count('data-block=') == len(ACTIVE_BLOCKS)
    assert html.count('data-section=') == len(BLOCKS)


def test_html_escaped(client, app):
    from portal.models import Assignment
    with app.app_context():
        db.session.get(Assignment, 1).name = '<script>alert(1)</script>'
        db.session.commit()
    html = client.get('/assignment/1').get_data(as_text=True)
    assert '<script>alert(1)</script>' not in html and '&lt;script&gt;' in html
