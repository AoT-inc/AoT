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

겹치는 후보 사이의 동점 규칙은 `aot.utils.geo_hierarchy.pick_smallest_container()`
하나가 정본이다(가장 작은 면적 = 가장 구체적인 것이 이긴다, site/zone 구분
없이). `find_containing_shape` 도 같은 함수를 쓴다. 컨테이너 후보는
Polygon/MultiPolygon 기하의 site/zone 도형뿐이다.

이 모듈이 소속 판정의 유일한 정본이다. map_overlay_id 를 새로 읽거나
쓰는 코드를 추가하지 말 것 — 컬럼은 사망 상태이며 추후 마이그레이션에서
제거된다. (docs/design/geo-data-integrity.md S3)
"""
import json
import logging
import re
from collections import namedtuple

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


# @manual geo/design-tool#zone
def _best_container(point, containers):
    """겹치는 site/zone 후보 중 가장 작은(가장 구체적인) 것이 이긴다.

    동점 규칙은 `geo_hierarchy.pick_smallest_container()` 하나가 정본이다
    (`find_containing_shape` 도 같은 함수를 쓴다). 예전에는 "zone 이 site
    를 이기되, zone 끼리 겹치면 `load_containers()` 가 먼저 돌려준 쪽" 이었다
    — 그 쿼리에는 `order_by` 가 없어 순서가 기하가 아니라 DB 반환 순서였고,
    zone 끼리 겹치는 지도(김제 site '3포장' 등)에서는 `geo_hierarchy` 쪽
    (면적 기준)과 다른 답을 냈다(`aot/tests/geo/test_geo_overlap_containment_tiebreak.py`
    실증). zone 끼리 겹치지 않으면(zone 이 보통 site 보다 작으므로) 결과는
    이전과 동일하다.
    """
    from shapely.geometry import Point

    from aot.utils.geo_hierarchy import pick_smallest_container

    p = Point(point[0], point[1])
    candidates = [(s, poly, getattr(poly, 'area', 0.0) or 0.0)
                 for s, kind, poly in containers]
    return pick_smallest_container(p, candidates)


# @manual geo/design-tool#zone
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


def load_markers(map_uuid):
    """지도의 장치 마커를 `[(device_id, (lng, lat))]` 로 — 반복 호출용 사전 로드.

    `load_containers` 와 같은 목적이다. 구획 목록처럼 같은 지도에 대해 폴리곤
    판정을 N번 도는 자리에서, 마커 전량 조회가 N번 반복되지 않도록 한 번만
    읽어 넘긴다.
    """
    out = []
    rows = GeoShape.query.filter(
        GeoShape.geo_id == map_uuid,
        GeoShape.device_id.isnot(None),
        GeoShape.type.in_(_MARKER_TYPES)).all()
    for m in rows:
        pt = _marker_point(m)
        if pt and m.device_id:
            out.append((m.device_id, pt))
    return out


def marker_points(map_uuid):
    """지도의 위치 마커 → `[(shape_uuid, (lng, lat))]` — 장치는 묻지 않는다.

    과거 기간을 조합하는 쪽(`plot_sources`)은 "어느 장치였나" 를 바인딩 이력
    에서 따로 구한다. 여기서 장치 컬럼까지 읽으면 지금 값 하나가 과거 기간에
    덮어씌워진다 — 그 결함을 없애려는 조회다.
    """
    out = []
    rows = GeoShape.query.filter(
        GeoShape.geo_id == map_uuid,
        GeoShape.type.in_(_MARKER_TYPES)).all()
    for m in rows:
        pt = _marker_point(m)
        if pt and m.unique_id:
            out.append((m.unique_id, pt))
    return out


def legacy_marker_devices(map_uuid):
    """바인딩 이력이 전혀 없는 마커의 장치 → `{shape_uuid: device_id}`.

    백필 전 설치에서만 쓰이는 폴백이다(`device_binding` 의 레거시 폴백과 같은
    성격). 이 값은 **지금** 장치 하나라 기간을 말하지 못한다 — 호출자는 그
    마커를 "처음부터 지금까지" 로만 읽어야 한다.
    """
    rows = GeoShape.query.filter(
        GeoShape.geo_id == map_uuid,
        GeoShape.device_id.isnot(None),
        GeoShape.type.in_(_MARKER_TYPES)).all()
    return {m.unique_id: str(m.device_id).split('::')[0] for m in rows
            if m.unique_id}


def zone_for_device(device_unique_id, map_uuid):
    """장치 하나의 소속 site/zone GeoShape (없으면 None).

    마커는 정본(`device_binding.shapes_for_device` — 바인딩 우선, 없으면 레거시
    컬럼)으로 찾고, 그중 **이 지도의 점**만 쓴다. 예전에는 `type in ('aot_device',
    'device')` 를 순서 없이 `.first()` 로 집었는데 'device' 는 장치 **영역
    폴리곤**이기도 해서, 그것이 먼저 오면 점이 없어 소속이 통째로 비었다
    (2026-10-08). 장소 경로(`PlaceIndex.device_paths`)와 같은 출처다.
    """
    from aot.aot_flask.geo.device_binding import shapes_for_device

    markers = sorted(
        (sh for sh in shapes_for_device(device_unique_id)
         if sh.geo_id == map_uuid and sh.type in _MARKER_TYPES),
        key=lambda sh: sh.id or 0)
    for marker in markers:
        pt = _marker_point(marker)
        if pt:
            return _best_container(pt, load_containers(map_uuid))
    return None


def container_for_geometry(map_uuid, geom, containers=None):
    """폴리곤을 감싸는 site/zone GeoShape (없으면 None).

    판정은 **대표점** 기준이다 — 구획이 zone 경계를 살짝 넘거나 두 zone 에
    걸친 경우에도 답이 하나로 정해져야 하고, 면적 교차 최대로 정하면 경계를
    조금 손볼 때마다 소속이 튄다. `representative_point()` 는 오목한 폴리곤
    에서도 반드시 내부에 있다(centroid 는 밖으로 나갈 수 있다).

    `containers` 를 넘기면 재사용한다 — 여러 구획을 한 번에 처리할 때
    지도 도형 전량 스캔이 반복되지 않도록.
    """
    from shapely.geometry import shape as shapely_shape

    from aot.utils.geo_hierarchy import containment_point

    geom = geom or {}
    if geom.get('type') not in ('Polygon', 'MultiPolygon'):
        return None
    try:
        pt = containment_point(shapely_shape(geom))
    except Exception as exc:
        logger.warning('membership: 기하 해석 실패(컨테이너 판정): %s', exc)
        return None
    if pt is None:
        return None
    if containers is None:
        containers = load_containers(map_uuid)
    return _best_container((pt.x, pt.y), containers)


def site_for_geometry(map_uuid, geom, containers=None):
    """폴리곤을 감싸는 **site** GeoShape (없으면 None) — zone 안에 있어도 그
    zone 을 감싸는 site 까지 올라간다.

    `container_for_geometry` 는 zone 이 site 를 이기므로, zone 안의 구획은
    그 결과만으로 site 를 알 수 없다(zone 이 나온다). 필터 화면이 "site"와
    "zone"을 별개 축으로 보이려면 이 둘을 각자 구해야 한다 — site 후보만
    남기고 같은 대표점으로 다시 판정한다.
    """
    from shapely.geometry import shape as shapely_shape

    from aot.utils.geo_hierarchy import containment_point

    geom = geom or {}
    if geom.get('type') not in ('Polygon', 'MultiPolygon'):
        return None
    try:
        pt = containment_point(shapely_shape(geom))
    except Exception as exc:
        logger.warning('membership: 기하 해석 실패(site 판정): %s', exc)
        return None
    if pt is None:
        return None
    if containers is None:
        containers = load_containers(map_uuid)
    # 대지가 겹치면(대지 안의 대지) 동점 규칙은 정본 하나 — 가장 작은 것이
    # 이긴다. 예전에는 `load_containers` 가 먼저 돌려준 대지(DB 순서)를 골라,
    # 같은 구획이 화면마다 다른 대지에 묶일 수 있었다(2026-10-08).
    return _best_container((pt.x, pt.y),
                           [c for c in containers if c[1] == 'site'])


def device_ids_in_geometry(map_uuid, geom, _label='geometry', markers=None):
    """임의 폴리곤 안에 마커가 있는 device_id 집합.

    `markers` 를 넘기면(`load_markers` 결과) 마커 전량 조회를 생략한다 — 같은
    지도에서 여러 폴리곤을 판정할 때 조회가 폴리곤 수만큼 반복되지 않도록.

    `device_ids_in_shape` 의 알맹이. GeoShape 행이 아닌 기하로도 물어야 하는
    소비처가 있어서 분리했다 — 식생 구획(GeoPlot)은 GeoShape 가 아니지만
    "이 폴리곤 안의 센서" 라는 질문은 완전히 같다
    (docs/design/geo-vegetation-plot.md §센서 참조 계약).

    ⚠ 이 함수는 **참조**를 답할 뿐 소속을 정하지 않는다. 소속 판정의 컨테이너
    목록(`_CONTAINER_TYPES`)에 식생 구획 같은 단명 대상을 추가하지 말 것 —
    "겹치면 zone 이 site 를 이긴다" 규칙에 끼어들면 장치의 소속이 작기마다
    바뀌고, 작기가 끝나는 순간 그 장치가 무소속이 된다.
    """
    from shapely.geometry import Point, shape as shapely_shape

    geom = geom or {}
    if geom.get('type') not in ('Polygon', 'MultiPolygon'):
        return set()
    try:
        poly = shapely_shape(geom)
    except Exception as exc:
        logger.warning('membership: %s 기하 해석 실패: %s', _label, exc)
        return set()

    result = set()
    if markers is None:
        markers = load_markers(map_uuid)
    for device_id, pt in markers:
        try:
            if poly.contains(Point(pt[0], pt[1])):
                result.add(device_id)
        except Exception:
            continue
    return result


def device_ids_in_shape(shape, markers=None):
    """도형(site/zone) 폴리곤 안에 마커가 있는 device_id 집합.

    site 폴리곤은 내부 zone 들을 기하학적으로 포함하므로, site 에 대해
    호출하면 하위 zone 의 장치까지 자연히 포함된다 — 별도의 계층 순회가
    필요 없다.
    """
    return device_ids_in_geometry(
        shape.geo_id, _feature(shape).get('geometry'),
        _label='도형 id=%s' % shape.id, markers=markers)


def area_choices():
    """필터용 필지·구역 목록 — `[{'value','item','kind'}]`, 종류별로 묶어 쓴다.

    **필지(site)와 구역(zone)을 한 덩어리로 내보내면 안 된다.** 이름순으로
    섞으면 '1-1'~'1-9' 같은 구역이 위를 다 차지하고 필지는 아래로 밀려, 화면만
    보고는 필지가 아예 없는 줄 안다(실제로 그렇게 보고받았다). 호출자가
    optgroup 으로 가를 수 있도록 `kind` 를 함께 준다.

    이름이 없는 도형은 뺀다. 목록에서 고르는 수단은 이름뿐이라 `(site 1)`
    같은 자리표시를 넣어 봐야 사용자가 그것이 무엇인지 알 방법이 없고, 로컬
    실측에서 12개나 되어 정작 이름 있는 필지를 목록 아래로 밀어냈다.

    같은 이름의 구역이 여러 지도에 있는 것은 정상이므로(1-1 하우스는 농장마다
    있다) 지도 이름을 함께 보여준다.

    **고를 것이 아무것도 없는 구역은 내보내지 않는다.** 로컬 실측에서 36개 중
    25개가 장치도 노트도 없었는데, 그런 항목을 고르면 모든 목록이 통째로 비어
    사용자는 "필터가 고장났다"로 읽는다. 측정값 없는 복합장치를 빼는 것과 같은
    이유다. 판정은 마커·바인딩·노트만 보는 싼 것으로 한다 — 참조(PID·함수)는
    이미 걸린 장치가 있어야 성립하므로 비어 있음 판정을 뒤집지 못한다.
    """
    from aot.databases.models import GeoMap

    maps = {m.unique_id: (m.name or '') for m in GeoMap.query.all()}
    rows = GeoShape.query.filter(
        GeoShape.type.in_(_CONTAINER_TYPES)).order_by(GeoShape.id).all()

    out = []
    for shape in rows:
        props = (_feature(shape).get('properties') or {})
        name = (props.get('label_name') or props.get('name') or '').strip()
        if not name:
            continue
        if not _area_has_anything(shape):
            continue
        where = maps.get(shape.geo_id) or ''
        out.append({'value': shape.unique_id,
                    'kind': shape.type,
                    # ⚠ `item` 은 **그대로 둔다** — 그래프 픽커
                    # (`routes_page.py`)와 기존 테스트가 이 합쳐진 문자열을
                    # 쓴다. 아래 둘은 **순수 추가**다: 지도명을 그룹 머리로
                    # 쓰려면(일지 허브) 합쳐진 라벨에서 되짚을 수 없기 때문.
                    'map_name': where,
                    'shape_name': name,
                    'item': ('%s · %s' % (where, name)) if where else name})
    out.sort(key=lambda o: o['item'])
    return out


def _area_has_anything(shape):
    """이 구역을 골랐을 때 화면에 뭐라도 남는가 — 싼 판정.

    장치가 없어도 노트가 있으면 고를 값이 있다("3-2 구역의 기록만 보기").
    둘 다 없으면 고르는 순간 모든 목록이 빈다.
    """
    from aot.databases.models import Notes

    inside = {sh.unique_id for sh in _shapes_inside(shape)}
    inside.add(shape.unique_id)
    if device_ids_in_shape(shape) or _bound_device_ids(inside):
        return True

    # 공간에 붙은 노트. 좌표로만 찍힌 노트는 여기서 보지 않는다 — 그것까지
    # 보려면 폴리곤 판정을 한 번 더 돌려야 하고, 로컬 실측에서 2건뿐이라
    # 목록을 두 배로 느리게 만들 값이 아니다.
    return Notes.query.filter(
        Notes.target_id.in_(facility_identity_ids(inside))).first() is not None


def _shapes_inside(area_shape):
    """구역 폴리곤 안에 있는 같은 지도의 도형들(자기 자신 포함).

    판정은 대표점(representative point)으로 한다. 완전 포함을 요구하면 경계에
    걸친 시설이 빠지고, 교차를 허용하면 옆 구역이 딸려 온다.
    """
    from shapely.geometry import shape as shapely_shape

    from aot.utils.geo_hierarchy import containment_point

    geom = _feature(area_shape).get('geometry') or {}
    if geom.get('type') not in ('Polygon', 'MultiPolygon'):
        return []
    try:
        poly = shapely_shape(geom)
    except Exception:
        return []

    out = []
    for other in GeoShape.query.filter(
            GeoShape.geo_id == area_shape.geo_id).all():
        if other.unique_id == area_shape.unique_id:
            out.append(other)
            continue
        g = _feature(other).get('geometry') or {}
        if not g.get('type'):
            continue
        try:
            pt = containment_point(shapely_shape(g))
            if pt is not None and poly.contains(pt):
                out.append(other)
        except Exception:
            continue
    return out


def _bound_device_ids(shape_uuids, include_facility_fittings=True):
    """도형들에 바인딩된 장치 + 그 도형에 놓인 시설의 설비에 바인딩된 장치.

    마커만 보면 안 되는 이유: 로컬 실측에서 출력 16개 중 마커가 있는 것은 1개,
    PID 는 0개다. 마커는 "지도에 점을 찍었다"는 뜻일 뿐이고, 구역을 담당하는
    장치는 보통 구역 폴리곤이나 시설 설비에 매여 있다.

    바인딩은 두 갈래다:

    · `spatial_kind='shape'` — 도형(구역 폴리곤·시설 외형)에 **직접** 맡긴 장치.
    · `spatial_id='<시설>:<설비>'` — 시설 **안의 설비**(측창·도어·관수밸브 …)에
      매인 장치. 시설을 한 겹 더 들어간 것이다.

    `include_facility_fittings=False` 는 뒤엣것을 뺀다. 필지(site) 모달이 그렇게
    부른다 — 필지에서 시설 안의 측창까지 늘어놓으면 "여기서 뭘 볼까"가 아니라
    "여기서 뭘 다 조작할 수 있나"가 되어, 정작 필지 단위로 판단할 것이 묻힌다.
    설비 액추에이터는 그 시설 모달에서 본다. 앞엣것은 어디서든 유지된다 —
    구역에 맡긴 밸브는 구역의 것이 맞다.
    """
    from aot.databases.models import GeoBinding, GeoFacility

    if not shape_uuids:
        return set()

    ids = {b.device_id for b in GeoBinding.query.filter(
        GeoBinding.spatial_kind == 'shape',
        GeoBinding.spatial_id.in_(list(shape_uuids)),
        GeoBinding.valid_to.is_(None)).all()}

    if include_facility_fittings:
        facilities = [f.unique_id for f in GeoFacility.query.filter(
            GeoFacility.shape_uuid.in_(list(shape_uuids))).all()]
        for fac in facilities:
            for b in GeoBinding.query.filter(
                    GeoBinding.spatial_id.like(fac + ':%'),
                    GeoBinding.valid_to.is_(None)).all():
                ids.add(b.device_id)
    return {i for i in ids if i}


def _referencing_device_ids(known):
    """이미 구역 안이라고 판정된 장치들을 **참조하는** PID·함수.

    PID 는 자기 마커를 갖는 일이 거의 없다(로컬 2개 중 0개). 그런데 그 PID 가
    읽는 센서와 움직이는 출력이 이 구역 안이면, 그 PID 는 이 구역의 것이다 —
    마커만 보면 구역을 고르는 순간 PID 목록이 통째로 비고, 사용자는 "필터가
    고장났다"로 읽는다.

    함수(CustomController)의 참조는 custom_options JSON 에 자유 형식으로
    들어 있어 스키마가 없다. 그래서 값 안에서 uuid 를 훑어 맞춰 본다 —
    정밀하지는 않지만 빠뜨리는 쪽보다 낫고, 남의 구역 것을 끌어오려면 그
    함수가 실제로 그 장치를 가리키고 있어야 한다.
    """
    import json as _json

    from aot.databases.models import CustomController, PID

    if not known:
        return set()

    extra = set()
    for pid in PID.query.all():
        refs = {(pid.measurement or '').split(',')[0],
                pid.raise_output_id or '', pid.lower_output_id or ''}
        if refs & known:
            extra.add(pid.unique_id)

    for fn in CustomController.query.all():
        raw = fn.custom_options or ''
        if not raw:
            continue
        try:
            blob = _json.dumps(_json.loads(raw))
        except Exception:
            blob = raw
        if any(dev in blob for dev in known):
            extra.add(fn.unique_id)
    return extra


# @manual geo/map-widget#click-a-zonesite-control-from-a-device-list
def device_ids_in_area(shape_uuid, include_facility_fittings=True,
                       include_references=True):
    """구역/필지 uuid → 그 안에 속한 장치 id 집합. 도형을 못 찾으면 None.

    None 은 "아무것도 없다"가 아니라 **"거르지 않는다"** 이다 — 둘을 같은
    값으로 접으면 지워진 구역을 필터로 들고 있을 때 화면이 텅 빈다.

    소속 판정은 네 겹이다. 하나만 쓰면 목록이 통째로 빈다:

    1. **마커** — 폴리곤 안에 위치 점이 찍힌 장치.
    2. **바인딩** — 그 안의 도형(구역 폴리곤)·시설 설비가 맡긴 장치. 실측상
       이쪽이 훨씬 두껍다(출력 16개 중 마커는 1개뿐이다).
    3. **그릇** — 복합장치가 안에 있으면 그 하위 Input/Output. 하위 장치는
       보통 자기 마커가 없어(그릇만 지도에 놓는다) 1·2 로는 빠지는데, 그러면
       "이 구역의 값"에서 정작 값을 재는 것들이 사라진다.
    4. **참조** — 위에서 모인 장치를 읽거나 움직이는 PID·함수.

    `include_facility_fittings=False` 는 2 겹에서 **시설 안 설비에 매인 것**만
    뺀다(`_bound_device_ids` 주석). 그 장치를 참조하는 PID·함수도 따라서 빠진다 —
    없는 장치를 움직이는 제어기를 목록에 두면 그것대로 읽을 수 없는 화면이 된다.
    """
    from aot.databases.models import Input, Output

    shape = GeoShape.query.filter(GeoShape.unique_id == shape_uuid).first()
    if shape is None:
        return None

    inside = _shapes_inside(shape)
    ids = set(device_ids_in_shape(shape))
    ids |= _bound_device_ids({sh.unique_id for sh in inside},
                             include_facility_fittings=include_facility_fittings)
    ids = {i for i in ids if i}
    if not ids:
        return ids

    for model in (Input, Output):
        rows = model.query.with_entities(model.unique_id).filter(
            model.parent_device_id.in_(ids)).all()
        ids.update(r[0] for r in rows)

    # 4겹(참조 PID·함수)은 PID·함수 전체를 훑는다. 센서만 필요한 자리(구획의
    # 구역 폴백)는 이 단계가 결과에 아무것도 더하지 않으므로 건너뛴다.
    if include_references:
        ids |= _referencing_device_ids(ids)
    return ids


#: **기상원을 알아보는 표식** — 이 measurement 를 하나라도 내면 그 장치는
#: 기상대(실물이든 예보 API 든)로 본다. 판별에만 쓰고, 일단 기상원으로 잡히면
#: **그 장치의 측정값 전부**를 싣는다(실외 온·습도도 참고 값이다).
#:
#: 드라이버 이름으로는 못 가른다 — 실측: API 기상은 `KMA_weather_500`·
#: `OPENWEATHERMAP_*` 처럼 이름이 말해 주지만, 실물 기상대(미러-기상대)는
#: 범용 `MQTT_PAHO_JSON` 이라 같은 규칙에 안 걸린다.
#:
#: ⚠ 좁게 고른다. `speed` 는 팬 회전수일 수 있고 `light` 는 실내 PAR 일 수
#:   있어 표식으로 쓰지 않는다 — 엉뚱한 장치가 기상대로 잡히면 그 장치의
#:   측정값 전부가 실외로 딸려 들어온다. 여기 있는 것들은 **구획이 잴 이유가
#:   없는 것**뿐이다(일사·강우·적설·시정·자외선·방위).
WEATHER_MARKER_MEASUREMENTS = frozenset({
    'radiation', 'precipitation', 'rain', 'snowfall', 'visibility', 'uvi',
    'direction',
})


#: 예보 출처 지정 행(`device_binding.SITE_FORECAST_ROLE`) — 실측 기상대가 아니다. 순환 import 를 피해 값을 둔다.
SITE_FORECAST_ROLE = 'forecast'


def bound_weather_device_ids(shape_uuid):
    """대지에 **지정된** 기상대 장치 id — 지정한 순서대로, 추론은 쓰지 않는다.

    지도 위젯의 기상 표현이 현장 값을 쓸 때의 출처다. 측정값으로 추론한 장치는 엉뚱한 값을
    기상 칸에 올릴 수 있어(`weather_device_ids` 의 `inferred`) 여기서는 빈 목록이다.
    """
    from aot.databases.models import GeoBinding

    if not shape_uuid:
        return []
    try:
        rows = GeoBinding.query.filter(
            GeoBinding.spatial_kind == 'weather',
            GeoBinding.spatial_id == shape_uuid,
            GeoBinding.role != SITE_FORECAST_ROLE,
            GeoBinding.valid_to.is_(None)).order_by(GeoBinding.id).all()
    except Exception:
        logger.exception('[weather] 지정 기상원 조회 실패: %s', shape_uuid)
        return []
    out = []
    for r in rows:
        if r.device_id and r.device_id not in out:
            out.append(r.device_id)
    return out


# @manual geo/map-widget#site-weather
def weather_device_ids(shape_uuid):
    """대지(또는 구역) uuid → `(장치 id 목록, 출처)`.

    출처는 `'bound'`(사람이 지정) | `'inferred'`(측정값으로 추론) | `'none'`.

    ## 왜 두 갈래인가

    일사·강우는 **대지에 하나 있는 기상대**가 재고, 구획마다 따로 재지 않는다.
    그런데 `sensors_for_plot` 의 폴백은 배타적이라(구획 안 → 동 → 시설 → 구역,
    처음 비지 않은 데서 멈춘다) **구획 안에 센서가 하나라도 있으면 대지의
    기상대까지 내려가지 않는다.** 실측: `[관찰] 육묘장 구획` 은 같은 대지에
    미러-기상대(일사·강우·풍향)가 있는데도 온습도 6대만 보고 있었다.

    **지정이 정본이다.** `geo_binding` 의 `spatial_kind='weather'` 행이 있으면
    그것만 쓴다 — 그 role 은 이미 있고(시설이 외기를 읽는 데 쓴다) 여기서는
    `spatial_id` 가 GeoShape 인 것만 다르다.

    **지정이 없으면 추론한다.** 지정 UI 가 생기기 전에도, 그리고 아무도 설정을
    만지지 않은 설치에서도 값이 보여야 하기 때문이다 — `scoping_active()` 가
    grant 0건일 때 판정을 건너뛰는 것과 같은 판단이다. 다만 **어느 규칙이었는지
    호출부가 알 수 있어야 한다**(화면이 "자동으로 찾은 기상대" 라고 말할 수
    있게) — 그래서 출처를 함께 돌려준다.
    """
    from aot.databases.models import DeviceMeasurements, GeoBinding

    if not shape_uuid:
        return [], 'none'

    # ── 1) 사람이 지정한 것 ────────────────────────────────────────────
    try:
        rows = GeoBinding.query.filter(
            GeoBinding.spatial_kind == 'weather',
            GeoBinding.spatial_id == shape_uuid,
            GeoBinding.role != SITE_FORECAST_ROLE,
            GeoBinding.valid_to.is_(None)).all()
        bound = sorted({r.device_id for r in rows if r.device_id})
        if bound:
            return bound, 'bound'
    except Exception:
        logger.exception('[weather] 지정 기상원 조회 실패: %s', shape_uuid)

    # ── 2) 측정값으로 추론 ─────────────────────────────────────────────
    inside = device_ids_in_area(shape_uuid)
    if not inside:
        return [], 'none'
    try:
        marked = DeviceMeasurements.query.with_entities(
            DeviceMeasurements.device_id).filter(
            DeviceMeasurements.device_id.in_(list(inside)),
            DeviceMeasurements.measurement.in_(
                list(WEATHER_MARKER_MEASUREMENTS))).all()
    except Exception:
        logger.exception('[weather] 기상원 추론 실패: %s', shape_uuid)
        return [], 'none'

    found = sorted({r[0] for r in marked if r[0]})
    return (found, 'inferred') if found else ([], 'none')


# @manual geo/map-widget#site-weather
def weather_candidates(shape_uuid):
    """이 대지 안에서 기상대로 **고를 수 있는** 장치 목록.

    반환: `[{'device_id', 'name', 'measurements': [표시명…], 'inferred': bool,
              'selected': bool}, …]` — 추론에 걸린 것이 앞에 온다.

    ⚠ **추론에 걸린 것만 내지 않는다.** 추론 기준은 측정값 이름
    (`WEATHER_MARKER_MEASUREMENTS`)인데, 실외 온습도만 재는 기상대는 그 이름을
    하나도 안 갖는다 — 목록에 없으면 사람은 "지정할 수단이 없다" 로 읽는다.
    지정 화면이 존재하는 이유가 **추론이 틀렸을 때 바로잡는 것**이라, 추론이
    고른 것만 보여 주면 화면이 자기 목적을 배반한다.

    측정값 이름을 함께 내는 것은 고르기 위해서다. 장치 이름만으로는 어느 것이
    기상대인지 알 수 없는 설치가 흔하다(실측: 한 대지에 장치 19대).
    """
    from aot.databases.models import DeviceMeasurements
    from aot.aot_flask.geo.widget.maps import _measurement_display_name

    inside = device_ids_in_area(shape_uuid) or []
    if not inside:
        return []

    selected, source = weather_device_ids(shape_uuid)
    selected_set = set(selected if source == 'bound' else [])

    try:
        rows = DeviceMeasurements.query.filter(
            DeviceMeasurements.device_id.in_(list(inside))).all()
    except Exception:
        logger.exception('[weather] 후보 조회 실패: %s', shape_uuid)
        return []

    by_dev = {}
    for r in rows:
        box = by_dev.setdefault(r.device_id, {'meas': [], 'keys': set(),
                                              'seen': set()})
        if not r.measurement:
            continue
        box['keys'].add(r.measurement)
        # ⚠ **채널이 스스로 붙인 이름이 먼저다.** 측정 어휘의 이름은 물리량이라
        #   `length` 가 '길이' 로 나오는데, 그 채널이 재는 것은 강우다 — 사람이
        #   고를 때 필요한 것은 단위가 아니라 무엇을 재는가다(일지에서 같은
        #   지적을 받아 고친 것과 같은 규칙).
        label = (r.name or '').strip() or _measurement_display_name(
            r.measurement) or r.measurement
        if label in box['seen']:
            continue        # 같은 이름이 두 채널에 있으면 한 번만 적는다
        box['seen'].add(label)
        box['meas'].append(label)

    out = []
    for dev_id, box in by_dev.items():
        name, kind = _device_display_name(dev_id)
        if not name:
            continue        # 실존하지 않는 장치를 고르게 두지 않는다
        if kind == 'output':
            # 출력(밸브·난방기)은 기상을 재지 않는다. 그런데 가동시간·듀티를
            # 측정값으로 갖고 있어 거르지 않으면 목록을 통째로 덮는다
            # (실측: 3포장 19대 중 18대가 밸브였다 — 고를 것 하나가 파묻힌다).
            continue
        out.append({
            'device_id': dev_id,
            'name': name,
            'measurements': box['meas'][:6],
            'inferred': bool(box['keys'] & WEATHER_MARKER_MEASUREMENTS),
            'selected': dev_id in selected_set,
        })

    # 고를 만한 것이 위로. 같은 등급 안에서는 이름순이라 목록이 흔들리지 않는다.
    out.sort(key=lambda d: (not d['selected'], not d['inferred'], d['name']))
    return out


def _device_display_name(device_id):
    """장치 uuid → `(이름, 종류)`. 못 찾으면 `(None, None)`.

    종류가 필요한 이유는 호출부가 출력을 걸러야 하기 때문이다 — 이름만으로는
    밸브와 기상대를 가를 수 없다.
    """
    from aot.databases.models import Input, Output, CustomController
    for model, kind in ((Input, 'input'), (Output, 'output'),
                        (CustomController, 'device')):
        try:
            row = model.query.filter_by(unique_id=device_id).first()
        except Exception:
            continue
        if row is not None:
            return (getattr(row, 'name', None) or device_id[:8], kind)
    return (None, None)


def note_ids_in_area(shape_uuid, device_ids=None):
    """이 구역에 속한 노트 uuid 집합. 도형을 못 찾으면 None(= 거르지 않음).

    노트는 세 가지로 구역에 매인다. 셋 다 봐야 한다:

    - **공간에 붙은 노트**(`target_id` 가 도형·시설) — 로컬 실측에서 이쪽이
      다수다(site 4 · zone 5 · GeoShape 3 · GeoFacility 4). 처음에 장치만
      보고 만들었더니 구역을 골라도 노트가 0건이었다.
    - **장치에 붙은 노트**(`target_id` 가 이 구역의 장치).
    - **좌표**(`gps_lat`/`gps_lng`) — 무엇에도 매이지 않고 그 자리에 적은 노트.

    태그 목록을 좁히는 데도, 그래프에 찍을 노트를 좁히는 데도 같은 집합을
    쓴다. 목록만 좁히고 표시를 안 좁히면 필터가 거짓말이 된다 — 태그를 골랐을
    때 남의 구역 노트가 함께 뜬다.
    """
    from shapely.geometry import Point, shape as shapely_shape

    from aot.databases.models import Notes

    shape = GeoShape.query.filter(GeoShape.unique_id == shape_uuid).first()
    if shape is None:
        return None

    if device_ids is None:
        device_ids = device_ids_in_area(shape_uuid) or set()

    from aot.databases.models import GeoFacility

    inside = {sh.unique_id for sh in _shapes_inside(shape)}
    inside.add(shape.unique_id)
    if inside:
        inside |= {f.unique_id for f in GeoFacility.query.filter(
            GeoFacility.shape_uuid.in_(list(inside))).all()}

    poly = None
    geom = _feature(shape).get('geometry') or {}
    if geom.get('type') in ('Polygon', 'MultiPolygon'):
        try:
            poly = shapely_shape(geom)
        except Exception:
            poly = None

    out = set()
    for note in Notes.query.all():
        if note.target_id and (note.target_id in device_ids
                               or note.target_id in inside):
            out.add(note.unique_id)
            continue
        if poly is not None and note.gps_lat is not None and note.gps_lng is not None:
            try:
                if poly.contains(Point(float(note.gps_lng), float(note.gps_lat))):
                    out.add(note.unique_id)
            except Exception:
                continue
    return out


def tag_ids_for_notes(note_ids):
    """주어진 노트들이 실제로 달고 있는 태그 uuid 집합.

    태그 자체는 구역에 속하지 않는다("관수"는 농장 전체의 어휘다). 구역에
    속하는 것은 노트이므로, 태그는 **그 구역에 노트가 하나라도 있을 때만**
    목록에 남긴다 — 그러지 않으면 골라도 아무것도 안 뜨는 태그가 남는다.
    """
    from aot.databases.models import Notes

    if not note_ids:
        return set()
    out = set()
    for note in Notes.query.filter(Notes.unique_id.in_(list(note_ids))).all():
        for tag in (note.tags or '').split(','):
            tag = tag.strip()
            if tag:
                out.add(tag)
    return out


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


# ---------------------------------------------------------------------------
# 장소 소속 정본 — "X 는 어디에 있나" 와 "P 안에 무엇이 있나" (2026-10-08)
# ---------------------------------------------------------------------------
#
# 같은 "3포장" 을 물어도 읽기 도구마다 다른 집합이 나왔다. 소속을 정하는 규칙이
# 다섯 벌이었기 때문이다(가장 안쪽 하나와 같은가 · 영역 안 전부 · 영역 안 마커만
# · 도형 계층 자손 · `device_zone_map` 의 자체 규칙). 외부 MCP 에 새로 연결한
# 모델이 "도구가 설명과 다르다" 를 반복 보고한 원인이다
# (.local/reports/place-membership-unification-20261008.md).
#
# 규칙은 이렇게 정한다(사용자 결정, 2026-10-08):
#   · 장소를 물으면 **하위 장소의 내용까지** 포함한다.
#   · 장치 소속은 마커뿐 아니라 **바인딩**까지 본다(`device_ids_in_area`).
#   · 부모는 `geo_hierarchy.build_geo_parent_map`(같은 지도, 명시 parent_id 우선,
#     동점은 `pick_smallest_container`).
#
# `aot/tools/data_tools` 는 소속을 이 절의 함수로만 묻는다 —
# `test_place_membership.py` 가 다른 헬퍼를 직접 부르는 것을 막는다.

#: 경로에 이름을 올리는 장소 종류. 장치 영역 폴리곤('device')·마커는 장소가 아니다.
PLACE_TYPES = ('site', 'zone', 'facility')

#: 장치가 "그곳에 있다" 고 볼 시설 바인딩 종류. 'weather' 는 여러 시설이 같은
#: 기상원을 나눠 쓰는 참조라 위치가 아니다.
_LOCATING_FACILITY_KINDS = ('fitting', 'actuator', 'sensor_role')

PATH_SEP = ' > '


def place_label(shape):
    """도형의 표시 이름(없으면 빈 문자열). 경량 레코드(`shape_index.ShapeRec`
    — feature 가 없고 이름을 미리 뽑아 둔다)도 받는다."""
    if not hasattr(shape, 'feature'):
        return str(getattr(shape, 'name', '') or '').strip()
    props = _feature(shape).get('properties') or {}
    return str(props.get('name') or props.get('label') or '').strip()


class PlaceIndex(object):
    """한 요청 안에서 장소 경로를 여러 번 물을 때 쓰는 사전 로드.

    도형 전체와 부모 맵을 한 번 읽는다(부모 맵은 `containment_cache` 를 거쳐
    대개 기하를 다시 돌지 않는다). 요청 단위로 만들고 버린다 — 프로세스에
    담으면 도형을 고친 뒤에도 옛 경로가 남는다.
    """

    def __init__(self):
        from aot.utils.geo_hierarchy import (build_geo_parent_map,
                                             _parent_map_from_cache)
        # 경량 레코드(이름만 뽑은 것)와 캐시된 부모 맵이 있으면 그것으로 —
        # 도형 JSON 을 통째로 읽지 않는다(`geo_descendant_recs` 와 같은 판단).
        # resolve_target 처럼 자주 불리는 도구가 이 색인을 쓰는데, ORM 으로
        # 읽으면 매 호출 7ms → 90~130ms 였다(2026-10-08 실측). 캐시가 비었으면
        # (첫 호출·무효화 직후) 기하로 파생해야 하므로 ORM 으로 물러선다.
        shapes = parent = None
        try:
            from aot.aot_flask.geo import shape_index
            recs = shape_index.all_shapes()
            pm = _parent_map_from_cache(recs)
            if pm is not None:
                shapes, parent = recs, pm
        except Exception:
            shapes = parent = None
        if shapes is None:
            shapes = GeoShape.query.all()
            parent = build_geo_parent_map(shapes)
        self.shapes = shapes
        self.by_id = {s.id: s for s in self.shapes}
        self.by_uid = {s.unique_id: s for s in self.shapes if s.unique_id}
        self.parent = parent
        self._containers = {}
        self._plot_parent = None
        self._facility_shape = None
        self._facility_shape_uid_of = {}
        self._fitting_table = None
        self._site_weather = {}
        # 이름 → 그 이름의 장소가 있는 지도들. 경로 맨 앞 이름이 다른 지도에도
        # 있으면 지도 이름을 붙인다(`path`).
        self._label_maps = {}
        for s in self.shapes:
            if s.type in PLACE_TYPES:
                lb = place_label(s)
                if lb:
                    self._label_maps.setdefault(lb, set()).add(s.geo_id)
        self._map_names = None

    # -- 시설 설비 표 ------------------------------------------------------
    def fitting_table(self):
        """{장치 id: [(시설 도형 uid, 역할)]} — 시설 설비에 매인 장치와 그 역할.

        역할은 설비(fittings[])의 `sensor_role`: 'indoor' | 'outdoor' | None(미설정).
        요청마다 한 번만 만든다(`PlaceIndex` 가 요청 단위라 같이 버려진다) —
        센서 분류가 장치마다 시설을 훑지 않게. 시설 단위 센서 등록(`sensors[].role`
        'outdoor_*'/'indoor_*')과 시설의 예보 연결(`weather`)도 같은 표에 싣는다.
        시설은 **도형 uid**(GeoShape.unique_id)로 가리킨다 — 장소 사슬과 같은 키.
        """
        if self._fitting_table is not None:
            return self._fitting_table
        table = {}
        try:
            from aot.databases.models import GeoBinding, GeoFacility
            facs = {f.unique_id: f for f in GeoFacility.query.all()}
            fit_role = {}
            for f in facs.values():
                for fit in (f.fittings or []):
                    if isinstance(fit, dict) and fit.get('id'):
                        fit_role[(f.unique_id, fit['id'])] = (
                            fit.get('sensor_role') or None)
                        if fit.get('input_id'):
                            table.setdefault(str(fit['input_id']), []).append(
                                (f.shape_uuid, fit.get('sensor_role') or None))
            for b in GeoBinding.query.filter(
                    GeoBinding.spatial_kind.in_(_LOCATING_FACILITY_KINDS
                                                + ('weather',)),
                    GeoBinding.valid_to.is_(None)).all():
                fac_uid, _, item = (b.spatial_id or '').partition(':')
                fac = facs.get(fac_uid)
                if fac is None or not b.device_id:
                    continue
                if b.spatial_kind == 'fitting' and b.role == 'sensor':
                    role = fit_role.get((fac_uid, item))
                elif b.spatial_kind == 'sensor_role':
                    role = 'outdoor' if (b.role or '').startswith('outdoor') \
                        else 'indoor'
                elif b.spatial_kind == 'weather':
                    role = 'outdoor'
                else:
                    role = None
                row = (fac.shape_uuid, role)
                rows = table.setdefault(b.device_id, [])
                if row not in rows and not any(r[0] == row[0] for r in rows):
                    rows.append(row)
        except Exception:
            logger.debug('[placement] 시설 설비 표 실패', exc_info=True)
        self._fitting_table = table
        return table

    # -- 장소 사슬 ---------------------------------------------------------
    def chain(self, shape):
        """바깥 → 안쪽 순의 장소 도형 목록. 장소가 아닌 도형(마커·장치 영역)은
        자기를 빼고 감싸는 장소부터 센다."""
        out, seen = [], set()
        cur = shape
        while cur is not None and cur.id not in seen:
            seen.add(cur.id)
            if cur.type in PLACE_TYPES:
                out.append(cur)
            cur = self.by_id.get(self.parent.get(cur.id))
        return list(reversed(out))

    def path(self, shape):
        """'3포장 > 3-1' — 이름 없는 장소는 건너뛴다. 장소 밖이면 ''.

        맨 앞 장소의 이름이 **다른 지도에도** 있으면 그 앞에 지도 이름을 붙인다
        ('김제 1포장 > 1-2'). 같은 '1포장' 이 김제의 대지이자 그린하트바이오의
        구역이라, 경로만 보고는 어느 것인지 알 수 없었다(2026-10-08 외부 MCP
        점검). 붙인 모양은 resolve_target 의 use_name('김제 1포장')과 같아서 경로의
        앞부분을 그대로 이름으로 다시 쓸 수 있다. 이름이 유일하면 붙이지 않는다 —
        장치·구획마다 실리는 값이라 늘 붙이면 그만큼 응답이 커진다.
        """
        # 접힌 zone(site 와 같은 땅의 유일한 기본 이름 zone)은 경로에서 건너뛴다.
        # 판정은 geo_hierarchy.collapsed_zone_site_map 한 곳이다.
        from aot.utils.geo_hierarchy import collapsed_zone_site_map
        _collapsed = collapsed_zone_site_map()
        chain = [s for s in self.chain(shape)
                 if place_label(s) and s.unique_id not in _collapsed]
        if not chain:
            return ''
        parts = [place_label(s) for s in chain]
        if len(self._label_maps.get(parts[0], ())) > 1:
            mn = self._map_name(chain[0].geo_id)
            if mn:
                parts[0] = '%s %s' % (mn, parts[0])
        return PATH_SEP.join(parts)

    def _map_name(self, geo_id):
        if self._map_names is None:
            try:
                from aot.databases.models import GeoMap
                self._map_names = {m.unique_id: (m.name or '').strip()
                                   for m in GeoMap.query.all()}
            except Exception:
                self._map_names = {}
        return self._map_names.get(geo_id) or ''

    def chain_uids(self, shape):
        return {s.unique_id for s in self.chain(shape)}

    def within(self, shape_uid, place_uid):
        """도형이 그 장소이거나 그 장소 안(자손)에 있는가."""
        shape = self.by_uid.get(shape_uid)
        if shape is None:
            return False
        return place_uid in self.chain_uids(shape) or shape_uid == place_uid

    # -- 구획 --------------------------------------------------------------
    def containers(self, map_uuid):
        if map_uuid not in self._containers:
            self._containers[map_uuid] = load_containers(map_uuid)
        return self._containers[map_uuid]

    def plot_container(self, plot):
        """구획을 감싸는 가장 안쪽 장소(대표점 기준). 시설 구획은 시설 외피로.

        구획 소속 캐시(`containment_cache` KIND_PLANTING — `_plot_ids_inside` 가
        같은 규칙으로 채운다)를 먼저 본다. 캐시에 없거나 지도가 어긋나면 기하로."""
        if self._plot_parent is None:
            try:
                from aot.aot_flask.geo import containment_cache as cc
                self._plot_parent = {k[1]: v for k, v in
                                     cc.load(kind=cc.KIND_PLANTING).items()}
            except Exception:
                self._plot_parent = {}
        if plot.unique_id in self._plot_parent:
            puid = self._plot_parent[plot.unique_id]
            if puid is None:
                return None
            hit = self.by_uid.get(puid)
            if hit is not None and hit.geo_id == plot.geo_id:
                return hit
        from aot.aot_flask.geo import plot_geometry
        geom = plot_geometry.geometry_of(plot)
        return container_for_geometry(plot.geo_id, geom,
                                      containers=self.containers(plot.geo_id))

    def plot_path(self, plot):
        container = self.plot_container(plot)
        base = self.path(container) if container is not None else ''
        fac = self._facility_name(getattr(plot, 'facility_uuid', None))
        if fac and fac not in base.split(PATH_SEP):
            base = (base + PATH_SEP + fac) if base else fac
        return base

    def plot_within(self, plot, place_uid):
        """구획이 그 장소 안인가 — 위치 경로(가장 안쪽 장소)와 시설 경로.

        시설 경로(2026-10-13): 위치 도형이 없는 시설 구획은 위치 경로로는 시설을
        감싼 장소(예: 대지 '3포장')로만 잡혀, 그 시설(육묘장3) 자체로 물으면
        빠졌다. 구획의 시설이 물은 장소이거나 그 안에 있으면 포함으로 본다.
        시설을 품지 않은 형제 구역(3-1·3-2)은 시설 도형 밖이라 끌어오지 않는다."""
        container = self.plot_container(plot)
        if container is not None and self.within(container.unique_id, place_uid):
            return True
        fac_shape = self._facility_shape_uid(getattr(plot, 'facility_uuid', None))
        return bool(fac_shape) and self.within(fac_shape, place_uid)

    def _load_facilities(self):
        if self._facility_shape is None:
            from aot.databases.models import GeoFacility
            rows = GeoFacility.query.all()
            self._facility_shape = {f.unique_id: f.name for f in rows}
            self._facility_shape_uid_of = {f.unique_id: f.shape_uuid
                                           for f in rows}

    def _facility_shape_uid(self, facility_uuid):
        if not facility_uuid:
            return None
        self._load_facilities()
        return self._facility_shape_uid_of.get(facility_uuid)

    def _facility_name(self, facility_uuid):
        if not facility_uuid:
            return None
        self._load_facilities()
        return self._facility_shape.get(facility_uuid)

    # -- 장치 --------------------------------------------------------------
    def device_paths(self, device_ids):
        """{device_id: [경로, …]} — 마커·도형 바인딩·시설 설비 바인딩에서.

        자기 위치가 없는 하위 장치(복합장치의 Input/Output)는 그릇의 경로를
        따른다. 경로가 여럿이면(같은 장치가 두 곳에 매임) 모두 싣는다.
        """
        from aot.aot_flask.geo.device_binding import shapes_for_devices
        from aot.databases.models import GeoBinding, GeoFacility, Input, Output

        ids = {str(d).split('::')[0] for d in (device_ids or []) if d}
        if not ids:
            return {}

        parents = {}
        for model in (Input, Output):
            for uid, parent in model.query.with_entities(
                    model.unique_id, model.parent_device_id).filter(
                    model.unique_id.in_(list(ids)),
                    model.parent_device_id.isnot(None)).all():
                if parent:
                    parents[uid] = parent
        wanted = ids | set(parents.values())

        found = {}
        for dev, shapes in (shapes_for_devices(wanted) or {}).items():
            for s in shapes:
                p = self.path(self.by_uid.get(s.unique_id, s))
                if p:
                    found.setdefault(dev, []).append(p)

        fac_rows = GeoBinding.query.filter(
            GeoBinding.device_id.in_(list(wanted)),
            GeoBinding.spatial_kind.in_(_LOCATING_FACILITY_KINDS),
            GeoBinding.valid_to.is_(None)).all()
        if fac_rows:
            fac_ids = {b.spatial_id.split(':')[0] for b in fac_rows}
            fac_shape = {f.unique_id: f.shape_uuid for f in GeoFacility.query.filter(
                GeoFacility.unique_id.in_(list(fac_ids))).all()}
            for b in fac_rows:
                shape = self.by_uid.get(fac_shape.get(b.spatial_id.split(':')[0]))
                p = self.path(shape) if shape is not None else ''
                if p:
                    found.setdefault(b.device_id, []).append(p)

        out = {}
        for dev in ids:
            paths = found.get(dev) or found.get(parents.get(dev)) or []
            uniq = []
            for p in paths:
                if p not in uniq:
                    uniq.append(p)
            if uniq:
                out[dev] = uniq
        return out


def annotate_places(items, index=None, id_key='id', kinds=None):
    """장치 dict 목록에 `place`(경로)를 제자리에서 채운다. 경로가 여럿이면
    `places` 도 싣는다. 경로가 없으면 아무것도 넣지 않는다 — 빈 값은 "어디에도
    없다" 로 읽히는데, 그것과 "위치를 모른다" 는 다르다."""
    rows = [r for r in items or []
            if isinstance(r, dict) and r.get(id_key)
            and (kinds is None or r.get('type') in kinds)]
    if not rows:
        return items
    index = index or PlaceIndex()
    paths = index.device_paths([r[id_key] for r in rows])
    for r in rows:
        ps = paths.get(str(r[id_key]).split('::')[0])
        if not ps:
            continue
        r['place'] = ps[0]
        if len(ps) > 1:
            r['places'] = ps
    return items


