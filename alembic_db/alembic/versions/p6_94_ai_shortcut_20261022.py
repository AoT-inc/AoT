# coding=utf-8
"""P6-94: misc.ai_shortcut_url — AI 바로가기 주소(기본 Claude 새 대화).

휴대폰 AI 창구(수신함 머리줄)의 바로가기 단추가 여는 https 주소. 비우면 단추가 없다. 기존 행도 기본값이
채워진다(서버 기본값). 재실행 안전.

Revision ID: p6_94_ai_shortcut_20261022
Revises: p6_93_ai_card_auto_20261022
Create Date: 2026-10-22
"""
import sqlalchemy as sa
from alembic import op

revision = 'p6_94_ai_shortcut_20261022'
down_revision = 'p6_93_ai_card_auto_20261022'
branch_labels = None
depends_on = None

MISC = 'misc'
COLUMN = 'ai_shortcut_url'
DEFAULT = 'https://claude.ai/new'


def _columns():
    insp = sa.inspect(op.get_bind())
    if not insp.has_table(MISC):
        return None
    return {c['name'] for c in insp.get_columns(MISC)}


def upgrade():
    cols = _columns()
    if cols is None or COLUMN in cols:
        return
    with op.batch_alter_table(MISC) as batch:
        batch.add_column(sa.Column(COLUMN, sa.String(length=512), nullable=True,
                                   server_default=DEFAULT))


def downgrade():
    cols = _columns()
    if cols is None or COLUMN not in cols:
        return
    with op.batch_alter_table(MISC) as batch:
        batch.drop_column(COLUMN)
