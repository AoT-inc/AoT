# coding=utf-8
"""
env_control/sensor_status.py — 센서 판독의 상태 분류 (순수 함수, I/O 없음).

지금까지 제어는 "값이 있다/없다" 만 알았다. 만료된 값과 아예 안 온 값이 둘 다
`None` 이 되어 사후에 구분이 안 됐고, 공간 MAD 이상치는 개수만 셌으며, 물리적으로
불가능한 값(습도 130 %)은 그대로 평균에 섞여 제어까지 흘렀다. 이 모듈이 그 판독을
여섯 상태 중 하나로 분류한다.

    valid         쓸 수 있다
    stale         값은 있으나 신선도 상한(`measurement_freshness`)을 넘었다
    missing       값이 없다(채널 없음·데이터 없음·조회 실패)
    outlier       공간 MAD 이상치로 평균에서 빠졌다 (`facility_sensors`)
    out_of_range  물리적으로 불가능하다 — **제어에 들어가지 않는다**
    frozen        시각은 새것인데 값이 오래 한 점에 붙어 있다 — **제어에 들어가지 않는다**

## 행동이 달라지는 것은 둘이다

`stale`/`missing`/`outlier` 는 **기록만** 한다(제어는 종전 그대로). `out_of_range`
와 `frozen` 은 그 센서의 값이 평균·제어로 가지 않고 `missing` 처럼 취급된다 — 축
전체가 비면 기존 "측정 없음" 경로(근거 21, 제자리 유지)가 맡는다. 근거: 습도 130 %
나 온도 150 °C 는 센서 고장이 확실해서 평균에 섞을 이유가 없다(다른 센서가 있으면
그 평균이 오염되고, 없으면 지어낸 값으로 장치가 움직인다). 멈춘 센서도 같다 —
시각이 새것이라 만료 판정(`stale`)에 안 걸리고, 값이 그럴듯해서 범위 검사에도 안
걸리지만, 실제 온실이 46 °C 일 때 30.7 °C 를 믿으면 창을 닫는다(폐루프 시뮬레이터
`sensor_indoor_frozen` 에서 확인).

## 멈춤(frozen) 판정 — `FrozenTracker`

(장치, 채널)마다 **같은 값이 얼마나 오래 이어졌는가** 를 센다. 값이 해상도(`FROZEN_RESOLUTION`)
이내로만 움직였고, 그동안 **서로 다른 시각의 표본이 `FROZEN_MIN_SAMPLES` 개 이상** 왔고,
진짜 센서라면 반드시 움직였을 시간(`FROZEN_WINDOW_S` — 낮 60분·밤 장치 이동 120분·조용한 밤
3시간·CO2 2시간, 정수 눈금 T·RH 는 3배)이 찼을 때 멈춘 것이다. 한 번이라도 해상도
밖으로 움직이면 즉시 풀린다. 상태는 메모리에만 둔다(재시작하면 처음부터 센다 — 보수적인 쪽).

⚠ **표본 수를 함께 보는 이유**: 40분마다 깨는 노드나 시간당 한 번 갱신하는 기상 API 는 같은
표본을 사이클마다 다시 읽는다. 시각이 같은 값을 "값이 그대로" 로 세면 정상 장치가 멈춘 것으로
보인다. 새 표본이 없는 시간은 `stale` 이 맡는다.

⚠ **변화시에만 보고하는 장치(report-on-change)는 구별할 수 없다.** 이 코드베이스에는 입력
장치가 그런 방식인지 알려 주는 메타데이터가 없다(`Input.period` 는 폴링 주기일 뿐이다). 값이 안
변하면 점을 안 쓰는 장치는 시각이 멈춰 `stale` 로 읽히므로 이 판정에 닿지 않지만, **변화가
없어도 주기마다 점을 쓰는 장치가 정말 3시간 동안 한 값에 머무는 경우**(포화한 습도 100 % 는
따로 뺀다)는 오탐이 될 수 있다. 오탐의 대가는 그 센서 하나가 평균에서 빠지는 것이다.

## 상수는 이 파일 한 곳에 둔다

범위·허용 오차를 호출부에 흩으면 갈라진다(이 도메인이 데인 실패 — 읽는 경로마다
기준이 다름). 판정 함수도 여기 하나다.
"""

