# coding=utf-8
"""P4-3: Add mcp_audit_log and mcp_confirmation tables.

Revision ID: p4_3_mcp_audit_tables
Revises: p3_5_points_json_method_data
Create Date: 2026-05-16
"""

revision = 'p4_3_mcp_audit_tables'
down_revision = 'p3_5_points_json_method_data'
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa


def upgrade():
    op.create_table(
        'mcp_audit_log',
        sa.Column('id',                  sa.Integer,     primary_key=True),
        sa.Column('unique_id',           sa.String(36),  nullable=False, unique=True),
        sa.Column('timestamp',           sa.DateTime,    nullable=False),
        sa.Column('agent_id',            sa.String(100), server_default='unknown'),
        sa.Column('tool_name',           sa.String(100), nullable=False),
        sa.Column('params_json',         sa.Text,        server_default='{}'),
        sa.Column('reason',              sa.Text,        server_default=''),
        sa.Column('permission',          sa.String(20),  server_default='read'),
        sa.Column('confirmation_status', sa.String(20),  server_default='n/a'),
        sa.Column('confirmation_id',     sa.String(36),  nullable=True),
        sa.Column('user_id',             sa.String(36),  nullable=True),
        sa.Column('result_summary',      sa.Text,        server_default=''),
        sa.Column('error',               sa.Text,        server_default=''),
    )
    op.create_index('idx_mcp_audit_tool',      'mcp_audit_log', ['tool_name'])
    op.create_index('idx_mcp_audit_timestamp', 'mcp_audit_log', ['timestamp'])

    op.create_table(
        'mcp_confirmation',
        sa.Column('id',          sa.Integer,     primary_key=True),
        sa.Column('unique_id',   sa.String(36),  nullable=False, unique=True),
        sa.Column('created_at',  sa.DateTime,    nullable=False),
        sa.Column('expires_at',  sa.DateTime,    nullable=False),
        sa.Column('tool_name',   sa.String(100), nullable=False),
        sa.Column('params_json', sa.Text,        server_default='{}'),
        sa.Column('reason',      sa.Text,        server_default=''),
        sa.Column('agent_id',    sa.String(100), server_default='unknown'),
        sa.Column('status',      sa.String(20),  server_default='pending'),
        sa.Column('user_id',     sa.String(36),  nullable=True),
    )
    op.create_index('idx_mcp_conf_status', 'mcp_confirmation', ['status'])


def downgrade():
    op.drop_table('mcp_audit_log')
    op.drop_table('mcp_confirmation')
