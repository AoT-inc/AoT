# coding=utf-8
"""P6-04: 사용자 Google 로그인 가입 — 승인대기 컬럼.

추가:
  - users.auth_provider 컬럼 (계정이 어떻게 생성되었는지, 'google' 또는 NULL)
  - users.is_approved 컬럼 (Google 로그인으로 자가가입한 계정이 관리자 승인
    전까지 로그인하지 못하도록 게이팅. 기존/관리자생성 계정은 기본값 True라
    영향 없음)

신규 설치는 db.create_all()이 스키마를 만들므로 이 upgrade()는 기존 설치용.

Revision ID: p6_04_user_google_signup_20260721
Revises: p6_03_google_drive_source_20260721
Create Date: 2026-07-21
"""
import sqlalchemy as sa
from alembic import op

revision = 'p6_04_user_google_signup_20260721'
down_revision = 'p6_03_google_drive_source_20260721'
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
    if not _has_column('users', 'auth_provider'):
        op.add_column('users', sa.Column('auth_provider', sa.String(length=32), nullable=True))
    if not _has_column('users', 'is_approved'):
        op.add_column('users', sa.Column(
            'is_approved', sa.Boolean(), nullable=False, server_default=sa.true()))


def downgrade():
    if _has_column('users', 'is_approved'):
        op.drop_column('users', 'is_approved')
    if _has_column('users', 'auth_provider'):
        op.drop_column('users', 'auth_provider')
