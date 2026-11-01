# coding=utf-8
"""
forecast_feedforward.py — 기상 예보 기반 선행 제어 신호 생성 (P3-4).

forecast.json (KMA 단기예보) → FeedforwardSignal 도출. 시설에 Open-Meteo 시간별 예보
입력(`OPEN_METEO_HOURLY_FORECAST`)이 묶여 있으면 그 입력이 쓴 같은 모양의 시간열 파일
(`forecast_<uuid>.json`)도 같은 함수로 읽는다(`load_fresh_facility_forecast`).
EnvCoordinator는 이 신호를 L1 목표 편향(bias)으로 적용해
기상 변화가 실제로 도달하기 전에 사전 대응한다.

편향 규칙:
  - 고온 예보(T_fcst > T_int + threshold): 냉방 선행 → T_target -= T_bias_cool
  - 저온 예보(T_fcst < T_int - threshold): 난방 선행 → T_target += T_bias_heat
  - 강우 예보(POP >= 50%): 환기 감소 신호(wind_open_inhibit)
  - 강풍 예보(WSD > wind_threshold): 환기 감소 신호
  - 고습 예보(REH > 85%): 제습 선행 → RH_target -= RH_bias_dehumid

참조: docs/env_control_enhancement_design.md §3.12 (P3-4)
"""
# @manual ai/env-control#settings-forecast

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)

# 예보 파일 캐시 — **경로별** {경로: (읽은 시각, 내용)}. 예전에는 하나뿐이라 두 번째
# 파일(시설 Open-Meteo 예보)이 첫 파일(forecast.json) 캐시를 돌려받았다.
_FORECAST_CACHE: dict = {}
_FORECAST_CACHE_TTL: float = 900.0   # 15분 캐시

# 시설 시간열 파일(Open-Meteo `forecast_<uuid>.json`)은 수신(`fetched_epoch`) 뒤 이 시간이
# 지나면 쓰지 않는다(환경제어 E3). 입력 주기 1800 s 기준 세 번 연속 실패한 셈이다.
FACILITY_FILE_MAX_AGE_S: float = 7200.0

# 시설 시간열 파일 경로에서 강수확률로 환기를 억제하려면 창 안 시간당 강수 최대가
# 이 값 이상이어야 한다(환경제어 E2). 강수 값이 없으면 확률만으로 억제하지 않는다.
FACILITY_RAIN_MM_H_MIN: float = 0.5


@dataclass
class FeedforwardSignal:
    """예보 기반 선행 제어 신호."""
    T_bias:          float = 0.0    # °C: 양수 → 목표 상향, 음수 → 목표 하향
    RH_bias:         float = 0.0    # %: 양수 → 목표 상향, 음수 → 목표 하향
    wind_inhibit:    bool  = False  # True → 환기 제한 (강우·강풍 예보)
    rain_expected:   bool  = False  # True → 강우 예보
    wind_expected:   float = 0.0    # m/s: 예보 최대 풍속
    reason:          str   = ''     # 사람이 읽는 이유 문자열
    lookahead_h:     float = 3.0    # 참조한 예보 시간 지평 (hours)
    valid:           bool  = False  # 예보 데이터가 유효한지


# ─────────────────────────────────────────────────────────────────────────────
# 예보 파일 로드 (캐시 포함)
# ─────────────────────────────────────────────────────────────────────────────

def _clear_cache() -> None:
    """테스트·강제 갱신용 캐시 초기화."""
    global _FORECAST_CACHE
    _FORECAST_CACHE = {}


def _default_forecast_path() -> Optional[str]:
    try:
        from aot.config import PATH_JSON
        return os.path.join(PATH_JSON, 'forecast.json')
    except ImportError:
        return None


