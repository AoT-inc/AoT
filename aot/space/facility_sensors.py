# coding=utf-8
"""
facility_sensors.py — GeoFacility 센서 바인딩 읽기 및 집계 유틸리티.

facility.sensors 배열에서 센서 목록을 로드하고, 각 센서의 최신 측정값을
InfluxDB에서 읽어 role별로 가중 평균을 계산한다.

지원 역할(role):
    indoor_temp       → indoor.temp_c         (°C)
    indoor_humidity   → indoor.humidity_pct   (%)
    indoor_co2        → indoor.co2_ppm        (ppm)
    outdoor_temp      → outdoor.temp_c        (°C)
    outdoor_humidity  → outdoor.humidity_pct  (%)
    outdoor_wind      → outdoor.wind_ms       (m/s)
    outdoor_wind_dir  → outdoor.wind_deg      (°)
    (실외 돌풍은 역할이 아니라 measurement_type 'wind_gust' → read_outdoor_sensors 의 wind_gust_ms)
    outdoor_solar     → outdoor.solar_wm2     (W/m²)

복수 센서(동일 role): weight 기반 가중 평균. 유효하지 않은 센서는 제외.
센서 유효 조건: max_age 이내의 InfluxDB 데이터 존재.

Update handling:
    1. 센서 목록 변경 → facility.sensors 수정. 런타임 엔드포인트 다음 폴링에서 즉시 반영.
    2. 측정값 갱신   → get_last_measurement가 매 호출마다 최신값 조회. max_age 초과 시 자동 제외.
    3. 장치 제거     → device_id/measurement_id 미존재 시 [None, None] 반환 → 자동 제외.
                      valid_count < total_count이면 결과에 degraded=True 플래그.
"""

import logging
from typing import Dict, List, Optional, Tuple

from aot.utils import psychro
from aot.utils import sensor_status as _ss
from aot.utils import measurement_freshness as _freshness
from aot.utils.influx import get_last_measurement  # module-level — patchable in tests
from aot.utils.timekit import naive_utc, parse_utc

logger = logging.getLogger(__name__)

# 측정값 유효 수명의 **하한** (초). 표시 경로에서는 여기서 시작해 장치 주기만큼
# 넓힌다(_max_age_for).
DEFAULT_MAX_AGE_S: int = 300

# 표시 경로에서 "늦었다"고 볼 배수. 2 = 표본 1회 유실까지는 정상으로 본다.
# 1배로 하면 데몬·전송 지터 몇 초에도 매 주기 끝마다 stale 로 깜빡인다.
STALE_PERIOD_FACTOR: int = 2


def _freshness_by_device(device_ids) -> Dict[str, tuple]:
    """{Input.unique_id: (주기(초), 장치 명시 max_age(초) or None)}.

    판정의 정본은 `aot.utils.measurement_freshness` 다 — 같은 질문을 하는
    자리가 다섯이라 규칙을 여기 두면 갈라진다. 이 이름은 호출부 호환용이다.
    """
    return _freshness.freshness_by_device(device_ids)


def _period_by_device(device_ids) -> Dict[str, float]:
    """{unique_id: 주기} — 옛 호출부 호환용 얇은 껍데기."""
    return {uid: p for uid, (p, _m) in _freshness_by_device(device_ids).items() if p}


def _fresh(table: Dict[str, tuple], device_id) -> tuple:
    """(주기, 장치 명시 max_age) — 없는 장치는 (None, None)."""
    return _freshness.lookup(table, device_id)


def _max_age_for(requested: Optional[int], period: Optional[float],
                 device_max_age: Optional[int] = None) -> int:
    """이 측정에 적용할 유효 수명(초).

    `requested is None` = "장치 주기로 정해라" — 표시 경로(/runtime·IEC 상태 화면)의
    기본값이다. Input.period 는 15초부터 86400초(1일)까지 제각각이라 고정 300초로는
    판정할 수 없다: 하루 한 번 재는 센서는 **정상인데도 항상** 300초를 넘겨,
    라벨은 상시 흐리게 표시되고 indoor/outdoor 집계에서는 값이 통째로 빠졌다.

    숫자가 오면 호출자가 명시한 값이므로 그대로 쓴다 — 제어(env_coordinator)의
    max_age 는 "이보다 오래된 값으로는 작동하지 않는다"는 **안전 결정**이라,
    주기를 근거로 넓혀서는 안 된다.

    그보다 앞서는 것이 `device_max_age`(`Input.max_age_s`)다. 근거는 정본
    모듈의 `effective_max_age` 주석 참조 — 여기 배수 2 는 "표본 1회 유실까지는
    정상" 이라는 이 화면의 판단이고, 표시 경로 공통 배수(3)와 다르다.
    """
    return _freshness.effective_max_age(
        requested, period, device_max_age,
        floor=DEFAULT_MAX_AGE_S, factor=STALE_PERIOD_FACTOR)


# role → (섹션, 필드) 매핑
_ROLE_MAP: Dict[str, Tuple[str, str]] = {
    'indoor_temp':      ('indoor',  'temp_c'),
    'indoor_humidity':  ('indoor',  'humidity_pct'),
    'indoor_co2':       ('indoor',  'co2_ppm'),
    'outdoor_temp':     ('outdoor', 'temp_c'),
    'outdoor_humidity': ('outdoor', 'humidity_pct'),
    'outdoor_wind':     ('outdoor', 'wind_ms'),
    'outdoor_wind_dir': ('outdoor', 'wind_deg'),
    'outdoor_solar':    ('outdoor', 'solar_wm2'),
}

KNOWN_ROLES = set(_ROLE_MAP.keys())


# ─────────────────────────────────────────────────────────────────────────────
# 역할 → 멈춘 센서 판정의 물리량 (`sensor_status.FROZEN_KINDS`)
_ROLE_FROZEN_KIND: Dict[str, str] = {
    'indoor_temp': 'T', 'indoor_humidity': 'RH', 'indoor_co2': 'CO2',
    'outdoor_temp': 'T', 'outdoor_humidity': 'RH',
}


def read_facility_sensors(
    sensor_bindings: List[dict],
    max_age: Optional[int] = None,
    frozen=None,
) -> dict:
    """sensor_bindings 목록을 읽어 indoor/outdoor 환경 값을 반환한다.

    Args:
        sensor_bindings: facility.sensors JSON 배열
            각 항목: {role, device_id, measurement_id, name, weight(optional)}
        max_age: 측정값 최대 유효 수명 (초). 초과 시 해당 센서 제외.
            None(기본) = 장치 샘플링 주기로 정한다(_max_age_for) — 표시 경로용.
            숫자를 주면 그대로 쓴다 — 제어의 안전 기준을 주기로 넓히지 않는다.
        frozen: `sensor_status.FrozenTracker` — 주어지면 값이 오래 멈춘 센서(T·RH·CO2 역할)는
            `degraded_reason='frozen'` 으로 집계에서 뺀다. 공간 경로(`compute_spatial_internal`)가
            멈춘 센서를 버린 뒤 이 역할 폴백이 같은 값을 되살리지 못하게 하는 것이다.

    Returns:
        {
            'indoor':  {temp_c, humidity_pct, co2_ppm},
            'outdoor': {temp_c, humidity_pct, wind_ms, wind_deg, solar_wm2},
            'sensors': [  # 센서별 상세 (디버깅/UI용)
                {role, name, value, unit, ts, valid, stale, degraded_reason}
            ],
            'degraded': bool,   # 하나 이상의 센서가 유효하지 않음
            'valid_count': int,
            'total_count': int,
        }
    """
    # 섹션별 집계 버킷: role → [(value, weight)]
    buckets: Dict[str, List[Tuple[float, float]]] = {}
    sensor_details: list = []
    total_count = 0
    valid_count = 0

    # 표시 경로(max_age 미지정)에서만 장치 주기를 조회한다 — 한 번의 IN 조회.
    fresh = _freshness_by_device(
        [(b.get('device_id') or '').strip() for b in (sensor_bindings or [])])

    for binding in (sensor_bindings or []):
        role          = (binding.get('role') or '').strip()
        device_id     = (binding.get('device_id') or '').strip()
        measurement_id = (binding.get('measurement_id') or '').strip()
        name          = binding.get('name') or role
        weight        = float(binding.get('weight') or 1.0)

        if not role or not device_id or not measurement_id:
            continue
        if role not in KNOWN_ROLES:
            logger.debug('[FacilitySensors] 알 수 없는 role 무시: %s', role)
            continue

        total_count += 1
        detail: dict = {
            'role':   role,
            'name':   name,
            'value':  None,
            'ts':     None,
            'valid':  False,
            'stale':  False,
            'degraded_reason': None,
        }

        eff_max_age = _max_age_for(max_age, *_fresh(fresh, device_id))
        try:
            ts, value = get_last_measurement(device_id, measurement_id,
                                             max_age=eff_max_age)
        except Exception as exc:
            logger.warning('[FacilitySensors] %s(%s) 조회 실패: %s', name, role, exc)
            detail['degraded_reason'] = f'query_error: {exc}'
            sensor_details.append(detail)
            continue

        if ts is None or value is None:
            # max_age 초과 여부 판단: max_age 없이 재조회하여 데이터 존재 자체를 확인
            try:
                ts_any, val_any = get_last_measurement(device_id, measurement_id, max_age=None)
                if ts_any is not None:
                    detail['stale'] = True
                    detail['degraded_reason'] = 'stale'
                else:
                    detail['degraded_reason'] = 'no_data'
            except Exception:
                detail['degraded_reason'] = 'no_data'
            sensor_details.append(detail)
            continue

        # 멈춘 센서 — 공간 경로와 같은 판정(같은 추적기)
        _fk = _ROLE_FROZEN_KIND.get(role)
        if (frozen is not None and _fk is not None
                and frozen.observe((device_id, measurement_id), _fk, value, ts)):
            detail['degraded_reason'] = _ss.FROZEN
            sensor_details.append(detail)
            continue

        # 유효한 측정값
        detail['value'] = value
        detail['ts']    = ts
        detail['valid'] = True
        valid_count += 1

        buckets.setdefault(role, []).append((float(value), weight))
        sensor_details.append(detail)

    # ── role별 가중 평균 계산 ──────────────────────────────────────────────
    averaged: Dict[str, Optional[float]] = {}
    for role, readings in buckets.items():
        total_w = sum(w for _, w in readings)
        averaged[role] = sum(v * w for v, w in readings) / total_w if total_w > 0 else None

    def _get(role: str) -> Optional[float]:
        return averaged.get(role)

    indoor = {
        'temp_c':       _get('indoor_temp'),
        'humidity_pct': _get('indoor_humidity'),
        'co2_ppm':      _get('indoor_co2'),
    }
    outdoor = {
        'temp_c':       _get('outdoor_temp'),
        'humidity_pct': _get('outdoor_humidity'),
        'wind_ms':      _get('outdoor_wind'),
        'wind_deg':     _get('outdoor_wind_dir'),
        'solar_wm2':    _get('outdoor_solar'),
    }

    return {
        'indoor':      indoor,
        'outdoor':     outdoor,
        'sensors':     sensor_details,
        'degraded':    valid_count < total_count,
        'valid_count': valid_count,
        'total_count': total_count,
    }


