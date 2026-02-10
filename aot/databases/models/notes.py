# coding=utf-8
import datetime

from sqlalchemy.dialects.mysql import LONGTEXT

from aot.databases import CRUDMixin
from aot.databases import set_uuid
from aot.aot_flask.extensions import db


class Notes(CRUDMixin, db.Model):
    __tablename__ = "notes"
    __table_args__ = {'extend_existing': True}

    id = db.Column(db.Integer, unique=True, primary_key=True)
    unique_id = db.Column(db.String(36), nullable=False, unique=True, default=set_uuid)  # ID for influxdb entries
    date_time = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    name = db.Column(db.Text, default=None)
    tags = db.Column(db.Text, default="")
    files = db.Column(db.Text, default=None)
    target_id = db.Column(db.String(36), default=None)
    target_type = db.Column(db.String(100), default=None)
    gps_lat = db.Column(db.Float, default=None)
    gps_lng = db.Column(db.Float, default=None)
    note = db.Column(db.Text().with_variant(LONGTEXT, "mysql", "mariadb"), default=None)
    
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), default=None)
    author = db.relationship("User", foreign_keys=[user_id])

    def __repr__(self):
        return "<{cls}(id={s.id})>".format(s=self, cls=self.__class__.__name__)


class NoteTags(CRUDMixin, db.Model):
    __tablename__ = "note_tags"
    __table_args__ = {'extend_existing': True}

    id = db.Column(db.Integer, unique=True, primary_key=True)
    unique_id = db.Column(db.String(36), nullable=False, unique=True, default=set_uuid)  # ID for influxdb entries
    name = db.Column(db.Text, default=None)

    def __repr__(self):
        return "<{cls}(id={s.id})>".format(s=self, cls=self.__class__.__name__)
