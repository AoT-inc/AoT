# coding=utf-8
"""P6-46: 단계 자동 승인 (P7).

정본: docs/design/program-layer.md §P7

- `geo_program.auto_advance` — 이 프로그램을 쓰는 구획의 단계 전환을 사람이
  확인하지 않고 기록한다.
- `geo_plot_stage_event.auto` — 그 줄이 자동으로 남았는지. `decided_by` 가 비었다는
  것만으로는 "로그인 정보가 없는 사람" 과 구분되지 않는다.

**기본은 꺼짐이다.** 이미 만들어진 프로그램의 동작이 업그레이드로 조용히 바뀌면,
사람이 아무 결정도 하지 않았는데 단계가 스스로 넘어가기 시작한다.

Revision ID: p6_46_program_auto_advance_20260819
Revises: p6_45_plot_stage_event_20260819
Create Date: 2026-08-19
"""
import sqlalchemy as sa
from alembic import op

revision = 'p6_46_program_auto_advance_20260819'
down_revision = 'p6_45_plot_stage_event_20260819'
branch_labels = None
depends_on = None


def upgrade():
    insp = sa.inspect(op.get_bind())
    if insp.has_table('geo_program'):
        cols = {c['name'] for c in insp.get_columns('geo_program')}
        if 'auto_advance' not in cols:
            with op.batch_alter_table('geo_program') as batch:
                batch.add_column(sa.Column('auto_advance', sa.Boolean(),
                                           nullable=False,
                                           server_default=sa.false()))
    if insp.has_table('geo_plot_stage_event'):
        cols = {c['name'] for c in insp.get_columns('geo_plot_stage_event')}
        if 'auto' not in cols:
            with op.batch_alter_table('geo_plot_stage_event') as batch:
                batch.add_column(sa.Column('auto', sa.Boolean(),
                                           nullable=False,
                                           server_default=sa.false()))


def downgrade():
    insp = sa.inspect(op.get_bind())
    if insp.has_table('geo_plot_stage_event'):
        if 'auto' in {c['name'] for c in
                      insp.get_columns('geo_plot_stage_event')}:
            with op.batch_alter_table('geo_plot_stage_event') as batch:
                batch.drop_column('auto')
    if insp.has_table('geo_program'):
        if 'auto_advance' in {c['name'] for c in
                              insp.get_columns('geo_program')}:
            with op.batch_alter_table('geo_program') as batch:
                batch.drop_column('auto_advance')
