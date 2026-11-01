# coding=utf-8
"""P6-97: 데이터 계층 설정 — misc.data_layers (예보·트윈 데이터 관리 D1).

Influx 버킷을 계층(L0 예보 발표본 `aot_fc`, 최신 곡선 `aot_calc`, 이력 `aot_hist`)으로 나누고 보존 기간을
계층별로 둔다(`aot/utils/influx_layers.py`). 그 설정을 담는 JSON 한 칸이다.

  {"enabled": true|false,                       # false 면 한 버킷(aot_db) 모드. 없으면 켜짐
   "retention_days": {"fc": 730, "calc": 60, "hist": 730}}   # 없는 계층은 기본값

NULL = 전부 기본값. 재실행 안전: 이미 있으면 건너뛴다. downgrade 는 칸을 지운다(데이터는 그대로).

Revision ID: p6_97_data_layers_20261025
Revises: p6_96_site_forecast_source_20261025
Create Date: 2026-10-25
"""
import sqlalchemy as sa
from alembic import op

revision = 'p6_97_data_layers_20261025'
down_revision = 'p6_96_site_forecast_source_20261025'
branch_labels = None
depends_on = None

TABLE = 'misc'


def _columns(table):
    return {c['name'] for c in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade():
    if 'data_layers' not in _columns(TABLE):
        with op.batch_alter_table(TABLE, schema=None) as batch_op:
            batch_op.add_column(sa.Column('data_layers', sa.JSON(), nullable=True))


def downgrade():
    if 'data_layers' in _columns(TABLE):
        with op.batch_alter_table(TABLE, schema=None) as batch_op:
            batch_op.drop_column('data_layers')
