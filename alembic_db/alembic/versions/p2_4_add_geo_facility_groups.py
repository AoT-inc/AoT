# coding=utf-8
"""P2-4: Add groups JSON column to geo_facility.

Stores actuator group definitions (multi-stage curtains, stacked vents,
windward pairs) consumed by env_coordinator group_expander.py.

Schema:
  {
    group_id: {
      mode:          'symmetric' | 'stacked' | 'multi_stage' | 'windward_diff',
      leader:        slot_key,
      members:       [slot_key, ...],
      threshold_pct: float,
    }, ...
  }

Previously the code read `facility.get('groups')` but the column did not
exist, so groups were always empty and group_expander was never used.

Revision ID: p2_4_geo_facility_groups
Revises:     p5_12_add_geo_facility_weather_bindings
Create Date: 2026-05-26
"""

revision = 'p2_4_geo_facility_groups'
down_revision = 'p5_12_add_geo_facility_weather_bindings'
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa


def upgrade():
    with op.batch_alter_table('geo_facility') as batch_op:
        batch_op.add_column(
            sa.Column('groups', sa.JSON(), nullable=True)
        )


def downgrade():
    with op.batch_alter_table('geo_facility') as batch_op:
        batch_op.drop_column('groups')
