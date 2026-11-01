import math
import time
from urllib.parse import urlsplit
from functools import wraps

from flask import Blueprint, abort, current_app, g, jsonify, redirect, render_template, request, session, url_for
from sqlalchemy import func, or_, text, inspect
from sqlalchemy.exc import SQLAlchemyError
from werkzeug.security import check_password_hash, generate_password_hash

from .models import db, Region, Assignment, Dataset, LoginAttempt
from .models import User, SourceRecord, SchemaVersion
from .services import allowed_regions, authorize_region, get_assignment, block_data, BLOCKS
from .form_layout import ACTIVE_BLOCKS, PRIVATE_BLOCKS
from .importer import valid_coordinates
from .metadata import existence_label
from .auth import start_session, end_session, throttle_keys, retry_after, failed_login
from .migrations import SCHEMA_VERSION
from .commitment import accepted, VERSION as COMMITMENT_VERSION, EVENT as COMMITMENT_EVENT
from .auth import event as audit_event

bp = Blueprint('web', __name__)
DUMMY_HASH = generate_password_hash('not-a-real-account-' + str(time.time()))


def login_required(fn):
    @wraps(fn)
    def decorated(*args, **kwargs):
        if not g.user:
            if request.path.endswith('/block') or request.headers.get('X-Portal-Request') == '1':
                abort(403)
            return redirect(url_for('web.login', next=request.full_path.rstrip('?')))
        if current_app.config['AUTH_REQUIRED'] and fn.__name__ not in ('commitment', 'logout') and not accepted():
            if request.path.endswith('/block') or request.headers.get('X-Portal-Request') == '1':
                abort(403)
            return redirect(url_for('web.commitment', next=request.full_path.rstrip('?')))
        return fn(*args, **kwargs)
    return decorated


def safe_destination(value):
    try:
        parts = urlsplit(value)
    except ValueError:
        return url_for('web.regions')
    if value.startswith('/') and not value.startswith('//') and not parts.netloc and not parts.scheme and '\\' not in value and not any(ord(char) < 32 for char in value):
        return value
    return url_for('web.regions')


@bp.route('/commitment', methods=['GET', 'POST'])
@login_required
def commitment():
    destination = safe_destination(request.args.get('next', ''))
    if not current_app.config['AUTH_REQUIRED'] or accepted():
        return redirect(destination if urlsplit(destination).path != '/commitment' else url_for('web.regions'))
    if request.method == 'POST':
        if request.form.get('decision') != 'accept':
            abort(400)
        audit_event(COMMITMENT_EVENT, g.user.id)
        db.session.commit()
        session['privacy_commitment'] = COMMITMENT_VERSION
        return redirect(destination if urlsplit(destination).path != '/commitment' else url_for('web.regions'))
    return render_template('commitment.html', destination=destination)


@bp.route('/login', methods=['GET', 'POST'])
def login():
    if not current_app.config['AUTH_REQUIRED']:
        return redirect(url_for('web.regions'))
    error = None
    if request.method == 'POST':
        username = request.form.get('username', '').strip()[:80].casefold()
        password = request.form.get('password', '')[:512]
        keys = throttle_keys(username, request.remote_addr or '')
        now = time.time()
        retry = retry_after(keys, now)
        if retry:
            return render_template('error.html', code=429), 429, {'Retry-After': str(retry)}
        user = db.session.query(User).filter(func.lower(User.username) == username).first()
        valid = check_password_hash(user.password_hash if user else DUMMY_HASH, password)
        if user and user.active and valid:
            db.session.query(LoginAttempt).filter(LoginAttempt.key.in_([keys['account'], keys['pair']])).delete()
            start_session(user)
            return redirect(safe_destination(request.args.get('next', '')))
        failed_login(keys, now, user.id if user else None)
        error = 'Nama pengguna atau kata sandi tidak sesuai.'
    return render_template('login.html', error=error, username=request.form.get('username', '')[:80])


@bp.post('/logout')
@login_required
def logout():
    end_session(g.user)
    return redirect(url_for('web.login' if current_app.config['AUTH_REQUIRED'] else 'web.regions'))


@bp.get('/health')
def health():
    db.session.execute(text('SELECT 1'))
    return jsonify(status='ok')


@bp.get('/ready')
def ready():
    try:
        required = {'user', 'region', 'assignment', 'source_record', 'dataset', 'grant', 'supervision', 'login_attempt', 'auth_session', 'audit_event', 'schema_version'}
        valid = required.issubset(inspect(db.engine).get_table_names())
        valid = valid and db.session.get(SchemaVersion, SCHEMA_VERSION) is not None
        valid = valid and db.session.get(Dataset, 1) is not None and db.session.query(Region).first() is not None
        valid = valid and db.session.query(User.id).filter_by(role='admin', active=True).first() is not None
        return jsonify(status='ready' if valid else 'not_ready'), 200 if valid else 503
    except SQLAlchemyError:
        db.session.rollback()
        return jsonify(status='not_ready'), 503


