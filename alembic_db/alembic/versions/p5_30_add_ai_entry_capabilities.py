# coding=utf-8
"""P5-30: Add model-agnostic registry columns to ai_entry.

Part of the AI v3.1 tier architecture refactor (see
.local/reports/ai_architecture_v3_tier_proposal.md §8, §13). Adds:
- protocol: which request driver to use (NULL = derive from model_type,
  preserves current ENGINE_REGISTRY-based routing unchanged)
- capabilities_json: conformance probe result (tool_use, structured_output,
  streaming, latency_ms), written by aot.ai.services.model_probe
- capabilities_probed_at: last probe timestamp

Revision ID: p5_30_add_ai_entry_capabilities
Revises: p5_28_add_custom_theme_presets
Create Date: 2026-07-06

Note: originally chained off an uncommitted 'p5_29_add_tuya_connection_to_misc'
migration that is not present in this branch (that Tuya work is separate/
untracked), which broke the alembic revision map (KeyError p5_29). Re-based onto
the last committed migration p5_28 so the chain resolves. The Tuya columns, when
present, are created by db.create_all() from the model — not required here.
"""

revision = 'p5_30_add_ai_entry_capabilities'
down_revision = 'p5_28_add_custom_theme_presets'
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa


def _col_names(table):
    conn = op.get_bind()
    return {row[1] for row in conn.execute(sa.text(f"PRAGMA table_info({table})"))}


def upgrade():
    cols = _col_names('ai_entry')
    if 'protocol' not in cols:
        op.add_column('ai_entry', sa.Column('protocol', sa.String(length=50), nullable=True))
    if 'capabilities_json' not in cols:
        op.add_column('ai_entry', sa.Column('capabilities_json', sa.Text(), server_default='{}', nullable=True))
    if 'capabilities_probed_at' not in cols:
        op.add_column('ai_entry', sa.Column('capabilities_probed_at', sa.DateTime(), nullable=True))


def downgrade():
    cols = _col_names('ai_entry')
    for name in ('protocol', 'capabilities_json', 'capabilities_probed_at'):
        if name in cols:
            op.drop_column('ai_entry', name)
