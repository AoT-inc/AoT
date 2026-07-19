# coding=utf-8
"""P5-6: Add fittings JSON column to geo_facility.

Stores per-fitting placements from the 3D editor (FittingsUI). With G1
policy, fittings are authoritative for vent area and airflow when present.
Without this column the UI silently lost every placed window/door/fan/sensor
on save.

Revision ID: p5_6_geo_facility_fittings
Revises: p5_3_function_crop_preset
Create Date: 2026-05-17
"""

revision = 'p5_6_geo_facility_fittings'
down_revision = 'p5_3_function_crop_preset'
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa


def upgrade():
    with op.batch_alter_table('geo_facility') as batch_op:
        batch_op.add_column(
            sa.Column('fittings', sa.JSON(), nullable=True)
        )


def downgrade():
    with op.batch_alter_table('geo_facility') as batch_op:
        batch_op.drop_column('fittings')
