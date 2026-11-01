"""Extract display metadata only. Never execute JavaScript from the reference form."""
import argparse
import ast
import hashlib
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bs4 import BeautifulSoup
from openpyxl import load_workbook
from pypdf import PdfReader

from portal.presentation import LABELS

OVERRIDES = {
    'level_3_name': 'Kecamatan', 'level_4_name': 'Desa/kelurahan',
    'level_5_name': 'SLS', 'level_6_name': 'Sub-SLS',
    'ada_bang_usaha': 'Keberadaan bangunan lainnya/usaha',
    'kode_bang': 'Penggunaan bangunan',
    'usaha_kos': 'Persewaan lahan, rumah kontrakan, atau kos',
    'usaha_bongkar': 'Usaha tetap dengan peralatan bongkar-pasang',
    'usaha_konstruksi': 'Usaha konstruksi/pemborongan atau penggalian perorangan',
    'pengusaha_var': 'Pengusaha/penanggung jawab dari anggota keluarga',
    'pend_usaha_lain': 'Penerimaan pendapatan lain (transfer/pensiun/pemberian)',
    'nilai_pend_lain': 'Total pendapatan lain',
    'jml_ak_tinggal': 'Jumlah keluarga yang tinggal dalam satu rumah',
    'jumlah_ak': 'Jumlah anggota keluarga yang menetap',
    'jumlah_emas_new': 'Emas/perhiasan (gram)',
    'total_aset_thn': 'Total aset pada 31 Desember 2025',
    'total_aset_bln': 'Total aset pada akhir bulan yang lalu',
    'biaya_pembelian': 'Biaya pembelian barang yang terjual',
    'gaji': 'Upah, gaji, dan jaminan sosial pegawai',
    'nilai_pendapatan': 'Nilai produksi/penjualan/pendapatan barang dan jasa',
    'total_pendapatan': 'Total nilai produksi/penjualan/pendapatan usaha',
    'sewa_sendiri': 'Perkiraan sewa rumah milik sendiri/bebas sewa per bulan',
    'sewa_kontrak': 'Nilai kontrak/sewa rumah per bulan',
    'sewa_dinas': 'Perkiraan sewa rumah dinas/lainnya per bulan',
    'produk_sendiri': 'Memproduksi barang di lokasi usaha',
    'layanan_mamin': 'Menyediakan layanan makan/minum',
    'keg_penjualan': 'Melakukan penjualan barang',
    'keg_jasa': 'Jenis aktivitas jasa/pertanian',
    'lokasi_usaha': 'Tempat kegiatan usaha biasanya dilakukan',
    'klasifikasi': 'Klasifikasi akomodasi jangka pendek',
    'cek_kbli_pml': 'Pemeriksaan kategori dan KBLI oleh PML',
    'nama_info_list': 'Nama pemberi informasi',
    'hasilPemadananNIK': 'Hasil pemeriksaan/pemadanan NIK',
    'isprelistart': 'Penanda anggota keluarga dari prelist',
    'ijazah_prelist': 'Ijazah tertinggi pada prelist',
    'sekolah_prelist': 'Partisipasi sekolah pada prelist',
    'profesi_lainnya': 'Profesi pekerjaan utama lainnya',
    'flag_pbi': 'Penanda PBI dari sumber',
    'ec_art_pendapatan': 'Kriteria keberadaan ART untuk pertanyaan pendapatan',
    'rt': 'RT', 'rw': 'RW',
    'kode_sls_subsls': 'Kode SLS/Sub-SLS', 'sls': 'SLS', 'sub_sls': 'Sub-SLS',
    'desa_kelurahan': 'Desa/kelurahan', 'jumlah_assignment_aktif': 'Jumlah assignment aktif',
}


def clean(value):
    soup = BeautifulSoup(str(value or ''), 'html.parser')
    for tag in soup(['script', 'style']):
        tag.decompose()
    return re.sub(r'\s+', ' ', soup.get_text(' ', strip=True)).strip()


def option_label(value):
    return re.sub(r'^\s*\d+[.)]\s*', '', clean(value))


def literal_options(expression):
    """Read only literal value/label objects, including conditional option lists."""
    literal = r'''("(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*')'''
    result = []
    for obj in re.findall(r'\{[^{}]*\}', expression or '', re.S):
        val = re.search(r'''["']?value["']?\s*:\s*''' + literal, obj)
        label = re.search(r'''["']?label["']?\s*:\s*''' + literal, obj)
        if val and label:
            try:
                v, text = ast.literal_eval(val.group(1)), ast.literal_eval(label.group(1))
            except (ValueError, SyntaxError):
                continue
            if isinstance(v, str) and isinstance(text, str) and '$' not in text:
                result.append({'value': v, 'label': text})
    return result


def flatten_components(template):
    result = {}

    def walk(value):
        if isinstance(value, dict):
            if 'dataKey' in value and 'type' in value:
                if value['dataKey'] in result:
                    raise ValueError('DataKey form ganda; jangan memilih definisi secara diam-diam.')
                result[value['dataKey']] = value
            for key, child in value.items():
                if key not in ('options', 'expression', 'enableCondition', 'label', 'value'):
                    walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    walk(template['components'])
    return result


def component_layout(template):
    """Record real form containers and traversal order without evaluating the form."""
    sections, locations = [], {}
    position = 0

    def walk(value, section=None, rosters=()):
        nonlocal position
        if isinstance(value, list):
            for child in value:
                walk(child, section, rosters)
        elif isinstance(value, dict):
            if 'dataKey' in value and 'type' in value:
                position += 1
                key = value['dataKey']
                if value['type'] == 1:
                    section = key
                    sections.append({'data_key': key, 'title': clean(value.get('label')), 'position': position})
                if value['type'] == 2:
                    rosters = rosters + (key,)
                locations[key] = {'form_section_key': section, 'form_position': position, 'form_rosters': list(rosters)}
            if 'components' in value:
                walk(value['components'], section, rosters)

    walk(template['components'])
    return sections, locations


