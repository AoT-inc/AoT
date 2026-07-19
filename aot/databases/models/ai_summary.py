# coding=utf-8
from datetime import datetime
from aot.databases import CRUDMixin
from aot.databases import set_uuid
from aot.aot_flask.extensions import db

class AISystemSummary(CRUDMixin, db.Model):
    """
    v26.0: AI Semantic Snapshot Core Model.
    Stores natural language summaries of system state at various hierarchical levels.

    @phase active
    @stability stable
    """
    __tablename__ = 'ai_system_summary'
    __table_args__ = (
        db.Index('idx_scope_time', 'scope_type', 'scope_id', 'timestamp'),
        {'extend_existing': True}
    )
    
    # Primary identification
    id = db.Column(db.Integer, primary_key=True)
    unique_id = db.Column(db.String(36), unique=True, nullable=False, index=True, default=set_uuid)
    
    # Temporal tracking
    timestamp = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)
    
    # Summary content
    summary_text = db.Column(db.Text, nullable=False)
    
    # Scope definition (System > Farm > DeviceGroup > Device)
    scope_type = db.Column(db.String(20), nullable=False, index=True)
    scope_id = db.Column(db.String(50), nullable=True, index=True)
    
    # Version control & Incremental tracking
    version = db.Column(db.Integer, nullable=False, default=1)
    previous_summary_id = db.Column(db.String(36), nullable=True)
    
    # Metrics & Performance
    generation_time_ms = db.Column(db.Integer, nullable=False, default=0)
    token_count = db.Column(db.Integer, nullable=False, default=0)
    
    # Anomaly Detection results
    anomaly_detected = db.Column(db.Boolean, default=False, index=True)
    alert_level = db.Column(db.String(10), default='none') # none, info, warning, critical
    
    # Incremental Change Summary
    change_summary = db.Column(db.Text, nullable=True)
    
    # Quality & Metadata
    quality_score = db.Column(db.Float, nullable=True)
    metadata_json = db.Column(db.Text, nullable=True, default='{}') # Stores raw metrics for comparison
    
    # Status Management
    is_active = db.Column(db.Boolean, default=True, index=True)
    
    # Relationships
    feedbacks = db.relationship('AISystemSummaryFeedback', backref='summary', lazy='dynamic')

    def __repr__(self):
        return f"<AISystemSummary(scope={self.scope_type}:{self.scope_id}, version={self.version}, alert={self.alert_level})>"

class AISystemSummaryFeedback(CRUDMixin, db.Model):
    """
    v26.0: User feedback for AI-generated summaries.

    @phase active
    @stability stable
    @dependency AISystemSummary
    """
    __tablename__ = 'ai_system_summary_feedback'
    __table_args__ = (
        db.Index('idx_summary_user', 'summary_id', 'user_id'),
        {'extend_existing': True}
    )
    
    id = db.Column(db.Integer, primary_key=True)
    summary_id = db.Column(db.String(36), db.ForeignKey('ai_system_summary.unique_id'), nullable=False, index=True)
    user_id = db.Column(db.String(50), nullable=False, index=True)
    
    rating = db.Column(db.Integer, nullable=False) # 1-5 scale
    feedback_text = db.Column(db.Text, nullable=True)
    timestamp = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    def __repr__(self):
        return f"<AISystemSummaryFeedback(user={self.user_id}, rating={self.rating})>"
