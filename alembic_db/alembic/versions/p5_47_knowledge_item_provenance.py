# coding=utf-8
"""P5-47: Add provenance/tags/entity_ref/attribution/content_kind/ttl to
ai_knowledge_chunk — unified knowledge item model (P1 of the AI library
redesign, see docs/design/ai-library-redesign.md §2, §9).

Every existing row today was written by _write_knowledge_chunks() from a
user-registered document/web_url AIContextSource, so backfill provenance to
'user_provided' and content_kind to 'prose' (the only kind any writer
produces so far) rather than leaving them at the column default for rows
that predate this migration — NULL-vs-default drift would otherwise make
"row has no explicit provenance yet" indistinguishable from "row is
unprovenanced by design".

tags/entity_ref/attribution/ttl are left NULL: no writer populates them yet
(P1 is schema + read path only), and NULL correctly means "unscoped / no
citation available" rather than a fabricated value.

Revision ID: p5_47_knowledge_item_provenance
Revises: p5_46_input_auto_vpd_toggle
Create Date: 2026-07-18
"""

revision = 'p5_47_knowledge_item_provenance'
down_revision = 'p5_46_input_auto_vpd_toggle'
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

    cols = _col_names('ai_knowledge_chunk')

    if 'provenance' not in cols:
        op.add_column('ai_knowledge_chunk',
                       sa.Column('provenance', sa.String(20), nullable=True))
    if 'tags' not in cols:
        op.add_column('ai_knowledge_chunk', sa.Column('tags', sa.Text(), nullable=True))
    if 'entity_ref' not in cols:
        op.add_column('ai_knowledge_chunk', sa.Column('entity_ref', sa.String(36), nullable=True))
        op.create_index('ix_ai_knowledge_chunk_entity_ref', 'ai_knowledge_chunk', ['entity_ref'])
    if 'attribution' not in cols:
        op.add_column('ai_knowledge_chunk', sa.Column('attribution', sa.Text(), nullable=True))
    if 'content_kind' not in cols:
        op.add_column('ai_knowledge_chunk',
                       sa.Column('content_kind', sa.String(16), nullable=True))
    if 'ttl' not in cols:
        op.add_column('ai_knowledge_chunk', sa.Column('ttl', sa.DateTime(), nullable=True))

    # Backfill pre-existing rows (see module docstring — every row so far is a
    # user-registered document/web_url digest).
    op.execute(sa.text(
        "UPDATE ai_knowledge_chunk SET provenance = 'user_provided' WHERE provenance IS NULL"
    ))
    op.execute(sa.text(
        "UPDATE ai_knowledge_chunk SET content_kind = 'prose' WHERE content_kind IS NULL"
    ))


def downgrade():
    if 'ai_knowledge_chunk' not in _table_names():
        return
    cols = _col_names('ai_knowledge_chunk')
    if 'entity_ref' in cols:
        op.drop_index('ix_ai_knowledge_chunk_entity_ref', table_name='ai_knowledge_chunk')
        op.drop_column('ai_knowledge_chunk', 'entity_ref')
    for col in ('ttl', 'content_kind', 'attribution', 'tags', 'provenance'):
        if col in cols:
            op.drop_column('ai_knowledge_chunk', col)
