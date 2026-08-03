# coding=utf-8
"""P6-21: 지도 도형 타입 정합 + 끊어진 zone/site 소속 복구.

GeoShape 는 도형 종류를 `type` 컬럼과 `feature.properties.aot_type` 두 곳에
들고 있다. 코드는 aot_type 을 정본으로 취급하지만(geo_overlays.py 의
`props.get('aot_type', 'feature')`) 둘이 어긋나도 막는 장치가 없고, `type` 에는
`default='feature'` 라는 조용한 폴백이 있다. 그래서 도형을 만드는 코드가 type 을
한 번 빠뜨리면 에러 없이 'feature' 가 들어간다 — `clone_map_config()` 가 정확히
그랬고(수정: 579876a), 그렇게 복제된 지도는 도형 전체가 'feature' 가 됐다.

어긋난 뒤가 진짜 문제다. save_overlays() 는 갱신 대상도 삭제 범위도 전부
`type=target_type` 으로 스코프하므로, 어긋나 있으면 "기존 것 없음"으로 판정해
UPDATE 대신 INSERT 하고 옛 행은 삭제 범위 밖이라 남는다. 저장 한 번에 같은
도형이 두 벌이 되는데 아무 에러도 안 난다.

증상은 읽는 경로마다 다르게 나타난다:
  - 지도 위젯 3D 시설:  type='facility' 인 도형만 GeoFacility 메타를 받는다
                        → 'feature' 에 매달린 시설은 높이 없이 납작해진다
  - zone 모달 장치 조회: type='aot_device' 인 마커만 폴리곤 포함 판정에 들어간다
                        → 'feature' 마커는 zone 에 장치가 없는 것으로 보인다
  - facility 페이지:     GeoFacility 를 직접 읽어 멀쩡 → 화면끼리 서로 안 맞는다

코드 수정(579876a)은 신규 오염만 막는다. 이미 오염된 데이터는 서버마다 남아
있고, 수동 복구를 서버 수만큼 반복할 일이 아니라서 여기서 일괄 처리한다.
2026-08-03 실측: koat 242건, aot-005 11건(type-mismatch) / aot-004 26건
(dangling-link).

하는 일 두 가지. 둘 다 **행을 지우지 않는다.**

  1) type 정합 — properties.aot_type 이 있고 type 과 다르면 type 을 aot_type 으로
     맞춘다. aot_type 이 정본이므로 방향은 이쪽 하나뿐이다.

  2) 끊어진 소속 복구 — map_overlay_id 가 존재하지 않는 GeoShape.id 를 가리키는
     장치는, 같은 지도에 놓인 자기 마커 좌표로 감싸는 site/zone 을 다시 찾아
     연결한다. 감싸는 도형을 못 찾으면 **그대로 둔다**(NULL 로 지우지 않는다).
     find_containing_shape() 와 같은 규칙 — 겹치면 zone 이 site 를 이긴다.

중복 도형(duplicate)은 **손대지 않는다.** 기하가 같다는 이유로 지우면 안 되기
때문이다 — 짝 중 어느 쪽에 GeoFacility 나 map_overlay_id 가 매달려 있는지는
기하가 알려주지 않고, 2026-08-03 에 그걸 무시한 정리가 시설 4건을 날리고 참조
11건을 끊었다. 중복은 `aot/scripts/check_geo_integrity.py` 로 보고만 하고 사람이
참조를 확인한 뒤 지운다.

앱 코드나 shapely 에 의존하지 않는다. 마이그레이션은 앱보다 먼저 도는 자리라
모델 import 는 스키마가 앞서 나갔을 때 깨지고, shapely 는 설치 보장이 없다.
포함 판정은 ray casting 으로 직접 한다(turf 의 열린 링 함정도 자연히 피한다).

멱등이다. 두 번 돌려도 두 번째는 바꿀 것이 없다.

Revision ID: p6_21_geo_shape_type_repair_20260803
Revises: p6_20_api_key_position_20260802
Create Date: 2026-08-03
"""
import json
import logging

import sqlalchemy as sa
from alembic import op

revision = 'p6_21_geo_shape_type_repair_20260803'
down_revision = 'p6_20_api_key_position_20260802'
branch_labels = None
depends_on = None

logger = logging.getLogger('alembic.runtime.migration')

# aot_type 으로 인정하는 값. 오타나 프런트가 실험적으로 넣은 값을 type 컬럼에
# 그대로 옮겨 담지 않기 위한 화이트리스트다.
VALID_TYPES = {
    'site', 'zone', 'facility', 'facility_bay', 'aot_device', 'device',
    'label_aux', 'equipment', 'equipment_collection', 'feature',
}

# map_overlay_id 를 가진 테이블 전부. 하나라도 빠뜨리면 그 테이블의 끊어진
# 참조가 조용히 남는다.
LINK_TABLES = ('input', 'output', 'pid', 'trigger', 'conditional',
               'custom_controller', 'function')


def _table_exists(insp, name):
    try:
        return name in insp.get_table_names()
    except Exception:
        return False


def _column_exists(insp, table, column):
    try:
        return column in [c['name'] for c in insp.get_columns(table)]
    except Exception:
        return False


