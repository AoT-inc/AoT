# coding=utf-8
"""P6-60: 환경 코디네이터 추세 히스토리를 사이클 간 보존 — `FunctionRuntimeState.trend_state_json`.

## 왜 필요한가

`EnvCoordinator` 는 사이클마다(활성 시설당 5~10분 주기) **새로 만들어진다**
(로그로 실측: "EnvCoordinator initialised" 가 사이클마다 반복). `integral`·
`prev_commands`·`active_vars`·캘리브레이션은 이 재생성을 견디도록 이미
`function_runtime_state` 에 저장·복원되는데(`RuntimeStateMixin`), 추세
히스토리(`TrendState.history`, 2점 이상 최소제곱 회귀의 재료)만 이 목록에서
빠져 있었다.

그 결과 매 사이클 `TrendState()` 가 빈 상태로 새로 만들어지고, 그 사이클
안에서 관측 1점만 쌓인 채 회귀에 들어간다 — 점 2개 미만이면 기울기는
**항상 0** 이다(`_slope_per_min`). 맵 팝업 [현황] → [환경] 카드는 반올림해서
0 으로 보일 값을 내지 않으므로(`_trendNote`), 추세 줄은 화면에서 조용히
사라진다 — 에러도, 로그도 없다. 실측(2026-08-28): 서로 다른 3개 시설의
`summary_json.trend` 가 전부 `{T:0.0, RH:0.0, CO2:0.0}` 또는 `None` 이었다.

## 무엇을 저장하는가

`TrendState.history` 하나뿐이다(`Dict[str, List[Tuple[float, float]]]`).
`window_sec` 은 저장하지 않는다 — `assess()` 가 매 호출마다 그 사이클의
`cycle_sec` 기준으로 다시 정하므로(situation.py `ts.window_sec = max(...)`),
저장된 값을 복원해도 곧바로 덮어써진다.

기존 행은 전부 NULL 이며(신선한 코디네이터와 동일하게 시작) 추세 계산 외
어디도 이 값을 읽지 않는다 — 업그레이드 직후 동작은 이전과 같다.

Revision ID: p6_60_env_coordinator_trend_state_20260828
Revises: p6_59_knowledge_source_ref_20260825
Create Date: 2026-08-28
"""
import sqlalchemy as sa
from alembic import op

revision = 'p6_60_env_coordinator_trend_state_20260828'
down_revision = 'p6_59_knowledge_source_ref_20260825'
branch_labels = None
depends_on = None


def _columns(bind, table):
    return {c['name'] for c in sa.inspect(bind).get_columns(table)}


def upgrade():
    bind = op.get_bind()
    if 'trend_state_json' in _columns(bind, 'function_runtime_state'):
        return                      # 재실행 안전
    with op.batch_alter_table('function_runtime_state', schema=None) as batch:
        batch.add_column(sa.Column('trend_state_json', sa.Text(), nullable=True))


def downgrade():
    bind = op.get_bind()
    if 'trend_state_json' not in _columns(bind, 'function_runtime_state'):
        return
    with op.batch_alter_table('function_runtime_state', schema=None) as batch:
        batch.drop_column('trend_state_json')
