# coding=utf-8
"""
Symmetric encryption-at-rest for sensitive credentials (OAuth refresh tokens).

The rest of this codebase stores tokens as plaintext db.Text (APIKey.key,
Misc.chirpstack_api_token, ...). OAuth refresh tokens are a deliberate
exception: they are long-lived credentials granting standing access to a
user's *personal* external account, so they are encrypted before hitting the
DB. This is the one encryption-at-rest helper in the project.

Key derivation: the Fernet key is derived from the existing Flask secret_key
file (databases/flask_secret_key, 32 random bytes generated on first run — see
aot/config/__init__.py) via HKDF-SHA256. No new secret to manage: rotating the
flask_secret_key file necessarily invalidates stored ciphertexts (callers must
treat a decrypt failure as "connection needs re-auth", not a crash).
"""
import base64
import logging

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

logger = logging.getLogger(__name__)

_fernet = None


def _get_fernet():
    """Lazily build the module-level Fernet from the Flask secret key.

    Imported lazily (inside the function) so this module has no import-time
    dependency on Flask app config — it can be imported by models/migrations
    that load before the app is configured."""
    global _fernet
    if _fernet is not None:
        return _fernet

    from aot.config import ProdConfig
    secret = ProdConfig.SECRET_KEY  # bytes (32 hex-encoded → 64 bytes as read)
    if isinstance(secret, str):
        secret = secret.encode()

    hkdf = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=None,
        info=b'aot-oauth-token-encryption-v1',
    )
    derived = hkdf.derive(secret)
    _fernet = Fernet(base64.urlsafe_b64encode(derived))
    return _fernet


def encrypt_secret(plaintext):
    """Encrypt a string for at-rest storage. Returns a str (urlsafe token), or
    None if given None/empty (so an absent token round-trips as absent, not as
    the ciphertext of an empty string)."""
    if not plaintext:
        return None
    if isinstance(plaintext, str):
        plaintext = plaintext.encode()
    return _get_fernet().encrypt(plaintext).decode()


def decrypt_secret(ciphertext):
    """Decrypt a value produced by encrypt_secret. Returns the plaintext str,
    or None on absent input OR on any decrypt failure (wrong/rotated key,
    corrupted value) — callers must treat None as "no usable credential" and
    prompt re-authentication rather than assuming success."""
    if not ciphertext:
        return None
    if isinstance(ciphertext, str):
        ciphertext = ciphertext.encode()
    try:
        return _get_fernet().decrypt(ciphertext).decode()
    except (InvalidToken, Exception) as exc:  # noqa: BLE001 — never leak crypto errors upward
        logger.warning("decrypt_secret failed (rotated key or corrupt value?): %s", type(exc).__name__)
        return None