def _load_forecast(forecast_path: Optional[str] = None) -> dict:
    """예보 파일을 로드한다 (경로별 15분 캐시). 경로가 없으면 `forecast.json`."""
    if forecast_path is None:
        forecast_path = _default_forecast_path()
        if forecast_path is None:
            return {}

    now = time.time()
    hit = _FORECAST_CACHE.get(forecast_path)
    if hit is not None and now - hit[0] < _FORECAST_CACHE_TTL and hit[1]:
        return hit[1]

    try:
        with open(forecast_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        _FORECAST_CACHE[forecast_path] = (now, data)
        return data
    except Exception as exc:
        logger.debug('forecast_feedforward: 파일 로드 실패 — %s', exc)
        return {}


def load_fresh_facility_forecast(forecast_path: Optional[str],
                                 now_epoch: Optional[float] = None) -> Optional[dict]:
    """시설 시간열 파일(Open-Meteo) → 내용, 쓸 수 없으면 None.

    `fetched_epoch`(수신 시각)가 없거나 `FACILITY_FILE_MAX_AGE_S`(2 h)보다 낡았으면 None
    — 소비처는 그때 기존 경로(바인딩 단일값·forecast.json)로 간다. 수신 시각이 지금보다
    10분 넘게 앞서면(시계 이상) 역시 쓰지 않는다.
    """
    if not forecast_path:
        return None
    data = _load_forecast(forecast_path)
    if not data or not data.get('forecasts'):
        return None
    try:
        fetched = float(data.get('fetched_epoch'))
    except (TypeError, ValueError):
        return None
    now = time.time() if now_epoch is None else float(now_epoch)
    age = now - fetched
    if age > FACILITY_FILE_MAX_AGE_S or age < -600.0:
        return None
    return data


def forecast_epoch(stamp, tz=None) -> Optional[float]:
    """예보 파일의 'YYYYmmddHHMM' 벽시계 + 시간대 이름 → epoch. 시간대가 없으면
    기상청(KST). 읽을 수 없으면 None."""
    if not stamp:
        return None
    try:
        import pytz
        from datetime import datetime
        naive = datetime.strptime(str(stamp), '%Y%m%d%H%M')
        zone = pytz.timezone(str(tz) if tz else 'Asia/Seoul')
        return zone.localize(naive).timestamp()
    except Exception:
        return None


def forecast_rows_ahead(data: dict, hours: float,
                        now_epoch: Optional[float] = None) -> list:
    """지금부터 `hours` 시간 안의 예보 → [(몇 시간 뒤, 항목)], 이른 순.

    ⚠ 파일의 오프셋 키는 **파일을 쓴 시각(`now`, 벽시계 `tz`) 기준**이다 — 지금 기준이
      아니다(2026-09-22 수정). 예전에는 오프셋을 그대로 "몇 시간 뒤" 로 읽어서, 파일이
      늦게 갱신되면 이미 지난 시간대를 앞으로 올 예보로 봤다. 발표 215일 지난 파일도
      "0~3시간 뒤" 가 채워져 있으니 판정이 계속 돌았다.

    지금 시각이 든 한 시간 칸(몇 시간 뒤가 −1 보다 큰 것)은 포함한다 — 매시 정각 값이
    그 시간을 대표한다. 기준 시각(`now`)이 없는 파일은 언제 것인지 모르므로 빈 목록이다.
    """
    fc = (data or {}).get('forecasts') or {}
    anchor = forecast_epoch((data or {}).get('now'), (data or {}).get('tz'))
    if not fc or anchor is None:
        return []
    now = time.time() if now_epoch is None else float(now_epoch)
    out = []
    for key, row in fc.items():
        try:
            off = int(key)
        except (TypeError, ValueError):
            continue
        if not row or not isinstance(row, dict):
            continue
        ahead = (anchor + off * 3600.0 - now) / 3600.0
        if -1.0 < ahead <= float(hours):
            out.append((ahead, row))
    out.sort(key=lambda r: r[0])
    return out


def _extract_window(data: dict, lookahead_h: float,
                    now_epoch: Optional[float] = None) -> list[dict]:
    """지금 ~ lookahead_h 시간 안의 예보 항목 리스트(`forecast_rows_ahead`)."""
    return [row for _ahead, row in forecast_rows_ahead(data, lookahead_h, now_epoch)]


# ─────────────────────────────────────────────────────────────────────────────
# 핵심 신호 도출
# ─────────────────────────────────────────────────────────────────────────────

def build_feedforward_signal(
    T_int: float,
    RH_int: float,
    lookahead_h: float = 3.0,
    T_bias_cool: float = 1.5,
    T_bias_heat: float = 1.0,
    RH_bias_dehumid: float = 5.0,
    T_delta_threshold: float = 3.0,
    wind_threshold: float = 8.0,
    rain_pop_threshold: int = 50,
    forecast_path: Optional[str] = None,
    now_epoch: Optional[float] = None,
    rain_mm_h_min: Optional[float] = None,
) -> FeedforwardSignal:
    """
    현재 내부 T/RH와 예보를 비교해 FeedforwardSignal을 반환한다.

    Parameters
    ----------
    T_int             : 현재 내부 온도 (°C)
    RH_int            : 현재 내부 습도 (%)
    lookahead_h       : 예보 조회 시간 지평 (hours, 기본 3h)
    T_bias_cool       : 고온 예보 시 적용할 목표 하향 편향 (°C)
    T_bias_heat       : 저온 예보 시 적용할 목표 상향 편향 (°C)
    RH_bias_dehumid   : 고습 예보 시 적용할 목표 하향 편향 (%)
    T_delta_threshold : 내부 온도와 예보 온도의 차이 임계값 (°C)
    wind_threshold    : 강풍 판단 임계값 (m/s)
    rain_pop_threshold: 강우 확률 임계값 (%)
    forecast_path     : forecast.json 경로 (None → 자동)
    rain_mm_h_min     : None 이면 강수확률만으로 환기 억제(기상청 forecast.json, 예전 그대로).
                        값이 있으면 **강수확률 ≥ 임계 그리고 창 안 시간당 강수(RN1) 최대
                        ≥ 이 값** 일 때만 억제한다. 강수 값이 없으면 확률만으로 억제하지
                        않는다 — 모름이 환기를 막으면 고온에 위험하다(시설 Open-Meteo 파일, E2).
    """
    sig = FeedforwardSignal(lookahead_h=lookahead_h)

    data = _load_forecast(forecast_path)
    if not data:
        return sig

    forecasts = data.get('forecasts', {})
    if not forecasts:
        return sig

    window = _extract_window(data, lookahead_h, now_epoch)
    if not window:
        return sig

    sig.valid = True
    reasons = []

    # 창 내 최고·최저 온도, 최대 습도, 최대 풍속, 최대 강우확률
    tmp_vals = [w.get('TMP') for w in window if w.get('TMP') is not None]
    reh_vals = [w.get('REH') for w in window if w.get('REH') is not None]
    wsd_vals = [w.get('WSD') for w in window if w.get('WSD') is not None]
    pop_vals = [w.get('POP') for w in window if w.get('POP') is not None]
    pty_vals = [w.get('PTY') for w in window if w.get('PTY') is not None]

    _safe = lambda lst, fn: fn(lst) if lst else None

    T_max  = _safe([v for v in tmp_vals if isinstance(v, (int, float))], max)
    T_min  = _safe([v for v in tmp_vals if isinstance(v, (int, float))], min)
    RH_max = _safe([v for v in reh_vals if isinstance(v, (int, float))], max)
    WSD_max= _safe([v for v in wsd_vals if isinstance(v, (int, float))], max)
    POP_max= _safe([v for v in pop_vals if isinstance(v, (int, float))], max)
    RN1_max= _safe([w.get('RN1') for w in window
                    if isinstance(w.get('RN1'), (int, float))], max)

    # ── 온도 편향 ─────────────────────────────────────────────────────────
    if T_max is not None and T_max > T_int + T_delta_threshold:
        sig.T_bias = -T_bias_cool
        reasons.append(f'고온 예보({T_max:.1f}°C) → 냉방 선행 -{T_bias_cool}°C')

    elif T_min is not None and T_min < T_int - T_delta_threshold:
        sig.T_bias = T_bias_heat
        reasons.append(f'저온 예보({T_min:.1f}°C) → 난방 선행 +{T_bias_heat}°C')

    # ── 습도 편향 ─────────────────────────────────────────────────────────
    if RH_max is not None and RH_max > 85.0:
        sig.RH_bias = -RH_bias_dehumid
        reasons.append(f'고습 예보({RH_max:.0f}%) → 제습 선행 -{RH_bias_dehumid}%')

    # ── 환기 제한 ─────────────────────────────────────────────────────────
    rain_flag = False
    pop_hit = POP_max is not None and POP_max >= rain_pop_threshold
    if pop_hit and rain_mm_h_min is not None:
        pop_hit = RN1_max is not None and RN1_max >= rain_mm_h_min
    if pop_hit:
        rain_flag = True
        sig.rain_expected = True
        if rain_mm_h_min is None:
            reasons.append(f'강우 확률 {POP_max:.0f}%')
        else:
            reasons.append(f'강우 확률 {POP_max:.0f}% · 시간당 강수 최대 {RN1_max:.1f} mm/h')

    # PTY ≠ '없음' / '강수없음'도 강우로 간주
    for pty in pty_vals:
        if isinstance(pty, str) and pty not in ('없음', '강수없음', '0', ''):
            rain_flag = True
            sig.rain_expected = True
            break

    wind_flag = False
    if WSD_max is not None and WSD_max > wind_threshold:
        wind_flag = True
        sig.wind_expected = WSD_max
        reasons.append(f'강풍 예보({WSD_max:.1f} m/s)')

    if rain_flag or wind_flag:
        sig.wind_inhibit = True

    sig.reason = '; '.join(reasons) if reasons else '정상 범위'
    return sig


# ─────────────────────────────────────────────────────────────────────────────
# facility weather_bindings 기반 신호 도출 (서비스 무관 범용 경로)
# ─────────────────────────────────────────────────────────────────────────────

def build_feedforward_signal_from_forecast(
    forecast: dict,
    T_int: float,
    RH_int: float,
    T_bias_cool: float = 1.5,
    T_bias_heat: float = 1.0,
    RH_bias_dehumid: float = 5.0,
    T_delta_threshold: float = 3.0,
    wind_threshold: float = 8.0,
    rain_pop_threshold: float = 50.0,
) -> FeedforwardSignal:
    """facility.weather_bindings 에서 읽은 예보 dict 로 FeedforwardSignal 을 생성한다.

    KMA/OpenWeatherMap/Open-Meteo 등 어떤 서비스든 read_forecast_sensors() 를
    통해 동일한 포맷으로 들어온다:
        {T, RH, wind, pop, rain, solar, valid_count, total_count}

    Parameters
    ----------
    forecast : read_forecast_sensors() 반환값.
    T_int    : 현재 내부 온도 (°C).
    RH_int   : 현재 내부 습도 (%).
    """
    sig = FeedforwardSignal(lookahead_h=0.0)  # 이미 서비스가 시간 지평을 적용한 값

    if not forecast or forecast.get('valid_count', 0) == 0:
        return sig

    sig.valid = True
    reasons: list = []

    T_fcst    = forecast.get('T')
    RH_fcst   = forecast.get('RH')
    wind_fcst = forecast.get('wind')
    pop_fcst  = forecast.get('pop')

    # ── 온도 편향 ─────────────────────────────────────────────────────────────
    if T_fcst is not None:
        if T_fcst > T_int + T_delta_threshold:
            sig.T_bias = -T_bias_cool
            reasons.append(f'고온 예보({T_fcst:.1f}°C) → 냉방 선행 -{T_bias_cool}°C')
        elif T_fcst < T_int - T_delta_threshold:
            sig.T_bias = T_bias_heat
            reasons.append(f'저온 예보({T_fcst:.1f}°C) → 난방 선행 +{T_bias_heat}°C')

    # ── 습도 편향 ─────────────────────────────────────────────────────────────
    if RH_fcst is not None and RH_fcst > 85.0:
        sig.RH_bias = -RH_bias_dehumid
        reasons.append(f'고습 예보({RH_fcst:.0f}%) → 제습 선행 -{RH_bias_dehumid}%')

    # ── 환기 제한 ─────────────────────────────────────────────────────────────
    rain_flag = (pop_fcst is not None and pop_fcst >= rain_pop_threshold)
    if rain_flag:
        sig.rain_expected = True
        reasons.append(f'강우 확률 {pop_fcst:.0f}%')

    wind_flag = (wind_fcst is not None and wind_fcst > wind_threshold)
    if wind_flag:
        sig.wind_expected = wind_fcst
        reasons.append(f'강풍 예보({wind_fcst:.1f} m/s)')

    if rain_flag or wind_flag:
        sig.wind_inhibit = True

    sig.reason = '; '.join(reasons) if reasons else '정상 범위'
    return sig


# ─────────────────────────────────────────────────────────────────────────────
# 목표에 편향 적용
# ─────────────────────────────────────────────────────────────────────────────

def apply_feedforward(
    env_target: dict,
    signal: FeedforwardSignal,
    T_g_min: float = 12.0,
    T_g_max: float = 32.0,
    RH_g_min: float = 40.0,
    RH_g_max: float = 85.0,
) -> None:
    """FeedforwardSignal을 env_target에 인-플레이스 적용한다.

    guide 범위를 벗어나는 편향은 클램프된다.
    """
    if not signal.valid:
        return

    tv_T = env_target.get('temperature')
    if tv_T is not None and signal.T_bias != 0.0:
        new_val = max(T_g_min, min(T_g_max, tv_T.value + signal.T_bias))
        tv_T.value = new_val

    tv_RH = env_target.get('humidity')
    if tv_RH is not None and signal.RH_bias != 0.0:
        new_val = max(RH_g_min, min(RH_g_max, tv_RH.value + signal.RH_bias))
        tv_RH.value = new_val
