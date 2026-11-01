# coding=utf-8
"""P6-99: 트윈 시나리오 정의·분석 실행 색인 표 (예보·트윈 데이터 관리 D7).

  twin_scenario : 시나리오 한 건의 정의·계보 (곡선은 Influx env_twin_scn*)
  twin_run      : 발행 한 건(대상 + t0)의 색인·계보

설계: plans/2026-10-25_twin_data_management_design.md §6.2·§6.6. 재실행 안전(이미 있으면 건너뜀).
downgrade 는 두 표를 지운다(곡선·머리말은 Influx 에 남고, 색인은 머리말에서 다시 만들 수 있다).

Revision ID: p6_99_twin_scenario_20261027
Revises: p6_98_fc_calibration_20261026
Create Date: 2026-10-27
"""
import sqlalchemy as sa
from alembic import op

revision = 'p6_99_twin_scenario_20261027'
down_revision = 'p6_98_fc_calibration_20261026'
branch_labels = None
depends_on = None


def _tables():
    return set(sa.inspect(op.get_bind()).get_table_names())


def upgrade():
    have = _tables()
    if 'twin_scenario' not in have:
        op.create_table(
            'twin_scenario',
            sa.Column('id', sa.String(8), primary_key=True),
            sa.Column('target_kind', sa.String(8), nullable=False),
            sa.Column('target_id', sa.String(80), nullable=False),
            sa.Column('label', sa.String(120), nullable=True),
            sa.Column('created_at', sa.Float(), nullable=False),
            sa.Column('requested_at', sa.Float(), nullable=True),
            sa.Column('finished_at', sa.Float(), nullable=True),
            sa.Column('status', sa.String(16), nullable=False, server_default='queued'),
            sa.Column('pinned', sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column('expires_at', sa.Float(), nullable=True),
            sa.Column('base_run', sa.String(120), nullable=True),
            sa.Column('base_mode', sa.String(8), nullable=False, server_default='hold'),
            sa.Column('future_input_mode', sa.String(8), nullable=False, server_default='hold'),
            sa.Column('overrides', sa.Text(), nullable=True),
            sa.Column('effects', sa.Text(), nullable=True),
            sa.Column('model_rev', sa.Integer(), nullable=True),
            sa.Column('cal_rev', sa.Integer(), nullable=True),
            sa.Column('fc_issue_epoch', sa.Float(), nullable=True),
            sa.Column('weather_src', sa.Integer(), nullable=True),
            sa.Column('obs_origin', sa.Integer(), nullable=True),
            sa.Column('fail_reason', sa.String(200), nullable=True),
            sa.Column('schema_version', sa.Integer(), nullable=False, server_default='1'))
        op.create_index('ix_twin_scenario_target', 'twin_scenario', ['target_kind', 'target_id'])
        op.create_index('ix_twin_scenario_created_at', 'twin_scenario', ['created_at'])
    if 'twin_run' not in have:
        op.create_table(
            'twin_run',
            sa.Column('run_id', sa.String(120), primary_key=True),
            sa.Column('target_kind', sa.String(8), nullable=False),
            sa.Column('target_id', sa.String(80), nullable=False),
            sa.Column('t0', sa.Float(), nullable=False),
            sa.Column('status', sa.Integer(), nullable=True),
            sa.Column('model_rev', sa.Integer(), nullable=True),
            sa.Column('cal_rev', sa.Integer(), nullable=True),
            sa.Column('fc_issue_epoch', sa.Float(), nullable=True),
            sa.Column('weather_src', sa.Integer(), nullable=True),
            sa.Column('obs_origin', sa.Integer(), nullable=True),
            sa.Column('policy', sa.Integer(), nullable=True),
            sa.Column('plan_src', sa.Integer(), nullable=True),
            sa.Column('fit', sa.Text(), nullable=True))
        op.create_index('ix_twin_run_target_t0', 'twin_run', ['target_kind', 'target_id', 't0'])
        op.create_index('ix_twin_run_t0', 'twin_run', ['t0'])


def downgrade():
    have = _tables()
    for name in ('twin_run', 'twin_scenario'):
        if name in have:
            op.drop_table(name)
