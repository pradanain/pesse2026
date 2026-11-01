import json
from pathlib import Path

import click
from sqlalchemy import func
from werkzeug.security import generate_password_hash

from .models import db, User, Region, Grant, Supervision
from .auth import revoke_sessions, event


def register_cli(app):
    @app.cli.command('migrate-db')
    def migrate_db():
        from .migrations import migrate_schema
        migrate_schema()
        click.echo('Migrasi schema aditif selesai; akun dan data sumber dipertahankan.')

    @app.cli.command('update-allocations')
    @click.argument('filename', type=click.Path(exists=True, dir_okay=False))
    @click.option('--apply', is_flag=True, help='Tanpa opsi ini hanya menampilkan ringkasan perubahan.')
    def update_allocations(filename, apply):
        from .allocations import read_allocations
        try:
            plan = read_allocations(filename, {r.code for r in db.session.query(Region)})
            users = {u.username.strip().casefold(): u for u in db.session.query(User).filter(User.role.in_(('ppl', 'pml')))}
            if any(email not in users or users[email].role != role for role, allocation in [('ppl', plan.ppl), ('pml', plan.pml)] for email in allocation):
                raise ValueError('Ada akun baru/peran berbeda; siapkan akun tersebut sebelum memperbarui alokasi.')
            ids = [u.id for u in users.values()]
            old_grants = {(r.user_id, r.region) for r in db.session.query(Grant).filter(Grant.user_id.in_(ids))}
            new_grants = {(users[email].id, region) for email, regions in plan.ppl.items() for region in regions}
            old_teams = {(r.pml_id, r.ppl_id) for r in db.session.query(Supervision)}
            new_teams = {(users[pml].id, users[ppl].id) for pml, enumerators in plan.pml.items() for ppl in enumerators}
            summary = {**plan.summary(), 'grants_added': len(new_grants - old_grants), 'grants_removed': len(old_grants - new_grants),
                       'teams_added': len(new_teams - old_teams), 'teams_removed': len(old_teams - new_teams), 'applied': apply}
            if apply:
                db.session.query(Grant).filter(Grant.user_id.in_(ids)).delete(synchronize_session=False)
                db.session.query(Supervision).delete(synchronize_session=False)
                for user_id, region in new_grants:
                    db.session.add(Grant(user_id=user_id, region=region))
                for pml, ppl in new_teams:
                    db.session.add(Supervision(pml_id=pml, ppl_id=ppl))
                for email, user in users.items():
                    user.active = email in plan.ppl or email in plan.pml
                    revoke_sessions(user.id)
                event('allocations_updated')
                db.session.commit()
            click.echo(json.dumps(summary))
        except (ValueError, OSError) as error:
            db.session.rollback()
            raise click.ClickException(str(error)) from None

    @app.cli.command('shorten-staff-passwords')
    @click.option('--credentials-file', default='private/akun_petugas_PES_SE2026.xlsx', type=click.Path(exists=True, dir_okay=False))
    def shorten_passwords(credentials_file):
        from .allocations import shorten_staff_passwords
        try:
            click.echo(json.dumps(shorten_staff_passwords(credentials_file)))
        except (ValueError, OSError) as error:
            raise click.ClickException(str(error)) from None

    @app.cli.command('import-allocations')
    @click.argument('filename', type=click.Path(exists=True, dir_okay=False))
    @click.option('--check', is_flag=True, help='Periksa alokasi tanpa membuat akun.')
    @click.option('--admin-email', default=None)
    @click.option('--credentials-file', default='private/akun_petugas_PES_SE2026.xlsx', type=click.Path())
    def import_allocations(filename, check, admin_email, credentials_file):
        from .allocations import read_allocations, provision_accounts
        try:
            plan = read_allocations(filename, {r.code for r in db.session.query(Region)})
            if check:
                click.echo(json.dumps(plan.summary(), ensure_ascii=False))
                return
            if not admin_email:
                admin_email = click.prompt('Email admin')
            password = click.prompt('Password admin', hide_input=True, confirmation_prompt=True)
            db.create_all()
            summary = provision_accounts(plan, admin_email, password, credentials_file)
            click.echo(json.dumps(summary, ensure_ascii=False))
            click.echo('Kredensial petugas tersimpan pada berkas distribusi lokal; tidak ditampilkan di log.')
        except (ValueError, OSError) as error:
            raise click.ClickException(str(error)) from None

    @app.cli.command('init-db')
    def init_db():
        from .migrations import migrate_schema
        migrate_schema()
        click.echo('Database siap.')

    @app.cli.command('import-excel')
    @click.argument('directory', type=click.Path(exists=True, file_okay=False))
    @click.option('--report-dir', default='docs', type=click.Path())
    def import_excel(directory, report_dir):
        from .importer import import_dataset
        try:
            report = import_dataset(directory, report_dir)
        except (ValueError, OSError) as error:
            raise click.ClickException(str(error)) from None
        click.echo(json.dumps({k: report.get(k) for k in ('counts', 'regions', 'active_assignments', 'stored_records', 'unmatched_records', 'warnings', 'unchanged')}, ensure_ascii=False, indent=2))

    @app.cli.command('create-user')
    @click.option('--username', prompt='Nama pengguna')
    @click.option('--role', type=click.Choice(['admin', 'petugas', 'ppl', 'pml']), default='petugas')
    @click.option('--sls', multiple=True, help='Dapat diulang untuk beberapa kode SLS.')
    @click.option('--sensitive', is_flag=True, help='Izinkan catatan dan kontak; nominal uang tetap disamarkan.')
    @click.password_option(confirmation_prompt=True)
    def create_user(username, role, sls, sensitive, password):
        username = username.strip().casefold()
        if not username or len(username) > 80 or len(password) < (12 if role == 'admin' else 8):
            raise click.ClickException('Nama pengguna wajib; password minimal 12 karakter admin / 8 karakter petugas.')
        if db.session.query(User).filter(func.lower(User.username) == username).first():
            raise click.ClickException('Nama pengguna sudah ada.')
        if role in ('petugas', 'ppl') and not sls:
            raise click.ClickException('Petugas memerlukan minimal satu --sls.')
        if role == 'ppl' and len(set(sls)) != 2:
            raise click.ClickException('PPL memerlukan tepat dua SLS.')
        if role == 'pml' and sls:
            raise click.ClickException('PML mengikuti alokasi tim; gunakan update-allocations.')
        for code in sls:
            if not db.session.get(Region, code):
                raise click.ClickException('Kode SLS tidak ditemukan.')
        user = User(username=username.strip(), role=role, sensitive=sensitive, password_hash=generate_password_hash(password))
        db.session.add(user); db.session.flush()
        for code in set(sls):
            db.session.add(Grant(user_id=user.id, region=code))
        event('account_created', target_id=user.id)
        db.session.commit(); click.echo('Akun dibuat.')

    @app.cli.command('set-password')
    @click.argument('username')
    @click.option('--credentials-file', type=click.Path(exists=True, dir_okay=False), help='Wajib untuk reset akun petugas agar berkas distribusi ikut diperbarui.')
    @click.password_option(confirmation_prompt=True)
    def set_password(username, credentials_file, password):
        user = db.session.query(User).filter(func.lower(User.username) == username.strip().casefold()).first()
        if not user or len(password) < (12 if user.role == 'admin' else 8):
            raise click.ClickException('Pengguna tidak ditemukan atau panjang password tidak sesuai perannya.')
        if user.role in ('ppl', 'pml'):
            if not credentials_file:
                raise click.ClickException('Sertakan --credentials-file untuk memperbarui distribusi petugas.')
            from .allocations import reset_staff_password
            try:
                reset_staff_password(user, password, credentials_file)
            except (ValueError, OSError) as error:
                raise click.ClickException(str(error)) from None
        else:
            user.password_hash = generate_password_hash(password)
            revoke_sessions(user.id)
            event('password_reset', target_id=user.id)
            db.session.commit()
        click.echo('Password dan pencabutan sesi diperbarui.')

    @app.cli.command('backup-db')
    @click.argument('destination', type=click.Path())
    def backup_db(destination):
        import sqlite3
        target = Path(destination)
        if target.exists():
            raise click.ClickException('Tujuan sudah ada; pilih nama backup baru.')
        if db.engine.url.get_backend_name() != 'sqlite':
            raise click.ClickException('Perintah ini khusus SQLite.')
        with sqlite3.connect(db.engine.url.database) as source, sqlite3.connect(target) as dest:
            source.backup(dest)
        click.echo('Backup konsisten selesai. Simpan di lokasi terbatas.')
