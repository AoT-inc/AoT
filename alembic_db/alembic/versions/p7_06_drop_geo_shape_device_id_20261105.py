# coding=utf-8
"""P7-06: 레거시 `geo_shape.device_id` 컬럼을 지운다 (장치 위치 정본 하나 L4 / geo_binding C-4).

마커·구역의 장치 연결은 geo_binding 이 유일한 정본이다. L4 S2 가 컬럼의 읽기·쓰기를
모두 걷어냈고(리졸버·게이트웨이·소비자·저장 경로), p7_05 가 컬럼에만 있던 연결을
바인딩으로 옮겼다. 이 리비전은 그 컬럼과, 그 컬럼에 걸린 인덱스를 지운다.

## 가드 (되돌릴 수 없는 삭제의 마지막 관문)

컬럼에 **살아 있는 장치**를 가리키는데 그 자리(도형+역할+채널)에 현재 바인딩이 하나도
없는 행이 남아 있으면 `RuntimeError` 로 중단한다 — 이 값은 컬럼을 지우면 영영 사라진다.
다음은 정당한 경우라 막지 않는다:
  - 죽은 참조(어느 장치 표에도 없는 uuid) — 장치가 이미 없다.
  - 자리에 다른 장치의 바인딩이 있다 — 사람이 한 배정이 정본이고 컬럼은 옛 값이다.
  - 마커·구역이 아닌 type — 장치를 매다는 자리가 아니었다.

## 마커 유일성 (I2)

옛 `geo_itg_i2_marker_unique`(컬럼 위의 부분 유니크 인덱스)는 컬럼과 함께 사라진다.
같은 불변식("지도·장치·채널당 마커 1개")은 바인딩 트리거 `geo_itg_i2b_marker_ins/upd` 로
옮겼다(geo_integrity_ddl). geo_binding 이 있는 DB 에만 만든다.

## SQLite

제자리 `DROP COLUMN`(3.35+)을 쓴다. 컬럼을 참조하는 인덱스(`ix_geo_shape_device_id`,
I2)를 먼저 지운다. 3.35 미만이면 **지우지 않고** 경고만 남긴다 — 앱은 컬럼을 읽지 않는다.

## downgrade

컬럼(nullable)과 `ix_geo_shape_device_id` 를 다시 만들고 I2b 를 내린다. **지운 값은
돌아오지 않는다**(바인딩이 정본이었다). 옛 I2 인덱스는 값이 NULL 이라 의미가 없어 되살리지 않는다.

Revision ID: p7_06_drop_geo_shape_device_id_20261105
Revises: p7_05_backfill_legacy_markers_20261105
Create Date: 2026-11-05
"""
import logging
import sqlite3

import sqlalchemy as sa
from alembic import op

revision = 'p7_06_drop_geo_shape_device_id_20261105'
down_revision = 'p7_05_backfill_legacy_markers_20261105'
branch_labels = None
depends_on = None

log = logging.getLogger('alembic.runtime.migration')

SHAPE_TYPE_ROLES = {'aot_device': 'marker', 'device': 'area'}
DEVICE_TABLES = ('input', 'output', 'custom_controller', 'function', 'pid',
                 'trigger', 'conditional')
OLD_INDEXES = ('geo_itg_i2_marker_unique', 'ix_geo_shape_device_id')
I2B = ('geo_itg_i2b_marker_ins', 'geo_itg_i2b_marker_upd')


def _is_sqlite(bind):
    return bind.dialect.name == 'sqlite'


def _has_column(bind, table, col):
    insp = sa.inspect(bind)
    return table in insp.get_table_names() and any(
        c['name'] == col for c in insp.get_columns(table))


