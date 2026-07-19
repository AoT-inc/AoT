# coding=utf-8
"""P5-51: Add agent_loop_enabled / agent_loop_canary_user_ids flags.

Phase 1 of the AI orchestration redesign (docs/design/ai-agent-loop.md) — a
single stateful agent loop (model-agnostic tool-calling, full catalog always
visible, ask_user as a first-class tool) that replaces the router-enum +
per-intent pipeline fan-out that repeatedly mis-routed requests (notes →
add_schedule, ambiguous follow-ups → hallucinated dashboard data). Both
flags default to inert values (agent_loop_enabled=False, canary list empty)
so this migration changes zero runtime behavior on its own — it only adds
the switch. See docs/design/ai-agent-loop.md §9/§11 (confirmed: flag
canary rollout, not a global cutover).

Revision ID: p5_51_agent_loop_canary_flags
Revises: p5_50_knowledge_injection_default_on
Create Date: 2026-07-19
"""

revision = 'p5_51_agent_loop_canary_flags'
down_revision = 'p5_50_knowledge_injection_default_on'
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
    if 'ai_global_settings' not in _table_names():
        return
    cols = _col_names('ai_global_settings')
    if 'agent_loop_enabled' not in cols:
        op.add_column('ai_global_settings',
                       sa.Column('agent_loop_enabled', sa.Boolean(), server_default=sa.false(), nullable=True))
    if 'agent_loop_canary_user_ids' not in cols:
        op.add_column('ai_global_settings',
                       sa.Column('agent_loop_canary_user_ids', sa.Text(), server_default='', nullable=True))


def downgrade():
    cols = _col_names('ai_global_settings')
    if 'agent_loop_canary_user_ids' in cols:
        op.drop_column('ai_global_settings', 'agent_loop_canary_user_ids')
    if 'agent_loop_enabled' in cols:
        op.drop_column('ai_global_settings', 'agent_loop_enabled')
