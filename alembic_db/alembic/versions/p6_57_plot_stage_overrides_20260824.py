# coding=utf-8
"""P6-57: 구획만의 단계 구성 (P8).

정본: docs/design/program-layer.md §P8

- `geo_plot.stage_overrides` — 이 구획에서 뺀 단계 · 더한 단계 · 단계별 지침.

프로그램의 단계 목록은 표준이고, 현장에서는 한 단계를 건너뛰거나 더 넣는 일이
흔하다. 목록을 통째로 복사하지 않고 **차이만** 담는다 — 복사하면 프로그램을
고쳐도 구획이 따라오지 않고 버전 고정이 의미를 잃는다.

Revision ID: p6_57_plot_stage_overrides_20260824
Revises: p6_56_plot_stage_plan_20260824
Create Date: 2026-08-24
"""
import sqlalchemy as sa
from alembic import op

revision = 'p6_57_plot_stage_overrides_20260824'
down_revision = 'p6_56_plot_stage_plan_20260824'
branch_labels = None
depends_on = None


def upgrade():
    insp = sa.inspect(op.get_bind())
    if not insp.has_table('geo_plot'):
        return
    if 'stage_overrides' in {c['name'] for c in insp.get_columns('geo_plot')}:
        return
    with op.batch_alter_table('geo_plot') as batch:
        batch.add_column(sa.Column('stage_overrides', sa.JSON(), nullable=True))


def downgrade():
    insp = sa.inspect(op.get_bind())
    if not insp.has_table('geo_plot'):
        return
    if 'stage_overrides' not in {c['name'] for c in insp.get_columns('geo_plot')}:
        return
    with op.batch_alter_table('geo_plot') as batch:
        batch.drop_column('stage_overrides')
