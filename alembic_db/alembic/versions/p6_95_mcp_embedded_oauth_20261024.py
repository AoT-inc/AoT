# coding=utf-8
"""P6-95: MCP 내장 인가 서버 — 표 셋(oauth_client·oauth_code·oauth_grant)과 인증 방식 칸.

`ai_global_settings.mcp_auth_mode`('central' / 'embedded', 비면 central) 를 더하고 내장 인가 서버가 쓰는 표를 만든다
(docs/design/mcp-embedded-oauth.md §6). 기본은 central 이라 기존 설치의 동작은 그대로다. 재실행 안전.

Revision ID: p6_95_mcp_embedded_oauth_20261024
Revises: p6_94_ai_shortcut_20261022
Create Date: 2026-10-24
"""
import sqlalchemy as sa
from alembic import op

revision = 'p6_95_mcp_embedded_oauth_20261024'
down_revision = 'p6_94_ai_shortcut_20261022'
branch_labels = None
depends_on = None

_SETTINGS = 'ai_global_settings'
_MODE = 'mcp_auth_mode'
_TABLES = ('oauth_code', 'oauth_grant', 'oauth_client')


def upgrade():
    insp = sa.inspect(op.get_bind())
    if insp.has_table(_SETTINGS) and _MODE not in {c['name'] for c in insp.get_columns(_SETTINGS)}:
        with op.batch_alter_table(_SETTINGS) as batch:
            batch.add_column(sa.Column(_MODE, sa.String(length=16), nullable=True, server_default='central'))

    if not insp.has_table('oauth_client'):
        op.create_table(
            'oauth_client',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('client_id', sa.String(length=64), nullable=False, unique=True),
            sa.Column('client_name', sa.String(length=100), nullable=False, server_default=''),
            sa.Column('redirect_uris', sa.Text(), nullable=False),
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.Column('last_used_at', sa.DateTime(), nullable=True),
        )
    if not insp.has_table('oauth_code'):
        op.create_table(
            'oauth_code',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('code_hash', sa.String(length=64), nullable=False, unique=True),
            sa.Column('client_id', sa.String(length=64), nullable=False),
            sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
            sa.Column('resource', sa.String(length=512), nullable=False),
            sa.Column('scope', sa.String(length=255), nullable=False),
            sa.Column('code_challenge', sa.String(length=128), nullable=False),
            sa.Column('redirect_uri', sa.String(length=2048), nullable=False),
            sa.Column('expires_at', sa.DateTime(), nullable=False),
            sa.Column('used', sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column('gid', sa.String(length=64), nullable=True),
        )
        op.create_index('ix_oauth_code_client_id', 'oauth_code', ['client_id'])
        op.create_index('ix_oauth_code_user_id', 'oauth_code', ['user_id'])
    if not insp.has_table('oauth_grant'):
        op.create_table(
            'oauth_grant',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('gid', sa.String(length=64), nullable=False, unique=True),
            sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
            sa.Column('client_id', sa.String(length=64), nullable=False),
            sa.Column('client_name', sa.String(length=100), nullable=False, server_default=''),
            sa.Column('resource', sa.String(length=512), nullable=False),
            sa.Column('scope', sa.String(length=255), nullable=False),
            sa.Column('refresh_hash', sa.String(length=64), nullable=False),
            sa.Column('prev_refresh_hash', sa.String(length=64), nullable=True),
            sa.Column('refresh_expires_at', sa.DateTime(), nullable=False),
            sa.Column('status', sa.String(length=16), nullable=False, server_default='active'),
            sa.Column('revoked_reason', sa.String(length=32), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.Column('last_used_at', sa.DateTime(), nullable=True),
        )
        op.create_index('ix_oauth_grant_user_id', 'oauth_grant', ['user_id'])
        op.create_index('ix_oauth_grant_client_id', 'oauth_grant', ['client_id'])
        op.create_index('ix_oauth_grant_refresh_hash', 'oauth_grant', ['refresh_hash'])
        op.create_index('ix_oauth_grant_prev_refresh_hash', 'oauth_grant', ['prev_refresh_hash'])


def downgrade():
    insp = sa.inspect(op.get_bind())
    for table in _TABLES:
        if insp.has_table(table):
            op.drop_table(table)
    if insp.has_table(_SETTINGS) and _MODE in {c['name'] for c in insp.get_columns(_SETTINGS)}:
        with op.batch_alter_table(_SETTINGS) as batch:
            batch.drop_column(_MODE)
