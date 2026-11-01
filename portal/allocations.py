"""Allocation workbook values are data only; no formulas or instructions execute."""
import re
import secrets
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font, PatternFill
from werkzeug.security import generate_password_hash, check_password_hash
from tempfile import NamedTemporaryFile

from .models import db, User, Grant, Supervision
from .auth import revoke_sessions, event

HEADERS = ('PROVINSI', 'KABUPATEN/KOTA', 'KECAMATAN', 'DESA', 'SLS', 'SUBSLS', 'Email Pengawas', 'Email Pencacah')


def email_address(value):
    email = str(value or '').strip().casefold()
    if len(email) > 80 or not re.fullmatch(r'[a-z0-9][a-z0-9._+\-]*@[a-z0-9-]+(?:\.[a-z0-9-]+)+', email):
        raise ValueError('Alamat email akun tidak valid.')
    return email


@dataclass
class AllocationPlan:
    rows: list
    ppl: dict
    pml: dict

    def summary(self):
        return {'rows': len(self.rows), 'sls': len({r['region'] for r in self.rows}),
                'ppl': len(self.ppl), 'pml': len(self.pml),
                'sls_per_ppl': sorted(len(v) for v in self.ppl.values()),
                'sls_per_pml': sorted(len(set().union(*(self.ppl[ppl] for ppl in enumerators))) for enumerators in self.pml.values()),
                'ppl_per_pml': sorted(len(v) for v in self.pml.values())}


def read_allocations(filename, known_regions):
    workbook = load_workbook(filename, read_only=True, data_only=True)
    try:
        if len(workbook.worksheets) != 1:
            raise ValueError('Alokasi harus memuat satu sheet yang jelas.')
        values = iter(workbook.active.values)
        if tuple(next(values, ())) != HEADERS:
            raise ValueError('Header alokasi tidak sesuai format wilayah/email petugas.')
        rows, owners, supervisors = [], {}, {}
        ppl, pml = defaultdict(set), defaultdict(set)
        for line, cells in enumerate(values, 2):
            if all(value in (None, '') for value in cells):
                continue
            try:
                parts = []
                for value, width in zip(cells[:6], (2, 2, 3, 3, 4, 2)):
                    if isinstance(value, float) and value.is_integer():
                        value = int(value)
                    text = str(value).strip()
                    if not text.isascii() or not text.isdigit() or len(text) > width:
                        raise ValueError('Kode wilayah tidak valid.')
                    parts.append(text.zfill(width))
                region = ''.join(parts)
                supervisor, enumerator = email_address(cells[6]), email_address(cells[7])
                if region not in known_regions:
                    raise ValueError('SLS tidak ditemukan pada data portal.')
                if region in owners:
                    raise ValueError('SLS dialokasikan lebih dari sekali.')
                if enumerator in supervisors and supervisors[enumerator] != supervisor:
                    raise ValueError('Satu PPL memiliki lebih dari satu PML.')
                owners[region] = enumerator
                supervisors[enumerator] = supervisor
                ppl[enumerator].add(region)
                pml[supervisor].add(enumerator)
                rows.append({'region': region, 'ppl': enumerator, 'pml': supervisor, 'line': line})
            except ValueError as error:
                raise ValueError(f'Baris alokasi {line}: {error}') from None
        if not rows or set(ppl) & set(pml):
            raise ValueError('Alokasi kosong atau email PPL dan PML bertabrakan.')
        if any(len(regions) != 2 for regions in ppl.values()):
            raise ValueError('Setiap PPL harus dialokasikan tepat dua SLS.')
        if set(owners) != set(known_regions):
            raise ValueError('Masih ada SLS portal yang belum dialokasikan.')
        return AllocationPlan(rows, dict(ppl), dict(pml))
    finally:
        workbook.close()


PASSWORD_POOL = tuple(word + code for word in ('Sensus', 'Ekonomi', 'Post', 'Survey')
                      for code in ('6502', '2026', '6500'))


def reset_staff_password(user, password, credentials_file):
    target = Path(credentials_file)
    original = target.read_bytes()
    workbook = load_workbook(target)
    temp = None
    replaced = False
    try:
        page = workbook['Akun petugas']
        matches = [line for line in range(2, page.max_row + 1) if email_address(page.cell(line, 1).value) == user.username]
        if len(matches) != 1:
            raise ValueError('Akun tidak memiliki satu baris distribusi yang jelas.')
        for line in range(2, page.max_row + 1):
            if line != matches[0] and page.cell(line, 3).value == password:
                raise ValueError('Password petugas harus berbeda dari petugas lainnya.')
        page.cell(matches[0], 3, password)
        with NamedTemporaryFile(dir=target.parent, suffix='.xlsx', delete=False) as stream:
            temp = Path(stream.name)
            workbook.save(stream)
        workbook.close()
        temp.chmod(0o600)
        temp.replace(target)
        replaced = True
        user.password_hash = generate_password_hash(password)
        revoke_sessions(user.id)
        event('password_reset', target_id=user.id)
        db.session.commit()
    except Exception:
        db.session.rollback()
        if replaced:
            target.write_bytes(original)
            target.chmod(0o600)
        raise
    finally:
        workbook.close()
        if temp and temp.exists():
            temp.unlink()


def generate_password(excluded=()):
    available = [password for password in PASSWORD_POOL if password not in excluded]
    if not available:
        raise ValueError('Kombinasi password pendek tidak cukup untuk seluruh petugas.')
    return secrets.choice(available)


