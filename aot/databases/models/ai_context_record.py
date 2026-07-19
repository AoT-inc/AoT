# coding=utf-8
from datetime import datetime

from aot.databases import CRUDMixin
from aot.databases import set_uuid
from aot.aot_flask.extensions import db


class AIContextRecord(CRUDMixin, db.Model):
    """
    Stores each context value with explicit trust state.
    Core of the three-state pipeline: system_generated, pending, user_confirmed.

    Context records represent parameter values that inform AI reasoning:
    - facility_id: links to the facility this context applies to
    - parameter_name: semantic identifier (e.g., 'temperature_air.warning_threshold')
    - value: JSON-serializable context value
    - source: origin marker ('domain_kr_module', 'user_note', 'sensor', 'ai_observation')
    - context_state: trust level ('system_generated', 'pending', 'user_confirmed')
    - confirmed_by/confirmed_at: metadata about user review/approval
    - expires_at: optional time window validity

    @phase active
    @stability stable
    """
    __tablename__ = "ai_context_record"
    __table_args__ = {'extend_existing': True}

    id = db.Column(db.Integer, unique=True, primary_key=True)
    unique_id = db.Column(db.String(36), nullable=False, unique=True, default=set_uuid)

    facility_id = db.Column(db.String(36), nullable=False, index=True)
    parameter_name = db.Column(db.String(100), nullable=False)
    value = db.Column(db.Text, nullable=False)

    source = db.Column(db.String(100), default=None)
    context_state = db.Column(db.String(20), default='system_generated')

    confirmed_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    confirmed_at = db.Column(db.DateTime, nullable=True)

    expires_at = db.Column(db.DateTime, nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    created_by = db.Column(db.String(20), default='system')

    def __repr__(self):
        return f"<{self.__class__.__name__}(id={self.id}, facility_id={self.facility_id}, param={self.parameter_name}, state={self.context_state})>"
