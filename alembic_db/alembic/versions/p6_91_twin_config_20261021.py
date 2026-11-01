# coding=utf-8
"""P6-91: 디지털트윈(실험) 대지·구획 설정 표 twin_config.

배포 제안 개정 2 §7 S3. 대지를 켜고 출처(비·기온·ET0·토양수분·예보 입력)를 고른 것을
DB 에 둔다 — S2 의 임시 덮어쓰기 JSON 을 대신한다. 구획은 대지에서 물려받고 덮어쓴다.

  scope      'site' | 'plot'
  target_id  대지 GeoShape.unique_id(대지 밖이면 'map:<지도 id>') 또는 GeoPlot.unique_id
  enabled    대지 켜기 / 구획 포함·제외(NULL = 대지를 따름)
  config     JSON 텍스트 {inputs, options, forecast} — aot/databases/models/twin_config.py

재실행 안전: 표가 있으면 건너뛴다. downgrade 는 표를 지운다(예측 데이터는 Influx 라 영향 없음).

Revision ID: p6_91_twin_config_20261021
Revises: p6_90_twin_settings_20261021
Create Date: 2026-10-21
"""
import sqlalchemy as sa
from alembic import op

revision = 'p6_91_twin_config_20261021'
down_revision = 'p6_90_twin_settings_20261021'
branch_labels = None
depends_on = None

TABLE = 'twin_config'


def _has_table():
    return TABLE in sa.inspect(op.get_bind()).get_table_names()


def upgrade():
    if _has_table():
        return
    op.create_table(
        TABLE,
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('unique_id', sa.String(length=36), nullable=False),
        sa.Column('scope', sa.String(length=8), nullable=False),
        sa.Column('target_id', sa.String(length=80), nullable=False),
        sa.Column('enabled', sa.Boolean(), nullable=True),
        sa.Column('config', sa.Text(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('unique_id'),
        sa.UniqueConstraint('scope', 'target_id', name='uq_twin_config_target'),
    )
    op.create_index('ix_twin_config_target_id', TABLE, ['target_id'])


def downgrade():
    if not _has_table():
        return
    op.drop_index('ix_twin_config_target_id', table_name=TABLE)
    op.drop_table(TABLE)
