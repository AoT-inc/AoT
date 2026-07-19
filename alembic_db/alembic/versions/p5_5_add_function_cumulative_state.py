# coding=utf-8
"""P5-5: Add function_cumulative_state table for DLI/GDD daily accumulation.

Revision ID: p5_5_function_cumulative_state
Revises: p5_1_geo_facility_timezone
Create Date: 2026-05-16
"""

revision = 'p5_5_function_cumulative_state'
down_revision = 'p5_1_geo_facility_timezone'
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa


def upgrade():
    op.create_table(
        'function_cumulative_state',
        sa.Column('function_id',             sa.String(36),  nullable=False),
        sa.Column('date',                    sa.Date(),      nullable=False),
        sa.Column('dli_actual',              sa.Float(),     nullable=True, server_default='0.0'),
        sa.Column('gdd_actual',              sa.Float(),     nullable=True, server_default='0.0'),
        sa.Column('vpd_hours',               sa.Float(),     nullable=True, server_default='0.0'),
        sa.Column('co2_hours',               sa.Float(),     nullable=True, server_default='0.0'),
        sa.Column('dli_target',              sa.Float(),     nullable=True),
        sa.Column('gdd_target',              sa.Float(),     nullable=True),
        sa.Column('debt_dli',                sa.Float(),     nullable=True, server_default='0.0'),
        sa.Column('debt_gdd',                sa.Float(),     nullable=True, server_default='0.0'),
        sa.Column('compensation_attempted',  sa.Text(),      nullable=True),
        sa.Column('updated_at',              sa.Float(),     nullable=True, server_default='0.0'),
        sa.PrimaryKeyConstraint('function_id', 'date'),
    )
    op.create_index(
        'ix_function_cumulative_state_function_id',
        'function_cumulative_state', ['function_id'],
    )


def downgrade():
    op.drop_index('ix_function_cumulative_state_function_id',
                  table_name='function_cumulative_state')
    op.drop_table('function_cumulative_state')
