# coding=utf-8
"""P5-13: Refactor geo_facility_setpoint to VPD-based schema.

Removes legacy absolute-value columns (target_temp_c, temp_band_c,
target_rh_pct, co2_cap_ppm) and replaces them with VPD-centric schema:
- target_vpd_kpa, guide_t_min/max_c, guide_rh_min/max_pct (from p5_10)
- temp_min_c, temp_max_c, humid_min_pct, humid_max_pct (hard safety bounds)
- target_co2_ppm (renamed from co2_cap_ppm)

Also cleans up stale migration-tracking columns from geo_shape / geo_map,
updates geo_model_asset index, notes.tier NOT NULL,
and scheduler_jobs_meta.schedule_type Enum + FK cascade.

Revision ID: p5_13_refactor_facility_setpoint_schema
Revises: p2_4_geo_facility_groups
Create Date: 2026-06-04
"""

revision = 'p5_13_refactor_facility_setpoint_schema'
down_revision = 'p2_4_geo_facility_groups'
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa


def _col_names(table):
    conn = op.get_bind()
    return {row[1] for row in conn.execute(sa.text(f"PRAGMA table_info({table})"))}


def _index_names(table):
    conn = op.get_bind()
    return {row[1] for row in conn.execute(sa.text(f"PRAGMA index_list({table})"))}


def upgrade():
    # --- geo_facility_setpoint: drop legacy columns, add new schema ---
    cols = _col_names('geo_facility_setpoint')
    with op.batch_alter_table('geo_facility_setpoint', schema=None) as batch_op:
        if 'temp_min_c' not in cols:
            batch_op.add_column(sa.Column('temp_min_c',    sa.Float(), nullable=True))
        if 'temp_max_c' not in cols:
            batch_op.add_column(sa.Column('temp_max_c',    sa.Float(), nullable=True))
        if 'humid_min_pct' not in cols:
            batch_op.add_column(sa.Column('humid_min_pct', sa.Float(), nullable=True))
        if 'humid_max_pct' not in cols:
            batch_op.add_column(sa.Column('humid_max_pct', sa.Float(), nullable=True))
        if 'target_co2_ppm' not in cols:
            batch_op.add_column(sa.Column('target_co2_ppm', sa.Float(), nullable=True))
        if 'target_rh_pct' in cols:
            batch_op.drop_column('target_rh_pct')
        if 'temp_band_c' in cols:
            batch_op.drop_column('temp_band_c')
        if 'target_temp_c' in cols:
            batch_op.drop_column('target_temp_c')
        if 'co2_cap_ppm' in cols:
            batch_op.drop_column('co2_cap_ppm')

    # --- geo_map: remove stale schema_version tracking column ---
    if 'schema_version' in _col_names('geo_map'):
        with op.batch_alter_table('geo_map', schema=None) as batch_op:
            batch_op.drop_column('schema_version')

    # --- geo_model_asset: replace non-unique index with proper unique index on id ---
    with op.batch_alter_table('geo_model_asset', schema=None) as batch_op:
        if 'ix_geo_model_asset_unique_id' in _index_names('geo_model_asset'):
            batch_op.drop_index('ix_geo_model_asset_unique_id')
        batch_op.create_unique_constraint('uq_geo_model_asset_id', ['id'])

    # --- geo_shape: remove stale migration-tracking columns ---
    shape_cols = _col_names('geo_shape')
    with op.batch_alter_table('geo_shape', schema=None) as batch_op:
        if 'migrated_at' in shape_cols:
            batch_op.drop_column('migrated_at')
        if 'original_data' in shape_cols:
            batch_op.drop_column('original_data')
        if 'schema_version' in shape_cols:
            batch_op.drop_column('schema_version')
        if 'migrated_from_version' in shape_cols:
            batch_op.drop_column('migrated_from_version')

    # --- notes.tier: enforce NOT NULL (default=2 already set) ---
    with op.batch_alter_table('notes', schema=None) as batch_op:
        batch_op.alter_column('tier',
               existing_type=sa.INTEGER(),
               nullable=False,
               existing_server_default=sa.text('2'))

    # --- scheduler_jobs_meta: schedule_type → Enum ---
    # FK ondelete='SET NULL' not applied here; SQLite does not enforce named FKs.
    with op.batch_alter_table('scheduler_jobs_meta', schema=None) as batch_op:
        batch_op.alter_column('schedule_type',
               existing_type=sa.VARCHAR(length=10),
               type_=sa.Enum('device', 'human', 'ai_system', name='scheduletype'),
               existing_nullable=False,
               existing_server_default=sa.text("'ai_system'"))


def downgrade():
    with op.batch_alter_table('scheduler_jobs_meta', schema=None) as batch_op:
        batch_op.alter_column('schedule_type',
               existing_type=sa.Enum('device', 'human', 'ai_system', name='scheduletype'),
               type_=sa.VARCHAR(length=10),
               existing_nullable=False,
               existing_server_default=sa.text("'ai_system'"))

    with op.batch_alter_table('notes', schema=None) as batch_op:
        batch_op.alter_column('tier',
               existing_type=sa.INTEGER(),
               nullable=True,
               existing_server_default=sa.text('2'))

    with op.batch_alter_table('geo_shape', schema=None) as batch_op:
        batch_op.add_column(sa.Column('migrated_from_version', sa.INTEGER(), nullable=True))
        batch_op.add_column(sa.Column('schema_version', sa.INTEGER(),
                                      server_default=sa.text("'2'"), nullable=True))
        batch_op.add_column(sa.Column('original_data', sa.TEXT(), nullable=True))
        batch_op.add_column(sa.Column('migrated_at', sa.DATETIME(), nullable=True))

    with op.batch_alter_table('geo_model_asset', schema=None) as batch_op:
        batch_op.drop_constraint('uq_geo_model_asset_id', type_='unique')
        batch_op.create_index('ix_geo_model_asset_unique_id', ['unique_id'], unique=False)

    with op.batch_alter_table('geo_map', schema=None) as batch_op:
        batch_op.add_column(sa.Column('schema_version', sa.INTEGER(),
                                      server_default=sa.text("'2'"), nullable=True))

    with op.batch_alter_table('geo_facility_setpoint', schema=None) as batch_op:
        batch_op.add_column(sa.Column('co2_cap_ppm',    sa.FLOAT(), nullable=True))
        batch_op.add_column(sa.Column('target_temp_c',  sa.FLOAT(), nullable=True))
        batch_op.add_column(sa.Column('temp_band_c',    sa.FLOAT(), nullable=True))
        batch_op.add_column(sa.Column('target_rh_pct',  sa.FLOAT(), nullable=True))
        batch_op.drop_column('target_co2_ppm')
        batch_op.drop_column('humid_max_pct')
        batch_op.drop_column('humid_min_pct')
        batch_op.drop_column('temp_max_c')
        batch_op.drop_column('temp_min_c')
