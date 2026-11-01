import re
from decimal import Decimal, InvalidOperation
from .metadata import CATALOG, describe, choice_label, readable_question

LABELS = {
    'assignment_id': 'Kode assignment', 'assignment_date_modified': 'Versi data sumber', 'code_identity': 'Kode identitas',
    'level_6_full_code': 'Kode SLS/Sub-SLS', 'level_3_name': 'Kecamatan', 'level_4_name': 'Desa/kelurahan',
    'level_5_name': 'SLS', 'level_6_name': 'Sub-SLS', 'nama_principal': 'Nama utama objek',
    'nama_kk': 'Nama kepala keluarga', 'dtsen_nama_kk': 'Nama kepala keluarga (prelist)', 'no_kk': 'Nomor KK',
    'dtsen_no_kk': 'Nomor KK (prelist)', 'nik_kk': 'NIK kepala keluarga', 'nik': 'NIK sumber',
    'nik_dtsen': 'NIK anggota keluarga', 'nik_dtsen_prelist': 'NIK anggota (prelist)', 'nik_pengusaha': 'NIK pengusaha',
    'no_bang': 'Nomor bangunan', 'jumlah_ak_kk': 'Jumlah anggota berdasarkan KK', 'jumlah_ak': 'Jumlah anggota hasil pendataan',
    'jml_ak_tinggal': 'Jumlah anggota yang tinggal', 'jml_kk': 'Jumlah keluarga (awal)', 'jml_kk_update': 'Jumlah keluarga dalam bangunan',
    'jumlah_usaha_ditemukan': 'Jumlah usaha ditemukan', 'jumlah_usaha_prelist': 'Jumlah usaha prelist',
    'ada_keluarga': 'Keberadaan keluarga', 'ada_bang_usaha': 'Keberadaan bangunan usaha', 'kode_bang': 'Jenis/kode bangunan',
    'assignment_status_alias': 'Status assignment', 'current_user_fullname': 'Petugas terakhir', 'date_modified': 'Waktu pembaruan sumber',
    'jenis_prelist': 'Jenis prelist', 'listing': 'Penanda listing sumber', 'mode': 'Moda pendataan',
    'geotag_latitude': 'Latitude', 'geotag_longitude': 'Longitude', 'geotag_accuracy': 'Akurasi geotagging (m)',
    'jalan_domisili': 'Jalan domisili', 'nomor_domisili': 'Nomor alamat', 'alamat_prelist': 'Alamat prelist',
    'nama_usaha_bang': 'Nama usaha/bangunan', 'index1': 'Indeks roster sumber', 'no_urut_kk': 'Nomor urut anggota',
    'nama_dtsen': 'Nama anggota keluarga', 'umur_ak': 'Umur (tahun)', 'hubungan': 'Hubungan dengan kepala keluarga',
    'jk_dtsen': 'Jenis kelamin', 'keberadaan_dtsen': 'Keberadaan anggota', 'tgl_lahir': 'Tanggal lahir',
    'bln_lahir': 'Bulan lahir', 'thn_lahir': 'Tahun lahir', 'status_kawin': 'Status perkawinan',
    'sekolah': 'Partisipasi sekolah', 'ijazah': 'Ijazah/STTB tertinggi', 'profesi': 'Profesi pekerjaan utama',
    'status_kerja': 'Kedudukan pekerjaan', 'rekening': 'Kepemilikan rekening', 'art_ada_usaha': 'Kepemilikan usaha anggota',
    'pendapatan_pekerjaan': 'Memiliki pendapatan pekerjaan', 'pendapatan_usaha': 'Memiliki pendapatan usaha',
    'pend_usaha_lain': 'Pendapatan usaha lainnya', 'pend_gaji': 'Gaji', 'pend_tunjangan': 'Tunjangan',
    'pend_uangmkn': 'Uang makan', 'pend_honor': 'Honor', 'pend_lembur': 'Lembur', 'pend_lainnya': 'Pendapatan pekerjaan lainnya',
    'nilai_pend_pekerjaan': 'Total pendapatan pekerjaan', 'pend_usaha': 'Pendapatan usaha', 'nilai_pend_lain': 'Pendapatan lainnya',
    'ec_art_pendapatan': 'Indikator pendapatan sumber', 'no_usaha': 'Nomor urut usaha', 'nama_usaha': 'Nama usaha (awal)',
    'nama_usaha_edit': 'Nama usaha hasil pendataan', 'nama_komersial': 'Nama komersial', 'keberadaan_usaha': 'Keberadaan usaha',
    'pengusaha': 'Nama pengusaha', 'pengusaha_var': 'Penanggung jawab (kode sumber)', 'alamat_usaha_view': 'Alamat usaha tercatat',
    'alamat_usaha_utama': 'Alamat utama usaha', 'hp': 'Nomor HP', 'no_telp': 'Nomor telepon', 'punya_nib': 'Kepemilikan NIB',
    'nib': 'Nomor induk berusaha', 'skala_usaha': 'Skala usaha', 'jenis_usaha': 'Jenis usaha', 'keg_utama': 'Kegiatan utama',
    'input': 'Input/bahan baku', 'proses': 'Proses usaha', 'produk': 'Produk utama', 'kbli': 'KBLI sumber',
    'kbli_genai': 'KBLI usulan sumber', 'kbli_akhir': 'KBLI akhir', 'kategori': 'Kategori KBLI', 'kategori_2025': 'Kategori KBLI 2025',
    'tk_laki': 'Tenaga kerja laki-laki', 'tk_pr': 'Tenaga kerja perempuan', 'total_tk_jk': 'Total tenaga kerja menurut jenis kelamin',
    'tk_dibayar': 'Tenaga kerja dibayar', 'tk_tdk_dibayar': 'Tenaga kerja tidak dibayar', 'total_tk_bayar': 'Total tenaga kerja menurut pembayaran',
    'tahun_operasi': 'Tahun mulai operasi', 'gaji': 'Biaya gaji', 'biaya_produksi': 'Biaya produksi', 'biaya_pembelian': 'Biaya pembelian',
    'operasional': 'Biaya operasional', 'non_operasional': 'Biaya nonoperasional', 'total_pengeluaran': 'Total pengeluaran usaha',
    'nilai_pendapatan': 'Pendapatan utama usaha', 'pendapatan_lain': 'Pendapatan lain usaha', 'total_pendapatan': 'Total pendapatan usaha',
    'total_aset_thn': 'Total aset (variabel tahunan)', 'total_aset_bln': 'Total aset (variabel bulanan)',
    'jns_bangunan': 'Jenis bangunan', 'status_kepemilikan': 'Status kepemilikan rumah', 'bukti_kepemilikan': 'Bukti kepemilikan',
    'luas_lantai': 'Luas lantai (m²)', 'jns_lantai': 'Jenis lantai', 'kondisi_lantai': 'Kondisi lantai',
    'jns_dinding': 'Jenis dinding', 'kondisi_dinding': 'Kondisi dinding', 'jns_atap': 'Jenis atap', 'kondisi_atap': 'Kondisi atap',
    'tempat_bab': 'Fasilitas buang air besar', 'jns_closet': 'Jenis kloset', 'buang_tinja': 'Pembuangan akhir tinja',
    'air_minum': 'Sumber air minum', 'sumber_penerangan': 'Sumber penerangan', 'jml_meteran': 'Jumlah meteran listrik',
    'total_pendapatan_keluarga_sebulan': 'Total pendapatan keluarga per bulan',
    'total_pengeluaran_keluarga_sebulan': 'Total pengeluaran keluarga per bulan',
    'pengeluaran_makanan_mingguan': 'Pengeluaran makanan per minggu', 'pengeluaran_non_makan_bulanan': 'Pengeluaran nonmakanan per bulan',
    'pengeluaran_non_makan_tahunan': 'Pengeluaran nonmakanan per tahun', 'listrik_sebulan': 'Pengeluaran listrik per bulan',
    'pulsa_sebulan': 'Pengeluaran komunikasi per bulan', 'sewa_sendiri': 'Perkiraan sewa rumah sendiri', 'sewa_kontrak': 'Sewa kontrak',
    'sewa_dinas': 'Sewa rumah dinas', 'catatan': 'Catatan asli pendataan', 'telp_info': 'Telepon pemberi informasi',
    'usaha_kos': 'Kos atau penyewaan', 'usaha_keliling': 'Usaha keliling', 'usaha_online': 'Usaha online',
    'usaha_bongkar': 'Usaha bongkar muat', 'usaha_konstruksi': 'Usaha konstruksi', 'usaha_lain': 'Kegiatan usaha lainnya',
    'tanaman_pangan': 'Tanaman pangan', 'hortikultura': 'Hortikultura', 'perkebunan': 'Perkebunan', 'peternakan': 'Peternakan',
    'kehutanan': 'Kehutanan', 'perikanan': 'Perikanan', 'jasa_pertanian': 'Jasa pertanian',
    'jumlah_tabung3kg_new': 'Jumlah tabung gas 3 kg', 'jumlah_tabung5kg_new': 'Jumlah tabung gas 5 kg',
    'jumlah_kulkas_new': 'Jumlah kulkas', 'jumlah_ac_new': 'Jumlah AC', 'jumlah_emas_new': 'Jumlah emas (satuan sumber)',
    'jumlah_laptop_new': 'Jumlah laptop', 'jumlah_motor_new': 'Jumlah sepeda motor', 'jumlah_mobil_new': 'Jumlah mobil',
    'jumlah_lahan_new': 'Jumlah lahan', 'jumlah_rumah_new': 'Jumlah rumah', 'nilai_motor': 'Nilai sepeda motor',
    'nilai_mobil': 'Nilai mobil', 'nilai_lahan': 'Nilai lahan', 'nilai_rumah': 'Nilai rumah',
}
MONEY = set('pend_gaji pend_tunjangan pend_uangmkn pend_honor pend_lembur pend_lainnya nilai_pend_pekerjaan pend_usaha nilai_pend_lain gaji biaya_produksi biaya_pembelian operasional non_operasional total_pengeluaran nilai_pendapatan pendapatan_lain total_pendapatan total_aset_thn total_aset_bln total_pendapatan_keluarga_sebulan total_pengeluaran_keluarga_sebulan pengeluaran_makanan_mingguan pengeluaran_non_makan_bulanan pengeluaran_non_makan_tahunan listrik_sebulan pulsa_sebulan sewa_sendiri sewa_kontrak sewa_dinas nilai_motor nilai_mobil nilai_lahan nilai_rumah'.split())
PRIVATE_CONTACT = {'hp', 'no_telp', 'telp_info', 'current_user_fullname', 'catatan', 'nama_info_list_value', 'nama_info_list_label', 'pengusaha', 'pengusaha_var_value', 'pengusaha_var_label'}
META = {'assignment_id', 'assignment_date_modified', 'level_6_full_code', 'code_identity', 'index1'}
SOURCE_LABELS = {'master': 'Identitas assignment', 'family': 'Identitas keluarga', 'members': 'Identitas anggota', 'education': 'Pendidikan dan pekerjaan', 'income': 'Pendapatan anggota', 'screening': 'Screening kegiatan usaha', 'businesses': 'Identitas usaha', 'activities': 'Kegiatan dan KBLI', 'business_finance': 'Tenaga kerja dan keuangan', 'housing': 'Tempat tinggal', 'economy': 'Pendapatan dan pengeluaran', 'assets': 'Aset keluarga'}
MONEY_BOUNDS = tuple(Decimal(n) for n in (
    100_000, 500_000, 1_000_000, 5_000_000, 10_000_000, 50_000_000,
    100_000_000, 500_000_000, 1_000_000_000, 5_000_000_000, 10_000_000_000,
    50_000_000_000, 100_000_000_000, 500_000_000_000, 1_000_000_000_000))


