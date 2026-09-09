# coding=utf-8
"""P6-65: mcp_confirmation.title 신설 — 승인 화면에서 tool_name 노출 제거.

일반 사용자에게 시스템 내부 언어(tool_name 원문, 예: operate_device)를 보여주면
안 된다는 지적을 받았다. 승인 대기 카드의 헤드라인을 tool_name 대신 사람이 읽는
제목으로 바꾼다 — MCP 로 접속한 LLM이 `_title` 메타 인자로 직접 보낼 수 있고,
안 보내면 mcp_safety_gate.synthesize_title() 이 도구별 동작 설명 표 + 장치 이름
조회로 대신 짓는다(항상 값이 있어야 하는 건 아니라 nullable — 마이그레이션
이전 행이나 폴백 실패 시엔 조회 시점(list_pending)에 다시 합성한다).

Revision ID: p6_65_mcp_confirmation_title_20260909
Revises: p6_64_mcp_confirmation_modified_params_20260909
Create Date: 2026-09-09
"""
import sqlalchemy as sa
from alembic import op

revision = 'p6_65_mcp_confirmation_title_20260909'
down_revision = 'p6_64_mcp_confirmation_modified_params_20260909'
branch_labels = None
depends_on = None

TABLE = 'mcp_confirmation'
COLUMN = 'title'


def _has_column(table, column):
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if table not in insp.get_table_names():
        return True  # 테이블이 없으면 할 일도 없다
    return column in [c['name'] for c in insp.get_columns(table)]


def upgrade():
    # 재실행 안전: 이미 있으면 건너뛴다.
    if not _has_column(TABLE, COLUMN):
        with op.batch_alter_table(TABLE, schema=None) as batch_op:
            batch_op.add_column(sa.Column(COLUMN, sa.String(200), nullable=True))


def downgrade():
    if _has_column(TABLE, COLUMN):
        with op.batch_alter_table(TABLE, schema=None) as batch_op:
            batch_op.drop_column(COLUMN)