def _load_feature(raw):
    """feature 컬럼을 dict 로. SQLite 는 JSON 을 문자열로 돌려주기도 한다."""
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except (ValueError, TypeError):
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _outer_rings(geom):
    """Polygon / MultiPolygon 의 바깥 링들을 [[x, y], ...] 목록으로."""
    if not isinstance(geom, dict):
        return []
    gtype, coords = geom.get('type'), geom.get('coordinates')
    if not coords:
        return []
    try:
        if gtype == 'Polygon':
            return [coords[0]]
        if gtype == 'MultiPolygon':
            return [poly[0] for poly in coords if poly]
    except (IndexError, TypeError):
        return []
    return []


def _point_in_ring(x, y, ring):
    """Ray casting. 링이 닫혀 있든 열려 있든 동작한다."""
    inside = False
    n = len(ring)
    if n < 3:
        return False
    j = n - 1
    for i in range(n):
        try:
            xi, yi = float(ring[i][0]), float(ring[i][1])
            xj, yj = float(ring[j][0]), float(ring[j][1])
        except (TypeError, ValueError, IndexError):
            j = i
            continue
        if (yi > y) != (yj > y):
            denom = (yj - yi) or 1e-18
            if x < (xj - xi) * (y - yi) / denom + xi:
                inside = not inside
        j = i
    return inside


def _contains(geom, x, y):
    return any(_point_in_ring(x, y, ring) for ring in _outer_rings(geom))


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)

    if not _table_exists(insp, 'geo_shape'):
        logger.info('P6-21: geo_shape 테이블이 없어 건너뜀.')
        return

    shapes = bind.execute(sa.text(
        'SELECT id, geo_id, device_id, type, feature FROM geo_shape')).fetchall()
    if not shapes:
        logger.info('P6-21: 도형이 없어 건너뜀.')
        return

    # ── 1) type 을 properties.aot_type 에 맞춘다 ────────────────────────
    retyped = 0
    parsed = {}
    for row in shapes:
        feature = _load_feature(row.feature)
        parsed[row.id] = feature
        aot_type = (feature.get('properties') or {}).get('aot_type')
        if (aot_type and aot_type in VALID_TYPES and aot_type != row.type):
            bind.execute(
                sa.text('UPDATE geo_shape SET type = :t WHERE id = :i'),
                {'t': aot_type, 'i': row.id})
            retyped += 1
    logger.info('P6-21: type 정합 %d건.', retyped)

    # ── 2) 끊어진 map_overlay_id 를 좌표로 다시 연결 ────────────────────
    # 장치 마커: 같은 지도에 놓인 Point 도형. device_id 로 장치와 이어진다.
    markers = {}          # device_id -> (geo_id, x, y)
    for row in shapes:
        if not row.device_id:
            continue
        geom = parsed.get(row.id, {}).get('geometry') or {}
        if geom.get('type') != 'Point':
            continue
        coords = geom.get('coordinates') or []
        if len(coords) < 2:
            continue
        try:
            markers[row.device_id] = (row.geo_id, float(coords[0]), float(coords[1]))
        except (TypeError, ValueError):
            continue

    # 지도별 site/zone 후보. type 정합을 이미 끝냈으므로 여기서는 갱신된
    # 값을 써야 한다 — parsed 의 aot_type 으로 판단한다.
    containers = {}       # geo_id -> [(shape_id, kind, geometry), ...]
    for row in shapes:
        feature = parsed.get(row.id, {})
        kind = (feature.get('properties') or {}).get('aot_type') or row.type
        if kind not in ('site', 'zone'):
            continue
        containers.setdefault(row.geo_id, []).append(
            (row.id, kind, feature.get('geometry') or {}))

    live_ids = {row.id for row in shapes}
    relinked = 0
    for table in LINK_TABLES:
        if not _table_exists(insp, table):
            continue
        if not _column_exists(insp, table, 'map_overlay_id'):
            continue
        rows = bind.execute(sa.text(
            f'SELECT unique_id, map_overlay_id FROM "{table}" '
            'WHERE map_overlay_id IS NOT NULL')).fetchall()
        for row in rows:
            if row.map_overlay_id in live_ids:
                continue                     # 멀쩡한 링크는 건드리지 않는다
            marker = markers.get(row.unique_id)
            if not marker:
                continue                     # 지도에 안 놓인 장치 — 추측하지 않는다
            geo_id, x, y = marker
            best = None
            for shape_id, kind, geom in containers.get(geo_id, ()):
                if not _contains(geom, x, y):
                    continue
                # 겹치면 zone 이 site 를 이긴다 (find_containing_shape 와 동일)
                if best is None or (kind == 'zone' and best[1] == 'site'):
                    best = (shape_id, kind)
            if best is None:
                continue                     # 감싸는 도형 없음 — 그대로 둔다
            bind.execute(
                sa.text(f'UPDATE "{table}" SET map_overlay_id = :m '
                        'WHERE unique_id = :u'),
                {'m': best[0], 'u': row.unique_id})
            relinked += 1
    logger.info('P6-21: 끊어진 zone/site 소속 %d건 복구.', relinked)

    if retyped or relinked:
        logger.info('P6-21: 완료 — type %d건, 소속 %d건. 남은 중복 도형은 '
                    'aot/scripts/check_geo_integrity.py 로 확인할 것.',
                    retyped, relinked)


def downgrade():
    """되돌리지 않는다.

    이 마이그레이션은 스키마가 아니라 어긋난 데이터를 고친다. 되돌린다는 것은
    도형을 다시 보이지 않게 만들고 장치를 다시 zone 에서 떼어낸다는 뜻이라
    복원이 아니라 재고장이다. 옛 값이 필요하면 업그레이드 전 DB 백업을 쓴다.
    """
    pass