def build_catalog(metadata, form, pdf, dictionary, destination):
    book = load_workbook(metadata, read_only=True, data_only=True)
    meta, defaults, conflicts = {}, {}, []
    sheet_summary = []
    try:
        for sheet in book:
            rows = sheet.iter_rows(values_only=True)
            headers = next(rows, ())
            count = 0
            for rownum, row in enumerate(rows, 2):
                if not any(v is not None for v in row):
                    continue
                d = dict(zip(headers, row)); count += 1
                if sheet.title == '_METADATA_TEMPLATE' and d.get('template') == 'UMKM' and d.get('data_key'):
                    key = d['data_key']
                    if key in meta and clean(meta[key]['label']) != clean(d.get('label')):
                        conflicts.append(key)
                    meta[key] = {**d, 'sheet': sheet.title, 'row': rownum}
                if sheet.title == '_METADATA_DEFAULT' and d.get('column'):
                    defaults[d['column']] = clean(d.get('description'))
            sheet_summary.append({'sheet': sheet.title, 'rows': count})
    finally:
        book.close()
    if conflicts:
        raise ValueError('Label UMKM ganda dan berbeda: ' + ', '.join(sorted(set(conflicts))))
    soup = BeautifulSoup(Path(form).read_text(encoding='utf-8'), 'html.parser')
    script = next(s.get_text() for s in soup.find_all('script') if s.get_text().lstrip().startswith('window.__TPL='))
    template, _ = json.JSONDecoder().raw_decode(script.split('=', 1)[1].lstrip())
    components = flatten_components(template)
    form_sections, locations = component_layout(template)
    if not {'ada_keluarga', 'usaha_online', 'keberadaan_dtsen', 'keberadaan_usaha'}.issubset(components):
        raise ValueError('Form referensi tidak dikenali sebagai instrumen keluarga/UMKM; jangan mencampur opsi UB.')
    exported = json.loads(Path(dictionary).read_text(encoding='utf-8'))['dictionary']
    columns = sorted({r['column'] for r in exported})
    fields = {}
    for column in columns:
        key = re.sub(r'_(label|value)$', '', column)
        component_key = key if key in components else re.sub(r'_(latitude|longitude|accuracy|url|uri|filename)$', '', key)
        component = components.get(component_key, {})
        md = meta.get(key, {})
        question = clean(md.get('label') or component.get('label'))
        short = OVERRIDES.get(key, LABELS.get(column, LABELS.get(key)))
        if not short:
            short = question if question and question != key else defaults.get(column, key.replace('_', ' ').capitalize())
        short = re.sub(r'^\s*\d+[.)]\s*', '', short)
        for old, new in [('$NAME$', 'anggota keluarga'), ('$namaKK', 'kepala keluarga'), ('$narasi', 'produksi/penjualan/pendapatan')]:
            short = short.replace(old, new)
        source_option = re.sub(r'@\$ROW\$$', '', component.get('sourceOption', ''))
        options = component.get('options') or []
        kind = 'inline' if options else None
        if not options and source_option:
            options = literal_options(components.get(source_option, {}).get('expression'))
            kind = 'literal-source-option' if options else 'dynamic'
        values = defaultdict(set)
        for option in options:
            if isinstance(option, dict) and isinstance(option.get('value'), (str, int)) and option.get('label'):
                values[str(option['value'])].add(option_label(option['label']))
        enum = {code: next(iter(labels)) for code, labels in values.items() if len(labels) == 1}
        ambiguous = [code for code, labels in values.items() if len(labels) > 1]
        fields[column] = {
            'data_key': key, 'label': short, 'question': question,
            'section': clean(md.get('section')), 'number': md.get('number'), 'type': md.get('type'),
            'options': enum, 'options_kind': kind, 'source_option': source_option or None,
            'ambiguous_options': ambiguous, 'metadata_sheet': md.get('sheet'), 'metadata_row': md.get('row'),
            'has_form_component': bool(component), 'default_description': defaults.get(column),
            **locations.get(component_key, {'form_section_key': None, 'form_position': None, 'form_rosters': []}),
            'source_files': sorted({r['file'] for r in exported if r['column'] == column}),
        }
    references = []
    for path in (metadata, form, pdf):
        path = Path(path)
        references.append({'file': path.name, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()})
    # Read PDF as explanatory source only; no SQL or engine code is executed.
    reader = PdfReader(pdf)
    pdf_pages = {str(n): clean(reader.pages[n - 1].extract_text()) for n in (29, 30, 32, 34, 38, 39, 40)}
    catalog = {'template': 'UMKM', 'form_version': template.get('version'), 'references': references,
               'metadata_sheets': sheet_summary, 'pdf_page_count': len(reader.pages),
               'pdf_reference_pages': pdf_pages, 'form_sections': form_sections, 'fields': fields}
    destination = Path(destination); destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(catalog, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return catalog


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--metadata', required=True)
    parser.add_argument('--form', required=True)
    parser.add_argument('--pdf', required=True)
    parser.add_argument('--dictionary', default='docs/data_dictionary.json')
    parser.add_argument('--output', default='portal/data/field_metadata.json')
    args = parser.parse_args()
    catalog = build_catalog(args.metadata, args.form, args.pdf, args.dictionary, args.output)
    print(json.dumps({'exported_columns': len(catalog['fields']), 'metadata_matches': sum(bool(f['metadata_row']) for f in catalog['fields'].values()),
                      'columns_with_options': sum(bool(f['options']) for f in catalog['fields'].values()), 'form_version': catalog['form_version']}, indent=2))
