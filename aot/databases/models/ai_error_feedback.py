# coding=utf-8
from datetime import datetime
from aot.databases import CRUDMixin
from aot.databases import set_uuid
from aot.aot_flask.extensions import db

class AIErrorFeedback(CRUDMixin, db.Model):
    """
    User-reported AI errors for self-learning and correction.
    Tracks incorrect responses, inappropriate actions, and hallucinations.

    @phase active
    @stability stable
    @dependency AIHistory
    """
    __tablename__ = 'ai_error_feedback'
    __table_args__ = (
        db.Index('idx_thread_agent', 'thread_id', 'agent_id'),
        db.Index('idx_error_type_severity', 'error_type', 'severity'),
        db.Index('idx_status', 'status'),
        {'extend_existing': True}
    )
    
    # Primary identification
    id = db.Column(db.Integer, primary_key=True)
    unique_id = db.Column(db.String(36), unique=True, nullable=False, index=True, default=set_uuid)
    
    # Error context
    history_id = db.Column(db.String(36), db.ForeignKey('ai_history.unique_id'), nullable=False, index=True)
    thread_id = db.Column(db.String(36), nullable=False, index=True)
    agent_id = db.Column(db.String(36), nullable=True, index=True)
    
    # Error classification
    error_type = db.Column(db.String(50), nullable=False, index=True)
    # Types: 'misinformation', 'inappropriate_action', 'hallucination', 'tool_misuse', 'other'
    
    severity = db.Column(db.String(20), nullable=False, default='medium')
    # Severity: 'low', 'medium', 'high', 'critical'
    
    # Error content
    incorrect_response = db.Column(db.Text, nullable=False)
    user_correction = db.Column(db.Text, nullable=True)
    user_comment = db.Column(db.Text, nullable=True)
    
    # Context snapshot (for analysis)
    context_snapshot = db.Column(db.Text, nullable=True)  # JSON
    prompt_used = db.Column(db.Text, nullable=True)
    
    # Response status
    status = db.Column(db.String(20), nullable=False, default='reported', index=True)
    # Status: 'reported', 'acknowledged', 'corrected', 'learned', 'dismissed'
    
    correction_applied = db.Column(db.Boolean, default=False)
    
    # Metadata
    reported_by = db.Column(db.String(50), nullable=False)
    reported_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)
    resolved_at = db.Column(db.DateTime, nullable=True)
    resolved_by = db.Column(db.String(50), nullable=True)
    
    # Learning integration
    added_to_knowledge_base = db.Column(db.Boolean, default=False)
    added_to_glossary = db.Column(db.Boolean, default=False)
    added_to_training_data = db.Column(db.Boolean, default=False)
    
    # Admin notes
    admin_notes = db.Column(db.Text, nullable=True)
    
    # Relationships
    history = db.relationship('AIHistory', backref='error_feedbacks', lazy='joined')

    def __repr__(self):
        return f"<AIErrorFeedback(type={self.error_type}, severity={self.severity}, status={self.status})>"
