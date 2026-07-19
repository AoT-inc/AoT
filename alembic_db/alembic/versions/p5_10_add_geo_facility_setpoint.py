# coding=utf-8
"""P5-10: Add geo_facility_setpoint table for IEC widget setpoints.

Stores one row per facility with operator-defined setpoints that mirror
the env_coordinator Function settings (target_vpd, guide ranges, constraints, co2).

Column mapping to env_coordinator custom_options:
  target_vpd_kpa    → target_vpd        (L1 primary VPD target)
  guide_t_min_c     → guide_T_min       (VPD decomposition T guidance range)
  guide_t_max_c     → guide_T_max
  guide_rh_min_pct  → guide_RH_min      (VPD decomposition RH guidance range)
  guide_rh_max_pct  → guide_RH_max
  temp_min_c        → temp_min          (hard safety constraint — forces heating)
  temp_max_c        → temp_max          (hard safety constraint — forces cooling)
  humid_min_pct     → humid_min         (hard safety constraint)
  humid_max_pct     → humid_max
  target_co2_ppm    → target_co2        (secondary CO2 target)

Revision ID: p5_10_geo_facility_setpoint
Revises: p5_9_geo_facility_view_options
Create Date: 2026-05-21
"""

revision = 'p5_10_geo_facility_setpoint'
down_revision = 'p5_9_geo_facility_view_options'
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa


def upgrade():
    op.create_table(
        'geo_facility_setpoint',
        sa.Column('id',               sa.Integer(),  nullable=False, primary_key=True),
        sa.Column('unique_id',        sa.String(36), nullable=False, unique=True),
        sa.Column('facility_uuid',    sa.String(36), nullable=False, unique=True, index=True),
        # VPD — primary control target
        sa.Column('target_vpd_kpa',   sa.Float(),    nullable=True),
        # VPD decomposition guidance ranges (T and RH target bands)
        sa.Column('guide_t_min_c',    sa.Float(),    nullable=True),
        sa.Column('guide_t_max_c',    sa.Float(),    nullable=True),
        sa.Column('guide_rh_min_pct', sa.Float(),    nullable=True),
        sa.Column('guide_rh_max_pct', sa.Float(),    nullable=True),
        # Hard safety constraints (override VPD control)
        sa.Column('temp_min_c',       sa.Float(),    nullable=True),
        sa.Column('temp_max_c',       sa.Float(),    nullable=True),
        sa.Column('humid_min_pct',    sa.Float(),    nullable=True),
        sa.Column('humid_max_pct',    sa.Float(),    nullable=True),
        # CO2 — secondary target
        sa.Column('target_co2_ppm',   sa.Float(),    nullable=True),
        # Metadata
        sa.Column('source',           sa.String(16), nullable=False, server_default='manual'),
        sa.Column('operator',         sa.String(64), nullable=True),
        sa.Column('updated_at',       sa.DateTime(), nullable=True),
    )


def downgrade():
    op.drop_table('geo_facility_setpoint')