# ─────────────────────────────────────────────────────────────────────────────
HOTSPOT_DELTA_T  = 3.0   # °C: 평균 대비 이 값 이상 차이나면 핫스팟
HOTSPOT_DELTA_RH = 10.0  # %RH

# 등가 환경 전제 하 공간 outlier(이상 센서) 제거 임계.
# 같은 마이크로환경을 측정하는 센서들 사이에서 robust z-score (MAD 기반)가
# 이 값을 초과하면 센서 오작동으로 간주하고 평균 계산에서 제외한다.
SPATIAL_MAD_K          = 3.5  # k·MAD 초과 시 reject
SPATIAL_MIN_FOR_REJECT = 3    # 이 미만이면 reject 판단 불가 — 전체 유지

# 변수별 최소 척도 (센서 정확도/잡음 한계). 다수 센서가 동일값을 뱉어 MAD=0 인
# 경우에도 이 척도를 사용해 명백히 튀는 센서를 잡아낸다. 일반 변동(잡음) 보다
# 큰 값으로 설정해야 false-positive 가 안 난다.
SPATIAL_SCALE_FLOOR: Dict[str, float] = {
    'T':     0.5,   # °C
    'RH':    2.0,   # %
    'CO2':   50.0,  # ppm
    'VPD':   0.1,   # kPa
    'light': 50.0,  # W/m²
}
SPATIAL_SCALE_FLOOR_DEFAULT = 0.5

# DeviceMeasurements.measurement 이름 집합 — measurement_type 미설정 시 추론용
_MEAS_T_NAMES       = {'temperature', 'temp', 'temp_c'}
_MEAS_RH_NAMES      = {'humidity', 'humidity_pct', 'relative_humidity'}
_MEAS_CO2_NAMES     = {'co2', 'co2_ppm', 'carbon_dioxide'}
_MEAS_VPD_NAMES     = {'vpd', 'vpd_kpa', 'vapor_pressure_deficit'}
_MEAS_LIGHT_NAMES   = {'light', 'solar', 'solar_wm2', 'irradiance', 'ppfd', 'lux', 'par', 'radiation'}
_MEAS_WIND_NAMES    = {'wind', 'wind_speed', 'wind_ms', 'windspeed', 'speed'}
_MEAS_WINDDIR_NAMES = {'wind_dir', 'wind_direction', 'wind_bearing', 'wind_deg', 'direction'}
# 돌풍 — 이름이 'speed' 인 돌풍 채널(SenseCAP 'Peak Wind Gust')은 이름으로 못 가른다. 사용자가
# 채널 종류를 'wind_gust' 로 고르면 직접 조회로 읽힌다(`_read_one_sensor`).
_MEAS_GUST_NAMES    = {'gust', 'wind_gust', 'wind_gusts', 'wind_gusts_10m', 'gust_speed',
                       'wind_gust_ms'}
_MEAS_RAIN_NAMES    = {'rain', 'rainfall', 'rainrate', 'rain_rate', 'precipitation',
                        'length', 'depth'}
# length/depth: ecowitt 계열 강수 채널의 raw measurement 이름
_RAIN_UNITS         = {'mm', 'mm_h', 'in_h', 'in'}
# mm: 누적 강수량, mm_h: 시간당 강수율, in_h/in: 변환 전 원시 단위
# ⚠ 단위가 mm 여도 강우가 아닌 채널 — 단위로 강우 채널을 찾을 때 건너뛴다(NASA POWER 의
#   증발산 채널 0 이 강우 채널 5 보다 먼저 잡혔다). 'percent' 인 'precipitation' 은 강수
#   **확률**(KMA_forecast POP)이라 이름이 맞아도 강우량이 아니다.
_NOT_RAIN_MEASUREMENTS = {'evapotranspiration', 'snowfall', 'snow_depth'}
_NOT_RAIN_UNITS        = {'percent', '%'}

# measurement_type → (이름 집합, 결과 소수점 자리수)
_MTYPE_MAP: Dict[str, Tuple[set, int]] = {
    'temperature':     (_MEAS_T_NAMES,       2),
    'humidity':        (_MEAS_RH_NAMES,      1),
    'co2':             (_MEAS_CO2_NAMES,     0),
    'vpd':             (_MEAS_VPD_NAMES,     3),
    'light':           (_MEAS_LIGHT_NAMES,   1),
    'wind_speed':      (_MEAS_WIND_NAMES,    2),
    'wind_direction':  (_MEAS_WINDDIR_NAMES, 1),
    'wind_gust':       (_MEAS_GUST_NAMES,    2),
    'rain':            (_MEAS_RAIN_NAMES,    2),
}

# measurement_type → result key (compute_spatial_internal / read_outdoor_sensors 반환 dict)
_MTYPE_KEY = {
    'temperature':    'T',
    'humidity':       'RH',
    'co2':            'CO2',
    'vpd':            'VPD',
    'light':          'light',
    'wind_speed':     'wind_ms',
    'wind_direction': 'wind_deg',
    'wind_gust':      'wind_gust_ms',
    'rain':           'rain_mm',
    'pressure':       'P',
    # ── 메타 채널(장치 자신의 상태) ──────────────────────────────────────────
    # 환경값이 아니라 "장치가 살아 있는가"를 말하는 채널이다. key 를 주는 이유는
    # 표시가 아니라 **식별**이다: key 가 없으면 display_key 가 번역된 표시명
    # ('RSSI'/'배터리 전압'/'バッテリ電圧')이 되어, 클라이언트가 언어에 상관없이
    # 이 채널을 골라낼 방법이 사라진다. 배지로 그리고 그래프에서 빼려면
    # 언어 독립적인 이름이 반드시 필요하다.
    'rssi':           'rssi',
    'snr':            'snr',
    'battery':        'battery',
}

# 메타 채널 key 집합 — 값 라벨·이력 그래프에서 제외하고 배지로만 그린다.
# 클라이언트(sensor-label.js isMetaChannel)와 같은 목록이어야 한다.
META_CHANNEL_KEYS = frozenset({'rssi', 'snr', 'battery'})

# 배터리 전압 판별용. measurement 는 'electrical_potential' 하나로 뭉뚱그려져 있어
# (RAK3172 HB 는 V, lorawan_mode_manager 는 mV 로 같은 measurement 에 쓴다) 전압
# 채널 전부를 배터리로 볼 수는 없다 — 이름에 배터리가 드러난 것만 승격한다.
_BATTERY_VOLTAGE_MEASUREMENTS = frozenset({'electrical_potential'})
_BATTERY_NAME_TOKENS = ('batt', 'vbat', '배터리', 'バッテリ')

# result key → 표시 단위 (라벨/팝업 출력용)
_UNIT_BY_KEY: Dict[str, str] = {
    'T':        '°C',
    'RH':       '%',
    'CO2':      'ppm',
    'VPD':      'kPa',
    'light':    'W/m²',
    'wind_ms':  'm/s',
    'wind_gust_ms': 'm/s',
    'wind_deg': '°',
    'P':        'hPa',   # 표준 단위. 저장 단위(Pa/hPa/kPa)가 있으면 그쪽이 우선한다.
    'rssi':     'dBm',
    'snr':      'dB',
    'battery':  '%',     # 저장 단위가 V/mV/bool 이면 그쪽이 우선한다(아래 참조).
}

# DB raw unit 문자열 → 표시 단위 (device_measurements.unit 이 그대로 노출되는 것 방지)
_RAW_UNIT_DISPLAY: Dict[str, str] = {
    'c':        '°C',
    'f':        '°F',
    'k':        'K',
    'percent':  '%',
    'rh':       '%',
    'ppm':      'ppm',
    'ppb':      'ppb',
    'pa':       'Pa',
    'hpa':      'hPa',
    'kpa':      'kPa',
    'm_s':      'm/s',
    'ms':       'm/s',
    'kmh':      'km/h',
    'km_h':     'km/h',
    'mph':      'mph',
    'bearing':  '°',
    'deg':      '°',
    'degrees':  '°',
    'w_m2':     'W/m²',
    'wm2':      'W/m²',
    'lux':      'lux',
    'umol':     'µmol/m²/s',
    'v':        'V',
    'mv':       'mV',
    'ma':       'mA',
    'ohm':      'Ω',
}

def _looks_like_battery(raw_measurement: Optional[str], raw_name: Optional[str]) -> bool:
    """전압 채널이 '배터리 전압'인지 이름으로 판별한다.

    measurement 이 'electrical_potential' 인 채널은 배터리일 수도, 그냥 아무 전압
    측정일 수도 있다. 전부 배터리로 보면 태양광 전압·EC 프로브 전압까지 배터리
    배지로 그려진다. 반대로 안 보면 실제 배포된 LoRaWAN 노드 전부(RAK3172 HB 는
    V, lorawan_mode_manager 는 mV)가 배터리로 안 잡힌다 — 그래서 이름을 본다.
    """
    if (raw_measurement or '').lower().strip() not in _BATTERY_VOLTAGE_MEASUREMENTS:
        return False
    name = (raw_name or '').lower()
    return any(tok in name for tok in _BATTERY_NAME_TOKENS)


def _effective_raw_unit(dm) -> str:
    """device_measurements 의 표시용 raw 단위 문자열을 반환한다.

    conversion_id 가 설정돼 있으면 InfluxDB 에는 변환된 값이 변환 단위
    (convert_unit_to)로 저장되고, get_last_measurement 도 그 단위로 조회한다
    (system_pi.return_measurement_info 참조). 따라서 표시 단위도 raw unit 이
    아니라 변환 단위와 일치해야 한다. 예) raw 'in' + (in→mm) 변환 → 'mm'.

    conversion 이 없거나 조회 실패 시 device_measurements.unit 을 그대로 쓴다.
    """
    raw = (getattr(dm, 'unit', '') or '').strip()
    cid = (getattr(dm, 'conversion_id', '') or '').strip()
    if not cid:
        return raw
    try:
        from aot.databases.models import Conversion
        from aot.utils.database import db_retrieve_table_daemon
        conv = db_retrieve_table_daemon(Conversion, unique_id=cid)
        to_unit = (getattr(conv, 'convert_unit_to', '') or '').strip() if conv else ''
        return to_unit or raw
    except Exception:
        return raw


# 키별 표시 자리수 (옵션 sensor_label_decimals 미지정 시 사용)
_DEFAULT_DECIMALS_BY_KEY: Dict[str, int] = {
    'T':        1,
    'RH':       1,
    'CO2':      0,
    'VPD':      2,
    'light':    0,
    'wind_ms':  1,
    'wind_gust_ms': 1,
    'wind_deg': 0,
    'P':        0,
}


