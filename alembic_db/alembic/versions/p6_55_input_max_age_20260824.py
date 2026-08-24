# coding=utf-8
"""P6-55: 장치별 측정 유효 수명 — `Input.max_age_s`.

## 왜 필요한가

"이 값이 늦었는가" 를 **전역 상수**로 판정하면 정상 장치가 고장처럼 보인다.
`Input.period` 는 15초부터 86400초(1일)까지 제각각이라, 하루 한 번 재는 센서는
고정 300초 기준에서 늘 탈락하고 15초 장치는 반대로 너무 오래된 값을 받는다.
그래서 표시 경로는 이미 **주기 대비**(period × 계수)로 판정한다.

그런데 제어 경로(env_coordinator)만 예외였다. 코디네이터의 `sensor_max_age`
하나가 모든 장치에 적용돼, 주기가 다른 소스를 섞을 수 없었다 — 실외를
기상대(60초)와 기상청(10분)으로 이중화하려 해도 한 숫자에 둘을 끼워 맞춰야 했다.

이 컬럼은 그 자리를 만든다. **파생이 기본이고 명시가 예외다**:

    NULL  → 주기에서 파생 (기존 동작 그대로)
    숫자  → 사람이 정한 값이 이긴다

## 이 마이그레이션은 아무것도 바꾸지 않는다

모든 기존 행이 NULL 이므로 판정은 전부 종전 경로(요청값 → 주기 파생 → 기본값)를
탄다. 업그레이드 직후의 동작은 비트 단위로 이전과 같다. 백필하지 않는 이유도
같다 — 값을 채우는 순간 그것이 "사람이 정한 값" 으로 보이는데, 아무도 정하지
않았다.

Revision ID: p6_55_input_max_age_20260824
Revises: p6_54_user_groups_20260823
Create Date: 2026-08-24
"""
import sqlalchemy as sa
from alembic import op

revision = 'p6_55_input_max_age_20260824'
down_revision = 'p6_54_user_groups_20260823'
branch_labels = None
depends_on = None


def _columns(bind, table):
    return {c['name'] for c in sa.inspect(bind).get_columns(table)}


def upgrade():
    bind = op.get_bind()
    if 'max_age_s' in _columns(bind, 'input'):
        return                      # 재실행 안전
    with op.batch_alter_table('input', schema=None) as batch:
        batch.add_column(sa.Column('max_age_s', sa.Integer(), nullable=True))


def downgrade():
    bind = op.get_bind()
    if 'max_age_s' not in _columns(bind, 'input'):
        return
    with op.batch_alter_table('input', schema=None) as batch:
        batch.drop_column('max_age_s')