def places_named(query, index=None, types=('site', 'zone')):
    """질의 문자열에 이름이 들어 있는 장소들 — 가장 구체적인 것만.

    "1포장 1-4구역" 처럼 바깥과 안쪽이 함께 불리면 안쪽(1-4)만 남긴다. 두 글자
    미만 이름은 보지 않는다("1포장" 의 "1" 이 장소 '1' 에 걸리지 않게).

    한정어도 읽는다(2026-10-08) — `resolve_target` 이 후보에 내주는 이름
    ('김제 1포장')으로 다시 물으면 그 지도로 좁아져야 한다:
      · 질의에 **지도 이름**이 있으면 그 지도의 장소만 남긴다(그렇게 해서 남는
        것이 없으면 한정어가 아니라 우연한 낱말로 보고 무시한다).
      · 이름이 같은 장소가 여럿일 때, 질의에 그 **상위 장소 이름**도 있는 쪽이
        있으면('그린하트바이오 1포장') 그쪽만 남긴다.
    그래도 같은 이름이 여럿 남으면 그대로 돌려준다 — 호출자가 묻는다
    (`same_name_groups`).
    """
    index = index or PlaceIndex()
    q = str(query or '')
    hits = [s for s in index.shapes
            if s.type in types and len(place_label(s)) >= 2
            and place_label(s) in q]
    try:
        from aot.databases.models import GeoMap
        named_maps = {m.unique_id for m in GeoMap.query.all()
                      if m.name and len(m.name.strip()) >= 2 and m.name.strip() in q}
    except Exception:
        named_maps = set()
    if named_maps:
        narrowed = [s for s in hits if s.geo_id in named_maps]
        if narrowed:
            hits = narrowed
    hit_uids = {s.unique_id for s in hits}
    # 다른 적중 장소의 조상이면 뺀다 — 안쪽이 이긴다.
    ancestors = set()
    for s in hits:
        ancestors |= (index.chain_uids(s) - {s.unique_id})
    hits = [s for s in hits if s.unique_id not in (ancestors & hit_uids)]
    # 같은 이름끼리는 상위 장소가 질의에 함께 불린 쪽이 이긴다.
    by_label = {}
    for s in hits:
        by_label.setdefault(place_label(s), []).append(s)
    out = []
    for label, group in by_label.items():
        if len(group) > 1:
            # 질의에 **불린** 장소(hit_uids) 중에 자기 상위가 있는 쪽.
            qualified = [s for s in group
                         if (index.chain_uids(s) - {s.unique_id}) & hit_uids]
            if qualified:
                group = qualified
        out.extend(group)
    return out


