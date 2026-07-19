"""add timezone column to pid table

Revision ID: c6d7e8f9a0b1
Revises: c5d6e7f8a9b0
Create Date: 2026-05-07

"""
from alembic import op
import sqlalchemy as sa


revision = 'c6d7e8f9a0b1'
down_revision = 'c5d6e7f8a9b0'
branch_labels = None
depends_on = None


def _has_column(table, column):
    conn = op.get_bind()
    rows = conn.execute(sa.text(f"PRAGMA table_info({table})")).fetchall()
    return any(row[1] == column for row in rows)


def upgrade():
    if not _has_column('pid', 'timezone'):
        op.add_column('pid', sa.Column('timezone', sa.String(length=64), nullable=True))


def downgrade():
    # SQLite does not support DROP COLUMN — leave in place
    pass