def channel_label_meta(measurement_type, raw_name: str, raw_unit: str,
                       raw_measurement: str = None) -> Tuple[str, str]:
    """(measurement_type, 표시명, 실효 raw 단위) → (밴드 key, 표시 단위).

    channel_meta_for_dm 의 순수 함수 버전 — ORM 행도 DB 조회도 필요 없다.
    시설 밖(구역/지도)에 배치된 Input 의 측정 채널에도 시설 라벨과 **동일한**
    key(T/RH/VPD/...)·표시 단위를 붙이기 위한 공용 진입점이다. 지도 장치 경로가
    이 규칙을 안 거치면 라벨에 key 가 없어 밴드 색상 판정 자체가 불가능해진다
    (표시명은 번역돼 들어오므로 key 대용으로 쓸 수 없다).

    raw_unit 은 conversion 이 걸린 경우 **변환 단위**를 넘겨야 한다
    (_effective_raw_unit 과 동일 계약). 호출부가 이미 conversion 을 일괄
    조회해 두었다면 그 값을 그대로 넘기면 되고, 그래야 N+1 조회가 안 생긴다.

    raw_measurement 는 DeviceMeasurements.measurement 원본값. 실제 DB 에서
    measurement_type 은 거의 항상 비어 있어서(사용자가 채우는 필드가 아니다)
    이것 없이는 key 가 하나도 안 잡힌다 — 시설 경로가 오래 전부터
    _infer_mtype_from_dm 으로 measurement 이름에서 추론해 온 이유다. 같은 표를
    쓴다: 여기서 다른 표를 쓰면 같은 센서가 시설 안/밖에서 다른 색을 받는다.
    """
    # 이름 추론은 measurement_type 이 **비었을 때뿐 아니라 매핑에 없을 때도** 돈다.
    # 예: auto_vpd 채널은 measurement_type='auto_vpd'(표에 없음) + measurement=
    # 'vapor_pressure_deficit' 이라, "비었을 때만" 추론하면 영영 안 잡힌다.
    if raw_measurement and measurement_type not in _MTYPE_KEY:
        try:
            from aot.space.facility_integration import _DM_NAME_TO_MTYPE
            inferred = _DM_NAME_TO_MTYPE.get((raw_measurement or '').lower().strip())
            if inferred:
                measurement_type = inferred
        except Exception:
            pass
    if measurement_type not in _MTYPE_KEY and _looks_like_battery(raw_measurement, raw_name):
        measurement_type = 'battery'
    key = _MTYPE_KEY.get(measurement_type) if measurement_type else None

    # 표시 단위는 **실제 저장 단위**를 우선한다. _UNIT_BY_KEY(키별 표준 단위)를
    # 무조건 씌우면 같은 key 라도 장치마다 저장 단위가 다른 채널에서 거짓말이 된다
    # — VPD 를 Pa 로 저장한 입력에 'kPa' 라벨이 붙던 것이 그 사례다. 저장 단위가
    # 비어 있을 때만 표준 단위로 메운다.
    ru = (raw_unit or '').strip()
    unit = _RAW_UNIT_DISPLAY.get(ru.lower(), ru) if ru else ''
    if not unit and key:
        unit = _UNIT_BY_KEY.get(key, '')
    display_key = key or (raw_name or '').strip() or (measurement_type or '')
    return display_key, unit


def channel_meta_for_dm(dm) -> dict:
    """DeviceMeasurements 한 행 → 차트/라벨용 채널 메타({key, unit, ...}).

    facility 라벨/팝업과 동일한 규칙으로 measurement_type → key(T/RH/...)와
    표시 단위를 만든다. 매핑 안 된 채널은 사용자 지정 name/measurement 과
    raw unit 표시 변환(_RAW_UNIT_DISPLAY)으로 라벨링해 UUID·raw 단위 노출을 막는다.
    """
    mtype = (getattr(dm, 'measurement_type', None) or None)
    m_name = ((getattr(dm, 'name', '') or '').strip()
              or (getattr(dm, 'measurement', '') or '').strip())
    m_unit = _effective_raw_unit(dm)   # conversion_id 있으면 변환 단위 사용
    display_key, unit = channel_label_meta(
        mtype, m_name, m_unit, getattr(dm, 'measurement', '') or '')

    return {
        'measurement_id':   dm.unique_id,
        'measurement_type': mtype,
        'key':              display_key,
        'unit':             unit,
        'channel':          getattr(dm, 'channel', None),
    }


def read_fitting_sensors(
    sensors_resolved_all: List[dict],
    max_age: Optional[int] = None,
) -> List[dict]:
    """fitting(kind=sensor) 별로 모든 채널 측정값을 묶어 반환한다.

    위젯 3D/지도 라벨에 사용. sensors_resolved + sensors_outdoor 를 모두 받아
    fitting_id 단위로 채널 배열을 만든다. 같은 fitting_id 의 여러 채널은
    동일 device 의 multi-measurement (T+RH+CO2 복합센서 등) 로 간주.

    Args
    ----
    sensors_resolved_all : facility_integration 의 sensors_resolved + sensors_outdoor.
        각 항목: {fitting_id, name, position, sensor_role, input_uuid,
                  measurement_id, measurement_type, input_name, input_device}
    max_age : 측정값 최대 유효 수명(초).

    Returns
    -------
    [{
        'fitting_id':  str,
        'name':        str,
        'position':    [x, y, z] | None,
        'sensor_role': 'indoor' | 'outdoor',
        'device_id':   str,
        'device_name': str | None,
        'channels': [
            {
                'measurement_id':   str,
                'measurement_type': str | None,
                'key':              str,   # 'T' | 'RH' | 'CO2' | ...
                'value':            float | None,
                'unit':             str,
                'ts':               str | None,  # ISO 8601
                'valid':            bool,
                'stale':            bool,
            }, ...
        ]
    }, ...]
    """
    from aot.utils.influx import get_last_measurement as _get_last

    # ── DeviceMeasurements 이름/단위 일괄 조회 (UUID 노출 방지) ───────────────
    # measurement_type 매핑(_MTYPE_KEY) 에 없는 채널도 사용자가 부여한 이름을
    # 그대로 표시한다. measurement_id → (display_name, unit) 사전.
    meta: Dict[str, Tuple[str, str, str]] = {}
    try:
        from aot.databases.models.measurement import DeviceMeasurements
        from aot.utils.database import db_retrieve_table_daemon
        ids = list({(s.get('measurement_id') or '') for s in (sensors_resolved_all or [])
                    if s.get('measurement_id')})
        if ids:
            rows = db_retrieve_table_daemon(DeviceMeasurements).filter(
                DeviceMeasurements.unique_id.in_(ids)
            ).all()
            for r in rows:
                display = (r.name or '').strip() or (r.measurement or '').strip() or ''
                # conversion_id 있으면 변환 단위(convert_unit_to)로 라벨링
                meta[r.unique_id] = (display, _effective_raw_unit(r), (r.measurement or '').strip())
    except Exception as exc:
        logger.debug('[FittingSensors] DeviceMeasurements lookup failed: %s', exc)

    # fitting_id → 누적 채널 목록
    grouped: Dict[str, dict] = {}
    order: List[str] = []  # 입력 순서 유지

    # 표시 경로(max_age 미지정)에서만 장치 주기를 조회한다 — 한 번의 IN 조회.
    fresh = _freshness_by_device(
        [s.get('input_uuid') for s in (sensors_resolved_all or [])])

    for s in (sensors_resolved_all or []):
        fid = s.get('fitting_id')
        if not fid:
            continue
        if fid not in grouped:
            display_name = s.get('name') or s.get('input_name') or fid
            grouped[fid] = {
                'fitting_id':  fid,
                'name':        display_name,
                'position':    s.get('position'),
                'bay_id':      s.get('bay_id'),
                'sensor_role': s.get('sensor_role') or 'indoor',
                'device_id':   s.get('input_uuid') or '',
                'device_name': s.get('input_name'),
                'channels':    [],
            }
            order.append(fid)

        iid     = s.get('input_uuid')
        meas_id = s.get('measurement_id')
        mtype   = s.get('measurement_type') or None
        if not iid or not meas_id:
            continue

        # 매핑 안 된 채널은 DeviceMeasurements 의 name/measurement 으로 라벨링.
        # UUID(measurement_id) 가 사용자에게 노출되지 않도록 한다.
        # 표시 단위는 channel_label_meta 가 실제 저장 단위(m_unit)를 우선하고,
        # 저장 단위가 없을 때만 _UNIT_BY_KEY 표준 단위로 메운다 — 이 규칙을
        # 여기서 다시 구현하면(과거처럼 표준 단위를 무조건 먼저 채우면) 저장
        # 단위가 다른 채널(예: bar 로 저장된 압력)에서 라벨이 거짓말을 한다.
        m_name, m_unit, m_measurement = meta.get(meas_id, ('', '', ''))
        display_key, unit = channel_label_meta(mtype, m_name, m_unit, m_measurement)

        ch: dict = {
            'measurement_id':   meas_id,
            'measurement_type': mtype,
            'key':              display_key,
            'value':            None,
            'unit':             unit,
            'ts':               None,
            'valid':            False,
            'stale':            False,
        }

        try:
            ts, val = _get_last(iid, meas_id,
                                max_age=_max_age_for(max_age, *_fresh(fresh, iid)))
        except Exception as exc:
            logger.debug('[FittingSensors] %s/%s 조회 실패: %s', iid, meas_id, exc)
            ts, val = None, None

        def _ts_iso(t):
            if t is None:
                return None
            if hasattr(t, 'isoformat'):
                return t.isoformat()
            try:
                import datetime as _dt
                return naive_utc(parse_utc(float(t))).isoformat() + 'Z'
            except Exception:
                return str(t)

        if ts is not None and val is not None:
            ch['value'] = float(val)
            ch['ts']    = _ts_iso(ts)
            ch['valid'] = True
        else:
            # max_age 초과인지 확인 (stale 표시용)
            try:
                ts_any, val_any = _get_last(iid, meas_id, max_age=None)
                if ts_any is not None:
                    ch['stale'] = True
                    ch['ts']    = _ts_iso(ts_any)
                    if val_any is not None:
                        ch['value'] = float(val_any)
            except Exception:
                pass

        grouped[fid]['channels'].append(ch)

    return [grouped[fid] for fid in order]


def _dm_row(measurement_id):
    """measurement_id → DeviceMeasurements 행 (없으면 None)."""
    if not measurement_id:
        return None
    try:
        from aot.databases.models.measurement import DeviceMeasurements
        from aot.utils.database import db_retrieve_table_daemon
        return db_retrieve_table_daemon(DeviceMeasurements).filter(
            DeviceMeasurements.unique_id == measurement_id).first()
    except Exception:                                           # noqa: BLE001
        return None


