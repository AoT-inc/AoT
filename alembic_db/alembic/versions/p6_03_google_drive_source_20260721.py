# coding=utf-8
"""P6-03: Google Drive 지식 라이브러리 소스 — Picker API 키 컬럼.

추가:
  - misc.google_picker_api_key 컬럼 (Google Picker JS SDK의 developerKey.
    google_oauth_client_id/secret과는 별개 — Picker는 OAuth Client Secret이
    아니라 Cloud Console에서 발급하는 별도 API 키가 필요함)

AIContextSource.source_type='google_drive'는 기존 String(30) 컬럼에 새 문자열
값만 추가되는 것이라 스키마 변경 불필요 (document/web_url/rest_api/
internal_query와 동일하게 config_json에 설정 저장).

신규 설치는 db.create_all()이 스키마를 만들므로 이 upgrade()는 기존 설치용.

Revision ID: p6_03_google_drive_source_20260721
Revises: p6_02_calendar_categories_20260721
Create Date: 2026-07-21
"""
import sqlalchemy as sa
from alembic import op

revision = 'p6_03_google_drive_source_20260721'
down_revision = 'p6_02_calendar_categories_20260721'
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
    if not _has_column('misc', 'google_picker_api_key'):
        op.add_column('misc', sa.Column('google_picker_api_key', sa.Text(), nullable=True))


def downgrade():
    if _has_column('misc', 'google_picker_api_key'):
        op.drop_column('misc', 'google_picker_api_key')
