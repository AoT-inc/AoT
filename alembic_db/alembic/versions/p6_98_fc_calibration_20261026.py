# coding=utf-8
"""P6-98: 예보 현장 보정 — 계수 판·대지 상태·알림 표 (예보·트윈 데이터 관리 D4).

  fc_calibration_site : 대지당 한 줄 — 보정 방식(auto/on/off)·쓰는 판·마지막 점검
  fc_calibration      : 판(rev)마다 (종류, 변수, 리드대) 한 줄 — 계수 JSON·상태·성적 요약
  fc_cal_event        : 채택·되돌림 알림 기록

설계: plans/2026-10-25_twin_data_management_design.md §4.3. 재실행 안전(이미 있으면 건너뜀).
downgrade 는 세 표를 지운다(계수는 L0 예보와 관측으로 다시 만들 수 있다).

Revision ID: p6_98_fc_calibration_20261026
Revises: p6_97_data_layers_20261025
Create Date: 2026-10-26
"""
import sqlalchemy as sa
from alembic import op

revision = 'p6_98_fc_calibration_20261026'
down_revision = 'p6_97_data_layers_20261025'
branch_labels = None
depends_on = None


def _tables():
    return set(sa.inspect(op.get_bind()).get_table_names())


def upgrade():
    have = _tables()
    if 'fc_calibration_site' not in have:
        op.create_table(
            'fc_calibration_site',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('site_id', sa.String(80), nullable=False),
            sa.Column('mode', sa.String(8), nullable=False, server_default='auto'),
            sa.Column('active_rev', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('last_run_at', sa.Float(), nullable=True),
            sa.Column('last_result', sa.Text(), nullable=True),
            sa.Column('updated_at', sa.DateTime(), nullable=True),
            sa.UniqueConstraint('id'),
            sa.UniqueConstraint('site_id'))
        op.create_index('ix_fc_calibration_site_site_id', 'fc_calibration_site', ['site_id'])
    if 'fc_calibration' not in have:
        op.create_table(
            'fc_calibration',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('site_id', sa.String(80), nullable=False),
            sa.Column('rev', sa.Integer(), nullable=False),
            sa.Column('kind', sa.String(1), nullable=False),
            sa.Column('var', sa.String(8), nullable=False),
            sa.Column('band', sa.String(8), nullable=False),
            sa.Column('status', sa.String(16), nullable=False),
            sa.Column('reason', sa.String(32), nullable=True),
            sa.Column('method', sa.String(16), nullable=True),
            sa.Column('coef', sa.Text(), nullable=True),
            sa.Column('meta', sa.Text(), nullable=True),
            sa.Column('window_start', sa.Float(), nullable=True),
            sa.Column('window_end', sa.Float(), nullable=True),
            sa.Column('l0_kind', sa.String(16), nullable=False, server_default='actual'),
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.UniqueConstraint('id'),
            sa.UniqueConstraint('site_id', 'rev', 'kind', 'var', 'band', name='uq_fc_calibration_item'))
        op.create_index('ix_fc_calibration_site_id', 'fc_calibration', ['site_id'])
        op.create_index('ix_fc_calibration_rev', 'fc_calibration', ['rev'])
    if 'fc_cal_event' not in have:
        op.create_table(
            'fc_cal_event',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('unique_id', sa.String(36), nullable=False),
            sa.Column('site_id', sa.String(80), nullable=False),
            sa.Column('rev', sa.Integer(), nullable=False),
            sa.Column('event', sa.String(16), nullable=False),
            sa.Column('kind', sa.String(1), nullable=False),
            sa.Column('var', sa.String(8), nullable=False),
            sa.Column('band', sa.String(8), nullable=False),
            sa.Column('detail', sa.Text(), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.Column('acked', sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.UniqueConstraint('id'),
            sa.UniqueConstraint('unique_id'))
        op.create_index('ix_fc_cal_event_site_id', 'fc_cal_event', ['site_id'])
        op.create_index('ix_fc_cal_event_created_at', 'fc_cal_event', ['created_at'])


def downgrade():
    have = _tables()
    for name in ('fc_cal_event', 'fc_calibration', 'fc_calibration_site'):
        if name in have:
            op.drop_table(name)
