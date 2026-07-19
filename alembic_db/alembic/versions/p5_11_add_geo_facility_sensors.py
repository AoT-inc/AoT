# coding=utf-8
"""P5-11: Add sensors JSON column to geo_facility.

Stores sensor placement data (position, size, input_id) for sensor
overlays rendered in the 3D facility editor and AoT_map widget.

Revision ID: p5_11_add_geo_facility_sensors
Revises: p5_10_geo_facility_setpoint
Create Date: 2026-05-21
"""

revision = 'p5_11_add_geo_facility_sensors'
down_revision = 'p5_10_geo_facility_setpoint'
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa


def upgrade():
    with op.batch_alter_table('geo_facility') as batch_op:
        batch_op.add_column(
            sa.Column('sensors', sa.JSON(), nullable=True)
        )


def downgrade():
    with op.batch_alter_table('geo_facility') as batch_op:
        batch_op.drop_column('sensors')
