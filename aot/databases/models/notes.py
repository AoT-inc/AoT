# coding=utf-8
from aot.utils.time_utils import utc_now

from sqlalchemy.dialects.mysql import LONGTEXT

from aot.databases import CRUDMixin
from aot.databases import set_uuid
from aot.aot_flask.extensions import db


class Notes(CRUDMixin, db.Model):
    """
    Represents a human-written or system-generated note linked to a facility entity.

    Notes are timestamped entries that can be tagged, categorized, geotagged, and
    optionally linked to an AITask or SchedulerJobMeta as a parent. They support
    archival and context state tracking.

    @phase active
    """
    __tablename__ = "notes"
    __table_args__ = {'extend_existing': True}

    id = db.Column(db.Integer, unique=True, primary_key=True)
    unique_id = db.Column(db.String(36), nullable=False, unique=True, default=set_uuid)  # ID for influxdb entries
    date_time = db.Column(db.DateTime, default=utc_now)

    name = db.Column(db.Text, default=None)
    tags = db.Column(db.Text, default="")
    files = db.Column(db.Text, default=None)
    target_id = db.Column(db.String(36), default=None)
    target_type = db.Column(db.String(100), default=None)
    gps_lat = db.Column(db.Float, default=None)
    gps_lng = db.Column(db.Float, default=None)
    parent_task_id = db.Column(db.String(36), index=True)  # Link to AITask.unique_id or JobMeta.id


    category = db.Column(db.String(64), default='general')
    priority = db.Column(db.Integer, default=0) # 0: normal, 1: high, 2: critical
    is_archived = db.Column(db.Boolean, default=False)
    context_state = db.Column(db.String(20), default='system_generated', nullable=True)

    # Tier for adaptive document storage (1=hot/summary, 2=warm/standard, 3=cold/archive)
    tier = db.Column(db.Integer, default=2, nullable=False, index=True)

    note = db.Column(db.Text().with_variant(LONGTEXT, "mysql", "mariadb"), default=None)
    
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), default=None)
    author = db.relationship("User", foreign_keys=[user_id])

    def __repr__(self):
        return "<{cls}(id={s.id})>".format(s=self, cls=self.__class__.__name__)


class NoteTags(CRUDMixin, db.Model):
    """
    Defines a tag label that can be applied to Notes for categorization.

    @phase active
    """
    __tablename__ = "note_tags"
    __table_args__ = {'extend_existing': True}

    id = db.Column(db.Integer, unique=True, primary_key=True)
    unique_id = db.Column(db.String(36), nullable=False, unique=True, default=set_uuid)  # ID for influxdb entries
    name = db.Column(db.Text, default=None)

    def __repr__(self):
        return "<{cls}(id={s.id})>".format(s=self, cls=self.__class__.__name__)
