"""Initialize a named volume from a separately transferred private seed, once."""
import hashlib
import json
import os
import shutil
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, '/app')
runtime = Path('/app/instance')
seed = Path('/seed')
runtime.mkdir(parents=True, exist_ok=True)
database, secret = runtime / 'portal.sqlite3', runtime / 'secret.key'
if database.exists() != secret.exists():
    raise SystemExit('Volume tidak lengkap. Pulihkan pasangan database dan secret; init tidak menimpanya.')
if not database.exists():
    manifest = json.loads((seed / 'manifest.json').read_text())
    for name in ('portal.sqlite3', 'secret.key'):
        source = seed / name
        if hashlib.sha256(source.read_bytes()).hexdigest() != manifest['sha256'][name]:
            raise SystemExit('Checksum seed tidak sesuai.')
    with sqlite3.connect(f'file:{seed / "portal.sqlite3"}?mode=ro', uri=True) as conn:
        if conn.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            raise SystemExit('Seed database tidak valid.')
    for name in ('portal.sqlite3', 'secret.key'):
        shutil.copyfile(seed / name, runtime / name)
        os.chmod(runtime / name, 0o600)
for path in (runtime, database, secret):
    os.chown(path, 10001, 10001)
backups = Path('/backups')
backups.mkdir(parents=True, exist_ok=True)
os.chown(backups, 10001, 10001)
os.setgid(10001)
os.setuid(10001)
from portal import create_app
from portal.migrations import migrate_schema
from portal.models import db, Dataset, Region, User

app = create_app()
with app.app_context():
    migrate_schema()
    if not db.session.get(Dataset, 1) or not db.session.query(Region).first() or not db.session.query(User).filter_by(role='admin', active=True).first():
        raise SystemExit('Dataset atau akun admin belum siap.')
print('Volume siap; data dan password dipertahankan.', flush=True)
