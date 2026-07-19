# coding=utf-8
"""P5-52: Flip agent_loop_enabled on for existing installs (Phase 3 staged
retirement, docs/design/ai-agent-loop.md §10/§15).

Same pattern as p5_50 (knowledge injection default-on): flipping the column
default in models/ai_settings.py only helps future new-install rows; this
migration backfills the value on whatever AIGlobalSettings row(s) already
exist so this install actually starts using AgentLoopService on the next
chat request, not just future ones.

This is a STAGED retirement, not a full deletion: the legacy router/planner/
synthesizer pipeline and UOC's non-'auto'-agent callers remain in the
codebase (only UOC itself, which was independent dead weight, was deleted
outright — see routes_ai_api.py / aot/ai/orchestration removal in the same
commit). Setting agent_loop_enabled back to False on an install remains a
full, working rollback to the legacy pipeline with no code change needed.

Revision ID: p5_52_agent_loop_default_on
Revises: p5_51_agent_loop_canary_flags
Create Date: 2026-07-19
"""

revision = 'p5_52_agent_loop_default_on'
down_revision = 'p5_51_agent_loop_canary_flags'
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
        "UPDATE ai_global_settings SET agent_loop_enabled = 1 "
        "WHERE agent_loop_enabled = 0 OR agent_loop_enabled IS NULL"
    ))


def downgrade():
    # Deliberately a no-op — see p5_50's downgrade for the same rationale:
    # a schema downgrade shouldn't also revoke a runtime routing decision.
    # Flip agent_loop_enabled back via AI Settings if that's ever wanted.
    pass
