# -*- coding: utf-8 -*-
from aot.databases import CRUDMixin
from aot.databases import set_uuid
from aot.aot_flask.extensions import db


class Remote(CRUDMixin, db.Model):
    """
    Stores SSH/RDP credentials for connecting to remote headless hosts.

    Each Remote record holds host, username, and password hash for a remote machine
    that can receive commands from AoT via secure shell or remote desktop.

    @phase active
    """
    __tablename__ = "remote"
    __table_args__ = {'extend_existing': True}

    id = db.Column(db.Integer, unique=True, primary_key=True)
    unique_id = db.Column(db.String(36), nullable=False, unique=True, default=set_uuid)
    is_activated = db.Column(db.Boolean, default=False)
    host = db.Column(db.Text, default='')
    username = db.Column(db.Text, default='')
    password_hash = db.Column(db.Text, default='')

    def __repr__(self):
        return "<{cls}(id={s.id})>".format(s=self, cls=self.__class__.__name__)