def shorten_staff_passwords(credentials_file):
    """Rotate staff only and update their existing private distribution workbook."""
    target = Path(credentials_file)
    original = target.read_bytes()
    workbook = load_workbook(target)
    temporary = None
    replaced = False
    try:
        sheet = workbook['Akun petugas']
        accounts = {u.username: u for u in db.session.query(User).filter(User.active.is_(True), User.role.in_(('ppl', 'pml')))}
        rows = [(line, email_address(sheet.cell(line, 1).value)) for line in range(2, sheet.max_row + 1)]
        if len(rows) != len(accounts) or {email for _, email in rows} != set(accounts):
            raise ValueError('Daftar kredensial tidak cocok dengan akun petugas aktif.')
        if len(rows) > len(PASSWORD_POOL):
            raise ValueError('Kombinasi password pendek tidak cukup untuk seluruh petugas.')
        for line, email in rows:
            if not check_password_hash(accounts[email].password_hash, str(sheet.cell(line, 3).value)):
                raise ValueError('Kredensial distribusi sudah tidak cocok; pembaruan dihentikan.')
        used = set()
        for line, email in rows:
            password = generate_password(used)
            used.add(password)
            accounts[email].password_hash = generate_password_hash(password)
            sheet.cell(line, 3, password)
        with NamedTemporaryFile(dir=target.parent, suffix='.xlsx', delete=False) as stream:
            temporary = Path(stream.name)
            workbook.save(stream)
        workbook.close()
        temporary.chmod(0o600)
        temporary.replace(target)
        replaced = True
        db.session.commit()
        return {'staff_passwords_updated': len(rows), 'passwords_unique': len(used) == len(rows), 'admin_unchanged': True}
    except Exception:
        db.session.rollback()
        if replaced:
            target.write_bytes(original)
            target.chmod(0o600)
        raise
    finally:
        workbook.close()
        if temporary and temporary.exists():
            temporary.unlink()


def provision_accounts(plan, admin_email, admin_password, credentials_file):
    admin_email = email_address(admin_email)
    if admin_email in set(plan.ppl) | set(plan.pml) or len(admin_password) < 12:
        raise ValueError('Akun admin bertabrakan dengan petugas atau password admin kurang dari 12 karakter.')
    target = Path(credentials_file)
    if target.exists():
        raise ValueError('Berkas kredensial sudah ada; impor tidak menimpanya.')
    users = db.session.query(User).all()
    if any(user.username.casefold() in set(plan.ppl) | set(plan.pml) for user in users):
        raise ValueError('Akun petugas sudah ada; impor tidak mereset password atau alokasi secara otomatis.')
    admin = next((user for user in users if user.username.casefold() == admin_email), None)
    if admin and admin.role != 'admin':
        raise ValueError('Email admin sudah digunakan oleh peran lain.')
    passwords, accounts = {}, {}
    used_passwords = {admin_password}
    if len(plan.ppl) + len(plan.pml) > len(set(PASSWORD_POOL) - used_passwords):
        raise ValueError('Kombinasi password pendek tidak cukup untuk seluruh petugas.')
    created_file = False
    try:
        if not admin:
            admin = User(username=admin_email, role='admin')
            db.session.add(admin)
        admin.username = admin_email
        admin.password_hash = generate_password_hash(admin_password)
        admin.active, admin.sensitive = True, True
        for role, allocation in [('pml', plan.pml), ('ppl', plan.ppl)]:
            for email in sorted(allocation):
                password = generate_password(used_passwords)
                used_passwords.add(password)
                passwords[email] = password
                user = User(username=email, role=role, active=True, sensitive=True,
                            password_hash=generate_password_hash(password))
                db.session.add(user)
                accounts[email] = user
        db.session.flush()
        for email, regions in plan.ppl.items():
            for region in regions:
                db.session.add(Grant(user_id=accounts[email].id, region=region))
        for email, enumerators in plan.pml.items():
            for enumerator in enumerators:
                db.session.add(Supervision(pml_id=accounts[email].id, ppl_id=accounts[enumerator].id))
        # This workbook becomes the active account roster. Superseded accounts lose access.
        retired = 0
        for user in users:
            if user.id != admin.id:
                retired += bool(user.active)
                user.active = False
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = 'Akun petugas'
        sheet.append(['Email', 'Peran', 'Password', 'Jumlah SLS', 'Email PML', 'Kode SLS'])
        for email, user in sorted(accounts.items(), key=lambda item: (item[1].role, item[0])):
            if user.role == 'ppl':
                regions = plan.ppl[email]
                supervisor = next(r['pml'] for r in plan.rows if r['ppl'] == email)
            else:
                regions = set().union(*(plan.ppl[ppl] for ppl in plan.pml[email]))
                supervisor = ''
            sheet.append([email, 'PML / Pengawas' if user.role == 'pml' else 'PPL / Pencacah',
                          passwords[email], len(regions), supervisor, '\n'.join(sorted(regions))])
        allocation = workbook.create_sheet('Alokasi SLS')
        allocation.append(['Kode SLS', 'Email PML', 'Email PPL'])
        for row in plan.rows:
            allocation.append([row['region'], row['pml'], row['ppl']])
        for page in workbook:
            page.freeze_panes = 'A2'
            page.auto_filter.ref = page.dimensions
            for cell in page[1]:
                cell.font = Font(bold=True, color='FFFFFF')
                cell.fill = PatternFill('solid', fgColor='172D3D')
            for column in page.columns:
                page.column_dimensions[column[0].column_letter].width = 34
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open('xb') as stream:
            created_file = True
            workbook.save(stream)
        workbook.close()
        target.chmod(0o600)
        db.session.commit()
    except Exception:
        db.session.rollback()
        if created_file:
            target.unlink(missing_ok=True)
        raise
    return {**plan.summary(), 'active_accounts': len(accounts) + 1, 'retired_accounts': retired}
