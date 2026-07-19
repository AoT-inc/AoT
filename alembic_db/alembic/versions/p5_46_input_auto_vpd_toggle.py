# coding=utf-8
"""P5-46: Move auto-VPD toggle from global (misc) to per-input.

VPD(수증기압차) 자동 계산을 전역 서비스에서 입력별 옵트인으로 변경한다.
misc.enable_auto_vpd(전역 토글, p5_45)를 제거하고, 대신 각 Input 에
auto_vpd_enabled 를 두어 원하는 입력에서만 VPD 채널을 자동 기록한다.

Revision ID: p5_46_input_auto_vpd_toggle
Revises: p5_45_add_misc_enable_auto_vpd
Create Date: 2026-07-15
"""

revision = 'p5_46_input_auto_vpd_toggle'
down_revision = 'p5_45_add_misc_enable_auto_vpd'
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa


def upgrade():
    with op.batch_alter_table('input') as batch_op:
        batch_op.add_column(
            sa.Column('auto_vpd_enabled', sa.Boolean(), nullable=True)
        )
    with op.batch_alter_table('misc') as batch_op:
        batch_op.drop_column('enable_auto_vpd')


def downgrade():
    with op.batch_alter_table('misc') as batch_op:
        batch_op.add_column(
            sa.Column('enable_auto_vpd', sa.Boolean(), nullable=True)
        )
    with op.batch_alter_table('input') as batch_op:
        batch_op.drop_column('auto_vpd_enabled')
