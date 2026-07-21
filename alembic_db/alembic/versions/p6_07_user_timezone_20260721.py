# coding=utf-8
"""P6-07: 사용자별 시간대 — users.timezone.

통합 시간 관리 재설계 Phase 4b 후속 (docs/design/timezone-management.md §3·§7).

지금까지 "사용자 시간대"는 시스템 전역 Misc.timezone 의 별칭일 뿐이었다
(get_user_tz 가 Misc 를 읽음). 개인 표시(뷰어 시각·개인 알림)를 위한 실제
사용자별 tz 를 도입한다. None 이면 시스템 기본값으로 폴백.

이 컬럼은 개인 '표시' 선호일 뿐, 장치 예약 해석(장치 현지 앵커)이나 시스템
폴백 체인을 바꾸지 않는다.

nullable 이라 기존 계정에 무해. 신규 설치는 db.create_all()이 스키마를 만든다.

Revision ID: p6_07_user_timezone_20260721
Revises: p6_06_scheduler_tz_anchor_20260721
Create Date: 2026-07-21
"""
import sqlalchemy as sa
from alembic import op

revision = 'p6_07_user_timezone_20260721'
down_revision = 'p6_06_scheduler_tz_anchor_20260721'
branch_labels = None
depends_on = None

_TABLE = 'users'


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
    if _has_table(_TABLE) and not _has_column(_TABLE, 'timezone'):
        op.add_column(_TABLE, sa.Column('timezone', sa.String(length=64), nullable=True))


def downgrade():
    if _has_table(_TABLE) and _has_column(_TABLE, 'timezone'):
        with op.batch_alter_table(_TABLE) as batch:
            batch.drop_column('timezone')
