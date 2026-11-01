"""Initial local setup; strong random admin password is never printed to logs."""
import secrets
from pathlib import Path

from werkzeug.security import generate_password_hash

from portal import create_app
from portal.importer import import_dataset
from portal.models import db, User

if __name__ == '__main__':
    root = Path(__file__).resolve().parent
    app = create_app()
    with app.app_context():
        from portal.migrations import migrate_schema
        migrate_schema()
        report = import_dataset(root, root / 'docs')
        if app.config['AUTH_REQUIRED'] and not db.session.query(User).filter_by(role='admin').first():
            password = secrets.token_urlsafe(24)
            username = 'admin-lokal'
            db.session.add(User(username=username, role='admin', sensitive=True, password_hash=generate_password_hash(password)))
            db.session.commit()
            private = root / 'private'
            private.mkdir(exist_ok=True)
            target = private / 'akses_awal.txt'
            target.write_text('Akses lokal SE2026\nhttp://127.0.0.1:6502\nNama pengguna: ' + username + '\nKata sandi: ' + password + '\n\nSimpan secara terbatas. Hapus file ini setelah kredensial disimpan aman.\nGanti kata sandi: python -m flask --app wsgi set-password admin-lokal\n', encoding='utf-8')
            target.chmod(0o600)
            print('Akun admin acak dibuat. Kredensial: private/akses_awal.txt (jangan dibagikan).')
        print(f"Siap: {report['regions']} SLS, {report['active_assignments']} assignment, {report['stored_records']} baris sumber.")
