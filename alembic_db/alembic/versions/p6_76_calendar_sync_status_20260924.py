# coding=utf-8
"""P6-76: 달력 동기화의 막힘 표시 — 연결의 `last_sync_refused`, 링크의 `sync_state`.

구글 달력 가져오기가 권한·그룹 범위로 일정을 막아도 연결의 상태는 'ok' 로
남아 화면에 아무것도 보이지 않았다. 막힌 일정 수(`user_calendar_connection.
last_sync_refused`)와, 구글 쪽 취소를 못 받아들인 링크 표지(`calendar_event_
link.sync_state`)를 담는다. 둘 다 nullable, 기본 NULL 이라 기존 행은 그대로다.

Revision ID: p6_76_calendar_sync_status_20260924
Revises: p6_75_api_key_tool_profile_20260924
Create Date: 2026-09-24
"""
import sqlalchemy as sa
from alembic import op

revision = 'p6_76_calendar_sync_status_20260924'
down_revision = 'p6_75_api_key_tool_profile_20260924'
branch_labels = None
depends_on = None

_ADDED = (
    ('user_calendar_connection', 'last_sync_refused', sa.Integer()),
    ('calendar_event_link', 'sync_state', sa.String(length=16)),
)


def _columns(bind, table):
    return {c['name'] for c in sa.inspect(bind).get_columns(table)}


def upgrade():
    bind = op.get_bind()
    for table, column, coltype in _ADDED:
        if not sa.inspect(bind).has_table(table):
            continue                # 새 설치는 create_all 이 처리한다
        if column not in _columns(bind, table):
            with op.batch_alter_table(table) as batch:
                batch.add_column(sa.Column(column, coltype, nullable=True))


def downgrade():
    bind = op.get_bind()
    for table, column, _t in _ADDED:
        if not sa.inspect(bind).has_table(table):
            continue
        if column in _columns(bind, table):
            with op.batch_alter_table(table) as batch:
                batch.drop_column(column)
