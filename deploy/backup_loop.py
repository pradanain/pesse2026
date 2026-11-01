"""Daily consistent database backup and isolated restore verification."""
import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, '/app/scripts')
from backup_local import backup_database

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
while True:
    try:
        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        backup_database('/app/instance/portal.sqlite3', Path('/backups') / f'portal-{stamp}.sqlite3')
        logging.info('Backup database dan pemeriksaan restore berhasil.')
    except Exception:
        logging.error('Backup gagal; periksa volume sumber dan kapasitas penyimpanan.')
        sys.exit(1)
    time.sleep(86400)
