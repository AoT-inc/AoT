# coding=utf-8
"""P6-64: mcp_confirmation.modified_params_json 신설 — 승인 전 수정 지원.

대시보드 위젯(widget_mcp_review)에서 승인자가 대기 중인 요청의 값을 고쳐서
승인할 수 있게 한다. p6_26 이 세운 원칙("승인 화면에 보인 값 = 실제 실행값")은
그대로 유지한다 — 원본 params_json 을 덮어쓰는 대신, 수정본을 별도 컬럼에
담아서 execute_approved() 가 있으면 그걸, 없으면 원본을 쓰게 한다. params_json
은 감사 근거로 항상 원본 그대로 남는다("무엇이 요청됐고 무엇으로 바뀌었는가"를
나중에 대조할 수 있어야 한다).

Revision ID: p6_64_mcp_confirmation_modified_params_20260909
Revises: p6_63_widget_mobile_full_width_20260908
Create Date: 2026-09-09
"""
import sqlalchemy as sa
from alembic import op

revision = 'p6_64_mcp_confirmation_modified_params_20260909'
down_revision = 'p6_63_widget_mobile_full_width_20260908'
branch_labels = None
depends_on = None

TABLE = 'mcp_confirmation'
COLUMN = 'modified_params_json'


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
            batch_op.add_column(sa.Column(COLUMN, sa.Text(), nullable=True))


def downgrade():
    if _has_column(TABLE, COLUMN):
        with op.batch_alter_table(TABLE, schema=None) as batch_op:
            batch_op.drop_column(COLUMN)
