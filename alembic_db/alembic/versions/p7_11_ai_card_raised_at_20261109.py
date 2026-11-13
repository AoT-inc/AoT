# coding=utf-8
"""P7-11: AI 카드 끌어올리기 칸 (ai_screen_cards.raised_at).

수신함은 최신순이다. 예전 카드를 사람이 [맨 위로] 누르거나, AI 가 이미 만든 카드를 다시
띄우면(screen card + card=<id>) 그 시각을 남겨 목록 맨 위로 올린다. 정렬 기준은
`raised_at` 이 있으면 그것, 없으면 `created_at` 이다(aot/utils/ai_screen_cards.py `sort_key`).

null 허용이라 기존 카드는 그대로(= 만든 시각 순). 신규 설치는 db.create_all()이 스키마를 만든다.
재실행 안전: 칸이 이미 있으면 건너뛴다. downgrade 는 칸을 지운다(SQLite 는 batch).

Revision ID: p7_11_ai_card_raised_at_20261109
Revises: p7_10_user_ui_lite_mode_20261109
Create Date: 2026-11-09
"""
import sqlalchemy as sa
from alembic import op

revision = 'p7_11_ai_card_raised_at_20261109'
down_revision = 'p7_10_user_ui_lite_mode_20261109'
branch_labels = None
depends_on = None

TABLE = 'ai_screen_cards'
COLUMN = 'raised_at'


def _has_table():
    return sa.inspect(op.get_bind()).has_table(TABLE)


def _columns():
    return {c['name'] for c in sa.inspect(op.get_bind()).get_columns(TABLE)}


def upgrade():
    if not _has_table():       # p6_86 이 만든다 — 없으면 할 일이 없다
        return
    if COLUMN not in _columns():
        with op.batch_alter_table(TABLE, schema=None) as batch_op:
            batch_op.add_column(sa.Column(COLUMN, sa.DateTime(), nullable=True))


def downgrade():
    if not _has_table():
        return
    if COLUMN in _columns():
        with op.batch_alter_table(TABLE, schema=None) as batch_op:
            batch_op.drop_column(COLUMN)
