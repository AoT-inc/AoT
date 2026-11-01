# coding=utf-8
"""P6-93: misc.ai_card_auto — AI 결과 카드 자동(기본 켬).

켜면 외부 AI(MCP)의 initialize 지침에 "사용자가 간직하거나 행동할 핵심 결과를 끝내면 카드로도 올려라"
규칙이 붙는다(aot/tools/tool_execution.py). 기존 행도 켬(서버 기본 1)이다. 재실행 안전.

Revision ID: p6_93_ai_card_auto_20261022
Revises: p6_92_twin_options_20261022
Create Date: 2026-10-22
"""
import sqlalchemy as sa
from alembic import op

revision = 'p6_93_ai_card_auto_20261022'
down_revision = 'p6_92_twin_options_20261022'
branch_labels = None
depends_on = None

MISC = 'misc'
COLUMN = 'ai_card_auto'


def _columns():
    insp = sa.inspect(op.get_bind())
    if not insp.has_table(MISC):
        return None
    return {c['name'] for c in insp.get_columns(MISC)}


def upgrade():
    cols = _columns()
    if cols is None or COLUMN in cols:
        return
    with op.batch_alter_table(MISC) as batch:
        batch.add_column(sa.Column(COLUMN, sa.Boolean(), nullable=True, server_default=sa.true()))


def downgrade():
    cols = _columns()
    if cols is None or COLUMN not in cols:
        return
    with op.batch_alter_table(MISC) as batch:
        batch.drop_column(COLUMN)
