# coding=utf-8
"""P6-50: 시설 구획의 몫 — `geo_plot.allocation`.

시설 구획은 기하가 없고 위치가 `facility_uuid`+`bay_id` 다(p6_39). 그래서 같은
구역에 구획을 둘 만들면 **둘 다 "그 구역 전체"를 가리킨다** — 화면도 서버도 둘을
구분할 수단이 없었다. 겹치기 자체는 정상이지만(간작·혼작, VP-3) 얼마씩인지 말할
길이 없는 것이 문제였다.

## 왜 기하가 아니라 스칼라인가

온실 안에 폴리곤을 그리게 하는 안은 셋으로 무너진다 — (1) 시설 구획의 요지가
좌표를 묻지 않는 것이고 (2) 시설을 다시 그리면 구획이 옛 자리에 남고 (3) 베드형·
수직형은 바닥 면적이 재배 규모와 무관하다(같은 100㎡ 가 3단이면 300㎡ 다).
`plot_context` 가 시설 구획에 `area_m2` 를 내지 않는 이유가 이미 그것이다.

## 담는 모양

    {"amount": 4}      구역 총량(`bays[].capacity.total`) 대비 차지한 몫
    {"percent": 33}    총량이 없는 시설에서의 폴백

비율은 **저장하지 않는다** — `amount/total` 에서 파생한다(정본을 둘로 만들지
않는다). `percent` 는 총량을 아직 적지 않은 시설에서만 쓰는 별개 축이다.

컬럼 하나에 dict 를 담는 이유는 단위·총량이 시설 쪽(`geo_facility.bays[]`)에
있기 때문이다 — 여기에 `amount`/`percent` 두 정수 컬럼을 만들면 둘 다 NULL 인
행이 대부분이고, 나중에 축이 하나 더 늘 때마다 컬럼이 는다.

Revision ID: p6_50_plot_allocation_20260822
Revises: p6_49_program_tab_20260821
Create Date: 2026-08-22
"""
import sqlalchemy as sa
from alembic import op

revision = 'p6_50_plot_allocation_20260822'
down_revision = 'p6_49_program_tab_20260821'
branch_labels = None
depends_on = None

_TABLE = 'geo_plot'


def _columns(bind):
    return {c['name'] for c in sa.inspect(bind).get_columns(_TABLE)}


def upgrade():
    bind = op.get_bind()
    if not sa.inspect(bind).has_table(_TABLE):
        return                      # 새 설치는 create_all 이 모델대로 만든다
    if 'allocation' not in _columns(bind):
        with op.batch_alter_table(_TABLE) as batch:
            batch.add_column(sa.Column('allocation', sa.JSON(), nullable=True))


def downgrade():
    bind = op.get_bind()
    if not sa.inspect(bind).has_table(_TABLE):
        return
    if 'allocation' in _columns(bind):
        with op.batch_alter_table(_TABLE) as batch:
            batch.drop_column('allocation')
