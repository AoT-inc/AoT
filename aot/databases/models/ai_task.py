# coding=utf-8
from datetime import datetime
from aot.utils.time_utils import utc_now
from sqlalchemy.dialects.mysql import LONGTEXT

from aot.databases import CRUDMixin
from aot.databases import set_uuid
from aot.aot_flask.extensions import db

class AITask(CRUDMixin, db.Model):
    """
    Represents a unified entity for Goals, Milestones, and Tasks.
    Supports infinite hierarchical nesting via self-referential parent_id.

    @phase active
    @stability stable
    @dependency AIAgent, SchedulerJobMeta
    """
    __tablename__ = "ai_task"
    __table_args__ = {'extend_existing': True}

    id = db.Column(db.Integer, unique=True, primary_key=True)
    unique_id = db.Column(db.String(36), nullable=False, unique=True, default=set_uuid)
    
    # Ownership and Assignment
    owner_id = db.Column(db.String(36), nullable=True)  # User unique_id who created this
    assignee_id = db.Column(db.String(36), nullable=True)  # Performer (User, Agent, or Robot)
    assignee_type = db.Column(db.String(20), default='user')  # user, agent, robot
    
    # Hierarchy
    parent_id = db.Column(db.String(36), db.ForeignKey('ai_task.unique_id'), nullable=True)
    agent_id = db.Column(db.String(36), db.ForeignKey('ai_agent.unique_id'), nullable=True)
    
    # Content
    title = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text().with_variant(LONGTEXT, "mysql", "mariadb"), default='')
    
    # Classification
    # goal: High-level objective
    # milestone: Significant stage
    # task: Actionable unit
    # checkpoint: Verification gate
    task_type = db.Column(db.String(20), default='task')
    is_goal = db.Column(db.Boolean, default=False)  # Quick filter for top-level goals
    
    # Status & Progress
    # pending, in_progress, completed, failed, cancelled, blocked
    status = db.Column(db.String(20), default='pending')
    priority = db.Column(db.Integer, default=3)  # 1: High, 5: Low
    sort_order = db.Column(db.Integer, default=0) # For vertical ordering
    
    # v2.0 AI Proposal & Meta
    change_reason = db.Column(db.Text().with_variant(LONGTEXT, "mysql", "mariadb"), nullable=True)
    linked_sensors = db.Column(db.Text().with_variant(LONGTEXT, "mysql", "mariadb"), default='[]') # JSON array of sensor IDs
    impact_score = db.Column(db.Integer, default=0) # 0-100
    is_routine = db.Column(db.Boolean, default=False)
    
    # Phase 3: AI Core Integration (Execution)
    # Replaces SchedulerJobMeta for unified task management
    action_type = db.Column(db.String(50), nullable=True) # e.g. 'output', 'function', 'pid'
    target_id = db.Column(db.String(100), nullable=True) # e.g. 'f_123', 'light_sub_1'
    action_params = db.Column(db.Text().with_variant(LONGTEXT, "mysql", "mariadb"), default='{}') # JSON params
    execution_result = db.Column(db.Text().with_variant(LONGTEXT, "mysql", "mariadb"), nullable=True) # Success/Fail message
    
    # Scheduling
    estimated_time = db.Column(db.Integer, default=0)  # Minutes
    actual_time = db.Column(db.Integer, default=0)     # Minutes
    start_date = db.Column(db.DateTime, nullable=True)
    end_date = db.Column(db.DateTime, nullable=True)
    proposed_start = db.Column(db.DateTime, nullable=True) # AI tentative start
    proposed_end = db.Column(db.DateTime, nullable=True)   # AI tentative end
    
    # Metadata for specific actions (device control, etc.)
    metadata_json = db.Column(db.Text().with_variant(LONGTEXT, "mysql", "mariadb"), default='{}')
    
    created_at = db.Column(db.DateTime, default=utc_now)
    updated_at = db.Column(db.DateTime, default=utc_now, onupdate=utc_now)

    # Phase 5: NotePromotionPipeline sync — links AITask to its SchedulerJobMeta counterpart
    scheduler_job_id = db.Column(
        db.Integer,
        db.ForeignKey('scheduler_jobs_meta.id'),
        nullable=True,
        index=True,
    )

    # Relationships
    children = db.relationship('AITask', backref=db.backref('parent', remote_side=[unique_id]), cascade="all, delete-orphan")
    agent = db.relationship('AIAgent', backref='tasks')
    scheduler_job = db.relationship(
        'SchedulerJobMeta',
        foreign_keys=[scheduler_job_id],
        backref='ai_tasks',
    )

    def __repr__(self):
        return f"<AITask(title={self.title}, type={self.task_type}, status={self.status})>"
