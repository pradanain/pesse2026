import hashlib
import hmac
import secrets
import time

from flask import current_app, session
from sqlalchemy.dialects.sqlite import insert
from .models import db, AuthSession, AuditEvent, LoginAttempt


def session_stamp(user):
    # Changing a password invalidates earlier sessions without storing the hash in cookies.
    return hmac.new(current_app.secret_key.encode(),
                    f'{user.id}:{user.password_hash}'.encode(), hashlib.sha256).hexdigest()


def event(name, actor_id=None, target_id=None):
    db.session.add(AuditEvent(at=time.time(), event=name, actor_id=actor_id, target_id=target_id))


def token_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


def start_session(user):
    token = secrets.token_urlsafe(32)
    now = time.time()
    db.session.query(AuthSession).filter(AuthSession.expires_at <= now).delete()
    old = session.get('session_token')
    if isinstance(old, str):
        db.session.query(AuthSession).filter_by(token_hash=token_hash(old)).delete()
    db.session.add(AuthSession(token_hash=token_hash(token), user_id=user.id, created_at=now,
        last_seen=now, expires_at=now + current_app.permanent_session_lifetime.total_seconds()))
    event('login_success', user.id)
    db.session.commit()
    session.clear()
    session.update(user_id=user.id, auth_stamp=session_stamp(user), session_token=token)
    session.permanent = True


def valid_session(user):
    token, stamp = session.get('session_token'), session.get('auth_stamp')
    if not isinstance(token, str) or len(token) > 128 or not isinstance(stamp, str):
        return False
    if not stamp.isascii() or not hmac.compare_digest(stamp, session_stamp(user)):
        return False
    record = db.session.get(AuthSession, token_hash(token))
    now = time.time()
    if not record or record.user_id != user.id or record.expires_at <= now or now - record.last_seen > current_app.config['SESSION_IDLE_SECONDS']:
        return False
    if now - record.last_seen > 300:
        record.last_seen = now
        db.session.commit()
    return True


def end_session(user):
    token = session.get('session_token')
    if isinstance(token, str):
        db.session.query(AuthSession).filter_by(token_hash=token_hash(token)).delete()
    event('logout', user.id)
    db.session.commit()
    session.clear()


def revoke_sessions(user_id):
    db.session.query(AuthSession).filter_by(user_id=user_id).delete()


def throttle_keys(username, address):
    secret = current_app.secret_key.encode()
    return {kind: hmac.new(secret, text.encode(), hashlib.sha256).hexdigest()
            for kind, text in {'account': 'user:' + username, 'pair': 'pair:' + username + ':' + address, 'ip': 'ip:' + address}.items()}


def retry_after(keys, now):
    retry = 0
    for kind, key in keys.items():
        record = db.session.get(LoginAttempt, key)
        threshold = 100 if kind == 'ip' else 8
        if record and now - record.window < 900 and record.failures >= threshold:
            retry = max(retry, int(900 - (now - record.window)) + 1)
    return retry


def failed_login(keys, now, user_id=None):
    # SQLite UPSERT prevents a duplicate-key race when workers see a new key together.
    for key in keys.values():
        statement = insert(LoginAttempt).values(key=key, failures=1, window=now)
        statement = statement.on_conflict_do_update(index_elements=['key'], set_={
            'failures': db.case((LoginAttempt.window <= now - 900, 1), else_=LoginAttempt.failures + 1),
            'window': db.case((LoginAttempt.window <= now - 900, now), else_=LoginAttempt.window)})
        db.session.execute(statement)
    db.session.query(LoginAttempt).filter(LoginAttempt.window < now - 86400).delete()
    event('login_failed', target_id=user_id)
    db.session.commit()
