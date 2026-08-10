# coding=utf-8
"""site(필지) 요약 — 지도 팝업이 "들어가 볼 이유"를 만드는 집계.

정본 설계: docs/design/map-site-summary.md

site 는 줌 아웃 화면에서 사용자가 가장 먼저 만나는 계층인데 팝업이 이름·면적
뿐이라, 필지를 하나씩 열어 봐야 어디가 문제인지 알 수 있었다. 이 모듈은 하위
구역·시설을 한 번에 훑어 "어디가 나쁜가"를 답한다.

**밴드 색은 여기서 계산하지 않는다.** 5단계 밴드의 경계값(DEFAULT_RANGES)·
색표(BAND_PALETTE)·단위 환산(BAND_UNIT_SCALE)은 전부 JS 와 CSS 토큰
(`--aot-band-1..5`, settings/custom_ui 로 사용자 정의 가능)에만 있다. 여기서
다시 구현하면 두 벌이 조용히 어긋나고, 사용자가 색을 바꿔도 서버 값은 안
따라온다. 서버는 `key`/`value`/`unit` 까지만 주고 색은 클라이언트의 기존
함수가 낸다(docs/design/color-system.md 의 "색을 도형에 되써 넣지 말 것"과
같은 이유다).

**status 도 색과 무관한 사실만으로 낸다** — 통신 두절·배터리·무응답 개수.
밴드는 사용자가 경계값을 바꿀 수 있는 표시 설정이라, 그걸로 상태를 정하면
색 설정을 바꾼 순간 없던 "고장"이 생겼다 사라진다.
"""
import logging
import threading
import time

logger = logging.getLogger(__name__)

# 대표 측정값 우선순위 — 클라이언트 _sensorSummary 의 _SENSOR_SUM_PRIORITY 와
# 같은 순서여야 한다(aot-map-widget-vector.js). 한쪽만 고치면 같은 구역이
# 지도 칩과 팝업에서 다른 측정을 대표로 내세운다.
SENSOR_KEY_PRIORITY = ('VPD', 'T', 'RH', 'CO2', 'light', 'wind_ms')

# 측정값이 "살아 있다"고 보는 최대 나이(초). 계측 dock 의 판정과 같은 값.
FRESH_MAX_AGE_S = 600

# 이 아래면 교체 대상으로 센다. 경고이지 고장이 아니다.
BATTERY_LOW_PCT = 20

CACHE_TTL_S = 30

_CACHE = {}
_CACHE_LOCK = threading.Lock()
_BUILD_LOCKS = {}


# ── 캐시 + 단일 비행 ────────────────────────────────────────────────────────

def cached_build(cache, locks, key, ttl_s, build, force=False):
    """TTL 캐시 + 키별 단일 비행. 모달 응답을 만드는 자리마다 쓴다.

    단일 비행이 캐시만큼 중요하다. 이 계산 하나가 influx 수십 질의라,
    같은 필지를 두 사람이 동시에 열거나 팝업이 폴링하는 동안 클릭이
    겹치면 **같은 계산이 그대로 곱해진다.** 저사양 호스트에서는 그
    팬아웃이 gunicorn 스레드풀을 삼켜, 사용자가 누른 요청이 큐에서
    기다린다(시설 모달에서 실측 1초+, 콜드 4초+).

    build() 가 None 을 주면 캐시에 넣지 않는다 — "못 찾음"을 30초 동안
    기억하면 방금 만든 도형이 그동안 없는 것이 된다.
    """
    now = time.time()
    if not force:
        with _CACHE_LOCK:
            hit = cache.get(key)
        if hit and hit[0] > now:
            return hit[1]

    with _CACHE_LOCK:
        lock = locks.get(key)
        if lock is None:
            lock = locks[key] = threading.Lock()

    with lock:
        # 앞선 대기자가 이미 채웠으면 그것을 쓴다.
        if not force:
            with _CACHE_LOCK:
                hit = cache.get(key)
            if hit and hit[0] > time.time():
                return hit[1]

        payload = build()
        if payload is not None:
            with _CACHE_LOCK:
                cache[key] = (time.time() + ttl_s, payload)
        return payload


