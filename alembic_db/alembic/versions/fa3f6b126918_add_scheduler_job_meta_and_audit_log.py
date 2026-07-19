"""Add scheduler_jobs_meta and scheduler_audit_log tables

Revision ID: fa3f6b126918
Revises: fa3f6b126917
Create Date: 2026-02-18 12:00:00.000000

"""
import sys
import os

sys.path.append(os.path.abspath(os.path.join(__file__, "../../../..")))

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.mysql import LONGTEXT

# revision identifiers, used by Alembic.
revision = 'fa3f6b126918'
down_revision = 'fa3f6b126917'
branch_labels = None
depends_on = None


def upgrade():
    # Check if table already exists (db.create_all() might have created it)
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    tables = inspector.get_table_names()

    if 'scheduler_jobs_meta' not in tables:
        op.create_table('scheduler_jobs_meta',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('unique_id', sa.String(length=36), nullable=False),
            sa.Column('action_type', sa.String(length=20), nullable=False),
            sa.Column('target_id', sa.String(length=36), nullable=False),
            sa.Column('params_json', sa.Text(), nullable=True),
            sa.Column('schedule_time', sa.DateTime(), nullable=True),
            sa.Column('schedule_cron', sa.Text(), nullable=True),
            sa.Column('proposed_by', sa.String(length=10), nullable=True),
            sa.Column('reasoning', sa.Text(), nullable=True),
            sa.Column('approval_required', sa.Boolean(), nullable=True),
            sa.Column('priority', sa.Integer(), nullable=True),
            sa.Column('state', sa.String(length=20), nullable=True),
            sa.Column('decided_by', sa.String(length=10), nullable=True),
            sa.Column('decided_at', sa.DateTime(), nullable=True),
            sa.Column('user_feedback', sa.Text(), nullable=True),
            sa.Column('executed_at', sa.DateTime(), nullable=True),
            sa.Column('execution_result', sa.Text(), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=True),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('id'),
            sa.UniqueConstraint('unique_id')
        )
        with op.batch_alter_table('scheduler_jobs_meta', schema=None) as batch_op:
            batch_op.create_index('ix_scheduler_jobs_meta_state', ['state'], unique=False)
            batch_op.create_index('ix_scheduler_jobs_meta_created_at', ['created_at'], unique=False)

    if 'scheduler_audit_log' not in tables:
        op.create_table('scheduler_audit_log',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('job_meta_id', sa.Integer(), nullable=False),
            sa.Column('actor', sa.String(length=10), nullable=False),
            sa.Column('decision', sa.String(length=20), nullable=False),
            sa.Column('feedback', sa.Text(), nullable=True),
            sa.Column('previous_state', sa.String(length=20), nullable=True),
            sa.Column('new_state', sa.String(length=20), nullable=True),
            sa.Column('timestamp', sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(['job_meta_id'], ['scheduler_jobs_meta.id'], ),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('id')
        )
        with op.batch_alter_table('scheduler_audit_log', schema=None) as batch_op:
            batch_op.create_index('ix_scheduler_audit_log_timestamp', ['timestamp'], unique=False)


def downgrade():
    with op.batch_alter_table('scheduler_audit_log', schema=None) as batch_op:
        batch_op.drop_index('ix_scheduler_audit_log_timestamp')
    op.drop_table('scheduler_audit_log')

    with op.batch_alter_table('scheduler_jobs_meta', schema=None) as batch_op:
        batch_op.drop_index('ix_scheduler_jobs_meta_created_at')
        batch_op.drop_index('ix_scheduler_jobs_meta_state')
    op.drop_table('scheduler_jobs_meta')
