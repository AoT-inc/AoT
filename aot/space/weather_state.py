# coding=utf-8
"""지도 위젯 기상 표현이 쓰는 **한 벌의 기상 상태** — ``GET /api/geo/weather_state``.

사용자가 고른 출처의 현재 기상 값과 태양 위치를 하나로 묶는다. 프런트(``aot-map-ambient.js``)는
이 응답으로

* 오버레이 강도(운량)와 관측 지연(0.5배),
* 주야 바닥 보정과 3D 조명(태양 고도·방위·단계),
* 측정값 독의 기상 묶음(강수·바람·운량·시정·위험·관측시각)

을 정한다. 설계: plans/2026-10-19_map_weather_daynight_proposal.md 3·4-1·5절,
plans/handoff_20261019_map_ambient_p2b_sources.md.

## 출처는 사용자가 정한다

공통 코드에는 제공자(KMA·Open-Meteo 등)도 지역도 없다. 값은 두 갈래에서만 온다.

* **gis-input** — 지도에 등록된 gis-input 중 표준 메서드 ``get_ambient_values(lat, lng)`` 를
  덮어쓴 모듈(레이어가 꺼져 있어도 쓴다). 그 입력의 "기상 데이터로 사용"
  (``use_for_ambient``, 기본 켬)을 끄면 빠진다. 같은 종류 안에서는 레이어 순서
  (레이어 페이지에서 정렬한 ``position_y``, 같으면 등록 순서).
* **현장 장치** — 대지에 기상대로 **지정(bound)** 한 장치의 측정값. 측정값으로 추론한
  장치는 쓰지 않는다. 같은 종류 안에서는 기상대 지정 순서.

두 갈래 중 어느 쪽이 먼저인지는 위젯 옵션 ``ambient_source_order``(기본 현장 장치 먼저).
항목마다 처음 값이 있는 출처를 쓰고, 관측 시각이 ``max_measure_age`` 보다 오래된 값은
다음 출처로 넘긴다. 출처가 하나도 없으면 항목이 비고, 화면은 칸도 연출도 만들지 않는다.

위험 칸은 현재값과 위젯 옵션의 문턱 3개(풍속·강수·기온)로만 판정한다. 예보 위험은 이번
범위가 아니다 — 나중에 gis-input 표준 메서드(예: ``get_ambient_forecast``)가 ``collect_hazards``
옆에 붙을 자리만 남겨 둔다.

## 시각 ``t`` (지도 위젯 시간 슬라이더, P3)

``t`` 가 없거나 지금과 5분 안이면 위와 똑같이 지금의 값이다. ``t`` 가 미래면 **gis-input 의 예보 표준 메서드**
(``get_ambient_forecast``)에서만, 과거면 대지 기상대 장치의 **측정 이력**과 gis-input 의 이력 표준 메서드
(``get_ambient_history``)에서 온다. 순서·"기상 데이터로 사용"·허용 지연은 지금 값과 같은 규칙이다. 태양 위치는
항상 ``t`` 기준이다. 그 시각의 값을 줄 출처가 없으면 ``items`` 가 비고, 화면은 칸도 연출도 만들지 않는다.
지금 값의 응답에는 ``timeline``(예보·이력이 가능한 구간)이 실려, 슬라이더가 범위를 정하는 데 쓴다.
응답에는 ``mode``(now|forecast|history)와 ``t``(ms)가 붙고, 예보 출처가 신뢰도를 주면 ``confidence`` 가 실린다.

## 모든 외부 호출은 실패해도 응답을 막지 않는다

gis-input 이 느리거나 키가 없어도 태양 위치와 있는 값만으로 응답한다. gis-input 결과는
레이어·좌표별로 5분 캐시하고, 현장 장치 값은 매번 읽는다.
"""
import logging
import re
import time

from aot.utils.timekit import parse_utc

from aot.inputs_gis.ambient_roles import (
    AMBIENT_ITEM_UNITS, ambient_max_age_override, ambient_source_enabled, normalize_ambient_values,
    normalize_forecast_range)

logger = logging.getLogger(__name__)

CACHE_TTL_S = 300.0
# gis-input 이 값을 못 줬을 때(시간 초과·키 없음)는 더 빨리 다시 시도한다.
FAIL_RETRY_S = 60.0
# 관측이 이보다 오래되면 프런트가 강도를 0.5배로 낮추고 "관측 지연"을 표시한다.
STALE_OBS_MIN = 30.0

#: 항목 키 → 표시 단위. 값 자체의 단위는 항상 이 표와 같다(출처가 달라도 환산해서 맞춘다).
ITEM_UNITS = AMBIENT_ITEM_UNITS
_ITEM_ORDER = ('precip', 'wind_speed', 'wind_dir', 'cloud', 'visibility', 'temp',
               'precip_type', 'lightning', 'lightning_km')

SOURCE_ORDERS = ('field_first', 'gis_first')

# ── 시간 축 ──
#: ``t`` 가 지금과 이 안이면 "지금"으로 본다(초).
TIME_TOLERANCE_S = 300.0
#: ``t`` 가 지금에서 이보다 멀면 거절한다(초) — 슬라이더는 이 안에서만 움직인다.
TIME_LIMIT_S = 30 * 86400.0
#: 현장 장치 측정 이력을 슬라이더가 되짚을 수 있는 깊이(초). 이력이 실제로 있는지는 장치마다 다르다(없으면 값이 빈다).
FIELD_HISTORY_S = 86400.0
FIELD_STEP_S = 600.0
#: 예보·이력 값 캐시의 시각 버킷(초) — 슬라이더를 끌어도 같은 칸이면 다시 묻지 않는다.
TIME_BUCKET_S = 900.0

#: 위젯 옵션 기본값 — 쿼리로 넘어온 값이 없거나 이상하면 이 값을 쓴다.
OPTION_DEFAULTS = {
    'source_order': 'field_first',
    'max_measure_age': 300.0,
    # 위험 문턱 4개(현재값 기준). 풍속·강수·폭염은 이상, 저온(서리)은 이하일 때 위험이다.
    'hazard_wind_ms': 10.0,
    'hazard_precip_mm_h': 5.0,
    # 표현용 미세 강수 문턱(mm/h) — 이 값 미만은 "비 없음"으로 그린다(WMO 흔적 기준). 값 자체는 바꾸지 않는다.
    'precip_trace_mm_h': 0.1,
    'hazard_temp_c': 2.0,
    'hazard_heat_c': 33.0,      # 이 값 이상이면 폭염 위험(서리선과 따로)
    # 온도 색조의 중립 구간(이 안에서는 색이 없다). 색이 가장 진한 끝은 서리·폭염 문턱을 다시 쓴다.
    'tint_low_c': 10.0,
    'tint_high_c': 28.0,
}


# ── 태양 ────────────────────────────────────────────────────────────────────

