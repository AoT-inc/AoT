# coding=utf-8
"""P6-90: 디지털트윈(실험) 전역 설정 — misc.twin_enabled / twin_run_times / twin_heartbeat.

디지털트윈은 데몬과 분리된 별도 서비스(aot_twin)로 돈다. 설정 > 일반의 토글이 켜져
있어야 서비스가 일한다(plans/2026-10-21_twin_deploy_proposal.md).

  twin_enabled    사용자가 켠 플래그. 기본 꺼짐. 낮은 사양 기기의 잠금은 이 칸이 아니라
                  aot/utils/twin_gate.py 가 판정한다(켜져 있어도 잠기면 꺼진 것으로 본다).
  twin_run_times  실행 시각 'HH:MM,HH:MM'(현지). 기존 행은 06:10,18:10 으로 채운다
                  (TEXT 칸이라 server_default 를 쓰지 않는다 — MySQL 호환).
  twin_heartbeat  서비스가 쓰는 상태 JSON {at, status, version, sites, plots,
                  last_run_at, failures, locked_reason}. 서비스가 안 돌면 NULL.

재실행 안전: 이미 있는 칸은 건너뛴다. downgrade 는 세 칸을 지운다(예측 데이터는 Influx 라 영향 없음).

Revision ID: p6_90_twin_settings_20261021
Revises: p6_89_ai_card_attachments_20261021
Create Date: 2026-10-21
"""
import sqlalchemy as sa
from alembic import op

revision = 'p6_90_twin_settings_20261021'
down_revision = 'p6_89_ai_card_attachments_20261021'
branch_labels = None
depends_on = None

TABLE = 'misc'
DEFAULT_RUN_TIMES = '06:10,18:10'


def _columns(table):
    return {c['name'] for c in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade():
    have = _columns(TABLE)
    with op.batch_alter_table(TABLE, schema=None) as batch_op:
        if 'twin_enabled' not in have:
            batch_op.add_column(sa.Column(
                'twin_enabled', sa.Boolean(), nullable=True, server_default=sa.text("0")))
        if 'twin_run_times' not in have:
            batch_op.add_column(sa.Column('twin_run_times', sa.Text(), nullable=True))
        if 'twin_heartbeat' not in have:
            batch_op.add_column(sa.Column('twin_heartbeat', sa.JSON(), nullable=True))

    op.get_bind().execute(
        sa.text(f"UPDATE {TABLE} SET twin_run_times = :v "
                f"WHERE twin_run_times IS NULL OR twin_run_times = ''"),
        {'v': DEFAULT_RUN_TIMES})


def downgrade():
    have = _columns(TABLE)
    with op.batch_alter_table(TABLE, schema=None) as batch_op:
        for col in ('twin_heartbeat', 'twin_run_times', 'twin_enabled'):
            if col in have:
                batch_op.drop_column(col)
