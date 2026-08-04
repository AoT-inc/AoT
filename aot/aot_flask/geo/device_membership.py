# coding=utf-8
"""장치 ↔ zone/site 소속의 단일 리졸버 — 저장하지 않고 파생한다.

과거에는 소속을 7개 모델의 `map_overlay_id` 컬럼에 저장했다. 그 컬럼은
완전히 유도 가능한 값(마커 좌표 → 그 지도에서 좌표를 감싸는 site/zone)
인데도 물질화돼 있어서, 복제가 남의 지도 링크를 복사하고, zone 재생성이
참조를 끊고, 도형 삭제가 고아를 남겼다(2026-08-03 사고 — aot-004 에서
밸브 16개가 존재하지 않는 도형을 가리켰다). 저장하지 않으면 이 오염
계열 전체가 성립하지 않는다: 복사할 것도, 끊길 것도, 빠뜨릴 것도 없다.

파생의 입력은 장치 위치 마커(GeoShape type='aot_device')이며, 마커의
유일성은 DB 계층(I2 부분 유니크 인덱스, p6_22)이 보장한다 — 오염된
입력 위의 계산이 아니다.

규칙은 find_containing_shape 와 동일하다: 겹치면 zone 이 site 를 이긴다.
컨테이너 후보는 Polygon/MultiPolygon 기하의 site/zone 도형뿐이다.

이 모듈이 소속 판정의 유일한 정본이다. map_overlay_id 를 새로 읽거나
쓰는 코드를 추가하지 말 것 — 컬럼은 사망 상태이며 추후 마이그레이션에서
제거된다. (docs/design/geo-data-integrity.md S3)
"""
import json
import logging

from aot.databases.models import GeoShape

logger = logging.getLogger(__name__)

# 마커로 인정하는 도형 종류. 레거시 'device' 점 마커는 p6_21 정합으로
# 전부 'aot_device' 가 됐지만, 미적용 설치를 위해 방어적으로 포함한다.
_MARKER_TYPES = ('aot_device', 'device')
_CONTAINER_TYPES = ('site', 'zone')


def _feature(shape):
    f = shape.feature
    if isinstance(f, str):
        try:
            f = json.loads(f)
        except (ValueError, TypeError):
            return {}
    return f if isinstance(f, dict) else {}


def _marker_point(shape):
    geom = _feature(shape).get('geometry') or {}
    if geom.get('type') != 'Point':
        return None
    coords = geom.get('coordinates') or []
    if len(coords) < 2:
        return None
    try:
        return float(coords[0]), float(coords[1])   # (lng, lat)
    except (TypeError, ValueError):
        return None


def load_containers(map_uuid):
    """지도의 site/zone 컨테이너를 [(shape, kind, shapely_polygon)] 로.

    shapely 를 쓰되(백엔드 포함 판정의 기존 표준), 실패한 기하는 조용히
    빼는 대신 로그를 남긴다 — 침묵 실패가 이 도메인의 고질병이었다.
    """
    from shapely.geometry import shape as shapely_shape

    out = []
    rows = GeoShape.query.filter(
        GeoShape.geo_id == map_uuid,
        GeoShape.type.in_(_CONTAINER_TYPES)).all()
    for s in rows:
        geom = _feature(s).get('geometry') or {}
        if geom.get('type') not in ('Polygon', 'MultiPolygon'):
            continue
        try:
            out.append((s, s.type, shapely_shape(geom)))
        except Exception as exc:
            logger.warning('membership: %s 도형(id=%s) 기하 해석 실패 — '
                           '포함 판정에서 제외: %s', s.type, s.id, exc)
    return out


def _best_container(point, containers):
    """zone 이 site 를 이긴다 (find_containing_shape 와 동일 규칙)."""
    from shapely.geometry import Point

    p = Point(point[0], point[1])
    best = None
    for s, kind, poly in containers:
        try:
            if not poly.contains(p):
                continue
        except Exception:
            continue
        if best is None or (kind == 'zone' and best[1] == 'site'):
            best = (s, kind)
    return best[0] if best else None


def membership_for_map(map_uuid):
    """{device_id: 감싸는 site/zone GeoShape} — 지도 단위 일괄 파생.

    collect_devices 같은 핫패스용. 컨테이너를 한 번만 준비해 마커 수 ×
    컨테이너 수 비교로 끝낸다.
    """
    containers = load_containers(map_uuid)
    if not containers:
        return {}
    result = {}
    markers = GeoShape.query.filter(
        GeoShape.geo_id == map_uuid,
        GeoShape.device_id.isnot(None),
        GeoShape.type.in_(_MARKER_TYPES)).all()
    for m in markers:
        pt = _marker_point(m)
        if not pt:
            continue
        container = _best_container(pt, containers)
        if container is not None:
            result[m.device_id] = container
    return result


