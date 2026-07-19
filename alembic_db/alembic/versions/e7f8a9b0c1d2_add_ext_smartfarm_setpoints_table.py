"""Add ext_smartfarm_setpoints table

Revision ID: e7f8a9b0c1d2
Revises: c1d2e3f4a5b6
Create Date: 2026-03-25

Phase 2a — EXT-KR-01 implementation.
Table is created by SQLAlchemy db.create_all() at startup;
this migration advances the tracked version only.
"""
import sys
import os

sys.path.append(os.path.abspath(os.path.join(__file__, "../../../..")))

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


revision = 'e7f8a9b0c1d2'
down_revision = 'c1d2e3f4a5b6'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = inspect(bind)
    existing_tables = inspector.get_table_names()

    if 'ext_smartfarm_setpoints' not in existing_tables:
        op.create_table(
            'ext_smartfarm_setpoints',
            sa.Column('id',               sa.Integer(),     primary_key=True, autoincrement=True),
            sa.Column('crop_type',        sa.String(64),    nullable=False),
            sa.Column('growth_stage',     sa.String(64),    nullable=False),
            sa.Column('opt_temp_min',     sa.Float(),       nullable=True),
            sa.Column('opt_temp_max',     sa.Float(),       nullable=True),
            sa.Column('opt_humidity_min', sa.Float(),       nullable=True),
            sa.Column('opt_humidity_max', sa.Float(),       nullable=True),
            sa.Column('opt_co2_min',      sa.Float(),       nullable=True),
            sa.Column('opt_co2_max',      sa.Float(),       nullable=True),
            sa.Column('opt_light_min',    sa.Float(),       nullable=True),
            sa.Column('opt_light_max',    sa.Float(),       nullable=True),
            sa.Column('fetched_at',       sa.DateTime(),    nullable=False),
            sa.UniqueConstraint('crop_type', 'growth_stage', name='uq_ext_sf_crop_stage'),
        )
        op.create_index('ix_ext_sf_crop_type',    'ext_smartfarm_setpoints', ['crop_type'])
        op.create_index('ix_ext_sf_growth_stage', 'ext_smartfarm_setpoints', ['growth_stage'])


def downgrade():
    bind = op.get_bind()
    inspector = inspect(bind)
    if 'ext_smartfarm_setpoints' in inspector.get_table_names():
        op.drop_table('ext_smartfarm_setpoints')
