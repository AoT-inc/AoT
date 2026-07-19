# coding=utf-8
from datetime import datetime

from aot.databases import CRUDMixin
from aot.databases import set_uuid
from aot.aot_flask.extensions import db


class AIFacilityLearning(CRUDMixin, db.Model):
    """
    Tracks per-facility AI learning state and progress.

    This model captures the learning trajectory for a facility:
    - learning_started_at: when AI was activated for this facility
    - last_feedback_at: timestamp of most recent user confirmation
    - feedback_count_total: cumulative confirmations for this facility
    - confirmations_json: aggregated by category (e.g., {"environmental": {"confirmed": 8, "total": 12}})
    - learning_phase_active: whether system is still in calibration mode
    - stalled_since: set when no feedback received for N days
    - onboarding_complete: tracks if formal onboarding was completed

    One record per facility_id. Created at facility AI activation.

    @phase active
    @stability stable
    """
    __tablename__ = "ai_facility_learning"
    __table_args__ = {'extend_existing': True}

    id = db.Column(db.Integer, unique=True, primary_key=True)
    unique_id = db.Column(db.String(36), nullable=False, unique=True, default=set_uuid)

    facility_id = db.Column(db.String(36), nullable=False, unique=True, index=True)

    learning_started_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_feedback_at = db.Column(db.DateTime, nullable=True)

    feedback_count_total = db.Column(db.Integer, default=0)
    confirmations_json = db.Column(db.Text, default='{}')

    learning_phase_active = db.Column(db.Boolean, default=True)
    stalled_since = db.Column(db.DateTime, nullable=True)

    onboarding_complete = db.Column(db.Boolean, default=False)

    def __repr__(self):
        return f"<{self.__class__.__name__}(facility_id={self.facility_id}, feedbacks={self.feedback_count_total}, active={self.learning_phase_active})>"
