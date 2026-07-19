# coding=utf-8
from aot.utils.time_utils import utc_now
from aot.databases import CRUDMixin
from aot.databases import set_uuid
from aot.aot_flask.extensions import db

class OrchTask(CRUDMixin, db.Model):
    """
    Represents an actionable unit within the orchestration system.

    @phase active
    @stability stable
    @dependency OrchWorkflow, OrchDevice
    """
    __tablename__ = "orch_task"
    __table_args__ = {'extend_existing': True}

    id = db.Column(db.Integer, unique=True, primary_key=True)
    unique_id = db.Column(db.String(36), nullable=False, unique=True, default=set_uuid)
    
    workflow_id = db.Column(db.String(36), db.ForeignKey('orch_workflow.unique_id'), nullable=True)
    
    # Task Classification
    task_type = db.Column(db.String(50), nullable=False)  # data_collection, device_control, image_capture, ai_analysis, etc.
    priority = db.Column(db.Integer, default=5)  # 1 (High) - 10 (Low)
    
    # Assignment
    assigned_device_id = db.Column(db.String(36), db.ForeignKey('orch_device.unique_id'), nullable=True)
    
    # Status: pending, assigned, running, completed, failed, retrying, cancelled
    status = db.Column(db.String(20), default='pending')
    
    # Content & Parameters
    params_json = db.Column(db.Text, default='{}')
    result_json = db.Column(db.Text, default='{}')
    error_message = db.Column(db.Text, nullable=True)
    
    # Execution Tracking
    retry_count = db.Column(db.Integer, default=0)
    max_retries = db.Column(db.Integer, default=3)
    
    created_at = db.Column(db.DateTime, default=utc_now)
    started_at = db.Column(db.DateTime, nullable=True)
    completed_at = db.Column(db.DateTime, nullable=True)
    deadline = db.Column(db.DateTime, nullable=True)
    
    # Dependency Management (Comma-separated list of orch_task.unique_id)
    dependencies = db.Column(db.Text, default='[]')

    # Relationships
    workflow = db.relationship('OrchWorkflow', backref=db.backref('tasks', cascade="all, delete-orphan"))
    device = db.relationship('OrchDevice', backref=db.backref('tasks'))

    def __repr__(self):
        return f"<OrchTask(type={self.task_type}, status={self.status}, device={self.assigned_device_id})>"
