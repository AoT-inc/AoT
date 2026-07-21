# coding=utf-8
"""P6-01: Google Calendar 양방향 동기화 — per-user OAuth 연결 + 이벤트 매핑.

추가:
  - user_calendar_connection 테이블 (per-user OAuth 링크 + 동기화 상태; 토큰 암호화)
  - calendar_event_link 테이블 (SchedulerJobMeta ↔ Google event 매핑, 연결별)
  - misc.google_oauth_client_id / google_oauth_client_secret / oauth_public_base_url 컬럼

신규 설치는 db.create_all()이 스키마를 만들므로(위 rebaseline docstring 참고) 이
upgrade()는 기존 설치를 위한 것. 로컬/운영 기존 설치에서 실제로 실행된다.

Revision ID: p6_01_google_calendar_20260720
Revises: p6_00_rebaseline_20260720
Create Date: 2026-07-20
"""
import sqlalchemy as sa
from alembic import op

revision = 'p6_01_google_calendar_20260720'
down_revision = 'p6_00_rebaseline_20260720'
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


def _has_table(table):
    bind = op.get_bind()
    insp = sa.inspect(bind)
    return table in insp.get_table_names()


def upgrade():
    if not _has_table('user_calendar_connection'):
        op.create_table(
            'user_calendar_connection',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('unique_id', sa.String(length=36), nullable=False),
            sa.Column('user_id', sa.Integer(), nullable=False),
            sa.Column('provider', sa.String(length=32), nullable=False),
            sa.Column('account_email', sa.String(length=255), nullable=True),
            sa.Column('refresh_token_enc', sa.Text(), nullable=True),
            sa.Column('access_token_enc', sa.Text(), nullable=True),
            sa.Column('token_expiry', sa.DateTime(), nullable=True),
            sa.Column('scope', sa.Text(), nullable=True),
            sa.Column('google_calendar_id', sa.String(length=255), nullable=True),
            sa.Column('sync_token', sa.Text(), nullable=True),
            sa.Column('push_enabled', sa.Boolean(), nullable=True),
            sa.Column('pull_enabled', sa.Boolean(), nullable=True),
            sa.Column('sync_interval_min', sa.Integer(), nullable=True),
            sa.Column('is_active', sa.Boolean(), nullable=True),
            sa.Column('last_synced_at', sa.DateTime(), nullable=True),
            sa.Column('last_sync_status', sa.String(length=16), nullable=True),
            sa.Column('last_sync_error', sa.Text(), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=True),
            sa.Column('updated_at', sa.DateTime(), nullable=True),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('unique_id'),
        )
        op.create_index('ix_user_calendar_connection_user_id',
                        'user_calendar_connection', ['user_id'])

    if not _has_table('calendar_event_link'):
        op.create_table(
            'calendar_event_link',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('unique_id', sa.String(length=36), nullable=False),
            sa.Column('connection_id', sa.Integer(), nullable=False),
            sa.Column('job_id', sa.Integer(), nullable=False),
            sa.Column('google_event_id', sa.String(length=255), nullable=False),
            sa.Column('google_etag', sa.String(length=255), nullable=True),
            sa.Column('origin', sa.String(length=8), nullable=False),
            sa.Column('last_synced_at', sa.DateTime(), nullable=True),
            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('unique_id'),
        )
        op.create_index('ix_calendar_event_link_connection_id',
                        'calendar_event_link', ['connection_id'])
        op.create_index('ix_calendar_event_link_job_id',
                        'calendar_event_link', ['job_id'])
        op.create_index('ix_calendar_event_link_google_event_id',
                        'calendar_event_link', ['google_event_id'])

    for col in ('google_oauth_client_id', 'google_oauth_client_secret'):
        if not _has_column('misc', col):
            op.add_column('misc', sa.Column(col, sa.Text(), nullable=True))
    if not _has_column('misc', 'oauth_public_base_url'):
        op.add_column('misc', sa.Column('oauth_public_base_url', sa.String(length=255), nullable=True))


def downgrade():
    for idx, tbl in (
        ('ix_calendar_event_link_google_event_id', 'calendar_event_link'),
        ('ix_calendar_event_link_job_id', 'calendar_event_link'),
        ('ix_calendar_event_link_connection_id', 'calendar_event_link'),
    ):
        try:
            op.drop_index(idx, table_name=tbl)
        except Exception:
            pass
    if _has_table('calendar_event_link'):
        op.drop_table('calendar_event_link')

    try:
        op.drop_index('ix_user_calendar_connection_user_id', table_name='user_calendar_connection')
    except Exception:
        pass
    if _has_table('user_calendar_connection'):
        op.drop_table('user_calendar_connection')

    for col in ('oauth_public_base_url', 'google_oauth_client_secret', 'google_oauth_client_id'):
        if _has_column('misc', col):
            op.drop_column('misc', col)
