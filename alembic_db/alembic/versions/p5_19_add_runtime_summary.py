# coding=utf-8
"""P5-19: Add summary_json column to function_runtime_state table.

env_coordinator가 사이클 종료 시 UI 요약 스냅샷(운전 모드, 목표 대비 편차,
추세, 환기 유효 개구 면적, 예보 선행 신호, 액추에이터 지령)을 저장한다.
맵 팝업 [현황] 탭이 /api/aot/facility/<uuid>/env_summary 로 읽는다.
NULL 이면 요약 미존재(구버전 데몬 또는 첫 사이클 이전)로 처리한다.

Revision ID: p5_19_add_runtime_summary
Revises: p5_18_add_trigger_schedule
Create Date: 2026-06-11
"""

from alembic import op
import sqlalchemy as sa


revision = 'p5_19_add_runtime_summary'
down_revision = 'p5_18_add_trigger_schedule'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('function_runtime_state') as batch_op:
        batch_op.add_column(
            sa.Column('summary_json', sa.Text(), nullable=True, server_default=None)
        )


def downgrade():
    with op.batch_alter_table('function_runtime_state') as batch_op:
        batch_op.drop_column('summary_json')