def is_money(key):
    info = describe(key)
    return key in MONEY or info.get('data_key') in MONEY or info.get('type') == 'Currency'


def money_reference(value):
    """Return only a coarse reference; never return an unparsed source amount."""
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return 'Nominal disamarkan · kisaran belum tersedia'
    if not number.is_finite():
        return 'Nominal disamarkan · kisaran belum tersedia'
    if number == 0:
        return 'Rp 0'
    if number < 0:
        return 'Nominal negatif · disamarkan'

    def rupiah(bound):
        for scale, name in ((10**12, 'triliun'), (10**9, 'miliar'), (10**6, 'juta'), (10**3, 'ribu')):
            if bound >= scale:
                return f'Rp {bound / scale:.0f} {name}'

    lower = None
    for upper in MONEY_BOUNDS:
        if number < upper:
            return ('Kurang dari ' if lower is None else rupiah(lower) + ' – kurang dari ') + rupiah(upper)
        lower = upper
    return rupiah(MONEY_BOUNDS[-1]) + ' atau lebih'


def label(key):
    mapped = describe(key).get('label')
    if mapped:
        return mapped
    base = re.sub(r'_(label|value)$', '', key)
    return LABELS.get(key, LABELS.get(base, base.replace('_', ' ').capitalize()))


def display_value(key, value):
    if value is None or value == '':
        return 'Belum terisi / keberlakuan belum diketahui'
    if is_money(key):
        return money_reference(value)
    if key.endswith('_value'):
        mapped = choice_label(key, value)
        if mapped is not None:
            return f'{mapped} (kode {value})'
        return f'Kode {value} · label belum diverifikasi'
    return str(value)


