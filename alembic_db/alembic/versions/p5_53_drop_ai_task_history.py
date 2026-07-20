# coding=utf-8
"""P5-53: Drop ai_task_history — orphan table, never had a live writer/reader.

The only writer was aot_daemon.py's log_history() @expose RPC method, which
nothing in the codebase ever called (grep-verified), and there is no reader
anywhere (AITaskHistory.query never appears). The table on installs that
have it was never created by an alembic migration in the first place —
p4/p5 history shows no op.create_table for it, so it must have come from an
ad-hoc db.create_all() at some point. Removed alongside the AITaskHistory
model class and its AITask.history backref (2026-07-20 A안 cleanup).

Revision ID: p5_53_drop_ai_task_history
Revises: p5_52_agent_loop_default_on
Create Date: 2026-07-20
"""

revision = 'p5_53_drop_ai_task_history'
down_revision = 'p5_52_agent_loop_default_on'
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql


def _table_names():
    conn = op.get_bind()
    return {row[0] for row in conn.execute(sa.text(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ))}


def upgrade():
    if 'ai_task_history' in _table_names():
        op.drop_table('ai_task_history')


def downgrade():
    op.create_table(
        'ai_task_history',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('unique_id', sa.String(length=36), nullable=False),
        sa.Column('task_id', sa.String(length=36), nullable=False),
        sa.Column('action', sa.String(length=50), nullable=False),
        sa.Column('user_id', sa.String(length=36), nullable=True),
        sa.Column('reason', sa.Text().with_variant(mysql.LONGTEXT(), 'mysql', 'mariadb'), nullable=True),
        sa.Column('snapshot_json', sa.Text().with_variant(mysql.LONGTEXT(), 'mysql', 'mariadb'), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['task_id'], ['ai_task.unique_id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('unique_id'),
    )
