"""Merge multiple heads

Revision ID: b8b3c27f6082
Revises: a1b2c3d4e5f6, b58bdb9fb18f
Create Date: 2026-02-22 13:41:08.854209

"""
import sys
import os

sys.path.append(os.path.abspath(os.path.join(__file__, "../../../..")))

# from alembic_db.alembic_post_utils import write_revision_post_alembic

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b8b3c27f6082'
down_revision = ('a1b2c3d4e5f6', 'b58bdb9fb18f')
branch_labels = None
depends_on = None


def upgrade():
    # write_revision_post_alembic(revision)

    pass


def downgrade():
    pass
