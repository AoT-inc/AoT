# coding=utf-8
"""P6-88: AI 카드 [공지로 게시] 칸 (ai_screen_cards.notice_id).

사용자가 AI 카드를 [공지로 게시] 하면 만든 공지(NoticePost)의 unique_id 를 남긴다 —
이미 게시했는지 표시하고, 같은 카드를 두 번 게시하지 않게(여러 워커 안전한 조건부
UPDATE) 하는 자리다. 칸은 null 허용이라 기존 카드는 그대로다. kind 값에 'artifact'
(정적 HTML 카드)가 더해지지만 칸 모양은 같다(String(16)).

재실행 안전: 칸이 이미 있으면 건너뛴다. downgrade 는 칸을 지운다(SQLite 는 batch).

Revision ID: p6_88_ai_card_notice_20261019
Revises: p6_87_ai_card_files_20261019
Create Date: 2026-10-19
"""
import sqlalchemy as sa
from alembic import op

revision = 'p6_88_ai_card_notice_20261019'
down_revision = 'p6_87_ai_card_files_20261019'
branch_labels = None
depends_on = None

TABLE = 'ai_screen_cards'
COLUMN = 'notice_id'


def _has_table():
    return sa.inspect(op.get_bind()).has_table(TABLE)


def _columns():
    return {c['name'] for c in sa.inspect(op.get_bind()).get_columns(TABLE)}


def upgrade():
    if not _has_table():       # p6_86 이 만든다 — 없으면 할 일이 없다
        return
    if COLUMN not in _columns():
        with op.batch_alter_table(TABLE, schema=None) as batch_op:
            batch_op.add_column(sa.Column(COLUMN, sa.String(length=36), nullable=True))


def downgrade():
    if not _has_table():
        return
    if COLUMN in _columns():
        with op.batch_alter_table(TABLE, schema=None) as batch_op:
            batch_op.drop_column(COLUMN)
