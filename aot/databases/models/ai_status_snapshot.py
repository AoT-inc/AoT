# coding=utf-8
from datetime import datetime

from aot.databases import CRUDMixin
from aot.aot_flask.extensions import db


class AIStatusSnapshot(CRUDMixin, db.Model):
    """
    Cached snapshot of AI status data for a facility.

    Prevents expensive re-calculation on every page load.
    Refresh intervals are based on how long the user has been onboarded
    (week_number), following a tapering cadence: daily in week 1, then
    progressively less frequent to once-monthly for long-term users.

    One record is kept per facility. On each page load the route checks
    whether the snapshot is still fresh; if stale it recalculates and
    overwrites this record.

    snapshot_data JSON shape:
        {
            "learning_progress": {
                "total": int,
                "confirmed": int,
                "pending": int
            },
            "keywords": [{"keyword": str, "confirmed_count": int}, ...],
            "features": [{"action_type": str, "count": int}, ...],
            "calculated_at": "ISO 8601 string"
        }

    @phase active
    @stability stable
    """
    __tablename__ = "ai_status_snapshot"
    __table_args__ = {'extend_existing': True}

    id = db.Column(db.Integer, unique=True, primary_key=True)
    facility_id = db.Column(db.String(36), nullable=False, index=True)
    snapshot_data = db.Column(db.Text, nullable=False, default='{}')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    week_number = db.Column(db.Integer, default=1)

    def __repr__(self):
        return f"<AIStatusSnapshot(facility_id={self.facility_id}, week={self.week_number}, created={self.created_at})>"
