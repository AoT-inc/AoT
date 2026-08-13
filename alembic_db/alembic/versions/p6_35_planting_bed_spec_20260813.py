# coding=utf-8
"""P6-35: 식생 구획에 두둑 규격 — geo_planting.bed_width_cm / path_width_cm.

"몇 줄 심을 수 있나" 를 세는 계산이 밭 전체에 줄을 균일하게 깐다고 보고
있었다. 실제 노지 채소는 두둑 위에 심고 고랑에는 아무것도 안 심는다 —
실측(폭 28.4m, 줄 간격 40cm)에서 균일 71줄 vs 두둑 120+고랑 40 배치 54줄로
24% 차이가 났다.

규격을 조회 파라미터로만 받으면 사람이 대화마다 다시 말해야 하고, 말하지
않은 대화에서는 조용히 틀린 숫자가 나온다. **두둑 규격은 밭의 성질이지
질문의 성질이 아니다** — 작물·기간과 달리 갈아엎기 전까지 그대로이므로
구획에 저장한다. 근거는 docs/design/geo-vegetation-planting.md.

NULL 은 "평평하다" 가 아니라 **"모른다"** 이다. 그래서 기본값을 넣지 않는다 —
0 이나 임의의 표준값으로 채우면 모르는 것과 확인한 것이 구분되지 않고, 조회가
확인되지 않은 규격으로 계산한 숫자를 확신하며 내밀게 된다. `path_width_cm` 은
0 이 유효한 값이라(두둑을 붙여 만드는 배치) NULL 과 반드시 구분되어야 한다.

Revision ID: p6_35_planting_bed_spec_20260813
Revises: p6_34_geo_planting_20260813
Create Date: 2026-08-13
"""
import sqlalchemy as sa
from alembic import op

revision = 'p6_35_planting_bed_spec_20260813'
down_revision = 'p6_34_geo_planting_20260813'
branch_labels = None
depends_on = None

_TABLE = 'geo_planting'
_COLUMNS = ('bed_width_cm', 'path_width_cm')


def _existing():
    insp = sa.inspect(op.get_bind())
    if _TABLE not in insp.get_table_names():
        return None
    return {c['name'] for c in insp.get_columns(_TABLE)}


def upgrade():
    have = _existing()
    if have is None:
        # 테이블 자체가 없는 설치 — p6_34 가 만들 것이므로 여기서는 할 일이 없다.
        return
    # 재실행 안전: 이미 있으면 더하지 않는다.
    for col in _COLUMNS:
        if col not in have:
            op.add_column(_TABLE, sa.Column(col, sa.Integer(), nullable=True))


def downgrade():
    have = _existing()
    if have is None:
        return
    for col in _COLUMNS:
        if col in have:
            op.drop_column(_TABLE, col)
