# coding=utf-8
"""P6-66: 사용자별 스마트폰 화면 배율 — users.ui_zoom_phone.

고령 농업인(경영주 평균 67.7세, 2025 농림어업총조사)을 위해 스마트폰에서 페이지
전체를 키운다. 글자만 키우는 방식은 px 로 박힌 폭·높이·버튼이 따라오지 않아
"같이 커지지 않는 요소가 너무 많다"(사용자, 2026-09-11)는 판단으로 페이지 전체
배율로 바꿨다. 값은 계정 모달 "휴대폰 화면 크기" 에서 90~150%(5 단위)로 고른다.

None 이면 기본값(115%)을 쓴다 — 적용은 templates/_phone_zoom.html.
스마트폰(손가락 화면 + 짧은 변 600px 미만)에만 걸리고 태블릿·컴퓨터는 무관하다.

nullable 이라 기존 계정에 무해. 신규 설치는 db.create_all()이 스키마를 만든다.

Revision ID: p6_66_user_ui_zoom_phone_20260911
Revises: p6_65_mcp_confirmation_title_20260909
Create Date: 2026-09-11
"""
import sqlalchemy as sa
from alembic import op

revision = 'p6_66_user_ui_zoom_phone_20260911'
down_revision = 'p6_65_mcp_confirmation_title_20260909'
branch_labels = None
depends_on = None

_TABLE = 'users'
_COLUMN = 'ui_zoom_phone'


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
