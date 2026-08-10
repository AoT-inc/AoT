# coding=utf-8
"""P6-30: Docker 자동 업데이트 — 활성화 토글과 실행 시각.

Docker 배포판의 업데이트는 업데이터 서비스가 수행한다(docs/design/docker-auto-update.md).
2단계까지는 사람이 버튼을 눌러야 돌았고, 이 두 컬럼이 "켜 두면 지정한 시각에
알아서" 를 만든다.

`docker_auto_update_time` 은 문자열 'HH:MM' 이다. 분 단위 정수(0~1439)로 두면
DB 를 직접 들여다볼 때 읽히지 않고, 시각/분 두 컬럼으로 쪼개면 항상 같이
읽고 같이 써야 하는 짝이 하나 더 생긴다. 해석 기준은 **로컬 시각**이다
(timekit; docs/design/timezone-management.md) — 농장 관리자가 "새벽 3시" 라고
말할 때 뜻하는 그 3시다.

기본값은 꺼짐이다. 켜는 것은 "제어가 잠시 멈추는 일을 사람 없는 시각에
자동으로 하겠다" 는 결정이라, 업그레이드로 조용히 켜지면 안 된다.

Revision ID: p6_30_docker_auto_update_20260810
Revises: p6_29_geo_binding_gb5_20260808
Create Date: 2026-08-10
"""
import sqlalchemy as sa
from alembic import op

revision = 'p6_30_docker_auto_update_20260810'
down_revision = 'p6_29_geo_binding_gb5_20260808'
branch_labels = None
depends_on = None

TABLE = 'misc'
COLUMNS = (
    ('docker_auto_update', sa.Boolean(), False),
    ('docker_auto_update_time', sa.String(length=5), '03:00'),
)


def _has_column(table, column):
    bind = op.get_bind()
    return column in [c['name'] for c in sa.inspect(bind).get_columns(table)]


def upgrade():
    # 재실행 안전: 이미 있으면 건너뛴다.
    with op.batch_alter_table(TABLE, schema=None) as batch_op:
        for name, coltype, default in COLUMNS:
            if _has_column(TABLE, name):
                continue
            batch_op.add_column(sa.Column(
                name, coltype, nullable=True,
                # server_default 를 둬야 기존 행에도 값이 들어간다. NULL 로
                # 두면 데몬이 매 검사마다 None 을 만나고, 시각이 None 인 채
                # 켜져 있으면 "켜졌는데 영원히 안 돈다" 가 된다.
                server_default=sa.text("0") if isinstance(coltype, sa.Boolean)
                else sa.text(f"'{default}'")))


def downgrade():
    with op.batch_alter_table(TABLE, schema=None) as batch_op:
        for name, _coltype, _default in COLUMNS:
            if _has_column(TABLE, name):
                batch_op.drop_column(name)