def sun_phase(elevation):
    """태양 고도(°) → 단계. 설계 3절의 표와 같은 경계다.

    day > 6 · golden 0~6 · twilight -6~0 · night < -6.  None 이면 None.
    """
    if elevation is None:
        return None
    if elevation > 6.0:
        return 'day'
    if elevation > 0.0:
        return 'golden'
    if elevation > -6.0:
        return 'twilight'
    return 'night'


def sun_block(lat, lon, at=None):
    """{elevation, azimuth, phase} — 좌표가 없거나 계산이 안 되면 None."""
    if lat is None or lon is None:
        return None
    try:
        from aot.utils.solar import sun_position
        elev, az = sun_position(latitude=lat, longitude=lon, at=at)
    except Exception as exc:                                # noqa: BLE001
        logger.debug('[weather_state] 태양 위치 실패: %s', exc)
        return None
    if elev is None or az is None:
        return None
    return {'elevation': round(float(elev), 2), 'azimuth': round(float(az), 2),
            'phase': sun_phase(elev)}


# ── 위젯 옵션 ───────────────────────────────────────────────────────────────

def _num(v):
    if isinstance(v, bool):
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f and f not in (float('inf'), float('-inf')) else None


def parse_options(args):
    """쿼리(또는 dict) → 옵션 한 벌. 모르는 값·범위 밖은 기본값으로 되돌린다.

    키: ``order``(field_first|gis_first) · ``max_age``(초) · ``hz_wind`` · ``hz_precip`` · ``pt``(미세 강수 문턱, mm/h) · ``hz_temp``(서리, 이하) · ``hz_heat``(폭염, 이상) · ``tint_lo``·``tint_hi``(온도 색조 중립 구간).
    """
    get = (args or {}).get
    d = OPTION_DEFAULTS
    out = dict(d)
    order = (get('order') or '').strip().lower() if isinstance(get('order'), str) else ''
    if order in SOURCE_ORDERS:
        out['source_order'] = order
    age = _num(get('max_age'))
    if age is not None and 10.0 <= age <= 86400.0:
        out['max_measure_age'] = age
    for opt, key, lo, hi in (('hazard_wind_ms', 'hz_wind', 0.0, 100.0),
                             ('hazard_precip_mm_h', 'hz_precip', 0.0, 500.0),
                             ('precip_trace_mm_h', 'pt', 0.0, 5.0),
                             ('hazard_temp_c', 'hz_temp', -60.0, 60.0),
                             ('hazard_heat_c', 'hz_heat', -60.0, 70.0)):
        v = _num(get(key))
        if v is not None and lo <= v <= hi:
            out[opt] = v
    for opt, key in (('tint_low_c', 'tint_lo'), ('tint_high_c', 'tint_hi')):
        v = _num(get(key))
        if v is not None and -60.0 <= v <= 70.0:
            out[opt] = v
    if out['tint_low_c'] >= out['tint_high_c']:          # 중립 구간이 뒤집히면 기본값
        out['tint_low_c'], out['tint_high_c'] = d['tint_low_c'], d['tint_high_c']
    return out


def parse_time(value, now=None):
    """쿼리의 ``t`` → epoch 초. ISO 8601(``Z``·오프셋 허용, 오프셋이 없으면 UTC)이나 epoch 초·밀리초 숫자.

    비었으면 None(= 지금). 읽을 수 없거나 지금에서 ``TIME_LIMIT_S`` 보다 멀면 ValueError.
    """
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    now = time.time() if now is None else now
    out = None
    n = _num(value)
    if n is not None:
        out = n / 1000.0 if abs(n) >= 1e11 else n          # 밀리초로 보이는 큰 수
    elif isinstance(value, str):
        try:
            out = parse_utc(value.strip()).timestamp()
        except ValueError:
            raise ValueError('t must be an ISO 8601 time or epoch')
    if out is None:
        raise ValueError('t must be an ISO 8601 time or epoch')
    if abs(out - now) > TIME_LIMIT_S:
        raise ValueError('t out of range')
    return out


def time_mode(t, now):
    """``t`` 가 지금에 대해 어느 쪽인가: ``now`` | ``forecast`` | ``history``."""
    if t is None or abs(t - now) <= TIME_TOLERANCE_S:
        return 'now'
    return 'forecast' if t > now else 'history'


# ── 항목 ────────────────────────────────────────────────────────────────────

def _item(value, src, at_epoch=None, src_id=None):
    v = _num(value)
    if v is None:
        return None
    it = {'value': round(v, 2), 'src': src,
          'at': int(at_epoch) if at_epoch is not None else None}
    if src_id is not None:
        it['src_id'] = src_id
    return it


def _cand(key, value, src, at, src_id, max_age=0.0, exact=False):
    """후보 하나. ``at`` 가 None 이면 방금 받은 값(gis-input 이 관측 시각을 모를 때).

    ``exact``: ``max_age`` 가 사용자가 정한 값이라 위젯 옵션과 비교하지 않고 그대로 쓴다."""
    v = _num(value)
    if v is None or key not in ITEM_UNITS:
        return None
    return {'key': key, 'value': v, 'src': src, 'at': at, 'src_id': src_id, 'max_age': max_age,
            'exact': bool(exact)}


def pick_items(field, gis, order, max_age, now):
    """출처별 후보 → 항목별 최종값.

    field / gis: ``{key: [후보, …]}`` — 후보 순서는 각 출처 안의 우선순위(기상대 지정 순서 /
    레이어 목록 순서). ``order`` 가 ``gis_first`` 면 gis 쪽을 먼저 본다. 관측 시각이 있고
    허용 지연을 넘긴 후보는 건너뛴다(허용 지연: 현장 장치는 ``max_age``, gis-input 은 사용자가 그 입력에 준 값이 있으면 그 값,
    없으면 모듈이 말한 값과 ``max_age`` 중 큰 쪽).
    """
    groups = [field or {}, gis or {}]
    if order == 'gis_first':
        groups.reverse()
    out = {}
    for key in _ITEM_ORDER:
        done = False
        for group in groups:
            for c in group.get(key) or []:
                if c['src'] == 'field':
                    limit = max_age
                elif c.get('exact'):
                    limit = c['max_age']          # 사용자가 이 gis-input 에 직접 준 값 — 그대로 쓴다
                else:
                    limit = max(max_age, c.get('max_age') or 0.0)
                if c['at'] is not None and now - c['at'] > limit:
                    continue
                it = _item(c['value'], c['src'], c['at'], c['src_id'])
                if it:
                    out[key] = dict(it, unit=ITEM_UNITS[key])
                    done = True
                    break
            if done:
                break
    return out


# ── 현장 장치 ───────────────────────────────────────────────────────────────

