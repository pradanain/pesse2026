from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


class Region(db.Model):
    code = db.Column(db.String(32), primary_key=True)
    district = db.Column(db.String(150), nullable=False)
    village = db.Column(db.String(150), nullable=False)
    name = db.Column(db.String(150), nullable=False)
    expected = db.Column(db.Integer)


class Assignment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    source_id = db.Column(db.String(150), nullable=False, index=True)
    version = db.Column(db.String(40), nullable=False)
    region = db.Column(db.String(32), db.ForeignKey('region.code'), nullable=False, index=True)
    latest = db.Column(db.Boolean, default=True, nullable=False, index=True)
    name = db.Column(db.String(300), nullable=False)
    building = db.Column(db.String(50), nullable=False)
    kind = db.Column(db.String(30), nullable=False)
    status = db.Column(db.String(150), nullable=False)
    existence = db.Column(db.String(80), nullable=False)
    members = db.Column(db.Integer, default=0)
    businesses = db.Column(db.Integer, default=0)
    issues = db.Column(db.JSON, default=list)
    __table_args__ = (db.UniqueConstraint('source_id', 'version'),)


class SourceRecord(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    source = db.Column(db.String(40), index=True, nullable=False)
    assignment_pk = db.Column(db.Integer, db.ForeignKey('assignment.id'), index=True)
    source_id = db.Column(db.String(150), index=True)
    version = db.Column(db.String(40))
    roster_index = db.Column(db.String(80))
    sheet = db.Column(db.String(150))
    line = db.Column(db.Integer)
    raw = db.Column(db.JSON, nullable=False)
    ambiguous = db.Column(db.Boolean, default=False, nullable=False)


class Dataset(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    fingerprint = db.Column(db.String(64), nullable=False)
    imported_at = db.Column(db.String(40), nullable=False)
    report = db.Column(db.JSON, nullable=False)


class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(300), nullable=False)
    role = db.Column(db.String(20), nullable=False, default='petugas')
    sensitive = db.Column(db.Boolean, nullable=False, default=False)
    active = db.Column(db.Boolean, nullable=False, default=True)


class Grant(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    region = db.Column(db.String(32), nullable=False)
    __table_args__ = (db.UniqueConstraint('user_id', 'region'),)


class Supervision(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    pml_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    ppl_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, unique=True)


class LoginAttempt(db.Model):
    key = db.Column(db.String(64), primary_key=True)
    failures = db.Column(db.Integer, nullable=False, default=0)
    window = db.Column(db.Float, nullable=False)


class AuthSession(db.Model):
    token_hash = db.Column(db.String(64), primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    created_at = db.Column(db.Float, nullable=False)
    last_seen = db.Column(db.Float, nullable=False)
    expires_at = db.Column(db.Float, nullable=False, index=True)


class AuditEvent(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    at = db.Column(db.Float, nullable=False, index=True)
    event = db.Column(db.String(40), nullable=False)
    actor_id = db.Column(db.Integer)
    target_id = db.Column(db.Integer)


class SchemaVersion(db.Model):
    version = db.Column(db.String(40), primary_key=True)
