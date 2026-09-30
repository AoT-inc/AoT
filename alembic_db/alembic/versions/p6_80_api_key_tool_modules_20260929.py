# coding=utf-8
"""P6-78: API 키별 설정 모듈 — `user_api_key.tool_modules`.

도구 묶음(p6_75)을 "운영 / 운영 + 설정 전부" 둘에서 **운영(항상) + 고른 설정
모듈**로 넓힌다. 모듈 이름을 쉼표 목록으로 적는다('plots,map'). NULL 은 모듈
없음이다.

칸만 더한다(nullable, 기본 NULL) — 기존 키는 바꾸지 않는다. 'operations' 키는
모듈 없음 그대로, 'configuration' 키는 이 칸을 보지 않고 언제나 모듈 전부라
(모듈이 늘어도 저절로 포함) 업그레이드 전과 같은 목록을 받는다. 되돌리면
(downgrade) 이 칸이 사라져 모듈을 고른 운영 키는 운영으로 **좁아진다** —
넓어지는 쪽으로는 어긋나지 않는다.

Revision ID: p6_80_api_key_tool_modules_20260929
Revises: p6_79_conditional_refractory_period_20260930
Create Date: 2026-09-29
"""
import sqlalchemy as sa
from alembic import op

revision = 'p6_80_api_key_tool_modules_20260929'
down_revision = 'p6_79_conditional_refractory_period_20260930'
branch_labels = None
depends_on = None

_TABLE = 'user_api_key'
_COLUMN = 'tool_modules'


def _columns(bind):
    return {c['name'] for c in sa.inspect(bind).get_columns(_TABLE)}


def upgrade():
    bind = op.get_bind()
    if not sa.inspect(bind).has_table(_TABLE):
        return                      # 새 설치는 create_all 이 처리한다
    if _COLUMN not in _columns(bind):
        with op.batch_alter_table(_TABLE) as batch:
            batch.add_column(sa.Column(_COLUMN, sa.String(length=128),
                                       nullable=True))


def downgrade():
    bind = op.get_bind()
    if not sa.inspect(bind).has_table(_TABLE):
        return
    if _COLUMN in _columns(bind):
        with op.batch_alter_table(_TABLE) as batch:
            batch.drop_column(_COLUMN)
