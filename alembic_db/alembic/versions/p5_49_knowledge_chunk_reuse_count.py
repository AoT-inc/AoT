# coding=utf-8
"""P5-49: Add reuse_count to ai_knowledge_chunk — P5 reuse-based
auto-corroboration counter, see docs/design/ai-library-redesign.md §3.2
and aot/ai/services/knowledge_promotion_service.py.

Revision ID: p5_49_knowledge_chunk_reuse_count
Revises: p5_48_knowledge_chunk_flagged_reason
Create Date: 2026-07-19
"""

revision = 'p5_49_knowledge_chunk_reuse_count'
down_revision = 'p5_48_knowledge_chunk_flagged_reason'
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa


def _col_names(table):
    conn = op.get_bind()
    return {row[1] for row in conn.execute(sa.text(f"PRAGMA table_info({table})"))}


def _table_names():
    conn = op.get_bind()
    return {row[0] for row in conn.execute(sa.text(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ))}


def upgrade():
    if 'ai_knowledge_chunk' not in _table_names():
        return
    if 'reuse_count' not in _col_names('ai_knowledge_chunk'):
        op.add_column('ai_knowledge_chunk',
                       sa.Column('reuse_count', sa.Integer(), nullable=True))
        op.execute(sa.text(
            "UPDATE ai_knowledge_chunk SET reuse_count = 0 WHERE reuse_count IS NULL"
        ))


def downgrade():
    if 'ai_knowledge_chunk' not in _table_names():
        return
    if 'reuse_count' in _col_names('ai_knowledge_chunk'):
        op.drop_column('ai_knowledge_chunk', 'reuse_count')
