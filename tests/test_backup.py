import sqlite3
import pytest
from scripts.backup_local import backup_database, verify_restore


def test_backup_restore_isolated_and_never_overwrites(tmp_path):
    source, target = tmp_path / 'source.db', tmp_path / 'backup.db'
    with sqlite3.connect(source) as conn:
        for table in ('user', 'region', 'assignment', 'source_record'):
            conn.execute(f'CREATE TABLE "{table}" (id INTEGER PRIMARY KEY, value TEXT)')
            conn.execute(f'INSERT INTO "{table}" VALUES (1, ?)', ('synthetic',))
    assert backup_database(source, target)['user'] == 1
    assert verify_restore(target)['source_record'] == 1
    with pytest.raises(ValueError):
        backup_database(source, target)
    with sqlite3.connect(source) as conn:
        assert conn.execute('SELECT value FROM "user"').fetchone()[0] == 'synthetic'
