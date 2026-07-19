"""add_ai_agent_skeleton_and_missing_columns

Revision ID: c1d2e3f4a5b6
Revises: ab6d34a7621b
Create Date: 2026-03-22

Applies migrations that were previously skipped because 77a06e44f056
and fa3b126920 existed only as .ready (checksum) files and were never
tracked by Alembic.

Tables/columns created here:
  - ai_agent_skeleton  (from 2018d14dd7e3, which depended on the .ready chain)
  - agent_mcp_access.allowed_tools  (from fa3b126920)

Both operations are guarded so re-running is safe.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = 'c1d2e3f4a5b6'
down_revision = 'ab6d34a7621b'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = inspect(bind)
    existing_tables = inspector.get_table_names()

    # 1. Create ai_agent_skeleton if it does not exist
    if 'ai_agent_skeleton' not in existing_tables:
        op.create_table(
            'ai_agent_skeleton',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('unique_id', sa.String(length=36), nullable=False),
            sa.Column('display_name', sa.String(length=100), nullable=False),
            sa.Column('agent_type', sa.String(length=20), nullable=False),
            sa.Column('is_mcp', sa.Boolean(), nullable=False),
            sa.Column('mcp_tool_registry_json', sa.Text(), nullable=True),
            sa.Column('authority_level', sa.Integer(), nullable=True),
            sa.Column('system_prompt', sa.Text(), nullable=True),
            sa.Column('custom_options_json', sa.Text(), nullable=True),
            sa.Column('is_activated', sa.Boolean(), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=True),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('unique_id'),
        )

    # 2. Add allowed_tools to agent_mcp_access if the column is missing
    if 'agent_mcp_access' in existing_tables:
        existing_cols = {c['name'] for c in inspector.get_columns('agent_mcp_access')}
        if 'allowed_tools' not in existing_cols:
            with op.batch_alter_table('agent_mcp_access', schema=None) as batch_op:
                batch_op.add_column(sa.Column('allowed_tools', sa.Text(), nullable=True))


def downgrade():
    bind = op.get_bind()
    inspector = inspect(bind)
    existing_tables = inspector.get_table_names()

    if 'agent_mcp_access' in existing_tables:
        existing_cols = {c['name'] for c in inspector.get_columns('agent_mcp_access')}
        if 'allowed_tools' in existing_cols:
            with op.batch_alter_table('agent_mcp_access', schema=None) as batch_op:
                batch_op.drop_column('allowed_tools')

    if 'ai_agent_skeleton' in existing_tables:
        op.drop_table('ai_agent_skeleton')
