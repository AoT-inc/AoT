# coding=utf-8
"""P5-7: Add commissioning_state JSON column to geo_facility.

Stores device check wizard results: per-actuator flags (sensor_suspect,
device_fault), calibration anchors, k_upper_bounds, and device alarms.
Previously the code attempted to use a non-existent facility.meta attribute,
causing silent failures on verdict submission.

Revision ID: p5_7_geo_facility_commissioning_state
Revises: p5_6_geo_facility_fittings
Create Date: 2026-05-19
"""

revision = 'p5_7_geo_facility_commissioning_state'
down_revision = 'p5_6_geo_facility_fittings'
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa


def upgrade():
    with op.batch_alter_table('geo_facility') as batch_op:
        batch_op.add_column(
            sa.Column('commissioning_state', sa.JSON(), nullable=True)
        )


def downgrade():
    with op.batch_alter_table('geo_facility') as batch_op:
        batch_op.drop_column('commissioning_state')