from __future__ import annotations

import math
import time
from typing import Dict, Iterable, List, Optional, Tuple

# ─────────────────────────────────────────────────────────────────────────────
# 상태
# ─────────────────────────────────────────────────────────────────────────────
VALID        = 'valid'
STALE        = 'stale'
MISSING      = 'missing'
OUTLIER      = 'outlier'
OUT_OF_RANGE = 'out_of_range'
FROZEN       = 'frozen'

# 좋은 순서 — 축의 상태는 이 순서에서 가장 앞선 것이다("쓸 수 있는 것 중 최선").
# stale 이 outlier 보다 앞인 이유: 낡은 값은 한때 맞았지만, 이상치는 같은 시각
# 이웃 센서들이 틀렸다고 말한 값이다. out_of_range 는 살아 있으나 고장이고,
# missing 은 정보가 아예 없다. frozen 은 한때 맞았을 수 있으나(멈추기 전) 지금은
# 아무것도 말해 주지 않는다 — out_of_range 보다 앞이다(범위 검사는 통과했다).
STATUS_ORDER: Tuple[str, ...] = (VALID, STALE, OUTLIER, FROZEN, OUT_OF_RANGE, MISSING)

# 로그 채널에 싣는 정수 코드 — 순서를 바꾸지 말 것(과거 기록과 이어지지 않는다).
STATUS_CODES: Dict[str, int] = {
    VALID: 0, STALE: 1, MISSING: 2, OUTLIER: 3, OUT_OF_RANGE: 4, FROZEN: 5,
}

# ─────────────────────────────────────────────────────────────────────────────
# 축 — 상태를 매기는 단위
# ─────────────────────────────────────────────────────────────────────────────
INDOOR_AXES: Tuple[str, ...]  = ('T', 'RH', 'CO2', 'VPD', 'light')
OUTDOOR_AXES: Tuple[str, ...] = ('T_ext', 'RH_ext', 'wind', 'rain', 'solar')
ALL_AXES: Tuple[str, ...]     = INDOOR_AXES + OUTDOOR_AXES

# 축 → 물리량 종류(범위표의 키)
AXIS_KIND: Dict[str, str] = {
    'T': 'T', 'RH': 'RH', 'CO2': 'CO2', 'VPD': 'VPD', 'light': 'light',
    'T_ext': 'T', 'RH_ext': 'RH', 'wind': 'wind', 'rain': 'rain', 'solar': 'light',
}

# `facility_sensors` 의 결과 키 → 물리량 종류 (풍향·기압·RSSI 등은 범위를 두지 않는다)
FACILITY_KEY_KIND: Dict[str, str] = {
    'T': 'T', 'RH': 'RH', 'CO2': 'CO2', 'VPD': 'VPD', 'light': 'light',
    'wind_ms': 'wind', 'rain_mm': 'rain',
    'wind_gust_ms': 'wind',   # 돌풍 — 풍속과 같은 물리 범위(축은 따로 두지 않는다)
}
# `read_outdoor_sensors` 결과 키 → 실외 축
OUTDOOR_FACILITY_KEY_AXIS: Dict[str, str] = {
    'T': 'T_ext', 'RH': 'RH_ext', 'wind_ms': 'wind', 'rain_mm': 'rain', 'light': 'solar',
}
# 실외 컨텍스트(`external` dict) 키 → 실외 축 (공유 컨텍스트 경로의 검사용)
EXTERNAL_KEY_AXIS: Dict[str, str] = {
    'T_ext': 'T_ext', 'RH_ext': 'RH_ext', 'wind': 'wind', 'rain': 'rain', 'solar': 'solar',
}

