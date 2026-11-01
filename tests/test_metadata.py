from copy import deepcopy

from portal.metadata import CATALOG, choice_label, existence_label
from portal.presentation import display_value, fields, label
from portal.models import db, SourceRecord


def test_choice_meaning_is_scoped_to_its_question():
    assert display_value('usaha_online_value', '1') == 'Ya (kode 1)'
    assert display_value('usaha_online_value', '2') == 'Tidak (kode 2)'
    assert display_value('keg_jasa_value', '1') == 'Jasa (kode 1)'
    assert display_value('kode_bang_value', '1') == 'Bangunan Khusus Usaha (kode 1)'
    assert existence_label('Keluarga', 'Kode 3') == 'Meninggal (kode 3)'
    assert existence_label('BKU', 'Kode 3') == 'Tutup (kode 3)'


def test_unknown_blank_zero_and_leading_zero_are_distinct():
    assert display_value('lokasi_usaha_value', '01') == 'Apotek (kode 01)'
    assert display_value('ijazah_value', '03') == 'SMA/sederajat (kode 03)'
    assert display_value('keberadaan_usaha_value', '00') == 'Tidak Ditemukan (kode 00)'
    assert choice_label('keberadaan_usaha_value', '0') is None
    assert display_value('pend_usaha_lain_value', '9') == 'Tidak Tahu (kode 9)'
    assert 'label belum diverifikasi' in display_value('usaha_online_value', '777')
    assert 'Belum terisi' in display_value('usaha_online_value', None)
    assert display_value('pend_gaji', 0) == 'Rp 0'
    assert display_value('ada_keluarga_value', '0') == 'Tidak Ditemukan (STOP) (kode 0)'


def test_existing_source_labels_win_and_source_dictionary_is_untouched():
    raw = {'sekolah_label': 'LABEL ASLI CONTOH', 'sekolah_value': '1', 'usaha_online_value': '2'}
    before = deepcopy(raw)
    shown = fields(raw, sensitive=True)
    assert raw == before
    assert any(f['value'] == 'LABEL ASLI CONTOH (kode 1)' for f in shown)
    assert any(f['value'] == 'Tidak (kode 2)' for f in shown)


def test_semantic_corrections_and_periods_from_metadata():
    assert label('usaha_bongkar_value') == 'Usaha tetap dengan peralatan bongkar-pasang'
    assert 'transfer/pensiun' in label('pend_usaha_lain_value')
    assert label('jml_ak_tinggal') == 'Jumlah keluarga yang tinggal dalam satu rumah'
    assert label('total_aset_thn') == 'Total aset pada 31 Desember 2025'
    assert label('total_aset_bln') == 'Total aset pada akhir bulan yang lalu'
    assert label('jumlah_emas_new') == 'Emas/perhiasan (gram)'
    assert CATALOG['template'] == 'UMKM' and CATALOG['form_version'] == '7.1.2'
    assert len(CATALOG['fields']) == 204


def test_dynamic_member_reference_uses_art_index_and_preserves_storage(app, client):
    with app.app_context():
        business = db.session.query(SourceRecord).filter_by(source='businesses', roster_index='1').one()
        business.raw = {**business.raw, 'pengusaha_var_value': '2'}
        economy = db.session.query(SourceRecord).filter_by(source='economy', source_id='contoh-keluarga').one()
        economy.raw = {**economy.raw, 'nama_info_list_value': '3'}
        db.session.commit()
    html = client.get('/assignment/1/ii/block').get_data(as_text=True)
    assert 'ANGGOTA CONTOH 2 (kode 2)' in html
    assert 'ANGGOTA CONTOH 3 (kode 3)' in client.get('/assignment/1/pemberi/block').get_data(as_text=True)
    with app.app_context():
        business = db.session.query(SourceRecord).filter_by(source='businesses', roster_index='1').one()
        assert business.raw['pengusaha_var_value'] == '2' and 'pengusaha_var_label' not in business.raw
    client.post('/logout')
    client.post('/login', data={'username': 'petugas', 'password': 'test-strong-pass-2026'})
    client.post('/commitment', data={'decision': 'accept'})
    assert 'ANGGOTA CONTOH 2' not in client.get('/assignment/1/ii/block').get_data(as_text=True)


def test_mapped_presence_labels_render_on_cards_and_filters(client):
    html = client.get('/sls/6502000000000001').get_data(as_text=True)
    assert 'Ditemukan (kode 1)' in html
    assert 'value="Kode 1"' in html
    assert 'Ditemukan (kode 1)' in client.get('/assignment/1').get_data(as_text=True)
    assert 'label belum diverifikasi' not in client.get('/assignment/1/p/block').get_data(as_text=True)


def test_metadata_questions_are_plain_text_not_executable_markup():
    shown = fields({'usaha_online_value': '1'}, sensitive=True)[0]
    assert '$namaKK' not in shown['question'] and '<script' not in shown['question']
    assert shown['section'] == 'SE2026 - P'
    for info in CATALOG['fields'].values():
        assert 'expression' not in info and 'enableCondition' not in info
