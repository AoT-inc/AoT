# coding=utf-8
"""P6-67: 사용자별 컴퓨터 화면 배율 — users.ui_zoom_desktop.

P6-66(스마트폰 배율)의 짝. 사용자가 "데스크탑에서 문자 크기가 작아서 매번 확대해서
읽어야 한다"(2026-09-11)고 해서, 컴퓨터(마우스 화면)에서도 계정 모달 "컴퓨터 화면
크기" 로 페이지 전체 배율을 90~150%(5 단위)로 고르게 한다.

None 이면 기본값(100% — 아무것도 바꾸지 않는다)을 쓴다. 적용은
templates/_screen_zoom.html(CSS zoom + --aot-zoom). 같은 날 태블릿은 모바일(ui_zoom_phone)
쪽으로 넣었다(사용자).

nullable 이라 기존 계정에 무해. 신규 설치는 db.create_all()이 스키마를 만든다.

Revision ID: p6_67_user_ui_zoom_desktop_20260911
Revises: p6_66_user_ui_zoom_phone_20260911
Create Date: 2026-09-11
"""
import sqlalchemy as sa
from alembic import op

revision = 'p6_67_user_ui_zoom_desktop_20260911'
down_revision = 'p6_66_user_ui_zoom_phone_20260911'
branch_labels = None
depends_on = None

_TABLE = 'users'
_COLUMN = 'ui_zoom_desktop'


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
        op.add_column(_TABLE, sa.Column(_COLUMN, sa.Integer(), nullable=True))


def downgrade():
    if _has_table(_TABLE) and _has_column(_TABLE, _COLUMN):
        with op.batch_alter_table(_TABLE) as batch:
            batch.drop_column(_COLUMN)
