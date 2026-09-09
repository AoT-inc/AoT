# coding=utf-8
"""P6-63: 모바일 전체 폭을 위젯 인스턴스 설정으로 — `widget.mobile_full_width`.

## 왜 필요한가

모바일(2열 격자)에서 위젯이 한 줄을 통째로 쓸지는 지금까지 **위젯 모듈**이
`WIDGET_INFORMATION['mobile_full_width']` 로 종류마다 고정했다. 같은 종류의
위젯은 사용자가 바꿀 수 없었고, 옵션이 있다는 사실조차 화면에 없었다.
이 열은 그 값을 인스턴스별 사용자 설정으로 격상한다. 모듈 쪽 값은 남지만
이제 **새로 추가할 때의 기본값**으로만 쓰인다.

## 기존 행의 초기값 — 화면이 그대로여야 한다

업그레이드로 이미 놓인 대시보드의 모바일 배치가 달라지면 안 된다. 지금까지
전체 폭이 되던 조건은 둘이었고(`dashboard.js` `syncLayout`),

  1. 위젯 종류가 `mobile_full_width: True` 를 선언했거나
  2. 데스크톱 폭이 12(24열의 절반)를 넘거나

둘 중 하나였다. 그래서 여기서도 **둘 다** 참으로 채운다. 2번을 빼면 넓게
늘려 둔 위젯이 업그레이드 후 갑자기 반 폭으로 접힌다.

앞으로는 이 열 하나가 판정 기준이다(`syncLayout` 의 폭 > 12 규칙도 없앴다).
넓게 만든 위젯이 저절로 전체 폭이 되는 대신, 토글이 죽은 노브가 되지 않는다.

## 종류 목록을 문자열로 박아 둔 이유

마이그레이션은 그 시점의 사실을 굳혀야 한다. 위젯 모듈을 import 해서 읽으면
나중에 모듈의 기본값이 바뀔 때 **과거 데이터의 초기값이 함께 흔들린다.**

Revision ID: p6_63_widget_mobile_full_width_20260908
Revises: p6_62_geo_journal_20260902
Create Date: 2026-09-08
"""
import sqlalchemy as sa
from alembic import op

revision = 'p6_63_widget_mobile_full_width_20260908'
down_revision = 'p6_62_geo_journal_20260902'
branch_labels = None
depends_on = None

# 2026-09-08 기준으로 WIDGET_INFORMATION['mobile_full_width'] = True 를
# 선언하고 있던 위젯 종류(widget_name_unique).
FULL_WIDTH_TYPES = (
    'AoT_pid',
    'AoT_plot',
    'AoT_map',
    'AoT_facility',
    'widget_calendar',
    'widget_trigger_sequence',
    'widget_notice',
    'widget_python_code',
    'AoT_controller_act_deact',
    'AoT_timer',
)


def _has_column(table, column):
    bind = op.get_bind()
    rows = bind.execute(sa.text(f"PRAGMA table_info({table})")).fetchall()
    return any(r[1] == column for r in rows)


def upgrade():
    if _has_column('widget', 'mobile_full_width'):
        return
    op.add_column(
        'widget',
        sa.Column('mobile_full_width', sa.Boolean(), nullable=True,
                  server_default=sa.false()))
    bind = op.get_bind()
    placeholders = ', '.join(f":t{i}" for i in range(len(FULL_WIDTH_TYPES)))
    params = {f"t{i}": t for i, t in enumerate(FULL_WIDTH_TYPES)}
    bind.execute(
        sa.text(
            "UPDATE widget SET mobile_full_width = 1 "
            f"WHERE graph_type IN ({placeholders}) OR width > 12"),
        params)
    bind.execute(sa.text(
        "UPDATE widget SET mobile_full_width = 0 WHERE mobile_full_width IS NULL"))


def downgrade():
    if _has_column('widget', 'mobile_full_width'):
        op.drop_column('widget', 'mobile_full_width')
