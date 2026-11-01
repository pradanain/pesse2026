"""Isolated Docker/Traefik deployment rehearsal, using synthetic data only."""
import hashlib
import http.cookies
import json
import os
import secrets
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.parse
import urllib.request
from pathlib import Path

root = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(root), str(root / 'tests')]
from conftest import create_workbooks
from portal import create_app
from portal.migrations import migrate_schema
from portal.importer import import_dataset
from portal.models import db, User
from werkzeug.security import generate_password_hash


def run(*args, **kwargs):
    return subprocess.run(args, check=True, text=True, capture_output=True, **kwargs).stdout


with tempfile.TemporaryDirectory(prefix='pes-deploy-qa-') as folder:
    temp = Path(folder)
    seed = temp / 'private/seed'; seed.mkdir(parents=True)
    (temp / 'private/backups').mkdir()
    workbooks = create_workbooks(temp / 'excel')
    app = create_app({'TESTING': True, 'SECRET_KEY': 'isolated-deploy-qa',
                      'SQLALCHEMY_DATABASE_URI': 'sqlite:///' + (seed / 'portal.sqlite3').as_posix()})
    with app.app_context():
        migrate_schema(); import_dataset(workbooks)
        db.session.add(User(username='qa@example.test', role='admin', active=True,
                            password_hash=generate_password_hash('Synthetic-deploy-only!')))
        db.session.commit(); db.session.remove(); db.engine.dispose()
    (seed / 'secret.key').write_text(secrets.token_hex(32))
    (seed / 'manifest.json').write_text(json.dumps({'sha256': {name: hashlib.sha256((seed / name).read_bytes()).hexdigest()
        for name in ('portal.sqlite3', 'secret.key')}}))
    shutil.copyfile(root / 'compose.server.yml', temp / 'compose.server.yml')
    network = 'pes-deploy-qa-proxy'
    override = {'services': {'portal': {'labels': {'pes.qa': 'deployment'}}, 'traefik-qa': {
        'image': 'traefik:v3.6', 'command': ['--providers.docker=true', '--providers.docker.exposedbydefault=false',
        '--providers.docker.constraints=Label(`pes.qa`, `deployment`)', '--entrypoints.web.address=:80'],
        'ports': ['127.0.0.1:6504:80'], 'networks': ['proxy'],
        'volumes': ['/var/run/docker.sock:/var/run/docker.sock:ro'], 'labels': {'traefik.enable': 'false'}}}}
    (temp / 'qa.json').write_text(json.dumps(override))
    env = {**os.environ, 'PORTAL_IMAGE': 'pesse-se2026:local', 'TRAEFIK_NETWORK': network, 'TRAEFIK_ENTRYPOINT': 'web'}
    compose = ['docker', 'compose', '-p', 'pesse_deploy_qa', '-f', str(temp / 'compose.server.yml'), '-f', str(temp / 'qa.json')]
    run('docker', 'network', 'create', network)
    try:
        run('docker', 'pull', 'traefik:v3.6')
        run(*compose, 'up', '-d', '--no-build', '--pull', 'never', '--wait', '--wait-timeout', '120', env=env)
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *args):
                return None
        opener = urllib.request.build_opener(NoRedirect)
        cookie = ''
        def request(path, data=None):
            headers = {'Host': 'pesse.databenuanta.id'}
            if data is not None:
                headers['Referer'] = 'https://pesse.databenuanta.id/login'
            if cookie:
                headers['Cookie'] = cookie
            req = urllib.request.Request('http://127.0.0.1:6504' + path,
                data=urllib.parse.urlencode(data).encode() if data is not None else None, headers=headers)
            try:
                return opener.open(req, timeout=15)
            except urllib.error.HTTPError as response:
                return response
        import re
        for _ in range(30):
            response = request('/login')
            if response.status == 200:
                break
            response.close()
            time.sleep(.5)
        assert response.status == 200, f'Origin login status: {response.status}'
        assert response.headers['Referrer-Policy'] == 'same-origin'
        html = response.read().decode()
        cookie = response.headers['Set-Cookie'].split(';')[0]
        token = re.search(r'name="csrf_token" value="([^"]+)"', html).group(1)
        response = request('/login', {'csrf_token': token, 'username': 'qa@example.test', 'password': 'Synthetic-deploy-only!'})
        assert response.status == 302 and response.headers['Location'] == '/', f'Login POST status: {response.status}'
        assert 'Secure' in response.headers['Set-Cookie'] and 'HttpOnly' in response.headers['Set-Cookie']
        cookie = response.headers['Set-Cookie'].split(';')[0]
        response = request('/')
        assert response.status == 302 and response.headers['Location'].startswith('/commitment')
        assert request('/assignment/1/i/block').status == 403
        response = request('/commitment')
        if response.headers.get('Set-Cookie'):
            cookie = response.headers['Set-Cookie'].split(';')[0]
        html = response.read().decode()
        assert 'Komitmen kerahasiaan data' in html
        token = re.search(r'name="csrf_token" value="([^"]+)"', html).group(1)
        response = request('/commitment', {'csrf_token': token, 'decision': 'accept'})
        assert response.status == 302, f'Commitment POST status: {response.status}'
        cookie = response.headers['Set-Cookie'].split(';')[0]
        assert request('/assignment/1/i/block').status == 200
        assert request('/ready').status == 200
        # Existing volume must survive seed removal and repeat initialization.
        fingerprint = run(*compose, 'exec', '-T', 'portal', 'python', '-c',
            "import sqlite3,hashlib; c=sqlite3.connect('/app/instance/portal.sqlite3'); print(hashlib.sha256(repr(c.execute('SELECT id,password_hash FROM user ORDER BY id').fetchall()).encode()).hexdigest())", env=env).strip()
        (seed / 'manifest.json').unlink()
        run(*compose, 'run', '--rm', 'initialize', env=env)
        after = run(*compose, 'exec', '-T', 'portal', 'python', '-c',
            "import sqlite3,hashlib; c=sqlite3.connect('/app/instance/portal.sqlite3'); print(hashlib.sha256(repr(c.execute('SELECT id,password_hash FROM user ORDER BY id').fetchall()).encode()).hexdigest())", env=env).strip()
        assert fingerprint == after
        for _ in range(20):
            if list((temp / 'private/backups').glob('*.sqlite3')):
                break
            time.sleep(.5)
        assert list((temp / 'private/backups').glob('*.sqlite3'))
        logs = run(*compose, 'logs', '--no-color', 'backup', env=env)
        assert 'pemeriksaan restore berhasil' in logs
        print(json.dumps({'traefik_port80_routing': 'passed', 'secure_cookie_csrf_commitment_login': 'passed',
                          'readiness': 'passed', 'repeat_init_preserves_passwords': 'passed',
                          'automatic_backup_restore_check': 'passed', 'data': 'synthetic only'}))
    except Exception:
        print(run(*compose, 'logs', '--tail', '30', env=env), file=sys.stderr)
        raise
    finally:
        run(*compose, 'down', '-v', '--remove-orphans', env=env)
        run('docker', 'network', 'rm', network)
