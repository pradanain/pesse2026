import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from openpyxl import Workbook
from werkzeug.security import generate_password_hash

from portal import create_app
from portal.catalog import SOURCES
from portal.importer import import_dataset
from portal.models import db, User, Grant


def create_workbooks(folder):
    folder.mkdir(exist_ok=True)
    version = '2026-10-17 10:29:06.897'
    shared = {'assignment_date_modified': version, 'level_6_full_code': '6502000000000001', 'code_identity': 'CONTOH'}
    roots = [{'assignment_id': 'contoh-keluarga', **shared}, {'assignment_id': 'contoh-bku', **shared}, {'assignment_id': 'contoh-root-kosong', **shared}]
    for filename, (source, grain) in SOURCES.items():
        rows = []
        if source == 'regions':
            rows = [{'kode_sls_subsls': f'65020000000000{i:02}', 'kecamatan': 'KECAMATAN CONTOH', 'desa_kelurahan': 'DESA CONTOH', 'sls': f'SLS CONTOH {i}', 'sub_sls': f'SLS CONTOH {i}', 'jumlah_assignment_aktif': 3 if i == 1 else 0} for i in range(1, 15)]
        elif source == 'master':
            rows = [{**roots[0], 'nama_principal': 'KELUARGA CONTOH', 'nama_kk': 'CONTOH', 'no_bang': 2, 'ada_keluarga_value': '1', 'assignment_status_alias': 'COMPLETED', 'geotag_latitude': 2.8, 'geotag_longitude': 117.3}, {**roots[1], 'nama_principal': 'BKU CONTOH', 'no_bang': 10, 'ada_bang_usaha_value': '1', 'assignment_status_alias': 'OPEN'}, {**roots[2], 'nama_principal': 'TANPA ROOT CONTOH', 'no_bang': None, 'jenis_prelist': 'keluarga'}]
        elif grain == 'member':
            from datetime import datetime
            rows = [{**roots[0], 'assignment_date_modified': datetime.fromisoformat(version), 'index1': str(i), 'nama_dtsen': f'ANGGOTA CONTOH {i}', 'umur_ak': 0 if i == 3 else 25, 'no_urut_kk': str(i)} for i in range(1, 4)]
            for row in rows:
                if source == 'members':
                    row.update(nik_dtsen='9999999999991234', hubungan_label='Anak', hubungan_value='3')
                elif source == 'education':
                    row.update(ijazah_label='SMA CONTOH', ijazah_value='5', profesi_label='PEKERJAAN CONTOH')
                else:
                    row.update(pend_gaji=0, nilai_pend_pekerjaan='2500000')
        elif grain == 'business':
            rows = [{**roots[0], 'index1': str(i), 'nama_usaha': f'USAHA CONTOH {i}'} for i in (1, 2)]
            for row in rows:
                if source == 'activities':
                    row.update(kbli_akhir='12345', keg_utama='KEGIATAN CONTOH')
                if source == 'business_finance':
                    row.update(tk_laki=1, total_pendapatan=0)
        else:
            rows = [dict(roots[0]), dict(roots[1])]
            for row in rows:
                if source == 'family':
                    row.update(nama_kk='CONTOH', no_kk='8888888888885678', jumlah_ak=3 if row['assignment_id'] == 'contoh-keluarga' else None, jumlah_usaha_ditemukan=2 if row['assignment_id'] == 'contoh-keluarga' else None)
                elif source == 'screening':
                    row.update(usaha_online_value='1', usaha_keliling_value='2', catatan='CATATAN RAHASIA CONTOH')
                elif source == 'economy':
                    row.update(total_pendapatan_keluarga_sebulan='2500000', total_pengeluaran_keluarga_sebulan='0', catatan='CATATAN RAHASIA CONTOH')
                elif source == 'housing':
                    row.update(luas_lantai=0, jns_lantai_label=None)
                elif source == 'assets':
                    row.update(jumlah_motor_new=0, nilai_motor=None)
        wb = Workbook(); ws = wb.active
        headers = list(dict.fromkeys(k for row in rows for k in row))
        ws.append(headers)
        for row in rows:
            ws.append([row.get(k) for k in headers])
        wb.save(folder / filename)
    return folder


@pytest.fixture
def source_dir(tmp_path):
    return create_workbooks(tmp_path / 'excel')


@pytest.fixture
def app(source_dir):
    app = create_app({'TESTING': True, 'AUTH_REQUIRED': True, 'SECRET_KEY': 'synthetic-test-only', 'SQLALCHEMY_DATABASE_URI': 'sqlite://', 'WTF_CSRF_ENABLED': False})
    with app.app_context():
        db.create_all(); import_dataset(source_dir)
        for username, role, sensitive in [('admin', 'admin', True), ('petugas', 'petugas', False), ('berizin', 'petugas', True), ('terbatas', 'petugas', True)]:
            user = User(username=username, role=role, sensitive=sensitive, password_hash=generate_password_hash('test-strong-pass-2026'))
            db.session.add(user); db.session.flush()
            if role != 'admin':
                db.session.add(Grant(user_id=user.id, region='6502000000000002' if username == 'terbatas' else '6502000000000001'))
        db.session.commit()
    yield app


@pytest.fixture
def client(app):
    c = app.test_client()
    c.post('/login', data={'username': 'admin', 'password': 'test-strong-pass-2026'})
    c.post('/commitment', data={'decision': 'accept'})
    return c
