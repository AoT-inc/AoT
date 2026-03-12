# coding=utf-8
import datetime
import logging
from aot.databases import CRUDMixin
from aot.aot_flask.extensions import db

logger = logging.getLogger("aot.guest_login_token")

class GuestLoginToken(CRUDMixin, db.Model):
    __tablename__ = "guest_login_token"
    __table_args__ = {'extend_existing': True}

    id = db.Column(db.Integer, primary_key=True)
    token = db.Column(db.String(128), unique=True, nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    expires_at = db.Column(db.DateTime, nullable=False)
    used = db.Column(db.Boolean, default=False)

    def __repr__(self):
        return f"<GuestLoginToken(id={self.id}, token={self.token}, user_id={self.user_id}, used={self.used})>"
