# coding=utf-8
"""P5-27: Add missing VPD columns to geo_facility_setpoint.

p5_10 and p5_13 were on separate revision branches.
p5_13 restructured the table but assumed target_vpd_kpa / guide_* were
already present (added by p5_10). DBs that followed the p5_13 branch
ended up without these five columns.

Revision ID: p5_27_add_facility_setpoint_vpd_columns
Revises: p5_26_fix_pid_device_measurements
Create Date: 2026-06-25
"""

revision = 'p5_27_add_facility_setpoint_vpd_columns'
down_revision = 'p5_26_fix_pid_device_measurements'
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa


def _col_names(table):
    conn = op.get_bind()
    return {row[1] for row in conn.execute(sa.text(f"PRAGMA table_info({table})"))}


def upgrade():
    cols = _col_names('geo_facility_setpoint')
    with op.batch_alter_table('geo_facility_setpoint', schema=None) as batch_op:
        if 'target_vpd_kpa' not in cols:
            batch_op.add_column(sa.Column('target_vpd_kpa',   sa.Float(), nullable=True))
        if 'guide_t_min_c' not in cols:
            batch_op.add_column(sa.Column('guide_t_min_c',    sa.Float(), nullable=True))
        if 'guide_t_max_c' not in cols:
            batch_op.add_column(sa.Column('guide_t_max_c',    sa.Float(), nullable=True))
        if 'guide_rh_min_pct' not in cols:
            batch_op.add_column(sa.Column('guide_rh_min_pct', sa.Float(), nullable=True))
        if 'guide_rh_max_pct' not in cols:
            batch_op.add_column(sa.Column('guide_rh_max_pct', sa.Float(), nullable=True))


def downgrade():
    cols = _col_names('geo_facility_setpoint')
    with op.batch_alter_table('geo_facility_setpoint', schema=None) as batch_op:
        if 'guide_rh_max_pct' in cols:
            batch_op.drop_column('guide_rh_max_pct')
        if 'guide_rh_min_pct' in cols:
            batch_op.drop_column('guide_rh_min_pct')
        if 'guide_t_max_c' in cols:
            batch_op.drop_column('guide_t_max_c')
        if 'guide_t_min_c' in cols:
            batch_op.drop_column('guide_t_min_c')
        if 'target_vpd_kpa' in cols:
            batch_op.drop_column('target_vpd_kpa')
