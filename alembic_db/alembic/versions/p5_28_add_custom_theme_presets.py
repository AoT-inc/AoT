# coding=utf-8
"""P5-28: Add misc.custom_theme_presets — user-saved theme color presets.

settings/custom_ui 에서 사용자가 지정한 색상 조합을 이름 붙여 저장/관리하는
프리셋 저장소. JSON: {"프리셋명": {color_field: "#RRGGBB", ...}}

Revision ID: p5_28_add_custom_theme_presets
Revises: p5_27_add_facility_setpoint_vpd_columns
Create Date: 2026-07-02
"""

revision = 'p5_28_add_custom_theme_presets'
down_revision = 'p5_27_add_facility_setpoint_vpd_columns'
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa


def _col_names(table):
    conn = op.get_bind()
    return {row[1] for row in conn.execute(sa.text(f"PRAGMA table_info({table})"))}


def upgrade():
    cols = _col_names('misc')
    if 'custom_theme_presets' not in cols:
        with op.batch_alter_table('misc', schema=None) as batch_op:
            batch_op.add_column(sa.Column(
                'custom_theme_presets', sa.Text(), nullable=True,
                server_default='{}'))


def downgrade():
    cols = _col_names('misc')
    if 'custom_theme_presets' in cols:
        with op.batch_alter_table('misc', schema=None) as batch_op:
            batch_op.drop_column('custom_theme_presets')