# ─────────────────────────────────────────────────────────────────────────────
# 물리 범위 — (하한, 상한). None 은 그쪽을 검사하지 않는다.
# ─────────────────────────────────────────────────────────────────────────────
PHYSICAL_RANGE: Dict[str, Tuple[Optional[float], Optional[float]]] = {
    'T':     (-40.0, 70.0),     # °C — 온실 안팎 어디서도 이 밖은 센서 고장이다
    'RH':    (0.0, 100.0),      # %
    'CO2':   (150.0, 10000.0),  # ppm — 대기 400, 대기 아래로 150 미만은 불가능
    'VPD':   (0.0, 10.0),       # kPa — 음수 불가, 70 °C 에서도 10 을 넘기기 어렵다
    # 일사: 상한은 두지 않는다. 광량 채널은 lux·PPFD 를 W/m² 로 환산해 싣는데
    # (`_normalise_light`), 환산 계수가 틀린 장치를 여기서 잘라내면 원인이
    # 가려진다. 음수만 막는다.
    'light': (0.0, None),       # W/m²
    'wind':  (0.0, 100.0),      # m/s — 지표 관측 최대가 113
    'rain':  (0.0, None),       # mm 또는 mm/h
}

# 센서 과대 표시 허용 — 이 안의 초과는 **고장이 아니라 눈금 오차**라 상한으로
# 잘라서 valid 로 쓴다 (RH 101 % 는 흔하다. 130 % 는 고장이다).
RH_OVERSHOOT_MAX = 102.0        # %

# 일사계는 밤에 열 오프셋으로 -1 ~ -5 W/m² 를 내는 것이 정상이다. 이 안의 음수는
# 0 으로 올려 valid 로 쓴다 — 그보다 낮아야 고장이다.
LIGHT_NEGATIVE_TOLERANCE = 5.0  # W/m²


def check_value(kind: str, value) -> Tuple[str, Optional[float]]:
    """한 판독의 범위 검사. `(valid|out_of_range, 쓸 값)`.

    - 숫자가 아니거나 NaN/inf 면 out_of_range.
    - RH 는 100 초과 `RH_OVERSHOOT_MAX` 이하를 100 으로 자르고 valid.
    - 일사는 0 미만 `LIGHT_NEGATIVE_TOLERANCE` 이내를 0 으로 올리고 valid.
    - 범위를 두지 않은 종류는 그대로 valid.

    out_of_range 의 쓸 값은 None 이다 — 호출부가 그 값을 실수로 쓸 수 없게.
    """
    try:
        v = float(value)
    except (TypeError, ValueError):
        return OUT_OF_RANGE, None
    if not math.isfinite(v):
        return OUT_OF_RANGE, None
    bounds = PHYSICAL_RANGE.get(kind)
    if bounds is None:
        return VALID, v
    lo, hi = bounds
    if kind == 'RH' and hi is not None and hi < v <= RH_OVERSHOOT_MAX:
        return VALID, hi
    if kind == 'light' and lo is not None and lo - LIGHT_NEGATIVE_TOLERANCE <= v < lo:
        return VALID, lo
    if lo is not None and v < lo:
        return OUT_OF_RANGE, None
    if hi is not None and v > hi:
        return OUT_OF_RANGE, None
    return VALID, v


def best_status(statuses: Iterable[str]) -> str:
    """여러 센서의 상태 중 가장 좋은 것. 비어 있으면 missing."""
    present = set(statuses)
    for s in STATUS_ORDER:
        if s in present:
            return s
    return MISSING


def summarize(statuses: Iterable[str]) -> dict:
    """한 축을 먹이는 센서들의 상태를 요약한다.

    `{'status': 최선, 'counts': {상태: 수}, 'n': 센서 수}` — 센서가 하나도 없으면
    `n=0` 으로 missing 이다("센서가 안 달렸다" 와 "센서가 값을 안 준다" 는 n 으로 가른다).
    """
    lst: List[str] = list(statuses)
    counts: Dict[str, int] = {}
    for s in lst:
        counts[s] = counts.get(s, 0) + 1
    return {'status': best_status(lst), 'counts': counts, 'n': len(lst)}


