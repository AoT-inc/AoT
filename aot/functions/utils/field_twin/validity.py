# coding=utf-8
"""
field_twin/validity.py — 동화 전 센서 유효성 검사 (계약 §10.5).

채널 이름이 "토양수분"이어도 값이 물리 범위를 벗어나거나 평탄하면 관측으로 쓰지 않는다.
김제 `온습도_N`(공기 전용)에는 토양 채널 템플릿이 달려 "토양수분" ≈ 3.7 %(표준편차
0.02), "토양온도" ≈ −90~−107 °C 로 고정된 값이 쌓인다(계획서 §9.4.1) — 이름만 믿으면
이 값이 동화에 들어간다.

규칙
- 범위: 체적수분 0~70 %, 토양온도 −30~60 °C. 범위 밖 점은 그 점만 버린다.
- 평탄: 하루(현지 0~24 시) 안 유효 점의 표준편차 < 0.1 %p 면 그 날 전체를 버린다.
  점이 6개 미만인 날도 평탄을 판정할 수 없어 버린다.
"""
from __future__ import annotations

import math
from typing import Dict, Iterable, List, Sequence, Tuple

import numpy as np

VWC_RANGE_PCT: Tuple[float, float] = (0.0, 70.0)
SOIL_T_RANGE_C: Tuple[float, float] = (-30.0, 60.0)
FLAT_STD_PCT = 0.1
MIN_POINTS_PER_DAY = 6

REASON_OK = 'ok'
REASON_RANGE = 'range'
REASON_FLAT = 'flat'
REASON_SPARSE = 'sparse'
REASON_NAN = 'nan'


def _day_key(t: float, tz_offset_s: float) -> int:
    return int(math.floor((t + tz_offset_s) / 86400.0))


def screen_series(times: Sequence[float], values: Sequence[float],
                  value_range: Tuple[float, float] = VWC_RANGE_PCT,
                  flat_std: float = FLAT_STD_PCT, tz_offset_s: float = 9 * 3600,
                  min_points: int = MIN_POINTS_PER_DAY) -> Tuple[np.ndarray, List[str]]:
    """점마다 (유효 여부, 사유). 사유는 ok·range·flat·sparse·nan 중 하나."""
    t = np.asarray(times, dtype=float)
    v = np.asarray(values, dtype=float)
    reason = [REASON_OK] * len(v)
    ok = np.isfinite(v)
    for i in np.where(~ok)[0]:
        reason[i] = REASON_NAN
    lo, hi = value_range
    out = ok & ((v < lo) | (v > hi))
    for i in np.where(out)[0]:
        reason[i] = REASON_RANGE
    ok &= ~out
    days: Dict[int, List[int]] = {}
    for i in np.where(ok)[0]:
        days.setdefault(_day_key(t[i], tz_offset_s), []).append(i)
    for idx in days.values():
        vals = v[idx]
        bad = None
        if len(idx) < min_points:
            bad = REASON_SPARSE
        elif float(np.std(vals)) < flat_std:
            bad = REASON_FLAT
        if bad:
            for i in idx:
                ok[i] = False
                reason[i] = bad
    return ok, reason


def channel_verdict(times, values, value_range=VWC_RANGE_PCT, min_valid_frac=0.5,
                    **kw) -> Dict[str, object]:
    """채널 전체 판정: 유효 비율이 min_valid_frac 미만이면 이 채널은 관측으로 쓰지 않는다."""
    ok, reason = screen_series(times, values, value_range=value_range, **kw)
    n = len(ok)
    counts: Dict[str, int] = {}
    for r in reason:
        counts[r] = counts.get(r, 0) + 1
    frac = float(ok.mean()) if n else 0.0
    return {'usable': n > 0 and frac >= min_valid_frac, 'valid_frac': frac,
            'n': n, 'reasons': counts}


def daily_means(times: Iterable[float], values: Iterable[float], mask=None,
                tz_offset_s: float = 9 * 3600, min_points: int = 12) -> Dict[int, Tuple[float, int]]:
    """현지 날짜(에포크 일 번호) → (유효 점 평균, 점 수). 점이 min_points 미만인 날은 뺀다."""
    t = np.asarray(list(times), dtype=float)
    v = np.asarray(list(values), dtype=float)
    m = np.isfinite(v) if mask is None else (np.asarray(mask, dtype=bool) & np.isfinite(v))
    acc: Dict[int, List[float]] = {}
    for ti, vi in zip(t[m], v[m]):
        acc.setdefault(_day_key(ti, tz_offset_s), []).append(vi)
    return {d: (float(np.mean(a)), len(a)) for d, a in acc.items() if len(a) >= min_points}


def placement_changes(times, soil_t, tz_offset_s: float = 9 * 3600, ratio: float = 2.0,
                      min_range_c: float = 15.0, lookback_d: int = 7) -> List[int]:
    """토양온도 일교차가 갑자기 커진 날(에포크 일 번호) — 센서가 얕아졌거나 드러난 신호.

    흙 속 5~20 cm 의 일교차는 공기보다 훨씬 작다. 그날 일교차가 앞 lookback_d 일
    중앙값의 ratio 배를 넘고 min_range_c 이상이면 설치 위치가 바뀐 것으로 본다.
    김제 A 토양_3: 09-27 까지 6~10 °C → 09-28 부터 26~40 °C(같은 시각 토양_1 두절).
    """
    rng = {}
    for d, (vals) in _by_day(times, soil_t, tz_offset_s).items():
        if len(vals) >= 18:
            rng[d] = max(vals) - min(vals)
    days = sorted(rng)
    out = []
    for i, d in enumerate(days):
        prev = [rng[p] for p in days[max(0, i - lookback_d):i] if d - p <= lookback_d]
        if len(prev) >= 3 and rng[d] >= min_range_c and rng[d] > ratio * float(np.median(prev)):
            if not out or d - out[-1] > lookback_d:
                out.append(d)
    return out


def _by_day(times, values, tz_offset_s):
    acc: Dict[int, List[float]] = {}
    for t, v in zip(times, values):
        if v is None or not np.isfinite(v) or not (SOIL_T_RANGE_C[0] <= v <= SOIL_T_RANGE_C[1]):
            continue
        acc.setdefault(_day_key(t, tz_offset_s), []).append(float(v))
    return acc


def boundary_means(times: Iterable[float], values: Iterable[float], mask=None,
                   tz_offset_s: float = 9 * 3600, half_window_s: float = 7200.0,
                   min_points: int = 2) -> Dict[int, Tuple[float, int]]:
    """현지 날짜 d 의 00:00 앞뒤 half_window_s 안 유효 점 평균 → {d: (평균, 점 수)}.

    일 격자의 대상 시각은 그날 00:00 이다(계약 §10.3). 상태와 같은 시각의 관측을 쓰면
    하루 평균에 섞이는 비 전·후 시간과 정전용량 센서의 온도 일주기가 빠진다.
    """
    t = np.asarray(list(times), dtype=float)
    v = np.asarray(list(values), dtype=float)
    m = np.isfinite(v) if mask is None else (np.asarray(mask, dtype=bool) & np.isfinite(v))
    acc: Dict[int, List[float]] = {}
    for ti, vi in zip(t[m], v[m]):
        local = ti + tz_offset_s
        d = int(math.floor(local / 86400.0 + 0.5))      # 가장 가까운 자정
        if abs(local - d * 86400.0) <= half_window_s:
            acc.setdefault(d, []).append(vi)
    return {d: (float(np.mean(a)), len(a)) for d, a in acc.items() if len(a) >= min_points}
