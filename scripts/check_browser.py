"""Responsive/end-to-end QA on explicitly synthetic workbooks; screenshots stay local."""
import json
import os
import re
import sys
import threading
import time
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tests'))

from playwright.sync_api import sync_playwright, expect
from flask import request
from werkzeug.security import generate_password_hash
from werkzeug.serving import make_server, WSGIRequestHandler
from conftest import create_workbooks
from portal import create_app
from portal.importer import import_dataset
from portal.models import db, User, Assignment, Grant, Supervision, SourceRecord
from portal.form_layout import BLOCKS, ACTIVE_BLOCKS


class QuietHandler(WSGIRequestHandler):
    def log_request(self, *args, **kwargs):
        pass


root = Path(__file__).resolve().parents[1]
artifacts = root / 'artifacts'; artifacts.mkdir(exist_ok=True)
with TemporaryDirectory() as temp:
    folder = create_workbooks(Path(temp) / 'excel')
    app = create_app({'TESTING': True, 'AUTH_REQUIRED': False, 'SECRET_KEY': 'browser-synthetic-only', 'SQLALCHEMY_DATABASE_URI': 'sqlite:///' + (Path(temp) / 'synthetic.sqlite3').as_posix()})
    with app.app_context():
        db.create_all(); import_dataset(folder)
        db.session.add(User(username='contoh@example.test', role='admin', sensitive=True, password_hash=generate_password_hash('synthetic-browser-only'))); db.session.commit()
        for i in range(35):
            db.session.add(Assignment(source_id=f'pagination-only-{i}', version='synthetic-only', region='6502000000000001', name=f'PAGINASI {i:02}', building=str(100 + i), kind='BKU', status='OPEN', existence='Kode 1'))
        db.session.commit()
        for record in db.session.query(SourceRecord).filter_by(source='master'):
            record.raw = {**record.raw, 'level_3_name': 'KECAMATAN CONTOH', 'level_4_name': 'DESA CONTOH',
                          'level_5_name': 'SLS CONTOH', 'level_6_name': 'SUB-SLS CONTOH', 'level_6_full_code': '6502000000000001'}
        db.session.commit()

    @app.before_request
    def simulate_slow_search():
        if request.args.get('q') == 'SLOW':
            time.sleep(.8)
    server = make_server('127.0.0.1', 0, app, threaded=True, request_handler=QuietHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    results = []
    try:
        with sync_playwright() as p:
            candidates = sorted((Path(os.environ.get('LOCALAPPDATA', '.')) / 'ms-playwright').glob('chromium-*/**/chrome.exe')) if os.name == 'nt' else []
            browser = p.chromium.launch(**({'executable_path': str(candidates[-1])} if candidates else {}), headless=True)
            page = browser.new_page()
            failures = []
            page.on('pageerror', lambda error: failures.append(str(error)))

            def wait_search():
                expect(page.locator('[data-live-search]')).not_to_have_class(re.compile('is-searching'))

            def choose(select_id, value):
                native = page.locator('#' + select_id)
                text = native.locator('option').evaluate_all('(options, value) => options.find(option => option.value === value).textContent', value)
                trigger = page.locator('#' + select_id + '-control')
                trigger.click()
                page.locator('#' + select_id + '-control-list').get_by_role('option', name=text, exact=True).click()
                expect(native).to_have_value(value)

            page.goto(f'http://127.0.0.1:{server.server_port}/')
            assert 'PES SE2026' in page.title()
            assert 'konfirmasi' not in page.locator('body').inner_text().casefold()
            assert page.get_by_role('button', name='Keluar', exact=True).count() == 0
            assert page.locator('.brand-logo img').evaluate('(img) => img.complete && img.naturalWidth > 0')
            assert page.locator('.region-card').count() == 14
            # Disabled controls and option state stay in sync with the form select.
            page.locator('#district').evaluate('(el) => el.disabled = true')
            expect(page.locator('#district-control')).to_be_disabled()
            page.locator('#district').evaluate('(el) => el.disabled = false')
            expect(page.locator('#district-control')).to_be_enabled()
            page.locator('#district-control').click()
            expect(page.locator('#district-control-list [aria-selected="true"]')).to_have_count(1)
            page.locator('.directory-intro h1').click()
            expect(page.locator('#district-control')).to_have_attribute('aria-expanded', 'false')
            assert page.locator('a[href="/dataset"]').count() == 0
            for width in (360, 390, 430, 768, 1440):
                page.set_viewport_size({'width': width, 'height': 900})
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), ('regions overflow', width)
                if width in (390, 1440):
                    page.screenshot(path=str(artifacts / f'contoh-wilayah-{width}.png'), full_page=True)
                    page.screenshot(path=str(artifacts / f'pes-beranda-viewport-{width}.png'))
                results.append({'screen': 'wilayah', 'width': width, 'overflow': False})
            page.evaluate('window.scrollTo(0, 600)')
            assert page.locator('.directory-tools').bounding_box()['y'] >= page.locator('.topbar').bounding_box()['height'] - 1
            page.evaluate('window.scrollTo(0, 0)')
            region_search = page.get_by_label('Cari wilayah', exact=True)
            page.evaluate("window.liveSearchSentinel = 'same-document'")
            region_search.fill('TIDAK ADA')
            expect(page.locator('.region-card')).to_have_count(0)
            assert page.locator('#q').evaluate('(el) => el === document.activeElement')
            page.get_by_role('button', name='Hapus kata pencarian', exact=True).click()
            expect(page.locator('.region-card')).to_have_count(14)
            region_search.fill('CONTOH')
            expect(page).to_have_url(re.compile('q=CONTOH'))
            assert page.evaluate('window.liveSearchSentinel') == 'same-document'
            assert page.locator('.region-card mark').count() > 0
            page.locator('.region-card').first.click()
            page.wait_for_selector('.assignment-card')
            for width in (360, 390, 430, 768, 1440):
                page.set_viewport_size({'width': width, 'height': 900})
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), ('assignments overflow', width)
                if width in (390, 1440):
                    page.screenshot(path=str(artifacts / f'contoh-objek-{width}.png'), full_page=True)
                results.append({'screen': 'assignment', 'width': width, 'overflow': False})

            # Pagination, filter history and typing all keep the same document.
            expect(page.locator('.assignment-card')).to_have_count(12)
            page.locator('.pagination').get_by_role('link', name='Berikutnya', exact=False).click()
            expect(page.locator('.assignment-card')).to_have_count(12)
            expect(page).to_have_url(re.compile('page=2'))
            page.get_by_label('Temukan data keluarga atau usaha').fill('KELUARGA')
            expect(page.locator('.assignment-card')).to_have_count(1)
            assert 'page=2' not in page.url
            page.locator('.filter-chips').get_by_role('link', name='Bangunan/usaha', exact=True).click()
            expect(page.locator('.assignment-card')).to_have_count(0)
            page.go_back()
            expect(page.locator('.assignment-card')).to_have_count(1)
            expect(page.locator('input[name="kind"]')).to_have_value('')

            # A canceled slow result must never overwrite a newer query.
            with page.expect_request(lambda req: 'q=SLOW' in req.url):
                page.get_by_label('Temukan data keluarga atau usaha').fill('SLOW')
            page.get_by_label('Temukan data keluarga atau usaha').fill('KELUARGA')
            expect(page).to_have_url(re.compile('q=KELUARGA'))
            wait_search()
            page.wait_for_timeout(900)
            expect(page.locator('.assignment-card')).to_have_count(1)
            expect(page.locator('#q')).to_have_value('KELUARGA')

            # Failed searches preserve previous results and expose a working retry.
            page.route('**/sls/*?*q=PUTUS*', lambda route: route.abort())
            page.get_by_label('Temukan data keluarga atau usaha').fill('PUTUS')
            expect(page.locator('[data-search-retry]')).to_be_visible()
            expect(page.locator('.assignment-card')).to_have_count(1)
            page.unroute('**/sls/*?*q=PUTUS*')
            page.get_by_role('button', name='Coba lagi', exact=True).click()
            expect(page.locator('.assignment-card')).to_have_count(0)
            expect(page.locator('[data-search-retry]')).to_be_hidden()

            page.get_by_label('Temukan data keluarga atau usaha').fill('KELUARGA')
            page.get_by_role('button', name='Cari data', exact=False).click()
            expect(page.locator('.assignment-card')).to_have_count(1)
            page.locator('.filter-chips').get_by_role('link', name='Bangunan/usaha', exact=True).click()
            expect(page.locator('.assignment-card')).to_have_count(0)
            page.locator('.filter-chips').get_by_role('link', name='Keluarga', exact=True).click()
            expect(page.locator('.assignment-card')).to_have_count(1)
            page.locator('.advanced-filters > summary').click()
            choose('existence', 'Kode 1')
            expect(page).to_have_url(re.compile('existence=Kode'))
            choose('sort', 'name')
            expect(page).to_have_url(re.compile('sort=name'))
            page.get_by_role('button', name='Terapkan filter', exact=True).click()
            wait_search()
            assert page.locator('.assignment-card').count() == 1
            requests = []
            page.on('request', lambda request: requests.append(request.url) if request.url.endswith('/block') else None)
            page.locator('.assignment-card').click()
            page.wait_for_selector('.info-block')
            expect(page.locator('details[data-section]:visible')).to_have_count(1)
            expect(page.locator('[data-block-prev]')).to_be_disabled()
            page.locator('[data-block-next]').click()
            expect(page.locator('#block-wilayah')).to_be_visible()
            page.locator('[data-block-prev]').click()
            expect(page.locator('#block-pengantar')).to_be_visible()
            page.locator('#block-pengantar > summary').press('ArrowRight')
            expect(page.locator('#block-wilayah')).to_be_visible()
            page.go_back()
            expect(page.locator('#block-pengantar')).to_be_visible()
            # Visit all sections once; unavailable form sections must not fetch.
            for key, config in BLOCKS.items():
                if key == 'iii':
                    page.route('**/assignment/*/iii/block', lambda route: route.abort())
                choose('section-jump', 'block-' + key)
                expect(page.locator('#block-' + key)).to_be_visible()
                expect(page.locator('details[data-section]:visible')).to_have_count(1)
                if config['available']:
                    if key == 'iii':
                        expect(page.locator('#block-iii').get_by_role('button', name='Coba lagi')).to_be_visible()
                        page.unroute('**/assignment/*/iii/block')
                        page.locator('#block-iii').get_by_role('button', name='Coba lagi').click()
                    expect(page.locator('#block-' + key)).to_have_attribute('data-loaded', '1')
            requests_after_loading = len(requests)
            assert page.locator('#block-i .roster-card').count() == 3
            assert page.locator('#block-iii .roster-card').count() == 3
            assert page.locator('#block-ii .roster-card').count() == 2
            assert page.locator('details[data-section]').count() == len(BLOCKS)
            assert 'tidak disertakan' in page.locator('#block-anomali-usaha').text_content()
            expect(page.locator('[data-block-next]')).to_be_disabled()
            page.set_viewport_size({'width': 390, 'height': 700})
            choose('section-jump', 'block-i')
            assert page.locator('#block-i').get_attribute('open') is not None
            expect(page.locator('#block-i .roster-card:visible')).to_have_count(1)
            choose('block-i-roster-select', '1')
            expect(page.locator('#block-i .roster-card:visible')).to_have_attribute('data-roster-index', '2')
            choose('block-i-roster-select', '0')
            page.locator('#block-i .roster-card[open] .field-definition > summary').first.click()
            page.locator('#block-i .roster-card[open] .source-info > summary').first.click()
            page.locator('#block-i').evaluate('(el) => el.scrollTop = 240')
            saved = page.locator('#block-i').evaluate('(el) => el.scrollTop')
            assert saved > 0
            page.locator('[data-block-next]').click()
            page.locator('[data-block-prev]').click()
            expect(page.locator('#block-i .field-definition[open]')).to_have_count(1)
            expect(page.locator('#block-i .source-info[open]')).to_have_count(1)
            page.wait_for_function('(saved) => Math.abs(document.querySelector("#block-i").scrollTop - saved) < 2', arg=saved)
            assert len(set(requests)) == len(ACTIVE_BLOCKS)
            assert len(requests) == requests_after_loading, 'Reopening a block must reuse the already fetched content.'
            # Custom popup keyboard navigation must not also navigate the reader.
            control = page.locator('#section-jump-control')
            control.click()
            expect(control).to_have_attribute('aria-expanded', 'true')
            expect(page.locator('#section-jump-control-list [aria-selected="true"]')).to_have_count(1)
            control.press('ArrowDown')
            expect(page.locator('#block-i')).to_be_visible()
            control.press('Escape')
            expect(control).to_have_attribute('aria-expanded', 'false')
            expect(page.locator('#section-jump')).to_have_value('block-i')
            control.press('Enter')
            control.press('Home')
            control.press('ArrowDown')
            control.press('Enter')
            expect(page.locator('#block-wilayah')).to_be_visible()
            expect(control.locator('.select-value')).to_have_text('IDENTITAS WILAYAH')
            choose('section-jump', 'block-i')
            control.click()
            control.press('Tab')
            expect(control).to_have_attribute('aria-expanded', 'false')
            assert 'konfirmasi' not in page.locator('body').inner_text().casefold()
            for width in (360, 390, 430, 768, 1440):
                page.set_viewport_size({'width': width, 'height': 900})
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), ('detail overflow', width)
                assert page.evaluate('document.documentElement.scrollHeight <= innerHeight + 2'), ('detail vertical page overflow', width)
                control_box = page.locator('[data-slide-controls]').bounding_box()
                assert control_box['y'] >= 0 and control_box['y'] + control_box['height'] <= 900, ('navigation outside viewport', width)
                control.click()
                popup = page.locator('#section-jump-control-list')
                expect(popup).to_be_visible()
                menu_box = popup.bounding_box()
                assert menu_box['x'] >= 0 and menu_box['x'] + menu_box['width'] <= width + 1
                assert menu_box['y'] >= 0 and menu_box['y'] + menu_box['height'] <= 900
                assert control.bounding_box()['height'] >= 44
                assert popup.get_by_role('option').first.bounding_box()['height'] >= 42
                popup.get_by_role('option', name='SE2026 - L BLOK II', exact=True).hover()
                expect(popup.get_by_role('option', name='SE2026 - L BLOK II', exact=True)).to_have_class(re.compile('is-current'))
                if width in (390, 1440):
                    page.screenshot(path=str(artifacts / f'pes-custom-menu-{width}.png'))
                control.press('Escape')
                if width in (390, 1440):
                    page.evaluate('() => window.scrollTo(0, 0)')
                    page.screenshot(path=str(artifacts / f'contoh-detail-{width}.png'), full_page=True)
                results.append({'screen': 'detail', 'width': width, 'overflow': False})
            # Exercise the touch gesture with the same pointer events used on HP.
            page.set_viewport_size({'width': 390, 'height': 700})
            page.locator('#block-i .block-body').evaluate('''(el) => {
                el.dispatchEvent(new PointerEvent('pointerdown', {bubbles:true,pointerType:'touch',isPrimary:true,pointerId:42,clientX:300,clientY:450}));
                el.dispatchEvent(new PointerEvent('pointerup', {bubbles:true,pointerType:'touch',isPrimary:true,pointerId:42,clientX:150,clientY:455}));
            }''')
            expect(page.locator('#block-ii')).to_be_visible()
            page.emulate_media(reduced_motion='reduce')
            assert page.locator('#block-ii').evaluate('(el) => getComputedStyle(el).animationName') == 'none'
            for width, height in ((360, 640), (390, 700), (1024, 600)):
                page.set_viewport_size({'width': width, 'height': height})
                control.click()
                box = page.locator('#section-jump-control-list').bounding_box()
                assert box['x'] >= 0 and box['x'] + box['width'] <= width + 1
                assert box['y'] >= 0 and box['y'] + box['height'] <= height + 1
                control.press('Escape')
            # Actual touch interaction with a newly fetched roster picker.
            touch_context = browser.new_context(has_touch=True, viewport={'width': 390, 'height': 844})
            touch_page = touch_context.new_page()
            touch_page.goto(f'http://127.0.0.1:{server.server_port}/assignment/1#block-iii')
            touch_roster = touch_page.locator('#block-iii-roster-select-control')
            expect(touch_roster).to_be_visible()
            touch_roster.tap()
            touch_page.locator('#block-iii-roster-select-control-list').get_by_role('option', name='2 · ANGGOTA CONTOH 2', exact=True).tap()
            expect(touch_page.locator('#block-iii .roster-card:visible')).to_have_attribute('data-roster-index', '2')
            touch_context.close()
            reader_context = browser.new_context()
            reader_page = reader_context.new_page()
            reader_page.goto(f'http://127.0.0.1:{server.server_port}/assignment/3#block-wilayah')
            expect(reader_page.locator('#block-wilayah')).to_have_attribute('data-loaded', '1')
            for width, height in ((1440, 675), (1280, 600), (1024, 600), (390, 700), (360, 640)):
                reader_page.set_viewport_size({'width': width, 'height': height})
                reader_page.wait_for_function('() => document.documentElement.scrollWidth <= innerWidth')
                normal_box = reader_page.locator('#block-wilayah').bounding_box()
                assert normal_box['height'] >= height * (.47 if width > 760 else .40), ('reader too short', width, height, normal_box['height'])
                assert reader_page.evaluate('document.documentElement.scrollHeight <= innerHeight + 2')
                if width == 1280:
                    reader_page.screenshot(path=str(artifacts / 'pes-reader-room-1280.png'))
                reader_page.locator('[data-reader-focus]').click()
                expect(reader_page.locator('body')).to_have_class(re.compile('reader-focus'))
                focus_box = reader_page.locator('#block-wilayah').bounding_box()
                assert reader_page.evaluate('document.documentElement.scrollHeight <= innerHeight + 2')
                assert focus_box['height'] > normal_box['height'] + 70
                assert focus_box['height'] >= height * .65
                if width == 1280:
                    reader_page.screenshot(path=str(artifacts / 'pes-reader-focus-1280.png'))
                reader_page.locator('[data-block-next]').click()
                expect(reader_page.locator('#block-p')).to_be_visible()
                reader_page.locator('[data-block-prev]').click()
                expect(reader_page.locator('#block-wilayah')).to_be_visible()
                reader_page.locator('[data-reader-focus]').click()
                expect(reader_page.locator('body')).not_to_have_class(re.compile('reader-focus'))
                reader_page.locator('[data-reader-focus]').click()
                reader_page.locator('#block-wilayah > summary').press('Escape')
                expect(reader_page.locator('body')).not_to_have_class(re.compile('reader-focus'))
            reader_context.close()
            page.get_by_role('link', name='Kembali ke daftar objek', exact=False).click()
            assert 'q=KELUARGA' in page.url
            assert page.locator('.assignment-card').count() == 1
            page.locator('.breadcrumb').get_by_role('link', name='Wilayah kerja', exact=True).click()
            assert 'q=CONTOH' in page.url
            nojs = browser.new_context(java_script_enabled=False)
            fallback = nojs.new_page()
            fallback.goto(f'http://127.0.0.1:{server.server_port}/sls/6502000000000001')
            fallback.get_by_label('Temukan data keluarga atau usaha').fill('KELUARGA')
            fallback.get_by_role('button', name='Cari data', exact=False).click()
            expect(fallback.locator('.assignment-card')).to_have_count(1)
            fallback.locator('.assignment-card').click()
            fallback.locator('#block-i > summary').click()
            expect(fallback.locator('#block-i noscript a')).to_be_visible()
            nojs.close()
            # Verify the actual email login form, role header, and reader with login enabled.
            with app.app_context():
                for role in ('ppl', 'pml'):
                    db.session.add(User(username=role + '@example.test', role=role, sensitive=True,
                                        password_hash=generate_password_hash('synthetic-browser-only')))
                db.session.flush()
                ppl = db.session.query(User).filter_by(role='ppl').one()
                pml = db.session.query(User).filter_by(role='pml').one()
                db.session.add_all([Grant(user_id=ppl.id, region=f'650200000000000{i}') for i in (1, 2)])
                db.session.add(Supervision(pml_id=pml.id, ppl_id=ppl.id))
                db.session.commit()
            app.config['AUTH_REQUIRED'] = True
            mobile_context = browser.new_context(viewport={'width': 390, 'height': 844})
            mobile_page = mobile_context.new_page()
            mobile_photos = []
            mobile_page.on('request', lambda request: mobile_photos.append(request.url) if 'pelatihan-pes' in request.url else None)
            mobile_page.goto(f'http://127.0.0.1:{server.server_port}/login')
            expect(mobile_page.get_by_label('Email petugas')).to_be_visible()
            assert not mobile_photos, 'Hidden mobile photo should not download'
            mobile_context.close()
            for email, count in [('ppl@example.test', 2), ('pml@example.test', 2), ('contoh@example.test', 14)]:
                account_context = browser.new_context()
                account_page = account_context.new_page()
                account_page.on('pageerror', lambda error: failures.append(str(error)))
                account_page.goto(f'http://127.0.0.1:{server.server_port}/')
                expect(account_page.get_by_label('Email petugas')).to_be_visible()
                for width, height in ((1366, 768), (1698, 895), (1024, 600), (390, 844), (360, 800)):
                    account_page.set_viewport_size({'width': width, 'height': height})
                    if width > 760:
                        expect(account_page.locator('.login-photo')).to_be_visible()
                        expect(account_page.locator('.login-photo img')).to_have_js_property('naturalWidth', 1200)
                    else:
                        expect(account_page.locator('.login-photo')).to_be_hidden()
                    assert account_page.evaluate('document.documentElement.scrollHeight <= innerHeight + 2'), ('login requires scrolling', width, height)
                    if email == 'ppl@example.test' and width in (1366, 390):
                        account_page.screenshot(path=str(artifacts / f'pes-login-fit-{width}.png'))
                for width in (360, 390, 768, 1440):
                    account_page.set_viewport_size({'width': width, 'height': 900})
                    assert account_page.evaluate('document.documentElement.scrollWidth <= innerWidth'), ('login overflow', width)
                account_page.get_by_label('Email petugas').fill(email)
                account_page.get_by_label('Kata sandi').fill('synthetic-browser-only')
                account_page.get_by_role('button', name='Masuk ke portal', exact=False).click()
                expect(account_page.get_by_role('dialog')).to_be_visible()
                if email == 'ppl@example.test':
                    for width, height in ((1366, 768), (390, 844), (360, 640), (740, 360)):
                        account_page.set_viewport_size({'width': width, 'height': height})
                        box = account_page.get_by_role('dialog').bounding_box()
                        assert box['x'] >= 0 and box['y'] >= 0
                        assert box['width'] <= width and box['height'] <= height
                        assert account_page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                        if width in (1366, 390):
                            account_page.screenshot(path=str(artifacts / f'pes-commitment-{width}.png'))
                    account_page.set_viewport_size({'width': 390, 'height': 844})
                    account_page.mouse.click(5, 5)
                    expect(account_page.get_by_role('dialog')).to_be_visible()
                account_page.get_by_role('button', name='Saya memahami dan berkomitmen', exact=False).click()
                expect(account_page.locator('.region-card')).to_have_count(count)
                for width in (360, 390, 768, 1440):
                    account_page.set_viewport_size({'width': width, 'height': 900})
                    assert account_page.evaluate('document.documentElement.scrollWidth <= innerWidth'), ('role header overflow', width)
                account_page.goto(f'http://127.0.0.1:{server.server_port}/assignment/1#block-i')
                expect(account_page.locator('#block-i')).to_have_attribute('data-loaded', '1')
                account_page.set_viewport_size({'width': 360, 'height': 800})
                assert account_page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                box = account_page.locator('[data-slide-controls]').bounding_box()
                assert box['y'] + box['height'] <= 800
                if email == 'ppl@example.test':
                    account_page.screenshot(path=str(artifacts / 'pes-login-detail-synthetic-360.png'))
                if email == 'contoh@example.test':
                    account_page.route('**/block', lambda route: route.fulfill(status=403, body=''))
                    account_page.locator('[data-block-next]').click()
                    expect(account_page.get_by_role('link', name='Masuk kembali')).to_be_visible()
                    account_page.unroute('**/block')
                account_page.get_by_role('button', name='Keluar', exact=True).click()
                expect(account_page.get_by_label('Email petugas')).to_be_visible()
                account_context.close()
            # Closing, cancelling and Escape log out; a new login always asks again.
            for dismissal in ('close', 'exit', 'escape'):
                cancel_context = browser.new_context(viewport={'width': 390, 'height': 844})
                cancel_page = cancel_context.new_page()
                cancel_page.goto(f'http://127.0.0.1:{server.server_port}/login')
                cancel_page.get_by_label('Email petugas').fill('ppl@example.test')
                cancel_page.get_by_label('Kata sandi').fill('synthetic-browser-only')
                cancel_page.get_by_role('button', name='Masuk ke portal', exact=False).click()
                expect(cancel_page.get_by_role('dialog')).to_be_visible()
                if dismissal == 'escape':
                    cancel_page.keyboard.press('Escape')
                else:
                    cancel_page.get_by_role('button', name='Tutup dan keluar dari portal' if dismissal == 'close' else 'Keluar', exact=True).click()
                expect(cancel_page.get_by_label('Email petugas')).to_be_visible()
                assert cancel_page.request.get(f'http://127.0.0.1:{server.server_port}/assignment/1/i/block').status == 403
                cancel_context.close()
            assert not failures, failures
            browser.close()
        print(json.dumps({'checks': results, 'browser_errors': failures,
                          'slides_single_section_prev_next_jump_keyboard_touch_saved_scroll_rosters_cached_fetch': 'passed',
                          'email_login_ppl_pml_admin_logout_responsive_role_header': 'passed',
                          'custom_select_popup_sizes_hover_selection_keyboard_escape_tab_touch_dynamic_roster': 'passed',
                          'reader_height_with_warning_short_viewports_and_focus_mode': 'passed',
                          'live_search_focus_highlights_pagination_history_race_failure_retry_nojs': 'passed'}, indent=2))
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=5)
        with app.app_context():
            db.session.remove(); db.engine.dispose()