def merge(a: Optional[dict], b: Optional[dict]) -> dict:
    """같은 축을 먹이는 두 출처의 요약을 합친다(센서 + 공유 컨텍스트 등).

    상태는 둘 중 좋은 쪽, 개수는 더한다. 한쪽이 None 이면 다른 쪽.
    """
    if not a:
        return dict(b) if b else summarize([])
    if not b:
        return dict(a)
    counts = dict(a.get('counts') or {})
    for k, n in (b.get('counts') or {}).items():
        counts[k] = counts.get(k, 0) + n
    return {'status': best_status([a.get('status'), b.get('status')]),
            'counts': counts, 'n': int(a.get('n', 0)) + int(b.get('n', 0))}


def from_value(present: bool) -> dict:
    """센서 목록 없이 값의 유무만 아는 축(공유 컨텍스트 등)의 요약."""
    return {'status': VALID if present else MISSING,
            'counts': {VALID: 1} if present else {}, 'n': 1 if present else 0}


def strip_out_of_range(values: dict, key_axis: Dict[str, str]) -> Dict[str, dict]:
    """`values`(제자리 수정)에서 범위 밖 항목을 **키째 뺀다**, 범위 안 초과는 자른다.

    `key_axis` 에 있는 키만 본다. 값이 None 이면 건드리지 않는다. 반환은
    `{축: summarize(...)}` — 검사한 축만 들어 있고, 키를 뺀 축은 out_of_range 다.
    """
    out: Dict[str, dict] = {}
    for key, axis in key_axis.items():
        if key not in values or values[key] is None:
            continue
        status, v = check_value(AXIS_KIND[axis], values[key])
        if status == OUT_OF_RANGE:
            del values[key]
            out[axis] = summarize([OUT_OF_RANGE])
        else:
            values[key] = v
            out[axis] = summarize([VALID])
    return out


def encode(summary: Optional[dict]) -> int:
    """축 요약 → 로그 채널 정수 코드. 요약이 없으면 missing."""
    return STATUS_CODES.get((summary or {}).get('status', MISSING),
                            STATUS_CODES[MISSING])


def indoor_summary(result: dict, axes: dict, via: dict, vpd_source: str) -> dict:
    """실내 다섯 축의 상태.

    `axes` 는 센서 경로의 요약(`compute_spatial_internal`)이다. 요약이 없는 축(센서
    미연결)이나 역할 폴백(`via`)으로 값을 댄 축은 `result` 에 값이 있는지로 정한다.
    VPD 축은 **제어가 쓰는 VPD** 의 상태다 — 계산이면 T/RH 가 있는 한 valid 이고,
    장치 채널의 상태는 `device` 에 따로 둔다.
    """
    out: Dict[str, dict] = {}
    for axis in INDOOR_AXES:
        if axis == 'VPD':
            continue
        summ = axes.get(axis)
        if axis in via or summ is None:
            summ = from_value(result.get(axis) is not None)
            if axis in via:
                summ = dict(summ, via=via[axis])
        out[axis] = summ
    dev = axes.get('VPD') or summarize([])
    if vpd_source == VPD_COMPUTED:
        vpd = {'status': VALID, 'counts': dict(dev.get('counts') or {}),
               'n': dev.get('n', 0)}
    elif vpd_source == VPD_DEVICE:
        vpd = dict(dev)
    else:
        vpd = dict(dev, status=dev.get('status') if dev.get('n') else MISSING)
    vpd['source'] = vpd_source
    vpd['device'] = dev.get('status', MISSING)
    out['VPD'] = vpd
    return out


