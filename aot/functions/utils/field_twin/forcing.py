# coding=utf-8
"""
field_twin/forcing.py — 일 격자 외생 입력(비·ET0·기온) 만들기.

어느 출처(기상청 관측소·예보·현장 우량계·POWER)를 쓸지는 **부르는 쪽이 정한다**.
여기는 받은 계열을 일 격자로 묶고, 빈 날을 표시할 뿐 출처를 고르지 않는다.

ET0 는 FAO-56 Penman-Monteith(`aot.inputs.nasa_power.reference_et0`)를 쓰는 것이
기본이고, 일사가 빠진 날(POWER 는 최근 며칠 일사가 늦게 채워진다)에는 기온만으로 되는
Hargreaves-Samani(FAO-56 식 52)로 메운다. 어느 식을 썼는지 날마다 남긴다.
"""
from __future__ import annotations

import math
from typing import Dict, Iterable, Optional, Tuple

import numpy as np


def _ra(lat_deg: float, doy: int) -> float:
    """대기외 일사 Ra [MJ/m²/day] — FAO-56 식 21."""
    phi = math.radians(lat_deg)
    dr = 1 + 0.033 * math.cos(2 * math.pi * doy / 365.0)
    decl = 0.409 * math.sin(2 * math.pi * doy / 365.0 - 1.39)
    ws = math.acos(max(-1.0, min(1.0, -math.tan(phi) * math.tan(decl))))
    return ((24 * 60 / math.pi) * 0.0820 * dr *
            (ws * math.sin(phi) * math.sin(decl) + math.cos(phi) * math.cos(decl) * math.sin(ws)))


def hargreaves_et0(t_min: float, t_max: float, lat_deg: float, doy: int) -> float:
    """기온만으로 ET0 [mm/day] — FAO-56 식 52. Penman-Monteith 를 못 쓸 때의 대체."""
    t_mean = 0.5 * (t_min + t_max)
    return max(0.0023 * (t_mean + 17.8) * math.sqrt(max(t_max - t_min, 0.0))
               * 0.408 * _ra(lat_deg, doy), 0.0)


def offset_at(t: float, tz) -> float:
    """순간 `t` 에서 현지 시계가 UTC 보다 앞선 초. `tz` 는 IANA 이름(점마다 그 시각의 오프셋 — 서머타임을 넘어도
    하루가 밀리지 않는다) 또는 고정 오프셋 초(시험·합성 데이터). 정하지 않으면(None) 오류다 — 예전 기본값 +9h 는
    다른 시간대의 장소를 조용히 한국 날짜로 접었다."""
    if tz is None:
        raise ValueError('tz 가 필요하다 (IANA 이름 또는 오프셋 초)')
    if isinstance(tz, str):
        from aot.utils.timekit import to_tz
        return to_tz(float(t), tz).utcoffset().total_seconds()
    return float(tz)


def daily_sum(points: Iterable[Tuple[float, float]], tz_offset_s=None,
              scale: float = 1.0) -> Dict[int, Tuple[float, int]]:
    """(epoch, 값) 시간 계열 → 현지 날짜(에포크 일) → (합×scale, 시간 수).

    시간 수가 24 보다 적은 날은 그만큼 비가 빠졌을 수 있다 — 부르는 쪽이 판단한다.
    """
    acc: Dict[int, list] = {}
    for t, v in points:
        if v is None or not np.isfinite(v):
            continue
        d = int(math.floor((t + offset_at(t, tz_offset_s)) / 86400.0))
        acc.setdefault(d, []).append(v)
    return {d: (float(np.sum(a)) * scale, len(a)) for d, a in acc.items()}


def day_number(year: int, month: int, day: int) -> int:
    """달력 날짜 → 에포크 일 번호(현지 날짜 기준 키와 같은 축)."""
    import datetime as _dt
    return (_dt.date(year, month, day) - _dt.date(1970, 1, 1)).days


def date_of(day: int):
    import datetime as _dt
    return _dt.date(1970, 1, 1) + _dt.timedelta(days=int(day))


def et0_daily(power_daily: Dict[str, Dict[str, float]], lat_deg: float, elevation_m: float = 10.0,
              pm=None, fallback_temps: Optional[Dict[int, Tuple[float, float]]] = None
              ) -> Dict[int, Tuple[float, str]]:
    """POWER 일 자료 {파라미터: {'YYYYMMDD': 값}} → 에포크 일 → (ET0 mm, 'pm'|'hs'|'hs_alt').

    pm: Penman-Monteith 함수(기본 `aot.inputs.nasa_power.reference_et0`). 일사가 없으면
    Hargreaves. POWER 기온도 없으면 fallback_temps{일: (최저, 최고)}(예: 관측소 기온)로
    Hargreaves('hs_alt'), 그것도 없으면 그 날은 뺀다.
    """
    if pm is None:
        from aot.inputs.nasa_power import reference_et0 as pm

    def g(name, key):
        v = power_daily.get(name, {}).get(key)
        return None if v is None or v <= -900 else float(v)

    out: Dict[int, Tuple[float, str]] = {}
    for key in power_daily.get('T2M_MAX', {}):
        y, m, d = int(key[:4]), int(key[4:6]), int(key[6:8])
        dn = day_number(y, m, d)
        doy = date_of(dn).timetuple().tm_yday
        tx, tn, tm = g('T2M_MAX', key), g('T2M_MIN', key), g('T2M', key)
        rh, ws, rs = g('RH2M', key), g('WS2M', key), g('ALLSKY_SFC_SW_DWN', key)
        if tx is None or tn is None:
            alt = (fallback_temps or {}).get(dn)
            if alt is not None:
                out[dn] = (hargreaves_et0(alt[0], alt[1], lat_deg, doy), 'hs_alt')
            continue
        if None not in (tm, rh, ws, rs):
            out[dn] = (max(pm(tm, tx, tn, rh, ws, rs, lat_deg, elevation_m, doy), 0.0), 'pm')
        else:
            out[dn] = (hargreaves_et0(tn, tx, lat_deg, doy), 'hs')
    for dn, (tn, tx) in (fallback_temps or {}).items():
        if dn not in out:
            doy = date_of(dn).timetuple().tm_yday
            out[dn] = (hargreaves_et0(tn, tx, lat_deg, doy), 'hs_alt')
    return out
