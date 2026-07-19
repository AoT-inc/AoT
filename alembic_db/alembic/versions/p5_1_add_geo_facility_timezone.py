# coding=utf-8
"""P5-1: Add timezone column to geo_facility.

Revision ID: p5_1_geo_facility_timezone
Revises: p4_4_merge_all_heads
Create Date: 2026-05-16
"""

revision = 'p5_1_geo_facility_timezone'
down_revision = 'p4_4_merge_all_heads'
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa


def upgrade():
    with op.batch_alter_table('geo_facility') as batch_op:
        batch_op.add_column(
            sa.Column('timezone', sa.String(64), nullable=True, server_default=None)
        )


def downgrade():
    with op.batch_alter_table('geo_facility') as batch_op:
        batch_op.drop_column('timezone')