def outdoor_summary(external: dict, od_cache: dict, shared_status: dict) -> dict:
    """실외 다섯 축의 상태. 시설 실외 센서 요약과 공유 컨텍스트를 합친다.

    시설 센서가 요약을 못 준 축(센서 미연결)은 `external` 에 값이 있는지로 정한다.
    센서가 stale 인데 공유 컨텍스트가 값을 주면 축은 valid 다 — 제어가 실제로 쓰는
    값이 있기 때문이다("가장 좋은 쪽").
    """
    sensor = (od_cache or {}).get('status') or {}
    key_for = {a: k for k, a in EXTERNAL_KEY_AXIS.items()}
    out: Dict[str, dict] = {}
    for axis in OUTDOOR_AXES:
        from_sensor = sensor.get(axis)
        from_shared = (shared_status or {}).get(axis)
        if from_shared is None and from_sensor is None:
            from_shared = from_value(external.get(key_for[axis]) is not None)
        out[axis] = merge(from_sensor, from_shared)
    return out


def snapshot(coordinator) -> dict:
    """이번 사이클의 센서 상태 — 실내·실외 열 개 축과 VPD 출처.

    `{'axes': {축: {status, counts, n, …}}, 'vpd_source': computed|device|none,
      'vpd_device_diff': 장치 VPD - 제어 VPD or None}`. 코디네이터가 수집 중에
    남긴 속성(`_indoor_status`·`_outdoor_status`·`_vpd_source`·`_vpd_device_diff`)을
    읽는다. 아직 수집 전이면 빈 축이다(전부 missing 으로 읽힌다).
    """
    axes: Dict[str, dict] = {}
    for attr in ('_indoor_status', '_outdoor_status'):
        part = getattr(coordinator, attr, None)
        if isinstance(part, dict):
            axes.update(part)
    source = getattr(coordinator, '_vpd_source', VPD_NONE)
    diff = getattr(coordinator, '_vpd_device_diff', None)
    return {
        'axes': axes,
        'vpd_source': source if source in VPD_SOURCE_CODES else VPD_NONE,
        'vpd_device_diff': diff if isinstance(diff, (int, float)) else None,
    }


# ─────────────────────────────────────────────────────────────────────────────
# 멈춘 센서 (frozen)
# ─────────────────────────────────────────────────────────────────────────────
# 상수는 여기 한 곳이다. 창은 "진짜 센서라면 **반드시** 움직였을 시간" 이다 — 짧게
# 잡을수록 빨리 잡지만 안정한 밤의 정상 센서를 멈춘 것으로 오인한다.

# 검사하는 물리량. 실내 T·RH·CO2 와 실외 T·RH 가 쓴다(실외 CO2 는 축이 없다).
# 풍속·강우·일사는 정상 값이 오래 한 점(0)에 머무는 것이 보통이라 검사하지 않는다.
#
# ⚠ **VPD 는 따로 재지 않고 같은 장치의 T·RH 가 멈추면 함께 뺀다**(`device_frozen`). VPD 채널을
#   그냥 두면 멈춘 장치의 VPD 가 T·RH 가 빠진 자리를 장치 VPD 폴백(`vpd_source=device`)으로 메워
#   **멈춘 값이 그대로 제어에 들어간다**(폐루프 `sensor_indoor_frozen` 에서 확인). 그렇다고
#   VPD 를 독립으로 재면 안 된다 — 포화 근처(밤)의 VPD 는 0.07 kPa 안팎에서 몇 시간 안 움직여
#   실측 3일치에서 정상 센서가 멈춘 것으로 잡혔다. T·RH 에서 나온 값이라 그 둘이 판정 근거다.
FROZEN_KINDS: Tuple[str, ...] = ('T', 'RH', 'CO2')

# 해상도 — 이 이내로만 움직이면 "그대로" 다. 센서 눈금(0.1 °C·0.1 %·1 ppm)의 반 정도.
FROZEN_RESOLUTION: Dict[str, float] = {'T': 0.05, 'RH': 0.1, 'CO2': 1.0}