def summary_for_site(site_uuid, force=False):
    """site 요약(dict). 도형을 못 찾으면 None. 30초 캐시 + 단일 비행."""
    return cached_build(_CACHE, _BUILD_LOCKS, site_uuid, CACHE_TTL_S,
                        lambda: _build_summary(site_uuid), force)


# 구역 모달 응답. site 요약과 같은 30초인 이유: 둘 다 사람이 창을 여는
# 순간에만 필요하고, 안에 든 것(센서 목록·현재 환경)이 30초 안에 달라질 일이
# 없다. 장치 on/off 는 이 응답이 아니라 별도 폴링이 따라간다.
_ZONE_CONTENTS_CACHE = {}
_ZONE_CONTENTS_LOCKS = {}
_ZONE_CONTENTS_TTL_S = 30


def cached_zone_contents(zone_uuid, build, force=False):
    """구역 모달 응답 캐시. 응답을 만드는 일은 호출자(라우트)가 한다."""
    return cached_build(_ZONE_CONTENTS_CACHE, _ZONE_CONTENTS_LOCKS,
                        zone_uuid, _ZONE_CONTENTS_TTL_S, build, force)


def invalidate_zone_contents(zone_uuid):
    """구역 내용이 바뀐 직후(사진 교체·장치 순서 저장) 부른다.

    안 부르면 방금 올린 사진이 30초 동안 안 보인다 — 저장은 됐는데 화면이
    안 바뀌는 것만큼 사람을 헷갈리게 하는 게 없다.
    """
    with _CACHE_LOCK:
        _ZONE_CONTENTS_CACHE.pop(zone_uuid, None)


def invalidate(site_uuid=None):
    """캐시 무효화 — 도형·장치가 바뀐 직후 호출할 자리를 열어 둔다."""
    with _CACHE_LOCK:
        if site_uuid is None:
            _CACHE.clear()
            _PARENT_CACHE.clear()
            _STATUS_CACHE.clear()
            _ZONE_STATUS_CACHE.clear()
            _ZONE_CONTENTS_CACHE.clear()
        else:
            _CACHE.pop(site_uuid, None)
            _STATUS_CACHE.pop(site_uuid, None)
            _ZONE_CONTENTS_CACHE.pop(site_uuid, None)


# ── 상위 site 찾기 ──────────────────────────────────────────────────────────

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


def parent_area_for_device(device_uuid):
    """장치가 속한 공간 — `{'kind','uuid','name'}` 또는 None.

    장치 모달의 "상위로" 화살표가 쓴다. `kind` 는 `'zone'|'site'|'facility'` 로,
    호출자가 어떤 모달을 열지 고른다.

    소속을 찾는 길이 둘이다. **마커만 보면 안 된다** — 실측상 출력 16개 중
    지도에 점이 찍힌 것은 1개뿐이고, 나머지는 시설 설비(fitting/actuator)에
    바인딩으로 매여 있다.

    좁은 것부터 고른다: **구역 > 시설 > 필지**. 마커가 필지 안에 있다는 사실은
    시설 설비에 매여 있다는 사실보다 덜 구체적이다 — 필지를 먼저 집으면 온실
    안의 창문 모터가 "이 장치는 3포장 소속"이라고 답한다. 실제로 겪었다
    (env_coordinator 가 시설이 아니라 같은 이름의 필지를 상위로 내놨다).
    """
    from aot.aot_flask.geo.device_membership import (
        map_for_device, zone_for_device)

    marker_area = None
    try:
        map_uuid = map_for_device(device_uuid)
        if map_uuid:
            shape = zone_for_device(device_uuid, map_uuid)
            if shape is not None:
                marker_area = {
                    'kind': 'zone' if shape.type == 'zone' else 'site',
                    'uuid': shape.unique_id,
                    'name': _shape_name(shape)}
    except Exception as exc:
        logger.debug('[SiteSummary] 마커 소속 판정 실패(%s): %s', device_uuid, exc)

    if marker_area and marker_area['kind'] == 'zone':
        return marker_area
    return _facility_for_device(device_uuid) or marker_area


