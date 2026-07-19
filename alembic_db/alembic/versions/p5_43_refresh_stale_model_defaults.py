# coding=utf-8
"""P5-43: Refresh the one stale model default baked into a data-seed migration.

The 'router' pipeline_role preset (seeded in d4e5f6a7b8c9) still points at
gemini-3.1-flash-lite-preview, a preview model since retired (2026-06). Every
other stale model-ID default in the codebase was a Python-level column
default or hardcoded fallback string — those take effect on next write and
needed no migration. This one row was baked into an already-applied INSERT,
so a follow-up UPDATE is the only way to correct it for existing databases.
See .local/plans/phase6_knowledge_digest_design.md (model catalog refresh).

Renumbered p5_40 -> p5_41 -> p5_42 -> p5_43 (2026-07-10) as part of
resolving the p5_39/p5_40/p5_41 revision collision — see
p5_42_add_knowledge_chunk.py.

Revision ID: p5_43_refresh_stale_model_defaults
Revises: p5_42_add_knowledge_chunk
Create Date: 2026-07-07
"""

revision = 'p5_43_refresh_stale_model_defaults'
down_revision = 'p5_42_add_knowledge_chunk'
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa

_STALE = 'gemini-3.1-flash-lite-preview'
_CURRENT = 'gemini-2.5-flash'


def upgrade():
    conn = op.get_bind()
    tables = {row[0] for row in conn.execute(sa.text(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ))}
    if 'agent_role_preset' in tables:
        op.execute(sa.text(
            "UPDATE agent_role_preset SET model_value = :cur "
            "WHERE pipeline_role = 'router' AND model_value = :stale"
        ).bindparams(cur=_CURRENT, stale=_STALE))


def downgrade():
    conn = op.get_bind()
    tables = {row[0] for row in conn.execute(sa.text(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ))}
    if 'agent_role_preset' in tables:
        op.execute(sa.text(
            "UPDATE agent_role_preset SET model_value = :stale "
            "WHERE pipeline_role = 'router' AND model_value = :cur"
        ).bindparams(stale=_STALE, cur=_CURRENT))
