"""Local HTTP checks; credentials stay in memory and never appear in reports."""
import argparse
import getpass
import http.cookiejar
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from bs4 import BeautifulSoup
from openpyxl import load_workbook

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from portal import create_app
from portal.allocations import read_allocations
from portal.form_layout import BLOCKS
from portal.models import db, Region, Assignment, SourceRecord, User


def verify(allocation_file, credentials_file):
    base = 'http://127.0.0.1:6502'
    app = create_app({'AUTH_REQUIRED': True})
    with app.app_context():
        plan = read_allocations(allocation_file, {r.code for r in db.session.query(Region)})
        objects = [(a.id, a.region) for a in db.session.query(Assignment).filter_by(latest=True)]
        admins = [u.username for u in db.session.query(User).filter_by(role='admin', active=True)]
        counts = {'assignments': len(objects), 'source_rows': db.session.query(SourceRecord).count()}
        assert len(admins) == 1
        db.session.remove()
        db.engine.dispose()
    workbook = load_workbook(credentials_file, read_only=True, data_only=True)
    staff = [(r[0], r[2]) for r in list(workbook['Akun petugas'].values)[1:]]
    workbook.close()
    assert len(staff) == len(plan.ppl) + len(plan.pml)
    assert len({password for _, password in staff}) == len(staff)
    blocked = 0

    def request(opener, path, data=None):
        try:
            payload = urllib.parse.urlencode(data).encode() if data is not None else None
            with opener.open(base + path, data=payload, timeout=15) as response:
                return response.status, response.read().decode(), response.url
        except urllib.error.HTTPError as error:
            return error.code, '', ''

    def token(html):
        match = re.search(r'name="csrf_token" value="([^"]+)"', html)
        assert match
        return match.group(1)

    anonymous = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    assert urllib.parse.urlparse(request(anonymous, '/')[2]).path == '/login'
    assert request(anonymous, '/assignment/1/iv/block')[0] == 403
    assert request(anonymous, '/private/' + Path(credentials_file).name)[0] == 404

    def account(username, password, allowed):
        nonlocal blocked
        opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        status, html, _ = request(opener, '/login')
        assert status == 200
        status, home, final = request(opener, '/login', {'csrf_token': token(html), 'username': username, 'password': password})
        assert status == 200 and urllib.parse.urlparse(final).path == '/commitment'
        status, home, final = request(opener, '/commitment', {'csrf_token': token(home), 'decision': 'accept'})
        assert status == 200 and final == base + '/'
        soup = BeautifulSoup(home, 'html.parser')
        assert {urllib.parse.urlparse(a['href']).path.rsplit('/', 1)[1] for a in soup.select('.region-card')} == allowed
        assert not soup.select('a[href="/dataset"]')
        for region in {r['region'] for r in plan.rows}:
            expected = 200 if region in allowed else 404
            assert request(opener, '/sls/' + region)[0] == expected
            blocked += expected == 404
        outside = next((pk for pk, region in objects if region not in allowed), None)
        if outside is not None:
            assert request(opener, f'/assignment/{outside}')[0] == 404
            for block in BLOCKS:
                assert request(opener, f'/assignment/{outside}/{block}/block')[0] == 404
                blocked += 1
        assert request(opener, '/logout', {'csrf_token': token(home)})[2] == base + '/login'
        assert request(opener, '/assignment/1/iv/block')[0] == 403

    for username, password in staff:
        allowed = plan.ppl[username] if username in plan.ppl else set().union(*(plan.ppl[ppl] for ppl in plan.pml[username]))
        account(username, password, allowed)
    print('Login dan batas akses seluruh petugas berhasil diperiksa.', flush=True)
    admin_password = getpass.getpass('Password admin untuk pemeriksaan login: ')
    account(admins[0], admin_password, {r['region'] for r in plan.rows})
    with app.app_context():
        assert db.session.query(SourceRecord).count() == counts['source_rows']
        assert db.session.query(Assignment).filter_by(latest=True).count() == counts['assignments']
        db.session.remove()
        db.engine.dispose()
    print(json.dumps({**plan.summary(), **counts, 'accounts_verified': len(staff) + 1,
                      'unauthorized_requests_blocked': blocked, 'logout_verified': True,
                      'credentials_unique': True, 'dataset_menu_hidden': True}, ensure_ascii=False))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('allocation')
    parser.add_argument('--credentials', default='private/akun_petugas_PES_SE2026.xlsx')
    args = parser.parse_args()
    try:
        verify(args.allocation, args.credentials)
    except Exception:
        raise SystemExit('Pemeriksaan akun gagal. Tidak ada kredensial atau data responden yang dicetak.') from None
