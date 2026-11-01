"""Consistent local SQLite backup and restore rehearsal; no respondent output."""
import argparse
import json
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory


def verify_restore(backup):
    with TemporaryDirectory() as folder:
        restored = Path(folder) / 'restored.sqlite3'
        with closing(sqlite3.connect(f'file:{Path(backup).as_posix()}?mode=ro', uri=True)) as source, closing(sqlite3.connect(restored)) as dest:
            source.backup(dest)
            if dest.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                raise ValueError('Integritas backup tidak valid.')
            tables = {row[0] for row in dest.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if not {'user', 'region', 'assignment', 'source_record'}.issubset(tables):
                raise ValueError('Backup tidak memiliki tabel portal yang lengkap.')
            counts = {table: dest.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
                      for table in ('user', 'region', 'assignment', 'source_record')}
        return counts


def backup_database(source, destination):
    source, destination = Path(source).resolve(), Path(destination).resolve()
    if not source.is_file() or destination.exists():
        raise ValueError('Sumber tidak ada atau tujuan sudah ada.')
    destination.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(f'file:{source.as_posix()}?mode=ro', uri=True)) as src, closing(sqlite3.connect(destination)) as dest:
        src.backup(dest)
    return verify_restore(destination)


if __name__ == '__main__':
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=root / 'instance/portal.sqlite3')
    parser.add_argument('--directory', type=Path, default=root.parent / 'Backups')
    parser.add_argument('--verify', type=Path)
    args = parser.parse_args()
    if args.verify:
        counts = verify_restore(args.verify)
    else:
        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        target = args.directory / f'portal-{stamp}.sqlite3'
        counts = backup_database(args.source, target)
    print(json.dumps({'backup_verified': True, 'restored_counts': counts}))
