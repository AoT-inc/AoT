# coding=utf-8
from aot.utils.time_utils import utc_now
from aot.databases import CRUDMixin
from aot.databases import set_uuid
from aot.aot_flask.extensions import db

class OrchWorkflow(CRUDMixin, db.Model):
    """
    Represents a collection of tasks with dependencies.

    @phase active
    @stability stable
    """
    __tablename__ = "orch_workflow"
    __table_args__ = {'extend_existing': True}

    id = db.Column(db.Integer, unique=True, primary_key=True)
    unique_id = db.Column(db.String(36), nullable=False, unique=True, default=set_uuid)
    
    name = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text, default='')
    
    # status: pending, running, completed, failed, cancelled
    status = db.Column(db.String(20), default='pending')
    
    created_at = db.Column(db.DateTime, default=utc_now)
    completed_at = db.Column(db.DateTime, nullable=True)
    
    metadata_json = db.Column(db.Text, default='{}')

    def __repr__(self):
        return f"<OrchWorkflow(name={self.name}, status={self.status})>"
