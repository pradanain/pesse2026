"""Additive, versioned schema migration; does not rewrite source data or users."""
from .models import db, SchemaVersion

SCHEMA_VERSION = '20261101_01'


def migrate_schema():
    db.create_all()
    if not db.session.get(SchemaVersion, SCHEMA_VERSION):
        db.session.add(SchemaVersion(version=SCHEMA_VERSION))
    db.session.commit()
