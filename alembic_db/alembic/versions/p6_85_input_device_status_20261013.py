# coding=utf-8
"""P6-85: 입력(센서)의 운영 상태 — 수리 중·철거됨·점검 중을 구조화 필드로.

9/4 노트에 '측정부 오류로 수리 중' 이라 적힌 센서가 get_device_freshness 에는
'활성·정지' 로만 나왔다(리허설 F5/B5). 상태를 노트가 아니라 컬럼으로 둔다.

  device_status       ok | repair | removed | maintenance  (기본 ok)
  device_status_note  짧은 사유
  device_status_since 시작 시각(UTC)

세 컬럼 모두 nullable — 기존 행은 NULL(= ok)로 안전하다.

Revision ID: p6_85_input_device_status_20261013
Revises: p6_84_matter_enabled_20261010
Create Date: 2026-10-13
"""
import sqlalchemy as sa
from alembic import op

revision = 'p6_85_input_device_status_20261013'
down_revision = 'p6_84_matter_enabled_20261010'
branch_labels = None
depends_on = None

TABLE = 'input'
COLUMNS = (
    ('device_status', lambda: sa.Column(
        'device_status', sa.String(length=16), nullable=True,
        server_default='ok')),
    ('device_status_note', lambda: sa.Column(
        'device_status_note', sa.Text(), nullable=True)),
    ('device_status_since', lambda: sa.Column(
        'device_status_since', sa.DateTime(), nullable=True)),
)


def _columns(table):
    return {c['name'] for c in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade():
    # 재실행 안전: 이미 있는 컬럼은 건너뛴다.
    have = _columns(TABLE)
    with op.batch_alter_table(TABLE, schema=None) as batch_op:
        for name, make in COLUMNS:
            if name not in have:
                batch_op.add_column(make())


def downgrade():
    have = _columns(TABLE)
    with op.batch_alter_table(TABLE, schema=None) as batch_op:
        for name, _ in reversed(COLUMNS):
            if name in have:
                batch_op.drop_column(name)
