# coding=utf-8
"""P6-77: 외부 MCP 의 중앙 인증 — 설정 칸 다섯 + 계정 연결 표.

`ai_global_settings` 에 인가 서버 주소·이 서버의 MCP 공개 주소·계정 연결 클라이언트를 더하고
(주소를 코드에 박지 않는다 — 설치처마다 네트워크·도메인이 다르다), 중앙 계정 ↔ 사용자 표
`mcp_external_account` 를 만든다. 기본은 꺼짐이라 기존 설치의 동작(API 키만)은 그대로다.

Revision ID: p6_77_mcp_central_auth_20260928
Revises: p6_76_calendar_sync_status_20260924
Create Date: 2026-09-28
"""
import sqlalchemy as sa
from alembic import op

revision = 'p6_77_mcp_central_auth_20260928'
down_revision = 'p6_76_calendar_sync_status_20260924'
branch_labels = None
depends_on = None

_SETTINGS = 'ai_global_settings'
_COLUMNS = (
    ('mcp_central_enabled', sa.Boolean()),
    ('mcp_central_issuer', sa.String(length=255)),
    ('mcp_public_url', sa.String(length=255)),
    ('mcp_link_client_id', sa.String(length=255)),
    ('mcp_link_client_secret', sa.Text()),
)
_LINKS = 'mcp_external_account'


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if insp.has_table(_SETTINGS):
        have = {c['name'] for c in insp.get_columns(_SETTINGS)}
        missing = [(name, kind) for name, kind in _COLUMNS if name not in have]
        if missing:
            with op.batch_alter_table(_SETTINGS) as batch:
                for name, kind in missing:
                    batch.add_column(sa.Column(name, kind, nullable=True))
    if not insp.has_table(_LINKS):
        op.create_table(
            _LINKS,
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('issuer', sa.String(length=255), nullable=False),
            sa.Column('subject', sa.String(length=255), nullable=False),
            sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
            sa.Column('label', sa.String(length=255), nullable=True),
            sa.Column('linked_at', sa.DateTime(), nullable=False),
            sa.UniqueConstraint('issuer', 'subject', name='uq_mcp_external_account_subject'),
            sa.UniqueConstraint('user_id', 'issuer', name='uq_mcp_external_account_user'),
        )
        op.create_index('ix_mcp_external_account_user_id', _LINKS, ['user_id'])


def downgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if insp.has_table(_LINKS):
        op.drop_table(_LINKS)
    if insp.has_table(_SETTINGS):
        have = {c['name'] for c in insp.get_columns(_SETTINGS)}
        present = [name for name, _kind in _COLUMNS if name in have]
        if present:
            with op.batch_alter_table(_SETTINGS) as batch:
                for name in present:
                    batch.drop_column(name)