def _normalise_light(value, dm):
    """광량 값을 **전천일사(W/m²)로** 맞춘다.

    ⚠ **`light` 결과 키는 W/m² 로 약속돼 있다**(`_UNIT_BY_KEY`). 그런데
      `_MEAS_LIGHT_NAMES` 는 `lux`·`ppfd`·`par` 도 광량으로 받아들이므로,
      값을 그대로 실으면 **자릿수가 다른 숫자가 임계와 비교된다** — 조도계
      50,000 lux 가 50,000 W/m² 로 읽혀 `light_max`(기본 800)를 언제나 넘고,
      차광막이 영구히 닫힌다. 에러는 나지 않는다.

      같은 값이 실내 광량 추정(`estimate_indoor_light`)·일소 잠금·DLI 로도
      흘러가므로, 어긋나면 그 셋이 함께 틀어진다.

    ⚠ **변환표를 여기서 만들지 말 것.** `cumulative_tracker` 가 이미 시스템
      변환표(`config_devices_units.UNIT_CONVERSIONS`)를 단일 출처로 쓰고
      있다. 두 벌이 되면 갈라지고, 갈라지면 화면과 제어가 다른 값을 본다.

    ⚠ 단위를 모르면 **바꾸지 않는다.** 모르는 것을 추측해서 곱하면 원래 맞던
      값까지 틀어진다(변환기 쪽도 같은 규칙이다).
    """
    if value is None or dm is None:
        return value
    unit = _effective_raw_unit(dm)      # conversion 이 걸렸으면 변환 단위
    if not unit:
        return value
    try:
        from aot.utils.light_units import light_to_wm2
        out = light_to_wm2(float(value), unit)
        return float(value) if out is None else out
    except Exception:                                           # noqa: BLE001
        return value


def _is_rain_channel(dm) -> bool:
    """이름이나 저장 단위로 이 채널을 강우로 읽어도 되는가(사용자가 채널을 직접 고르지
    않은 경로 — measurement_type 만 있거나 자동 스캔). 확률(%)·증발산은 강우가 아니다."""
    meas_lower = (getattr(dm, 'measurement', '') or '').lower()
    unit = _effective_raw_unit(dm).lower()
    if unit in _NOT_RAIN_UNITS or meas_lower in _NOT_RAIN_MEASUREMENTS:
        return False
    return meas_lower in _MEAS_RAIN_NAMES or unit in _RAIN_UNITS


def _normalise_rain(value, dm):
    """강우 값을 **mm/h**(감우기는 0/1)로 맞춘다 — 규칙의 정본은
    `aot.utils.inputs.rain_unit_scale`(강우 게이트도 같은 단위로 본다).

    `_normalise_light` 와 같은 자리·같은 원칙이다: 단위를 모르면 바꾸지 않는다.
    """
    if value is None or dm is None:
        return value
    try:
        from aot.utils.inputs import rain_channel_mm_h
        return rain_channel_mm_h(float(value), dm, unit=_effective_raw_unit(dm))
    except Exception:                                           # noqa: BLE001
        return value


def _accept_reading(result: dict, rkey: str, val, probe: Optional[dict],
                    frozen=None, ident=None, ts=None) -> None:
    """판독을 범위 검사한 뒤 `result` 에 싣는다 (`sensor_status.check_value`).

    frozen: `sensor_status.FrozenTracker` — 주어지면 범위를 통과한 값이 **멈춘 센서**인지
    (`ident` = (장치, 채널) 키, `ts` = 표본 시각) 본다. 멈췄으면 범위 밖과 똑같이 싣지
    않고 probe 에 `frozen` 으로 남긴다. 제어 사이클만 넘기고 화면 경로는 넘기지 않는다.

    범위 밖(습도 130 % 등)이면 **싣지 않는다** — 평균에 섞이면 다른 센서의 값까지
    오염시키고, 센서가 하나뿐이면 지어낸 값으로 장치가 움직인다. 싣지 않으므로
    호출부에서는 "이 센서는 값이 없다" 와 같다(기존 결측 경로). 판독은 probe 에만
    `out_of_range` 로 남는다. 습도 100 초과 102 이하는 눈금 오차라 100 으로 자른다.
    """
    kind = _ss.FACILITY_KEY_KIND.get(rkey)
    if kind is not None:
        status, val = _ss.check_value(kind, val)
        if status == _ss.OUT_OF_RANGE:
            logger.debug('[FacilitySensors] %s 물리 범위 밖 판독을 버립니다', rkey)
            if probe is not None:
                probe[rkey] = _ss.OUT_OF_RANGE
            return
    # VPD 는 따로 재지 않는다 — 같은 장치의 T·RH 가 멈췄으면 그 VPD 도 같은 값이 멈춘 것이다
    # (장치 VPD 폴백이 멈춘 값을 되살리지 못하게). 판정 근거는 `sensor_status.FROZEN_KINDS` 주석.
    if (frozen is not None and ident is not None
            and (frozen.device_frozen(ident[0]) if rkey == 'VPD'
                 else frozen.observe(ident, rkey, val, ts))):
        logger.debug('[FacilitySensors] %s 값이 멈춘 센서의 판독을 버립니다', rkey)
        if probe is not None:
            probe[rkey] = _ss.FROZEN
        return
    result[rkey] = val
    if probe is not None:
        probe[rkey] = _ss.VALID


def _note_miss(probe: Optional[dict], rkey: str, input_uuid: str, meas_id) -> None:
    """max_age 안에 값이 없었던 채널이 stale 인지 missing 인지 probe 에 남긴다.

    `max_age=None` 으로 한 번 더 조회해 가른다 — 데이터가 있으면 낡은 것(stale),
    없으면 없는 것(missing). 추가 조회는 **값을 못 받은 채널에서만, 상태를 물은
    호출(probe 가 있을 때)에서만** 일어난다.
    """
    if probe is None or rkey in probe:
        return
    kind = _ss.MISSING
    if meas_id:
        try:
            # 지역 import — `_read_one_sensor` 와 같은 조회 함수를 쓴다(테스트가
            # 패치하는 자리가 `aot.utils.influx` 쪽이다).
            from aot.utils.influx import get_last_measurement as _glm
            ts_any, _v = _glm(input_uuid, meas_id, max_age=None)
            if ts_any is not None:
                kind = _ss.STALE
        except Exception:
            pass
    probe[rkey] = kind


def _read_one_sensor(
    input_uuid: str,
    measurement_type: Optional[str],
    max_age: int,
    measurement_id: Optional[str] = None,
    probe: Optional[dict] = None,
    frozen=None,
) -> Dict[str, Optional[float]]:
    """input_uuid 장치에서 측정값을 하나 읽어 {result_key: value} 로 반환한다.

    measurement_id 가 지정된 경우 해당 채널을 직접 조회한다 (이름 추론 불필요).
    measurement_type 으로 결과 키(T, RH, CO2 …)를 결정한다.
    둘 다 없으면 T·RH 이름 추론(하위 호환).

    probe: 주어지면 `{결과 키: valid|stale|missing|out_of_range}` 를 채운다
    (`sensor_status`). 값 자체는 probe 와 무관하게 범위 검사를 거친다.

    frozen: `sensor_status.FrozenTracker` — 멈춘 센서 판정(`_accept_reading`). 제어만 넘긴다.
    """
    from aot.utils.influx import get_last_measurement

    result: Dict[str, Optional[float]] = {}

    # measurement_id 있고 measurement_type 없으면 DB에서 measurement 이름으로 추론
    if measurement_id and not measurement_type:
        try:
            from aot.databases.models.measurement import DeviceMeasurements
            from aot.utils.database import db_retrieve_table_daemon
            from aot.space.facility_integration import _infer_mtype_from_dm
            _dm = db_retrieve_table_daemon(DeviceMeasurements).filter(
                DeviceMeasurements.unique_id == measurement_id
            ).first()
            measurement_type = _infer_mtype_from_dm(_dm)
        except Exception:
            pass

    if measurement_id and measurement_type and measurement_type in _MTYPE_KEY:
        # 채널 직접 조회 — 이름 추론 없음
        rkey = _MTYPE_KEY[measurement_type]
        try:
            ts, val = get_last_measurement(input_uuid, measurement_id, max_age=max_age)
            if ts is not None and val is not None:
                val = float(val)
                if rkey == 'light':
                    val = _normalise_light(val, _dm_row(measurement_id))
                elif rkey == 'rain_mm':
                    val = _normalise_rain(val, _dm_row(measurement_id))
                _accept_reading(result, rkey, val, probe, frozen,
                                (input_uuid, measurement_id), ts)
        except Exception:
            pass
        _note_miss(probe, rkey, input_uuid, measurement_id)
        return result

    if measurement_type and measurement_type in _MTYPE_MAP:
        # measurement_id 없이 measurement_type 만 있는 경우 — 이름으로 채널 탐색
        from aot.databases.models.measurement import DeviceMeasurements
        from aot.utils.database import db_retrieve_table_daemon
        target_names, _ = _MTYPE_MAP[measurement_type]
        rkey = _MTYPE_KEY[measurement_type]
        try:
            dm_rows = db_retrieve_table_daemon(DeviceMeasurements).filter(
                DeviceMeasurements.device_id == input_uuid
            ).all()
        except Exception:
            dm_rows = []
        for dm in dm_rows:
            meas_lower = (dm.measurement or '').lower()
            matched = meas_lower in target_names
            # 이름 불일치 시 **저장 단위**로 재확인 — 변환이 걸린 채널은 이름이
            # 원시 그대로여도 단위가 목표 단위다.
            #
            # ⚠ 예전에는 `return_measurement_info(dm.unique_id)` 였다. 그 함수의
            #   시그니처는 `(행, conversion)` 이라 **TypeError** 가 났고, 바로
            #   아래 `except` 가 그것을 삼켜 이 재확인은 **한 번도 성립한 적이
            #   없었다**(2026-08-27 실측). `_effective_raw_unit` 이 같은 답을
            #   행 하나로 준다.
            if measurement_type == 'rain':
                matched = _is_rain_channel(dm)
            if matched:
                try:
                    ts, val = get_last_measurement(input_uuid, dm.unique_id, max_age=max_age)
                    if ts is not None and val is not None:
                        val = float(val)
                        if rkey == 'light':
                            val = _normalise_light(val, dm)
                        elif rkey == 'rain_mm':
                            val = _normalise_rain(val, dm)
                        _accept_reading(result, rkey, val, probe, frozen,
                                        (input_uuid, dm.unique_id), ts)
                except Exception:
                    pass
                _note_miss(probe, rkey, input_uuid, dm.unique_id)
                break
        else:
            _note_miss(probe, rkey, input_uuid, None)   # 맞는 채널이 없다 — missing
        return result

    # 하위 호환: measurement_id / measurement_type 모두 미설정 → T·RH 이름 추론
    from aot.databases.models.measurement import DeviceMeasurements
    from aot.utils.database import db_retrieve_table_daemon
    try:
        dm_rows = db_retrieve_table_daemon(DeviceMeasurements).filter(
            DeviceMeasurements.device_id == input_uuid
        ).all()
    except Exception:
        dm_rows = []
    t_val = rh_val = None
    t_src = rh_src = None       # (채널 id, 표본 시각) — 멈춘 센서 판정용
    for dm in dm_rows:
        meas_lower = (dm.measurement or '').lower()
        # 상태를 물은 호출이면 T·RH 로 읽히는 채널의 실패를 stale/missing 으로 가른다.
        rkey_try = ('T' if meas_lower in _MEAS_T_NAMES
                    else 'RH' if meas_lower in _MEAS_RH_NAMES else None)
        try:
            ts, val = get_last_measurement(input_uuid, dm.unique_id, max_age=max_age)
        except Exception:
            if rkey_try:
                _note_miss(probe, rkey_try, input_uuid, dm.unique_id)
            continue
        if ts is None or val is None:
            if rkey_try:
                _note_miss(probe, rkey_try, input_uuid, dm.unique_id)
            continue
        if meas_lower in _MEAS_T_NAMES and t_val is None:
            t_val = float(val)
            t_src = (dm.unique_id, ts)
        elif meas_lower in _MEAS_RH_NAMES and rh_val is None:
            rh_val = float(val)
            rh_src = (dm.unique_id, ts)
    # 값이 있는 쪽이 먼저 probe 를 채우도록 — 이미 miss 가 적혀 있어도 valid 가 덮는다.
    for _rk, _v, _src in (('T', t_val, t_src), ('RH', rh_val, rh_src)):
        if _v is not None:
            if probe is not None:
                probe.pop(_rk, None)
            _accept_reading(result, _rk, _v, probe, frozen,
                            (input_uuid, _src[0]), _src[1])
    return result


