from bs4 import BeautifulSoup

from portal.form_layout import BLOCKS, placement
from portal.metadata import describe
from portal.models import db, SourceRecord
from portal.metadata import CATALOG
from portal.catalog import SOURCES
from collections import defaultdict


def test_sections_and_field_locations_follow_reference_form():
    assert [b['title'] for b in BLOCKS.values() if b['is_form']] == [
        'PENGANTAR', 'IDENTITAS WILAYAH', 'SE2026 - P', 'SE2026 - L BLOK I',
        'SE2026 - L BLOK II', 'SE2026 - L BLOK III', 'SE2026 - L BLOK IV',
        'KETERANGAN PEMBERI JAWABAN', 'CATATAN', 'ANOMALI USAHA', 'ANOMALI KELUARGA']
    assert placement('members', 'nama_dtsen')['block'] == 'i'
    assert placement('education', 'ijazah_label')['block'] == 'iii'
    assert placement('income', 'pend_gaji')['block'] == 'iii'
    assert placement('family', 'nik_kk')['block'] == 'iii'
    assert placement('economy', 'total_pendapatan_keluarga_sebulan')['block'] == 'iv'
    assert placement('master', 'geotag_latitude')['block'] == 'p'
    assert describe('pengusaha_var_label')['form_rosters'] == ['se2026_nested']


def test_rosters_are_split_between_real_blocks(client):
    identity = client.get('/assignment/1/i/block').get_data(as_text=True)
    social = client.get('/assignment/1/iii/block').get_data(as_text=True)
    business = client.get('/assignment/1/ii/block').get_data(as_text=True)
    assert identity.count('data-roster-kind="member"') == 3
    assert social.count('data-roster-kind="member"') == 3
    assert business.count('data-roster-kind="business"') == 2
    assert '9999999999991234' in identity and '9999999999991234' not in social
    assert 'Ijazah/STTB tertinggi' in social and 'Ijazah/STTB tertinggi' not in identity
    assert 'Total pendapatan keluarga per bulan' in client.get('/assignment/1/iv/block').get_data(as_text=True)


def test_duplicates_merge_provenance_and_differing_answers_remain(app, client):
    soup = BeautifulSoup(client.get('/assignment/1/i/block').data, 'html.parser')
    card = soup.select_one('[data-roster-index="1"]')
    # The same age in the three source files appears once in block I.
    assert sum(dt.get_text(strip=True).endswith('Umur (tahun)') for dt in card.select('dt')) == 1
    assert 'PENDIDIKAN_PEKERJAAN_ART.xlsx' in card.get_text()
    assert 'PENDAPATAN_PER_ART.xlsx' in card.get_text()
    with app.app_context():
        record = db.session.query(SourceRecord).filter_by(source='education', roster_index='1').one()
        record.raw = {**record.raw, 'umur_ak': 31}
        db.session.commit()
    soup = BeautifulSoup(client.get('/assignment/1/i/block').data, 'html.parser')
    conflicts = soup.select('[data-roster-index="1"] .field-conflict')
    assert len(conflicts) == 2
    assert {element.dd.get_text(strip=True) for element in conflicts} == {'25', '31'}


def test_unavailable_form_anomalies_are_not_portal_checks(client):
    assert not BLOCKS['anomali-usaha']['available'] and not BLOCKS['anomali-keluarga']['available']
    missing = client.get('/assignment/1/anomali-usaha/block').get_data(as_text=True)
    assert 'tidak disertakan' in missing and 'Tidak ada indikasi' not in missing
    technical = client.get('/assignment/3/sumber/block').get_data(as_text=True)
    assert 'Isian root keluarga' in technical and 'di luar blok kuesioner' in technical


def test_unknown_export_columns_stay_visible_as_source_information(app, client):
    with app.app_context():
        record = db.session.query(SourceRecord).filter_by(source='family', source_id='contoh-keluarga').one()
        record.raw = {**record.raw, 'kolom_baru_contoh': 'NILAI SUMBER CONTOH'}
        db.session.commit()
    assert 'NILAI SUMBER CONTOH' in client.get('/assignment/1/sumber/block').get_data(as_text=True)


def test_question_order_matches_form_and_uses_real_numbers(client):
    soup = BeautifulSoup(client.get('/assignment/1/i/block').data, 'html.parser')
    labels = [dt.get_text(' ', strip=True) for dt in soup.select('[data-roster-index="1"] dt')]
    assert next(i for i, t in enumerate(labels) if 'Nama anggota keluarga' in t) < next(i for i, t in enumerate(labels) if 'NIK anggota' in t)
    numbers = [span.get_text(strip=True) for span in soup.select('[data-roster-index="1"] .question-number')]
    assert numbers[:3] == ['5', '6', '7']


def test_all_detail_columns_have_one_destination():
    destinations = defaultdict(set)
    expected = set()
    for key, info in CATALOG['fields'].items():
        files = [f for f in info['source_files'] if SOURCES[f][1] != 'region']
        if files and key != 'index1' and not key.endswith(('_url', '_uri', '_filename')):
            expected.add(key)
        for filename in files:
            where = placement(SOURCES[filename][0], key)
            if where:
                destinations[key].add(where['block'])
    assert set(destinations) == expected
    assert all(len(targets) == 1 for targets in destinations.values())
