# coding=utf-8
"""P5-37: Add t3_server_page_context_enabled flag to ai_global_settings.

Server-side dashboard data assembly (page context) — reads widget bindings +
current values server-side instead of DOM scraping. Flag default False. See
.local/plans/server_side_page_context_design.md.

Revision ID: p5_37_add_server_page_context_flag
Revises: p5_36_add_budget_governance
Create Date: 2026-07-06
"""

revision = 'p5_37_add_server_page_context_flag'
down_revision = 'p5_36_add_budget_governance'
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa


def _col_names(table):
    conn = op.get_bind()
    return {row[1] for row in conn.execute(sa.text(f"PRAGMA table_info({table})"))}


def upgrade():
    if 't3_server_page_context_enabled' not in _col_names('ai_global_settings'):
        op.add_column('ai_global_settings', sa.Column('t3_server_page_context_enabled', sa.Boolean(), server_default=sa.false(), nullable=True))


def downgrade():
    if 't3_server_page_context_enabled' in _col_names('ai_global_settings'):
        op.drop_column('ai_global_settings', 't3_server_page_context_enabled')
