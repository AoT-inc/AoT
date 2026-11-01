# coding=utf-8
"""P6-86: AI 자막·수신함 카드 테이블 (ai_screen_cards) + Misc.hide_ai_messages.

외부 AI 가 screen_action(action='post')으로 남긴 카드를 사용자별로 보관한다.
읽음·닫기·만료 칸을 갖는 전용 테이블이다(Notes 재사용 안 함).

misc.hide_ai_messages — "AI 메시지 숨기기"(settings/general). 켜도 카드는 수신함에
저장되고 자막만 뜨지 않는다. nullable·기본 0 이라 기존 행은 안전하다.

재실행 안전: 테이블·인덱스가 이미 있으면 건너뛴다. downgrade 는 테이블을 지운다.

Revision ID: p6_86_ai_screen_cards_20261019
Revises: p6_85_input_device_status_20261013
Create Date: 2026-10-19
"""
import sqlalchemy as sa
from alembic import op

revision = 'p6_86_ai_screen_cards_20261019'
down_revision = 'p6_85_input_device_status_20261013'
branch_labels = None
depends_on = None

TABLE = 'ai_screen_cards'
IX_USER_CREATED = 'ix_ai_screen_cards_user_created'
IX_EXPIRES = 'ix_ai_screen_cards_expires_at'
MISC = 'misc'
MISC_COLUMN = 'hide_ai_messages'


def _has_table():
    return sa.inspect(op.get_bind()).has_table(TABLE)


def _indexes():
    return {i['name'] for i in sa.inspect(op.get_bind()).get_indexes(TABLE)}


def _misc_columns():
    insp = sa.inspect(op.get_bind())
    if not insp.has_table(MISC):
        return None
    return {c['name'] for c in insp.get_columns(MISC)}


def upgrade():
    if not _has_table():
        op.create_table(
            TABLE,
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('unique_id', sa.String(length=36), nullable=False),
            sa.Column('user_id', sa.Integer(), nullable=False),
            sa.Column('created_at', sa.DateTime(), nullable=True),
            sa.Column('expires_at', sa.DateTime(), nullable=False),
            sa.Column('kind', sa.String(length=16), nullable=True),
            sa.Column('title', sa.String(length=80), nullable=True),
            sa.Column('body', sa.Text(), nullable=True),
            sa.Column('source_label', sa.String(length=64), nullable=True),
            sa.Column('source_key_id', sa.String(length=36), nullable=True),
            sa.Column('read_at', sa.DateTime(), nullable=True),
            sa.Column('dismissed_at', sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(['user_id'], ['users.id']),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('id'),
            sa.UniqueConstraint('unique_id'),
        )
    have = _indexes()
    if IX_USER_CREATED not in have:
        op.create_index(IX_USER_CREATED, TABLE, ['user_id', 'created_at'])
    if IX_EXPIRES not in have:
        op.create_index(IX_EXPIRES, TABLE, ['expires_at'])
    have_misc = _misc_columns()
    if have_misc is not None and MISC_COLUMN not in have_misc:
        with op.batch_alter_table(MISC, schema=None) as batch_op:
            batch_op.add_column(sa.Column(
                MISC_COLUMN, sa.Boolean(), nullable=True, server_default=sa.false()))


def downgrade():
    if _has_table():
        op.drop_table(TABLE)
    have_misc = _misc_columns()
    if have_misc is not None and MISC_COLUMN in have_misc:
        with op.batch_alter_table(MISC, schema=None) as batch_op:
            batch_op.drop_column(MISC_COLUMN)
