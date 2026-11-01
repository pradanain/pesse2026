"""Live-workbook reconciliation, never prints respondent data or source URLs."""
import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from portal import create_app
from portal.importer import import_dataset
from portal.models import db, Assignment, SourceRecord, User
from portal.form_layout import BLOCKS, ACTIVE_BLOCKS
from werkzeug.security import generate_password_hash

root = Path(__file__).resolve().parents[1]
with TemporaryDirectory() as temp:
    app = create_app({'TESTING': True, 'AUTH_REQUIRED': True, 'WTF_CSRF_ENABLED': False, 'SECRET_KEY': 'ephemeral-verification-only', 'SQLALCHEMY_DATABASE_URI': 'sqlite:///' + (Path(temp) / 'verify.sqlite3').as_posix()})
    with app.app_context():
        db.create_all(); report = import_dataset(root)
        assert db.session.query(SourceRecord).count() == sum(s['rows'] for s in report['sheets'])
        second = import_dataset(root)
        assert second['unchanged']
        db.session.add(User(username='temporary-verifier', password_hash=generate_password_hash('ephemeral-test-only'), role='admin', sensitive=True)); db.session.commit()
        client = app.test_client()
        assert client.post('/login', data={'username': 'temporary-verifier', 'password': 'ephemeral-test-only'}).status_code == 302
        assert client.post('/commitment', data={'decision': 'accept'}).status_code == 302
        assignments = db.session.query(Assignment).filter_by(latest=True).all()
        groups = {}
        for a in assignments:
            for source, count in [('members', a.members), ('businesses', a.businesses)]:
                assert db.session.query(SourceRecord).filter_by(assignment_pk=a.id, source=source, ambiguous=False).count() == count
            # Render every actual form section plus portal source information.
            assert client.get(f'/assignment/{a.id}').status_code == 200
            for block in BLOCKS:
                response = client.get(f'/assignment/{a.id}/{block}/block')
                assert response.status_code == 200
                if block in ('i', 'ii', 'iii'):
                    assert response.get_data(as_text=True).count('class="roster-card"') == (a.businesses if block == 'ii' else a.members)
            groups[a.kind] = groups.get(a.kind, 0) + 1
        summary = {k: report[k] for k in ('counts', 'regions', 'active_assignments', 'historical_assignments', 'stored_records', 'unmatched_records', 'conflicting_assignments', 'duplicates', 'warnings')}
        summary['assignment_types'] = groups
        summary['all_assignment_blocks_rendered'] = len(assignments) * len(BLOCKS)
        summary['data_blocks_rendered'] = len(assignments) * len(ACTIVE_BLOCKS)
        summary['form_sections'] = len(BLOCKS) - 1
        print(json.dumps(summary, indent=2, ensure_ascii=False))
        db.session.remove()
        db.engine.dispose()
