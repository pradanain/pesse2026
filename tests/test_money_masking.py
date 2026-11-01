from copy import deepcopy

from bs4 import BeautifulSoup

from portal.form_layout import FILES
from portal.metadata import CATALOG
from portal.models import db, SourceRecord
from portal.presentation import MONEY, display_value, fields, is_money


def test_every_currency_and_computed_money_column_is_masked():
    keys = MONEY | {key for key, info in CATALOG['fields'].items() if info.get('type') == 'Currency'}
    assert len(keys) == 34
    for key in keys:
        assert is_money(key)
        assert display_value(key, '2678913') == 'Rp 1 juta – kurang dari Rp 5 juta'
        assert display_value(key, 'infinity').startswith('Nominal disamarkan')
        assert display_value(key, '2.678.913').startswith('Nominal disamarkan')


def test_money_boundaries_zero_blank_and_negative_stay_distinct():
    assert display_value('pend_gaji', None).startswith('Belum terisi')
    assert display_value('pend_gaji', '').startswith('Belum terisi')
    assert display_value('pend_gaji', 0) == 'Rp 0'
    assert display_value('pend_gaji', 99999) == 'Kurang dari Rp 100 ribu'
    assert display_value('pend_gaji', 100000) == 'Rp 100 ribu – kurang dari Rp 500 ribu'
    assert display_value('pend_gaji', 5000000) == 'Rp 5 juta – kurang dari Rp 10 juta'
    assert display_value('pend_gaji', 10**12) == 'Rp 1 triliun atau lebih'
    assert display_value('pend_gaji', '-1234567') == 'Nominal negatif · disamarkan'


def test_quantities_identifiers_and_income_presence_answers_are_unchanged():
    raw = {'jumlah_motor_new': 2, 'jumlah_emas_new': 12.5, 'jumlah_lahan_new': 3,
           'nik_dtsen': '9999999999991234', 'no_kk': '8888888888885678', 'tk_laki': 5,
           'pendapatan_pekerjaan_value': '1', 'pend_usaha_lain_value': '2', 'nilai_motor': 2678913}
    original = deepcopy(raw)
    shown = {field['key']: field for field in fields(raw, sensitive=True)}
    assert raw == original
    for key in ('jumlah_motor_new', 'jumlah_emas_new', 'jumlah_lahan_new', 'nik_dtsen', 'no_kk', 'tk_laki'):
        assert shown[key]['value'] == str(raw[key])
        assert not shown[key]['money_masked']
    assert shown['pendapatan_pekerjaan_value']['value'] == 'Ya (kode 1)'
    assert shown['pend_usaha_lain_value']['value'] == 'Tidak (kode 2)'
    assert shown['nilai_motor']['money_masked']


def test_exact_money_is_absent_from_http_even_for_admin_and_local_mode(app, client):
    with app.app_context():
        records = db.session.query(SourceRecord).filter_by(source_id='contoh-keluarga').all()
        for record in records:
            keys = [key for key, info in CATALOG['fields'].items()
                    if FILES[record.source] in info.get('source_files', []) and is_money(key)]
            if keys:
                record.raw = {**record.raw, **{key: '2678913' for key in keys}}
        db.session.commit()
        snapshot = {record.id: deepcopy(record.raw) for record in records}
    for auth_required in (True, False):
        app.config['AUTH_REQUIRED'] = auth_required
        for block in ('iii', 'iv', 'ii'):
            response = client.get(f'/assignment/1/{block}/block')
            assert response.status_code == 200
            html = response.get_data(as_text=True)
            assert '2678913' not in html and '2.678.913' not in html
            soup = BeautifulSoup(html, 'html.parser')
            assert soup.select('.money-reference')
            assert 'Rp 1 juta – kurang dari Rp 5 juta' in soup.get_text()
            assert 'Tetap tanyakan nominal kepada responden' in soup.get_text()
        identity = client.get('/assignment/1/i/block').get_data(as_text=True)
        assert '9999999999991234' in identity
        assert '8888888888885678' in client.get('/assignment/1/p/block').get_data(as_text=True)
        assert 'money-reference' not in identity
    with app.app_context():
        assert {record.id: record.raw for record in db.session.query(SourceRecord).filter_by(source_id='contoh-keluarga')} == snapshot


def test_conflicting_money_in_same_range_keeps_both_origins(app, client):
    with app.app_context():
        for source, value in [('economy', '2500000'), ('assets', '2600000')]:
            record = db.session.query(SourceRecord).filter_by(source=source, source_id='contoh-keluarga').one()
            record.raw = {**record.raw, 'total_pendapatan_keluarga_sebulan': value}
        db.session.commit()
    html = client.get('/assignment/1/iv/block').get_data(as_text=True)
    assert all(value not in html for value in ('2500000', '2600000', '2.500.000', '2.600.000'))
    soup = BeautifulSoup(html, 'html.parser')
    conflicts = [element for element in soup.select('.field-conflict')
                 if 'Total pendapatan keluarga per bulan' in element.dt.get_text()]
    assert len(conflicts) == 2
    assert {element.dd.get_text() for element in conflicts} == {'Rp 1 juta – kurang dari Rp 5 juta'}
    assert all('Kisaran acuan dapat sama' in element.get_text() for element in conflicts)
