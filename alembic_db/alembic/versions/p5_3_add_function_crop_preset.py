# coding=utf-8
"""P3-2': Add function_crop_preset table for photosynthesis model presets.

Revision ID: p5_3_function_crop_preset
Revises: p5_5_function_cumulative_state
Create Date: 2026-05-16
"""

revision = 'p5_3_function_crop_preset'
down_revision = 'p5_5_function_cumulative_state'
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa


def upgrade():
    op.create_table(
        'function_crop_preset',
        sa.Column('id',           sa.Integer(),     nullable=False, primary_key=True, autoincrement=True),
        sa.Column('crop_key',     sa.String(64),    nullable=False, unique=True),
        sa.Column('display_name', sa.String(128),   nullable=False, server_default=''),
        sa.Column('A_max',        sa.Float(),       nullable=False, server_default='20.0'),
        sa.Column('K_L',          sa.Float(),       nullable=False, server_default='100.0'),
        sa.Column('K_C',          sa.Float(),       nullable=False, server_default='600.0'),
        sa.Column('T_opt',        sa.Float(),       nullable=False, server_default='22.0'),
        sa.Column('T_sigma',      sa.Float(),       nullable=False, server_default='5.0'),
        sa.Column('VPD_half',     sa.Float(),       nullable=False, server_default='1.0'),
        sa.Column('T_base',       sa.Float(),       nullable=False, server_default='10.0'),
        sa.Column('notes',        sa.Text(),        nullable=True,  server_default=''),
        sa.Column('created_at',   sa.DateTime(),    nullable=True),
    )
    op.create_index('ix_function_crop_preset_crop_key',
                    'function_crop_preset', ['crop_key'], unique=True)


def downgrade():
    op.drop_index('ix_function_crop_preset_crop_key',
                  table_name='function_crop_preset')
    op.drop_table('function_crop_preset')