def _reject_spatial_outliers(
    readings: List[Tuple[int, float]],
    scale_floor: float = SPATIAL_SCALE_FLOOR_DEFAULT,
) -> Tuple[List[Tuple[int, float]], List[int]]:
    """등가 환경 전제 하 공간 outlier(이상 센서) 제거.

    같은 마이크로환경에 설치된 센서들이라는 전제 하에, 동일 시각의 측정값들
    사이에서 robust z-score 가 SPATIAL_MAD_K 를 초과하는 센서는 오작동으로
    간주하고 제외한다.

    척도(scale)는 1.4826·MAD 와 scale_floor 중 큰 값을 사용한다. 이는 다수
    센서가 동일값(MAD=0)을 뱉을 때도 명백히 튀는 센서를 잡아낼 수 있게 한다.
    scale_floor 는 해당 변수의 정상 잡음 한계로 설정해야 false-positive 가
    없다 (예: T 는 0.5°C).

    Args
    ----
    readings    : List of (detail_idx, value).
    scale_floor : 최소 척도. MAD 가 이보다 작으면 이 값으로 대체.

    Returns
    -------
    (kept, rejected_indices). 판단 불가(샘플 < SPATIAL_MIN_FOR_REJECT)이면
    전부 유지. 과반이 outlier 로 판정되면 (다수 동시 오작동 또는 임계 부적절)
    median 자체를 신뢰할 수 없으므로 보수적으로 전부 유지.
    """
    if len(readings) < SPATIAL_MIN_FOR_REJECT:
        return list(readings), []

    import statistics
    vals = [v for _, v in readings]
    median = statistics.median(vals)
    deviations = [abs(v - median) for v in vals]
    mad = statistics.median(deviations)
    scale = max(1.4826 * mad, scale_floor)

    kept: List[Tuple[int, float]] = []
    rejected: List[int] = []
    for idx, v in readings:
        z = abs(v - median) / scale
        if z > SPATIAL_MAD_K:
            rejected.append(idx)
        else:
            kept.append((idx, v))

    # 과반이 reject 되면 median 자체를 못 믿음 → 보수적으로 전부 유지
    if len(rejected) > len(readings) // 2:
        return list(readings), []
    return kept, rejected


def compute_spatial_internal(
    sensors_resolved: List[dict],
    max_age: Optional[int] = None,
    with_status: bool = False,
    frozen=None,
) -> dict:
    """sensors_resolved 목록에서 위치 인식 내부 환경값을 계산한다 (D2).

    measurement_type 이 설정된 센서는 해당 항목을 정확히 읽는다.
    미설정 센서는 T/RH 이름 추론(하위 호환).

    등가 환경 전제: 모든 실내 센서가 동일 마이크로환경을 측정한다고 가정.
    따라서 동시각 측정값 사이의 큰 편차는 센서 오작동으로 간주하고
    _reject_spatial_outliers() 로 평균 계산에서 제외한다.

    Returns
    -------
    {
        'T'          : float | None,        # outlier 제거 후 평균
        'RH'         : float | None,
        'CO2'        : float | None,
        'VPD'        : float | None,        # 표시용 — 장치 VPD 가 있으면 그것, 없으면 T/RH 계산값
        'VPD_device' : float | None,        # 장치가 준 VPD 만(없으면 None) — 엽온 기준일 수 있다
        'VPD_calc'   : float | None,        # 이 계산의 T/RH 평균에서 구한 공기 VPD
        'light'      : float | None,
        'T_min'      : float | None,        # outlier 제거 후 극값 (safety_gates 용)
        'T_max'      : float | None,
        'RH_min'     : float | None,
        'RH_max'     : float | None,
        'detail'     : list,                # 각 항목에 rejected: {key: True} 가능
        'hotspot_T'  : bool,
        'hotspot_RH' : bool,
        'valid_count': int,
        'rejected_count': int,              # outlier 로 제외된 (센서·항목) 쌍 수
        'source'     : 'spatial',
        'status'     : {axis: {status, counts, n}},   # with_status=True 일 때만
    }

    with_status: True 면 센서별 판독 상태(valid/stale/missing/outlier/out_of_range)를
        `detail[i]['status']` 와 축별 요약 `status` 로 싣는다. stale 과 missing 을
        가르려면 값을 못 받은 채널마다 max_age 없이 한 번 더 조회하므로 상태가 필요한
        호출(제어 사이클)만 켠다. 범위 밖 판독을 버리는 것은 이 옵션과 무관하게 늘 한다.
    frozen: `sensor_status.FrozenTracker` — 주어지면 값이 오래 멈춘 센서(T·RH·CO2)의 판독도
        버린다(상태 `frozen`). 추적 상태가 필요해 코디네이터만 넘긴다 — 화면 경로는 넘기지 않는다.
    """
    # key → [(detail_idx, value)]
    buckets: Dict[str, List[Tuple[int, float]]] = {
        k: [] for k in ('T', 'RH', 'CO2', 'VPD', 'light')
    }
    detail: List[dict] = []

    # 표시 경로(max_age 미지정)에서만 장치 주기를 조회한다 — 한 번의 IN 조회.
    fresh = _freshness_by_device(
        [s.get('input_uuid') for s in (sensors_resolved or [])])

    for s in (sensors_resolved or []):
        input_uuid = s.get('input_uuid')
        if not input_uuid:
            continue

        mtype   = s.get('measurement_type') or None
        meas_id = s.get('measurement_id')   or None
        probe: Optional[dict] = {} if with_status else None
        # probe·frozen 은 필요한 호출만 넘긴다(읽기 함수를 갈아 끼운 테스트 호환).
        _probe_kw = {'probe': probe} if probe is not None else {}
        if frozen is not None:
            _probe_kw['frozen'] = frozen
        vals = _read_one_sensor(input_uuid, mtype,
                                _max_age_for(max_age, *_fresh(fresh, input_uuid)),
                                measurement_id=meas_id, **_probe_kw)

        d_idx = len(detail)
        for k in buckets:
            if k in vals and vals[k] is not None:
                buckets[k].append((d_idx, vals[k]))

        detail.append({
            'fitting_id':       s.get('fitting_id'),
            'name':             s.get('name') or input_uuid,
            'position':         s.get('position'),
            'measurement_type': mtype,
            'rejected':         {},  # {key: True} — 공간 outlier 로 제외된 항목
            # **응답 여부는 "값이 하나라도 왔는가" 다.** 아래 다섯 키(T/RH/CO2/
            # VPD/light)는 실내 환경 평균에 쓰이는 것일 뿐, 센서가 살아 있는지와
            # 다른 이야기다 — 이슬점·풍속만 재는 센서는 멀쩡히 응답하는데도
            # 예전에는 "응답 없음" 으로 셌다(2026-08-20 육묘장: 바닥센서 하나가
            # 그래서 영영 4/5 였다).
            'responded':        any(v is not None for v in vals.values()),
            **{k: vals.get(k) for k in ('T', 'RH', 'CO2', 'VPD', 'light')},
        })
        if with_status:     # 상태를 물은 호출에만 — 화면 응답의 모양은 그대로 둔다
            detail[-1]['status'] = {k: v for k, v in probe.items() if k in buckets}

    # ── 등가 환경 전제: 공간 outlier 제거 ────────────────────────────────────
    kept: Dict[str, List[float]] = {}
    rejected_count = 0
    for k, readings in buckets.items():
        floor = SPATIAL_SCALE_FLOOR.get(k, SPATIAL_SCALE_FLOOR_DEFAULT)
        kept_pairs, rejected_idx = _reject_spatial_outliers(readings, scale_floor=floor)
        kept[k] = [v for _, v in kept_pairs]
        for ridx in rejected_idx:
            detail[ridx]['rejected'][k] = True
            if with_status:
                detail[ridx]['status'][k] = _ss.OUTLIER
        rejected_count += len(rejected_idx)

    def _avg(lst: List[float], ndigits: int) -> Optional[float]:
        return round(sum(lst) / len(lst), ndigits) if lst else None

    def _min(lst: List[float], ndigits: int) -> Optional[float]:
        return round(min(lst), ndigits) if lst else None

    def _max(lst: List[float], ndigits: int) -> Optional[float]:
        return round(max(lst), ndigits) if lst else None

    T_readings  = kept['T']
    RH_readings = kept['RH']
    # outlier 제거 후에도 잔여 편차가 큰 경우만 hotspot — 등가 환경 전제 하에서는
    # 실제 공간 편차이거나 임계 미만 다중 오작동 가능성.
    hotspot_T   = len(T_readings)  > 1 and (max(T_readings)  - min(T_readings))  > HOTSPOT_DELTA_T
    hotspot_RH  = len(RH_readings) > 1 and (max(RH_readings) - min(RH_readings)) > HOTSPOT_DELTA_RH

    # VPD 센서 미설정 시 T/RH 평균으로 자동 계산
    vpd_readings = kept['VPD']
    # 호출자가 "센서가 준 VPD" 와 "T/RH 로 계산한 VPD" 를 가를 수 있게 남긴다 —
    # 계산값이면 걸러진 T/RH 로 다시 계산하는 쪽이 맞다(env_coordinator 잡음 필터).
    vpd_measured = bool(vpd_readings)
    vpd_device = (round(sum(vpd_readings) / len(vpd_readings), 3)
                  if vpd_readings else None)
    # 공기 VPD — 장치 VPD 와 무관하게 늘 구해 둔다. 제어는 이쪽을 쓴다(장치 VPD 는
    # 엽온 기준일 수 있어 목표와 의미가 다르다 — env_coordinator `_collect_internal`).
    vpd_calc_value = None
    if T_readings and RH_readings:
        T_avg  = sum(T_readings)  / len(T_readings)
        RH_avg = sum(RH_readings) / len(RH_readings)
        vpd_calc_value = round(psychro.vpd_from_rh(T_avg, RH_avg), 3)
        if not vpd_readings:
            vpd_readings = [vpd_calc_value]

    # 화면 문구가 "센서 응답" 이므로 세는 것도 **응답**이어야 한다. 환경 평균에
    # 기여하지 않는 센서(이슬점·풍속 전용)를 고장처럼 세면, 사용자는 멀쩡한
    # 장치를 찾아 헤맨다.
    valid = sum(1 for d in detail if d.get('responded'))
    status = None
    if with_status:
        status = {
            k: _ss.summarize(d['status'][k] for d in detail if k in d['status'])
            for k in _ss.INDOOR_AXES
        }
    out = {
        'T':           _avg(T_readings,         2),
        'RH':          _avg(RH_readings,        1),
        'CO2':         _avg(kept['CO2'],        0),
        'VPD':         _avg(vpd_readings,       3),
        'VPD_device':  vpd_device,
        'VPD_calc':    vpd_calc_value,
        'vpd_measured': vpd_measured,
        'light':       _avg(kept['light'],      1),
        'T_min':       _min(T_readings,         2),
        'T_max':       _max(T_readings,         2),
        'RH_min':      _min(RH_readings,        1),
        'RH_max':      _max(RH_readings,        1),
        'detail':      detail,
        'hotspot_T':   hotspot_T,
        'hotspot_RH':  hotspot_RH,
        'valid_count': valid,
        'rejected_count': rejected_count,
        'source':      'spatial',
    }
    if status is not None:
        out['status'] = status
    return out


