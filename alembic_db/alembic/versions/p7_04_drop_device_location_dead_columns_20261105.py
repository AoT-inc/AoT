# coding=utf-8
"""P7-04: 장치 행의 죽은 위치 컬럼 세 개를 지운다 (장치 위치 정본 하나 L3).

위치의 정본은 배치(geo_binding 자리 + 자리 기하)이고, 읽기는
`aot/aot_flask/geo/device_location.locate()`, 쓰기는
`device_placement.place_device()` 하나로 모였다(L1·L2). 그 뒤로 아무도
읽거나 쓰지 않는 세 컬럼을 지운다.

  - `map_config_id`        — 7개 장치 표 전부. 지도는 마커·바인딩에서 파생한다.
  - `location_source`      — 7개 장치 표 전부. `Placement.source` 가 대체.
  - `location_updated_utc` — input·output 만. 앱 읽기 없음.

`latitude`·`longitude`·`timezone`·`tz_source` 는 L4 몫이라 그대로 둔다.

## 순서가 중요하다

1. 지도 삭제 트리거 I5(`geo_itg_i5_map_cascade`, geo_map 위)가 7개 표의
   `map_config_id` 를 NULL 로 되돌린다. 컬럼을 참조하는 트리거가 남아 있으면
   SQLite 의 `ALTER TABLE ... DROP COLUMN` 이 거절한다. 그래서 먼저 I5 를
   `map_config_id` 줄이 없는 판으로 갈아 끼운다(I5 가 원래 없던 DB 에는
   만들지 않는다 — Tier-1 을 켜지 않은 설치를 바꾸지 않는다).
2. 컬럼을 지운다. SQLite 는 **제자리 `DROP COLUMN`(3.35+)** 을 쓴다.
   `batch_alter_table` 의 표 재생성은 쓰지 않는다 — 표를 새로 만들어
   옮기면 그 표에 걸린 트리거(GB-3 `geo_itg_gb3_<표>` 등)가 함께 사라지고,
   외래 키를 켠 연결에서는 자식 행 연쇄 삭제 위험까지 있다. SQLite 가
   3.35 보다 낮으면 **지우지 않고** 경고만 남긴다(컬럼이 남아도 앱은 읽지
   않는다 — 비파괴가 우선).

## downgrade

컬럼을 다시 만든다(nullable, 값은 NULL). **지운 값은 돌아오지 않는다** —
L1·L2 이후 이 값들은 정본이 아니었고 앱도 읽지 않았으므로 되돌림에 필요한
정보가 아니다. I5 는 `map_config_id` 줄이 있는 옛 판으로 되돌린다(있던 경우만).

Revision ID: p7_04_drop_device_location_dead_columns_20261105
Revises: p7_03_geo_favorite_20261104
Create Date: 2026-11-05
"""
import logging
import sqlite3

import sqlalchemy as sa
from alembic import op

revision = 'p7_04_drop_device_location_dead_columns_20261105'
down_revision = 'p7_03_geo_favorite_20261104'
branch_labels = None
depends_on = None

log = logging.getLogger('alembic.runtime.migration')

# geo_integrity_ddl.DEVICE_LINK_TABLES 와 같은 7종 — 이 이전의 시점을 고정하려고
# import 하지 않고 적어 둔다.
DEVICE_TABLES = ('input', 'output', 'pid', 'trigger', 'conditional',
                 'custom_controller', 'function')
COLUMNS = {t: ('map_config_id', 'location_source') for t in DEVICE_TABLES}
COLUMNS['input'] += ('location_updated_utc',)
COLUMNS['output'] += ('location_updated_utc',)

# 되만들 때의 타입(원래 선언: models/_locatable.py, input.py, output.py).
_TYPES = {
    'map_config_id': lambda t: sa.String(36),
    'location_source': lambda t: sa.Text() if t in ('input', 'output') else sa.String(32),
    'location_updated_utc': lambda t: sa.DateTime(),
}

I5 = 'geo_itg_i5_map_cascade'


def _i5_sql(with_config_null):
    overlay_null = '\n'.join(
        '        UPDATE "{t}" SET map_overlay_id = NULL WHERE map_overlay_id IN '
        '(SELECT id FROM geo_shape WHERE geo_id = OLD.unique_id);'.format(t=t)
        for t in DEVICE_TABLES)
    config_null = '\n'.join(
        '        UPDATE "{t}" SET map_config_id = NULL '
        'WHERE map_config_id = OLD.unique_id;'.format(t=t)
        for t in DEVICE_TABLES) if with_config_null else ''
    return """
    CREATE TRIGGER {name}
    AFTER DELETE ON geo_map
    BEGIN
{overlay_null}
{config_null}
        DELETE FROM geo_facility_setpoint
         WHERE facility_uuid IN (SELECT unique_id FROM geo_facility
                                  WHERE geo_id = OLD.unique_id);
        DELETE FROM geo_facility WHERE geo_id = OLD.unique_id;
        DELETE FROM geo_shape WHERE geo_id = OLD.unique_id;
    END
    """.format(name=I5, overlay_null=overlay_null, config_null=config_null)


def _is_sqlite(bind):
    return bind.dialect.name == 'sqlite'


def _has_trigger(bind, name):
    return bind.execute(sa.text(
        "SELECT 1 FROM sqlite_master WHERE type='trigger' AND name=:n"),
        {'n': name}).first() is not None


def _swap_i5(bind, with_config_null):
    if not _is_sqlite(bind) or not _has_trigger(bind, I5):
        return
    bind.exec_driver_sql('DROP TRIGGER IF EXISTS %s' % I5)
    bind.exec_driver_sql(_i5_sql(with_config_null))


def _cols(bind, table):
    insp = sa.inspect(bind)
    if table not in insp.get_table_names():
        return None
    return {c['name'] for c in insp.get_columns(table)}


def upgrade():
    bind = op.get_bind()
    if _is_sqlite(bind) and sqlite3.sqlite_version_info < (3, 35, 0):
        log.warning('SQLite %s 는 제자리 DROP COLUMN 을 지원하지 않아 죽은 위치 '
                    '컬럼을 남겨 둡니다(앱은 읽지 않습니다).', sqlite3.sqlite_version)
        return
    _swap_i5(bind, with_config_null=False)
    for table, columns in COLUMNS.items():
        present = _cols(bind, table)
        if present is None:
            continue
        for col in columns:
            if col in present:
                op.drop_column(table, col)


def downgrade():
    bind = op.get_bind()
    for table, columns in COLUMNS.items():
        present = _cols(bind, table)
        if present is None:
            continue
        for col in columns:
            if col not in present:
                op.add_column(table, sa.Column(col, _TYPES[col](table), nullable=True))
    _swap_i5(bind, with_config_null=True)