# 값 단위(소문자 id/기호) → 표준 단위로 가는 배율. 표에 없으면 그 측정값은 버린다.
_UNIT_SCALE = {
    'wind_speed': {'m_s': 1.0, 'm/s': 1.0, 'ms': 1.0, 'km_h': 1 / 3.6, 'km/h': 1 / 3.6,
                   'kmh': 1 / 3.6, 'kph': 1 / 3.6, 'mph': 0.44704, 'kn': 0.514444, 'kt': 0.514444},
    'wind_dir': {'bearing': 1.0, 'degree': 1.0, 'degrees': 1.0, 'deg': 1.0, '°': 1.0},
    # 시간당 단위만 여기서 바로 받는다. 누적량(mm·in)은 측정 간격을 알 때만 ``_precip_to_mm_h`` 가 환산한다.
    'precip': {'mm_h': 1.0, 'mm/h': 1.0, 'in_h': 25.4},
    'visibility': {'m': 0.001, 'meter': 0.001, 'meters': 0.001, 'km': 1.0},
    'cloud': {'percent': 1.0, '%': 1.0},
}
_TEMP_UNITS = ('c', '°c', 'celsius', 'f', '°f', 'fahrenheit', 'k', 'kelvin')
# 기상대에 달린 온도 중 대기 온도가 아닌 것은 기온 칸에 올리지 않는다.
_NOT_AIR_TEMP = ('soil', 'ground', '토양', '지온', '지중', 'water', '수온', 'dew', '이슬', 'leaf',
                 '엽온', 'surface', '지표', 'internal', 'probe', 'cpu', 'board', 'battery')


def classify_field_measurement(measurement, unit='', name=''):
    """현장 장치 측정 하나 → 항목 키(``precip`` 등) 또는 None.

    측정 종류(``measurement``)·단위·이름으로 판별한다. 좁게 고른다 — 엉뚱한 값을
    기상 칸에 올리느니 못 올리는 편이 낫다(``device_membership`` 의 표식 규칙과 같은 판단).
    """
    m = (measurement or '').lower()
    u = (unit or '').lower()
    n = (name or '').lower()
    hay = m + ' ' + n

    if m in ('rain', 'precipitation', 'rainfall') or any(
            k in hay for k in ('강우', '강수', 'rainfall', 'precip')):
        return 'precip'
    if m == 'direction' or any(
            k in hay for k in ('풍향', 'wind_dir', 'winddir', 'wind direction', 'wind_deg',
                               'wind_bearing')) or (
            u == 'bearing' and ('wind' in hay or '풍' in hay)):
        return 'wind_dir'
    if any(k in hay for k in ('풍속', 'wind_speed', 'windspeed', 'wind speed')) or (
            'wind' in hay and u in ('m/s', 'm_s', 'km/h', 'km_h', 'kph', 'mph', 'kn')):
        return 'wind_speed'
    if m == 'visibility' or '시정' in hay or 'visibility' in hay:
        return 'visibility'
    if any(k in hay for k in ('운량', 'cloud')):
        return 'cloud'
    if m == 'temperature' and not any(k in hay for k in _NOT_AIR_TEMP):
        return 'temp'
    return None


# ── 방위(bearing) 측정값이 풍향인가 ─────────────────────────────────────────
#
# 측정값 독은 방위 항목의 화살표를 **풍향일 때만** 불어 가는 쪽(값+180°)으로 그린다. 태양 방위·
# 시설 방향·나침반 같은 방위값은 값 그대로다. 같은 측정 종류(``direction``, 단위 ``bearing``)를
# 풍향도 나침반도 쓰므로 종류만으로는 못 가른다 — 근거는 이 순서다.
#
# 1. 측정 종류가 풍향 전용(``wind_dir`` 등) — 메타데이터.
# 2. 입력 **모듈 정의**가 그 채널에 붙인 이름(``measurements_dict[ch]['name']``, 예 'Wind Direction'·
#    'Wind' / 'Compass'). 사용자가 고칠 수 없는 모듈의 말이라 이름이지만 메타데이터로 친다.
#    '바람' 계열 이름이면 풍향, 그 밖의 구체적인 이름이면 풍향이 아닌 방위, 방향·bearing 같은
#    일반어뿐이면 말해 준 것이 아니라 3번으로 넘어간다.
# 3. 위 둘이 말해 주지 않을 때만 사용자가 붙인 채널·장치 이름의 풍향 토큰 — **보조 근거**다
#    (사용자가 이름을 '풍향' 으로 지은 사용자 지정 입력을 살리려는 것이라 틀릴 수 있다).
#
# 반환: ``'wind'`` 풍향 · ``'other'`` 모듈이 풍향이 아니라고 말한 방위 · ``'unknown'`` 방위값이지만
# 근거가 없음(풍향으로 보지 않는다) · ``''`` 방위값이 아님.
WIND_DIR_MEASUREMENTS = frozenset(('wind_dir', 'winddir', 'wind_direction', 'wind_bearing', 'wind_deg'))
WIND_DIR_NAME_TOKENS = ('풍향', 'wind_dir', 'winddir', 'wind direction', 'wind_bearing', 'wind_deg')
# 모듈이 채널에 붙인 이름이 이런 일반어뿐이면 풍향인지 아닌지 말해 준 것이 아니다.
_GENERIC_DIR_NAMES = frozenset(('direction', 'bearing', 'dir', 'angle', 'degree', 'degrees', '방향', '방위'))
_module_channel_names = None


def _msgid(name):
    """lazy_gettext 이름은 번역 전 원문(msgid)을 쓴다 — 언어가 바뀌어도 판정이 같다."""
    args = getattr(name, '_args', None)
    if args:
        name = args[0]
    return str(name or '').strip()


def module_channel_name(module_id, channel):
    """입력 모듈이 채널에 붙인 이름(원문). 모르면 ''. 모듈 목록은 프로세스에서 한 번만 읽는다."""
    global _module_channel_names
    if _module_channel_names is None:
        names = {}
        try:
            from aot.utils.inputs import parse_input_information
            for mid, info in (parse_input_information() or {}).items():
                chans = {}
                for ch, meta in ((info or {}).get('measurements_dict') or {}).items():
                    nm = _msgid((meta or {}).get('name'))
                    if nm:
                        chans[str(ch)] = nm
                names[mid] = chans
        except Exception:
            logger.debug('module channel names unavailable', exc_info=True)
        _module_channel_names = names
    return (_module_channel_names.get(module_id) or {}).get(str(channel), '')


def _has_wind_dir_token(*texts):
    hay = ' '.join(str(t or '') for t in texts).lower()
    return any(tok in hay for tok in WIND_DIR_NAME_TOKENS)