def fields(raw, sensitive=False, include_meta=False):
    output = []
    for key, value in raw.items():
        if not include_meta and key in META:
            continue
        if 'url' in key.lower():
            continue  # Access to source photos and assignment URLs has not been verified.
        if not sensitive and (is_money(key) or key in PRIVATE_CONTACT or key in ('catatan', 'nib') or key.startswith(('jumlah_', 'nilai_')) and 'new' in key):
            continue
        if key.endswith('_value') and raw.get(key[:-6] + '_label') not in (None, ''):
            continue
        if key.endswith('_label'):
            paired = raw.get(key[:-6] + '_value')
            if value in (None, '') and paired not in (None, ''):
                continue
            if value not in (None, '') and paired not in (None, ''):
                value = f'{value} (kode {paired})'
        info = describe(key)
        question = readable_question(key)
        shown = display_value(key, value)
        money_masked = is_money(key) and value not in (None, '')
        output.append({'label': label(key), 'value': shown, 'key': key,
                       'money_masked': money_masked,
                       'money_hint': ('Nilai nol pada sumber' if shown == 'Rp 0' else 'Nominal disamarkan' if 'disamarkan' in shown else 'Kisaran acuan · nominal asli disamarkan') if money_masked else '',
                       'question': question if len(question) > 100 else '',
                       'section': info.get('section') or next((s['title'] for s in CATALOG.get('form_sections', []) if s['data_key'] == info.get('form_section_key')), ''),
                       'number': info.get('number')})
    return output
