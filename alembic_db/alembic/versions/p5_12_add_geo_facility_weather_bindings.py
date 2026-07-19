# coding=utf-8
"""P5-12: Add weather_bindings JSON column to geo_facility.

Stores user-configured forecast/weather Input device connections per facility.
Each entry: {measurement_type, input_uuid, measurement_id, name}
measurement_type values: forecast_temperature | forecast_humidity |
  forecast_wind_speed | forecast_precipitation_prob | forecast_precipitation |
  forecast_solar

Revision ID: p5_12_add_geo_facility_weather_bindings
Revises: p5_11_add_geo_facility_sensors
Create Date: 2026-05-21
"""

revision = 'p5_12_add_geo_facility_weather_bindings'
down_revision = 'p5_11_add_geo_facility_sensors'
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa


def upgrade():
    with op.batch_alter_table('geo_facility') as batch_op:
        batch_op.add_column(
            sa.Column('weather_bindings', sa.JSON(), nullable=True)
        )


def downgrade():
    with op.batch_alter_table('geo_facility') as batch_op:
        batch_op.drop_column('weather_bindings')
