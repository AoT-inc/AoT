# coding=utf-8
"""P5-8: Add calibration_state_json to function_runtime_state.

Persists CalibrationRegistry (RLS K-hat values, update counts) across daemon
restarts. Without this column, all online learning is lost on every restart.

Revision ID: p5_8_add_calibration_state
Revises: p5_7_geo_facility_commissioning_state
Create Date: 2026-05-19
"""

revision = 'p5_8_add_calibration_state'
down_revision = 'p5_7_geo_facility_commissioning_state'
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa


def upgrade():
    with op.batch_alter_table('function_runtime_state') as batch_op:
        batch_op.add_column(
            sa.Column('calibration_state_json', sa.Text(), nullable=True)
        )


def downgrade():
    with op.batch_alter_table('function_runtime_state') as batch_op:
        batch_op.drop_column('calibration_state_json')
