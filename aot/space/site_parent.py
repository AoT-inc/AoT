# coding=utf-8
"""도형이 속한 site(필지) 찾기와 도형 이름 (아키텍처 4c-1, `docs/design/space-domain-package.md`).

필지 요약(`aot.aot_flask.geo.site_summary`)에 있던 함수를 그대로 옮겼다. 예보 계열
(`forecast_series`)도 상위 필지를 찾는데, 필지 요약 모듈은 웹에 남는다. 그래서
`GeoShape`·`geo_hierarchy` 만 쓰는 이 부분만 공간 도메인으로 내린다.

필지 요약은 이 모듈의 잠금(`_CACHE_LOCK`)과 부모 색인 캐시(`_PARENT_CACHE`)를
**같은 객체로** 가져가 자기 캐시와 함께 쓴다 — `site_summary.invalidate()` 가 같은
잠금 아래에서 이 캐시를 비운다. 사본을 만들면 무효화가 조용히 빗나간다.
"""
import logging
import threading
import time

logger = logging.getLogger(__name__)

_CACHE_LOCK = threading.Lock()

_PARENT_CACHE = {}
_PARENT_TTL_S = 60


def parent_site_for_shape(shape_uuid):
    """도형이 속한 site — `{'uuid', 'name'}` 또는 None.

    구역·시설 모달의 "상위로" 화살표가 쓴다. 한 단계 위가 아니라 **site 가
    나올 때까지 거슬러 올라간다** — 구역 안에 놓인 시설은 부모가 구역이고,
    그 위가 필지다.

    `parent_id` 컬럼은 운영 데이터에서 site/zone 전 행이 NULL 이라
    (geo_hierarchy 모듈 주석) 공간 포함 관계로 푸는 build_geo_parent_map 을
    쓴다. 그 계산이 지도 도형 전량을 shapely 로 훑으므로 지도 단위로 캐시한다.
    """
    from aot.databases.models import GeoShape

    shape = GeoShape.query.filter_by(unique_id=shape_uuid).first()
    if shape is None:
        return None
    if shape.type == 'site':
        return None      # 자기 자신이 필지 — 올라갈 곳이 없다

    index = _parent_index(shape.geo_id)
    if index is None:
        return None
    parent_map, by_id = index

    current, seen = shape.id, set()
    while current is not None and current not in seen:
        seen.add(current)
        current = parent_map.get(current)
        node = by_id.get(current) if current is not None else None
        if node is not None and node.type == 'site':
            return {'uuid': node.unique_id, 'name': _shape_name(node)}
    return None


def _parent_index(map_uuid):
    """(parent_map, by_id) — 지도 단위 60초 캐시. 실패하면 None."""
    from aot.databases.models import GeoShape
    from aot.utils.geo_hierarchy import build_geo_parent_map

    now = time.time()
    with _CACHE_LOCK:
        hit = _PARENT_CACHE.get(map_uuid)
    if hit and hit[0] > now:
        return hit[1]

    try:
        shapes = GeoShape.query.filter(GeoShape.geo_id == map_uuid).all()
        index = (build_geo_parent_map(shapes), {s.id: s for s in shapes})
    except Exception as exc:
        logger.warning('[SiteSummary] 계층 색인 실패(map=%s): %s', map_uuid, exc)
        return None

    with _CACHE_LOCK:
        _PARENT_CACHE[map_uuid] = (now + _PARENT_TTL_S, index)
    return index


def _facility_of_shape(shape_uuid):
    """도형 uuid → `GeoFacility` (없으면 None).

    시설 모달은 `GeoFacility` 로 열린다. 이 행이 없으면 도형이 있어도 열
    대상이 없다 — 목록에 넣을지 정하는 근거이자, 이름을 찾는 자리이기도 하다
    (시설 이름은 도형이 아니라 이 행에 있다).
    """
    try:
        from aot.databases.models import GeoFacility
        return GeoFacility.query.filter_by(shape_uuid=shape_uuid).first()
    except Exception:                                       # noqa: BLE001
        return None


def _shape_name(shape):
    props = _feature(shape).get('properties') or {}
    name = props.get('label_name') or props.get('name')
    if name:
        return name

    # **시설은 이름이 도형이 아니라 `GeoFacility` 에 있다.** 시설 편집기에서
    # 만든 시설의 외곽 도형은 `properties.name` 이 비어 있는 것이 정상이고,
    # 그대로 두면 목록에 uuid 가 그대로 찍힌다("e05c9d51-093f-…"). 필지 요약의
    # [구성] 탭이 시설을 따로 세우면서 드러났다 — 그전에는 구역과 섞여 있어
    #     눈에 덜 띄었을 뿐 같은 값이었다.
    if getattr(shape, 'type', None) == 'facility':
        fac = _facility_of_shape(shape.unique_id)
        if fac is not None and fac.name:
            return fac.name
    return shape.unique_id


def _feature(shape):
    import json

    raw = shape.feature
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (ValueError, TypeError):
            return {}
    return raw if isinstance(raw, dict) else {}