def same_name_groups(places):
    """places_named 결과에서 이름이 같은 장소가 둘 이상인 묶음 → [[GeoShape, …]]."""
    by_label = {}
    for s in places:
        by_label.setdefault(place_label(s), []).append(s)
    return [g for g in by_label.values() if len(g) > 1]


def place_members(place_uid, include_facility_fittings=True,
                  include_references=True):
    """장소 안(하위 장소 포함)의 장치 id 집합. 장소를 못 찾으면 None.

    `device_ids_in_area` 를 그대로 쓴다 — 마커·바인딩·그릇·참조 4겹, 하위
    구역은 대표점 포함으로 같은 지도 안에서 따라온다. 이름만 정본 쪽으로 둔다:
    읽기 도구가 "영역 안의 마커만"(`device_ids_in_shape`)을 따로 쓰던 것이
    갈라짐의 한 원인이었다."""
    return device_ids_in_area(place_uid,
                              include_facility_fittings=include_facility_fittings,
                              include_references=include_references)


def weather_place_for(place_uid, index=None):
    """장소 uuid → 그 장소의 기상원을 물을 장소 uuid(못 찾으면 None).

    대지(site)는 자기 자신, 구역·시설은 자기를 감싸는 **가장 안쪽 대지**다 —
    기상대는 대지에 하나 두고 그 안의 구역이 나눠 본다(`_weather_for_plot` 과
    같은 판단). 감싸는 대지가 없으면 그 장소 자신을 본다(구역에 기상대를
    매단 설치가 있다).
    """
    if not place_uid:
        return None
    index = index or PlaceIndex()
    shape = index.by_uid.get(place_uid)
    if shape is None:
        return None
    if getattr(shape, 'type', None) == 'site':
        return shape.unique_id
    sites = [s for s in index.chain(shape) if getattr(s, 'type', None) == 'site']
    return sites[-1].unique_id if sites else shape.unique_id


