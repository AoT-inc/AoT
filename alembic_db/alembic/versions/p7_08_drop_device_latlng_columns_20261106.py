# coding=utf-8
"""P7-08: 장치 행의 좌표 컬럼(`latitude`·`longitude`)을 지운다 (장치 위치 정본 하나 L4, S3c).

장치 7종이 `_locatable.LocatableColumnsMixin` 으로 복붙해 온 마지막 위치 컬럼이다.
위치는 장치의 속성이 아니라 **배치(geo_binding 자리)의 결과**이고(결정: 2026-11-04
"장치 위치 정보의 정본 하나"), 좌표를 읽는 소비자는 전부 `timekit.resolve_coords`
→ `device_location.locate()` 로 수렴했다. 그 리졸버는 이미 장치 행 좌표를 읽지
않는다(S2a 에서 레거시 폴백 제거). 즉 이 컬럼은 읽는 코드가 없는 유령이다.

## 예보 지점 좌표
예보성 입력(open_meteo_*·kma·nasa·owm)의 "조회 지점"도 이 컬럼이 아니라 배치로
해석한다. 수동 배치는 지도 마커(→ geo_binding)로 이미 해석되고, 자동 생성
(`twin_config.create_forecast_input`)도 이 리비전과 함께 마커 배치(`place_device`)로
바뀌었다. 그래서 예보 좌표도 별도 저장소가 필요 없다.

## 백필을 하지 않는다 (의도)
S3b(p7_07, 시간대)와 달리 승격/백필이 없다. 이 컬럼은 **어느 소비자도 읽지 않으므로**
지워도 런타임 해석이 바뀌지 않는다. 컬럼 값을 마커로 되살리면 오히려 리졸버가
무시하던 좌표를 부활시켜(배치 ≠ 컬럼) 정본이 둘이 된다 — 그래서 되살리지 않는다.
값이 남아 있던 행 수는 기록용으로 로그만 남긴다(차단하지 않음).

## 컬럼 삭제
SQLite **제자리 `DROP COLUMN`(3.35+)** — 표 재생성은 그 표에 걸린 트리거(GB-3 등)를
잃으므로 쓰지 않는다. 3.35 미만이면 지우지 않고 경고만(앱은 읽지 않는다 — 비파괴 우선).

## downgrade
컬럼을 다시 만든다(nullable, 값 NULL). **지운 값은 돌아오지 않는다** — L4 이후 장치
좌표는 정본이 아니다(배치에서 해석).

Revision ID: p7_08_drop_device_latlng_columns_20261106
Revises: p7_07_drop_device_tz_columns_20261105
Create Date: 2026-11-06
"""
import logging
import sqlite3

import sqlalchemy as sa
from alembic import op

revision = 'p7_08_drop_device_latlng_columns_20261106'
down_revision = 'p7_07_drop_device_tz_columns_20261105'
branch_labels = None
depends_on = None

log = logging.getLogger('alembic.runtime.migration')

# geo_integrity_ddl.DEVICE_LINK_TABLES 와 같은 7종 — 시점을 고정하려고 적어 둔다.
DEVICE_TABLES = ('input', 'output', 'pid', 'trigger', 'conditional',
                 'custom_controller', 'function')
LATLNG_COLUMNS = ('latitude', 'longitude')

# 되만들 때의 타입(원래 선언: models/_locatable.py).
_TYPES = {
    'latitude': sa.Float(),
    'longitude': sa.Float(),
}


def _is_sqlite(bind):
    return bind.dialect.name == 'sqlite'


def _cols(bind, table):
    insp = sa.inspect(bind)
    if table not in insp.get_table_names():
        return None
    return {c['name'] for c in insp.get_columns(table)}


def _count_rows_with_coords(conn):
    """좌표가 남아 있던 행 수(기록용). 컬럼이 없는 표는 건너뛴다."""
    total = 0
    for table in DEVICE_TABLES:
        present = _cols(conn, table)
        if present is None or 'latitude' not in present or 'longitude' not in present:
            continue
        n = conn.execute(sa.text(
            'SELECT count(*) FROM "%s" '
            'WHERE latitude IS NOT NULL OR longitude IS NOT NULL' % table)).scalar()
        total += (n or 0)
    return total


def upgrade():
    bind = op.get_bind()
    had = _count_rows_with_coords(bind)
    log.info('p7_08 장치 좌표 컬럼 삭제: 값이 있던 행 %d건(백필하지 않음 — '
             '리졸버가 읽지 않는 유령 컬럼).', had)

    if _is_sqlite(bind) and sqlite3.sqlite_version_info < (3, 35, 0):
        log.warning('SQLite %s 는 제자리 DROP COLUMN 을 지원하지 않아 장치 좌표 '
                    '컬럼을 남겨 둡니다(앱은 읽지 않습니다).', sqlite3.sqlite_version)
        return
    for table in DEVICE_TABLES:
        present = _cols(bind, table)
        if present is None:
            continue
        for col in LATLNG_COLUMNS:
            if col in present:
                op.drop_column(table, col)


def downgrade():
    bind = op.get_bind()
    for table in DEVICE_TABLES:
        present = _cols(bind, table)
        if present is None:
            continue
        for col in LATLNG_COLUMNS:
            if col not in present:
                op.add_column(table, sa.Column(col, _TYPES[col], nullable=True))
