# coding=utf-8
from datetime import datetime

from aot.databases import CRUDMixin
from aot.databases import set_uuid
from aot.aot_flask.extensions import db


class AIOnboardingRecord(CRUDMixin, db.Model):
    """
    Records the formal onboarding contract acknowledgment per facility.

    Answers the foundational question: Did this user acknowledge the system's
    limitations and agree to the learning period before AI operations began?

    Fields:
    - facility_id: which facility this onboarding applies to
    - user_id: which operator is onboarding
    - onboarding_started_at: when the onboarding flow began
    - contract_acknowledged_at: when user formally accepted learning-period terms
    - onboarding_completed_at: when first operational phase is cleared to begin
    - facility_type: user-provided facility category (e.g., 'greenhouse', 'field')
    - operator_experience: user's domain expertise ('novice', 'practitioner', 'expert')
    - critical_parameters_json: JSON list of parameters user flagged as critical
    - notes: any additional context from the onboarding conversation

    One record per (facility_id, user_id) pair.
    contract_acknowledged_at being NULL means onboarding is incomplete.

    @phase active
    @stability stable
    @dependency User
    """
    __tablename__ = "ai_onboarding_record"
    __table_args__ = {'extend_existing': True}

    id = db.Column(db.Integer, unique=True, primary_key=True)
    unique_id = db.Column(db.String(36), nullable=False, unique=True, default=set_uuid)

    facility_id = db.Column(db.String(36), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)

    onboarding_started_at = db.Column(db.DateTime, default=datetime.utcnow)
    contract_acknowledged_at = db.Column(db.DateTime, nullable=True)
    onboarding_completed_at = db.Column(db.DateTime, nullable=True)

    facility_type = db.Column(db.String(50), nullable=True)
    operator_experience = db.Column(db.String(20), nullable=True)
    critical_parameters_json = db.Column(db.Text, nullable=True)
    notes = db.Column(db.Text, nullable=True)

    def __repr__(self):
        return f"<{self.__class__.__name__}(facility_id={self.facility_id}, user_id={self.user_id}, acknowledged={self.contract_acknowledged_at is not None})>"
