"""merge_philosophy_and_ext_heads

Revision ID: c4d5e6f7a8b9
Revises: 36b52ba0, 38b183f3162a
Create Date: 2026-03-26

Merges the Phase 1 Philosophy Schema branch (36b52ba0) with the
ext_pest_alerts branch (38b183f3162a) into a single HEAD.
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c4d5e6f7a8b9'
down_revision = ('36b52ba0', '38b183f3162a')
branch_labels = None
depends_on = None


def upgrade():
    pass


def downgrade():
    pass
