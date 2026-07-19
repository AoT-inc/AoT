# coding=utf-8
"""P5-48: Add flagged_reason to ai_knowledge_chunk — P4 contradiction
signal for AI-shelved (ai_curated) knowledge items, see
docs/design/ai-library-redesign.md §3.3/§4 and
aot/ai/services/knowledge_shelve_service.py.

Revision ID: p5_48_knowledge_chunk_flagged_reason
Revises: p5_47_knowledge_item_provenance
Create Date: 2026-07-19
"""

revision = 'p5_48_knowledge_chunk_flagged_reason'
down_revision = 'p5_47_knowledge_item_provenance'
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
    if 'flagged_reason' not in _col_names('ai_knowledge_chunk'):
        op.add_column('ai_knowledge_chunk', sa.Column('flagged_reason', sa.Text(), nullable=True))


def downgrade():
    if 'ai_knowledge_chunk' not in _table_names():
        return
    if 'flagged_reason' in _col_names('ai_knowledge_chunk'):
        op.drop_column('ai_knowledge_chunk', 'flagged_reason')
