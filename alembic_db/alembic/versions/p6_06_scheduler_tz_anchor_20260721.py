# coding=utf-8
"""P6-06: 스케줄 tz 앵커 — anchor_tz / anchor_source.

통합 시간 관리 재설계 Phase 4 (docs/design/timezone-management.md §6).

예약의 벽시계("06:00")가 어느 시계로 작성됐는지(anchor_tz)와 그 출처
(anchor_source: device/shape/user/system)를 저장한다. 같은 UTC 순간을 장치현지·
사용자·뷰어 tz 어느 쪽으로도 의도를 잃지 않고 재표시하고, 반복 규칙은 anchor_tz
에서 재평가(DST)하기 위함. 확정 정책: 장치 예약은 장치 현지 tz 기준.

nullable 컬럼이라 기존 행에 무해. 신규 설치는 db.create_all()이 스키마를 만든다.

Revision ID: p6_06_scheduler_tz_anchor_20260721
Revises: p6_05_tz_inheritance_20260721
Create Date: 2026-07-21
"""
import sqlalchemy as sa
from alembic import op

revision = 'p6_06_scheduler_tz_anchor_20260721'
down_revision = 'p6_05_tz_inheritance_20260721'
branch_labels = None
depends_on = None

_TABLE = 'scheduler_jobs_meta'


def _has_column(table, column):
    bind = op.get_bind()
    insp = sa.inspect(bind)
    try:
        cols = [c['name'] for c in insp.get_columns(table)]
    except Exception:
        return False
    return column in cols


def _has_table(table):
    bind = op.get_bind()
    insp = sa.inspect(bind)
    try:
        return table in insp.get_table_names()
    except Exception:
        return False


def upgrade():
    if _has_table(_TABLE):
        if not _has_column(_TABLE, 'anchor_tz'):
            op.add_column(_TABLE, sa.Column('anchor_tz', sa.String(length=64), nullable=True))
        if not _has_column(_TABLE, 'anchor_source'):
            op.add_column(_TABLE, sa.Column('anchor_source', sa.String(length=16), nullable=True))


def downgrade():
    if _has_table(_TABLE):
        with op.batch_alter_table(_TABLE) as batch:
            for col in ('anchor_source', 'anchor_tz'):
                if _has_column(_TABLE, col):
                    batch.drop_column(col)
