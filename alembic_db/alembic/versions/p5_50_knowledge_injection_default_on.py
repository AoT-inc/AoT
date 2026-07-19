# coding=utf-8
"""P5-50: Flip knowledge injection flags on for existing installs (P6,
docs/design/ai-library-redesign.md §6/§9).

t3_knowledge_search_enabled and knowledge_digest_enabled defaulted False
through P1-P5 development, which reproduced exactly the "동작하는 척" bug the
whole redesign set out to fix: an operator could register/sync a source and
it would sit in AIKnowledgeChunk forever, invisible to knowledge_search / the
AI, with no UI anywhere exposing either flag to explain why or let anyone
turn it on. Neither flag has ever been read or written by any
template/route (grepped before writing this migration) — so a stored False
here never reflected a deliberate operator choice, only "nobody could have
touched this." Flipping the column default (models/ai_settings.py) only
helps future new-install rows; this migration backfills the value on
whatever AIGlobalSettings row(s) already exist so this install's AI
actually starts using its library on the next request, not just future ones.

knowledge_chunk_confirmed_only is NOT touched here — see design §9: its
semantics were separately redefined (P6, knowledge_search.py) but its
default (False) already matches the desired P6 behavior (unconfirmed
ai_curated notes ARE searchable at low trust; this flag is an opt-in
stricter mode an operator turns on deliberately, not something to flip on
for everyone).

Revision ID: p5_50_knowledge_injection_default_on
Revises: p5_49_knowledge_chunk_reuse_count
Create Date: 2026-07-19
"""

revision = 'p5_50_knowledge_injection_default_on'
down_revision = 'p5_49_knowledge_chunk_reuse_count'
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa


def _table_names():
    conn = op.get_bind()
    return {row[0] for row in conn.execute(sa.text(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ))}


def upgrade():
    if 'ai_global_settings' not in _table_names():
        return
    op.execute(sa.text(
        "UPDATE ai_global_settings SET t3_knowledge_search_enabled = 1 "
        "WHERE t3_knowledge_search_enabled = 0 OR t3_knowledge_search_enabled IS NULL"
    ))
    op.execute(sa.text(
        "UPDATE ai_global_settings SET knowledge_digest_enabled = 1 "
        "WHERE knowledge_digest_enabled = 0 OR knowledge_digest_enabled IS NULL"
    ))


def downgrade():
    # Deliberately a no-op: reverting to False would silently re-break
    # knowledge injection for whoever's been running with it on since this
    # migration applied — a schema downgrade shouldn't also revoke a runtime
    # behavior decision. Flip the flags back via settings if that's ever
    # actually wanted.
    pass
