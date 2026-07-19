# coding=utf-8
"""P5-31: Add t1_unified_enabled feature flag to ai_global_settings.

Part of the AI v3.1 tier architecture refactor, Phase 1 (T1 unified loop).
Default False → zero behavior change; CONTROL intents keep using the legacy
planner→supervisor→synthesizer pipeline until an operator turns this on.
See .local/plans/phase1_t1_loop_design.md.

Revision ID: p5_31_add_t1_unified_flag
Revises: p5_30_add_ai_entry_capabilities
Create Date: 2026-07-06
"""

revision = 'p5_31_add_t1_unified_flag'
down_revision = 'p5_30_add_ai_entry_capabilities'
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa


def _col_names(table):
    conn = op.get_bind()
    return {row[1] for row in conn.execute(sa.text(f"PRAGMA table_info({table})"))}


def upgrade():
    cols = _col_names('ai_global_settings')
    if 't1_unified_enabled' not in cols:
        op.add_column('ai_global_settings', sa.Column('t1_unified_enabled', sa.Boolean(), server_default=sa.false(), nullable=True))


def downgrade():
    cols = _col_names('ai_global_settings')
    if 't1_unified_enabled' in cols:
        op.drop_column('ai_global_settings', 't1_unified_enabled')
