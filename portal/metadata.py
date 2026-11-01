"""Read-only, source-backed labels; no questionnaire expressions are evaluated."""
import json
import re
from pathlib import Path

_catalog_path = Path(__file__).parent / 'data' / 'field_metadata.json'
CATALOG = json.loads(_catalog_path.read_text(encoding='utf-8')) if _catalog_path.exists() else {'fields': {}}
FIELD_METADATA = CATALOG['fields']


def describe(key):
    base = re.sub(r'_(label|value)$', '', key)
    return FIELD_METADATA.get(key) or FIELD_METADATA.get(base) or FIELD_METADATA.get(base + '_value') or FIELD_METADATA.get(base + '_label') or {}


def choice_label(key, value):
    if value is None or value == '':
        return None
    return describe(key).get('options', {}).get(str(value))


def readable_question(key):
    question = describe(key).get('question', '')
    for old, new in [('$NAME$', 'anggota keluarga'), ('$namaKK', 'kepala keluarga'), ('$narasi', 'produksi/penjualan/pendapatan sesuai jenis usaha')]:
        question = question.replace(old, new)
    return re.sub(r'\$[A-Za-z_][A-Za-z0-9_]*\$?', 'isian terkait', question)


def existence_label(kind, value):
    if not value or not value.startswith('Kode '):
        return value
    field = 'ada_bang_usaha_value' if kind == 'BKU' else 'ada_keluarga_value' if kind == 'Keluarga' else None
    code = value[5:]
    text = choice_label(field, code) if field else None
    return f'{text} (kode {code})' if text else value + ' · label belum terpetakan'
