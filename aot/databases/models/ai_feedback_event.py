# coding=utf-8
from datetime import datetime

from aot.databases import CRUDMixin
from aot.databases import set_uuid
from aot.aot_flask.extensions import db


class AIFeedbackEvent(CRUDMixin, db.Model):
    """
    Append-only log of every user feedback action.

    Primary evidence of co-growth and learning. Records all interaction types:
    - confirmed: user approved a parameter value
    - rejected: user disagreed with AI recommendation
    - dismissed: user acknowledged but did not act on suggestion

    Fields:
    - facility_id: which facility this feedback applies to
    - user_id: which operator provided the feedback
    - event_type: 'confirmed', 'rejected', or 'dismissed'
    - parameter_name: which parameter was affected
    - previous_value: what was the old value (if applicable)
    - new_value: what the new value is (if applicable)
    - reasoning: optional user note explaining their feedback
    - context_record_id: links to the AIContextRecord this feedback addresses

    This table is append-only. Never update or delete rows.
    This is the audit trail that makes learning progress verifiable.

    @phase active
    @stability stable
    @dependency AIContextRecord, User
    """
    __tablename__ = "ai_feedback_event"
    __table_args__ = {'extend_existing': True}

    id = db.Column(db.Integer, unique=True, primary_key=True)
    unique_id = db.Column(db.String(36), nullable=False, unique=True, default=set_uuid)

    facility_id = db.Column(db.String(36), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)

    event_type = db.Column(db.String(20), nullable=False)
    parameter_name = db.Column(db.String(100), nullable=False)

    previous_value = db.Column(db.Text, nullable=True)
    new_value = db.Column(db.Text, nullable=True)
    reasoning = db.Column(db.Text, nullable=True)

    context_record_id = db.Column(db.String(36), nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f"<{self.__class__.__name__}(id={self.id}, facility_id={self.facility_id}, event={self.event_type}, param={self.parameter_name})>"
