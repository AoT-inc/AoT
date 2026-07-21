# coding=utf-8
"""P6-02: 카테고리별 구글 캘린더 라우팅 (AI / 사용자 / 장치).

추가:
  - user_calendar_connection.category_calendars (JSON) — 카테고리→{calendar_id, sync_token}
  - calendar_event_link.google_calendar_id — 이벤트가 어느 캘린더에 있는지(멀티캘린더 update/delete용)

Revision ID: p6_02_calendar_categories_20260721
Revises: p6_01_google_calendar_20260720
Create Date: 2026-07-21
"""
import sqlalchemy as sa
from alembic import op

revision = 'p6_02_calendar_categories_20260721'
down_revision = 'p6_01_google_calendar_20260720'
branch_labels = None
depends_on = None


def _has_column(table, column):
    bind = op.get_bind()
    insp = sa.inspect(bind)
    try:
        cols = [c['name'] for c in insp.get_columns(table)]
    except Exception:
        return False
    return column in cols


def upgrade():
    if not _has_column('user_calendar_connection', 'category_calendars'):
        op.add_column('user_calendar_connection',
                      sa.Column('category_calendars', sa.JSON(), nullable=True))
    if not _has_column('calendar_event_link', 'google_calendar_id'):
        op.add_column('calendar_event_link',
                      sa.Column('google_calendar_id', sa.String(length=255), nullable=True))


def downgrade():
    if _has_column('calendar_event_link', 'google_calendar_id'):
        op.drop_column('calendar_event_link', 'google_calendar_id')
    if _has_column('user_calendar_connection', 'category_calendars'):
        op.drop_column('user_calendar_connection', 'category_calendars')
