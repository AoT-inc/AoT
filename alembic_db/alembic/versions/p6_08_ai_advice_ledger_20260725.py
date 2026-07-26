# coding=utf-8
"""P6-08: 다자 AI 의견 원장 — ai_advice.

메인 AoT의 AI, 외부에서 MCP로 접속한 AI, AI를 가진 하위 노드가 각각 낸 의견을
한 원장에 모아 사람이 비교·채택·기각할 수 있게 한다.

AISystemSummary(스코프당 최신 1건)로는 여러 주체의 의견이 서로를 덮어쓰므로
상충 의견을 나란히 보관할 수 없어 별도 테이블을 둔다. 실행 승인 큐
(mcp_confirmation)와도 목적이 다르다 — 이쪽은 "의견", 그쪽은 "실행 허가".

추가 전용(새 테이블)이라 기존 데이터에 무해. 신규 설치는 db.create_all()이 만든다.

Revision ID: p6_08_ai_advice_ledger_20260725
Revises: p6_07_user_timezone_20260721
Create Date: 2026-07-25
"""
import sqlalchemy as sa
from alembic import op

revision = 'p6_08_ai_advice_ledger_20260725'
down_revision = 'p6_07_user_timezone_20260721'
branch_labels = None
depends_on = None

_TABLE = 'ai_advice'


def _has_table(table):
    bind = op.get_bind()
    insp = sa.inspect(bind)
    try:
        return table in insp.get_table_names()
    except Exception:
        return False


def upgrade():
    if _has_table(_TABLE):
        return
    op.create_table(
        _TABLE,
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('unique_id', sa.String(length=36), nullable=False, unique=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('agent_id', sa.String(length=100), nullable=False),
        sa.Column('agent_kind', sa.String(length=20), nullable=True),
        sa.Column('scope_type', sa.String(length=20), nullable=True),
        sa.Column('scope_id', sa.String(length=64), nullable=True),
        sa.Column('scope_name', sa.String(length=128), nullable=True),
        sa.Column('title', sa.String(length=200), nullable=False),
        sa.Column('advice', sa.Text(), nullable=False),
        sa.Column('rationale', sa.Text(), nullable=True),
        sa.Column('proposed_action', sa.Text(), nullable=True),
        sa.Column('severity', sa.String(length=20), nullable=True),
        sa.Column('confidence', sa.Float(), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=True),
        sa.Column('reviewed_by', sa.String(length=36), nullable=True),
        sa.Column('reviewed_at', sa.DateTime(), nullable=True),
        sa.Column('review_note', sa.Text(), nullable=True),
    )
    op.create_index('ix_ai_advice_created_at', _TABLE, ['created_at'])
    op.create_index('ix_ai_advice_scope_id', _TABLE, ['scope_id'])
    op.create_index('ix_ai_advice_status', _TABLE, ['status'])


def downgrade():
    if _has_table(_TABLE):
        op.drop_table(_TABLE)