def _facility_for_device(device_uuid):
    """시설 설비에 매인 장치의 시설. spatial_id 는 `<시설uuid>:<슬롯>` 계약이다."""
    from aot.databases.models import GeoBinding, GeoFacility

    try:
        rows = GeoBinding.query.filter(
            GeoBinding.device_id == device_uuid,
            GeoBinding.valid_to.is_(None)).all()
        for row in rows:
            spatial_id = row.spatial_id or ''
            facility_uuid = spatial_id.split(':')[0]
            if not facility_uuid:
                continue
            facility = GeoFacility.query.filter_by(
                unique_id=facility_uuid).first()
            if facility is not None:
                return {'kind': 'facility',
                        'uuid': facility.unique_id,
                        'name': facility.name or facility.unique_id}
    except Exception as exc:
        logger.debug('[SiteSummary] 시설 소속 판정 실패(%s): %s', device_uuid, exc)
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


# ── 집계 본체 ───────────────────────────────────────────────────────────────

def _build_summary(site_uuid):
    from aot.databases.models import GeoShape

    site = GeoShape.query.filter_by(unique_id=site_uuid, type='site').first()
    if site is None:
        return None

    partial = []
    children_shapes = _direct_children(site)

    # 장치 소속은 자식별로 뽑되, 통신 상태는 **한 번에** 읽는다.
    # read_link_status_batch 는 호출마다 데몬 input_status_all() 을 한 번 치므로
    # 자식마다 부르면 데몬 왕복이 자식 수만큼 늘어난다.
    ids_by_child = {}
    all_ids = set()
    for shape in children_shapes:
        ids = _device_ids_for(shape)
        ids_by_child[shape.unique_id] = ids
        all_ids |= ids

    link_status = _link_status(all_ids, partial)

    children = []
    for shape in children_shapes:
        children.append(_child_entry(shape, ids_by_child[shape.unique_id],
                                     link_status, partial))

    offline_total = sum(c['issues']['comm_fault'] for c in children)

    return {
        'site': {
            'uuid': site.unique_id,
            'name': _shape_name(site),
            'area_m2': _shape_area_m2(site),
            'status': _rollup_status(children),
            'counts': {
                'zones': sum(1 for c in children if c['kind'] == 'zone'),
                'facilities': sum(1 for c in children if c['kind'] == 'facility'),
                'devices': len(all_ids),
            },
        },
        'children': children,
        'today': _today_block(site, all_ids, offline_total, partial),
        'notes': _notes_block(site, partial),
        'generated_at': _now_iso(),
        'partial': partial,
    }


def _direct_children(site):
    """site 직속 zone·facility 도형 — 손자는 부모 자식 행에 합산된다.

    계층은 geo_hierarchy 가 정본이다(parent_id 가 있으면 그것, 없으면 자기를
    감싸는 가장 작은 site/zone 폴리곤). 같은 지도의 도형으로만 좁혀서 부른다 —
    전체 도형을 넘기면 지도 수만큼 기하 해석이 늘어난다.
    """
    from aot.databases.models import GeoShape
    from aot.utils.geo_hierarchy import build_geo_parent_map

    shapes = GeoShape.query.filter(GeoShape.geo_id == site.geo_id).all()
    try:
        parent_map = build_geo_parent_map(shapes)
    except Exception as exc:
        logger.warning('[SiteSummary] 계층 해석 실패(site=%s): %s',
                       site.unique_id, exc)
        return []

    kids = [s for s in shapes
            if s.type in ('zone', 'facility')
            and parent_map.get(s.id) == site.id]
    # 구역 먼저, 그 다음 시설. 각각 이름순 — 지도를 보며 눈으로 찾는 순서다.
    kids.sort(key=lambda s: (0 if s.type == 'zone' else 1, _shape_name(s)))
    return kids


