"""add timezone column to device tables (input, output, custom_controller, function, conditional, trigger)

Revision ID: c7d8e9f0a1b2
Revises: c6d7e8f9a0b1
Create Date: 2026-05-07

"""
from alembic import op
import sqlalchemy as sa

revision = 'c7d8e9f0a1b2'
down_revision = 'c6d7e8f9a0b1'
branch_labels = None
depends_on = None

TARGET_TABLES = [
    'input',
    'output',
    'custom_controller',
    'function',
    'conditional',
    'trigger',
]


def _has_column(table, column):
    conn = op.get_bind()
    rows = conn.execute(sa.text(f"PRAGMA table_info({table})")).fetchall()
    return any(row[1] == column for row in rows)


def upgrade():
    for table in TARGET_TABLES:
        if not _has_column(table, 'timezone'):
            op.add_column(table, sa.Column('timezone', sa.String(length=64), nullable=True))


def downgrade():
    # SQLite does not support DROP COLUMN — left in place
    pass
