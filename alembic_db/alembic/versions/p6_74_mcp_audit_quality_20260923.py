# coding=utf-8
"""P6-74: MCP 호출 품질 칸 — `mcp_audit_log` 에 nullable 칸 9개.

감사 행 하나에 "얼마나 걸렸나 · 얼마나 컸나 · 잘렸나 · 어느 전송으로 왔나 ·
같은 대화의 호출인가" 를 함께 적어, 평소 호출 품질을 따로 저장소 없이 쌓는다
(설계: `docs/design/ai-tool-architecture.md` "호출 품질 칸").

- 전부 nullable 이다. 옛 행은 NULL 로 남고, 지표는 NULL 행을 빼고 계산한다.
- 백필·인덱스는 없다. 지표는 기존 `ix_mcp_audit_log_timestamp` 범위 조회로 읽는다.
- 채우기는 `AOT_MCP_QUALITY_LEDGER=0` 으로 끌 수 있다(칸은 남는다).

Revision ID: p6_74_mcp_audit_quality_20260923
Revises: p6_73_role_use_ai_chat_20260922
Create Date: 2026-09-23
"""
import sqlalchemy as sa
from alembic import op

revision = 'p6_74_mcp_audit_quality_20260923'
down_revision = 'p6_73_role_use_ai_chat_20260922'
branch_labels = None
depends_on = None

_TABLE = 'mcp_audit_log'

#: (이름, 타입) — 모델 `MCPAuditLog` 와 같은 순서·타입이어야 한다.
_COLUMNS = (
    ('duration_ms', sa.Integer()),
    ('session_key', sa.String(32)),
    ('transport', sa.String(16)),
    ('via_drawer', sa.Boolean()),
    ('response_tokens', sa.Integer()),
    ('response_bytes', sa.Integer()),
    ('truncated', sa.Boolean()),
    ('call_state', sa.String(24)),
    ('result_items', sa.Integer()),
)


def _columns(bind):
    return {c['name'] for c in sa.inspect(bind).get_columns(_TABLE)}


def upgrade():
    bind = op.get_bind()
    if not sa.inspect(bind).has_table(_TABLE):
        return                      # 새 설치는 create_all 이 모델에서 만든다

    have = _columns(bind)
    missing = [(n, t) for n, t in _COLUMNS if n not in have]
    if not missing:
        return
    with op.batch_alter_table(_TABLE) as batch:
        for name, type_ in missing:
            batch.add_column(sa.Column(name, type_, nullable=True))


def downgrade():
    bind = op.get_bind()
    if not sa.inspect(bind).has_table(_TABLE):
        return
    have = _columns(bind)
    present = [n for n, _t in _COLUMNS if n in have]
    if not present:
        return
    with op.batch_alter_table(_TABLE) as batch:
        for name in present:
            batch.drop_column(name)