def sensor_priority_of(entry: dict) -> str:
    """실외 센서의 순위 — 'backup' 이라고 적힌 것만 백업이고 나머지는 메인이다.

    ⚠ 모르는 값을 백업으로 읽지 말 것. 오타 하나로 멀쩡한 기상대가 뒤로
      밀리면 API 값이 제어를 가져가는데 아무 에러도 안 난다.
    """
    raw = (entry or {}).get('sensor_priority')
    return 'backup' if str(raw or '').strip().lower() == 'backup' else 'primary'


def _rain_origin(device_ids) -> str:
    """강우 출처 — 판정은 `aot.utils.inputs.rain_origin_of` 하나다(수집기도 같은 것을
    부른다). 데몬 모듈이 이 Flask 패키지를 거치지 않게 거기 둔다."""
    from aot.utils.inputs import rain_origin_of
    return rain_origin_of(device_ids)


# @manual ai/env-control#safety-gates, geo/facility#sensor-roles
def read_outdoor_sensors(
    sensors_outdoor: List[dict],
    max_age: Optional[int] = None,
    with_status: bool = False,
    frozen=None,
    rain_seen: Optional[dict] = None,
) -> dict:
    """sensors_outdoor 목록에서 실외 환경값을 읽는다.

    measurement_type 이 설정된 경우 해당 항목을 정확히 읽는다.
    미설정 센서는 T/RH 이름 추론(하위 호환).

    Returns
    -------
    {
        'T_ext'      : float | None,
        'RH_ext'     : float | None,
        'CO2_ext'    : float | None,
        'wind_ms'    : float | None,
        'wind_deg'   : float | None,
        'wind_gust_ms': float | None,  # 'wind_gust' 채널의 최댓값(센서 여럿이면 가장 센 값)
        'solar_wm2'  : float | None,
        'rain_mm'    : float | None,   # **mm/h**(감우기는 0/1) — `utils.inputs.rain_unit_scale`
        'rain_origin': 'model' | 'measured' | None,  # 강우 값의 출처(`utils.inputs.rain_origin_of`)
        'valid_count': int,
        'total_count': int,
        'status'     : {축: {status, counts, n}},  # with_status=True 일 때만
    }

    with_status: `compute_spatial_internal` 과 같다. 축은 `sensor_status.OUTDOOR_AXES`
    (T_ext·RH_ext·wind·rain·solar). 메인/백업 순위와 무관하게 그 축을 먹이는 모든
    센서의 상태를 요약한다 — 값 선택(`backup_keys`)과는 다른 질문이다.

    frozen: `compute_spatial_internal` 과 같다. 실외는 T·RH 만 본다(CO2_ext 는 축이 없다).

    rain_seen: 제어(코디네이터)가 사이클 사이에 들고 다니는 dict — 마지막 **신선한 실측**
    강우(`measured_mm`)와 그 장치(`devices`). 실측 강우계가 끊겼는데 끊기기 직전 비가
    오고 있었으면 예보 모델 값으로 갈아타지 않는다(아래 '규칙 A' 주석). 화면 경로는 넘기지
    않는다(기억이 없으면 예전과 같다).
    """
    # ── 메인과 백업 (2026-09-14) ─────────────────────────────────────────────
    # 실외 센서가 둘 이상일 때 **동등하게 평균하지 않는다.** 현장 기상대가
    # 메인이고 위성·예보 API 는 기상대가 꺼질 때를 대비한 백업인데, 둘을
    # 평균하면 멀쩡한 기상대 값이 API 쪽으로 끌려간다. 실측(2026-09-14
    # aot-005): 09:40 기상대 22.9 °C · 62 % 인데 Open-Meteo 는 19.5 °C · 79 %
    # 였다 — 평균하면 실외가 실제보다 차고 습해져 창이 늦게 열린다.
    #
    # 규칙: 값 종류마다 **메인에 신선한 값이 하나라도 있으면 메인만** 쓰고,
    # 메인이 전부 끊겼을 때만 백업을 쓴다. 같은 순위 안에서는 예전처럼 평균이다.
    #
    # ⚠ **온도와 습도는 짝으로 고른다.** 메인이 온도만 주고 습도를 못 줄 때
    #   종류별로 따로 고르면 메인 온도 + 백업 습도가 되어, 서로 다른 장소의
    #   두 값으로 VPD 를 계산한다. 짝이 온전한 순위를 먼저 찾는다.
    #
    # 순위가 없는 설비(기존 설치 전부)는 메인이다 — 업그레이드로 동작이 바뀌지
    # 않는다.
    #
    # ── 실측과 예보 모델도 섞지 않는다 (2026-10-10) ─────────────────────────────
    # 순위 표시 없이(= 둘 다 메인) 강우계와 Open-Meteo 를 묶은 설치에서 강우계 0 과
    # 예보 1.2 가 **평균**되어 0.6 ≥ 문턱 0.5 — 게다가 실측이 섞였으니 출처는 'measured'
    # (`rain_origin_of` 는 전부 모델일 때만 'model') 라 한낮에 창을 **전부** 닫았다(폐루프
    # `rain_gauge_vs_forecast_primary`, 실내 47.6 °C). 출처(`data_origin`)는 순위 안에서
    # 한 번 더 가른다:
    #   온도·습도·풍속·풍향·일사·CO₂  메인 실측 > 메인 모델 > 백업 실측 > 백업 모델
    #                                (사용자가 적은 순위가 먼저 — 그 안에서 실측 먼저)
    #   강우                         메인 실측 > 백업 실측 > 메인 모델 > 백업 모델
    #                                (신선한 실측이 하나라도 있으면 실측만 — 순위보다 앞선다)
    # 강우만 순위를 넘는 이유: 실측 강우가 게이트를 더 엄격하게 쓴다(전부 닫음). 예보가 메인이고
    # 강우계가 백업인 설치에서 예보를 따르면 지금 오는 비를 모델의 "약한 비" 로 깎는다.
    # 같은 묶음 안에서 강우는 **최댓값**이다(나머지는 예전처럼 평균): 감우기(0/1)와 강우율을
    # 평균하면 뜻이 없는 숫자가 되고, 한 강우계만 비를 볼 때(막힘·국지 소나기) 평균은 비를
    # 반으로 깎는다 — 닫는 쪽으로 틀리는 편이 안전하다.
    _KEYS = ('T', 'RH', 'CO2', 'wind_ms', 'wind_deg', 'wind_gust_ms', 'light', 'rain_mm')
    _ORDER = (('primary', 'measured'), ('primary', 'model'),
              ('backup', 'measured'), ('backup', 'model'))
    _RAIN_ORDER = (('primary', 'measured'), ('backup', 'measured'),
                   ('primary', 'model'), ('backup', 'model'))
    total = 0
    outdoor_device_ids: List[str] = []
    device_tier: Dict[str, str] = {}
    # (값 종류, 순위, 장치, 값) — 출처는 장치 목록이 다 모인 뒤 한 번에 가른다.
    raw: List[Tuple[str, str, str, float]] = []
    # 강우를 **고른**(measurement_type 'rain') 장치 — 끊긴 실측 강우계를 알아보는 근거.
    rain_bound: List[str] = []

    # 표시 경로(max_age 미지정)에서만 장치 주기를 조회한다 — 한 번의 IN 조회.
    fresh = _freshness_by_device(
        [s.get('input_uuid') for s in (sensors_outdoor or [])])

    axis_statuses: Dict[str, List[str]] = {a: [] for a in _ss.OUTDOOR_AXES}
    rain_from: List[str] = []

    for s in (sensors_outdoor or []):
        input_uuid = s.get('input_uuid')
        if not input_uuid:
            continue
        total += 1
        tier = sensor_priority_of(s)
        if input_uuid not in outdoor_device_ids:
            outdoor_device_ids.append(input_uuid)
        # 한 장치가 두 순위에 걸쳐 있으면 메인으로 본다(강우 자동 스캔 순서용).
        if device_tier.get(input_uuid) != 'primary':
            device_tier[input_uuid] = tier

        mtype   = s.get('measurement_type') or None
        meas_id = s.get('measurement_id')   or None
        if mtype == 'rain' and input_uuid not in rain_bound:
            rain_bound.append(input_uuid)
        probe: Optional[dict] = {} if with_status else None
        # probe·frozen 은 필요한 호출만 넘긴다(읽기 함수를 갈아 끼운 테스트 호환).
        _probe_kw = {'probe': probe} if probe is not None else {}
        if frozen is not None:
            _probe_kw['frozen'] = frozen
        vals = _read_one_sensor(input_uuid, mtype,
                                _max_age_for(max_age, *_fresh(fresh, input_uuid)),
                                measurement_id=meas_id, **_probe_kw)
        for rk, st in (probe or {}).items():
            ax = _ss.OUTDOOR_FACILITY_KEY_AXIS.get(rk)
            if ax:
                axis_statuses[ax].append(st)

        for k in _KEYS:
            if vals.get(k) is not None:
                raw.append((k, tier, input_uuid, vals[k]))

    # 출처 — 값을 낸 장치(와 강우 스캔 후보)만 묻는다. 판정은 `utils.inputs` 하나다.
    # **모르면 실측**(빈 집합) — 실측 쪽이 강우 게이트에서 엄격하다.
    _ask = sorted({r[2] for r in raw} | set(outdoor_device_ids))
    try:
        from aot.utils.inputs import model_origin_device_ids
        model_devs = set(model_origin_device_ids(_ask)) if _ask else set()
    except Exception:                                       # noqa: BLE001
        model_devs = set()

    def _origin(dev):
        return 'model' if dev in model_devs else 'measured'

    groups: Dict[str, Dict[Tuple[str, str], List[Tuple[str, float]]]] = {
        k: {g: [] for g in _ORDER} for k in _KEYS}
    for k, tier, dev, v in raw:
        groups[k][(tier, _origin(dev))].append((dev, v))

    buckets: Dict[str, List[float]] = {k: [] for k in _KEYS}
    backup_keys: List[str] = []
    chosen: Dict[str, Optional[Tuple[str, str]]] = {k: None for k in _KEYS}

    def _take(keys, g):
        for k in keys:
            buckets[k] = [v for _d, v in groups[k][g]]
            chosen[k] = g
            if g[0] == 'backup' and buckets[k]:
                backup_keys.append(k)

    def _first(k, order=_ORDER):
        return next((g for g in order if groups[k][g]), None)

    # 온도·습도 짝 — 짝이 온전한 첫 묶음.
    _pair = ('T', 'RH')
    _g = next((g for g in _ORDER if all(groups[k][g] for k in _pair)), None)
    if _g is not None:
        _take(_pair, _g)
    else:
        # 어느 묶음도 짝이 온전하지 않다 — 종류별로 있는 것을 쓴다.
        for k in _pair:
            g = _first(k)
            if g is not None:
                _take((k,), g)
    for k in _KEYS:
        if k in _pair:
            continue
        g = _first(k, _RAIN_ORDER if k == 'rain_mm' else _ORDER)
        if g is not None:
            _take((k,), g)
    if chosen['rain_mm'] is not None:
        rain_from = [d for d, _v in groups['rain_mm'][chosen['rain_mm']]]

    # ── 규칙 A — 끊긴 실측의 "비 옴" 을 예보가 덮지 않는다 ─────────────────────
    # 실측 강우계가 끊기면(위에서 값 없음) 예보 모델이 강우를 넘겨받는다. 그런데 끊기기 직전
    # 실측이 비를 보고 있었다면, 게이트는 그 마지막 값으로 닫힌 채 있어야 한다(오래된 "비 옴"
    # 은 닫는 근거 — `safety_gates._weather_view`). 예보 값을 내면 게이트가 그것을 이번 값으로
    # 받아 실측 래치를 지우고 모델의 단계 제한으로 **풀어 버린다.** 그래서 이때는 강우를 비워
    # 둔다(= 잃음) — 실측이 돌아오거나 마지막 실측이 0 이었으면 예보가 그대로 넘겨받는다.
    rain_held = False
    if rain_seen is not None:
        if chosen['rain_mm'] is not None and chosen['rain_mm'][1] == 'measured':
            rain_seen['measured_mm'] = max(buckets['rain_mm'])
            rain_seen['devices'] = list(rain_from)
        elif (float(rain_seen.get('measured_mm') or 0.0) > 0.0
              and set(rain_seen.get('devices') or ()) & set(rain_bound)):
            rain_held = True
            buckets['rain_mm'] = []
            rain_from = []
            chosen['rain_mm'] = None
            if 'rain_mm' in backup_keys:
                backup_keys.remove('rain_mm')

    # 명시적 rain 피팅이 없어도 outdoor 장치 채널을 자동 스캔해서 rain 감지
    # 변환 후 단위가 mm인 채널, 또는 measurement 이름이 _MEAS_RAIN_NAMES에 속하는 채널을 찾는다
    # 실측 장치를 먼저, 그 안에서 메인 장치를 먼저 본다 — 위 강우 순서(`_RAIN_ORDER`)와 같다.
    outdoor_device_ids.sort(key=lambda d: (d in model_devs, device_tier.get(d) == 'backup'))
    if not buckets['rain_mm'] and outdoor_device_ids and not rain_held:
        from aot.databases.models.measurement import DeviceMeasurements
        from aot.utils.database import db_retrieve_table_daemon
        from aot.utils.influx import get_last_measurement
        try:
            dm_rows = db_retrieve_table_daemon(DeviceMeasurements).filter(
                DeviceMeasurements.device_id.in_(outdoor_device_ids)
            ).all()
            _rank = {d: i for i, d in enumerate(outdoor_device_ids)}
            dm_rows = sorted(dm_rows, key=lambda r: _rank.get(r.device_id, len(_rank)))
            for dm in dm_rows:
                # ⚠ 같은 깨진 호출이 여기에도 있었다(위 `_read_one_sensor`
                #   의 주석 참조) — 두 곳 다 TypeError 를 삼키고 있었으므로
                #   **이름이 원시 그대로인 강수 채널은 어느 경로로도 안
                #   잡혔다.** 한 곳만 고치면 나머지 하나가 그대로 남는다.
                if _is_rain_channel(dm):
                    try:
                        ts, val = get_last_measurement(
                            dm.device_id, dm.unique_id,
                            max_age=_max_age_for(max_age, *_fresh(fresh, dm.device_id)))
                        if ts is not None and val is not None:
                            # 자동 스캔도 같은 범위 검사를 거친다 — 불가능한 값이면
                            # 이 채널은 건너뛰고 다음 후보를 본다.
                            _rs, _rv = _ss.check_value('rain', _normalise_rain(val, dm))
                            if _rs == _ss.OUT_OF_RANGE:
                                axis_statuses['rain'].append(_ss.OUT_OF_RANGE)
                                continue
                            buckets['rain_mm'].append(_rv)
                            rain_from.append(dm.device_id)
                            axis_statuses['rain'].append(_ss.VALID)
                            if device_tier.get(dm.device_id) == 'backup':
                                backup_keys.append('rain_mm')
                            if rain_seen is not None and dm.device_id not in model_devs:
                                rain_seen['measured_mm'] = float(_rv)
                                rain_seen['devices'] = [dm.device_id]
                            break
                    except Exception:
                        pass
        except Exception:
            pass

    def _avg(lst: List[float], ndigits: int) -> Optional[float]:
        return round(sum(lst) / len(lst), ndigits) if lst else None

    T_ext     = _avg(buckets['T'],        2)
    RH_ext    = _avg(buckets['RH'],       1)
    CO2_ext   = _avg(buckets['CO2'],      0)
    wind_ms   = _avg(buckets['wind_ms'],  2)
    wind_deg  = _avg(buckets['wind_deg'], 1)
    # 돌풍은 평균하지 않는다 — 여러 센서면 **가장 센 값**(강풍 게이트는 보수적인 쪽이 옳다).
    wind_gust_ms = (round(max(buckets['wind_gust_ms']), 2)
                    if buckets['wind_gust_ms'] else None)
    solar_wm2 = _avg(buckets['light'],    1)
    # 강우는 평균이 아니라 최댓값이다(위 '실측과 예보 모델도 섞지 않는다').
    rain_mm   = round(max(buckets['rain_mm']), 2) if buckets['rain_mm'] else None

    valid = sum(1 for v in (T_ext, RH_ext, CO2_ext, wind_ms, wind_deg, solar_wm2, rain_mm) if v is not None)
    out = {
        'T_ext':       T_ext,
        'RH_ext':      RH_ext,
        'CO2_ext':     CO2_ext,
        'wind_ms':     wind_ms,
        'wind_deg':    wind_deg,
        'wind_gust_ms': wind_gust_ms,   # 잰 돌풍(m/s) — 채널이 없으면 None(추정하지 않는다)
        'solar_wm2':   solar_wm2,
        'rain_mm':     rain_mm,
        'valid_count': valid,
        'total_count': total,
        # 메인이 끊겨 백업에서 온 값의 종류 — 비어 있으면 전부 메인(또는 없음).
        'backup_keys': backup_keys,
        # 강우 값의 출처 — 'model'(예보·재분석 모델) | 'measured' | None(강우 없음).
        'rain_origin': (_rain_origin(rain_from) if rain_mm is not None else None),
        # 끊긴 실측 강우계의 마지막 "비 옴" 을 지키느라 예보 강우를 내지 않았다(규칙 A).
        'rain_held':   rain_held,
    }
    if with_status:
        out['status'] = {a: _ss.summarize(axis_statuses[a]) for a in _ss.OUTDOOR_AXES}
    return out