@bp.get('/')
@login_required
def regions():
    allowed = allowed_regions()
    query = db.session.query(Region)
    aq = db.session.query(Assignment).filter_by(latest=True)
    if allowed is not None:
        query = query.filter(Region.code.in_(allowed)); aq = aq.filter(Assignment.region.in_(allowed))
    all_regions = query.order_by(Region.district, Region.village, Region.name).all()
    districts = sorted({r.district for r in all_regions})
    q = request.args.get('q', '').strip()[:200].casefold()
    district = request.args.get('district', '')
    visible = [r for r in all_regions if (not q or q in ' '.join((r.code, r.district, r.village, r.name)).casefold()) and (not district or r.district == district)]
    counts = {row[0]: row[1:] for row in aq.with_entities(Assignment.region, func.count(), func.sum(db.case((Assignment.kind == 'Keluarga', 1), else_=0)), func.sum(db.case((Assignment.kind == 'BKU', 1), else_=0)), func.sum(Assignment.businesses)).group_by(Assignment.region)}
    total = aq.count()
    member_total = aq.with_entities(func.coalesce(func.sum(Assignment.members), 0)).scalar()
    business_total = sum((c[3] or 0) for c in counts.values())
    return render_template('regions.html', regions=visible, districts=districts, counts=counts, total=total,
                           member_total=member_total, business_total=business_total, region_total=len(all_regions),
                           district=district, q=request.args.get('q', ''), dataset=db.session.get(Dataset, 1))


@bp.get('/sls/<code>')
@login_required
def assignments(code):
    authorize_region(code)
    region = db.get_or_404(Region, code)
    query = db.session.query(Assignment).filter_by(region=code, latest=True)
    status_pairs = query.with_entities(Assignment.existence, Assignment.kind).distinct().all()
    statuses = sorted({r[0] for r in status_pairs})
    status_labels = {}
    for status in statuses:
        variants = [(kind, existence_label(kind, status)) for raw, kind in status_pairs if raw == status]
        texts = list(dict.fromkeys(text for _, text in variants))
        status_labels[status] = texts[0] if len(texts) == 1 else ' / '.join(kind + ': ' + text for kind, text in variants)
    q = request.args.get('q', '').strip()[:200]
    if q:
        query = query.filter(or_(Assignment.name.contains(q, autoescape=True), Assignment.building.contains(q, autoescape=True), Assignment.source_id.contains(q, autoescape=True)))
    if request.args.get('kind') in ('Keluarga', 'BKU', 'Belum teridentifikasi'):
        query = query.filter_by(kind=request.args['kind'])
    if request.args.get('existence'):
        query = query.filter_by(existence=request.args['existence'])
    if request.args.get('review') == '1':
        query = query.filter(func.json_array_length(Assignment.issues) > 0)
    if request.args.get('sort') == 'name':
        query = query.order_by(Assignment.name, Assignment.id)
    else:
        query = query.order_by(Assignment.building == '', db.cast(Assignment.building, db.Integer), Assignment.name, Assignment.id)
    page = max(1, min(request.args.get('page', 1, type=int), 10000))
    page_size = 12
    count = query.count(); pages = max(1, math.ceil(count / page_size)); page = min(page, pages)
    return render_template('assignments.html', region=region, assignments=query.offset((page - 1) * page_size).limit(page_size).all(), count=count, pages=pages, page=page, page_size=page_size, statuses=statuses, status_labels=status_labels)


@bp.get('/assignment/<int:pk>')
@login_required
def detail(pk):
    a = get_assignment(pk)
    return render_template('detail.html', a=a, region=db.session.get(Region, a.region), blocks=BLOCKS,
                           sensitive=g.user.role == 'admin' or g.user.sensitive, private_blocks=PRIVATE_BLOCKS,
                           active_block_count=len(ACTIVE_BLOCKS))


@bp.get('/assignment/<int:pk>/<block>/block')
@login_required
def block(pk, block):
    a = get_assignment(pk)
    cards, ambiguous = block_data(a, block)
    maps = None
    if block == 'p':
        master = db.session.query(SourceRecord).filter_by(assignment_pk=a.id, source='master').first()
        if master and valid_coordinates(master.raw):
            maps = f"https://www.google.com/maps/search/?api=1&query={float(master.raw['geotag_latitude'])},{float(master.raw['geotag_longitude'])}"
    money_reference = any(field.get('money_masked') for card in cards for section in card['sections'] for field in section['fields'])
    return render_template('block.html', a=a, block=block, block_config=BLOCKS[block], cards=cards, ambiguous=ambiguous, maps=maps, money_reference=money_reference)


@bp.get('/dataset')
@login_required
def dataset():
    if g.user.role != 'admin':
        abort(403)
    return render_template('dataset.html', dataset=db.session.get(Dataset, 1))
