# coding=utf-8
"""P7-07: 장치 행의 시간대 컬럼(`timezone`·`tz_source`)을 지운다 (장치 위치 정본 하나 L4).

결정 ①: 장치별 시간대는 캐시였고, 시간대의 권위는 배치(도형 트리)다. 장치의
시간대는 이제 읽을 때 `timekit.tz_of` 가 배치 도형에서 상속으로 해석한다
(docs/design/timezone-management.md §4.2·§5). 그래서 장치 7종의 `timezone`·
`tz_source` 캐시 컬럼을 지운다. `latitude`·`longitude` 는 별개 결정(예보 지점
좌표 자리)이 남아 그대로 둔다.

## 순서가 중요하다 — explicit 승격 먼저

`tz_source='explicit'` 은 사람이 "이 장치만 다른 시간대"로 핀한 의도다. 컬럼을
지우기 전에 그 의도를 **대표 자리 도형의 timezone 으로 승격**한다(도형이 이미
explicit tz 를 가지면 건드리지 않는다 — 사람이 도형에 정한 것이 우선).

자리(현재 shape 바인딩)가 없는 explicit 장치는 **자동으로 처리하지 않는다**:
승격할 곳이 없으므로 `RuntimeError` 로 업그레이드를 멈춘다(아무 컬럼도 지우지
않았다). 운영자가 그 장치에 자리(대지)를 만들어 승격하거나 `tz_source` 를 바꾼
뒤 다시 마이그레이션한다. (계획 device-concept-ui-ux-plan §L4·결정 메모)

컬럼 삭제는 SQLite **제자리 `DROP COLUMN`(3.35+)** 으로 한다 — 표 재생성은
그 표에 걸린 트리거(GB-3 등)를 잃으므로 쓰지 않는다. 3.35 미만이면 지우지
않고 경고만 남긴다(컬럼이 남아도 앱은 읽지 않는다 — 비파괴 우선).

## downgrade

컬럼을 다시 만든다(nullable, 값 NULL). **지운 값은 돌아오지 않는다** — L4
이후 장치 시간대는 정본이 아니고(배치에서 해석), 승격된 explicit 값은 도형에
남는다.

Revision ID: p7_07_drop_device_tz_columns_20261105
Revises: p7_06_drop_geo_shape_device_id_20261105
Create Date: 2026-11-05
"""
import logging
import sqlite3

import sqlalchemy as sa
from alembic import op

revision = 'p7_07_drop_device_tz_columns_20261105'
down_revision = 'p7_06_drop_geo_shape_device_id_20261105'
branch_labels = None
depends_on = None

log = logging.getLogger('alembic.runtime.migration')

# geo_integrity_ddl.DEVICE_LINK_TABLES 와 같은 7종 — 시점을 고정하려고 적어 둔다.
DEVICE_TABLES = ('input', 'output', 'pid', 'trigger', 'conditional',
                 'custom_controller', 'function')
TZ_COLUMNS = ('timezone', 'tz_source')

# 되만들 때의 타입(원래 선언: models/_locatable.py).
_TYPES = {
    'timezone': sa.String(64),
    'tz_source': sa.String(16),
}


def _is_sqlite(bind):
    return bind.dialect.name == 'sqlite'


def _has_column(insp, table, col):
    return table in insp.get_table_names() and any(
        c['name'] == col for c in insp.get_columns(table))


def _cols(bind, table):
    insp = sa.inspect(bind)
    if table not in insp.get_table_names():
        return None
    return {c['name'] for c in insp.get_columns(table)}


def promote_explicit_tz(conn):
    """explicit 장치 시간대를 대표 자리 도형으로 승격. 통계를 돌려준다.
    승격할 자리가 없는 explicit 행이 있으면 'placeless' 가 비지 않는다(호출자가 중단)."""
    insp = sa.inspect(conn)
    tables = set(insp.get_table_names())
    stats = {'promoted': 0, 'shape_already_explicit': 0, 'placeless': []}
    shape_has_tz = (_has_column(insp, 'geo_shape', 'timezone')
                    and _has_column(insp, 'geo_shape', 'tz_source'))
    has_binding = 'geo_binding' in tables

    for table in DEVICE_TABLES:
        if table not in tables:
            continue
        if not (_has_column(insp, table, 'timezone')
                and _has_column(insp, table, 'tz_source')):
            continue
        rows = conn.execute(sa.text(
            'SELECT unique_id, timezone FROM "%s" '
            "WHERE tz_source = 'explicit' AND timezone IS NOT NULL "
            "AND timezone != ''" % table)).fetchall()
        for dev, tz in rows:
            # 현재 shape 바인딩 — 대표 자리는 marker 우선, 없으면 아무 현재 바인딩.
            binds = []
            if has_binding:
                binds = conn.execute(sa.text(
                    "SELECT role, spatial_id FROM geo_binding "
                    "WHERE spatial_kind = 'shape' AND valid_to IS NULL "
                    "AND (device_id = :d OR device_id LIKE :dl)"),
                    dict(d=dev, dl=str(dev) + '::%')).fetchall()
            if not binds or not shape_has_tz:
                stats['placeless'].append((table, dev, tz))
                continue
            shape = next((s for r, s in binds if r == 'marker'), binds[0][1])
            cur = conn.execute(sa.text(
                "SELECT timezone, tz_source FROM geo_shape WHERE unique_id = :s"),
                dict(s=shape)).first()
            if cur is not None and cur[1] == 'explicit' and cur[0]:
                stats['shape_already_explicit'] += 1
                continue
            conn.execute(sa.text(
                "UPDATE geo_shape SET timezone = :t, tz_source = 'explicit' "
                "WHERE unique_id = :s"), dict(t=tz, s=shape))
            stats['promoted'] += 1
    return stats


def upgrade():
    bind = op.get_bind()
    stats = promote_explicit_tz(bind)
    log.info('p7_07 explicit tz 승격: 승격 %d, 도형 이미 explicit %d, 자리 없음 %d',
             stats['promoted'], stats['shape_already_explicit'],
             len(stats['placeless']))
    if stats['placeless']:
        raise RuntimeError(
            'p7_07: 자리 없는 explicit 시간대 장치 %d건 — 지우면 그 값이 사라진다. '
            '먼저 그 장치에 자리(대지)를 만들어 승격하거나 tz_source 를 바꾼 뒤 다시 '
            '마이그레이션하라(아무 컬럼도 지우지 않았다). 첫 건: %r'
            % (len(stats['placeless']), stats['placeless'][0]))

    if _is_sqlite(bind) and sqlite3.sqlite_version_info < (3, 35, 0):
        log.warning('SQLite %s 는 제자리 DROP COLUMN 을 지원하지 않아 장치 시간대 '
                    '컬럼을 남겨 둡니다(앱은 읽지 않습니다).', sqlite3.sqlite_version)
        return
    for table in DEVICE_TABLES:
        present = _cols(bind, table)
        if present is None:
            continue
        for col in TZ_COLUMNS:
            if col in present:
                op.drop_column(table, col)


def downgrade():
    bind = op.get_bind()
    for table in DEVICE_TABLES:
        present = _cols(bind, table)
        if present is None:
            continue
        for col in TZ_COLUMNS:
            if col not in present:
                op.add_column(table, sa.Column(col, _TYPES[col], nullable=True))