def bearing_kind(measurement, unit='', module_name='', name='', device_name=''):
    """방위 측정값이 풍향인지 가른다 — 위 설명의 순서. 근거와 한계는 모듈 주석에 있다."""
    m = (measurement or '').lower().strip()
    u = (unit or '').lower().strip()
    if m in WIND_DIR_MEASUREMENTS:
        return 'wind'
    is_bearing = m == 'direction' or u == 'bearing'
    if not is_bearing and not _has_wind_dir_token(name, device_name):
        return ''                                  # 방위값이 아니다(풍속 채널의 모듈 이름 'Wind' 에 속지 않는다)
    mod = (module_name or '').strip()
    if mod:
        # 모듈이 채널을 '바람' 계열 이름으로 부르면 풍향이다(OpenWeather·Open-Meteo 는 풍속·풍향 둘 다 그냥 'Wind').
        if 'wind' in mod.lower() or '풍' in mod:
            return 'wind'
        if is_bearing and mod.lower() not in _GENERIC_DIR_NAMES:
            return 'other'
    if _has_wind_dir_token(name, device_name):
        return 'wind'
    return 'unknown'


# 누적 강수의 단위(길이) → mm 배율. 시간당 단위는 _UNIT_SCALE 이 받는다.
_ACCUM_MM = {'mm': 1.0, 'in': 25.4}
# 단위·측정 이름에 적힌 기간 표기(예: "15분", "15min", "1h"). 숫자 바로 뒤의 시간 단위만 본다.
_PERIOD_RE = re.compile(r'(?<![0-9.])(\d+(?:\.\d+)?)\s*(분|시간|min(?:ute)?s?|hours?|hrs?|h)(?![a-z])', re.I)
_PERIOD_MINUTES = (1.0, 1440.0)       # 이 범위 밖의 간격은 믿지 않는다(1분 ~ 24시간)


def _period_minutes(text):
    """문자열에 적힌 기간 표기 → 분. 없거나 둘 이상 달라 모호하면 None."""
    found = set()
    for num, unit in _PERIOD_RE.findall(text or ''):
        minutes = float(num) * (60.0 if unit.lower() in ('시간', 'h', 'hr', 'hrs', 'hour', 'hours') else 1.0)
        if _PERIOD_MINUTES[0] <= minutes <= _PERIOD_MINUTES[1]:
            found.add(minutes)
    return found.pop() if len(found) == 1 else None


def _precip_to_mm_h(value, unit, name, driver=None):
    """강수 측정값 → mm/h. 시간당 단위는 그대로, 누적량은 간격을 **확실히** 알 때만 환산한다.

    간격은 측정값 메타데이터에서만 읽는다: 단위 문자열의 기간 표기(``mm_15min``) → 측정값 이름의 기간 표기
    (``강수15분``) → 드라이버가 저장하는 누적 구간(``utils.inputs._RAIN_ACCUM_BY_DRIVER`` — 단위 ``mm`` 만 쓰는
    입력의 간격은 드라이버만 안다, 예: Open-Meteo 현재 입력은 직전 1시간 합). 어느 쪽에도 없으면 None — 강수
    키에 쓰지 않고 다음 출처로 넘어간다. 입력의 측정 주기는 누적 창과 같다는 보장이 없어 쓰지 않는다.
    장치 이름은 보지 않는다(여기에는 측정값 이름과 드라이버 이름만 온다).
    """
    u = (unit or '').strip().lower()
    scale = _UNIT_SCALE['precip'].get(u)
    if scale is not None:
        return value * scale
    mm = _ACCUM_MM.get(u)
    if mm is not None:
        minutes = _period_minutes(u)
        if minutes:
            return value * mm * 60.0 / minutes
        out = _accum_from_name(value, mm, name)
        return out if out is not None else _accum_from_driver(value, mm, u, driver)
    # 단위에 기간이 붙은 형태: mm_15min, mm/15min
    m = re.match(r'^(mm|in)[_/ ]?(.+)$', u)
    if m and m.group(1) in _ACCUM_MM:
        minutes = _period_minutes(m.group(2))
        if minutes:
            return value * _ACCUM_MM[m.group(1)] * 60.0 / minutes
    return None


def _accum_from_name(value, mm, name):
    minutes = _period_minutes(name)
    return value * mm * 60.0 / minutes if minutes else None


def _accum_from_driver(value, mm, unit, driver):
    """드라이버 표의 누적 구간(초)으로 mm/h 환산. 표에 없으면 None."""
    if not driver:
        return None
    try:
        from aot.utils.inputs import _RAIN_ACCUM_BY_DRIVER
    except Exception:                                       # noqa: BLE001
        return None
    per = (_RAIN_ACCUM_BY_DRIVER.get(driver) or {}).get(unit)
    return value * mm * 3600.0 / float(per) if per else None


def to_standard(key, value, unit, name='', driver=None):
    """측정값 → 표준 단위의 값. 단위를 모르면(강수는 누적 간격을 모르면) None(그 키를 버린다).

    ``name`` 은 측정값 이름, ``driver`` 는 장치의 입력 드라이버다 — 누적 강수의 간격을 읽을 때만 쓴다.
    """
    v = _num(value)
    if v is None:
        return None
    u = (unit or '').strip().lower()
    if key == 'temp':
        if u in ('c', '°c', 'celsius'):
            return v
        if u in ('f', '°f', 'fahrenheit'):
            return (v - 32.0) / 1.8
        if u in ('k', 'kelvin'):
            return v - 273.15
        return None
    if key == 'precip':
        out = _precip_to_mm_h(v, unit, name, driver)
        return None if out is None else max(0.0, out)
    scale = _UNIT_SCALE.get(key, {}).get(u)
    if scale is None:
        return None
    out = v * scale
    return out % 360.0 if key == 'wind_dir' else out


def _effective_unit(row):
    """장치 측정값이 influx 에 저장된 단위(변환·재스케일 반영) — 값을 읽는 쪽과 같은 규칙."""
    try:
        from aot.databases.models import Conversion
        from aot.utils.system_pi import return_measurement_info
        conv = None
        if getattr(row, 'conversion_id', None):
            conv = Conversion.query.filter_by(unique_id=row.conversion_id).first()
        _ch, unit, measurement = return_measurement_info(row, conv)
        return measurement or row.measurement, unit or row.unit
    except Exception:                                       # noqa: BLE001
        return row.measurement, row.unit


