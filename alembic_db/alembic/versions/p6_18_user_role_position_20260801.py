# coding=utf-8
"""P6-18: Settings > Users 카드 순서 — users/roles 에 position_y 추가.

사용자 설정 페이지가 Input/Output 과 같은 카드+드로어 구조로 바뀌면서 카드
드래그로 순서를 바꿀 수 있게 됐는데, 그 순서를 담을 자리가 없었다. Input 이
쓰는 것과 같은 이름/의미의 컬럼을 추가한다 — 0 부터 시작하는 정수 랭크이고,
저장 시 서버가 0..N-1 로 다시 매겨 동률을 없앤다.

기존 행은 전부 0 으로 시작한다. 전부 동률이면 ORDER BY position_y 만으로는
순서가 불안정하므로, 조회 쪽에서 id 를 2차 정렬키로 함께 쓴다(= 마이그레이션
직후에는 지금까지와 같은 생성 순서 그대로 보인다).

Revision ID: p6_18_user_role_position_20260801
Revises: p6_17_method_solar_anchor_20260731
Create Date: 2026-08-01
"""
import sqlalchemy as sa
from alembic import op

revision = 'p6_18_user_role_position_20260801'
down_revision = 'p6_17_method_solar_anchor_20260731'
branch_labels = None
depends_on = None

_TABLES = ('users', 'roles')
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
    for table in _TABLES:
        if not _has_table(table) or _has_column(table, _COLUMN):
            continue
        op.add_column(table, sa.Column(
            _COLUMN, sa.Integer(), nullable=True, server_default=sa.text('0')))


def downgrade():
    for table in _TABLES:
        if not _has_table(table) or not _has_column(table, _COLUMN):
            continue
        with op.batch_alter_table(table) as batch:
            batch.drop_column(_COLUMN)
