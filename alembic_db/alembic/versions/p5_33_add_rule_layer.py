# coding=utf-8
"""P5-33: Add ai_rule / ai_rule_proposal tables + rule_layer_enabled flag.

AI v3.1 tier architecture, Phase 3 (3-tier evolving rules). Enforcement rules
(prompt fragments injected at resolve time) + learned-rule proposals generated
from Phase 2 advisory-audit evidence. Flag default False → dormant until an
operator turns it on. See .local/plans/phase3_rule_layer_design.md.

Revision ID: p5_33_add_rule_layer
Revises: p5_32_add_t3_audit_flag
Create Date: 2026-07-06
"""

revision = 'p5_33_add_rule_layer'
down_revision = 'p5_32_add_t3_audit_flag'
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
    tables = _table_names()

    if 'ai_rule' not in tables:
        op.create_table(
            'ai_rule',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('unique_id', sa.String(length=36), nullable=False, unique=True),
            sa.Column('name', sa.String(length=120), nullable=False),
            sa.Column('layer', sa.String(length=20), server_default='enforcement'),
            sa.Column('role_scope', sa.String(length=30), server_default='all'),
            sa.Column('inject_at', sa.String(length=30), server_default='system_prompt'),
            sa.Column('content', sa.Text(), nullable=False),
            sa.Column('severity', sa.String(length=10), server_default='warn'),
            sa.Column('is_active', sa.Boolean(), server_default=sa.true()),
            sa.Column('source', sa.String(length=60), server_default='human'),
            sa.Column('created_at', sa.DateTime(), nullable=True),
        )

    if 'ai_rule_proposal' not in tables:
        op.create_table(
            'ai_rule_proposal',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('unique_id', sa.String(length=36), nullable=False, unique=True),
            sa.Column('proposed_rule_text', sa.Text(), nullable=False),
            sa.Column('category', sa.String(length=20), server_default='style'),
            sa.Column('role_scope', sa.String(length=30), server_default='all'),
            sa.Column('evidence_ids', sa.Text(), server_default='[]'),
            sa.Column('evidence_count', sa.Integer(), server_default='0'),
            sa.Column('pattern_key', sa.String(length=120), nullable=True),
            sa.Column('status', sa.String(length=20), server_default='pending'),
            sa.Column('created_by', sa.String(length=60), server_default='advisory_audit_generator'),
            sa.Column('resulting_rule_id', sa.String(length=36), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=True),
            sa.Column('reviewed_at', sa.DateTime(), nullable=True),
        )
        op.create_index('ix_ai_rule_proposal_pattern_key', 'ai_rule_proposal', ['pattern_key'])

    if 't3_rule_layer_enabled' not in _col_names('ai_global_settings'):
        op.add_column('ai_global_settings', sa.Column('t3_rule_layer_enabled', sa.Boolean(), server_default=sa.false(), nullable=True))


def downgrade():
    tables = _table_names()
    if 't3_rule_layer_enabled' in _col_names('ai_global_settings'):
        op.drop_column('ai_global_settings', 't3_rule_layer_enabled')
    if 'ai_rule_proposal' in tables:
        op.drop_index('ix_ai_rule_proposal_pattern_key', table_name='ai_rule_proposal')
        op.drop_table('ai_rule_proposal')
    if 'ai_rule' in tables:
        op.drop_table('ai_rule')
