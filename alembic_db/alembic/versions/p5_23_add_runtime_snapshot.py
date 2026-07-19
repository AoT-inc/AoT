# coding=utf-8
"""P5-23: Add runtime_json column to function_runtime_state table.

env_coordinator 가 사이클 종료 시 센서 스냅샷(indoor/outdoor/sensors/
fitting_sensors)을 저장한다. 맵 위젯 /api/aot/facility/<uuid>/runtime 이
이를 읽어 InfluxDB 직접 조회를 피한다(저사양 호스트 스레드 풀 포화 방지).
NULL 이면 스냅샷 미존재(코디네이터 없음/구버전 데몬)로 보고 라이브 계산 폴백.

Revision ID: p5_23_add_runtime_snapshot
Revises: p5_22_add_gunicorn_threads
Create Date: 2026-06-13
"""

from alembic import op
import sqlalchemy as sa


revision = 'p5_23_add_runtime_snapshot'
down_revision = 'p5_22_add_gunicorn_threads'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('function_runtime_state') as batch_op:
        batch_op.add_column(
            sa.Column('runtime_json', sa.Text(), nullable=True, server_default=None)
        )


def downgrade():
    with op.batch_alter_table('function_runtime_state') as batch_op:
        batch_op.drop_column('runtime_json')
