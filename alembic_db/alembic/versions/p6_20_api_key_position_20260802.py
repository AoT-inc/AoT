# coding=utf-8
"""P6-20: settings/api_key 카드 순서 — api_key 에 position_y 추가.

API 키 관리 페이지도 사용자 페이지와 같은 카드+드로어 구조로 바뀌면서 카드를
끌어 순서를 바꿀 수 있게 됐고, 그 순서를 담을 자리가 필요하다. users/roles 의
position_y(p6_18)와 같은 의미다 — 0부터 시작하는 정수 랭크이고, 저장 시 서버가
0..N-1 로 다시 매겨 동률을 없앤다.

기존 행은 전부 0 이라 조회 쪽에서 id 를 2차 정렬키로 함께 쓴다(= 마이그레이션
직후에는 지금까지와 같은 순서 그대로 보인다).

Revision ID: p6_20_api_key_position_20260802
Revises: p6_19_user_fullname_active_20260801
Create Date: 2026-08-02
"""
import sqlalchemy as sa
from alembic import op

revision = 'p6_20_api_key_position_20260802'
down_revision = 'p6_19_user_fullname_active_20260801'
branch_labels = None
depends_on = None

_TABLE = 'api_key'
_COLUMN = 'position_y'


def _has_table(table):
    bind = op.get_bind()
    insp = sa.inspect(bind)
    try:
        return table in insp.get_table_names()
    except Exception:
        return False


def _has_column(table, column):
    bind = op.get_bind()
    insp = sa.inspect(bind)
    try:
        cols = [c['name'] for c in insp.get_columns(table)]
    except Exception:
        return False
    return column in cols


def upgrade():
    if not _has_table(_TABLE) or _has_column(_TABLE, _COLUMN):
        return
    op.add_column(_TABLE, sa.Column(
        _COLUMN, sa.Integer(), nullable=True, server_default=sa.text('0')))


def downgrade():
    if not _has_table(_TABLE) or not _has_column(_TABLE, _COLUMN):
        return
    with op.batch_alter_table(_TABLE) as batch:
        batch.drop_column(_COLUMN)
