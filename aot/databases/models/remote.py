# -*- coding: utf-8 -*-
from aot.databases import CRUDMixin
from aot.databases import set_uuid
from aot.aot_flask.extensions import db


class Remote(CRUDMixin, db.Model):
    """
    Stores connection info for another AoT instance managed via the
    Remote Admin Dashboard (host, username, and an issued access token).

    access_token is NOT the remote user's password hash — it is a
    dedicated, revocable bearer token issued by the remote instance
    specifically for this purpose (see RemoteAccessToken). Losing this
    value only exposes remote-admin dashboard access to that one host,
    and can be revoked/rotated on the remote side without touching the
    user's real login credentials.

    @phase active
    """
    __tablename__ = "remote"
    __table_args__ = {'extend_existing': True}

    id = db.Column(db.Integer, unique=True, primary_key=True)
    unique_id = db.Column(db.String(36), nullable=False, unique=True, default=set_uuid)
    is_activated = db.Column(db.Boolean, default=False)
    host = db.Column(db.Text, default='')
    username = db.Column(db.Text, default='')
    access_token = db.Column(db.Text, default='')

    def __repr__(self):
        return "<{cls}(id={s.id})>".format(s=self, cls=self.__class__.__name__)