def unsafe_rows(bind):
    """컬럼 값이 살아 있는 장치를 가리키는데 자리에 바인딩이 없는 행들(= 지우면 잃는 것)."""
    insp = sa.inspect(bind)
    if not _has_column(bind, 'geo_shape', 'device_id'):
        return []
    live = set()
    for t in DEVICE_TABLES:
        if t in insp.get_table_names():
            live.update(r[0] for r in bind.execute(
                sa.text('SELECT unique_id FROM "%s"' % t)))
    has_binding = 'geo_binding' in insp.get_table_names()
    has_channel = _has_column(bind, 'geo_shape', 'channel_id')
    rows = bind.execute(sa.text(
        "SELECT unique_id, type, device_id, %s FROM geo_shape "
        "WHERE device_id IS NOT NULL AND device_id != ''"
        % ('channel_id' if has_channel else "'0'"))).fetchall()
    bad = []
    for sid, stype, dev, ch in rows:
        role = SHAPE_TYPE_ROLES.get(stype)
        base = dev.split('::')[0]
        if role is None or base not in live:
            continue
        bound = False
        if has_binding:
            bound = bind.execute(sa.text(
                "SELECT 1 FROM geo_binding WHERE spatial_kind='shape' "
                "AND spatial_id=:s AND role=:r AND channel_id=:c "
                "AND valid_to IS NULL LIMIT 1"),
                dict(s=sid, r=role, c=(ch or '0'))).first() is not None
        if not bound:
            bad.append((sid, stype, dev))
    return bad


def upgrade():
    bind = op.get_bind()
    if not _has_column(bind, 'geo_shape', 'device_id'):
        _ensure_i2b(bind)
        return
    if _is_sqlite(bind) and sqlite3.sqlite_version_info < (3, 35, 0):
        log.warning('SQLite %s 는 제자리 DROP COLUMN 을 지원하지 않아 geo_shape.device_id '
                    '를 남겨 둡니다(앱은 읽지 않습니다).', sqlite3.sqlite_version)
        _ensure_i2b(bind)
        return

    bad = unsafe_rows(bind)
    if bad:
        raise RuntimeError(
            'p7_06: geo_shape.device_id 에만 남은 살아 있는 연결 %d건 — 컬럼을 지우면 '
            '잃는다. 업그레이드를 중단한다(아무것도 지우지 않았다). p7_05 백필 결과를 '
            '확인할 것. 첫 건: %r' % (len(bad), bad[0]))

    if _is_sqlite(bind):
        for name in OLD_INDEXES:
            bind.exec_driver_sql('DROP INDEX IF EXISTS %s' % name)
    else:
        for name in OLD_INDEXES:
            try:
                op.drop_index(name, table_name='geo_shape')
            except Exception:  # noqa: BLE001 — 없으면 무동작
                pass
    op.drop_column('geo_shape', 'device_id')
    _ensure_i2b(bind)


_I2B_COND = """
NEW.spatial_kind = 'shape' AND NEW.role = 'marker' AND NEW.valid_to IS NULL
AND EXISTS (
  SELECT 1
    FROM geo_binding b
    JOIN geo_shape s2 ON s2.unique_id = b.spatial_id
    JOIN geo_shape s1 ON s1.unique_id = NEW.spatial_id
   WHERE b.spatial_kind = 'shape' AND b.role = 'marker'
     AND b.valid_to IS NULL
     AND b.device_id = NEW.device_id
     AND b.channel_id = NEW.channel_id
     AND b.spatial_id <> NEW.spatial_id
     AND s2.geo_id = s1.geo_id
     AND s2.type = 'aot_device')
"""


def _ensure_i2b(bind):
    """I2b 트리거를 만든다(geo_binding 이 있는 SQLite 에만). 멱등.

    geo_integrity_ddl 을 import 하지 않고 이 시점의 SQL 을 고정한다(과거 리비전이
    현재 모듈 모양에 매이지 않도록 — p7_04 와 같은 이유).
    """
    if not _is_sqlite(bind) or 'geo_binding' not in sa.inspect(bind).get_table_names():
        return
    for when, name in (('INSERT', I2B[0]), ('UPDATE', I2B[1])):
        bind.exec_driver_sql('DROP TRIGGER IF EXISTS %s' % name)
        bind.exec_driver_sql(
            "CREATE TRIGGER %s BEFORE %s ON geo_binding WHEN %s BEGIN "
            "SELECT RAISE(ABORT, 'GEO-I2: 같은 지도에 같은 장치·채널의 마커가 이미 있다'); END"
            % (name, when, _I2B_COND))


def downgrade():
    bind = op.get_bind()
    if _is_sqlite(bind):
        for name in I2B:
            bind.exec_driver_sql('DROP TRIGGER IF EXISTS %s' % name)
    if not _has_column(bind, 'geo_shape', 'device_id'):
        op.add_column('geo_shape',
                      sa.Column('device_id', sa.String(64), nullable=True))
        op.create_index('ix_geo_shape_device_id', 'geo_shape', ['device_id'])
