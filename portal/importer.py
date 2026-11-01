import hashlib
from collections import Counter, defaultdict
from datetime import datetime, timezone

from .analysis import read_sources, write_analysis
from .models import db, Region, Assignment, SourceRecord, Dataset

IMPORT_REVISION = '3'


def present(v):
    return v is not None and v != ''


def integer(v):
    try:
        n = float(v)
        return int(n) if n.is_integer() else None
    except (ValueError, TypeError):
        return None


def valid_coordinates(d):
    try:
        lat, lon = float(d['geotag_latitude']), float(d['geotag_longitude'])
        return -90 <= lat <= 90 and -180 <= lon <= 180 and (lat, lon) != (0, 0)
    except (KeyError, TypeError, ValueError):
        return False


def import_dataset(directory, analysis_dir=None):
    rows, report = read_sources(directory)
    fingerprint = hashlib.sha256((IMPORT_REVISION + ''.join(s['sha256'] + s['sheet'] for s in report['sheets'])).encode()).hexdigest()
    previous = db.session.get(Dataset, 1)
    if previous and previous.fingerprint == fingerprint:
        return {**previous.report, 'unchanged': True}
    groups = defaultdict(list)
    for r in rows:
        d = r['raw']
        if r['grain'] == 'region':
            key = ('regions', str(d['kode_sls_subsls']))
        else:
            if not present(d['assignment_id']) or not present(d['level_6_full_code']):
                raise ValueError(f"Kunci kosong: {r['file']}/{r['sheet']} baris {r['line']}")
            if r['grain'] in ('member', 'business') and not present(d['index1']):
                raise ValueError(f"Index roster kosong: {r['file']} baris {r['line']}")
            key = (r['source'], str(d['assignment_id']), r['version'], str(d.get('index1', '')))
        groups[key].append(r)
    ambiguous = {key for key, items in groups.items() if len(items) > 1}
    if any(key[0] in ('master', 'regions') for key in ambiguous):
        raise ValueError('Kunci master/wilayah ganda; dataset aktif dipertahankan. Periksa sumber.')
    report['duplicates'] = {source: sum(len(groups[k]) for k in ambiguous if k[0] == source) for source in {r['source'] for r in rows}}
    counts = Counter(r['source'] for r in rows)
    report['counts'] = dict(counts)
    report['warnings'] = []
    existing_ids = {(a.source_id, a.version): a.id for a in db.session.query(Assignment)}
    next_pk = max(max(existing_ids.values(), default=0) + 1, previous.report.get('next_assignment_pk', 1) if previous else 1)
    try:
        # Replace the active snapshot in one transaction; source workbooks stay untouched.
        db.session.query(SourceRecord).delete()
        db.session.query(Assignment).delete()
        db.session.query(Region).delete()
        for r in rows:
            if r['source'] == 'regions':
                d = r['raw']
                db.session.add(Region(code=str(d['kode_sls_subsls']), district=d.get('kecamatan') or 'Belum tercatat', village=d.get('desa_kelurahan') or 'Belum tercatat', name=d.get('sub_sls') or d.get('sls') or 'Belum tercatat', expected=integer(d.get('jumlah_assignment_aktif'))))
        db.session.flush()
        known = {r.code for r in db.session.query(Region)}
        masters = [r for r in rows if r['source'] == 'master']
        latest = {}
        for r in masters:
            sid = str(r['raw']['assignment_id'])
            latest[sid] = max(latest.get(sid, ''), r['version'])
        lookup, by_assignment = {}, defaultdict(list)
        for r in masters:
            d = r['raw']; region = str(d['level_6_full_code']); sid = str(d['assignment_id'])
            if region not in known:
                raise ValueError('Kode SLS master tidak terdapat di validasi wilayah; impor dibatalkan.')
            kind = 'BKU' if present(d.get('ada_bang_usaha_value')) else 'Keluarga' if present(d.get('ada_keluarga_value')) or present(d.get('nama_kk')) or d.get('jenis_prelist') == 'keluarga' else 'Belum teridentifikasi'
            existence_key = 'ada_bang_usaha_value' if kind == 'BKU' else 'ada_keluarga_value'
            pk = existing_ids.get((sid, r['version']))
            if pk is None:
                pk = next_pk; next_pk += 1
            a = Assignment(id=pk, source_id=sid, version=r['version'], region=region, latest=r['version'] == latest[sid],
                           name=next((str(d[k]) for k in ('nama_principal', 'nama_kk', 'nama_usaha_bang') if present(d.get(k))), 'Nama belum tercatat'),
                           building=str(d['no_bang']) if present(d.get('no_bang')) else '', kind=kind,
                           status=str(d.get('assignment_status_alias') or 'Belum tercatat'),
                           existence=f"Kode {d[existence_key]}" if present(d.get(existence_key)) else 'Belum terisi')
            db.session.add(a); db.session.flush(); lookup[(sid, r['version'])] = a
        orphan_count = 0
        for r in rows:
            d = r['raw']; sid = str(d.get('assignment_id', '')); a = lookup.get((sid, r['version']))
            roster_index = str(d.get('index1', ''))
            key = ('regions', str(d.get('kode_sls_subsls'))) if r['grain'] == 'region' else (r['source'], sid, r['version'], roster_index)
            if a and str(d.get('level_6_full_code')) != a.region:
                a = None
            if not a and r['source'] != 'regions':
                orphan_count += 1
            record = SourceRecord(source=r['source'], assignment_pk=a.id if a else None, source_id=sid,
                                  version=r['version'], roster_index=roster_index, sheet=r['sheet'], line=r['line'], raw=d, ambiguous=key in ambiguous)
            db.session.add(record)
            if a:
                by_assignment[a.id].append(record)
        conflicting_assignments = 0
        for a in lookup.values():
            items = by_assignment[a.id]; issues = []
            a.members = sum(r.source == 'members' and not r.ambiguous for r in items)
            a.businesses = sum(r.source == 'businesses' and not r.ambiguous for r in items)
            family = [r.raw for r in items if r.source == 'family' and not r.ambiguous]
            master = next(r.raw for r in items if r.source == 'master')
            if any(r.ambiguous for r in items):
                issues.append('Kunci sumber ganda; rincian ambigu tidak digabung.')
            if not family:
                issues.append('Isian root keluarga tidak tersedia pada versi yang sama.')
            elif a.kind == 'Keluarga':
                if not any(present(family[0].get(k)) for k in ('nama_kk', 'dtsen_nama_kk', 'jumlah_ak', 'no_kk')):
                    issues.append('Isian identitas keluarga belum tersedia pada versi ini.')
                for key, actual, title in [('jumlah_ak', a.members, 'ART'), ('jumlah_usaha_ditemukan', a.businesses, 'usaha')]:
                    expected = integer(family[0].get(key))
                    if expected is not None and expected != actual:
                        issues.append(f'Jumlah {title} sumber {expected}, roster {actual}; cakupan/keberadaan perlu diperiksa.')
            if not valid_coordinates(master):
                issues.append('Koordinat belum tersedia atau di luar rentang yang dapat dipetakan.')
            repeated = defaultdict(set)
            for item in items:
                if item.ambiguous:
                    continue
                namespace = 'member' if item.source in ('members', 'education', 'income') else 'business' if item.source in ('businesses', 'activities', 'business_finance') else 'root'
                for key, value in item.raw.items():
                    if key not in ('assignment_date_modified', 'assignment_id', 'index1') and present(value):
                        repeated[(namespace, item.roster_index, key)].add((type(value).__name__, str(value)))
            if any(len(values) > 1 for values in repeated.values()):
                conflicting_assignments += 1
                issues.append('Variabel berulang antar-file memiliki nilai/tipe berbeda; periksa rincian masing-masing sumber.')
            for other in ('education', 'income', 'activities', 'business_finance'):
                anchor = 'members' if other in ('education', 'income') else 'businesses'
                anchors = {r.roster_index for r in items if r.source == anchor and not r.ambiguous}
                supplements = {r.roster_index for r in items if r.source == other and not r.ambiguous}
                if anchors != supplements:
                    issues.append(f'Cakupan {other} berbeda dengan {anchor}; baris tetap disimpan terpisah.')
            a.issues = issues
        report['unmatched_records'] = orphan_count
        report['conflicting_assignments'] = conflicting_assignments
        report['next_assignment_pk'] = next_pk
        report['active_assignments'] = sum(a.latest for a in lookup.values())
        report['historical_assignments'] = len(lookup) - report['active_assignments']
        report['regions'] = len(known)
        for region in db.session.query(Region):
            actual = sum(a.latest and a.region == region.code for a in lookup.values())
            if region.expected is not None and region.expected != actual:
                report['warnings'].append(f'Jumlah assignment SLS {region.code}: validasi {region.expected}, master {actual}.')
        if orphan_count:
            report['warnings'].append(f'{orphan_count} baris tidak cocok dengan versi/wilayah master; disimpan tanpa JOIN.')
        db.session.flush()
        stored = db.session.query(SourceRecord).count()
        if stored != len(rows):
            raise ValueError('Jumlah baris sumber dan database tidak sesuai.')
        report['stored_records'] = stored
        # Finalize before assigning JSON: mutating an already assigned dictionary
        # can evade SQLAlchemy change detection when replacing an existing import.
        db.session.merge(Dataset(id=1, fingerprint=fingerprint, imported_at=datetime.now(timezone.utc).isoformat(), report=dict(report)))
        db.session.commit()
    except Exception:
        db.session.rollback()
        raise
    if analysis_dir:
        write_analysis(report, analysis_dir)
    return report
