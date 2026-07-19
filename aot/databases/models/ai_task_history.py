# coding=utf-8
from datetime import datetime
from sqlalchemy.dialects.mysql import LONGTEXT

from aot.databases import CRUDMixin
from aot.databases import set_uuid
from aot.aot_flask.extensions import db

class AITaskHistory(CRUDMixin, db.Model):
    """
    Audit log for AITask status changes and AI architecture proposals.
    Supports tracking 'Who, When, and Why' for each state transition.

    @phase active
    @stability stable
    @dependency AITask
    """
    __tablename__ = "ai_task_history"
    __table_args__ = {'extend_existing': True}

    id = db.Column(db.Integer, unique=True, primary_key=True)
    unique_id = db.Column(db.String(36), nullable=False, unique=True, default=set_uuid)
    
    task_id = db.Column(db.String(36), db.ForeignKey('ai_task.unique_id'), nullable=False)
    
    # action: PROPOSED, CONFIRMED, REJECTED, COMPLETED, UPDATED
    action = db.Column(db.String(50), nullable=False)
    user_id = db.Column(db.String(36), nullable=True) # User or Agent unique_id
    
    reason = db.Column(db.Text().with_variant(LONGTEXT, "mysql", "mariadb"), nullable=True)
    snapshot_json = db.Column(db.Text().with_variant(LONGTEXT, "mysql", "mariadb"), default='{}')
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relationships
    task = db.relationship('AITask', backref=db.backref('history', cascade="all, delete-orphan"))

    def __repr__(self):
        return f"<AITaskHistory(task_id={self.task_id}, action={self.action}, at={self.created_at})>"