def _device_ids_for(shape):
    """도형에 속한 장치 id 집합.

    device_membership.device_ids_in_area 가 소속 판정의 유일한 정본이다
    (마커·바인딩·그릇·참조 4겹). 마커만 보면 목록이 통째로 빈다 — 실측상
    출력 16개 중 마커가 있는 것은 1개뿐이다.
    """
    from aot.aot_flask.geo.device_membership import device_ids_in_area

    try:
        return set(device_ids_in_area(shape.unique_id) or set())
    except Exception as exc:
        logger.warning('[SiteSummary] 소속 판정 실패(shape=%s): %s',
                       shape.unique_id, exc)
        return set()


def _child_entry(shape, device_ids, link_status, partial):
    rep, sensors = _sensor_rollup(device_ids, partial)
    issues = _issue_counts(device_ids, link_status)

    return {
        'uuid': shape.unique_id,
        'kind': 'facility' if shape.type == 'facility' else 'zone',
        'name': _shape_name(shape),
        'status': _child_status(device_ids, sensors, issues),
        'rep': rep,
        'sensors': sensors,
        'issues': issues,
        # 자동제어 연동은 내지 않는다 — **시설별로 알 수가 없다.** GeoFacility 에
        # IEC 함수를 가리키는 컬럼이 없고, /status 엔드포인트는 클라이언트가 넘긴
        # function_uuid 가 없으면 전역에서 활성 env_coordinator 하나를 골라 쓴다.
        # 그대로 행에 찍으면 센서도 없는 관리동까지 "자동제어 활성"이 되어,
        # 실제로 제어 중인 시설과 구분이 사라진다. 시설별 링크가 생기면 그때
        # 채운다(docs/design/map-site-summary.md).
        'control': None,
    }


# ── 대표 측정값 ─────────────────────────────────────────────────────────────

def env_for_devices(device_ids):
    """장치 묶음의 현재 환경 — `{'readings': [...], 'sensors': {...}}`.

    구역 모달도 같은 답이 필요해서 공용으로 뺐다(routes_geo 의 zone contents).
    한쪽만 고치면 같은 구역이 필지 요약과 구역 모달에서 다른 온도를 말한다.

    readings 는 채널 key 별 평균이다. 메타 채널(rssi/snr/battery)은 뺀다 —
    빼기 전에는 하트비트 채널이 0번인 LoRaWAN 노드가 온도 대신 배터리 전압을
    대표값으로 내세웠다. 정렬은 SENSOR_KEY_PRIORITY 순이라 첫 항목이 곧 대표값이다.
    """
    from aot.aot_flask.geo.facility_sensors import (
        META_CHANNEL_KEYS, channel_meta_for_dm)
    from aot.databases.models import DeviceMeasurements, Input

    empty = {'readings': [], 'sensors': {'valid': 0, 'total': 0}}
    if not device_ids:
        return empty

    inputs = Input.query.filter(Input.unique_id.in_(list(device_ids))).all()

    by_key = {}
    valid = total = 0

    for inp in inputs:
        measurements = DeviceMeasurements.query.filter_by(
            device_id=inp.unique_id).all()
        renderable = []
        for dm in measurements:
            meta = channel_meta_for_dm(dm)
            key = meta.get('key')
            if not key or key in META_CHANNEL_KEYS:
                continue
            renderable.append((dm, meta))
        if not renderable:
            continue

        total += 1
        fresh_here = False
        for dm, meta in renderable:
            value = _last_value(inp.unique_id, dm.unique_id)
            if value is None:
                continue
            fresh_here = True
            entry = by_key.setdefault(meta['key'],
                                      {'sum': 0.0, 'n': 0,
                                       'unit': meta.get('unit') or ''})
            entry['sum'] += value
            entry['n'] += 1
        if fresh_here:
            valid += 1

    order = {k: i for i, k in enumerate(SENSOR_KEY_PRIORITY)}
    readings = [{'key': k,
                 'value': round(e['sum'] / e['n'], 2),
                 'unit': e['unit'],
                 'n': e['n']}
                for k, e in by_key.items()]
    readings.sort(key=lambda r: (order.get(r['key'], len(order)), r['key']))
    return {'readings': readings, 'sensors': {'valid': valid, 'total': total}}


