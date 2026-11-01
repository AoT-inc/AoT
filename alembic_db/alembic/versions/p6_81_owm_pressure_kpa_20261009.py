# coding=utf-8
"""P6-81: OpenWeatherMap 입력의 기압 단위를 Pa → kPa 로.

두 OpenWeatherMap 드라이버(OPENWEATHERMAP_CALL_WEATHER · _ONECALL)는 API 가 hPa 로
주는 기압을 그대로 저장하면서 단위를 'Pa' 로 선언했다 — 1022 hPa 가 "1022 Pa" 로
보였다(2026-10-09 외부 AI 점검). 드라이버는 이제 kPa(hPa/10)로 저장한다.

저장되는 값의 단위 꼬리표는 드라이버 정의가 아니라 **이 행**(`device_measurements.unit`)
에서 온다(controller_input.create_measurements_dict). 그래서 이미 만들어진 장치의
행을 함께 옮기지 않으면 새 값이 'Pa' 꼬리표로 쌓인다.

⚠ InfluxDB 의 과거 값은 여기서 옮기지 않는다 — 행을 바꾸는 일과 시계열을 다시
쓰는 일을 한 트랜잭션에 섞지 않는다(백필이 마이그레이션과 분리된 것과 같은 판단).
과거 값은 `aot/scripts/migrate_owm_pressure_kpa.py` 가 옮긴다. 옮기기 전까지
그래프·조회는 과거 기압을 찾지 못한다(꼬리표가 'Pa' 로 남아 있다).

'Pa' 인 행만 바꾼다 — 사람이 다른 단위·변환을 골라 둔 행은 건드리지 않는다.

Revision ID: p6_81_owm_pressure_kpa_20261009
Revises: p6_80_api_key_tool_modules_20260929
Create Date: 2026-10-09
"""
import sqlalchemy as sa
from alembic import op

revision = 'p6_81_owm_pressure_kpa_20261009'
down_revision = 'p6_80_api_key_tool_modules_20260929'
branch_labels = None
depends_on = None

_DRIVERS = ('OPENWEATHERMAP_CALL_WEATHER', 'OPENWEATHERMAP_CALL_ONECALL')


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
    _swap('Pa', 'kPa')


def downgrade():
    _swap('kPa', 'Pa')
