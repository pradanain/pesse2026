"""Question placement follows the supplied form containers, independently of Excel files."""
from .catalog import SOURCES
from .metadata import CATALOG, FIELD_METADATA, describe

FORM_IDS = {
    'b0': 'pengantar', 'b1_p': 'wilayah', 'b5': 'p', 'b_ak': 'i', 'blokl': 'ii',
    'b_ak_lanjutan': 'iii', 'b_perumahan': 'iv', 'ket_jawaban': 'pemberi',
    'cat': 'catatan', 'anomali_section': 'anomali-usaha', 'anomali_keluarga': 'anomali-keluarga',
}
DESCRIPTIONS = {
    'pengantar': 'Informasi pengantar yang tercakup dalam ekstraksi',
    'wilayah': 'Identitas wilayah pada data sumber',
    'p': 'Identitas keluarga/bangunan dan screening usaha',
    'i': 'Keterangan anggota keluarga',
    'ii': 'Keterangan usaha/perusahaan',
    'iii': 'Identitas keluarga, pendidikan, pekerjaan dan pendapatan ART',
    'iv': 'Tempat tinggal, fasilitas, pengeluaran dan aset keluarga',
    'pemberi': 'Identitas pemberi informasi', 'catatan': 'Catatan asli pendataan',
    'anomali-usaha': 'Bagian anomali usaha pada form',
    'anomali-keluarga': 'Bagian anomali keluarga pada form',
}
GRAINS = {source: grain for source, grain in SOURCES.values()}
FILES = {source: filename for filename, (source, _) in SOURCES.items()}
IDENTITY_FIELDS = {'level_3_name', 'level_4_name', 'level_5_name', 'level_6_name', 'level_6_full_code'}
CONTEXT_FIELDS = {'assignment_id', 'assignment_date_modified', 'level_6_full_code', 'code_identity', 'no_bang', 'nama_kk'}


def placement(source, key):
    grain = GRAINS.get(source, 'assignment')
    if grain == 'region':
        return None  # Region-validation columns belong to the SLS directory.
    if key == 'index1' or key.lower().endswith(('_url', '_uri', '_filename')):
        return None
    if grain in ('member', 'business') and key in CONTEXT_FIELDS:
        return None  # Join context is not a repeated questionnaire answer.
    info = describe(key)
    rosters = info.get('form_rosters', [])
    scope = 'member' if any(r in ('nested_dtsen', 'nested_dtsen_var') for r in rosters) else 'business' if 'se2026_nested' in rosters else 'root'
    if info.get('form_section_key'):
        if scope != (grain if grain in ('member', 'business') else 'root'):
            return None
        section = FORM_IDS.get(info['form_section_key'], 'form-' + info['form_section_key'])
        return {'block': section, 'scope': scope, 'order': info.get('form_position') or 10000,
                'supporting': not info.get('section') and not info.get('number')}
    if grain == 'assignment' and key in IDENTITY_FIELDS:
        return {'block': 'wilayah', 'scope': 'root', 'order': 10000, 'supporting': True}
    return {'block': 'sumber', 'scope': grain if grain in ('member', 'business') else 'root',
            'order': 20000, 'supporting': True}


def _blocks():
    blocks = {}
    for section in CATALOG['form_sections']:
        key = FORM_IDS.get(section['data_key'], 'form-' + section['data_key'])
        blocks[key] = {'title': section['title'], 'description': DESCRIPTIONS.get(key, ''),
                       'badge': key.upper() if key in ('p', 'i', 'ii', 'iii', 'iv') else '',
                       'icon': 'map' if key == 'wilayah' else 'book', 'is_form': True,
                       'available': False, 'source_key': section['data_key']}
    blocks['sumber'] = {'title': 'Informasi data sumber', 'description': 'Metadata dan pemeriksaan otomatis portal; di luar blok form',
                        'badge': '', 'icon': 'files', 'is_form': False, 'available': True, 'source_key': None}
    for key, info in FIELD_METADATA.items():
        for filename in info.get('source_files', []):
            if filename in SOURCES:
                where = placement(SOURCES[filename][0], key)
                if where and where['block'] in blocks:
                    blocks[where['block']]['available'] = True
    return blocks


BLOCKS = _blocks()
ACTIVE_BLOCKS = tuple(key for key, config in BLOCKS.items() if config['available'])
PRIVATE_BLOCKS = {'pemberi', 'catatan'}