def _sensor_rollup(device_ids, partial):
    """(rep, sensors) — 필지 행이 쓰는 축약형."""
    try:
        env = env_for_devices(device_ids)
    except Exception as exc:
        logger.warning('[SiteSummary] 환경 집계 실패: %s', exc)
        _mark(partial, 'children.sensors')
        return None, {'valid': 0, 'total': 0}
    return _pick_rep(env['readings']), env['sensors']


def _pick_rep(readings):
    """readings 는 이미 우선순위 순이라 첫 항목이 대표값이다."""
    if not readings:
        return None
    first = readings[0]
    return {
        'key': first['key'],
        'value': first['value'],
        'unit': first['unit'],
        'more': len(readings) > 1,
    }


def _last_value(device_id, measurement_id):
    """신선한 마지막 값(float) 또는 None. 오래된 값은 없는 것으로 친다."""
    from aot.utils.influx import get_last_measurement

    try:
        ts, value = get_last_measurement(device_id, measurement_id,
                                         max_age=FRESH_MAX_AGE_S)
    except Exception as exc:
        logger.debug('[SiteSummary] %s/%s 조회 실패: %s',
                     device_id, measurement_id, exc)
        return None
    if ts is None or value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


# ── 통신·배터리 ─────────────────────────────────────────────────────────────

def _link_status(device_ids, partial):
    from aot.aot_flask.geo.device_link_status import read_link_status_batch

    if not device_ids:
        return {}
    try:
        return read_link_status_batch(list(device_ids))
    except Exception as exc:
        logger.warning('[SiteSummary] link_status 실패: %s', exc)
        _mark(partial, 'children.issues')
        return {}


def _issue_counts(device_ids, link_status):
    comm_fault = battery_low = 0
    for uid in device_ids:
        status = link_status.get(uid)
        if not status:
            continue
        if status.get('comm_fault'):
            comm_fault += 1
        battery = status.get('battery') or {}
        percent = battery.get('percent')
        if percent is not None and percent <= BATTERY_LOW_PCT:
            battery_low += 1
    return {'comm_fault': comm_fault, 'battery_low': battery_low}


# ── 상태 판정 ───────────────────────────────────────────────────────────────

def _child_status(device_ids, sensors, issues):
    if not device_ids:
        return 'empty'
    if issues['comm_fault']:
        return 'fault'
    if issues['battery_low']:
        return 'warning'
    if sensors['total'] and sensors['valid'] < sensors['total']:
        return 'warning'
    return 'ok'


def status_from(device_ids, env=None):
    """장치 묶음의 상태 — 필지 행과 **같은 판정**.

    구역·시설 모달의 제목줄 상태 점이 쓴다. 계층마다 판정이 다르면 같은 점이
    화면마다 다른 뜻이 되어, 통일하려던 것이 오히려 혼란을 늘린다.

    `env` 를 이미 계산했으면 넘겨서 influx 재조회를 피한다.
    """
    if not device_ids:
        return 'empty'
    try:
        if env is None:
            env = env_for_devices(device_ids)
        issues = _issue_counts(device_ids, _link_status(device_ids, []))
        return _child_status(device_ids, env['sensors'], issues)
    except Exception as exc:
        logger.warning('[SiteSummary] 상태 판정 실패: %s', exc)
        return None


_STATUS_CACHE = {}
_STATUS_TTL_S = 30


_ZONE_STATUS_CACHE = {}
_ZONE_STATUS_TTL_S = 60


