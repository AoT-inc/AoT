# coding=utf-8
"""P5-44: Add facility_id to ai_knowledge_chunk — multi-site scoping.

Multi-site operators reported that knowledge_search's unified index mixed
document/web knowledge across all facilities: a source uploaded for site A
could surface in an answer for site B. AIContextSource was already scoped by
facility_id, but the derived AIKnowledgeChunk rows were not, and neither was
the search index. This adds the column (backfilled from the parent source)
and an index for the WHERE facility_id=... filter added in knowledge_search.
See .local/plans/phase6_knowledge_digest_design.md (multi-site addendum).

Renumbered p5_41 -> p5_42 -> p5_43 -> p5_44 (2026-07-10) as part of
resolving the p5_39/p5_40/p5_41 revision collision — see
p5_42_add_knowledge_chunk.py.

Revision ID: p5_44_add_knowledge_chunk_facility_scope
Revises: p5_43_refresh_stale_model_defaults
Create Date: 2026-07-07
"""

revision = 'p5_44_add_knowledge_chunk_facility_scope'
down_revision = 'p5_43_refresh_stale_model_defaults'
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
        return  # p5_42 didn't run yet on this DB (fresh install runs migrations in order anyway)

    if 'facility_id' not in _col_names('ai_knowledge_chunk'):
        op.add_column('ai_knowledge_chunk', sa.Column('facility_id', sa.String(36), nullable=True))
        op.create_index(
            'ix_ai_knowledge_chunk_facility_id', 'ai_knowledge_chunk', ['facility_id']
        )

    # Backfill existing rows from their parent source (any synced before this
    # migration would otherwise be facility_id=NULL — invisible to a
    # facility-scoped search until the next sync).
    op.execute(sa.text(
        "UPDATE ai_knowledge_chunk "
        "SET facility_id = ("
        "  SELECT facility_id FROM ai_context_source "
        "  WHERE ai_context_source.source_id = ai_knowledge_chunk.source_id"
        ") "
        "WHERE facility_id IS NULL"
    ))


def downgrade():
    if 'ai_knowledge_chunk' not in _table_names():
        return
    if 'facility_id' in _col_names('ai_knowledge_chunk'):
        op.drop_index('ix_ai_knowledge_chunk_facility_id', table_name='ai_knowledge_chunk')
        op.drop_column('ai_knowledge_chunk', 'facility_id')
