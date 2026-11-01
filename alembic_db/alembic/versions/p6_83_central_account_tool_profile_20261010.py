# coding=utf-8
"""P6-83: 인가 서버(OAuth)로 연결된 계정에도 도구 묶음을 저장한다.

claude.ai 같은 원격 커넥터는 API 키를 넣을 칸이 없어 OAuth(중앙 인증)로 들어온다.
그런데 그 연결에는 키 행이 없어 도구 묶음이 토큰 범위로 고정됐다(aot.config 가
있으면 'configuration'). 그래서 키에서 '가벼움' 을 골라도 claude.ai 에는 닿지
않았다(2026-10-10). 연결 행에 묶음을 두고, 비어 있으면 예전과 같게 동작한다.

Revision ID: p6_83_central_account_tool_profile_20261010
Revises: p6_82_kma_pressure_kpa_20261009
Create Date: 2026-10-10
"""
import sqlalchemy as sa
from alembic import op

revision = 'p6_83_central_account_tool_profile_20261010'
down_revision = 'p6_82_kma_pressure_kpa_20261009'
branch_labels = None
depends_on = None

_TABLE = 'mcp_external_account'
_COLUMN = 'tool_profile'


def _columns():
    insp = sa.inspect(op.get_bind())
    try:
        if _TABLE not in insp.get_table_names():
            return None
        return {c['name'] for c in insp.get_columns(_TABLE)}
    except Exception:
        return None


def upgrade():
    cols = _columns()
    if cols is None or _COLUMN in cols:
        return
    with op.batch_alter_table(_TABLE) as batch:
        batch.add_column(sa.Column(_COLUMN, sa.String(length=255), nullable=True))


def downgrade():
    cols = _columns()
    if cols is None or _COLUMN not in cols:
        return
    with op.batch_alter_table(_TABLE) as batch:
        batch.drop_column(_COLUMN)
