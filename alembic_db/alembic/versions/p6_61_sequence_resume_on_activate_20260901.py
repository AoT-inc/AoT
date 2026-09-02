# coding=utf-8
"""P6-61: 시퀀스를 다시 켤 때 이어서 갈지 처음부터 갈지 — `Trigger.resume_on_activate`.

## 왜 필요한가

시퀀스를 껐다가 다시 켜면 지금은 **언제나 이어서** 간다. 비활성화해도 그 사이클의
런타임 상태(`FunctionRuntimeState`)가 남아 있고, 재활성화 때
`_load_runtime_state()` 가 그것을 복원하기 때문이다. 그 동작은 데몬 재시작을
위해 만들어진 것인데(재시작이 관수를 끊지 않게), 사용자가 **의도적으로 끈** 경우와
구분되지 않았다.

두 요구가 실제로 다르다. 잠깐 멈췄다 재개하는 것이면 이어서가 맞고, 설정을 고치고
다시 돌리는 것이면 처음부터가 맞다. 지금은 후자를 하려면 주기가 지나기를 기다리는
수밖에 없다(`_load_runtime_state` 는 주기보다 오래된 상태만 버린다).

## 기본값이 True 인 이유

`True` = 이어서, 즉 **업그레이드 전과 똑같이 동작한다.** 물리 장비를 다루는
설정에서 기본값이 동작을 바꾸면, 업그레이드한 농장이 아무것도 만지지 않았는데
관수가 달라진다.

## 데몬 재시작에는 영향이 없다

이 옵션은 **비활성화될 때 저장된 상태를 지울지**만 정한다(`run_finally`). 데몬
재시작은 `is_activated` 를 건드리지 않으므로 그 경로를 지나지 않고, 진행 중이던
사이클은 옵션과 무관하게 언제나 이어서 복원된다.

Revision ID: p6_61_sequence_resume_on_activate_20260901
Revises: p6_60_env_coordinator_trend_state_20260828
Create Date: 2026-09-01
"""
import sqlalchemy as sa
from alembic import op

revision = 'p6_61_sequence_resume_on_activate_20260901'
down_revision = 'p6_60_env_coordinator_trend_state_20260828'
branch_labels = None
depends_on = None


def _has_column(table, column):
    bind = op.get_bind()
    rows = bind.execute(sa.text(f"PRAGMA table_info({table})")).fetchall()
    return any(r[1] == column for r in rows)


def upgrade():
    if _has_column('trigger', 'resume_on_activate'):
        return
    op.add_column(
        'trigger',
        sa.Column('resume_on_activate', sa.Boolean(), nullable=True,
                  server_default=sa.true()))
    # 기존 행은 지금까지의 동작(이어서)을 그대로 유지한다.
    op.get_bind().execute(sa.text(
        "UPDATE trigger SET resume_on_activate = 1 "
        "WHERE resume_on_activate IS NULL"))


def downgrade():
    if _has_column('trigger', 'resume_on_activate'):
        op.drop_column('trigger', 'resume_on_activate')