def zone_status_for_map(map_uuid):
    """지도의 구역별 대표값·상태 — `{zone_uuid: {...}}`. 60초 캐시.

    지도 라벨이 쓴다. **구역마다 따로 물으면 안 된다** — 통신 상태를 읽는
    read_link_status_batch 가 호출마다 데몬 왕복을 한 번 하므로, 구역 수만큼
    데몬을 두들기게 된다. 여기서는 지도 전체 장치를 모아 한 번만 읽는다.

    캐시 수명이 site 요약(30초)보다 긴 것은 의도적이다. 이건 지도 위에 늘
    떠 있는 라벨이라 갱신이 잦고, 구역 하나가 아니라 전부를 계산한다.
    """
    from aot.databases.models import GeoShape

    now = time.time()
    with _CACHE_LOCK:
        hit = _ZONE_STATUS_CACHE.get(map_uuid)
    if hit and hit[0] > now:
        return hit[1]

    result = {}
    try:
        zones = GeoShape.query.filter(
            GeoShape.geo_id == map_uuid, GeoShape.type == 'zone').all()

        ids_by_zone, all_ids = {}, set()
        for zone in zones:
            ids = _device_ids_for(zone)
            ids_by_zone[zone.unique_id] = ids
            all_ids |= ids

        link_status = _link_status(all_ids, [])

        for zone in zones:
            ids = ids_by_zone[zone.unique_id]
            env = env_for_devices(ids) if ids else {
                'readings': [], 'sensors': {'valid': 0, 'total': 0}}
            issues = _issue_counts(ids, link_status)
            result[zone.unique_id] = {
                'status': _child_status(ids, env['sensors'], issues),
                'rep': _pick_rep(env['readings']),
                'sensors': env['sensors'],
                'issues': issues,
            }
    except Exception as exc:
        logger.warning('[SiteSummary] 구역 상태 일괄 계산 실패(map=%s): %s',
                       map_uuid, exc)
        return {}

    with _CACHE_LOCK:
        _ZONE_STATUS_CACHE[map_uuid] = (now + _ZONE_STATUS_TTL_S, result)
    return result


def status_for_shape(shape_uuid):
    """도형(구역·시설) uuid → 상태. 30초 캐시.

    시설 overview 처럼 이미 무거운 응답에 얹히므로 캐시가 필수다 —
    판정 한 번이 도형 스캔 + influx 수 회다.
    """
    now = time.time()
    with _CACHE_LOCK:
        hit = _STATUS_CACHE.get(shape_uuid)
    if hit and hit[0] > now:
        return hit[1]

    from aot.databases.models import GeoShape

    shape = GeoShape.query.filter_by(unique_id=shape_uuid).first()
    status = _child_status_for_shape(shape) if shape is not None else None

    with _CACHE_LOCK:
        _STATUS_CACHE[shape_uuid] = (now + _STATUS_TTL_S, status)
    return status


def _child_status_for_shape(shape):
    return status_from(_device_ids_for(shape))


_STATUS_RANK = {'ok': 0, 'warning': 1, 'fault': 2}


def _rollup_status(children):
    """자식 중 최악값. `empty` 는 승격에 참여하지 않는다.

    장치 없는 관리동 하나가 필지 전체를 회색으로 만들면, 정작 문제 있는
    필지와 구분이 안 된다.
    """
    ranked = [c['status'] for c in children if c['status'] != 'empty']
    if not ranked:
        return 'empty'
    return max(ranked, key=lambda s: _STATUS_RANK.get(s, 0))


# ── 오늘 ────────────────────────────────────────────────────────────────────

def _today_block(site, device_ids, offline_total, partial):
    advice = _advice(site, partial)
    return {
        'schedule_count': _schedule_count(site, device_ids, partial),
        'advice_open': 1 if advice else 0,
        'offline_devices': offline_total,
        'advice_latest': advice,
    }


def _schedule_count(site, device_ids, partial):
    """오늘 예정된 작업 수.

    **대상이 장치인 것만 센다.** 함수·시퀀스를 대상으로 하는 일정까지 풀려면
    각 함수가 어느 구역에 속하는지 다시 해석해야 하는데, 그 해석이 이 팝업의
    비용을 두 배로 만든다. 이건 실패가 아니라 정의상의 축소라서 `partial` 에
    올리지 않는다 — 둘을 섞으면 "일부 실패"와 "원래 안 세는 것"을 구분할 수
    없다.
    """
    from aot.databases.models.scheduler import SchedulerJobMeta

    if not device_ids:
        return 0
    try:
        start, end = _local_day_bounds_utc(site)
        return SchedulerJobMeta.query.filter(
            SchedulerJobMeta.target_id.in_(list(device_ids)),
            SchedulerJobMeta.state.in_(('DRAFT', 'PENDING', 'RUNNING')),
            SchedulerJobMeta.schedule_time >= start,
            SchedulerJobMeta.schedule_time < end).count()
    except Exception as exc:
        logger.warning('[SiteSummary] 일정 조회 실패: %s', exc)
        _mark(partial, 'today.schedule')
        return 0


