# coding=utf-8
"""P6-56: 구획이 일정을 고친다 (P8).

정본: docs/design/program-layer.md §P8

- `geo_plot.auto_advance` — 자동 승인을 **프로그램에서 구획으로 옮긴다.**
  자동 승인이 묻는 것은 "이 작물의 단계 모델이 정확한가" 가 아니라 "이 자리를
  사람 눈 없이 믿을 수 있는가" 이고, 그것은 구획의 성질이다.
- `geo_plot.stage_plan` — 사람이 정한 단계 경계(연기·앞당김). 프로그램의 단계
  길이는 표준이고 현실은 표준대로 가지 않는다.
- `geo_program.auto_advance` 제거 — 양쪽에 두면 "왜 넘어갔나" 의 답이 두 곳이 된다.

**값을 옮긴다.** 켜져 있던 프로그램을 쓰는 구획에 그 값을 복사한 뒤에 지운다 —
사람이 켜 둔 결정을 업그레이드가 조용히 끄면, 그 사람은 자동 승인이 멈춘 것을
한참 뒤에야 안다.

Revision ID: p6_56_plot_stage_plan_20260824
Revises: p6_55_input_max_age_20260824
Create Date: 2026-08-24
"""
import sqlalchemy as sa
from alembic import op

revision = 'p6_56_plot_stage_plan_20260824'
down_revision = 'p6_55_input_max_age_20260824'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if not insp.has_table('geo_plot'):
        return

    cols = {c['name'] for c in insp.get_columns('geo_plot')}
    with op.batch_alter_table('geo_plot') as batch:
        if 'auto_advance' not in cols:
            batch.add_column(sa.Column('auto_advance', sa.Boolean(),
                                       nullable=False,
                                       server_default=sa.false()))
        if 'stage_plan' not in cols:
            batch.add_column(sa.Column('stage_plan', sa.JSON(), nullable=True))

    if not insp.has_table('geo_program'):
        return
    if 'auto_advance' not in {c['name'] for c in
                              insp.get_columns('geo_program')}:
        return

    # 이관 — 켜 둔 프로그램을 쓰는 구획으로 값을 옮긴다.
    bind.execute(sa.text(
        "UPDATE geo_plot SET auto_advance = 1 "
        "WHERE program_uuid IN (SELECT unique_id FROM geo_program "
        "                       WHERE auto_advance = 1)"))

    with op.batch_alter_table('geo_program') as batch:
        batch.drop_column('auto_advance')


def downgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)

    if insp.has_table('geo_program'):
        if 'auto_advance' not in {c['name'] for c in
                                  insp.get_columns('geo_program')}:
            with op.batch_alter_table('geo_program') as batch:
                batch.add_column(sa.Column('auto_advance', sa.Boolean(),
                                           nullable=False,
                                           server_default=sa.false()))
        # 되돌릴 때는 **구획 중 하나라도 켜져 있으면** 프로그램을 켠다. 축이
        # 다르므로 무손실 역변환은 없다 — 켜 둔 사람의 의도를 잃는 쪽보다
        # 넓게 켜지는 쪽을 고른다(내려간 뒤 화면에서 끌 수 있다).
        if insp.has_table('geo_plot'):
            bind.execute(sa.text(
                "UPDATE geo_program SET auto_advance = 1 "
                "WHERE unique_id IN (SELECT program_uuid FROM geo_plot "
                "                    WHERE auto_advance = 1 "
                "                      AND program_uuid IS NOT NULL)"))

    if insp.has_table('geo_plot'):
        cols = {c['name'] for c in insp.get_columns('geo_plot')}
        with op.batch_alter_table('geo_plot') as batch:
            if 'stage_plan' in cols:
                batch.drop_column('stage_plan')
            if 'auto_advance' in cols:
                batch.drop_column('auto_advance')
