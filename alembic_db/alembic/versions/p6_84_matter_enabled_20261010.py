# coding=utf-8
"""P6-84: Matter 를 쓸지 — 설정 > 일반의 선택 기능 토글.

Matter 컨트롤러(docs/design/matter-controller.md)는 실험 기능이고, 쓰려면 Linux
호스트와 사이드카 컨테이너가 따로 있어야 한다. 그래서 기본은 꺼짐이고, 켠
설치에만 설정 사이드바에 Matter 가 나타나고 Matter 페이지·API 가 열린다.

이미 Matter 장치(device_matter_node)가 있는 설치는 켠 채로 올린다 — 꺼진 채로
올리면 있던 장치를 관리할 화면이 사라진다.

Revision ID: p6_84_matter_enabled_20261010
Revises: p6_83_central_account_tool_profile_20261010
Create Date: 2026-10-10
"""
import sqlalchemy as sa
from alembic import op

revision = 'p6_84_matter_enabled_20261010'
down_revision = 'p6_83_central_account_tool_profile_20261010'
branch_labels = None
depends_on = None

TABLE = 'misc'
COLUMN = 'matter_enabled'


def _has_column(table, column):
    bind = op.get_bind()
    return column in [c['name'] for c in sa.inspect(bind).get_columns(table)]


def _has_table(table):
    return table in sa.inspect(op.get_bind()).get_table_names()


def upgrade():
    # 재실행 안전: 이미 있으면 건너뛴다.
    if _has_column(TABLE, COLUMN):
        return
    with op.batch_alter_table(TABLE, schema=None) as batch_op:
        batch_op.add_column(sa.Column(
            COLUMN, sa.Boolean(), nullable=True, server_default=sa.text("0")))

    if _has_table('custom_controller'):
        in_use = op.get_bind().execute(sa.text(
            "SELECT COUNT(*) FROM custom_controller WHERE device = 'device_matter_node'"
        )).scalar()
        if in_use:
            op.get_bind().execute(sa.text(f"UPDATE {TABLE} SET {COLUMN} = 1"))


def downgrade():
    if not _has_column(TABLE, COLUMN):
        return
    with op.batch_alter_table(TABLE, schema=None) as batch_op:
        batch_op.drop_column(COLUMN)
