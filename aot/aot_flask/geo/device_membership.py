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
    for s, kind, poly in containers:
        if kind != 'site':
            continue
        try:
            if poly.contains(pt):
                return s
        except Exception:
            continue
    return None


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
        Notes.target_id.in_(list(inside))).first() is not None


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


def device_ids_in_area(shape_uuid, include_facility_fittings=True):
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