# ─────────────────────────────────────────────────────────────────────────────
# 기상/예보 바인딩 읽기
# ─────────────────────────────────────────────────────────────────────────────

# measurement_type → result key 매핑
_FORECAST_MTYPE_KEY: Dict[str, str] = {
    'forecast_temperature':        'T',
    'forecast_humidity':           'RH',
    'forecast_wind_speed':         'wind',
    'forecast_precipitation_prob': 'pop',   # % 0-100
    'forecast_precipitation':      'rain',  # mm
    'forecast_solar':              'solar', # W/m²
}

KNOWN_FORECAST_TYPES = set(_FORECAST_MTYPE_KEY.keys())


def read_forecast_sensors(
    weather_bindings: List[dict],
    max_age: int = 7200,  # 예보는 2시간 이내 조회 기본값
) -> dict:
    """weather_bindings 목록에서 기상/예보 Input 장치 값을 읽는다.

    어떤 예보 서비스(OpenWeatherMap, Open-Meteo, KMA, AccuWeather ...)든
    해당 서비스의 Input 플러그인이 InfluxDB 에 값을 기록하면 이 함수로 읽힌다.
    measurement_type 이 동일한 항목이 여러 개면 단순 평균.

    Args
    ----
    weather_bindings : facility.weather_bindings 배열.
        각 항목: {measurement_type, input_uuid, measurement_id, name}
    max_age : 측정값 최대 허용 수명(초). 예보 업데이트 주기보다 넉넉하게 설정.

    Returns
    -------
    {
        'T'    : float | None,   # forecast temperature (°C)
        'RH'   : float | None,   # forecast humidity (%)
        'wind' : float | None,   # forecast wind speed (m/s)
        'pop'  : float | None,   # precipitation probability (%)
        'rain' : float | None,   # precipitation amount (mm)
        'solar': float | None,   # solar irradiance (W/m²)
        'valid_count': int,
        'total_count': int,
    }
    """
    from aot.utils.influx import get_last_measurement

    buckets: Dict[str, List[float]] = {k: [] for k in _FORECAST_MTYPE_KEY.values()}
    total = 0
    valid = 0

    for wb in (weather_bindings or []):
        mtype   = (wb.get('measurement_type') or '').strip()
        iid     = (wb.get('input_uuid') or '').strip()
        meas_id = (wb.get('measurement_id') or '').strip()
        if not mtype or not iid or not meas_id:
            continue
        rkey = _FORECAST_MTYPE_KEY.get(mtype)
        if not rkey:
            logger.debug('[ForecastSensors] 알 수 없는 measurement_type 무시: %s', mtype)
            continue

        total += 1
        # P2-1: 항목별 max_age_sec 설정 지원.
        # weather_bindings 항목에 max_age_sec 키가 있으면 해당 소스 전용 유효 수명 사용.
        # 없으면 함수 인수 max_age(= 시설 기본값 또는 caller 지정값) 적용.
        item_max_age = wb.get('max_age_sec')
        effective_max_age = int(item_max_age) if item_max_age is not None else max_age
        try:
            ts, val = get_last_measurement(iid, meas_id, max_age=effective_max_age)
            if ts is not None and val is not None:
                buckets[rkey].append(float(val))
                valid += 1
        except Exception as exc:
            logger.debug('[ForecastSensors] %s 조회 실패: %s', mtype, exc)

    def _avg(lst: List[float]) -> Optional[float]:
        return round(sum(lst) / len(lst), 2) if lst else None

    return {
        'T':           _avg(buckets['T']),
        'RH':          _avg(buckets['RH']),
        'wind':        _avg(buckets['wind']),
        'pop':         _avg(buckets['pop']),
        'rain':        _avg(buckets['rain']),
        'solar':       _avg(buckets['solar']),
        'valid_count': valid,
        'total_count': total,
    }


