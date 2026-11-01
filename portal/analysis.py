import hashlib
import json
from collections import Counter
from datetime import date, datetime, timezone, timedelta
from pathlib import Path

from openpyxl import load_workbook
from openpyxl.utils.datetime import from_excel, WINDOWS_EPOCH

from .catalog import SOURCES
from .presentation import label
from .metadata import describe


def normalize_date(value, epoch=WINDOWS_EPOCH):
    if value is None or isinstance(value, bool):
        raise ValueError('Tanggal kunci kosong/tidak valid')
    if isinstance(value, (int, float)):
        value = from_excel(value, epoch)
    if isinstance(value, str):
        value = datetime.fromisoformat(value.strip().replace('Z', '+00:00'))
    if not isinstance(value, datetime):
        raise ValueError('Tanggal kunci harus menyertakan waktu')
    if value.tzinfo:
        value = value.astimezone(timezone.utc).replace(tzinfo=None)
    # Excel stores floating point days. Source exports have millisecond precision.
    value = (value + timedelta(microseconds=500)).replace(microsecond=0) if value.microsecond >= 999500 else value.replace(microsecond=((value.microsecond + 500) // 1000) * 1000)
    return value.isoformat(timespec='milliseconds')


def json_value(value):
    return value.isoformat() if isinstance(value, (date, datetime)) else value


def read_sources(directory):
    result, sheets, dictionary = [], [], []
    for filename, (source, grain) in SOURCES.items():
        path = Path(directory) / filename
        if not path.exists():
            raise ValueError(f'File wajib belum tersedia: {filename}')
        book = load_workbook(path, read_only=True, data_only=True)
        formulas = load_workbook(path, read_only=True, data_only=False)
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        try:
            for sheet in book:
                rows = sheet.iter_rows(values_only=True)
                headers = next(rows, ())
                if not headers or any(not isinstance(h, str) or not h.strip() for h in headers) or len(set(headers)) != len(headers):
                    raise ValueError(f'Header kosong/ganda: {filename}/{sheet.title}')
                required = {'kode_sls_subsls'} if grain == 'region' else {'assignment_id', 'assignment_date_modified', 'level_6_full_code'}
                if grain in ('member', 'business'):
                    required.add('index1')
                if not required.issubset(headers):
                    raise ValueError(f'Kolom kunci tidak lengkap: {filename}/{sheet.title}')
                stats = {h: {'types': Counter(), 'empty': 0, 'zero': 0} for h in headers}
                count = 0
                formula_rows = formulas[sheet.title].iter_rows(min_row=2)
                for line, (values, formula_cells) in enumerate(zip(rows, formula_rows), 2):
                    if all(v is None for v in values):
                        continue
                    if any(c.data_type == 'f' for c in formula_cells):
                        raise ValueError(f'Formula Excel memerlukan ekspor nilai: {filename}/{sheet.title}, baris {line}')
                    raw = dict(zip(headers, values))
                    for h, v in raw.items():
                        stats[h]['empty'] += v is None or v == ''
                        stats[h]['zero'] += v == 0 and v is not None
                        if v is not None:
                            stats[h]['types'][type(v).__name__] += 1
                    try:
                        version = normalize_date(raw['assignment_date_modified'], book.epoch) if grain != 'region' else ''
                    except (ValueError, TypeError, OverflowError):
                        raise ValueError(f'Tanggal kunci tidak valid: {filename}/{sheet.title}, baris {line}') from None
                    result.append({'source': source, 'grain': grain, 'file': filename, 'sheet': sheet.title, 'line': line,
                                   'raw': {k: json_value(v) for k, v in raw.items()},
                                   'version': version,
                                   'digest': digest})
                    count += 1
                sheets.append({'file': filename, 'sheet': sheet.title, 'rows': count, 'columns': len(headers), 'sha256': digest})
                for h, stat in stats.items():
                    dictionary.append({'file': filename, 'sheet': sheet.title, 'column': h, 'display_label': label(h),
                                       'interpretation': 'Label dan opsi mengikuti metadata SQL Lab/form SE2026; nilai sumber dipertahankan.' if describe(h).get('metadata_row') else 'Kolom teknis/wilayah; deskripsi mengikuti sumber dan kamus kolom.',
                                       'question': describe(h).get('question'), 'question_section': describe(h).get('section'),
                                       'grain': grain, **stat,
                                       'pair': h[:-6] + '_value' if h.endswith('_label') and h[:-6] + '_value' in headers else None})
        finally:
            book.close()
            formulas.close()
    return result, {'sheets': sheets, 'dictionary': dictionary}


def write_analysis(report, destination):
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    (destination / 'data_dictionary.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    lines = ['# Analisis sumber Excel', '', 'Metadata saja; tanpa nama, identitas responden, atau URL assignment.', '', '| File | Sheet | Baris | Kolom |', '|---|---|---:|---:|']
    lines += [f"| {s['file']} | {s['sheet']} | {s['rows']} | {s['columns']} |" for s in report['sheets']]
    (destination / 'ANALISIS_DATA.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
