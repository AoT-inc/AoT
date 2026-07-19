# coding=utf-8
"""P5-34: Add ai_experience_memory table + t3_memory_loop_enabled flag.

AI v3.1 tier architecture, Phase 4 (memory loop). Tiered experience memory
(error/emotion/usage) whose repeated error patterns feed the Phase 3 rule loop
as pending behavior proposals. Flag default False → dormant. See
.local/plans/phase4_memory_loop_design.md.

Revision ID: p5_34_add_experience_memory
Revises: p5_33_add_rule_layer
Create Date: 2026-07-06
"""

revision = 'p5_34_add_experience_memory'
down_revision = 'p5_33_add_rule_layer'
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
    if 'ai_experience_memory' not in _table_names():
        op.create_table(
            'ai_experience_memory',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('unique_id', sa.String(length=36), nullable=False, unique=True),
            sa.Column('signal_type', sa.String(length=20), server_default='error'),
            sa.Column('pattern_key', sa.String(length=120), nullable=False),
            sa.Column('summary', sa.Text(), nullable=True),
            sa.Column('occurrence_count', sa.Integer(), server_default='1'),
            sa.Column('importance', sa.Integer(), server_default='1'),
            sa.Column('tier', sa.String(length=10), server_default='cold'),
            sa.Column('evidence_ids', sa.Text(), server_default='[]'),
            sa.Column('facility_id', sa.String(length=36), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=True),
            sa.Column('last_seen_at', sa.DateTime(), nullable=True),
        )
        op.create_index('ix_ai_experience_memory_pattern_key', 'ai_experience_memory', ['pattern_key'])
        op.create_index('ix_ai_experience_memory_facility_id', 'ai_experience_memory', ['facility_id'])

    if 't3_memory_loop_enabled' not in _col_names('ai_global_settings'):
        op.add_column('ai_global_settings', sa.Column('t3_memory_loop_enabled', sa.Boolean(), server_default=sa.false(), nullable=True))


def downgrade():
    if 't3_memory_loop_enabled' in _col_names('ai_global_settings'):
        op.drop_column('ai_global_settings', 't3_memory_loop_enabled')
    if 'ai_experience_memory' in _table_names():
        op.drop_index('ix_ai_experience_memory_facility_id', table_name='ai_experience_memory')
        op.drop_index('ix_ai_experience_memory_pattern_key', table_name='ai_experience_memory')
        op.drop_table('ai_experience_memory')
