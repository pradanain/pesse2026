"""Versioned acknowledgement bound to the current signed login session."""
from flask import session

VERSION = '20261101-v1'
EVENT = 'privacy_commitment_v1'


def accepted():
    return session.get('privacy_commitment') == VERSION
