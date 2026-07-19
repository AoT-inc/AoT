# coding=utf-8
"""P5-38: Add t1_goal_loop_enabled flag to ai_global_settings.

Goal-directed continuous loop (agentic T1) — a user request is set as a GOAL and
processed autonomously until achieved (read/discovery tools run without approval
and feed the next step within the turn; only physical control gates on approval).
Flag default False. See .local/plans/ai_goal_loop_design.md.

Revision ID: p5_38_add_goal_loop_flag
Revises: p5_37_add_server_page_context_flag
Create Date: 2026-07-07
"""

revision = 'p5_38_add_goal_loop_flag'
down_revision = 'p5_37_add_server_page_context_flag'
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa


def _col_names(table):
    conn = op.get_bind()
    return {row[1] for row in conn.execute(sa.text(f"PRAGMA table_info({table})"))}


def upgrade():
    if 't1_goal_loop_enabled' not in _col_names('ai_global_settings'):
        op.add_column('ai_global_settings', sa.Column('t1_goal_loop_enabled', sa.Boolean(), server_default=sa.false(), nullable=True))


def downgrade():
    if 't1_goal_loop_enabled' in _col_names('ai_global_settings'):
        op.drop_column('ai_global_settings', 't1_goal_loop_enabled')
