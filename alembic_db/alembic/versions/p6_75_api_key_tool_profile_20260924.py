# coding=utf-8
"""P6-75: API 키별 도구 묶음 — `user_api_key.tool_profile`.

외부 MCP 에 보여 줄 도구의 범위를 키마다 고른다: 'operations'(일상 운영) 또는
'configuration'(운영 + 설정·작성). 키의 scope(무엇을 해도 되는가)와는 다른
축이다 — 이 칸은 무엇을 목록에 싣는가만 정한다.

칸만 더한다(nullable, 기본 NULL). NULL 은 "아직 배정 전" 이고, 기존 키의 값은
여기서 정하지 않는다 — 앱 기동 때 `mcp_auth.backfill_key_tool_profiles` 가
최근 90일 사용 기록을 보고 한 번 채운다. 마이그레이션에 넣지 않는 이유는 그
판정이 도구 분류표(tool_registry)를 읽어야 하기 때문이다. 마이그레이션은 앱
코드가 바뀌어도 같은 결과를 내야 한다.

Revision ID: p6_75_api_key_tool_profile_20260924
Revises: p6_74_mcp_audit_quality_20260923
Create Date: 2026-09-24
"""
import sqlalchemy as sa
from alembic import op

revision = 'p6_75_api_key_tool_profile_20260924'
down_revision = 'p6_74_mcp_audit_quality_20260923'
branch_labels = None
depends_on = None

_TABLE = 'user_api_key'
_COLUMN = 'tool_profile'


def _columns(bind):
    return {c['name'] for c in sa.inspect(bind).get_columns(_TABLE)}


def upgrade():
    bind = op.get_bind()
    if not sa.inspect(bind).has_table(_TABLE):
        return                      # 새 설치는 create_all 이 처리한다
    if _COLUMN not in _columns(bind):
        with op.batch_alter_table(_TABLE) as batch:
            batch.add_column(sa.Column(_COLUMN, sa.String(length=16),
                                       nullable=True))


def downgrade():
    bind = op.get_bind()
    if not sa.inspect(bind).has_table(_TABLE):
        return
    if _COLUMN in _columns(bind):
        with op.batch_alter_table(_TABLE) as batch:
            batch.drop_column(_COLUMN)
