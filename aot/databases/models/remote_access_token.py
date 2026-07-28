# -*- coding: utf-8 -*-
import hashlib
import hmac
import secrets

from aot.databases import CRUDMixin
from aot.databases import set_uuid
from aot.aot_flask.extensions import db


class RemoteAccessToken(CRUDMixin, db.Model):
    """
    Issued credential for the Remote Admin Dashboard feature.

    A hub AoT instance authenticates once with a user's real password
    (see routes_authentication.newremote) and receives a high-entropy
    opaque token in return. That token is unrelated to the user's actual
    password hash — it is scoped to remote-admin access only, can be
    revoked or rotated independently, and only its SHA-256 digest is
    stored here (never the raw token). SHA-256 (not bcrypt) is
    appropriate because the token already has 256 bits of entropy from
    secrets.token_urlsafe(32); bcrypt's deliberate slowness defends
    against brute-forcing low-entropy human passwords, which doesn't
    apply here.

    @phase active
    @dependency User
    """
    __tablename__ = "remote_access_token"
    __table_args__ = {'extend_existing': True}

    id = db.Column(db.Integer, primary_key=True)
    unique_id = db.Column(db.String(36), nullable=False, unique=True, default=set_uuid)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    token_hash = db.Column(db.String(64), nullable=False, unique=True, index=True)
    label = db.Column(db.Text, default='')
    created_at = db.Column(db.DateTime, nullable=False)
    last_used_at = db.Column(db.DateTime, default=None)
    revoked = db.Column(db.Boolean, nullable=False, default=False)

    def __repr__(self):
        return "<{cls}(id={s.id}, user_id={s.user_id}, revoked={s.revoked})>".format(
            s=self, cls=self.__class__.__name__)

    @staticmethod
    def generate_raw_token():
        """Generate a new high-entropy bearer token (returned to the caller once)."""
        return secrets.token_urlsafe(32)

    @staticmethod
    def hash_token(raw_token):
        if isinstance(raw_token, str):
            raw_token = raw_token.encode('utf-8')
        return hashlib.sha256(raw_token).hexdigest()

    @classmethod
    def find_valid(cls, user_id, raw_token):
        """Return the matching non-revoked token row for user_id, or None.

        Compares by hash lookup (indexed, O(1)) then confirms with a
        constant-time comparison to avoid any timing side-channel on the
        hash column itself.
        """
        candidate_hash = cls.hash_token(raw_token)
        row = cls.query.filter_by(
            user_id=user_id, token_hash=candidate_hash, revoked=False).first()
        if row and hmac.compare_digest(row.token_hash, candidate_hash):
            return row
        return None
