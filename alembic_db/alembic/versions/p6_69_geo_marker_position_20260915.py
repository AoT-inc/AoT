# coding=utf-8
"""P6-69: 장치 위치 마커의 좌표 기간 기록 — geo_marker_position.

좌표를 옮기면 마커 feature 를 덮어쓰고, 장치를 지우면 마커 도형을 지운다.
그래서 "그 기간에 그 센서가 어디 있었나" 가 사라져, 떼어낸 센서의 과거 값을
구획 위치에 다시 적용할 수 없었다. 좌표를 기간과 함께 남기는 표를 만든다.

행은 ORM 리스너(geo_marker_position._register_marker_position_listeners)만 쓴다.
기존 마커는 백필하지 않는다 — 처음 바뀌는 순간 옛 좌표를 valid_from=NULL 로
먼저 남기므로, 운영 DB 에 일괄 작업을 돌리지 않아도 앞으로의 변경은 빠짐없이
남는다(docs/design/geo-plot-instance.md §센서 위치 이력).

신규 설치는 db.create_all()이 스키마를 만든다.

Revision ID: p6_69_geo_marker_position_20260915
Revises: p6_68_device_measurement_removed_at_20260915
Create Date: 2026-09-15
"""
import sqlalchemy as sa
from alembic import op

revision = 'p6_69_geo_marker_position_20260915'
down_revision = 'p6_68_device_measurement_removed_at_20260915'
branch_labels = None
depends_on = None

_TABLE = 'geo_marker_position'


def _has_table(table):
    bind = op.get_bind()
    insp = sa.inspect(bind)
    try:
        return table in insp.get_table_names()
    except Exception:
        return False


def upgrade():
    if _has_table(_TABLE):
        return
    op.create_table(
        _TABLE,
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('unique_id', sa.String(36), nullable=False, unique=True),
        sa.Column('shape_uuid', sa.String(36), nullable=False),
        sa.Column('geo_id', sa.String(64), nullable=False),
        sa.Column('lng', sa.Float(), nullable=False),
        sa.Column('lat', sa.Float(), nullable=False),
        sa.Column('valid_from', sa.DateTime(), nullable=True),
        sa.Column('valid_to', sa.DateTime(), nullable=True),
        sa.Column('ended_reason', sa.String(16), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
    )
    op.create_index('ix_geo_marker_position_shape_uuid', _TABLE, ['shape_uuid'])
    op.create_index('ix_geo_marker_position_geo_id', _TABLE, ['geo_id'])


def downgrade():
    if _has_table(_TABLE):
        op.drop_table(_TABLE)
