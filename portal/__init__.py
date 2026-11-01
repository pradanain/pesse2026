import os
import secrets
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

from flask import Flask, g, session, render_template, request, abort
from flask_wtf.csrf import CSRFProtect
from sqlalchemy import event
from sqlalchemy.engine import Engine

from .models import db, User
from .auth import valid_session
from .config import env_bool


@event.listens_for(Engine, 'connect')
def sqlite_config(connection, _):
    if connection.__class__.__module__.startswith('sqlite3'):
        connection.execute('PRAGMA foreign_keys=ON')
        connection.execute('PRAGMA busy_timeout=10000')


def create_app(config=None):
    app = Flask(__name__, instance_relative_config=True)
    Path(app.instance_path).mkdir(parents=True, exist_ok=True)
    secret = os.environ.get('SECRET_KEY')
    if not secret and not (config and config.get('TESTING')):
        secret_file = Path(app.instance_path) / 'secret.key'
        if not secret_file.exists():
            try:
                with secret_file.open('x', encoding='utf-8') as f:
                    f.write(secrets.token_hex(32))
                secret_file.chmod(0o600)
            except FileExistsError:
                pass
        secret = secret_file.read_text(encoding='utf-8').strip()
    app.config.update(SECRET_KEY=secret, SQLALCHEMY_DATABASE_URI=os.environ.get('DATABASE_URL', 'sqlite:///' + str(Path(app.instance_path) / 'portal.sqlite3').replace('\\', '/')),
                      AUTH_REQUIRED=env_bool('AUTH_REQUIRED', True),
                      SQLALCHEMY_ENGINE_OPTIONS={'hide_parameters': True},
                      SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE='Lax', SESSION_COOKIE_SECURE=env_bool('COOKIE_SECURE'),
                      SESSION_IDLE_SECONDS=1800,
                      PERMANENT_SESSION_LIFETIME=timedelta(hours=8), MAX_CONTENT_LENGTH=1024 * 1024, WTF_CSRF_TIME_LIMIT=28800)
    if config:
        app.config.update(config)
    db.init_app(app)
    CSRFProtect(app)
    app.jinja_env.globals['icon'] = app.jinja_env.get_template('components/icons.html').module.icon
    from .metadata import existence_label
    app.jinja_env.filters['existence_label'] = existence_label
    if env_bool('TRUST_PROXY'):
        from werkzeug.middleware.proxy_fix import ProxyFix
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    @app.before_request
    def load_user():
        if not app.config['AUTH_REQUIRED']:
            if not app.testing and request.remote_addr not in ('127.0.0.1', '::1'):
                abort(403)
            # Local read-only mode intentionally has no account/session dependency.
            g.user = SimpleNamespace(id=None, username='Lokal', role='admin', sensitive=True, active=True)
            return
        user_id = session.get('user_id')
        g.user = db.session.get(User, user_id) if type(user_id) is int else None
        if g.user and (not g.user.active or not valid_session(g.user)):
            session.clear(); g.user = None

    @app.after_request
    def secure_headers(response):
        response.headers['Cache-Control'] = 'public, max-age=31536000, immutable' if request.endpoint == 'static' and request.args.get('v') else 'public, max-age=3600' if request.endpoint == 'static' else 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['Referrer-Policy'] = 'same-origin'
        response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
        if app.config['SESSION_COOKIE_SECURE']:
            response.headers['Strict-Transport-Security'] = 'max-age=31536000'
        return response

    for code in (400, 403, 404, 429, 500):
        app.register_error_handler(code, lambda error: (render_template('error.html', code=error.code), error.code))
    from .routes import bp
    app.register_blueprint(bp)
    from .cli import register_cli
    register_cli(app)
    return app