def _weather_outdoor(place_uid, index=None):
    """장소의 실외 기준 → `(장치 id 집합, 출처, 기상 장소 uuid)`.

    대지의 기상원(`weather_device_ids`)과 그 하위 장치(복합장치의 Input/Output).
    `place_members_split` 와 `classify_sensors` 가 같은 판정을 쓰도록 한 곳에 둔다.
    """
    from aot.databases.models import Input, Output

    wuid = weather_place_for(place_uid, index=index) if place_uid else None
    outdoor, source = ([], 'none')
    if wuid:
        try:
            outdoor, source = weather_device_ids(wuid)
        except Exception:
            logger.exception('[weather] 실내외 분리 실패: %s', place_uid)
            outdoor, source = [], 'none'
    outdoor = {d for d in outdoor if d}
    if outdoor:
        # 기상대를 그릇(복합장치)으로 지정했으면 채널을 내는 하위 Input 도 실외다.
        for model in (Input, Output):
            try:
                rows = model.query.with_entities(model.unique_id).filter(
                    model.parent_device_id.in_(list(outdoor))).all()
                outdoor.update(r[0] for r in rows if r[0])
            except Exception:
                logger.debug('[weather] 하위 장치 조회 실패', exc_info=True)
    return outdoor, source, wuid


def place_members_split(place_uid, include_facility_fittings=True,
                        include_references=True, index=None):
    """장소 소속을 **실내(indoor)/실외(outdoor)** 로 나눠 돌려준다.

    반환: `{'indoor': set, 'outdoor': set, 'source': 'bound'|'inferred'|'none',
    'weather_place': uuid|None, 'members': set}`(members 는 `place_members`
    그대로 — 호출부가 두 번 계산하지 않게) — 장소를 못 찾으면 None(`place_members` 와
    같은 뜻: "거르지 않는다").

    · outdoor = 그 장소를 감싸는 대지의 기상원(`weather_device_ids` — 사람이
      지정한 것이 우선, 없으면 측정값으로 추론)과 그 하위 장치(복합장치의
      Input). **장소 소속이 아니어도 싣는다** — 구역 3-1 을 물어도 대지의
      기상대는 그 구역의 실외 기준이다. 지도에 마커 없이 시설 설비에만 매인
      기상대(미러-기상대)도 추론에 걸리면 여기로 온다.
    · indoor = 소속(`place_members`) − outdoor.
    · source = 나눈 근거. 'bound' 면 사람이 기상원을 지정했으므로 나머지가
      실내라는 것도 사람의 판단이고, 'inferred'·'none' 이면 추론이다.

    `classify_sensors` 와 같은 기상 판정(`_weather_outdoor`)을 쓰는 얇은 함수다.
    반환 계약은 그대로다 — 설비 역할·예보 모델까지 실외로 접는 것은 새 분류
    (`classify_sensors`)의 몫이고, 이 함수의 indoor/outdoor 는 바꾸지 않는다.

    ⚠ `place_members` 는 바꾸지 않는다 — 노트·일정·화면 소속이 "그곳에 있는
      장치 전부" 로 쓰고 있다. 실내외 구분이 필요한 읽기(센서 요약·평균)만
      이 함수를 쓴다. 환경 제어(env_coordinator)는 시설 바인딩의
      sensor_role 로 안팎을 나누며 이 함수와 무관하다.
    """
    members = place_members(place_uid,
                            include_facility_fittings=include_facility_fittings,
                            include_references=include_references)
    if members is None:
        return None
    outdoor, source, wuid = _weather_outdoor(place_uid, index=index)
    return {'indoor': set(members) - outdoor, 'outdoor': outdoor,
            'source': source, 'weather_place': wuid, 'members': set(members)}


