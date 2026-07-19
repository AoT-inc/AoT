# coding=utf-8
"""P5-16: Add schedule_start_time and schedule_week_offset to PID table.

DailyMultiPoint method 의 다중 주차 keyframe 진행을 PID에서도
env_coordinator 와 동일하게 재배 시작일 기준으로 추적하기 위한 컬럼 추가.

Revision ID: p5_16_add_pid_schedule_fields
Revises: p5_15_add_trigger_weekday
Create Date: 2026-06-05
"""

from alembic import op
import sqlalchemy as sa


revision = 'p5_16_add_pid_schedule_fields'
down_revision = 'p5_15_add_trigger_weekday'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('pid') as batch_op:
        batch_op.add_column(
            sa.Column('schedule_start_time', sa.Text(), nullable=True, server_default=None)
        )
        batch_op.add_column(
            sa.Column('schedule_week_offset', sa.Float(), nullable=True, server_default='0.0')
        )


def downgrade():
    with op.batch_alter_table('pid') as batch_op:
        batch_op.drop_column('schedule_week_offset')
        batch_op.drop_column('schedule_start_time')
