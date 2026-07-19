"""Merge heads: camera fields + ai_enabled

Revision ID: 68e82f214735
Revises: 68e82f214734, f8a9b2c3d4e5
Create Date: 2026-03-06

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '68e82f214735'
down_revision = ('68e82f214734', 'f8a9b2c3d4e5')
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