# -- 센서 위치 유형(placement) ------------------------------------------------
#: kind: facility | open_field | outdoor | unplaced.
#: source: fitting_role | weather_bound | weather_inferred | geometry(unplaced 는 None).
#: conflict: 설비 역할(fitting)과 새 분류가 다를 때의 경고 문자열(없으면 None).
#: ⚠ 읽기 전용 분류다 — 환경 제어(env_coordinator)는 이 모듈을 import 하지
#:   않고 설비 sensor_role 을 그대로 쓴다(test_env_isolation_from_placement).
Placement = namedtuple('Placement', 'kind place_uid facility_uid source conflict')
Placement.__new__.__defaults__ = (None,)

_SOIL_MEASUREMENTS = frozenset({
    'volumetric_water_content', 'soil_moisture', 'soil_temperature',
    'soil_water_potential', 'soil_ec', 'water_potential'})
_SOIL_NAME_RE = re.compile(r'토양|지온|soil|地温|地中|土壌', re.IGNORECASE)


def channel_medium(dm_row):
    """채널 → 'air' | 'soil' | 'other' (위치 축과 별개인 매질 축).

    토양 판정은 채널 이름 휴리스틱(토양/soil/地温)과 측정 종류
    (volumetric_water_content 등). 통신 상태 채널(배터리·RSSI·SNR)은 'other'.
    """
    names = ' '.join(str(getattr(dm_row, a, '') or '')
                     for a in ('name', 'measurement'))
    mtype = str(getattr(dm_row, 'measurement_type', '') or '').lower()
    meas = str(getattr(dm_row, 'measurement', '') or '').lower()
    if mtype in _SOIL_MEASUREMENTS or meas in _SOIL_MEASUREMENTS \
            or _SOIL_NAME_RE.search(names):
        return 'soil'
    try:
        from aot.aot_flask.geo.facility_sensors import (META_CHANNEL_KEYS,
                                                        channel_meta_for_dm)
        if channel_meta_for_dm(dm_row).get('key') in META_CHANNEL_KEYS:
            return 'other'
    except Exception:
        pass
    return 'air'


