"""add geo_facility table

Revision ID: c5d6e7f8a9b0
Revises: e1f2a3b4c5d6
Create Date: 2026-05-03

"""
from alembic import op
import sqlalchemy as sa


revision = 'c5d6e7f8a9b0'
down_revision = 'e1f2a3b4c5d6'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    existing = [r[0] for r in bind.execute(sa.text("SELECT name FROM sqlite_master WHERE type='table'")).fetchall()]
    if 'geo_facility' in existing:
        return
    op.create_table(
        'geo_facility',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('unique_id', sa.String(length=36), nullable=False),
        sa.Column('shape_uuid', sa.String(length=36), nullable=False),
        sa.Column('geo_id', sa.String(length=64), nullable=False),
        sa.Column('name', sa.String(length=128), nullable=False, server_default='New Facility'),
        sa.Column('preset', sa.String(length=64), server_default='standard_arch'),
        sa.Column('structure', sa.String(length=32), server_default='single'),
        sa.Column('bay_count', sa.Integer(), server_default='1'),
        sa.Column('geometry_3d', sa.JSON(), nullable=True),
        sa.Column('envelope', sa.JSON(), nullable=True),
        sa.Column('actuators', sa.JSON(), nullable=True),
        sa.Column('bays', sa.JSON(), nullable=True),
        sa.Column('computed', sa.JSON(), nullable=True),
        sa.Column('sort_order', sa.Integer(), server_default='0'),
        sa.Column('notes', sa.Text(), server_default=''),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.Column('created_by', sa.String(length=36), server_default=''),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('unique_id'),
    )
    op.create_index('ix_geo_facility_shape_uuid', 'geo_facility', ['shape_uuid'])
    op.create_index('ix_geo_facility_geo_id', 'geo_facility', ['geo_id'])


def downgrade():
    op.drop_index('ix_geo_facility_geo_id', table_name='geo_facility')
    op.drop_index('ix_geo_facility_shape_uuid', table_name='geo_facility')
    op.drop_table('geo_facility')
