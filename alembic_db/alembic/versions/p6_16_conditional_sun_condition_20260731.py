# coding=utf-8
"""P6-16: Conditional 태양 조건 — conditional_data 에 sun_* 컬럼 추가.

일출/일몰이 트리거 한 종류의 전용 계산에서 시스템 공용 커널(aot.utils.solar)로
올라가면서, Conditional 도 "지금 주간인가" / "다음 태양 이벤트까지 몇 초인가"를
조건으로 물을 수 있게 한다(조건 타입 sun_state · sun_event_countdown).

위치는 새 컬럼으로 받지 않는다 — 부모 Conditional 이 지도에서 갖는 위치를
상속한다(docs/design/timezone-management.md §13.3). 따라서 추가되는 값은
이벤트 종류와 오프셋뿐이다.

기존 행에는 기본값(sunset / 0 / 0)이 채워지며, 태양 조건이 아닌 행에서는
사용되지 않는다.

Revision ID: p6_16_conditional_sun_condition_20260731
Revises: p6_15_mcp_http_enabled_20260728
Create Date: 2026-07-31
"""
import sqlalchemy as sa
from alembic import op

revision = 'p6_16_conditional_sun_condition_20260731'
down_revision = 'p6_15_mcp_http_enabled_20260728'
branch_labels = None
depends_on = None

_TABLE = 'conditional_data'
_COLUMNS = (
    ('sun_event', sa.String(length=32), 'sunset'),
    ('sun_offset_start_minutes', sa.Integer(), '0'),
    ('sun_offset_end_minutes', sa.Integer(), '0'),
)


def _has_table(table):
    bind = op.get_bind()
    insp = sa.inspect(bind)
    try:
        return table in insp.get_table_names()
    except Exception:
        return False


def _has_column(table, column):
    bind = op.get_bind()
    insp = sa.inspect(bind)
    try:
        cols = [c['name'] for c in insp.get_columns(table)]
    except Exception:
        return False
    return column in cols


def upgrade():
    if not _has_table(_TABLE):
        return
    for name, type_, default in _COLUMNS:
        if _has_column(_TABLE, name):
            continue
        op.add_column(_TABLE, sa.Column(
            name, type_, nullable=True, server_default=sa.text(
                f"'{default}'" if isinstance(type_, sa.String) else default)))


def downgrade():
    if not _has_table(_TABLE):
        return
    with op.batch_alter_table(_TABLE) as batch:
        for name, _type, _default in _COLUMNS:
            if _has_column(_TABLE, name):
                batch.drop_column(name)
