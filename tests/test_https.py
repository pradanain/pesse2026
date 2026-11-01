import re


def test_https_login_and_commitment_work_with_csrf_and_secure_cookies(app):
    app.config.update(WTF_CSRF_ENABLED=True, SESSION_COOKIE_SECURE=True)
    client = app.test_client()
    origin = 'https://pesse.databenuanta.id'
    response = client.get('/login', base_url=origin)
    assert response.headers['Referrer-Policy'] == 'same-origin'
    token = re.search(r'name="csrf_token" value="([^"]+)"', response.get_data(as_text=True)).group(1)
    data = {'csrf_token': token, 'username': 'admin', 'password': 'test-strong-pass-2026'}
    assert client.post('/login', data=data, base_url=origin).status_code == 400
    response = client.post('/login', data=data, base_url=origin, headers={'Referer': origin + '/login'})
    assert response.status_code == 302 and 'Secure' in response.headers['Set-Cookie']
    assert '/commitment?' in client.get('/', base_url=origin).location
    response = client.get('/commitment', base_url=origin)
    token = re.search(r'name="csrf_token" value="([^"]+)"', response.get_data(as_text=True)).group(1)
    response = client.post('/commitment', base_url=origin, headers={'Referer': origin + '/commitment'}, data={'csrf_token': token, 'decision': 'accept'})
    assert response.status_code == 302
    assert client.get('/', base_url=origin).status_code == 200