# 창(초) — 센서가 놓인 상황 3단계. 같은 값이 이만큼 이어지면 센서가 멈춘 것이다.
#   day    낮(일사 > FROZEN_ACTIVE_SOLAR_WM2) — 온도·습도가 분 단위로 움직인다
#   moved  밤이지만 최근 장치가 움직였다 — 움직였다고 반드시 값이 변하는 것은 아니다
#   quiet  조용한 밤 — 온실이 정말로 한 점에 머물 수 있다
# 근거는 실측(김제·영양 3일치, 온도 0.1 °C 눈금): 한 값이 이어진 최장 시간은 낮 12분,
# 밤 1.0시간(온도). 그래서 밤의 '장치 이동' 은 낮과 같은 60분이 아니라 120분이다 — 60분은
# 실측 최장 1.0시간과 같아 오탐 여지가 있다. CO2 는 하나다.
LEVEL_DAY, LEVEL_MOVED, LEVEL_QUIET = 'day', 'moved', 'quiet'
FROZEN_WINDOW_S: Dict[str, Dict[str, float]] = {
    'T':   {LEVEL_DAY: 3600.0, LEVEL_MOVED: 7200.0, LEVEL_QUIET: 10800.0},
    'RH':  {LEVEL_DAY: 3600.0, LEVEL_MOVED: 7200.0, LEVEL_QUIET: 10800.0},
    'CO2': {LEVEL_DAY: 7200.0, LEVEL_MOVED: 7200.0, LEVEL_QUIET: 7200.0},
}

# 눈금이 정수뿐인 센서(습도를 1 % 로 내는 장치가 흔하다)는 창을 이 배수로 늘린다. 실측: 영양·김제
# 실내외 습도는 전부 정수 눈금이고, 밤에 같은 정수가 최장 4.5시간 이어졌다(3시간 창이면 70시간
# 동안 정상 센서가 45번 멈춘 것으로 잡혔다). 눈금이 거칠면 '움직이지 않았다' 의 증거가 약하다.
# 한 번이라도 소수 값을 낸 센서는 정밀 센서다. T·RH 에만 적용한다(CO2 의 1 ppm 은 원래 눈금).
FROZEN_COARSE_FACTOR = 3.0
FROZEN_COARSE_KINDS: Tuple[str, ...] = ('T', 'RH')

# 서로 다른 시각의 표본이 이만큼은 와야 한다 — 40분 주기 노드·시간당 갱신 API 가 같은
# 표본을 되읽는 것을 "멈춤" 으로 세지 않는다. 그런 장치는 이 판정에 거의 닿지 않는다.
FROZEN_MIN_SAMPLES = 6

# 관측이 이만큼 끊겼다가 돌아오면 처음부터 센다(코디네이터가 꺼져 있던 동안의 변화를
# 모른다). 이미 멈춘 것으로 판정된 센서는 같은 값이면 그대로 멈춘 채다.
FROZEN_MAX_GAP_S = 3600.0

FROZEN_ACTIVE_SOLAR_WM2 = 100.0   # 이보다 밝으면 낮
FROZEN_ACTIVE_MOVE_S    = 1800.0  # 장치가 이 안에 움직였으면 moved

# 포화한 습도는 정상이다 — 안개·결로 밤에 100 % 에 몇 시간이고 붙어 있다.
FROZEN_RH_SATURATION = 99.5       # %


