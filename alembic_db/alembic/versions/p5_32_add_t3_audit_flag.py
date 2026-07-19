# coding=utf-8
"""P5-32: Add t3_async_audit_enabled feature flag to ai_global_settings.

Part of the AI v3.1 tier architecture refactor, Phase 2 (gate dualization).
Default False → zero behavior change; the async advisory auditor stays dormant
until an operator turns it on. See
.local/plans/phase2_gate_dualization_design.md.

Revision ID: p5_32_add_t3_audit_flag
Revises: p5_31_add_t1_unified_flag
Create Date: 2026-07-06
"""

revision = 'p5_32_add_t3_audit_flag'
down_revision = 'p5_31_add_t1_unified_flag'
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa


def _col_names(table):
    conn = op.get_bind()
    return {row[1] for row in conn.execute(sa.text(f"PRAGMA table_info({table})"))}


def upgrade():
    cols = _col_names('ai_global_settings')
    if 't3_async_audit_enabled' not in cols:
        op.add_column('ai_global_settings', sa.Column('t3_async_audit_enabled', sa.Boolean(), server_default=sa.false(), nullable=True))


def downgrade():
    cols = _col_names('ai_global_settings')
    if 't3_async_audit_enabled' in cols:
        op.drop_column('ai_global_settings', 't3_async_audit_enabled')
