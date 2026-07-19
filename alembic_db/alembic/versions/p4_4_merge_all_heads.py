# coding=utf-8
"""Merge all heads: d0e1f2a3b4c5, bc57e722cb25, p4_3_mcp_audit_tables

Revision ID: p4_4_merge_all_heads
Revises: d0e1f2a3b4c5, bc57e722cb25, p4_3_mcp_audit_tables
Create Date: 2026-05-16
"""

revision = 'p4_4_merge_all_heads'
down_revision = ('d0e1f2a3b4c5', 'bc57e722cb25', 'p4_3_mcp_audit_tables')
branch_labels = None
depends_on = None

from alembic import op


def upgrade():
    pass


def downgrade():
    pass
