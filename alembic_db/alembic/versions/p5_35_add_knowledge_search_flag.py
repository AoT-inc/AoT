# coding=utf-8
"""P5-35: Add t3_knowledge_search_enabled feature flag to ai_global_settings.

AI v3.1 tier architecture, Phase 5 (agentic knowledge search). Default False →
the knowledge_search discovery hint stays out of the AI prompt until an
operator turns it on. The tool itself is always executable. See
.local/plans/phase5_knowledge_search_design.md.

Revision ID: p5_35_add_knowledge_search_flag
Revises: p5_34_add_experience_memory
Create Date: 2026-07-06
"""

revision = 'p5_35_add_knowledge_search_flag'
down_revision = 'p5_34_add_experience_memory'
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa


def _col_names(table):
    conn = op.get_bind()
    return {row[1] for row in conn.execute(sa.text(f"PRAGMA table_info({table})"))}


def upgrade():
    if 't3_knowledge_search_enabled' not in _col_names('ai_global_settings'):
        op.add_column('ai_global_settings', sa.Column('t3_knowledge_search_enabled', sa.Boolean(), server_default=sa.false(), nullable=True))


def downgrade():
    if 't3_knowledge_search_enabled' in _col_names('ai_global_settings'):
        op.drop_column('ai_global_settings', 't3_knowledge_search_enabled')