HOURLY_FORECAST_DRIVER = 'OPEN_METEO_HOURLY_FORECAST'

# 바인딩 입력 id 묶음 → 드라이버 조회 결과. 코디네이터가 사이클마다(피드포워드·MPC)
# 부르므로 DB 조회를 5분에 한 번으로 줄인다.
_DRIVER_CACHE: Dict[tuple, tuple] = {}
_DRIVER_CACHE_TTL = 300.0


def _bound_input_drivers(uuids: tuple) -> Dict[str, str]:
    import time as _time
    now = _time.time()
    hit = _DRIVER_CACHE.get(uuids)
    if hit is not None and now - hit[0] < _DRIVER_CACHE_TTL:
        return hit[1]
    from aot.utils.inputs import input_devices_by_ids
    rows = input_devices_by_ids(list(uuids))
    if rows is None:            # 조회 실패 — 기억하지 않는다(다음 사이클에 다시)
        return {}
    drivers = {uid: dev for uid, dev in rows}
    _DRIVER_CACHE[uuids] = (now, drivers)
    return drivers


# @manual ai/env-control#settings-forecast
def forecast_file_for(weather_bindings: List[dict], sole: bool = False) -> Optional[str]:
    """시설 예보 바인딩 → 묶인 Open-Meteo 시간별 예보 입력의 시간열 파일 경로. 없으면 None.

    바인딩 중 드라이버가 `OPEN_METEO_HOURLY_FORECAST` 인 입력(바인딩 순서상 첫 번째)의
    `DATABASE_PATH/openmeteo/forecast_<uuid>.json` — 경로는 드라이버의
    `forecast_file_path` 로 만든다(uuid 형식 검사 포함). 파일이 있는지·신선한지는 보지
    않는다(`forecast_feedforward.load_fresh_facility_forecast` 가 본다).

    `sole=True` 면 **묶인 예보 입력이 그 입력 하나뿐일 때만** 경로를 낸다 — 다른 예보
    입력(기상청·OpenWeather 등)이 섞인 시설은 피드포워드를 기존 바인딩 단일값 경로로
    둔다(환경제어 E1).
    """
    order: List[str] = []
    for wb in (weather_bindings or []):
        iid = str((wb or {}).get('input_uuid') or '').strip()
        if iid and iid not in order:
            order.append(iid)
    if not order:
        return None
    try:
        drivers = _bound_input_drivers(tuple(sorted(order)))
    except Exception:                                       # noqa: BLE001
        logger.debug('[ForecastFile] 입력 드라이버 조회 실패', exc_info=True)
        return None
    hourly = [iid for iid in order if drivers.get(iid) == HOURLY_FORECAST_DRIVER]
    if not hourly:
        return None
    if sole and len(order) != 1:
        return None
    try:
        from aot.inputs.open_meteo_hourly_forecast import forecast_file_path
        return forecast_file_path(hourly[0])
    except (ValueError, ImportError):
        logger.debug('[ForecastFile] 파일 경로를 만들 수 없음: %r', hourly[0], exc_info=True)
        return None


def fresh_forecast_file_for(weather_bindings: List[dict], sole: bool = False,
                            now_epoch: Optional[float] = None) -> Optional[str]:
    """`forecast_file_for` 중 파일이 신선(수신 2 h 이내)한 것만. 아니면 None."""
    path = forecast_file_for(weather_bindings, sole=sole)
    if not path:
        return None
    from aot.functions.utils.env_control.forecast_feedforward import (
        load_fresh_facility_forecast)
    return path if load_fresh_facility_forecast(path, now_epoch) is not None else None


def validate_sensor_binding(binding: dict) -> Tuple[bool, str]:
    """센서 바인딩 항목의 필수 필드와 role 유효성을 검사한다.

    Returns:
        (ok: bool, reason: str)
    """
    for field in ('role', 'device_id', 'measurement_id'):
        if not (binding.get(field) or '').strip():
            return False, f'missing field: {field}'

    role = binding['role'].strip()
    if role not in KNOWN_ROLES:
        return False, f'unknown role: {role} (valid: {sorted(KNOWN_ROLES)})'

    weight = binding.get('weight')
    if weight is not None:
        try:
            w = float(weight)
            if w <= 0:
                return False, f'weight must be > 0, got {w}'
        except (TypeError, ValueError):
            return False, f'weight must be numeric, got {weight!r}'

    return True, 'ok'


def validate_sensor_bindings(bindings: list) -> Tuple[bool, List[str]]:
    """sensor_bindings 배열 전체를 검증한다.

    Returns:
        (all_ok: bool, errors: list[str])
    """
    if not isinstance(bindings, list):
        return False, ['sensors must be a list']
    errors = []
    for i, b in enumerate(bindings):
        ok, reason = validate_sensor_binding(b)
        if not ok:
            errors.append(f'sensors[{i}]: {reason}')
    return len(errors) == 0, errors


# @manual geo/facility-widget#b-environment, geo/facility-widget#data-refresh
def build_sensor_snapshot(
    sensors_resolved: List[dict],
    sensors_outdoor: List[dict],
    max_age: Optional[int] = None,
    ext_fallback: bool = True,
) -> dict:
    """시설 런타임 응답의 센서 부분을 만든다 (indoor/outdoor/sensors/fitting_sensors).

    /api/aot/facility/<uuid>/runtime 의 라이브 경로와, env_coordinator 사이클이
    매 주기 미리 계산해 FunctionRuntimeState.runtime_json 에 저장하는 precompute
    경로가 공유한다 — 같은 형식을 보장한다.

    무거운 비용(센서당 InfluxDB 조회: compute_spatial_internal + read_fitting_sensors)
    이 여기에 모여 있다. 데몬 사이클이 이 함수를 호출해 결과를 저장해두면, 웹 요청은
    InfluxDB 를 건드리지 않고 그 스냅샷을 읽기만 하면 된다 (저사양 호스트에서
    스레드 풀 포화 방지).

    ext_fallback: 실외 미설정 항목을 ext_context_collector 공유 컨텍스트로 보충.
    """
    indoor  = {'temp_c': None, 'humidity_pct': None, 'co2_ppm': None, 'vpd_kpa': None,
               'vpd_air_kpa': None}
    outdoor = {'temp_c': None, 'humidity_pct': None, 'wind_ms': None,
               'wind_deg': None, 'solar_wm2': None}
    valid_count = 0
    total_count = 0
    degraded = False

    if sensors_resolved:
        try:
            spatial = compute_spatial_internal(sensors_resolved, max_age=max_age)
            indoor['temp_c']       = spatial.get('T')
            indoor['humidity_pct'] = spatial.get('RH')
            # CO₂ 도 같은 공간 평균에서 이미 계산돼 있다 — 채우지 않아서 시설
            # 위젯의 CO₂ 칸이 늘 '— ppm' 이었다.
            indoor['co2_ppm']      = spatial.get('CO2')
            indoor['vpd_kpa']      = spatial.get('VPD')
            # 공기 VPD — 온·습도 평균에서 계산(`VPD_calc`). 화면의 [공기 VPD] 칸과 목표 비교는
            # 이것을 쓴다. `vpd_kpa` 는 종전 뜻(장치 VPD 가 있으면 그것)을 그대로 둔다 — 장치
            # VPD 는 엽온 어림(기온 − 1.5 °C) 기준일 수 있다. 잎 VPD·목표 기준은 코디네이터가
            # 자기 스냅숏에 더 싣는다(`_annotate_snapshot_vpd_basis`).
            indoor['vpd_air_kpa']  = spatial.get('VPD_calc')
            valid_count = spatial.get('valid_count', 0)
            total_count = len(sensors_resolved)
            degraded    = valid_count < total_count
        except Exception:
            pass

    if sensors_outdoor:
        try:
            od = read_outdoor_sensors(sensors_outdoor, max_age=max_age)
            if od.get('T_ext')     is not None: outdoor['temp_c']       = od['T_ext']
            if od.get('RH_ext')    is not None: outdoor['humidity_pct'] = od['RH_ext']
            if od.get('wind_ms')   is not None: outdoor['wind_ms']      = od['wind_ms']
            if od.get('wind_deg')  is not None: outdoor['wind_deg']     = od['wind_deg']
            if od.get('solar_wm2') is not None: outdoor['solar_wm2']    = od['solar_wm2']
        except Exception:
            pass

    if ext_fallback:
        try:
            import time as _time
            from aot.functions.ext_context_collector import (
                get_shared_context, get_shared_context_ts)
            ext = get_shared_context() or {}
            ext_age = _time.time() - get_shared_context_ts()
            if ext and ext_age < 600:
                _ext_map = {
                    'temp_c':       ext.get('T_ext'),
                    'humidity_pct': ext.get('RH_ext'),
                    'wind_ms':      ext.get('wind'),
                    'wind_deg':     ext.get('wind_dir'),
                    'solar_wm2':    ext.get('solar'),
                }
                for key, val in _ext_map.items():
                    if outdoor.get(key) is None and val is not None:
                        outdoor[key] = val
        except Exception:
            pass

    fitting_sensors: List[dict] = []
    try:
        combined = list(sensors_resolved) + list(sensors_outdoor)
        if combined:
            fitting_sensors = read_fitting_sensors(combined, max_age=max_age)
    except Exception:
        fitting_sensors = []

    return {
        'indoor':  indoor,
        'outdoor': outdoor,
        'sensors': {
            'detail':      [],
            'valid_count': valid_count,
            'total_count': total_count,
            'degraded':    degraded,
        },
        'fitting_sensors': fitting_sensors,
    }