def classify_sensors(device_ids, place_uid=None, *, index=None):
    """장치 id 들 → `{id: Placement}`. 읽기 전용(저장·바인딩 생성 없음).

    판정 순서:
      1. outdoor — 대지 기상원(지정 우선·추론), 시설 설비 sensor_role=='outdoor',
         예보 모델 장치.
      2. facility — 시설 설비에 매이고 역할이 indoor/미설정, 또는 장소 사슬에
         시설이 하나라도 있음(시설이 이긴다 — 구획은 감싸는 장소를 따른다).
      3. open_field — 사슬에 시설이 없는 구역·대지 직속.
      4. unplaced — 마커·설비 없이 참조로만 들어온 센서.
    복합장치의 하위 Input 은 부모를 따른다. 장소 사슬은 반드시 `PlaceIndex` 의
    부모 맵으로 센다(대표점 판정은 '1포장' 대지를 구역 1-3 안으로 본다).

    `place_uid` 를 주면 그 장소의 대지 기상원을 모든 장치에 적용한다(장소 소속이
    아니어도 — `place_members_split` 과 같다). 주지 않으면 장치가 놓인 대지의
    기상원으로 장치마다 판단한다. 기상원이 없는 대지는 "실외 기준 없음"이다 —
    다른 대지의 기상을 빌리지 않는다.
    """
    from aot.databases.models import Input, Output

    ids = []
    for d in (device_ids or []):
        d = str(d or '').split('::')[0]
        if d and d not in ids:
            ids.append(d)
    if not ids:
        return {}
    index = index or PlaceIndex()

    parents = {}
    for model in (Input, Output):
        for uid, parent in model.query.with_entities(
                model.unique_id, model.parent_device_id).filter(
                model.unique_id.in_(ids),
                model.parent_device_id.isnot(None)).all():
            if parent:
                parents[uid] = parent
    wanted = set(ids) | set(parents.values())

    from aot.aot_flask.geo.device_binding import shapes_for_devices
    homes = shapes_for_devices(wanted) or {}
    fit = index.fitting_table()

    model_ids = set()
    try:
        from aot.utils.inputs import model_input_drivers
        drivers = model_input_drivers()
        if drivers:
            model_ids = {r[0] for r in Input.query.with_entities(
                Input.unique_id).filter(Input.unique_id.in_(list(wanted)),
                                        Input.device.in_(list(drivers))).all()}
    except Exception:
        logger.debug('[placement] 예보 모델 조회 실패', exc_info=True)

    given_out, given_src, given_w = (_weather_outdoor(place_uid, index=index)
                                     if place_uid else (set(), 'none', None))

    def _site_weather(shape):
        sites = [s for s in index.chain(shape) if s.type == 'site']
        if not sites:
            return set(), 'none', None
        uid = sites[-1].unique_id
        if uid not in index._site_weather:
            index._site_weather[uid] = _weather_outdoor(uid, index=index)
        return index._site_weather[uid]

    def _classify(d):
        own = d in homes or d in fit
        root = d if own else parents.get(d, d)
        shapes = list(homes.get(root, []))
        for fac_uid, _ in fit.get(root, []):
            fs = index.by_uid.get(fac_uid)
            if fs is not None:
                shapes.append(fs)
        # 기상원 — 장소를 줬으면 그 대지 것, 아니면 장치가 놓인 대지 것.
        wsrc, wplace = None, None
        if place_uid:
            if root in given_out or d in given_out:
                wsrc, wplace = given_src, given_w
        else:
            for sh in shapes:
                outs, src, wu = _site_weather(sh)
                if root in outs or d in outs:
                    wsrc, wplace = src, wu
                    break
        roles = [r for _, r in fit.get(root, [])]
        fit_kind = None
        if roles:
            fit_kind = 'outdoor' if 'outdoor' in roles else 'facility'
        # 장소 사슬(부모 맵). 시설이 하나라도 있으면 시설이 이긴다.
        place_id = fac_id = None
        has_chain = False
        for sh in shapes:
            ch = index.chain(sh)
            if not ch:
                continue
            has_chain = True
            facs = [c for c in ch if c.type == 'facility']
            if facs and fac_id is None:
                fac_id, place_id = facs[-1].unique_id, ch[-1].unique_id
            elif place_id is None:
                place_id = ch[-1].unique_id
        if wsrc:
            res = ('outdoor', wplace or place_id, fac_id,
                   'weather_bound' if wsrc == 'bound' else 'weather_inferred')
        elif fit_kind == 'outdoor':
            res = ('outdoor', place_id, fac_id, 'fitting_role')
        elif root in model_ids or d in model_ids:
            res = ('outdoor', place_id, fac_id, 'weather_inferred')
        elif fit_kind == 'facility':
            res = ('facility', place_id, fac_id, 'fitting_role')
        elif fac_id:
            res = ('facility', place_id, fac_id, 'geometry')
        elif has_chain:
            res = ('open_field', place_id, None, 'geometry')
        else:
            res = ('unplaced', None, None, None)
        conflict = None
        if fit_kind and res[0] != fit_kind:
            conflict = 'fitting_role=%s but placement=%s' % (fit_kind, res[0])
        return Placement(res[0], res[1], res[2], res[3], conflict)

    return {d: _classify(d) for d in ids}


