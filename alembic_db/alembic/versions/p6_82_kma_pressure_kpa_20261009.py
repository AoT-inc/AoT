# coding=utf-8
"""P6-82: 기상청(KMA) 입력의 기압 단위를 hPa → kPa 로.

p6_81 이 OpenWeatherMap 기압을 kPa 로 옮긴 뒤, 같은 측정을 드라이버마다 다른
단위로 두지 않도록 기상청도 맞춘다(2026-10-09 사용자 결정 — kPa 는 0.00 자리로
짧게 보이기 좋다). 드라이버(kma_weather_500)는 이제 hPa/10 을 kPa 로 저장한다.

저장되는 값의 단위 꼬리표는 이 행(`device_measurements.unit`)에서 오므로 함께
옮긴다. 과거 값은 `aot/scripts/migrate_pressure_kpa.py` 가 옮긴다 — 옮기기
전까지 그래프·조회가 과거 기압을 찾지 못한다.

'hPa' 이고 변환이 없는 행만 바꾼다(사람이 고른 단위·변환은 그대로).

Revision ID: p6_82_kma_pressure_kpa_20261009
Revises: p6_81_owm_pressure_kpa_20261009
Create Date: 2026-10-09
"""
import sqlalchemy as sa
from alembic import op

revision = 'p6_82_kma_pressure_kpa_20261009'
down_revision = 'p6_81_owm_pressure_kpa_20261009'
branch_labels = None
depends_on = None

_DRIVERS = ('KMA_weather_500',)


def _has_tables(*tables):
    insp = sa.inspect(op.get_bind())
    try:
        names = set(insp.get_table_names())
    except Exception:
        return False
    return all(t in names for t in tables)


def _swap(old, new):
    if not _has_tables('device_measurements', 'input'):
        return
    op.get_bind().execute(sa.text(
        "UPDATE device_measurements SET unit = :new "
        "WHERE measurement = 'pressure' AND unit = :old "
        "AND (conversion_id IS NULL OR conversion_id = '') "
        "AND device_id IN (SELECT unique_id FROM input WHERE device IN (%s))"
        % ", ".join("'%s'" % d for d in _DRIVERS)),
        {"old": old, "new": new})


def upgrade():
    _swap('hPa', 'kPa')


def downgrade():
    _swap('kPa', 'hPa')
