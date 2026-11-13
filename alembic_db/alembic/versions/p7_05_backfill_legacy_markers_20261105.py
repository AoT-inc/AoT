# coding=utf-8
"""P7-05: 레거시 마커 컬럼(`geo_shape.device_id`)을 geo_binding 으로 백필하고 검증한다.

장치 위치 정본 하나 L4 / geo_binding Phase C-4 의 선행 단계. 이 리비전은
**아무것도 지우지 않는다.** 뒤이은 리비전이 `geo_shape.device_id` 와 장치 행의
좌표·시간대 컬럼을 지우므로, 그 전에 레거시 컬럼에만 있는 연결을 바인딩으로
옮기고, 못 옮긴 것이 있으면 **여기서 업그레이드를 멈춘다**(가드).

## 규칙 (scripts/backfill_geo_binding.py 의 원천 ① 과 같다)

  - type 'aot_device' → role 'marker', type 'device' → role 'area'. 다른 type 은
    건드리지 않는다(보고만).
  - device_kind 는 uuid 가 실존하는 장치 표로 판별한다. 어디에도 없는 uuid 는
    죽은 참조 — 바인딩으로 승격하지 않고 건너뛴다(차단하지 않음).
  - 자리(shape+role+channel)에 이미 **다른 장치**의 현재 바인딩이 있으면 건너뛴다.
    사람이 실제로 한 배정이 정본이고, 컬럼은 교체 때 따라 갱신되지 않았다.
  - 이미 같은 현재 바인딩이 있으면 건너뛴다(멱등).
  - valid_from 은 실행 시각. 과거 이력을 지어내지 않는다.

## 가드

장치가 실존하고 자리가 비어 있는데도 바인딩을 못 만든 행(삽입 실패)이 하나라도
있으면 RuntimeError 로 중단한다. 죽은 참조·임자가 다른 자리는 정당한 건너뜀이라
차단하지 않는다. 백업 없이 지울 수 없는 데이터를 지우기 전의 마지막 관문이다.

geo_binding 이나 `geo_shape.device_id` 가 없는 DB 는 할 일이 없어 그냥 지나간다.

## downgrade

없음(백필된 행은 무해하며, 지우면 사람이 한 배정과 구분되지 않는다).

Revision ID: p7_05_backfill_legacy_markers_20261105
Revises: p7_04_drop_device_location_dead_columns_20261105
Create Date: 2026-11-05
"""
import logging
import uuid
from datetime import datetime, timezone

import sqlalchemy as sa
from alembic import op

revision = 'p7_05_backfill_legacy_markers_20261105'
down_revision = 'p7_05_camera_driver_20261105'
branch_labels = None
depends_on = None

log = logging.getLogger('alembic.runtime.migration')

# geo_marker_kinds.MARKER_TYPE 등을 import 하지 않고 시점을 고정한다.
SHAPE_TYPE_ROLES = {'aot_device': 'marker', 'device': 'area'}
# device_binding.device_kind_models() 의 판별 순서와 같다.
KIND_TABLES = (('input', 'input'), ('output', 'output'),
               ('device', 'custom_controller'), ('function', 'function'),
               ('pid', 'pid'), ('trigger', 'trigger'),
               ('conditional', 'conditional'))


def _has_column(insp, table, col):
    return table in insp.get_table_names() and any(
        c['name'] == col for c in insp.get_columns(table))


def backfill_legacy_markers(conn):
    """백필하고 통계를 돌려준다. 막아야 할 실패가 있으면 'failed' 목록이 비지 않는다."""
    insp = sa.inspect(conn)
    stats = {'created': 0, 'present': 0, 'dead': [], 'slot_taken': [],
             'unmapped_type': [], 'failed': []}
    if 'geo_binding' not in insp.get_table_names() or \
            not _has_column(insp, 'geo_shape', 'device_id'):
        return stats

    has_channel = _has_column(insp, 'geo_shape', 'channel_id')
    kind_of = {}
    for kind, table in KIND_TABLES:
        if table in insp.get_table_names():
            for (u,) in conn.execute(sa.text('SELECT unique_id FROM "%s"' % table)):
                kind_of.setdefault(u, kind)

    rows = conn.execute(sa.text(
        "SELECT unique_id, type, device_id, %s FROM geo_shape "
        "WHERE device_id IS NOT NULL AND device_id != ''"
        % ('channel_id' if has_channel else "'0'"))).fetchall()

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    for sid, stype, dev, ch in rows:
        ch = (ch or '0')
        role = SHAPE_TYPE_ROLES.get(stype)
        if role is None:
            stats['unmapped_type'].append((sid, stype, dev))
            continue
        kind = kind_of.get(dev)
        if kind is None:
            stats['dead'].append((sid, dev))
            continue
        holder = conn.execute(sa.text(
            "SELECT device_id FROM geo_binding WHERE spatial_kind='shape' "
            "AND spatial_id=:s AND role=:r AND channel_id=:c "
            "AND valid_to IS NULL"), dict(s=sid, r=role, c=ch)).fetchall()
        if any(h[0] == dev for h in holder):
            stats['present'] += 1
            continue
        if holder:
            stats['slot_taken'].append((sid, dev, holder[0][0]))
            continue
        try:
            with conn.begin_nested():
                conn.execute(sa.text(
                    "INSERT INTO geo_binding (unique_id, spatial_kind, "
                    "spatial_id, role, device_kind, device_id, channel_id, "
                    "valid_from, created_at) VALUES (:u,'shape',:s,:r,:k,:d,"
                    ":c,:t,:t)"),
                    dict(u=str(uuid.uuid4()), s=sid, r=role, k=kind, d=dev,
                         c=ch, t=now))
            stats['created'] += 1
        except Exception as e:  # 인덱스·트리거 거부 등
            stats['failed'].append((sid, dev, str(e)[:200]))
    return stats


def upgrade():
    stats = backfill_legacy_markers(op.get_bind())
    log.info('p7_05 백필: 생성 %d, 이미 있음 %d, 죽은 참조 %d, 임자 다른 자리 %d, '
             '미매핑 type %d, 실패 %d', stats['created'], stats['present'],
             len(stats['dead']), len(stats['slot_taken']),
             len(stats['unmapped_type']), len(stats['failed']))
    if stats['failed']:
        raise RuntimeError(
            'p7_05: 레거시 마커 %d건을 geo_binding 으로 옮기지 못했다 — 업그레이드를 '
            '중단한다(아무것도 지우지 않았다). 첫 건: %r' %
            (len(stats['failed']), stats['failed'][0]))


def downgrade():
    pass