def place_scope_ids(shape, include_self=True):
    """도형 → "그 안에서 일어나는 일" 의 target_id 들과 내역 `(ids, breakdown)`.

    일정·노트처럼 대상 id 로 붙는 기록을 장소 단위로 모을 때 쓴다. 도형 계층의
    자손(구역·시설·마커·구획 — `geo_hierarchy.descendant_target_ids`)에 더해,
    장소라면 정본 소속(`place_members` — 바인딩으로 맡긴 장치 포함)을 합친다.

    AI 도구(search_notes·search_schedule)와 화면(노트·일정 모달)이 **이 함수
    하나**를 쓴다. 예전에는 AI 는 자손만, 일정 화면은 자손+바인딩, 노트 화면은
    자손만 봐서 같은 장소에 세 가지 답이 있었다(2026-10-08).
    """
    from aot.utils.geo_hierarchy import descendant_target_ids
    more, breakdown = descendant_target_ids(shape, include_self=include_self)
    more = list(more or [])
    if getattr(shape, 'type', None) in PLACE_TYPES:
        # 바인딩 쪽이 실패해도 계층 자손만큼은 낸다 — 통째로 실패하면 호출자가
        # 대상 하나(정확 일치)로 물러서서 장소 안의 기록이 전부 사라진다.
        try:
            bound = sorted((place_members(shape.unique_id) or set()) - set(more))
        except Exception:
            logger.warning('place_scope_ids: 소속 확장 실패(shape=%s) — 계층 '
                           '자손만 씁니다', shape.unique_id, exc_info=True)
            bound = []
        if bound:
            more.extend(bound)
            if isinstance(breakdown, dict):
                breakdown = dict(breakdown, bound_devices=len(bound))
    return more, breakdown


