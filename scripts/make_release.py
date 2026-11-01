"""Build separate public source and PRIVATE ready-to-run seed archives."""
import hashlib
import json
import secrets
import shutil
import sqlite3
import subprocess
import tarfile
import zipfile
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path


def create_release(root, destination):
    root, destination = Path(root).resolve(), Path(destination).resolve()
    destination.mkdir(parents=True, exist_ok=False)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    source_zip = destination / f'PESSE2026-GITHUB-{stamp}.zip'
    roots = ['portal', 'deploy', 'scripts', 'tests', '.github']
    files = ['Dockerfile', '.dockerignore', '.gitignore', '.env.example', 'deploy.env.example',
             'compose.yml', 'compose.traefik.yml', 'compose.server.yml', 'deploy.sh', 'wsgi.py',
             'run_local.py', 'setup_local.py', 'start.ps1', 'README.md', 'docs/DEPLOY_SERVER.md',
             'requirements.txt', 'requirements-dev.txt', 'requirements.lock.txt', 'requirements-dev.lock.txt']
    selected = [root / name for name in files]
    for name in roots:
        selected.extend(p for p in (root / name).rglob('*') if p.is_file() and '__pycache__' not in p.parts)
    with zipfile.ZipFile(source_zip, 'w', zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(set(selected)):
            if not path.is_file():
                raise ValueError(f'Required source file missing: {path.name}')
            relative = path.relative_to(root)
            if path.suffix.casefold() in ('.xlsx', '.sqlite3', '.key') or path.name == '.env':
                raise ValueError('Private file blocked from public source archive.')
            archive.write(path, relative.as_posix())
    staging = destination / 'PRIVATE'
    seed = staging / 'private/seed'
    seed.mkdir(parents=True)
    database = seed / 'portal.sqlite3'
    with closing(sqlite3.connect(f'file:{(root / "instance/portal.sqlite3").as_posix()}?mode=ro', uri=True)) as source, closing(sqlite3.connect(database)) as target:
        source.backup(target)
        baseline = source.execute('SELECT id, password_hash, role, active FROM "user" ORDER BY id').fetchall()
        target.execute('DELETE FROM auth_session')
        target.execute('DELETE FROM login_attempt')
        target.commit()
        assert target.execute('SELECT id, password_hash, role, active FROM "user" ORDER BY id').fetchall() == baseline
        assert target.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
        counts = {table: target.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
                  for table in ('user', 'region', 'assignment', 'source_record')}
    (seed / 'secret.key').write_text(secrets.token_hex(32), encoding='utf-8')
    manifest = {'created_utc': stamp, 'counts': counts, 'sha256': {
        name: hashlib.sha256((seed / name).read_bytes()).hexdigest() for name in ('portal.sqlite3', 'secret.key')}}
    (seed / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
    shutil.copyfile(root / 'private/akun_petugas_PES_SE2026.xlsx', staging / 'private/akun_petugas_PES_SE2026.xlsx')
    (staging / 'private/backups').mkdir()
    private_tar = destination / f'PESSE2026-PRIVATE-SERVER-{stamp}.tar.gz'
    with tarfile.open(private_tar, 'w:gz') as archive:
        for path in sorted((staging / 'private').rglob('*')):
            info = archive.gettarinfo(str(path), path.relative_to(staging).as_posix())
            info.mode = 0o700 if path.is_dir() else 0o600
            info.uid = info.gid = 0
            info.uname = info.gname = ''
            if path.is_file():
                with path.open('rb') as stream:
                    archive.addfile(info, stream)
            else:
                archive.addfile(info)
    server = destination / 'SERVER-READY'
    server.mkdir()
    with zipfile.ZipFile(source_zip) as archive:
        archive.extractall(server)
    shutil.copytree(staging / 'private', server / 'private')
    (server / 'images').mkdir()
    subprocess.run(['docker', 'save', '-o', str(server / 'images/portal-amd64.tar'),
                    'ghcr.io/pradanain/pesse2026:latest'], check=True)
    server_tar = destination / f'PESSE2026-SERVER-READY-AMD64-{stamp}.tar.gz'
    with tarfile.open(server_tar, 'w:gz') as archive:
        for path in sorted(server.rglob('*')):
            if not path.is_file():
                continue
            info = archive.gettarinfo(str(path), path.relative_to(server).as_posix())
            info.mode = 0o600 if 'private' in path.relative_to(server).parts else 0o644
            info.uid = info.gid = 0
            info.uname = info.gname = ''
            with path.open('rb') as stream:
                archive.addfile(info, stream)
    output = {'public_source': source_zip.name, 'private_server': private_tar.name, 'counts': counts,
              'ready_server_amd64': server_tar.name,
              'sha256': {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in (source_zip, private_tar, server_tar)}}
    (destination / 'RELEASE.json').write_text(json.dumps(output, indent=2) + '\n', encoding='utf-8')
    return output


if __name__ == '__main__':
    root = Path(__file__).resolve().parents[1]
    destination = root / 'dist' / datetime.now(timezone.utc).strftime('release-%Y%m%dT%H%M%SZ')
    result = create_release(root, destination)
    print(json.dumps({'directory': str(destination), **result}, indent=2))