def zone_for_device(device_unique_id, map_uuid):
    """장치 하나의 소속 site/zone GeoShape (없으면 None)."""
    marker = GeoShape.query.filter(
        GeoShape.geo_id == map_uuid,
        GeoShape.device_id == device_unique_id,
        GeoShape.type.in_(_MARKER_TYPES)).first()
    if marker is None:
        return None
    pt = _marker_point(marker)
    if not pt:
        return None
    return _best_container(pt, load_containers(map_uuid))


def device_ids_in_shape(shape):
    """도형(site/zone) 폴리곤 안에 마커가 있는 device_id 집합.

    site 폴리곤은 내부 zone 들을 기하학적으로 포함하므로, site 에 대해
    호출하면 하위 zone 의 장치까지 자연히 포함된다 — 별도의 계층 순회가
    필요 없다.
    """
    from shapely.geometry import Point, shape as shapely_shape

    geom = _feature(shape).get('geometry') or {}
    if geom.get('type') not in ('Polygon', 'MultiPolygon'):
        return set()
    try:
        poly = shapely_shape(geom)
    except Exception as exc:
        logger.warning('membership: 도형 id=%s 기하 해석 실패: %s',
                       shape.id, exc)
        return set()

    result = set()
    markers = GeoShape.query.filter(
        GeoShape.geo_id == shape.geo_id,
        GeoShape.device_id.isnot(None),
        GeoShape.type.in_(_MARKER_TYPES)).all()
    for m in markers:
        pt = _marker_point(m)
        if not pt:
            continue
        try:
            if poly.contains(Point(pt[0], pt[1])):
                result.add(m.device_id)
        except Exception:
            continue
    return result


def maps_for_device(device_unique_id):
    """장치가 배치된 지도 uuid 목록 (배치 순서: geo_shape.id 오름차순).

    한 장치가 여러 지도에 마커를 가질 수 있다 — 같은 밸브를 전체 지도와
    구역 지도 양쪽에 놓는 식이다. 그래서 목록을 돌려준다.
    """
    rows = GeoShape.query.filter(
        GeoShape.device_id == device_unique_id,
        GeoShape.type.in_(_MARKER_TYPES)).order_by(GeoShape.id).all()
    seen, out = set(), []
    for r in rows:
        if r.geo_id and r.geo_id not in seen:
            seen.add(r.geo_id)
            out.append(r.geo_id)
    return out


def map_for_device(device_unique_id, prefer=None):
    """장치가 배치된 대표 지도 uuid (없으면 None).

    `map_config_id` 컬럼을 읽던 자리를 대체하는 파생값이다. 컬럼이 단일
    값이었으므로 여기서도 하나를 고른다.

    `prefer` 는 전환기의 안전장치다. 같은 장치가 여러 지도에 마커를 갖는
    경우(미사용 복사본 지도에 옛 마커가 남아 있는 등) 단순히 "첫 배치"를
    고르면 사용자가 실제로 쓰는 지도가 아니라 오래된 사본을 고를 수 있다 —
    koat 실측에서 28건이 그랬다(`Copy of KMA ...` 가 김제보다 먼저 생성).
    그래서 호출자가 기존 `map_config_id` 를 힌트로 넘기면, **그것이 실제
    배치 목록에 있을 때만** 채택한다. 정본은 여전히 배치다: 배치에 없는
    힌트는 무시하고, 힌트가 없으면 첫 배치로 간다.

    P4 에서 미사용 사본 지도를 정리하면 다중 배치가 사라지고, P5 에서
    컬럼을 드롭할 때 이 인자도 함께 제거한다.

    미배치 장치는 None 이다. "어느 지도에도 없다"가 정답이며, 과거처럼
    모든 지도에 나타나게 하지 않는다(원칙 3).
    """
    maps = maps_for_device(device_unique_id)
    if not maps:
        return None
    if prefer and prefer in maps:
        return prefer
    return maps[0]


def devices_on_map(map_uuid):
    """지도에 배치된 장치 uuid 집합. `map_config_id == uuid` 조회의 대체."""
    rows = GeoShape.query.filter(
        GeoShape.geo_id == map_uuid,
        GeoShape.device_id.isnot(None),
        GeoShape.type.in_(_MARKER_TYPES)).all()
    return {r.device_id for r in rows if r.device_id}
