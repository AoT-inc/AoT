# coding=utf-8
"""P6-15: 외부 MCP HTTP 서버 활성화 토글 — ai_global_settings.mcp_http_enabled.

aot_mcp_server.py --http 모드(도커 aot_mcp 서비스, 네이티브 aotmcp.service)는
지금까지 켜져 있으면 무조건 요청에 응답했다. 주소/바인딩(host:port)은
docker-compose.yml의 ports: 매핑 또는 systemd 유닛의 ExecStart 인자로 정해져,
실행 중인 프로세스가 스스로 바꿀 수 없어 이 리비전은 그 부분은 건드리지
않는다. 대신 "이 서버가 요청에 응답할지 여부"만 DB 값으로 옮겨, Settings >
General > AI 서비스에서 토글하면 컨테이너/서비스 재시작 없이 매 요청마다
즉시 반영되게 한다.

기존 설치는 이 토글이 없던 상태(=사실상 항상 켜짐)였으므로 기본값은 True로
두어 업그레이드로 인해 기존에 쓰던 외부 MCP 연동이 조용히 끊기지 않게 한다.

Revision ID: p6_15_mcp_http_enabled_20260728
Revises: p6_14_device_membership_20260728
Create Date: 2026-07-28
"""
import sqlalchemy as sa
from alembic import op

revision = 'p6_15_mcp_http_enabled_20260728'
down_revision = 'p6_14_device_membership_20260728'
branch_labels = None
depends_on = None

_TABLE = 'ai_global_settings'
_COLUMN = 'mcp_http_enabled'


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
    if not _has_table(_TABLE):
        return
    if _has_column(_TABLE, _COLUMN):
        return
    op.add_column(_TABLE, sa.Column(_COLUMN, sa.Boolean(), nullable=True,
                                     server_default=sa.true()))


def downgrade():
    if not _has_table(_TABLE) or not _has_column(_TABLE, _COLUMN):
        return
    with op.batch_alter_table(_TABLE) as batch:
        batch.drop_column(_COLUMN)
