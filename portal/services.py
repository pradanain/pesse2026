import json
from collections import defaultdict

from flask import abort, g

from .models import db, Grant, Assignment, SourceRecord, Supervision, User
from .presentation import fields, display_value
from .metadata import describe, choice_label
from .form_layout import BLOCKS, PRIVATE_BLOCKS, FILES, GRAINS, placement


def allowed_regions():
    if g.user.role == 'admin':
        return None
    if g.user.role == 'pml':
        return [row[0] for row in db.session.query(Grant.region).join(Supervision, Grant.user_id == Supervision.ppl_id)
                .join(User, User.id == Supervision.ppl_id)
                .filter(Supervision.pml_id == g.user.id, User.role == 'ppl').distinct()]
    if g.user.role not in ('ppl', 'petugas'):
        return []
    return [r.region for r in db.session.query(Grant).filter_by(user_id=g.user.id)]


def authorize_region(code):
    allowed = allowed_regions()
    if allowed is not None and code not in allowed:
        abort(404)


def get_assignment(pk):
    a = db.session.get(Assignment, pk)
    if a is None or not a.latest:
        abort(404)
    authorize_region(a.region)
    return a


def _origin(record, note=''):
    return {'source': record.source, 'file': FILES.get(record.source, record.source), 'sheet': record.sheet,
            'line': record.line, 'index': record.roster_index or '', 'note': note}


def _add_origin(sources, origin):
    if origin not in sources:
        sources.append(origin)


def _sort_index(value):
    value = str(value or '')
    return (0, int(value), value) if value.isdigit() else (1, 0, value)


def _card_identity(scope, index, records):
    preferred = 'members' if scope == 'member' else 'businesses'
    anchor = next((r for r in records if r.source == preferred), records[0])
    raw = anchor.raw
    if scope == 'member':
        return {'name': raw.get('nama_dtsen') or f'Anggota indeks {index}',
                'summary': ' · '.join(str(raw[k]) for k in ('hubungan_label', 'jk_dtsen_label', 'keberadaan_dtsen_label') if raw.get(k)),
                'number': raw.get('no_urut_kk'), 'age': raw.get('umur_ak'), 'missing_anchor': anchor.source != 'members'}
    if scope == 'business':
        return {'name': raw.get('nama_usaha_edit') or raw.get('nama_usaha') or f'Usaha indeks {index}',
                'summary': raw.get('keberadaan_usaha_label') or display_value('keberadaan_usaha_value', raw.get('keberadaan_usaha_value')),
                'number': raw.get('no_usaha'), 'age': None, 'missing_anchor': anchor.source != 'businesses'}
    return {'name': '', 'summary': '', 'number': None, 'age': None, 'missing_anchor': False}


def block_data(a, block):
    if block not in BLOCKS:
        abort(404)
    sensitive = g.user.role == 'admin' or g.user.sensitive
    if block in PRIVATE_BLOCKS and not sensitive:
        abort(403)
    if not BLOCKS[block]['available']:
        return [], 0
    records = db.session.query(SourceRecord).filter_by(assignment_pk=a.id).order_by(SourceRecord.id).all()
    safe_records = [r for r in records if not r.ambiguous]
    units = defaultdict(list)
    member_names = defaultdict(list)
    for record in safe_records:
        grain = GRAINS.get(record.source)
        scope = grain if grain in ('member', 'business') else 'root'
        units[(scope, record.roster_index if scope != 'root' else '')].append(record)
        if record.source == 'members' and record.raw.get('nama_dtsen'):
            member_names[record.roster_index].append(record)
    ambiguous = sum(r.ambiguous and any((placement(r.source, key) or {}).get('block') == block for key in r.raw) for r in records)
    displayed = defaultdict(lambda: defaultdict(dict))
    for record in safe_records:
        if not sensitive and record.source in ('income', 'economy', 'assets'):
            continue
        raw = dict(record.raw)
        if not sensitive and record.source == 'business_finance':
            raw = {key: value for key, value in raw.items()
                   if key.startswith('tk_') or key in ('total_tk_jk', 'total_tk_bayar', 'tahun_operasi')}
        references = {}
        for key in ('pengusaha_var_value', 'nama_info_list_value'):
            code = raw.get(key)
            info = describe(key)
            if (code is not None and info.get('source_option') in ('art_pengusaha', 'ak_info')
                    and not raw.get(key[:-6] + '_label') and choice_label(key, code) is None):
                matches = member_names.get(str(code), [])
                if len(matches) == 1:
                    paired = key[:-6] + '_label'
                    raw[paired] = matches[0].raw['nama_dtsen']
                    references[paired] = _origin(matches[0], 'referensi ART')
        # Resolve references first, then format only fields belonging to this block.
        selected_raw = {key: value for key, value in raw.items() if (placement(record.source, key) or {}).get('block') == block}
        for field in fields(selected_raw, sensitive=sensitive, include_meta=True):
            key = field['key']
            where = placement(record.source, key)
            if not where or where['block'] != block:
                continue
            scope = where['scope']
            unit = (scope, record.roster_index if scope != 'root' else '')
            canonical = describe(key).get('data_key', key)
            if key.endswith(('_label', '_value')):
                base = key.rsplit('_', 1)[0]
                code = raw.get(base + '_value')
                signature = (field['value'], type(code).__name__, str(code))
            else:
                signature = (field['value'], type(raw[key]).__name__, json.dumps(raw[key], ensure_ascii=False, sort_keys=True))
            variants = displayed[unit][canonical]
            if signature not in variants:
                variants[signature] = {**field, 'canonical': canonical, 'order': where['order'],
                                       'supporting': where['supporting'], 'sources': [], 'conflict': False}
            current = variants[signature]
            _add_origin(current['sources'], _origin(record))
            if key in references:
                _add_origin(current['sources'], references[key])
    cards = []
    for (scope, index), answers in displayed.items():
        flat = []
        for variants in answers.values():
            for value in variants.values():
                value['conflict'] = len(variants) > 1
                flat.append(value)
        flat.sort(key=lambda f: (f['order'], f['canonical']))
        sections = []
        for supporting, title in [(False, 'Isian sesuai urutan form'), (True, 'Informasi pendukung pada sumber')]:
            selected = [f for f in flat if f['supporting'] == supporting]
            if not selected:
                continue
            origins = []
            for field in selected:
                for origin in field['sources']:
                    _add_origin(origins, origin)
            sections.append({'title': title, 'fields': selected, 'sources': origins})
        identity = _card_identity(scope, index, units[(scope, index)])
        highlights = []
        if scope == 'member' and block == 'iii':
            education = next((r.raw for r in units[(scope, index)] if r.source == 'education'), {})
            highlights = [('Ijazah terakhir', education.get('ijazah_label') or display_value('ijazah_value', education.get('ijazah_value'))),
                          ('Pekerjaan utama', education.get('profesi_label') or display_value('profesi_value', education.get('profesi_value')))]
        elif scope == 'business' and block == 'ii':
            activity = next((r.raw for r in units[(scope, index)] if r.source == 'activities'), {})
            highlights = [('KBLI akhir', activity.get('kbli_akhir') or 'Belum terisi'),
                          ('Kegiatan utama', activity.get('keg_utama') or 'Belum terisi')]
        cards.append({**identity, 'kind': scope, 'index': index, 'sections': sections,
                      'field_count': len(flat), 'highlights': highlights})
    cards.sort(key=lambda card: ({'root': 0, 'member': 1, 'business': 2}[card['kind']],
                                 _sort_index(card['number'] if card['number'] is not None else card['index'])))
    return cards, ambiguous
