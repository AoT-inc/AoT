# coding=utf-8
import logging

from aot.databases import CRUDMixin, set_uuid
from aot.aot_flask.extensions import db

logger = logging.getLogger("aot.api_key")


class APIKey(CRUDMixin, db.Model):
    """
    Stores third-party API credentials used by AoT services.

    Each record holds a name, provider, key value, base URL, tag, and description
    for an external API. These are referenced by services that integrate with
    weather, SMS, email, or other remote providers.

    @phase active
    """
    __tablename__ = "api_key"
    __table_args__ = {'extend_existing': True}

    id = db.Column(db.Integer, unique=True, primary_key=True)
    unique_id = db.Column(db.String(36), nullable=False, unique=True, default=set_uuid)
    name = db.Column(db.String(128), default='')
    provider = db.Column(db.String(128), default='')
    key = db.Column(db.Text, default='')
    url = db.Column(db.Text, default='')
    tag = db.Column(db.String(128), default='')
    description = db.Column(db.Text, default='')

    def __repr__(self):
        return "<{cls}(id={s.id}, name={s.name})>".format(s=self, cls=self.__class__.__name__)
