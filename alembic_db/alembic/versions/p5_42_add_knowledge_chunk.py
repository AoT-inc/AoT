# coding=utf-8
"""P5-42: Add ai_knowledge_chunk table + knowledge digest feature flags.

Phase 6 knowledge digest pipeline: AI Library document/web_url sources are
chunked and digested (LLM summarize + keyword extraction) once at sync time
and cached here, so query-time retrieval (knowledge_search) is pure DB
lookup + deterministic search — no LLM call on the read path. Reuses the
AIContextRecord 3-state trust pipeline (context_state column). Both new
ai_global_settings flags default False — fully inert until an operator opts
in. See .local/plans/phase6_knowledge_digest_design.md.

Renumbered p5_39 -> p5_40 -> p5_41 -> p5_42 (2026-07-10): p5_39/p5_40/p5_41
were independently taken by the concurrent notice-board feature branch
(p5_39_add_notice_board -> p5_40_drop_notice_links -> p5_41_add_notice_category,
also descending from p5_38_add_goal_loop_flag and merged to main in the
interim). Re-chained to follow its actual head (confirmed via `alembic
heads` against main, not just the — stale — ALEMBIC_VERSION constant)
instead of branching alembic history into two heads from the same parent.

Revision ID: p5_42_add_knowledge_chunk
Revises: p5_41_add_notice_category
Create Date: 2026-07-07
"""

revision = 'p5_42_add_knowledge_chunk'
down_revision = 'p5_41_add_notice_category'
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
        op.create_table(
            'ai_knowledge_chunk',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('unique_id', sa.String(36), nullable=False, unique=True),
            sa.Column('source_id', sa.String(36), nullable=False, index=True),
            sa.Column('source_name', sa.String(100), nullable=True),
            sa.Column('section_title', sa.String(255), nullable=True),
            sa.Column('digest_text', sa.Text(), nullable=False),
            sa.Column('keywords', sa.Text(), nullable=True),
            sa.Column('raw_excerpt', sa.Text(), nullable=True),
            sa.Column('locale', sa.String(8), nullable=True, server_default='ko'),
            sa.Column('chunk_index', sa.Integer(), nullable=True, server_default='0'),
            sa.Column('content_hash', sa.String(64), nullable=False, index=True),
            sa.Column('context_state', sa.String(20), nullable=True, server_default='system_generated'),
            sa.Column('is_enabled', sa.Boolean(), nullable=True, server_default='1'),
            sa.Column('created_at', sa.DateTime(), nullable=True),
            sa.Column('updated_at', sa.DateTime(), nullable=True),
            sa.PrimaryKeyConstraint('id'),
            sa.ForeignKeyConstraint(['source_id'], ['ai_context_source.source_id'], ondelete='CASCADE'),
        )

    if 'knowledge_digest_enabled' not in _col_names('ai_global_settings'):
        op.add_column('ai_global_settings', sa.Column('knowledge_digest_enabled', sa.Boolean(), server_default=sa.false(), nullable=True))
    if 'knowledge_chunk_confirmed_only' not in _col_names('ai_global_settings'):
        op.add_column('ai_global_settings', sa.Column('knowledge_chunk_confirmed_only', sa.Boolean(), server_default=sa.false(), nullable=True))


def downgrade():
    if 'knowledge_chunk_confirmed_only' in _col_names('ai_global_settings'):
        op.drop_column('ai_global_settings', 'knowledge_chunk_confirmed_only')
    if 'knowledge_digest_enabled' in _col_names('ai_global_settings'):
        op.drop_column('ai_global_settings', 'knowledge_digest_enabled')
    if 'ai_knowledge_chunk' in _table_names():
        op.drop_table('ai_knowledge_chunk')
