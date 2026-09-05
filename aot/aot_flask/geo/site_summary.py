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

# 측정값이 "살아 있다"고 보는 최대 나이(초)의 **하한**. 장치 주기가 이보다
# 길면 주기 × STALE_PERIOD_FACTOR 로 늘린다 — 고정값 하나로 판정하면 주기가
# 이 값과 같거나 더 긴 장치는 지터만으로 매 주기 경계마다 "꺼짐"으로 잘못
# 보인다(측정 시각과 조회 시각이 그 순간 우연히 어긋날 뿐인데도).
FRESH_MAX_AGE_S = 600

# 표시 경로 공통 배수 — `routes_general._PERIOD_LOOKBACK_FACTOR` 와 같은 값
# ("표본 2회 유실까지 견딘다"). `facility_sensors._max_age_for` 의 2배(표본
# 1회분)는 여기서는 부족했다 — 로컬에서 실측한 KMA_weather_500 입력(주기
# 300초)이 692초(2.3주기) 공백을 정상적으로 낸다. 이 드라이버는 그 자체가
# "유효 데이터 없음"을 단발로는 DEBUG 로만 남기고 6회 연속(=30분)부터 ERROR
# 로 올린다 — 몇 주기 정도의 공백은 설계상 정상이라는 뜻이라, 표시 판정도
# 그만큼 여유를 둬야 한다.
STALE_PERIOD_FACTOR = 3

# 이 아래면 교체 대상으로 센다. 경고이지 고장이 아니다.
BATTERY_LOW_PCT = 20

CACHE_TTL_S = 30

_CACHE = {}
_CACHE_LOCK = threading.Lock()
_BUILD_LOCKS = {}


# ── 캐시 + 단일 비행 ────────────────────────────────────────────────────────

#: 사전 하나가 들고 있을 수 있는 최대 항목 수.
#:
#: 예전에는 상한이 **없었다.** 키가 자원 uuid 하나뿐일 때는 자원 수가 곧
#: 상한이라 무해했는데, 창(기간·단위·단계)을 키에 넣는 순간 그 보호가
#: 사라진다 — 구획 44개 × 단계 6개 × 단위 2개 = 528 이고, 끝난 단계의 창은
#: 날짜가 고정이라 **다시 조회되지 않은 채 영원히 남는다.** 만료된 항목조차
#: 지우는 코드가 없었다(잠금 사전도 함께 자랐다).
#:
#: 512 는 "현실적인 동시 사용의 몇 배" 다. 넘으면 만료가 가까운 것부터
#: 버리므로, 지금 보고 있는 창이 밀려나는 일은 사실상 없다.
MAX_CACHE_ENTRIES = 512


def _evict(cache, locks, max_entries):
    """만료된 항목과 넘치는 항목을 버린다. **`_CACHE_LOCK` 을 쥔 채 부른다.**

    잠금 사전도 함께 줄인다 — 그러지 않으면 캐시만 비고 `locks` 는 계속
    자란다(키 하나당 `threading.Lock` 하나라 조용히 쌓인다).

    ⚠ **쥐고 있는 잠금은 지우지 않는다.** 지금 build() 를 도는 스레드의
      잠금을 지우면 다음 호출자가 새 잠금을 만들어, 같은 계산이 둘 돈다
      (틀린 값이 나오지는 않지만 단일 비행이 조용히 풀린다).
    """
    now = time.time()
    for k in [k for k, v in cache.items() if v[0] <= now]:
        del cache[k]
    over = len(cache) - max_entries
    if over > 0:
        # 만료가 **가까운 것부터** 버린다 — 방금 채운 것이 가장 늦게 만료되므로
        # 지금 보고 있는 창이 밀려나지 않는다.
        for k in sorted(cache, key=lambda k: cache[k][0])[:over]:
            del cache[k]
    for k in [k for k, lk in locks.items()
              if k not in cache and not lk.locked()]:
        del locks[k]


