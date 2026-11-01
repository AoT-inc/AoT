# coding=utf-8
"""P7-00: 대상 별칭 표 (MCP 점검 2026-10-28 세션 E).

  target_alias : 사용자가 대상을 부르는 다른 이름 — 서버(농장) 단위, 어느 AI 든 공유

대상 해석(`aot/tools/domain/targets.py`)이 이름보다 먼저 이 표를 본다.
재실행 안전(이미 있으면 건너뜀). downgrade 는 표를 지운다(별칭만 사라지고 대상은 그대로다).

Revision ID: p7_00_target_alias_20261028
Revises: p6_99_twin_scenario_20261027
Create Date: 2026-10-28
"""
import sqlalchemy as sa
from alembic import op

revision = 'p7_00_target_alias_20261028'
down_revision = 'p6_99_twin_scenario_20261027'
branch_labels = None
depends_on = None


def upgrade():
    if 'target_alias' in set(sa.inspect(op.get_bind()).get_table_names()):
        return
    op.create_table(
        'target_alias',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('alias', sa.String(80), nullable=False),
        sa.Column('alias_key', sa.String(80), nullable=False),
        sa.Column('target_kind', sa.String(16), nullable=False),
        sa.Column('target_id', sa.String(80), nullable=False),
        sa.Column('created_by', sa.String(64), nullable=True),
        sa.Column('created_at', sa.Float(), nullable=False))
    op.create_index('ix_target_alias_key', 'target_alias', ['alias_key'])
    op.create_index('ix_target_alias_target', 'target_alias', ['target_kind', 'target_id'])


def downgrade():
    if 'target_alias' in set(sa.inspect(op.get_bind()).get_table_names()):
        op.drop_table('target_alias')
