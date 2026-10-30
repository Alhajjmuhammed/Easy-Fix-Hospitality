"""Encrypting provider credentials (mobile money / SMS keys) at rest.

The key comes from settings.CREDENTIALS_ENCRYPTION_KEY when set (a Fernet key), otherwise it is
derived from SECRET_KEY. If that key changes, saved credentials can no longer be read and the
restaurant simply enters them again — nothing else breaks.
"""
import base64
import hashlib
import json

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings


def _fernet():
    key = getattr(settings, 'CREDENTIALS_ENCRYPTION_KEY', '') or ''
    if not key:
        digest = hashlib.sha256(('credentials:' + settings.SECRET_KEY).encode()).digest()
        key = base64.urlsafe_b64encode(digest)
    return Fernet(key)


def encrypt_dict(data):
    return _fernet().encrypt(json.dumps(data or {}).encode()).decode()


def decrypt_dict(token):
    if not token:
        return {}
    try:
        return json.loads(_fernet().decrypt(token.encode()).decode())
    except (InvalidToken, ValueError):
        return {}