def collect_field(site_uuid, max_age, now):
    """대지에 지정된 기상대 장치의 측정값 → ``{key: [후보, …]}`` (지정 순서).

    ``max_age`` 안에 측정된 값만 읽는다 — 오래된 값은 다음 후보·출처로 넘어간다.
    지정이 없거나 대지가 없으면 {}. 측정값 추론으로 찾은 장치는 쓰지 않는다.
    """
    out = {}
    if not site_uuid:
        return out
    try:
        from aot.space import device_membership
        from aot.databases.models import DeviceMeasurements
        from aot.utils.influx import get_last_measurement

        from aot.utils.inputs import forecast_time_input_drivers, input_driver_of

        future = forecast_time_input_drivers()
        for dev_id in device_membership.bound_weather_device_ids(site_uuid):
            driver = input_driver_of(dev_id)
            if driver in future:
                continue            # '+3h 기온' 같은 미래 채널은 지금 값이 아니다 — 예보 출처(forecast_series)의 몫
            rows = DeviceMeasurements.query.filter(
                DeviceMeasurements.device_id == dev_id).order_by(DeviceMeasurements.id).all()
            for r in rows:
                meas, unit = _effective_unit(r)
                key = classify_field_measurement(meas, unit, r.name)
                if not key:
                    continue
                try:
                    last = get_last_measurement(r.device_id, r.unique_id, max_age=int(max_age))
                except Exception:                           # noqa: BLE001
                    last = None
                if not last or last[1] is None or not isinstance(last[0], (int, float)):
                    continue
                v = to_standard(key, last[1], unit, r.name, driver)
                c = _cand(key, v, 'field', float(last[0]), r.unique_id) if v is not None else None
                if c and now - c['at'] <= max_age:
                    out.setdefault(key, []).append(c)
    except Exception:                                       # noqa: BLE001
        logger.debug('[weather_state] 현장 장치 읽기 실패', exc_info=True)
    return out


def _field_value_at(row, t, max_age):
    """장치 측정 하나의 ``t`` 이전 ``max_age`` 초 안 마지막 값 → ``(epoch 초, 값)`` | None. influx 이력을 읽는다."""
    import datetime as _dt
    from aot.databases.models import Conversion
    from aot.utils.influx import read_influxdb_single
    from aot.utils.system_pi import return_measurement_info

    conv = None
    if getattr(row, 'conversion_id', None):
        conv = Conversion.query.filter_by(unique_id=row.conversion_id).first()
    channel, unit, measurement = return_measurement_info(row, conv)
    fmt = '%Y-%m-%dT%H:%M:%S.%fZ'
    utc = _dt.timezone.utc
    start = _dt.datetime.fromtimestamp(t - max_age, utc).strftime(fmt)
    end = _dt.datetime.fromtimestamp(t + 1.0, utc).strftime(fmt)
    got = read_influxdb_single(row.device_id, unit, channel, measure=measurement,
                               start_str=start, end_str=end, value='LAST')
    if not got or got[1] is None or not isinstance(got[0], (int, float)):
        return None
    return float(got[0]), got[1]


def collect_field_at(site_uuid, t, max_age, now):
    """대지에 지정된 기상대 장치의 ``t`` 시각 측정 이력 → ``{key: [후보, …]}`` (지정 순서).

    ``t`` 이전 ``max_age`` 초 안에 측정된 값만 쓴다(지금 값과 같은 규칙). 지정이 없거나 이력이 없으면 {}.
    """
    out = {}
    if not site_uuid:
        return out
    try:
        from aot.space import device_membership
        from aot.databases.models import DeviceMeasurements

        from aot.utils.inputs import forecast_time_input_drivers, input_driver_of

        future = forecast_time_input_drivers()
        for dev_id in device_membership.bound_weather_device_ids(site_uuid):
            driver = input_driver_of(dev_id)
            if driver in future:
                continue            # '+3h 기온' 같은 미래 채널은 지금 값이 아니다 — 예보 출처(forecast_series)의 몫
            rows = DeviceMeasurements.query.filter(
                DeviceMeasurements.device_id == dev_id).order_by(DeviceMeasurements.id).all()
            for r in rows:
                meas, unit = _effective_unit(r)
                key = classify_field_measurement(meas, unit, r.name)
                if not key:
                    continue
                try:
                    got = _field_value_at(r, t, max_age)
                except Exception:                           # noqa: BLE001
                    got = None
                if not got:
                    continue
                v = to_standard(key, got[1], unit, r.name, driver)
                c = _cand(key, v, 'field', got[0], r.unique_id) if v is not None else None
                if c and 0 <= t - c['at'] <= max_age:
                    out.setdefault(key, []).append(c)
    except Exception:                                       # noqa: BLE001
        logger.debug('[weather_state] 현장 장치 이력 읽기 실패', exc_info=True)
    return out


# ── gis-input ───────────────────────────────────────────────────────────────

_GIS_CACHE = {}     # (layer uid, lat2, lon2[, mode, 시각 버킷]) -> (ts, {'values', 'at', 'max_age'} | None)
_CAPABLE = {}       # (입력 종류, 메서드) -> bool (그 표준 메서드를 덮어썼는가)
_TL_CACHE = {}      # layer uid -> (ts, {'forecast': 범위|None, 'history': 범위|None})


def _ambient_instance(layer, method='get_ambient_values'):
    """GeoLayer → 입력 모듈 인스턴스. 그 표준 메서드(``method``)를 덮어쓰지 않은 모듈이면 None."""
    from aot.inputs_gis.layer_instance import _load_gis_layer_instance
    from aot.inputs_gis.base_input_gis import AbstractGisInput

    inst = _load_gis_layer_instance(layer.unique_id)
    if inst is None:
        return None
    capable = getattr(type(inst), method, None) is not getattr(AbstractGisInput, method, None)
    _CAPABLE[(layer.type, method)] = capable
    return inst if capable else None


def _gis_values(layer, lat, lon, now):
    """한 gis-input 의 표준 값(5분 캐시). 실패·무응답은 None."""
    key = (layer.unique_id, round(lat, 2), round(lon, 2))
    hit = _GIS_CACHE.get(key)
    if hit is not None and now - hit[0] < (CACHE_TTL_S if hit[1] else FAIL_RETRY_S):
        return hit[1]
    res = None
    if _CAPABLE.get((layer.type, 'get_ambient_values')) is not False:
        try:
            inst = _ambient_instance(layer)
            if inst is not None:
                got = normalize_ambient_values(inst.get_ambient_values(lat, lon))
                if got:
                    got['max_age'] = float(inst.get_ambient_max_age() or 0)
                    res = got
        except Exception:                                   # noqa: BLE001
            logger.debug('[weather_state] gis-input 기상 값 실패: %s', layer.unique_id, exc_info=True)
    _GIS_CACHE[key] = (now, res)
    return res