def _local_day_bounds_utc(site):
    """필지 현지 시각 기준 오늘의 UTC 경계 (start, end).

    UTC 로 하루를 자르면 한국 기준 오전 9시에 "오늘"이 바뀐다.
    """
    from datetime import datetime, timedelta

    tz = None
    try:
        from aot.utils.device_tz import resolve_location_tz
        tz = resolve_location_tz(site.unique_id)
    except Exception:
        tz = None

    if tz is None:
        from aot.utils.time_utils import utc_now
        now = utc_now()
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        return start, start + timedelta(days=1)

    local_now = datetime.now(tz)
    local_start = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
    local_end = local_start + timedelta(days=1)
    return (local_start.astimezone(_utc()).replace(tzinfo=None),
            local_end.astimezone(_utc()).replace(tzinfo=None))


def _utc():
    from datetime import timezone
    return timezone.utc


def _advice(site, partial):
    """이 지도(farm 스코프)의 최신 조언.

    site 스코프 조언은 아직 없다 — AISummaryService 의 어휘는 facility/farm/
    system 3종이다. 스코프가 생기면 여기만 바꾸면 되도록 응답 필드는 site
    스코프를 전제로 잡아 뒀다(docs/design/map-site-summary.md 미결-1).
    """
    try:
        from aot.ai.services.ai_summary_service import AISummaryService
        summary = AISummaryService.get_latest_summary(
            scope_type='farm', scope_id=site.geo_id)
    except Exception as exc:
        logger.warning('[SiteSummary] 조언 조회 실패: %s', exc)
        _mark(partial, 'today.advice')
        return None

    if summary is None or (summary.alert_level or 'none') == 'none':
        return None

    return {
        'title': (summary.summary_text or '').split('.')[0].strip(),
        'alert_level': summary.alert_level,
        'timestamp': (summary.timestamp.isoformat()
                      if summary.timestamp else None),
    }


# ── 노트 ────────────────────────────────────────────────────────────────────

def _notes_block(site, partial):
    """필지 도형에 붙은 최근 노트 2건.

    구역·장치에 붙은 노트까지 끌어오려면 note_ids_in_area 가 필요한데 그건
    Notes 전량을 순회한다. 팝업의 노트 줄은 "여기 적어 둔 게 있나"를 알리는
    자리이지 목록이 아니므로, 도형 자신에 붙은 것만 본다.

    날짜는 서식하지 않고 ISO 로 낸다 — 표시 시각대는 AoTTz 가 정한다.
    """
    from aot.databases.models import Notes

    try:
        rows = Notes.query.filter_by(target_id=site.unique_id).order_by(
            Notes.date_time.desc()).limit(2).all()
    except Exception as exc:
        logger.warning('[SiteSummary] 노트 조회 실패: %s', exc)
        _mark(partial, 'notes')
        return []

    out = []
    for row in rows:
        files = [f for f in (row.files or '').split(',') if f.strip()]
        out.append({
            'unique_id': row.unique_id,
            'note': row.note or '',
            'date_time': row.date_time.isoformat() if row.date_time else None,
            'files_count': len(files),
        })
    return out


# ── 잡동사니 ────────────────────────────────────────────────────────────────

def _shape_name(shape):
    props = _feature(shape).get('properties') or {}
    return (props.get('label_name') or props.get('name')
            or shape.unique_id)


def _shape_area_m2(shape):
    from aot.aot_flask.geo.facility_calc import polygon_area_m2

    geometry = _feature(shape).get('geometry') or {}
    try:
        return round(polygon_area_m2(geometry), 1)
    except Exception:
        return None


def _feature(shape):
    import json

    raw = shape.feature
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (ValueError, TypeError):
            return {}
    return raw if isinstance(raw, dict) else {}


def _now_iso():
    from aot.utils.time_utils import utc_now
    return utc_now().isoformat()


def _mark(partial, name):
    if name not in partial:
        partial.append(name)
