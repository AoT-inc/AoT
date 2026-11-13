# coding=utf-8
"""P7-10: 사용자별 경량 모드 — users.ui_lite_mode.

자원 조절 R6. 느린 기기·회선에서 화면을 가볍게 쓰는 사람이 고르는 설정이다(계정 모달
"경량 모드"). 브라우저가 알려 주는 기기 신호(`deviceMemory`·`saveData`)는 iOS Safari 에
없어서, 자동 감지만으로는 아이폰·아이패드에서 아무것도 줄일 수 없다 — 사람이 바로잡는
수단이 필요하다.

값: NULL·'off' = 끔(기본) · 'phone' = 폰·태블릿(손가락 화면)에서만 · 'always' = 항상.
켜지면 화면 폴링 ×2, 지도·시설 3D 의 움직임 효과 끔, 카메라 실시간 영상 대신 스냅숏.
적용은 templates/_lite_mode.html → `<html data-aot-lite>`.

nullable 이라 기존 계정에 무해(= 끔). 신규 설치는 db.create_all()이 스키마를 만든다.

Revision ID: p7_10_user_ui_lite_mode_20261109
Revises: p7_09_ai_card_viz_spec_20261106
Create Date: 2026-11-09
"""
import sqlalchemy as sa
from alembic import op

revision = 'p7_10_user_ui_lite_mode_20261109'
down_revision = 'p7_09_ai_card_viz_spec_20261106'
branch_labels = None
depends_on = None

_TABLE = 'users'
_COLUMN = 'ui_lite_mode'


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
    if _has_table(_TABLE) and not _has_column(_TABLE, _COLUMN):
        op.add_column(_TABLE, sa.Column(_COLUMN, sa.String(length=8), nullable=True))


def downgrade():
    if _has_table(_TABLE) and _has_column(_TABLE, _COLUMN):
        with op.batch_alter_table(_TABLE) as batch:
            batch.drop_column(_COLUMN)
