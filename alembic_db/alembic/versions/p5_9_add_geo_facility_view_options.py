# coding=utf-8
"""P5-9: Add view_options JSON column to geo_facility.

Persists UI display options (category visibility toggles) set in the 3D
editor. AoT_map widget reads the same value to filter which fitting
categories are rendered on the map.

Revision ID: p5_9_geo_facility_view_options
Revises: p5_8_add_calibration_state
Create Date: 2026-05-21
"""

revision = 'p5_9_geo_facility_view_options'
down_revision = 'p5_8_add_calibration_state'
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa


def upgrade():
    with op.batch_alter_table('geo_facility') as batch_op:
        batch_op.add_column(
            sa.Column('view_options', sa.JSON(), nullable=True)
        )


def downgrade():
    with op.batch_alter_table('geo_facility') as batch_op:
        batch_op.drop_column('view_options')
