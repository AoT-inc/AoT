# coding=utf-8
"""P6-79: Conditional 불응기(refractory_period) 컬럼 추가.

Conditional 함수의 `Run Python Code` 는 period 마다 반복 실행되므로, 조건이
계속 참인 동안(예: 센서 무응답, 온도 초과) 사용자 코드가 매 주기 self.run_action()
/ self.run_all_actions() 를 호출하면 알림이 그만큼 반복 발송된다. 지금까지는
사용자 코드에서 `hasattr(self, ...)` 로 직접 래치를 구현하는 것이 유일한
우회책이었다(docs/Functions.md 예시 7).

이 컬럼은 forms_conditional.py 에 오래전부터 있었지만 저장 경로도 컬럼도 없어
죽어있던 필드를 실제로 살리는 것이다: 0(기본값, 비활성화)보다 크면, 마지막
액션 발동 이후 이 시간(초) 동안 같은 Conditional 의 재발동을 억제한다.
시행은 aot/controllers/base_conditional.py 의 AbstractConditional 에서
run_action()/run_all_actions() 호출 시점에 이루어진다(액션 디스패치 계층).

기존 행에는 기본값 0 이 채워지며, 값을 설정하지 않은 Conditional 의 동작은
바뀌지 않는다.

Revision ID: p6_79_conditional_refractory_period_20260930
Revises: p6_78_smtp_password_encrypt_20260930
Create Date: 2026-09-30
"""
import sqlalchemy as sa
from alembic import op

revision = 'p6_79_conditional_refractory_period_20260930'
down_revision = 'p6_78_smtp_password_encrypt_20260930'
branch_labels = None
depends_on = None

_TABLE = 'conditional'
_COLUMN = 'refractory_period'


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
    op.add_column(_TABLE, sa.Column(
        _COLUMN, sa.Float(), nullable=True, server_default=sa.text('0')))


def downgrade():
    if not _has_table(_TABLE):
        return
    if not _has_column(_TABLE, _COLUMN):
        return
    with op.batch_alter_table(_TABLE) as batch:
        batch.drop_column(_COLUMN)
