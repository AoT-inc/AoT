# coding=utf-8
"""P6-68: 측정 정의 제거 표시 — device_measurements.removed_at.

측정 정의를 지우면 떼어낸 센서의 과거 값(Influx 에 장치 id·채널 태그로 남는다)을
어떤 채널·단위로 불러야 하는지가 사라진다. 구획이 "그 기간 그 자리의 센서" 값을
다시 적용하려면 정의가 남아 있어야 하므로, 삭제를 제거 표시로 바꾼다
(docs/design/geo-plot-instance.md §센서 위치 이력).

nullable 이라 기존 행에 무해하다. 신규 설치는 db.create_all()이 스키마를 만든다.

Revision ID: p6_68_device_measurement_removed_at_20260915
Revises: p6_67_user_ui_zoom_desktop_20260911
Create Date: 2026-09-15
"""
import sqlalchemy as sa
from alembic import op

revision = 'p6_68_device_measurement_removed_at_20260915'
down_revision = 'p6_67_user_ui_zoom_desktop_20260911'
branch_labels = None
depends_on = None

_TABLE = 'device_measurements'
_COLUMN = 'removed_at'


def _has_column(table, column):
    bind = op.get_bind()
    insp = sa.inspect(bind)
    try:
        cols = [c['name'] for c in insp.get_columns(table)]
    except Exception:
        return False
    return column in cols


def _has_table(table):
    bind = op.get_bind()
    insp = sa.inspect(bind)
    try:
        return table in insp.get_table_names()
    except Exception:
        return False


def upgrade():
    if _has_table(_TABLE) and not _has_column(_TABLE, _COLUMN):
        op.add_column(_TABLE, sa.Column(_COLUMN, sa.DateTime(), nullable=True))


def downgrade():
    if _has_table(_TABLE) and _has_column(_TABLE, _COLUMN):
        with op.batch_alter_table(_TABLE) as batch:
            batch.drop_column(_COLUMN)
