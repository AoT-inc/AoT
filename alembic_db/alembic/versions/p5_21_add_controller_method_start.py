# coding=utf-8
"""P5-21: Add method_start_time column to custom_controller table.

env_coordinator 의 VPD/CO2 Method setpoint 코드는 PID 와 동일하게
custom_controller.method_start_time 을 읽고 기록하지만, 이 컬럼은 pid
테이블에만 존재했다. 그 결과 Method 핸들러 초기화가 매 사이클 실패해
('VPD method load failed') setpoint 가 None 으로 떨어지고, 목표값이
guide 중간값에 고정되는 문제가 있었다.

Revision ID: p5_21_add_controller_method_start
Revises: p5_20_add_facility_photo
Create Date: 2026-06-11
"""

from alembic import op
import sqlalchemy as sa


revision = 'p5_21_add_controller_method_start'
down_revision = 'p5_20_add_facility_photo'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('custom_controller') as batch_op:
        batch_op.add_column(
            sa.Column('method_start_time', sa.Text(), nullable=True, server_default=None)
        )


def downgrade():
    with op.batch_alter_table('custom_controller') as batch_op:
        batch_op.drop_column('method_start_time')
