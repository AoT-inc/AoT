# coding=utf-8
"""P5-36: Add ai_usage_meter table + budget governance flags.

AI v3.1 tier architecture, Phase 6 (budget governance). Per-connection monthly
usage tally + t3_budget_governance_enabled / budget_hard_stop flags. Flags
default False → dormant. See .local/plans/phase6_onboarding_budget_design.md.

Revision ID: p5_36_add_budget_governance
Revises: p5_35_add_knowledge_search_flag
Create Date: 2026-07-06
"""

revision = 'p5_36_add_budget_governance'
down_revision = 'p5_35_add_knowledge_search_flag'
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa


def _table_names():
    conn = op.get_bind()
    return {row[0] for row in conn.execute(sa.text("SELECT name FROM sqlite_master WHERE type='table'"))}


def _col_names(table):
    conn = op.get_bind()
    return {row[1] for row in conn.execute(sa.text(f"PRAGMA table_info({table})"))}


def upgrade():
    if 'ai_usage_meter' not in _table_names():
        op.create_table(
            'ai_usage_meter',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('entry_unique_id', sa.String(length=36), nullable=False),
            sa.Column('period', sa.String(length=7), nullable=False),
            sa.Column('estimated_cost_usd', sa.Float(), server_default='0.0'),
            sa.Column('request_count', sa.Integer(), server_default='0'),
            sa.Column('updated_at', sa.DateTime(), nullable=True),
        )
        op.create_index('ix_ai_usage_meter_entry_unique_id', 'ai_usage_meter', ['entry_unique_id'])
        op.create_index('ix_ai_usage_meter_period', 'ai_usage_meter', ['period'])

    cols = _col_names('ai_global_settings')
    if 't3_budget_governance_enabled' not in cols:
        op.add_column('ai_global_settings', sa.Column('t3_budget_governance_enabled', sa.Boolean(), server_default=sa.false(), nullable=True))
    if 'budget_hard_stop' not in cols:
        op.add_column('ai_global_settings', sa.Column('budget_hard_stop', sa.Boolean(), server_default=sa.false(), nullable=True))


def downgrade():
    cols = _col_names('ai_global_settings')
    if 'budget_hard_stop' in cols:
        op.drop_column('ai_global_settings', 'budget_hard_stop')
    if 't3_budget_governance_enabled' in cols:
        op.drop_column('ai_global_settings', 't3_budget_governance_enabled')
    if 'ai_usage_meter' in _table_names():
        op.drop_index('ix_ai_usage_meter_period', table_name='ai_usage_meter')
        op.drop_index('ix_ai_usage_meter_entry_unique_id', table_name='ai_usage_meter')
        op.drop_table('ai_usage_meter')
