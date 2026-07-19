# coding=utf-8
"""P5-45: Add enable_auto_vpd toggle to misc.

Global system-wide switch for automatic VPD (vapor pressure deficit)
calculation. When enabled, any Input measuring temperature + humidity gets a
VPD channel auto-populated at measurement time (see aot/utils/auto_vpd.py).

Revision ID: p5_45_add_misc_enable_auto_vpd
Revises: p5_44_add_knowledge_chunk_facility_scope
Create Date: 2026-07-15
"""

revision = 'p5_45_add_misc_enable_auto_vpd'
down_revision = 'p5_44_add_knowledge_chunk_facility_scope'
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa


def upgrade():
    with op.batch_alter_table('misc') as batch_op:
        batch_op.add_column(
            sa.Column('enable_auto_vpd', sa.Boolean(), nullable=True)
        )


def downgrade():
    with op.batch_alter_table('misc') as batch_op:
        batch_op.drop_column('enable_auto_vpd')
