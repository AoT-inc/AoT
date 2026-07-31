# coding=utf-8
"""P6-17: 설정점 곡선의 태양 앵커 — method_data 에 time_*_event/offset 추가.

하루 단위 메서드(Daily)는 "06:00~18:00" 처럼 벽시계로 저장된다. 고정 시각의
문제는 계절이다 — 한여름엔 일출 뒤 한참 지나 시작하고 한겨울엔 캄캄할 때
시작한다. 작물이 겪는 하루는 시계가 아니라 해에 묶여 있으므로, 구간의 양 끝을
태양 이벤트(일출·일몰·남중·시민박명)에 걸 수 있게 한다.

NULL = 기존 동작(저장된 벽시계 그대로). 기존 행은 전부 NULL 로 남는다.

Revision ID: p6_17_method_solar_anchor_20260731
Revises: p6_16_conditional_sun_condition_20260731
Create Date: 2026-07-31
"""
import sqlalchemy as sa
from alembic import op

revision = 'p6_17_method_solar_anchor_20260731'
down_revision = 'p6_16_conditional_sun_condition_20260731'
branch_labels = None
depends_on = None

_TABLE = 'method_data'
_COLUMNS = (
    ('time_start_event', sa.String(length=32), None),
    ('time_start_offset_min', sa.Integer(), '0'),
    ('time_end_event', sa.String(length=32), None),
    ('time_end_offset_min', sa.Integer(), '0'),
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
        kwargs = {'nullable': True}
        if default is not None:
            kwargs['server_default'] = sa.text(default)
        op.add_column(_TABLE, sa.Column(name, type_, **kwargs))


def downgrade():
    if not _has_table(_TABLE):
        return
    with op.batch_alter_table(_TABLE) as batch:
        for name, _type, _default in _COLUMNS:
            if _has_column(_TABLE, name):
                batch.drop_column(name)
