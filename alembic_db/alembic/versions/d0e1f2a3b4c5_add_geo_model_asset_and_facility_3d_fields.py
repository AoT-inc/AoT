"""Add geo_model_asset table and 3D asset fields to geo_facility/geo_setting

Revision ID: d0e1f2a3b4c5
Revises: c7d8e9f0a1b2
Create Date: 2026-05-13

Changes:
  - NEW TABLE : geo_model_asset (user-registered 3D model assets)
  - ALTER     : geo_facility  — add model_asset_uuid, model_transform, render_mode
  - ALTER     : geo_setting   — add length_unit
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import sqlite

revision = 'd0e1f2a3b4c5'
down_revision = 'c7d8e9f0a1b2'
branch_labels = None
depends_on = None


def upgrade():
    # ── 1. geo_model_asset (new table) ────────────────────────────────────────
    op.create_table(
        'geo_model_asset',
        sa.Column('id',             sa.Integer(),    nullable=False),
        sa.Column('unique_id',      sa.String(36),   nullable=False),
        sa.Column('owner_user_id',  sa.Integer(),    nullable=True),
        sa.Column('name',           sa.String(128),  nullable=False, server_default='New Asset'),
        sa.Column('kind',           sa.String(32),   nullable=False, server_default='primitive'),
        sa.Column('spec_json',      sa.JSON(),       nullable=True),
        sa.Column('authored_unit',  sa.String(8),    nullable=False, server_default='m'),
        sa.Column('tags',           sa.Text(),       nullable=True),
        sa.Column('preview_png',    sa.Text(),       nullable=True),
        sa.Column('preview_status', sa.String(16),   nullable=False, server_default='pending'),
        sa.Column('source_file',    sa.Text(),       nullable=True),
        sa.Column('sort_order',     sa.Integer(),    server_default='0'),
        sa.Column('notes',          sa.Text(),       server_default=''),
        sa.Column('created_at',     sa.DateTime(),   nullable=True),
        sa.Column('updated_at',     sa.DateTime(),   nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('unique_id'),
    )
    op.create_index('ix_geo_model_asset_owner_user_id', 'geo_model_asset', ['owner_user_id'])
    op.create_index('ix_geo_model_asset_unique_id',     'geo_model_asset', ['unique_id'])

    # ── 2. geo_facility — three new columns ───────────────────────────────────
    with op.batch_alter_table('geo_facility') as batch_op:
        batch_op.add_column(sa.Column('model_asset_uuid', sa.String(36), nullable=True))
        batch_op.add_column(sa.Column('model_transform',  sa.JSON(),     nullable=True))
        batch_op.add_column(sa.Column('render_mode',      sa.String(16), nullable=False, server_default='parametric'))
    op.create_index('ix_geo_facility_model_asset_uuid', 'geo_facility', ['model_asset_uuid'])

    # ── 3. geo_setting — length_unit ──────────────────────────────────────────
    with op.batch_alter_table('geo_setting') as batch_op:
        batch_op.add_column(sa.Column('length_unit', sa.String(8), nullable=False, server_default='m'))


def downgrade():
    # geo_setting
    with op.batch_alter_table('geo_setting') as batch_op:
        batch_op.drop_column('length_unit')

    # geo_facility
    op.drop_index('ix_geo_facility_model_asset_uuid', table_name='geo_facility')
    with op.batch_alter_table('geo_facility') as batch_op:
        batch_op.drop_column('render_mode')
        batch_op.drop_column('model_transform')
        batch_op.drop_column('model_asset_uuid')

    # geo_model_asset
    op.drop_index('ix_geo_model_asset_unique_id',     table_name='geo_model_asset')
    op.drop_index('ix_geo_model_asset_owner_user_id', table_name='geo_model_asset')
    op.drop_table('geo_model_asset')
