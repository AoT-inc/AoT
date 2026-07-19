# coding=utf-8

"""
Scheduler models for Human-AI collaborative job management.
"""
import enum

from aot.utils.time_utils import utc_now
from sqlalchemy.dialects.mysql import LONGTEXT

from aot.databases import CRUDMixin, set_uuid
from aot.aot_flask.extensions import db


class ScheduleType(enum.Enum):
    device    = "device"
    human     = "human"
    ai_system = "ai_system"


class SchedulerJobMeta(CRUDMixin, db.Model):
    """
    Extended metadata for scheduled jobs.
    Tracks AI proposals, human decisions, and execution results
    alongside APScheduler's internal job store.
    """
    __tablename__ = "scheduler_jobs_meta"
    __table_args__ = {'extend_existing': True}

    id = db.Column(db.Integer, unique=True, primary_key=True)
    unique_id = db.Column(db.String(36), nullable=False, unique=True, default=set_uuid)

    # Source tracking: scheduler, trigger, conditional, function, manual, external
    source_type = db.Column(db.String(20), default='scheduler', index=True)

    # Action definition
    action_type = db.Column(db.String(20), nullable=False)  # output, pid, function
    target_id = db.Column(db.String(36), nullable=False)
    params_json = db.Column(db.Text().with_variant(LONGTEXT, "mysql", "mariadb"), default='{}')

    # Scheduling
    schedule_time = db.Column(db.DateTime, nullable=True)   # one-time (start time)
    duration_sec = db.Column(db.Integer, default=0)         # duration (for abstract plans or output)
    end_time = db.Column(db.DateTime, nullable=True)        # calculated or manual end time
    schedule_cron = db.Column(db.Text, nullable=True)        # recurring (cron trigger JSON)

    # Collaboration
    proposed_by = db.Column(db.String(10), default='AI')     # AI or HUMAN
    reasoning = db.Column(db.Text().with_variant(LONGTEXT, "mysql", "mariadb"), default='')
    approval_required = db.Column(db.Boolean, default=True)
    priority = db.Column(db.Integer, default=1)              # 1=normal, 2=critical

    # State machine: DRAFT → PENDING → RUNNING → COMPLETED/FAILED, or DRAFT → ARCHIVED
    state = db.Column(db.String(20), default='DRAFT', index=True)

    # Decision tracking
    decided_by = db.Column(db.String(10), nullable=True)     # HUMAN
    decided_at = db.Column(db.DateTime, nullable=True)
    user_feedback = db.Column(db.Text().with_variant(LONGTEXT, "mysql", "mariadb"), default='')

    # Execution tracking
    executed_at = db.Column(db.DateTime, nullable=True)
    execution_result = db.Column(db.Text().with_variant(LONGTEXT, "mysql", "mariadb"), default='')

    # Timestamps and state machine
    created_at = db.Column(db.DateTime, default=utc_now, index=True)

    # Management and Edit tracking
    is_editable = db.Column(db.Boolean, default=True)
    is_deletable = db.Column(db.Boolean, default=True)
    edit_count = db.Column(db.Integer, default=0)
    last_edited_at = db.Column(db.DateTime, nullable=True)
    last_edited_by = db.Column(db.String(10), nullable=True)  # HUMAN, AI
    deletion_reason = db.Column(db.Text().with_variant(LONGTEXT, "mysql", "mariadb"), nullable=True)

    # Schedule origin classification
    schedule_type = db.Column(db.Enum(ScheduleType),
                              nullable=False,
                              default=ScheduleType.ai_system)

    # Owner: NULL = system job, not NULL = user-owned job
    user_id = db.Column(db.Integer,
                        db.ForeignKey('users.id', ondelete='SET NULL'),
                        nullable=True,
                        index=True)

    owner = db.relationship('User', backref='schedules', lazy='select')

    def __repr__(self):
        return f"<SchedulerJobMeta(id={self.id}, type={self.action_type}, state={self.state})>"


class SchedulerAuditLog(CRUDMixin, db.Model):
    """
    Immutable audit trail for all scheduler decisions.
    Records who did what, when, and why.
    """
    __tablename__ = "scheduler_audit_log"
    __table_args__ = {'extend_existing': True}

    id = db.Column(db.Integer, unique=True, primary_key=True)
    job_meta_id = db.Column(db.Integer, db.ForeignKey('scheduler_jobs_meta.id'), nullable=False)

    actor = db.Column(db.String(10), nullable=False)         # AI or HUMAN
    decision = db.Column(db.String(20), nullable=False)       # PROPOSED, APPROVED, REJECTED, ADJUSTED
    feedback = db.Column(db.Text().with_variant(LONGTEXT, "mysql", "mariadb"), default='')
    previous_state = db.Column(db.String(20), default='')
    new_state = db.Column(db.String(20), default='')

    timestamp = db.Column(db.DateTime, default=utc_now, index=True)


    # Relationship
    job_meta = db.relationship('SchedulerJobMeta', backref='audit_logs')

    def __repr__(self):
        return f"<SchedulerAuditLog(job={self.job_meta_id}, decision={self.decision})>"