def facility_identity_ids(ids):
    """id 목록 → 시설이 섞여 있으면 그 시설의 **두 id 모두**를 덧붙여 돌려준다.

    시설은 정체성이 둘이다 — `GeoFacility.unique_id`(웹이 노트를 붙인다)와 그
    도형 `GeoShape.unique_id`(= `GeoFacility.shape_uuid`, MCP 가 예전에 붙였다).
    어느 쪽이 들어와도 둘 다 후보에 넣어야 같은 시설의 노트가 갈라지지 않는다.
    시설이 아닌 id 는 그대로 둔다. 순서·중복 제거 유지. 조회 실패 시 입력 그대로.
    """
    out = list(dict.fromkeys(i for i in (ids or []) if i))
    if not out:
        return out
    try:
        from aot.databases.models import GeoFacility
        rows = GeoFacility.query.filter(
            (GeoFacility.unique_id.in_(out)) |
            (GeoFacility.shape_uuid.in_(out))).all()
    except Exception:
        logger.warning('facility_identity_ids: 조회 실패 — 입력 그대로',
                       exc_info=True)
        return out
    for f in rows:
        for i in (f.unique_id, f.shape_uuid):
            if i and i not in out:
                out.append(i)
    return out


def normalize_facility_note_target(target_id, target_type):
    """노트 쓰기용 — 시설(도형 id 든 시설 id 든)이면 웹과 같이
    `(GeoFacility.unique_id, 'GeoFacility')`, 아니면 입력 그대로."""
    tid = target_id.strip() if isinstance(target_id, str) else None
    if not tid:
        return target_id, target_type
    try:
        from aot.databases.models import GeoFacility
        fac = GeoFacility.query.filter(
            (GeoFacility.unique_id == tid) |
            (GeoFacility.shape_uuid == tid)).first()
    except Exception:
        logger.warning('normalize_facility_note_target: 조회 실패 — 그대로',
                       exc_info=True)
        return target_id, target_type
    if fac is not None:
        return fac.unique_id, 'GeoFacility'
    return target_id, target_type


def place_at_point(lat, lng):
    """좌표를 감싸는 가장 작은 대지·구역(GeoShape, 없으면 None).

    지도 화면 중심으로 "여기 밸브 다 열어줘" 를 좁힐 때 쓴다. 화면은 지도 id 를
    보내지 않으므로 모든 지도의 장소를 후보로 두고, 동점 규칙은 정본
    (`pick_smallest_container` — 가장 작은 것)이다. 고른 장소 **안**의 판정은
    그 장소의 지도에서만 한다(`place_members`).
    """
    from shapely.geometry import Point, shape as shapely_shape
    from aot.utils.geo_hierarchy import pick_smallest_container
    try:
        pt = Point(float(lng), float(lat))
    except (TypeError, ValueError):
        return None
    candidates = []
    for s in GeoShape.query.filter(GeoShape.type.in_(_CONTAINER_TYPES)).all():
        geom = _feature(s).get('geometry') or {}
        if geom.get('type') not in ('Polygon', 'MultiPolygon'):
            continue
        try:
            poly = shapely_shape(geom)
        except Exception:
            continue
        candidates.append((s, poly, getattr(poly, 'area', 0.0) or 0.0))
    return pick_smallest_container(pt, candidates)


def screen_members(place):
    """화면이 "이 장소의 장치" 로 보이는 집합 — **설비를 빼는 유일한 자리**.

    · 대지(site): 시설 안 설비(측창·도어 …)에 매인 장치는 뺀다. 필지 모달에서
      그것까지 늘어놓으면 "이 필지를 어떻게 볼까" 가 아니라 "여기서 뭘 다 조작할
      수 있나" 가 된다(2026-09-06 현장 보고). 설비는 그 시설 모달에서 본다.
    · 구역(zone)·그 밖: 그대로 — 구역 안 시설의 설비는 구역의 것이 맞다.

    필지 엔드포인트와 지도 화면 기준 제어 제안이 이 함수를 같이 쓴다(2026-10-08,
    사용자 결정 — 화면에 보이는 목록과 제안 대상이 같아야 한다). 켜고 끄는 자리를
    늘리면 어느 화면이 무엇을 세는지 아무도 모르게 된다
    (test_site_contents_scope.TestOnlyTheSiteEndpointTurnsItOff).
    """
    if getattr(place, 'type', None) == 'site':
        return device_ids_in_area(place.unique_id, include_facility_fittings=False)
    return device_ids_in_area(place.unique_id)