class FrozenTracker:
    """(장치, 채널)마다 값이 얼마나 오래 같았는지 센다 — 순수 상태, I/O 없음.

    사이클 시작에 `begin(now, level)` 로 시각과 상황 단계(day/moved/quiet)를 알리고, 읽을
    때마다 `observe(...)` 를 부른다(True = 멈춘 센서, 값을 쓰지 않는다).

    창은 **비율로 쌓는다**: 관측 간격 dt 를 그 순간의 창으로 나눠 더하고 합이 1 이 되면
    멈춘 것이다. 단계가 바뀌는 구간에서도 "얼마나 오래" 가 일관되게 센다(낮 30분 + 밤
    90분 = 0.5 + 0.5).

    영속화하지 않는다 — 재시작하면 처음부터 센다(멈춤을 늦게 잡을 뿐이다).
    """

    def __init__(self) -> None:
        self.now: Optional[float] = None
        self.level: str = LEVEL_QUIET
        self._fine: Dict[tuple, bool] = {}     # 소수 값을 낸 적 있는 센서(정밀) — 눈금 판별
        # key → {anchor, load, n, last_ts, last_obs, since}
        self._state: Dict[tuple, dict] = {}
        self._frozen: Dict[tuple, str] = {}
        self._events: List[dict] = []

    def begin(self, now: Optional[float], level=LEVEL_QUIET) -> None:
        """사이클의 시각과 단계. `level` 은 'day'|'moved'|'quiet' (True=day, False=quiet 도 받는다)."""
        self.now = float(now) if now is not None else time.time()
        if level is True:
            level = LEVEL_DAY
        elif level is False or level not in (LEVEL_DAY, LEVEL_MOVED, LEVEL_QUIET):
            level = LEVEL_QUIET
        self.level = level

    @property
    def frozen_keys(self) -> Dict[tuple, str]:
        return dict(self._frozen)

    def device_frozen(self, device_id) -> bool:
        """이 장치의 T 또는 RH 채널이 멈춘 상태인가 — 그 장치의 VPD 채널을 함께 뺄 근거."""
        return any(k[0] == device_id and kind in ('T', 'RH')
                   for k, kind in self._frozen.items())

    def drain_events(self) -> List[dict]:
        """상태가 바뀐 것만 — `{'event': 'frozen'|'recovered', 'key', 'kind', 'value', 'minutes'}`."""
        ev, self._events = self._events, []
        return ev

    def _start(self, key, value, ts, now) -> None:
        self._state[key] = {'anchor': value, 'load': 0.0, 'n': 1, 'last_ts': ts,
                            'last_obs': now, 'since': now}

    def observe(self, key: tuple, kind: str, value, ts) -> bool:
        """한 판독을 보고 멈춘 센서인지 돌려준다. 검사 대상이 아닌 물리량은 False."""
        res = FROZEN_RESOLUTION.get(kind)
        if res is None:
            return False
        try:
            v = float(value)
        except (TypeError, ValueError):
            return False
        if not math.isfinite(v):
            return False
        now = self.now if self.now is not None else time.time()
        if abs(v - round(v)) > 1e-6:
            self._fine[key] = True
        st = self._state.get(key)
        saturated = kind == 'RH' and v >= FROZEN_RH_SATURATION
        if saturated or st is None or abs(v - st['anchor']) > res:
            if key in self._frozen:
                self._recover(key, kind, v, now, st)
            if saturated:
                self._state.pop(key, None)
            else:
                self._start(key, v, ts, now)
            return False
        dt = now - st['last_obs']
        st['last_obs'] = now
        if key in self._frozen:
            return True
        if dt < 0 or dt > FROZEN_MAX_GAP_S:
            self._start(key, v, ts, now)
            return False
        window = FROZEN_WINDOW_S[kind][self.level]
        if kind in FROZEN_COARSE_KINDS and not self._fine.get(key):
            window *= FROZEN_COARSE_FACTOR
        st['load'] += dt / window
        if ts != st['last_ts']:
            st['n'] += 1
            st['last_ts'] = ts
        if st['n'] >= FROZEN_MIN_SAMPLES and st['load'] >= 1.0 - 1e-9:   # 부동소수 누적 오차
            self._frozen[key] = kind
            self._events.append({'event': 'frozen', 'key': key, 'kind': kind,
                                 'value': st['anchor'],
                                 'minutes': (now - st['since']) / 60.0})
            return True
        return False

    def _recover(self, key, kind, value, now, st) -> None:
        self._frozen.pop(key, None)
        self._events.append({'event': 'recovered', 'key': key, 'kind': kind,
                             'value': value,
                             'minutes': ((now - st['since']) / 60.0) if st else 0.0})


def tracker_of(coordinator) -> FrozenTracker:
    """코디네이터의 `FrozenTracker` — 없으면 만들어 단다(지연 생성).

    `isinstance` 로 확인한다: 속성이 있어도 다른 것(테스트의 MagicMock)이면 새로 만든다.
    """
    tr = getattr(coordinator, '_frozen_tracker', None)
    if not isinstance(tr, FrozenTracker):
        tr = FrozenTracker()
        try:
            coordinator._frozen_tracker = tr
        except Exception:                                        # noqa: BLE001
            pass
    return tr