def _gis_values_at(layer, lat, lon, t, mode, now):
    """한 gis-input 의 ``t`` 시각 표준 값 — 미래는 ``get_ambient_forecast``, 과거는 ``get_ambient_history``.

    같은 칸(시각 버킷)은 5분 캐시한다. 실패·무응답은 None.
    """
    method = 'get_ambient_forecast' if mode == 'forecast' else 'get_ambient_history'
    key = (layer.unique_id, round(lat, 2), round(lon, 2), mode, int(t // TIME_BUCKET_S))
    hit = _GIS_CACHE.get(key)
    if hit is not None and now - hit[0] < (CACHE_TTL_S if hit[1] else FAIL_RETRY_S):
        return hit[1]
    res = None
    if _CAPABLE.get((layer.type, method)) is not False:
        try:
            inst = _ambient_instance(layer, method)
            if inst is not None:
                raw = getattr(inst, method)(lat, lon, t)
                got = normalize_ambient_values(raw)
                if got:
                    got['max_age'] = float(inst.get_ambient_max_age() or 0)
                    res = got
        except Exception:                                   # noqa: BLE001
            logger.debug('[weather_state] gis-input %s 실패: %s', method, layer.unique_id, exc_info=True)
    _GIS_CACHE[key] = (now, res)
    return res


def _ordered_gis_layers():
    """기상 출처로 쓸 gis-input 들 → ``[(layer, 저장 옵션 dict), …]`` (레이어 페이지 순서, 같으면 등록 순서).

    레이어가 꺼져 있어도 쓰고, "기상 데이터로 사용"을 끈 입력은 뺀다.
    """
    import json
    try:
        from aot.databases.models import GeoLayer
        layers = GeoLayer.query.filter_by(is_activated=True).order_by(GeoLayer.id).all()
    except Exception:                                       # noqa: BLE001
        logger.debug('[weather_state] gis-input 목록 실패', exc_info=True)
        return []
    parsed = []
    for layer in layers:
        try:
            opts = json.loads(layer.options) if layer.options else {}
        except ValueError:
            opts = {}
        if not isinstance(opts, dict) or not ambient_source_enabled(opts):
            continue
        # 레이어 페이지에서 사용자가 늘어놓은 순서(position_y), 같거나 없으면 등록 순서.
        pos = opts.get('position_y')
        pos = pos if isinstance(pos, (int, float)) and not isinstance(pos, bool) else float('inf')
        parsed.append((pos, layer.id or 0, layer, opts))
    return [(layer, opts) for _pos, _id, layer, opts in sorted(parsed, key=lambda t: (t[0], t[1]))]


def _gis_candidates(fetch):
    """``fetch(layer) -> 정규화된 값 | None`` 를 사용자 순서대로 돌려 후보 목록을 모은다."""
    out = {}
    for layer, opts in _ordered_gis_layers():
        res = fetch(layer)
        if not res:
            continue
        # 사용자가 이 입력에 준 지연 문턱이 모듈 기본값을 덮는다(옵션은 매번 읽어 바로 반영된다).
        override = ambient_max_age_override(opts)
        for key, v in res['values'].items():
            c = _cand(key, v, 'gis', res['at'], layer.unique_id,
                      override if override is not None else (res.get('max_age') or 0.0),
                      exact=override is not None)
            if c:
                if res.get('confidence') is not None:        # 예보 출처가 준 신뢰도(관측 값에는 없다)
                    c['confidence'] = res['confidence']
                out.setdefault(key, []).append(c)
    return out


def collect_gis(lat, lon, now):
    """등록된 gis-input 의 표준 값 → ``{key: [후보, …]}`` (레이어 목록 순서)."""
    return _gis_candidates(lambda layer: _gis_values(layer, lat, lon, now))


def collect_gis_at(lat, lon, t, mode, now):
    """``t`` 시각의 gis-input 표준 값 → ``{key: [후보, …]}`` (예보 또는 이력, 사용자 순서)."""
    return _gis_candidates(lambda layer: _gis_values_at(layer, lat, lon, t, mode, now))


def _time_range_of(layer, method, now):
    """한 gis-input 의 예보·이력 구간(``method`` = get_ambient_forecast_range | get_ambient_history_range). 외부 호출 없음."""
    if _CAPABLE.get((layer.type, method)) is False:
        return None
    try:
        inst = _ambient_instance(layer, method)
        return normalize_forecast_range(getattr(inst, method)()) if inst is not None else None
    except Exception:                                       # noqa: BLE001
        logger.debug('[weather_state] gis-input %s 실패: %s', method, layer.unique_id, exc_info=True)
        return None


def collect_timeline(site, now):
    """슬라이더가 값을 받을 수 있는 구간 ``{'forecast': {start_ms,end_ms,step_ms}|None, 'history': …}``.

    예보는 대지에 지정한 예보 계열(forecast_series — 시간별 뒤 일별)이 있으면 그 구간만, 없으면 gis-input 의
    ``get_ambient_forecast_range`` 합집합(공통 폴백). 이력은 대지에 기상대 장치가 지정돼 있으면
    ``FIELD_HISTORY_S`` 만큼, 그리고 gis-input 의 ``get_ambient_history_range`` 합집합. 출처가 없으면 None.
    """
    spans = {'forecast': [], 'history': []}
    designated = None
    fsrc = None
    if site:
        try:
            from aot.space import forecast_series
            designated = forecast_series.timeline_range(site, now)
            if designated:
                fsrc = forecast_series.source_info(forecast_series.site_series(site, now, fallback=False))
        except Exception:                                   # noqa: BLE001
            logger.debug('[weather_state] 예보 출처 범위 실패', exc_info=True)
    fc_layers = []
    for layer, _opts in _ordered_gis_layers():
        hit = _TL_CACHE.get(layer.unique_id)
        if hit is None or now - hit[0] >= CACHE_TTL_S:
            hit = (now, {'forecast': _time_range_of(layer, 'get_ambient_forecast_range', now),
                         'history': _time_range_of(layer, 'get_ambient_history_range', now)})
            _TL_CACHE[layer.unique_id] = hit
        for kind in spans:
            if hit[1][kind]:
                spans[kind].append(hit[1][kind])
        if hit[1]['forecast']:
            fc_layers.append((layer, hit[1]['forecast']))
    if designated:
        # 대지에 예보 출처가 지정돼 있으면 미래는 그 계열만 — gis 레이어 범위를 합치지 않는다(한 출처).
        spans['forecast'] = [designated]
    if site:
        try:
            from aot.space import device_membership
            if device_membership.bound_weather_device_ids(site):
                spans['history'].append({'start': now - FIELD_HISTORY_S, 'end': now, 'step_s': FIELD_STEP_S})
        except Exception:                                   # noqa: BLE001
            logger.debug('[weather_state] 기상대 이력 범위 실패', exc_info=True)
    out = {}
    for kind, lst in spans.items():
        if not lst:
            out[kind] = None
            continue
        out[kind] = {'start_ms': int(min(r['start'] for r in lst) * 1000),
                     'end_ms': int(max(r['end'] for r in lst) * 1000),
                     'step_ms': int(min(r['step_s'] for r in lst) * 1000)}
    # 미래 값이 어디서 오는가 — 범례·독('예보 제공 범위 밖' 칸)이 사용자에게 밝힌다(트윈·AI 와 같은 출처).
    if fsrc is None:
        from aot.space import forecast_series
        if fc_layers:
            fsrc = {'basis': 'map_layer', 'basis_text': forecast_series.BASIS_TEXT['map_layer'],
                    'segments': [{'kind': 'hourly', 'start': r['start'], 'end': r['end'],
                                  'name': layer.name or layer.unique_id, 'input_id': None} for layer, r in fc_layers]}
        else:
            fsrc = {'basis': 'none', 'basis_text': forecast_series.BASIS_TEXT['none'], 'segments': []}
    out['forecast_source'] = fsrc
    return out


# ── 위험(현재값 기준) ───────────────────────────────────────────────────────

def collect_hazards(items, opts):
    """현재값과 문턱 4개(풍속·강수·저온·폭염)로만 판정한다 → ``{stale, age_hours, items}``.

    ``items`` 의 모양은 예전 예보 위험과 같다(``kind·severity·in_h·value·unit``) — ``in_h`` 는
    항상 0(지금). 예보를 붙일 때는 같은 모양의 항목을 더하면 화면이 그대로 읽는다.
    """
    def val(key):
        it = (items or {}).get(key)
        return it['value'] if it and it.get('value') is not None else None

    out = []
    w, p, t = val('wind_speed'), val('precip'), val('temp')
    from aot.inputs_gis.ambient_roles import AMBIENT_WEATHER_THRESHOLDS as th
    strikes, strike_km = val('lightning'), val('lightning_km')
    if strikes is not None and strikes >= 1:
        near = strike_km is not None and strike_km <= th['lightning_near_km']
        out.append({'kind': 'lightning', 'severity': 'severe' if near else 'warn', 'in_h': 0,
                    'value': round(strike_km, 1) if strike_km is not None else int(strikes),
                    'unit': 'km' if strike_km is not None else ''})
    if w is not None and w >= opts['hazard_wind_ms'] > 0:
        out.append({'kind': 'wind', 'severity': 'severe' if w >= opts['hazard_wind_ms'] * 1.4 else 'warn',
                    'in_h': 0, 'value': round(w, 1), 'unit': 'm/s'})
    if p is not None and p >= opts['hazard_precip_mm_h'] > 0:
        severe = p >= opts['hazard_precip_mm_h'] * 2.0
        out.append({'kind': 'heavy_rain' if severe else 'rain', 'severity': 'severe' if severe else 'warn',
                    'in_h': 0, 'value': round(p, 1), 'unit': 'mm/h'})
    if t is not None and t <= opts['hazard_temp_c']:
        severe = t <= 0.0 < opts['hazard_temp_c']
        out.append({'kind': 'freeze' if severe else 'frost', 'severity': 'severe' if severe else 'warn',
                    'in_h': 0, 'value': round(t, 1), 'unit': '°C'})
    elif t is not None and t >= opts['hazard_heat_c']:
        # 폭염: 문턱 +2 °C 부터는 심각(예전 예보 규칙 33/35 °C 와 같은 간격).
        out.append({'kind': 'heat', 'severity': 'severe' if t >= opts['hazard_heat_c'] + 2.0 else 'warn',
                    'in_h': 0, 'value': round(t, 1), 'unit': '°C'})
    return {'stale': False, 'age_hours': None, 'items': out}


def temp_tint(temp_item, opts):
    """기온 → 색조 강도 ``{'k': -1~+1}`` (음수 = 참, 양수 = 더움). 기온이 없으면 None.

    중립 구간(``tint_low_c`` ~ ``tint_high_c``)은 0, 색이 가장 진한 끝은 서리 문턱(``hazard_temp_c``)과
    폭염 문턱(``hazard_heat_c``)이다. 그 사이는 선형. 문턱이 중립 구간 안쪽으로 들어오면 0.5 °C 밖으로 잡는다.
    색을 칠할지(위젯 옵션 '온도 색조')와 어떤 색인지는 화면이 정한다 — 여기서는 강도만 낸다.
    """
    t = temp_item.get('value') if temp_item else None
    if t is None:
        return None
    lo, hi = opts['tint_low_c'], opts['tint_high_c']
    cold_end = min(opts['hazard_temp_c'], lo - 0.5)
    hot_end = max(opts['hazard_heat_c'], hi + 0.5)
    if t < lo:
        k = -min(1.0, (lo - t) / (lo - cold_end))
    elif t > hi:
        k = min(1.0, (t - hi) / (hot_end - hi))
    else:
        k = 0.0
    return {'k': round(k, 3)}


# ── 조립 ────────────────────────────────────────────────────────────────────

def build_state(lat, lon, now=None, field=None, gis=None, opts=None, site=None,
                mode='now', real_now=None, timeline=None, confidence=None):
    """수집된 조각을 응답 한 벌로 묶는다 — 외부 호출 없는 순수 함수.

    field / gis: ``{key: [후보, …]}``. 관측 지연(30분 초과)이면 ``strength.stale`` 이 true 가 되고
    ``strength.factor`` 가 0.5 가 된다. ``strength.cloud`` 는 0~1 운량 — 프런트 plan() 의 강도 입력이다.

    ``now`` 는 **이 상태가 말하는 시각**(epoch 초)이다. 시간 슬라이더(P3)에서는 ``t`` 가 들어오고 ``mode`` 가
    ``forecast``/``history`` 가 되며, 태양 위치·값의 낡음은 모두 그 시각 기준이다. ``real_now`` 는 서버의 실제 지금
    (``server_epoch_ms`` 용). 예보는 관측이 아니므로 "관측 지연"을 따지지 않는다.
    """
    now = time.time() if now is None else now
    real_now = now if real_now is None else real_now
    opts = dict(OPTION_DEFAULTS, **(opts or {}))
    items = pick_items(field, gis, opts['source_order'], opts['max_measure_age'], now)
    ats = [it['at'] for it in items.values() if it.get('at')]
    obs_epoch = max(ats) if ats else None
    age_min = None
    if obs_epoch is not None:
        age_min = round(max(0.0, (now - obs_epoch) / 60.0), 1)
    stale = mode != 'forecast' and age_min is not None and age_min > STALE_OBS_MIN
    cloud = items.get('cloud')
    decided = decide_ambient(items, opts)
    out = {
        'ok': True,
        'site': site,
        'lat': lat,
        'lon': lon,
        'server_epoch_ms': int(real_now * 1000),
        't': int(now * 1000),
        'mode': mode,
        'sun': sun_block(lat, lon, at=parse_utc(now)),
        'items': items,
        'hazards': collect_hazards(items, opts),
        'tint': temp_tint(items.get('temp'), opts),
        'observed_at': int(obs_epoch * 1000) if obs_epoch is not None else None,
        'obs_age_min': age_min,
        'strength': {
            'cloud': round(min(1.0, max(0.0, cloud['value'] / 100.0)), 3) if cloud else None,
            'stale': bool(stale),
            'factor': 0.5 if stale else 1.0,
        },
        'auto_layers': decided['auto_layers'],
        'fx': decided['fx'],
        'wind_calm': decided['wind_calm'],
    }
    if timeline is not None:
        out['timeline'] = timeline
    if confidence is not None:
        out['confidence'] = confidence
    return out


def decide_ambient(items, opts=None):
    """항목 → 연출·자동 켜기 판정. 문턱은 ``ambient_roles.AMBIENT_WEATHER_THRESHOLDS`` 한 곳.

    ``auto_layers``: 조건이 맞아 등록된 기상 레이어를 화면에서만 켤 종류(precip/cloud/wind).
    ``fx.strong_wind``: 바람 흐름선을 호박색으로 그릴 강풍인가.
    ``fx.precip_kind``: 모듈이 알려 준 강수 종류(rain/snow/sleet/hail) — 모르면 None(화면이 기온으로 짐작한다).
    ``fx.lightning``: 최근 낙뢰가 있는가 — 화면 섬광과 위험 칸이 쓴다.
    ``fx.precip``: 비·눈을 그릴 만한 강수인가 — ``opts['precip_trace_mm_h']`` 이상일 때만 true(표현 문턱, 값은 그대로).
    값이 없는 항목은 false — 모르는 것으로 레이어를 켜지 않는다.
    """
    from aot.inputs_gis.ambient_roles import AMBIENT_PRECIP_TYPES, AMBIENT_WEATHER_THRESHOLDS as th
    trace = (opts or {}).get('precip_trace_mm_h', OPTION_DEFAULTS['precip_trace_mm_h'])

    def val(key):
        it = (items or {}).get(key)
        return it['value'] if it and it.get('value') is not None else None

    p, c, w = val('precip'), val('cloud'), val('wind_speed')
    pt, ln = val('precip_type'), val('lightning')
    return {
        'auto_layers': {
            'precip': p is not None and p >= th['precip_mm_h'],
            'cloud': c is not None and c >= th['cloud_pct'],
            'wind': w is not None and w >= th['wind_ms'],
        },
        'fx': {'precip': p is not None and p >= max(trace, 1e-9),
               'strong_wind': w is not None and w >= th['strong_wind_ms'],
               'precip_kind': AMBIENT_PRECIP_TYPES.get(int(pt)) if pt is not None else None,
               'lightning': ln is not None and ln >= 1},
        # 풍속을 알고 고요(보퍼트 0)이면 true — 화면이 방향 이름 대신 "고요"를 쓴다. 풍속을 모르면 None.
        'wind_calm': None if w is None else w < th['calm_ms'],
    }


def _min_confidence(gis, items):
    """응답에 실린 gis 값들이 주장한 신뢰도 중 가장 낮은 것(0~1). 주장이 없으면 None."""
    used = {it.get('src_id') for it in items.values() if it.get('src') == 'gis'}
    vals = [c['confidence'] for cands in (gis or {}).values() for c in cands
            if c.get('src_id') in used and isinstance(c.get('confidence'), (int, float))]
    return min(vals) if vals else None


def get_state(lat, lon, site=None, opts=None, now=None, t=None):
    """수집 + 조립. gis-input 결과만 5분 캐시한다(현장 장치 값·옵션은 매번 반영).

    ``t``(epoch 초): 지금과 5분 넘게 다르면 그 시각의 상태 — 미래는 대지 예보 계열(`_forecast_state`)에서만, 과거는 기상대 장치
    측정 이력과 gis-input 이력에서만 온다. 없으면(또는 지금과 같으면) 지금 상태이고 ``timeline`` 이 함께 실린다.
    """
    now = time.time() if now is None else now
    opts = dict(OPTION_DEFAULTS, **(opts or {}))
    mode = time_mode(t, now)
    if mode == 'now':
        field = collect_field(site, opts['max_measure_age'], now)
        gis = collect_gis(lat, lon, now)
        return build_state(lat, lon, now=now, field=field, gis=gis, opts=opts, site=site,
                           timeline=collect_timeline(site, now))
    if mode == 'forecast':
        return _forecast_state(lat, lon, site, opts, t, now)
    field = collect_field_at(site, t, opts['max_measure_age'], now)
    gis = collect_gis_at(lat, lon, t, mode, now)
    st = build_state(lat, lon, now=t, field=field, gis=gis, opts=opts, site=site, mode=mode, real_now=now)
    conf = _min_confidence(gis, st['items'])
    if conf is not None:
        st['confidence'] = conf
    return st


def _layer_names(ids):
    names = []
    try:
        from aot.databases.models import GeoLayer
        for uid in ids:
            row = GeoLayer.query.filter_by(unique_id=uid).first()
            names.append(row.name if row is not None and row.name else uid)
    except Exception:                                       # noqa: BLE001
        names = list(ids)
    return names


def _forecast_state(lat, lon, site, opts, t, now):
    """미래 시각의 상태 — 대지 예보 계열 하나(`forecast_series`)에서만 온다. 트윈·AI 와 같은 출처다.

    지정이 있으면 그 계열만 쓴다(gis 를 섞지 않는다): 시간별 구간이면 시간 값, 그 뒤면 그 날의 일 값(``daily``),
    범위 밖이면 ``out_of_range``. 지정이 없으면 공통 폴백 — gis-input 예보 레이어(사용자 순서). 어느 쪽인지
    ``forecast_source``(basis·구간·출처 이름·구간 목록)가 밝힌다."""
    from aot.space import forecast_series
    at = forecast_series.state_at(site, t, now, lat, lon) if site else None
    if at is not None:
        field, gis = at['candidates'], {}
    else:
        field, gis = {}, collect_gis_at(lat, lon, t, 'forecast', now)
    st = build_state(lat, lon, now=t, field=field, gis=gis, opts=opts, site=site, mode='forecast', real_now=now)
    if at is not None:
        st['forecast_source'] = {'basis': at['basis'], 'basis_text': at['info']['basis_text'],
                                 'segment': at['segment'], 'name': (at['source'] or {}).get('name'),
                                 'segments': at['info']['segments']}
        if at['segment'] == 'daily':
            st['daily'] = at['daily']
    else:
        used = sorted({it.get('src_id') for it in st['items'].values() if it.get('src') == 'gis' and it.get('src_id')})
        basis = 'map_layer' if st['items'] else 'none'
        st['forecast_source'] = {'basis': basis, 'basis_text': forecast_series.BASIS_TEXT[basis],
                                 'segment': 'hourly' if st['items'] else None,
                                 'name': ', '.join(_layer_names(used)) or None, 'segments': []}
        conf = _min_confidence(gis, st['items'])
        if conf is not None:
            st['confidence'] = conf
    if st['forecast_source']['segment'] is None:
        st['out_of_range'] = True
    return st


def clear_cache():
    _GIS_CACHE.clear()
    _CAPABLE.clear()
    _TL_CACHE.clear()