def cached_build(cache, locks, key, ttl_s, build, force=False,
                 max_entries=MAX_CACHE_ENTRIES):
    """TTL 캐시 + 키별 단일 비행. 모달 응답을 만드는 자리마다 쓴다.

    단일 비행이 캐시만큼 중요하다. 이 계산 하나가 influx 수십 질의라,
    같은 필지를 두 사람이 동시에 열거나 팝업이 폴링하는 동안 클릭이
    겹치면 **같은 계산이 그대로 곱해진다.** 저사양 호스트에서는 그
    팬아웃이 gunicorn 스레드풀을 삼켜, 사용자가 누른 요청이 큐에서
    기다린다(시설 모달에서 실측 1초+, 콜드 4초+).

    build() 가 None 을 주면 캐시에 넣지 않는다 — "못 찾음"을 30초 동안
    기억하면 방금 만든 도형이 그동안 없는 것이 된다.

    **상한은 여기 하나에 있다**(`_evict`). 사전마다 따로 두면 새 캐시를
    만드는 사람이 그것을 기억해야 하고, 기억하지 못한 사전만 조용히 샌다.
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
                # 넣은 **직후에만** 정리한다. 조회마다 훑으면 폴링이 잦은
                # 화면에서 그 비용이 그대로 요청에 붙는다.
                _evict(cache, locks, max_entries)
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


_PLANTING_CONTENTS_CACHE = {}
_PLANTING_CONTENTS_LOCKS = {}


_PLOT_ENV_WEEK_CACHE = {}
_PLOT_ENV_WEEK_LOCKS = {}
# 일별 버킷은 **하루에 한 번만** 바뀌고 오늘 열만 진행 중이다. 30초로 두면
# 근거 없이 InfluxDB 를 다시 훑는다. 반대로 너무 길면 오늘 열이 굳는다.
_PLOT_ENV_WEEK_TTL_S = 600


def env_week_key(base, days, end=None, unit='day', hidden=None):
    """주간 환경 계열의 캐시 키 — **창을 가르는 것을 전부 담는다.**

    `base` 는 무엇의 계열인가(구획 uuid, 시설이면 `시설uuid|동id`)이고,
    나머지가 창이다. 같은 대상이라도 창이 다르면 **다른 답**이다.

    ⚠ **라우트가 새 질의 인자를 받기 시작하면 반드시 여기도 더할 것.**
      키에 없는 축은 캐시에서 섞이고, 증상은 "다른 단계를 눌렀는데 같은
      그림" 이며 **에러가 나지 않는다.** 예전에 `?days=` 가 정확히 그
      상태였다 — 라우트는 받는데 키는 uuid 하나였다.

    키를 만드는 규칙이 **캐시 옆에** 있는 이유: 라우트마다 조립하면(구획·시설
    두 곳이 그랬다) 한쪽만 고쳐도 아무 신호가 없다.
    """
    # 감춘 목록도 답을 가른다(계열이 줄어든다). 순서에 안 흔들리게 정렬한다 —
    # 같은 집합이 다른 키가 되면 캐시가 그만큼 헛돈다.
    h = ','.join(sorted(str(k) for k in (hidden or ())))
    return '%s|d%s|e%s|%s|h%s' % (base, days, end or '', unit, h)


def cached_plot_env_week(key, build, force=False):
    """구획 모달의 주간 환경 계열 캐시 — **10분**.

    `cached_plot_contents`(30초)와 사전을 나누는 이유는 수명이 다르기
    때문이다. 같이 두면 둘 중 하나가 남의 주기로 끌려간다.

    ⚠ **키는 구획 uuid 하나가 아니다.** 같은 구획이라도 **창이 다르면 다른
    답**이다(기간·단위, 그리고 앞으로는 고른 단계). 예전에는 uuid 하나였고
    라우트가 `?days=` 를 받으면서도 그것을 키에 안 담아, 창을 바꿔 부르면
    **앞의 것이 그대로 나왔다**(에러 없이). 그때는 "화면이 기본값만 쓴다" 는
    전제로 버텼는데 그 전제가 곧 깨진다.

    키를 만드는 일은 **부르는 쪽**이 한다(`_env_week_key`) — 창을 정하는 것이
    라우트이고, 여기서 다시 조립하면 두 곳이 갈린다. 시설 쪽
    (`cached_facility_env_week`)이 이미 그 모양이다.
    """
    return cached_build(_PLOT_ENV_WEEK_CACHE, _PLOT_ENV_WEEK_LOCKS,
                        key, _PLOT_ENV_WEEK_TTL_S, build, force)


_FACILITY_ENV_WEEK_CACHE = {}
_FACILITY_ENV_WEEK_LOCKS = {}


def cached_facility_env_week(key, build, force=False):
    """시설 모달의 주간 환경 계열 캐시 — 구획과 같은 수명(10분).

    키는 `시설uuid|동id|창` 이다 — 다동 시설은 동마다 센서가 다르고, 같은
    동이라도 창이 다르면 다른 답이다(구획 쪽의 같은 경고 참조).
    """
    return cached_build(_FACILITY_ENV_WEEK_CACHE, _FACILITY_ENV_WEEK_LOCKS,
                        key, _PLOT_ENV_WEEK_TTL_S, build, force)


def cached_plot_contents(plot_uuid, build, force=False):
    """식생 구획 모달 응답 캐시 — 구역 모달과 **같은 수명**(30초).

    사전을 따로 두는 이유는 무효화 단위가 다르기 때문이다: 구획을 고치면 그
    구획만 버려야 하는데 하나를 같이 쓰면 uuid 공간이 섞여, 구역 무효화가
    구획 캐시를 함께 날리거나 그 반대가 된다.
    """
    return cached_build(_PLANTING_CONTENTS_CACHE, _PLANTING_CONTENTS_LOCKS,
                        plot_uuid, _ZONE_CONTENTS_TTL_S, build, force)


def invalidate_plot_contents(plot_uuid=None):
    """구획이 바뀐 직후(저장·종료·삭제) 부른다.

    `None` 이면 전부 버린다 — 새 구획이 생기면 **다른 구획의 응답도** 달라지기
    때문이다(같은 밸브를 공유하는 이웃의 `also_covers` 에 그 구획이 나타나야
    한다). 자기 것만 버리면 이웃 창은 30초 동안 "함께 젖는 것" 목록에서 새
    구획을 빠뜨린 채로 보인다.
    """
    with _CACHE_LOCK:
        if plot_uuid is None:
            _PLANTING_CONTENTS_CACHE.clear()
            # 주간 계열도 함께 버린다 — 프로그램·단계가 바뀌면 목표대가
            # 달라지므로 10분을 기다리면 옛 목표 위에 새 값이 그려진다.
            _PLOT_ENV_WEEK_CACHE.clear()
        else:
            _PLANTING_CONTENTS_CACHE.pop(plot_uuid, None)
            _PLOT_ENV_WEEK_CACHE.pop(plot_uuid, None)


def invalidate_zone_contents_all():
    """구역 모달 캐시 전량 폐기.

    식생 구획이 바뀌었을 때 쓴다 — 구획의 소속 구역은 저장돼 있지 않고 기하에서
    파생되므로, 기하를 옮기면 "전" 과 "후" 두 구역이 함께 낡는다. 어느 쪽인지
    따지느니 전부 버린다(30초 캐시다).
    """
    with _CACHE_LOCK:
        _ZONE_CONTENTS_CACHE.clear()


def invalidate_zone_contents(zone_uuid):
    """구역 내용이 바뀐 직후(사진 교체·장치 순서 저장) 부른다.

    안 부르면 방금 올린 사진이 30초 동안 안 보인다 — 저장은 됐는데 화면이
    안 바뀌는 것만큼 사람을 헷갈리게 하는 게 없다.
    """
    with _CACHE_LOCK:
        _ZONE_CONTENTS_CACHE.pop(zone_uuid, None)


def invalidate_rep(shape):
    """대표 측정 지정이 바뀐 직후 부른다 — **그 값을 쓰는 캐시만** 버린다.

    rep_key 를 읽는 곳은 셋뿐이다: 구역 모달 응답, 지도 라벨의 구역 상태
    (지도 단위), 필지 요약의 자식 행(필지 단위). 전체 `invalidate()` 를
    부르면 편하지만 `_PARENT_CACHE` 까지 함께 날아간다 — 그건 지도 도형 전량을
    shapely 로 훑어 만드는 이 모듈에서 가장 비싼 캐시이고, 대표 측정과는 아무
    상관이 없다. 값 하나 바꿨다고 그걸 다시 만들게 할 이유가 없다.
    """
    if shape is None:
        return
    with _CACHE_LOCK:
        _ZONE_CONTENTS_CACHE.pop(shape.unique_id, None)
        _ZONE_STATUS_CACHE.pop(getattr(shape, 'geo_id', None), None)
    # 필지 요약은 상위 site 를 찾아야 한다(캐시된 부모 색인을 그대로 쓴다).
    try:
        parent = parent_site_for_shape(shape.unique_id)
    except Exception:
        parent = None
    if parent:
        with _CACHE_LOCK:
            _CACHE.pop(parent['uuid'], None)


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

    # 측정값도 **한 번에** 읽는다 — 통신 상태를 한 번에 읽는 것과 같은 이유다.
    # 자식마다 채널 수만큼 Influx 를 치면 시설 10개짜리 필지에서 100회를 넘고,
    # 그것이 이 엔드포인트가 6~7초 걸리던 원인이었다(라즈베리파이 실측).
    # 실패해도 값이 사라지지 않는다 — 사전 조회가 없는 것은 곧 개별 조회다.
    try:
        prefetched = prefetch_last_values(all_ids)
    except Exception as exc:
        logger.warning('[SiteSummary] 값 사전 조회 실패: %s', exc)
        prefetched = {}

    children = []
    for shape in children_shapes:
        # **열 수 없는 것은 목록에 넣지 않는다.** `type='facility'` 인데
        # `GeoFacility` 행이 없는 도형이 실제로 있다(geo/design 에서 시설
        # 종류로 그렸지만 시설 등록은 안 한 경우 — 로컬 실측 4건). 그런 줄은
        # 이름이 없어 "이름 없음" 으로 뜨고, 눌러도 시설 모달이 열 대상을
        # 못 찾아 **아무 일도 일어나지 않는다** — 존재하지 않는 링크다.
        #
        # 도형은 지도에 계속 그려진다. 목록이 담는 것은 "이 필지에 무엇이
        # 있나" 가 아니라 **"어디로 내려갈 수 있나"** 다.
        if shape.type == 'facility' and not _facility_of_shape(shape.unique_id):
            continue
        children.append(_child_entry(shape, ids_by_child[shape.unique_id],
                                     link_status, partial,
                                     prefetched=prefetched))

    offline_total = sum(c['issues']['comm_fault'] for c in children)

    return {
        'site': {
            'uuid': site.unique_id,
            'name': _shape_name(site),
            # 사람이 적은 설명. `meta_json` 에 있다(도형 저장이 건드리지 않는
            # 유일한 자리 — `feature` 에 두면 지도를 다시 그릴 때 사라진다).
            'description': (site.meta_json or {}).get('description') or '',
            'area_m2': _shape_area_m2(site),
            'status': _rollup_status(children),
            'counts': dict({
                'zones': sum(1 for c in children if c['kind'] == 'zone'),
                'facilities': sum(1 for c in children if c['kind'] == 'facility'),
                'devices': len(all_ids),
            }, **_plot_counts(site)),
        },
        'children': children,
        # 다가오는 일정 — 구역·식생·시설과 **같은 창(지금부터)·같은 목록**이다.
        # 예전에는 여기만 "오늘 N건" 숫자라서, 대지가 0인데 구역을 열면 내일
        # 일이 있는 상태가 났다(실측). 자식 도형까지 넣는 것은 롤업이라서다.
        'schedule': upcoming_schedule(
            site, all_ids, [c.unique_id for c in children_shapes]),
        'today': _today_block(site, all_ids, offline_total, partial,
                              [c.unique_id for c in children_shapes]),
        'notes': _notes_block(site, partial),
        'generated_at': _now_iso(),
        'partial': partial,
    }


def _plot_counts(site):
    """필지 안에서 구획 대상 종수·구획 수 → `{'subjects', 'plots'}`.

    **작물 이름을 구역 행에 넣지 않는다.** 그 행은 이미 `이름 | 값 | 상태`
    3열이라 거기에 작물을 이어붙이면 한 열이 두 가지를 말하게 되고 열 간격이
    틀어진다. 필지에서 알고 싶은 것은 "여기 몇 가지가 자라고 있나" 라는 규모
    감각이므로 숫자 타일 하나로 낸다.

    실패해도 필지 요약 전체를 막지 않는다 — 식생이 없는 지도가 정상이다.
    """
    try:
        from aot.aot_flask.geo import plot_context

        rows = plot_context.active_plots(site.geo_id)
        if not rows:
            return {'subjects': 0, 'plots': 0}

        site_geom = plot_context.geometry_of(site)
        inside = []
        for row in rows:
            covered = plot_context.plots_covered_by_shape(
                site_geom, site.geo_id, candidates=[row])
            if covered:
                inside.append(row)
        return {'subjects': len({r.subject for r in inside if r.subject}),
                'plots': len(inside)}
    except Exception:
        logger.exception('site summary: 식생 집계 실패')
        return {'subjects': 0, 'plots': 0}


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


def _child_entry(shape, device_ids, link_status, partial, prefetched=None):
    rep, sensors = _sensor_rollup(device_ids, partial, rep_key_of(shape),
                                  prefetched=prefetched)
    issues = _issue_counts(device_ids, link_status)

    # 이름이 없으면 **빈 문자열**로 낸다 — uuid 를 그대로 내보내면 목록에
    # "e05c9d51-093f-…" 가 찍힌다(이름 없는 도형은 실제로 있다: geo/design 에서
    # 시설 종류로 그렸지만 `GeoFacility` 행이 없는 경우). 화면이 그 자리에
    # 무엇을 보일지 정한다 — 서버가 uuid 를 사람에게 보이는 값으로 쓰지 않는다.
    _name = _shape_name(shape)
    return {
        'uuid': shape.unique_id,
        'kind': 'facility' if shape.type == 'facility' else 'zone',
        'name': '' if _name == shape.unique_id else _name,
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

def prefetch_last_values(device_ids):
    """`(device_id, measurement_id) → 값|None` 을 **한 번에** 읽어 둔다.

    필지 요약은 자식(구역·시설)마다 `env_for_devices` 를 부르고, 그것이 다시
    장치의 채널마다 Influx 를 한 번씩 친다. 채널이 곱해지므로 시설 10개짜리
    필지에서 100회를 넘고, 한 번이 수십 ms 라 그대로 초 단위가 된다 —
    라즈베리파이 테스트 서버 실측에서 이 엔드포인트 하나가 **6~7초**였다.
    `query_last_values_bulk` 가 그것을 창(max_age)당 한 번으로 접는다.

    Returns:
        dict. **키가 있으면 그것이 답이다**(값 또는 None=신선한 값 없음).
        키가 없으면 "사전 조회하지 못했다" 이므로 호출부가 개별 조회로
        되돌아간다. 그래서 사전 조회가 실패해도 값이 사라지지 않고 느려질
        뿐이다.

    ⚠ 빈 dict 를 "값이 하나도 없다" 로 읽으면 안 된다 — 그 둘을 가르는 것이
    `query_last_values_bulk_status` 의 `ok` 다. 측정이 아직 하나도 없는 설치
    (갓 만든 서버)에서는 전부 miss 인데, 그것을 실패로 보면 개별 조회로 전부
    되돌아가 **가장 느린 경우에 최적화가 통째로 꺼진다.**
    """
    from aot.databases.models import Conversion, DeviceMeasurements, Input
    from aot.utils.influx import bulk_key, query_last_values_bulk_status
    from aot.utils.measurement_freshness import effective_max_age
    from aot.utils.system_pi import return_measurement_info

    out = {}
    ids = [d for d in (device_ids or []) if d]
    if not ids:
        return out

    inputs = Input.query.filter(Input.unique_id.in_(ids)).all()
    if not inputs:
        return out

    rows = DeviceMeasurements.query.filter(
        DeviceMeasurements.device_id.in_([i.unique_id for i in inputs])).all()
    conv_ids = {r.conversion_id for r in rows if r.conversion_id}
    conversions = {}
    if conv_ids:
        conversions = {c.unique_id: c for c in Conversion.query.filter(
            Conversion.unique_id.in_(list(conv_ids))).all()}
    by_device = {}
    for row in rows:
        by_device.setdefault(row.device_id, []).append(row)

    # 창(max_age)이 다르면 한 쿼리로 합칠 수 없다 — 주기가 같은 장치끼리 묶인다.
    # 창을 가장 긴 것으로 통일해 한 번에 치지 않는 이유: 하루짜리 장치 하나가
    # 나머지 전부의 스캔 범위까지 하루로 넓혀 버린다.
    by_age = {}
    for inp in inputs:
        max_age = effective_max_age(None, inp.period, inp.max_age_s,
                                    floor=FRESH_MAX_AGE_S,
                                    factor=STALE_PERIOD_FACTOR)
        for row in by_device.get(inp.unique_id, []):
            channel, unit, measure = return_measurement_info(
                row, conversions.get(row.conversion_id))
            if not unit:
                continue
            by_age.setdefault(int(max_age), []).append(
                (inp.unique_id, row.unique_id, unit, channel, measure))

    for max_age, items in by_age.items():
        try:
            found, ok = query_last_values_bulk_status(
                [(unit, dev, ch, meas) for dev, _mid, unit, ch, meas in items],
                past_sec=max_age)
        except Exception as exc:
            logger.warning('[SiteSummary] 값 사전 조회 실패(max_age=%s): %s',
                           max_age, exc)
            continue
        if not ok:
            continue
        for dev, mid, unit, ch, meas in items:
            hit = found.get(bulk_key(unit, dev, ch, meas))
            value = None
            if hit is not None:
                try:
                    value = float(hit[1])
                except (TypeError, ValueError):
                    value = None
            out[(dev, mid)] = value
    return out


def env_for_devices(device_ids, prefetched=None):
    """장치 묶음의 현재 환경 — `{'readings': [...], 'sensors': {...}}`.

    구역 모달도 같은 답이 필요해서 공용으로 뺐다(routes_geo 의 zone contents).
    한쪽만 고치면 같은 구역이 필지 요약과 구역 모달에서 다른 온도를 말한다.

    readings 는 채널 key 별 평균이다. 메타 채널(rssi/snr/battery)은 뺀다 —
    빼기 전에는 하트비트 채널이 0번인 LoRaWAN 노드가 온도 대신 배터리 전압을
    대표값으로 내세웠다. 정렬은 SENSOR_KEY_PRIORITY 순이라 첫 항목이 곧 대표값이다.

    `prefetched`(`prefetch_last_values` 의 결과)를 주면 Influx 를 채널마다 치지
    않는다. **키가 있으면 그 값이 답이고**(None 이면 신선한 값 없음), 없으면
    개별 조회로 되돌아간다 — 사전 조회를 못 한 장치가 섞여도 값이 비지 않는다.

    안 주면 **여기서 한 번 뜬다.** 그래야 이 함수를 그냥 부르는 자리(구역
    모달)도 왕복이 채널 수만큼 늘지 않는다. 여러 묶음을 도는 호출자만
    `prefetch_last_values` 를 자기가 불러 **전체를 한 번에** 접으면 된다
    (필지 요약이 그렇게 한다) — 묶음마다 맡기면 묶음 수만큼 쿼리가 된다.
    빈 dict 를 넘기는 것과 None 은 다르다: 빈 dict 는 "이미 시도했고 못 얻었다"
    이므로 다시 뜨지 않는다.
    """
    from aot.aot_flask.geo.facility_sensors import (
        META_CHANNEL_KEYS, channel_meta_for_dm)
    from aot.databases.models import DeviceMeasurements, Input

    empty = {'readings': [], 'sensors': {'valid': 0, 'total': 0}}
    if not device_ids:
        return empty

    inputs = Input.query.filter(Input.unique_id.in_(list(device_ids))).all()
    if not inputs:
        return empty

    # 장치마다 다시 묻지 않는다 — 자식 수 × 장치 수만큼 반복되던 자리다.
    by_device = {}
    for row in DeviceMeasurements.query.filter(
            DeviceMeasurements.device_id.in_(
                [i.unique_id for i in inputs])).all():
        by_device.setdefault(row.device_id, []).append(row)

    if prefetched is None:
        try:
            prefetched = prefetch_last_values([i.unique_id for i in inputs])
        except Exception as exc:
            logger.warning('[SiteSummary] 값 사전 조회 실패: %s', exc)
            prefetched = {}

    by_key = {}
    valid = total = 0

    for inp in inputs:
        renderable = []
        for dm in by_device.get(inp.unique_id, []):
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
            hit = (inp.unique_id, dm.unique_id)
            if hit in prefetched:
                value = prefetched[hit]
            else:
                value = _last_value(inp.unique_id, dm.unique_id,
                                    period=inp.period,
                                    device_max_age=inp.max_age_s)
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


def live_device_ids(device_ids, prefetched=None):
    """지금 값을 주고 있는 장치만 남긴다 → set.

    판정은 `env_for_devices` 하나로 한다 — 여기서 따로 세면 같은 센서를 두고
    한 화면은 살아 있다 하고 다른 화면은 죽었다 한다(`_env_of` 가 그것을
    그대로 쓰는 것과 같은 이유).

    쓰이는 자리는 **폴백 후보 고르기**다. 구획 안에 센서가 없어 옆에서
    끌어올 때, 거리만 보고 고르면 값을 못 주는 것을 골라 놓고 화면은 그대로
    빈다(실측 2026-09-04, 김제 3-2 청자5호).

    조회가 실패하면 **살아 있는 것으로 본다** — 실패를 죽음으로 읽으면
    인플럭스가 잠깐 흔들릴 때마다 화면이 옆 센서로 갈아탄다.

    값 조회는 **한 번만** 뜬다(`prefetch_last_values`). 장치마다 뜨면 왕복이
    후보 수만큼 는다.
    """
    ids = [d for d in (device_ids or []) if d]
    if not ids:
        return set()

    if prefetched is None:
        try:
            prefetched = prefetch_last_values(ids)
        except Exception as exc:
            logger.warning('[SiteSummary] 값 사전 조회 실패: %s', exc)
            prefetched = {}

    out = set()
    for device_id in ids:
        try:
            env = env_for_devices([device_id], prefetched=prefetched)
        except Exception as exc:
            logger.warning('[SiteSummary] 센서 신선도 판정 실패(%s): %s',
                           device_id, exc)
            out.add(device_id)
            continue
        if (env.get('sensors') or {}).get('valid', 0) > 0:
            out.add(device_id)
    return out


def _sensor_rollup(device_ids, partial, rep_key=None, prefetched=None):
    """(rep, sensors) — 필지 행이 쓰는 축약형."""
    try:
        env = env_for_devices(device_ids, prefetched=prefetched)
    except Exception as exc:
        logger.warning('[SiteSummary] 환경 집계 실패: %s', exc)
        _mark(partial, 'children.sensors')
        return None, {'valid': 0, 'total': 0}
    return _pick_rep(env['readings'], rep_key), env['sensors']


def rep_key_of(shape):
    """도형에 지정된 대표 측정 key(없으면 None).

    사용자가 구역 모달의 현재 블록에서 값을 눌러 정한다. 도형에 붙어 있으므로
    지도 라벨·필지 요약·구역 모달이 **한 값**을 본다 — 위젯 옵션에 두면 같은
    구역이 대시보드마다 다른 것을 대표로 내세운다.
    """
    meta = getattr(shape, 'meta_json', None) or {}
    key = meta.get('rep_key')
    return key if isinstance(key, str) and key else None


# [현황]의 카드 안에서 **빼 둔 항목**. 카드별 key 목록이다.
#
#   {'now': ['RH', 'dewpoint'], 'control': ['curtain']}
#
# `rep_key` 와 같은 자리(도형 meta_json)에 둔다. 이유도 같다 — 어디에서 보든
# 같은 곳은 같은 것을 보여야 하고, 위젯 옵션에 두면 같은 시설이 대시보드마다
# 다른 항목을 감춘다. **감추는 것은 화면의 일이라 서버는 값을 계속 보낸다** —
# 여기서 걸러 버리면 설정 창이 "무엇을 감출 수 있는지" 를 목록으로 만들 수
# 없고(감춘 것이 응답에서 사라져 다시 켤 수단이 없어진다), 대표값·지도 라벨
# 같은 다른 소비처까지 함께 눈이 먼다.
_HIDDEN_ROW_CARDS = ('now', 'control')


def hidden_rows_of(shape):
    """도형에 지정된 '카드에서 빼 둔 항목' (없으면 빈 dict)."""
    meta = getattr(shape, 'meta_json', None) or {}
    raw = meta.get('hidden_rows')
    if not isinstance(raw, dict):
        return {}
    out = {}
    for card in _HIDDEN_ROW_CARDS:
        vals = raw.get(card)
        if not isinstance(vals, list):
            continue
        keys = [k for k in vals if isinstance(k, str) and k]
        if keys:
            out[card] = keys
    return out


def hidden_rows_for_shape(shape_uuid):
    """도형 uuid 로 바로 읽는다 — 도형 객체를 이미 들고 있지 않은 호출부용.

    구획(`GeoPlot`)처럼 **자기 설정을 갖지 않고 상위 것을 물려받는** 자리가
    쓴다. 없거나 못 찾으면 빈 dict — 상위를 못 찾은 것과 상위가 아무것도
    감추지 않은 것은 화면에서 같은 결과라야 한다(못 찾았다고 전부 감추면
    구획 창이 통째로 비고, 원인은 어디에도 안 보인다).
    """
    if not shape_uuid:
        return {}
    from aot.databases.models import GeoShape
    shape = GeoShape.query.filter_by(unique_id=shape_uuid).first()
    return hidden_rows_of(shape) if shape is not None else {}


def hidden_rows_for_facility(facility_uuid):
    """시설 uuid → 그 시설 도형의 설정. 시설은 도형을 한 겹 건너 갖는다."""
    if not facility_uuid:
        return {}
    from aot.databases.models import GeoFacility
    row = GeoFacility.query.filter_by(unique_id=facility_uuid).first()
    return hidden_rows_for_shape(row.shape_uuid) if row is not None else {}


def _pick_rep(readings, rep_key=None):
    """대표값 하나. 지정이 있으면 그것, 없으면 우선순위 첫 항목.

    지정한 측정이 지금 값을 내지 못하면(센서 두절·미설치) 지정을 지우지 않고
    **그때만** 우선순위로 물러선다 — 센서가 돌아오면 지정이 그대로 살아난다.
    """
    if not readings:
        return None
    first = readings[0]
    if rep_key:
        for r in readings:
            if r['key'] == rep_key:
                first = r
                break
    # 'more'(뒤에 더 있음)는 내지 않는다 — 라벨에 붙던 ' +' 를 뗐다(2026-08-10).
    # 좁은 라벨에서 그 한 글자가 숫자를 밀어내는데, "더 있다"는 사실만으로는
    # 아무 판단도 못 한다. 더 보려면 어차피 눌러서 창을 연다.
    return {
        'key': first['key'],
        'value': first['value'],
        'unit': first['unit'],
    }


def _last_value(device_id, measurement_id, period=None, device_max_age=None):
    """신선한 마지막 값(float) 또는 None. 오래된 값은 없는 것으로 친다.

    `period`(장치 샘플링 주기, 초)를 넘기면 `period × STALE_PERIOD_FACTOR` 로
    유효 수명을 정한다 — `FRESH_MAX_AGE_S` 는 그 하한일 뿐이다. 주기와 같은
    고정값으로 판정하면 여유가 0이라, 지터 몇 초에도 매 주기 경계마다
    "꺼짐"으로 잘못 보인다.

    `device_max_age`(`Input.max_age_s`)가 있으면 그것이 이긴다 — 주기가
    "얼마나 자주 재는가" 라면 이 값은 "얼마나 늦어도 되는가" 로, 후자를 아는
    것은 배수가 아니라 그 장치를 설치한 사람이다. 판정 순서의 정본은
    `measurement_freshness.effective_max_age`.
    """
    from aot.utils.influx import get_last_measurement
    from aot.utils.measurement_freshness import effective_max_age

    max_age = effective_max_age(None, period, device_max_age,
                                floor=FRESH_MAX_AGE_S,
                                factor=STALE_PERIOD_FACTOR)
    try:
        ts, value = get_last_measurement(device_id, measurement_id,
                                         max_age=max_age)
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

def _today_block(site, device_ids, offline_total, partial, child_uuids=()):
    advice = _advice(site, partial)
    return {
        'schedule_count': _schedule_count(site, device_ids, partial, child_uuids),
        'advice_open': 1 if advice else 0,
        'offline_devices': offline_total,
        'advice_latest': advice,
    }


# 아직 일어나지 않은 일정의 상태들. 한 곳에 둔다 — 세는 곳과 목록을 내는 곳이
# 다른 집합을 쓰면 "3건 예정" 인데 목록에는 2건만 나온다.
SCHEDULE_LIVE_STATES = ('DRAFT', 'PENDING', 'RUNNING')


def schedule_targets(shape, device_ids, child_uuids=()):
    """이 계층에 걸린 일정의 **대상 집합**.

    `SchedulerJobMeta.target_id` 는 장치 id 만 담지 않는다 — 실제 데이터에는
    site·zone 도형 uuid 를 대상으로 한 농작업 이벤트("제초작업 - 투입인원
    4명…")가 들어 있다. 예전에는 장치 id 만 봐서 **그 계층 자신에게 걸린
    일정이 그 계층 모달에서 영영 안 보였다**(실측: 1포장에 자기 uuid 를
    대상으로 한 활성 이벤트가 있는데 그 모달의 집계는 0이었다).

    자식 도형까지 넣는 이유는 이 값이 **롤업**이기 때문이다 — 필지 요약은
    이미 하위 구역의 장치·상태를 합산해 보여준다. 일정만 자기 것으로 좁히면
    같은 화면 안에서 기준이 갈린다.
    """
    targets = set(device_ids or ())
    if shape is not None and getattr(shape, 'unique_id', None):
        targets.add(shape.unique_id)
    targets.update(u for u in (child_uuids or ()) if u)
    return targets


def _schedule_count(site, device_ids, partial, child_uuids=()):
    """오늘 예정된 작업 수.

    **함수·시퀀스를 대상으로 하는 일정은 세지 않는다.** 각 함수가 어느 구역에
    속하는지 다시 해석해야 하는데, 그 해석이 이 팝업의 비용을 두 배로 만든다.
    이건 실패가 아니라 정의상의 축소라서 `partial` 에 올리지 않는다 — 둘을
    섞으면 "일부 실패"와 "원래 안 세는 것"을 구분할 수 없다.
    """
    from aot.databases.models.scheduler import SchedulerJobMeta

    targets = schedule_targets(site, device_ids, child_uuids)
    if not targets:
        return 0
    try:
        start, end = _local_day_bounds_utc(site)
        return SchedulerJobMeta.query.filter(
            SchedulerJobMeta.target_id.in_(list(targets)),
            SchedulerJobMeta.state.in_(SCHEDULE_LIVE_STATES),
            SchedulerJobMeta.schedule_time >= start,
            SchedulerJobMeta.schedule_time < end).count()
    except Exception as exc:
        logger.warning('[SiteSummary] 일정 조회 실패: %s', exc)
        _mark(partial, 'today.schedule')
        return 0


def upcoming_schedule(shape, device_ids, extra_targets=(), limit=5):
    """다가오는 일정 → `{'own': [...], 'devices': [...]}` (없으면 빈 목록).

    **"오늘"이 아니라 "지금부터"** 인 이유: 구역 하나에 오늘 잡힌 일이 있는
    날은 드물어서, 오늘만 보이면 그 블록은 대부분 비어 있다. 빈 블록은 화면에
    노이즈로만 남는다. 필지의 숫자 타일은 창이 고정돼야 뜻이 서므로 "오늘"을
    그대로 둔다 — 세는 것과 나열하는 것은 다른 질문이다.

    `own` 은 이 도형(과 `extra_targets`)을 대상으로 한 일정, `devices` 는 하위
    장치의 예약이다. 화면은 둘을 한 목록으로 합쳐 보여준다 — 시스템에 그런
    구분이 없어서다(buildScheduleHtml 주석). 나눠 담는 것은 호출자가 필요하면
    쓰라는 것뿐이다.

    `extra_targets` 는 "이 도형과 **같은 것을 가리키는** 다른 id" 다:
      * site      직속 자식 도형들(롤업 — 필지 요약은 이미 하위를 합산한다)
      * facility  GeoFacility uuid. 시설은 정체성이 둘이다 — 노트·일정은
                  GeoFacility uuid 로 붙는데 장치·기하는 GeoShape 쪽에 있어서,
                  도형 uuid 만 보면 방금 만든 일정이 그 시설 화면에서 안 보인다
                  (실제로 그렇게 나갔다).
    """
    from aot.databases.models.scheduler import SchedulerJobMeta
    from aot.ai.services.aot_data_tool_service import AoTDataToolService
    from aot.utils.time_utils import utc_now

    shape_targets = set()
    if shape is not None and getattr(shape, 'unique_id', None):
        shape_targets.add(shape.unique_id)
    shape_targets.update(u for u in (extra_targets or ()) if u)
    dev_targets = set(device_ids or ())
    if not shape_targets and not dev_targets:
        return {'own': [], 'devices': [], 'total': 0}

    try:
        rows = SchedulerJobMeta.query.filter(
            SchedulerJobMeta.target_id.in_(list(shape_targets | dev_targets)),
            SchedulerJobMeta.state.in_(SCHEDULE_LIVE_STATES),
            SchedulerJobMeta.schedule_time.isnot(None),
            SchedulerJobMeta.schedule_time >= utc_now().replace(tzinfo=None),
        ).order_by(SchedulerJobMeta.schedule_time.asc()).limit(limit * 4).all()
    except Exception as exc:
        logger.warning('[SiteSummary] 예정 일정 조회 실패: %s', exc)
        return {'own': [], 'devices': [], 'total': 0}

    # `total` 은 **표시 상한을 넘은 것이 있는지** 말하기 위한 것이다. 5건만
    # 보여주고 더 있다는 말이 없으면 사용자는 그것이 전부라고 읽는다 —
    # "없는 것" 과 "안 보여준 것" 이 같은 화면이 되면 안 된다.
    out = {'own': [], 'devices': [], 'total': len(rows)}
    for row in rows:
        # 직렬화는 AI 도구와 **같은 함수**를 쓴다 — 앵커 tz 로 벽시계를 맞추는
        # 규칙(§7)이 거기 하나뿐이라, 여기서 다시 만들면 같은 일정이 화면과
        # AI 답변에서 다른 시각으로 나온다.
        try:
            item = AoTDataToolService._schedule_summary(row)
        except Exception:
            logger.exception('[SiteSummary] 일정 직렬화 실패')
            continue
        bucket = 'own' if row.target_id in shape_targets else 'devices'
        if len(out[bucket]) < limit:
            out[bucket].append(item)
    return out


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