def frozen_activity(coordinator, now: float, solar: Optional[float] = None) -> str:
    """멈춘 센서 판정의 단계 — 'day'(낮) · 'moved'(최근 장치가 움직였다) · 'quiet'.

    `solar`(W/m²)가 없으면 마지막 유효 실외값 캐시의 일사를 본다. 둘 다 모르면 낮이 아니라고
    본다(긴 창 = 보수적). 장치 이동은 `_dispatch_moved`({장치: 마지막 이동 시각})다.
    """
    if solar is None:
        try:
            solar = (getattr(coordinator._ext_cache, 'values', None) or {}).get('solar')
        except Exception:                                        # noqa: BLE001
            solar = None
    try:
        if solar is not None and float(solar) > FROZEN_ACTIVE_SOLAR_WM2:
            return LEVEL_DAY
    except (TypeError, ValueError):
        pass
    moved = getattr(coordinator, '_dispatch_moved', None)
    if isinstance(moved, dict):
        for ts in moved.values():
            try:
                if now - float(ts) <= FROZEN_ACTIVE_MOVE_S:
                    return LEVEL_MOVED
            except (TypeError, ValueError):
                continue
    return LEVEL_QUIET


def begin_frozen_cycle(coordinator, now: Optional[float] = None,
                       solar: Optional[float] = None) -> FrozenTracker:
    """사이클의 첫 읽기 앞에서 호출 — 시각과 창 종류를 정하고 추적기를 돌려준다."""
    now = time.time() if now is None else now
    tr = tracker_of(coordinator)
    tr.begin(now, frozen_activity(coordinator, now, solar))
    return tr


def log_frozen_events(coordinator, logger) -> None:
    """멈춤/회복 전환을 **한 번씩** 남긴다.

    ⚠ error 레벨이다 — 기본 설치의 컨트롤러 로거는 ERROR 라 warning 은 어디에도 안 남는다
    (`_cycle_mixin` 의 실외 백업 전환 로그와 같은 이유).
    """
    tr = getattr(coordinator, '_frozen_tracker', None)
    if not isinstance(tr, FrozenTracker):
        return
    for ev in tr.drain_events():
        dev, meas = (tuple(ev['key']) + ('', ''))[:2]
        who = f'{str(dev)[:8]}/{str(meas)[:8]}'
        if ev['event'] == 'frozen':
            logger.error(
                '센서 값이 멈췄습니다: %s %s=%.2f — 시각은 새것인데 %.0f분째 같은 값입니다. '
                '이 센서는 평균과 제어에서 뺍니다 (값이 바뀌면 곧바로 돌아옵니다)',
                who, ev['kind'], ev['value'], ev['minutes'])
        else:
            logger.error('센서 값이 다시 움직입니다: %s %s=%.2f — 제어에 다시 씁니다',
                         who, ev['kind'], ev['value'])


# ── VPD 출처 ─────────────────────────────────────────────────────────────────
# 제어 VPD 가 어디서 왔는가. 센서가 준 VPD 는 엽온 기준(auto_vpd: 기온 - 1.5 °C)일
# 수 있어 공기 VPD 보다 0.1~0.45 kPa 낮다(10~35 °C, 바른 잎–공기 식 — 2026-10-09 전 식은
# 0.04~0.23) — 목표·분해는 공기 VPD 를 가정한다. 잎 기준 목표는 `leaf_vpd` 가 옮긴다.
VPD_COMPUTED = 'computed'   # 걸러진 실내 T/RH 로 psychro 계산 (기본)
VPD_DEVICE   = 'device'     # T 또는 RH 가 없을 때만 쓰는 장치 VPD
VPD_NONE     = 'none'
VPD_SOURCE_CODES: Dict[str, int] = {VPD_NONE: 0, VPD_COMPUTED: 1, VPD_DEVICE: 2}


def encode_vpd_source(source: Optional[str]) -> int:
    return VPD_SOURCE_CODES.get(source or VPD_NONE, 0)
