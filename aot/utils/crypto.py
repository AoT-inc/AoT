# coding=utf-8
"""
Symmetric encryption-at-rest for sensitive credentials (OAuth refresh tokens,
the SMTP account password).

Most other tokens in this codebase are still plaintext db.Text (APIKey.key,
Misc.chirpstack_api_token, ...). OAuth refresh tokens and the SMTP password are
the exceptions: they grant standing access to a user's *personal* external
account (a mail-account app password often unlocks the whole mailbox), so they
are encrypted before hitting the DB. This is the one encryption-at-rest helper
in the project.

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


# --- Marked ciphertext for columns that used to hold plaintext -------------
#
# A column that already exists as plaintext (SMTP.passw) cannot tell "not yet
# migrated" from "ciphertext" on its own, so stored values carry a prefix.
# That makes the migration idempotent (the daemon and the web app both run
# alembic; a second pass must not encrypt the ciphertext again) and lets the
# reader distinguish an old plaintext value from one it cannot decrypt.
SEALED_PREFIX = 'aotenc1:'

# Result of open_sealed() — why a value could / could not be read.
SEALED_EMPTY = 'empty'                # nothing stored
SEALED_OK = 'ok'                      # decrypted
SEALED_LEGACY = 'legacy_plaintext'    # stored before encryption existed
SEALED_UNREADABLE = 'unreadable'      # encrypted with a different key / corrupt


def is_sealed(value):
    return isinstance(value, str) and value.startswith(SEALED_PREFIX)


def seal_secret(plaintext):
    """Encrypt and mark. None/empty stays None."""
    token = encrypt_secret(plaintext)
    return SEALED_PREFIX + token if token else None


def open_sealed(value):
    """Return (plaintext_or_None, state) for a stored value.

    A value from another install (a settings export restored on a machine with
    a different flask_secret_key) comes back as (None, SEALED_UNREADABLE) so the
    caller can ask for the secret again instead of trying to use garbage."""
    if not value:
        return None, SEALED_EMPTY
    if not is_sealed(value):
        return value, SEALED_LEGACY
    plaintext = decrypt_secret(value[len(SEALED_PREFIX):])
    if plaintext is None:
        return None, SEALED_UNREADABLE
    return plaintext, SEALED_OK
