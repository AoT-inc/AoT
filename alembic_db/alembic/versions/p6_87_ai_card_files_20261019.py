# coding=utf-8
"""P6-87: AI 카드 첨부 파일·고정·노트 저장 칸 (ai_screen_cards).

screen_action(action='post')가 이미지·파일을 함께 남길 수 있게 한다(P1).
추가 칸은 모두 null 허용이라 기존 카드는 그대로 text 카드다.

  file_path  첨부 파일의 PATH_AI_CARD_FILES 아래 상대경로('YYYY/MM/uuid.ext')
  file_name  사용자에게 보이는 원본 이름(≤120자)
  file_mime  서버가 확장자로 정한 MIME
  file_size  바이트
  pinned_at  고정한 시각(고정 카드는 만료·300건 정리에서 빠진다)
  note_id    [노트로 저장] 한 노트의 unique_id

인덱스 ix_ai_screen_cards_user_pinned(user_id, pinned_at). 재실행 안전: 칸·인덱스가
이미 있으면 건너뛴다. downgrade 는 인덱스와 칸을 지운다(SQLite 는 batch).

Revision ID: p6_87_ai_card_files_20261019
Revises: p6_86_ai_screen_cards_20261019
Create Date: 2026-10-19
"""
import sqlalchemy as sa
from alembic import op

revision = 'p6_87_ai_card_files_20261019'
down_revision = 'p6_86_ai_screen_cards_20261019'
branch_labels = None
depends_on = None

TABLE = 'ai_screen_cards'
IX_USER_PINNED = 'ix_ai_screen_cards_user_pinned'
COLUMNS = (
    ('file_path', lambda: sa.Column('file_path', sa.String(length=255), nullable=True)),
    ('file_name', lambda: sa.Column('file_name', sa.String(length=120), nullable=True)),
    ('file_mime', lambda: sa.Column('file_mime', sa.String(length=64), nullable=True)),
    ('file_size', lambda: sa.Column('file_size', sa.Integer(), nullable=True)),
    ('pinned_at', lambda: sa.Column('pinned_at', sa.DateTime(), nullable=True)),
    ('note_id', lambda: sa.Column('note_id', sa.String(length=36), nullable=True)),
)


def _has_table():
    return sa.inspect(op.get_bind()).has_table(TABLE)


def _columns():
    return {c['name'] for c in sa.inspect(op.get_bind()).get_columns(TABLE)}


def _indexes():
    return {i['name'] for i in sa.inspect(op.get_bind()).get_indexes(TABLE)}


def upgrade():
    if not _has_table():       # p6_86 이 만든다 — 없으면 할 일이 없다
        return
    have = _columns()
    missing = [make for name, make in COLUMNS if name not in have]
    if missing:
        with op.batch_alter_table(TABLE, schema=None) as batch_op:
            for make in missing:
                batch_op.add_column(make())
    if IX_USER_PINNED not in _indexes():
        op.create_index(IX_USER_PINNED, TABLE, ['user_id', 'pinned_at'])


def downgrade():
    if not _has_table():
        return
    if IX_USER_PINNED in _indexes():
        op.drop_index(IX_USER_PINNED, table_name=TABLE)
    have = _columns()
    present = [name for name, _make in COLUMNS if name in have]
    if present:
        with op.batch_alter_table(TABLE, schema=None) as batch_op:
            for name in present:
                batch_op.drop_column(name)
