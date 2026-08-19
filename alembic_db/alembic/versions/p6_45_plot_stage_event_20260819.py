# coding=utf-8
"""P6-45: 단계 전환 원장 `geo_plot_stage_event` (P5).

정본: docs/design/program-layer.md §P5

## 왜

현재 단계는 파생값이라(시작일 + 프로그램) 승인이 그 파생을 바꾸지 않으면
"확인했음" 체크박스일 뿐이다. 승인은 **기준점을 옮긴다** — 확인된 전환 날짜부터
남은 단계를 다시 계산한다.

**대기 중 전환은 이 표에 넣지 않는다.** 그것은 파생값이고(기준점 이후 계산이
기준점보다 앞서면 곧 제안), 행으로 만들면 프로그램 수정·GDD 변화에 조용히 낡는다.

되돌리기는 행을 지우지 않고 `undone_at` 을 적는다 — 지우면 "누가 언제 확인했다가
물렀다" 가 사라진다.

Revision ID: p6_45_plot_stage_event_20260819
Revises: p6_44_geo_plot_20260819
Create Date: 2026-08-19
"""
import sqlalchemy as sa
from alembic import op

revision = 'p6_45_plot_stage_event_20260819'
down_revision = 'p6_44_geo_plot_20260819'
branch_labels = None
depends_on = None

_TABLE = 'geo_plot_stage_event'


def upgrade():
    insp = sa.inspect(op.get_bind())
    if insp.has_table(_TABLE):
        return
    op.create_table(
        _TABLE,
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('unique_id', sa.String(36), nullable=False, unique=True),
        sa.Column('plot_uuid', sa.String(36), nullable=False),
        sa.Column('stage_key', sa.String(64), nullable=False),
        sa.Column('stage_index', sa.Integer(), nullable=False),
        sa.Column('started_on', sa.Date(), nullable=False),
        sa.Column('source', sa.String(16), nullable=False,
                  server_default='manual'),
        sa.Column('decided_at', sa.DateTime(), nullable=True),
        sa.Column('decided_by', sa.String(64), nullable=True),
        sa.Column('undone_at', sa.DateTime(), nullable=True),
        sa.Column('undone_by', sa.String(64), nullable=True),
        sa.Column('note', sa.Text(), nullable=True),
    )
    # 기준점 조회는 항상 "이 구획의 안 무른 행 중 가장 늦은 것" 이다.
    op.create_index('ix_geo_plot_stage_event_plot_uuid', _TABLE, ['plot_uuid'])


def downgrade():
    insp = sa.inspect(op.get_bind())
    if not insp.has_table(_TABLE):
        return
    if 'ix_geo_plot_stage_event_plot_uuid' in {
            i['name'] for i in insp.get_indexes(_TABLE)}:
        op.drop_index('ix_geo_plot_stage_event_plot_uuid', table_name=_TABLE)
    op.drop_table(_TABLE)
