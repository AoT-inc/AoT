# coding=utf-8
"""P6-41: 재배 프로그램에 목표 곡선(Method) 참조를 둔다.

정본: docs/design/program-layer.md

단계별 `targets` 는 계단이다(그 단계 내내 같은 값). 실제 재배는 주차마다 조금씩
옮겨 가는 쪽이 많고, AoT 에는 그것을 표현하는 수단이 이미 있다 — Method(시간축
곡선). 항목마다 Method 를 걸 수 있게 해서 **전 주기에 걸쳐 변하는 목표**를 담는다.

곡선이 있으면 곡선이 이기고, 없는 항목은 단계 값을 쓴다.

Revision ID: p6_41_program_target_methods_20260819
Revises: p6_40_program_20260819
Create Date: 2026-08-19
"""
import sqlalchemy as sa
from alembic import op

revision = 'p6_41_program_target_methods_20260819'
down_revision = 'p6_40_program_20260819'
branch_labels = None
depends_on = None

_TABLE = 'geo_program'


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if not insp.has_table(_TABLE):
        return
    cols = {c['name'] for c in insp.get_columns(_TABLE)}
    if 'targets_methods' not in cols:
        with op.batch_alter_table(_TABLE) as batch:
            batch.add_column(sa.Column('targets_methods', sa.JSON, nullable=True))


def downgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if not insp.has_table(_TABLE):
        return
    cols = {c['name'] for c in insp.get_columns(_TABLE)}
    if 'targets_methods' in cols:
        with op.batch_alter_table(_TABLE) as batch:
            batch.drop_column('targets_methods')
