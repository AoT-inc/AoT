# coding=utf-8
"""
env_control/sim/storm.py — 극한 기상 외기 시나리오(한국·일본 기후)의 시계열 생성기.

`scenarios.py` 의 합성 생성기(`synth`)는 하루 주기 코사인 하나로 온도·습도를 만든다. 태풍·스콜·
복사냉각 서리·안개 같은 **급변** 은 그 모양으로 못 만든다. 여기는 시나리오마다 **키프레임**(시간 [h],
값)으로 평균 경로를 적고, 거기에 씨앗 고정 난류(AR(1))를 얹는다. 같은 이름이면 언제나 같은 값이다
(난수는 `random.Random(sc.seed)` 하나만 쓴다).

## 격자와 채널

격자는 60 s 다(스콜 앞머리의 20 분 15 K 하강을 5 분 격자로는 못 담는다). 시설 모델은 이 격자를 선형
보간해 쓰고, 하네스가 제어기에 내는 실외 측정은 5 분 격자(KMA 주기)에서 **측정기답게** 가공한다:

  wind        시설이 겪는 풍속 = 평균 + 난류(60 s 표본). 제어기에는 10 분 평균(`wind_avg_s`)으로 나간다.
  gust        그 1 분 안의 돌풍 최댓값 — 지표용(제어기는 돌풍 채널이 없다).
  rain        mm/h 순간 강우율. 제어기에는 직전 15 분 누적(`rain_accum_s`, KMA `강수15분`)으로 나간다.
  visibility  km — 안개·호우에서 짧다.
  fc_rain …   예보 모델(Open-Meteo)이 같은 시각에 내놓는 값 — 현장 실측이 아니다. 시설 물리에는 안 쓴다.

## 일사

일사 = 맑은 하늘 전천일사(Haurwitz) × `tau`(하늘 투과율). `tau` 를 따로 두는 이유: `cloud_factor` 는
운량 1 에서도 0.25 라 태풍 호우(실제 0.03~0.1)나 짙은 안개(0.1)를 못 만든다. `cloud` 는 하늘 유효
온도(복사냉각)에만 쓰인다.

## 습도

RH 는 **이슬점**에서 만든다(Magnus). 기온이 15 K 떨어져도 공기 중 수증기는 그대로라는 사실이
스콜의 RH 를 정한다. 강우 중 RH 는 95 % 아래로 내려가지 않는다.
"""

from __future__ import annotations

import datetime as _dt
import math
import random
from typing import Callable, Dict, List, Sequence, Tuple

from aot.utils.timekit import to_tz, wall_to_utc
from .scenarios import DEFAULT_TZ, WeatherSeries, clear_sky_ghi, cloud_factor

GRID_S = 60.0
STORM_KEYS = ('T', 'RH', 'solar', 'wind', 'wind_dir', 'rain', 'co2', 'cloud', 'pressure',
              'gust', 'visibility')

# 지표용 위험 문턱 — 코디네이터 기본값(`PreGateConfig.wind_threshold` 12 m/s) 과 돌풍 15 m/s.
WIND_GATE_MS = 12.0
GUST_HAZARD_MS = 15.0


# ─────────────────────────────────────────────────────────────────────────────
# 도구
# ─────────────────────────────────────────────────────────────────────────────

def svp_kpa(T: float) -> float:
    """포화 수증기압 [kPa] (Magnus — 이 파일 안에서만 쓴다)."""
    return 0.6112 * math.exp(17.62 * T / (243.12 + T))


def rh_from_dewpoint(T: float, Td: float) -> float:
    return max(1.0, min(100.0, 100.0 * svp_kpa(min(Td, T)) / svp_kpa(T)))


def kf(points: Sequence[Tuple[float, float]], ease: bool = False) -> Callable[[float], float]:
    """키프레임 [(h, v)…] → h 의 함수. 범위 밖은 양끝 값. `ease` 면 키프레임 사이를 코사인으로."""
    pts = sorted(points)
    hs = [p[0] for p in pts]

    def f(h: float) -> float:
        if h <= hs[0]:
            return pts[0][1]
        if h >= hs[-1]:
            return pts[-1][1]
        lo, hi = 0, len(hs) - 1
        while hi - lo > 1:
            mid = (lo + hi) // 2
            if hs[mid] <= h:
                lo = mid
            else:
                hi = mid
        x = (h - hs[lo]) / (hs[hi] - hs[lo])
        if ease:
            x = 0.5 * (1.0 - math.cos(math.pi * x))
        return pts[lo][1] + (pts[hi][1] - pts[lo][1]) * x
    return f


def bump(h: float, center: float, width: float, peak: float) -> float:
    """가우스 모양 한 덩이(강우 띠)."""
    return peak * math.exp(-(((h - center) / width) ** 2))


class _Ar1:
    """정상 AR(1) — 평균 0, 표준편차 sigma, 상관시간 tau_s."""

    def __init__(self, rnd: random.Random, tau_s: float, sigma: float, step_s: float = GRID_S):
        self.rnd, self.sigma = rnd, sigma
        self.a = math.exp(-step_s / max(1.0, tau_s))
        self.x = rnd.gauss(0.0, sigma)

    def step(self, sigma: float = None) -> float:
        s = self.sigma if sigma is None else sigma
        self.x = self.a * self.x + math.sqrt(1.0 - self.a ** 2) * self.rnd.gauss(0.0, s)
        return self.x


def diurnal_extrema(t0: float, tmins: Sequence[float], tmaxs: Sequence[float],
                    h_min: float = 5.5, h_max: float = 14.5,
                    tz: str = DEFAULT_TZ) -> Callable[[float], float]:
    """날마다 (최저 h_min, 최고 h_max) 극값 사이를 코사인으로 잇는 기온 함수 f(h since t0).

    `scenarios._diurnal_frac` 은 날짜가 바뀌는 자정에 계수가 뛴다. 이쪽은 극값을 시간순으로 놓고
    이어서 연속이다. 날짜 목록이 모자라면 마지막 값.
    """
    l0 = to_tz(t0, tz)
    d0 = wall_to_utc(l0.replace(tzinfo=None, hour=0, minute=0, second=0, microsecond=0), tz)
    base_h = (d0.timestamp() - t0) / 3600.0       # 시작 시각 기준 그날 0 시 [h] (<= 0)
    pts = []
    n_days = max(len(tmins), len(tmaxs)) + 3
    for d in range(-1, n_days):
        tmn = tmins[min(max(d, 0), len(tmins) - 1)]
        tmx = tmaxs[min(max(d, 0), len(tmaxs) - 1)]
        pts.append((base_h + 24.0 * d + h_min, float(tmn)))
        pts.append((base_h + 24.0 * d + h_max, float(tmx)))
    return kf(pts, ease=True)


# ─────────────────────────────────────────────────────────────────────────────
# 조립
# ─────────────────────────────────────────────────────────────────────────────

def wind_from_mean(mean: float, rnd_turb: _Ar1) -> Tuple[float, float]:
    """평균 풍속 → (시설이 겪는 60 s 표본 풍속, 그 1 분의 돌풍 최댓값)."""
    ti = 0.10 + 0.25 / (1.0 + mean / 3.0)         # 난류 강도: 약풍일수록 상대 변동이 크다
    sig = ti * max(mean, 0.3)
    w = max(0.0, mean + rnd_turb.step(sig))
    g = max(w, mean + 2.4 * sig)
    return w, g


def assemble(sc, point: Callable[[float, float, dict], dict],
             extra_keys: Sequence[str] = ()) -> WeatherSeries:
    """격자를 돌며 `point(h, t_epoch, st)` 가 낸 값으로 시계열을 만든다.

    point 는 {'T','Td' 또는 'RH','wind_mean','wind_dir','rain','cloud','tau','pressure',
    'visibility', 'rh_min'} 와 extra_keys 를 돌려준다. 난수 상태는 `st` 에 싣는다.
    """
    rnd = random.Random(sc.seed)
    st = {'rnd': rnd, 'turb': _Ar1(rnd, 45.0, 1.0), 'rain_j': _Ar1(rnd, 300.0, 1.0),
          'meso': _Ar1(rnd, 900.0, 0.04)}
    n = int(round(sc.hours * 3600.0 / GRID_S)) + 1
    ts = [sc.t0 + i * GRID_S for i in range(n)]
    data = {k: [] for k in tuple(STORM_KEYS) + tuple(extra_keys)}
    for i, t in enumerate(ts):
        h = i * GRID_S / 3600.0
        p = point(h, t, st)
        T = float(p['T'])
        rain = max(0.0, float(p.get('rain', 0.0)))
        if rain > 0.3:
            rain = min(rain * math.exp(0.15 * st['rain_j'].step()), float(p.get('rain_cap', 80.0)))
        rain = rain if rain >= 0.3 else 0.0
        if 'RH' in p:
            RH = float(p['RH'])
        else:
            RH = rh_from_dewpoint(T, float(p['Td']))
        floor = float(p.get('rh_rain', 95.0))
        if rain > 0.5 and RH < floor:
            RH += (floor - RH) * min(1.0, rain / 8.0)      # 비가 셀수록 포화에 가깝다
        RH = min(100.0, RH)
        # 돌풍군(중규모 변동): 10 분 평균도 ±4 % 안팎으로 일렁인다.
        wmean = max(0.0, float(p['wind_mean'])) * (1.0 + st['meso'].step())
        w, g = wind_from_mean(wmean, st['turb'])
        cloud = max(0.0, min(1.0, float(p.get('cloud', 0.0))))
        tau = p.get('tau')
        if tau is None:
            tau = cloud_factor(cloud) * (1.0 - 0.8 * min(1.0, rain / 5.0))
        solar = clear_sky_ghi(t, sc.lat, sc.lon) * max(0.0, min(1.0, float(tau)))
        data['T'].append(round(T, 3))
        data['RH'].append(round(RH, 2))
        data['solar'].append(round(solar, 1))
        data['wind'].append(round(w, 2))
        data['gust'].append(round(g, 2))
        data['wind_dir'].append(round(float(p.get('wind_dir', 225.0)) % 360.0, 1))
        data['rain'].append(round(rain, 2))
        data['co2'].append(float(p.get('co2', 420.0)))
        data['cloud'].append(round(cloud, 3))
        data['pressure'].append(round(float(p.get('pressure', 1010.0)), 1))
        data['visibility'].append(round(float(p.get('visibility', 20.0)), 3))
        for k in extra_keys:
            data[k].append(float(p.get(k, 0.0)))
    return WeatherSeries(ts, data)


# ─────────────────────────────────────────────────────────────────────────────
# 1) 태풍 — 2027-09-05 14:00 시작, 48 h
# ─────────────────────────────────────────────────────────────────────────────
# 시설이 진로의 동쪽(위험반원)에 놓인 서해안 통과를 그린다: 바람이 동 → 남동 → 남 → 남서 → 서 → 북서로
# **시계 방향으로 돈다**. h 는 시작(9/5 14:00) 이후 시간: 최대풍 h≈20(9/6 10:00), 중심기압 최저
# h≈20.5, 개이는 것은 h≈34 이후, 9/7 아침(h 40~48)에 덥고 습한 맑은 날.

_TY_WIND = [(0, 4.5), (4, 6), (6, 9), (10, 12), (13, 15), (16, 19), (18, 22.5), (20, 25),
            (22, 24), (24, 21), (26, 19), (28, 15), (31, 11), (34, 7), (38, 4), (42, 2.5), (48, 2.0)]
_TY_DIR = [(0, 90), (6, 95), (10, 105), (14, 125), (17, 150), (19.5, 175), (21, 200), (23, 230),
           (26, 265), (30, 290), (34, 305), (40, 270), (44, 230), (48, 215)]
_TY_PRESSURE = [(0, 1004), (6, 1001), (12, 994), (16, 984), (18.5, 968), (20.5, 958), (23, 962),
                (26, 972), (30, 986), (34, 996), (40, 1003), (48, 1006)]
_TY_T = [(0, 29.5), (3, 29.0), (5, 26.5), (8, 26.0), (12, 25.0), (18, 24.2), (22, 23.8),
         (28, 24.0), (32, 24.8), (34, 24.0), (38, 23.0), (40, 22.2), (42, 24.5), (44, 28.5),
         (46, 31.5), (48, 33.0)]
_TY_TD = [(0, 23.5), (6, 24.5), (12, 24.4), (20, 23.7), (30, 23.5), (34, 22.5), (40, 21.8),
          (44, 23.5), (48, 24.3)]
_TY_CLOUD = [(0, 0.5), (4, 0.7), (7, 0.9), (10, 1.0), (31, 1.0), (33, 0.8), (36, 0.5),
             (39, 0.2), (42, 0.1), (48, 0.15)]
# (중심 h, 폭 h, 최대 mm/h) — 외곽 띠에서 중심 띠로 갈수록 세진다.
_TY_BANDS = [(5.7, 0.8, 8), (8.6, 0.6, 7), (11.7, 0.9, 22), (14.8, 1.0, 28), (17.0, 0.8, 35),
             (19.2, 0.9, 40), (20.1, 0.6, 50), (22.5, 1.0, 38), (24.6, 0.9, 30),
             (27.3, 1.0, 20), (29.8, 0.8, 12), (31.5, 0.6, 5)]


def build_typhoon(sc) -> WeatherSeries:
    f_wind, f_dir, f_p = kf(_TY_WIND), kf(_TY_DIR), kf(_TY_PRESSURE)
    f_T, f_Td, f_cl = kf(_TY_T, ease=True), kf(_TY_TD, ease=True), kf(_TY_CLOUD)

    def point(h, t, st):
        rain = 0.0
        for c, w, pk in _TY_BANDS:
            rain += bump(h, c, w, pk)
        if 10.0 <= h <= 31.0:
            rain += 1.5                                   # 띠 사이 이슬비
        vis = 20.0 if rain <= 0.3 else max(0.3, 8.0 / (1.0 + rain / 3.0))
        return {'T': f_T(h) - min(1.5, 0.08 * rain), 'Td': f_Td(h),
                'wind_mean': f_wind(h), 'wind_dir': f_dir(h), 'rain': min(rain, 48.0),
                'rain_cap': 55.0, 'cloud': f_cl(h), 'pressure': f_p(h), 'visibility': vis,
                'rh_rain': 96.0}
    return assemble(sc, point)


# ─────────────────────────────────────────────────────────────────────────────
# 2) 열대류 스콜 — 2027-08-02 06:00 시작, 34 h
# ─────────────────────────────────────────────────────────────────────────────
# 첫날 16:10(h=10.17)에 돌풍전선이 온다: 15 K 하강(20 분), 호우 30 분, 17:30 이후 다시 해. 이튿날은 맑고 덥다.

SQ_TF = 10.17          # 돌풍전선 도착 [h since start]


def build_squall(sc) -> WeatherSeries:
    t0 = sc.t0
    base_T = diurnal_extrema(t0, [25.5, 24.5], [34.8, 34.0])
    tf = SQ_TF
    # 기온: 맑은 날 곡선에서 빼는 하강량(K) — 5 분에 3 K, 20 분에 15 K, 한 시간 넘게 19 °C 대.
    f_drop = kf([(0, 0), (tf, 0), (tf + 0.083, 3.0), (tf + 0.33, 15.0), (tf + 0.8, 14.5),
                 (tf + 1.5, 11.3), (tf + 3.3, 7.0), (tf + 6.0, 3.5), (tf + 10.0, 1.5),
                 (tf + 14.0, 0.5), (tf + 16.0, 0.0)], ease=True)
    f_Td = kf([(0, 21.5), (tf, 21.5), (tf + 0.33, 19.0), (tf + 1.0, 19.2), (tf + 2.0, 20.5),
               (tf + 4.0, 21.5), (30, 21.0)], ease=True)
    wind_day = kf([(0, 1.5), (3, 2.5), (8, 3.0), (tf - 0.6, 2.5), (tf - 0.15, 1.1), (tf - 0.005, 1.1),
                   (tf + 0.07, 15.0), (tf + 0.12, 16.0), (tf + 0.5, 11.0), (tf + 1.0, 6.0),
                   (tf + 1.8, 3.0), (tf + 4.0, 1.0), (tf + 12, 0.8), (tf + 17, 2.5), (40, 3.0)])
    f_dir = kf([(0, 225), (tf - 0.001, 225), (tf + 0.001, 340), (tf + 1.5, 330), (tf + 4, 280),
                (tf + 12, 230), (40, 225)])
    f_tau = kf([(0, 0.97), (tf - 1.0, 0.96), (tf - 0.3, 0.9), (tf - 0.05, 0.55), (tf + 0.1, 0.07),
                (tf + 0.7, 0.08), (tf + 1.0, 0.35), (tf + 1.5, 0.8), (tf + 2.0, 0.96), (40, 0.97)])
    f_cl = kf([(0, 0.05), (tf - 1.0, 0.15), (tf - 0.05, 0.7), (tf + 0.1, 1.0), (tf + 1.0, 0.9),
               (tf + 1.6, 0.4), (tf + 2.2, 0.1), (40, 0.05)])
    f_p = kf([(0, 1006), (tf - 0.15, 1005.5), (tf + 0.05, 1009.0), (tf + 0.5, 1008.0),
              (tf + 2.0, 1006.5), (40, 1006)])

    def point(h, t, st):
        # 호우 핵은 전선 도착 4 분 뒤부터(그 전에는 비가 없다), 30 분 넘게 30 mm/h 이상, 꼬리 비는 30 분.
        x = (h - (tf + 0.07)) / 0.10
        onset = 0.0 if x <= 0.0 else (1.0 if x >= 1.0 else x * x * (3.0 - 2.0 * x))
        rain = onset * (bump(h, tf + 0.38, 0.27, 60.0) + bump(h, tf + 0.9, 0.4, 6.0))
        if rain < 0.4:
            rain = 0.0
        vis = 20.0 if rain <= 0.3 else max(0.3, 8.0 / (1.0 + rain / 3.0))
        return {'T': base_T(h) - f_drop(h), 'Td': f_Td(h), 'wind_mean': wind_day(h),
                'wind_dir': f_dir(h), 'rain': min(rain, 62.0), 'rain_cap': 70.0,
                'cloud': f_cl(h), 'tau': f_tau(h), 'pressure': f_p(h), 'visibility': vis,
                'rh_rain': 97.0}
    return assemble(sc, point)


# ─────────────────────────────────────────────────────────────────────────────
# 3) 폭염 + 열대야 — 2027-08-06 04:00 시작, 72 h
# ─────────────────────────────────────────────────────────────────────────────

def build_heatwave(sc) -> WeatherSeries:
    t0 = sc.t0
    f_T = diurnal_extrema(t0, [27.2, 27.8, 28.4], [36.0, 37.5, 38.0])
    # 이슬점: 밤에 높고(26~27 °C → 밤 RH 90 % 이상) 낮에 조금 낮다(RH 40 %대).
    f_Td = diurnal_extrema(t0, [26.5, 27.0, 27.2], [25.0, 25.5, 25.8])
    f_w = diurnal_extrema(t0, [0.7, 0.6, 0.6], [2.8, 3.0, 2.6])

    def point(h, t, st):
        return {'T': f_T(h), 'Td': f_Td(h), 'wind_mean': f_w(h), 'wind_dir': 225.0,
                'rain': 0.0, 'cloud': 0.05, 'tau': 0.96, 'pressure': 1006.0, 'visibility': 8.0}
    return assemble(sc, point)


# ─────────────────────────────────────────────────────────────────────────────
# 4) 푄(높새) 건조열풍 — 2027-06-02 06:00 시작, 36 h
# ─────────────────────────────────────────────────────────────────────────────

def build_foehn(sc) -> WeatherSeries:
    t0 = sc.t0
    f_T = diurnal_extrema(t0, [24.5, 24.5], [31.5, 31.5])
    ramp = kf([(0, 0.0), (2.5, 1.0)], ease=True)                # 시작 2.5 h 에 푄이 자리잡는다

    def point(h, t, st):
        r = ramp(h)
        # 느린 변조(±0.5 m/s, 상관 시간 ~30 분) — 푄은 '거의 일정' 하다.
        if 'slow' not in st:
            st['slow'] = _Ar1(st['rnd'], 1800.0, 0.45)
        wm = 3.0 + (10.0 - 3.0) * r + st['slow'].step() * r
        Td = 11.0 + (2.5 - 11.0) * r
        T = f_T(h) - 4.0 * (1.0 - r)
        return {'T': T, 'Td': Td, 'wind_mean': max(0.0, wm), 'wind_dir': 60.0 + 4.0 * math.sin(h / 3.0),
                'rain': 0.0, 'cloud': 0.0, 'tau': 0.98, 'pressure': 1010.0 - 3.0 * r,
                'visibility': 25.0}
    return assemble(sc, point)


# ─────────────────────────────────────────────────────────────────────────────
# 5) 늦서리 — 2027-04-10 08:00 시작, 36 h  (맑고 바람 없는 밤의 복사냉각)
# ─────────────────────────────────────────────────────────────────────────────

_FR_T = [(0, 7.0), (3, 12.0), (6.5, 18.0), (8, 17.0), (10, 14.5), (11, 11.5), (12, 8.7), (14, 4.2),
         (16, 1.2), (18, -1.5), (20, -3.3), (21.5, -4.0), (22.5, -3.4), (24, -1.0), (25, 3.0),
         (26, 7.5), (28, 12.5), (30.5, 16.0), (32, 15.5), (34, 12.5), (36, 9.0)]
_FR_TD = [(0, -2.0), (6.5, 1.5), (10, 1.0), (14, -1.5), (18, -3.5), (21.5, -5.0), (24, -4.5),
          (28, -2.0), (30.5, 0.0), (36, -1.0)]
_FR_W = [(0, 1.5), (4, 2.5), (8, 2.0), (11, 0.6), (13, 0.3), (23, 0.25), (24, 0.8), (27, 2.0),
         (30, 3.0), (36, 2.0)]


def build_frost(sc) -> WeatherSeries:
    f_T, f_Td, f_w = kf(_FR_T, ease=True), kf(_FR_TD, ease=True), kf(_FR_W)

    def point(h, t, st):
        return {'T': f_T(h), 'Td': f_Td(h), 'wind_mean': f_w(h),
                'wind_dir': 320.0 if h < 12 or h > 24 else 20.0, 'rain': 0.0,
                'cloud': 0.0, 'tau': 0.99, 'pressure': 1024.0, 'visibility': 30.0}
    return assemble(sc, point)


# ─────────────────────────────────────────────────────────────────────────────
# 6) 아침 안개 → 갑작스런 맑음 — 2027-10-18 21:00 시작, 30 h
# ─────────────────────────────────────────────────────────────────────────────

FOG_ON_H, FOG_OFF_H = 5.0, 14.0          # 02:00 에 끼고 11:00 에 걷힌다(시작 21:00 기준)

_FG_T = [(0, 14.5), (2, 12.2), (4, 10.8), (5, 10.1), (9.5, 9.6), (12, 10.5), (13.7, 11.5),
         (14, 12.0), (15, 16.5), (16, 19.5), (17.5, 21.5), (19, 21.0), (21, 17.0), (24, 12.5),
         (26, 11.0), (30, 9.5)]
_FG_TD = [(0, 9.0), (4, 9.8), (5, 10.1), (9.5, 9.6), (13.7, 11.4), (14, 11.5), (15, 10.5),
          (16, 9.0), (17.5, 8.0), (19, 8.5), (24, 9.5), (30, 9.5)]


def build_fog(sc) -> WeatherSeries:
    f_T, f_Td = kf(_FG_T, ease=True), kf(_FG_TD, ease=True)
    f_tau = kf([(0, 1.0), (FOG_ON_H - 0.01, 1.0), (FOG_ON_H, 0.10), (13.8, 0.10), (14.1, 0.95),
                (30, 0.97)])
    f_cl = kf([(0, 0.1), (4, 0.1), (FOG_ON_H, 1.0), (13.8, 1.0), (14.2, 0.15), (30, 0.1)])
    f_w = kf([(0, 0.8), (4, 0.3), (14.0, 0.3), (15.0, 2.0), (18, 2.5), (24, 0.6), (30, 0.4)])

    def point(h, t, st):
        fog = FOG_ON_H <= h < FOG_OFF_H
        out = {'T': f_T(h), 'Td': f_Td(h), 'wind_mean': f_w(h),
               'wind_dir': 300.0 if h > FOG_OFF_H else 90.0, 'rain': 0.0, 'cloud': f_cl(h),
               'tau': f_tau(h), 'pressure': 1022.0, 'visibility': 20.0}
        if fog:
            out.update({'RH': 100.0, 'T': min(f_T(h), f_Td(h) + 0.1), 'visibility': 0.12})
        return out
    return assemble(sc, point)


# ─────────────────────────────────────────────────────────────────────────────
# 7) 예보 강수 vs 실측 강우계 — 2027-08-14 05:00 시작, 30 h (덥고 맑음이 이어진다)
# ─────────────────────────────────────────────────────────────────────────────
# 실측: 비 없음. 예보 모델(Open-Meteo)은 낮 12~17시에 시간당 0.5~1.8 mm 를 내놓는다 — 모델이 소나기를
# 엉뚱한 시각·장소에 놓은 흔한 오차. 예보값은 시 단위 계단이다(그 시각이 속한 한 시간의 모델값).

_FC_RAIN_BY_HOUR = {12: 0.6, 13: 1.2, 14: 1.8, 15: 1.4, 16: 0.9, 17: 0.5}


def build_forecast_rain(sc) -> WeatherSeries:
    t0 = sc.t0
    f_T = diurnal_extrema(t0, [25.0, 25.0], [34.5, 34.0])
    f_Td = diurnal_extrema(t0, [22.0, 22.0], [20.5, 20.5])
    f_w = diurnal_extrema(t0, [0.9, 0.9], [2.8, 2.8], h_min=3.0, h_max=14.0)

    def point(h, t, st):
        lh = to_tz(t, sc.tz)
        day = (lh.date() - to_tz(t0, sc.tz).date()).days
        fc = _FC_RAIN_BY_HOUR.get(lh.hour, 0.0) if day == 0 else 0.0
        aft = 0.2 if 12 <= lh.hour < 17 else 0.05           # 낮 적운 — 해는 거의 그대로
        return {'T': f_T(h), 'Td': f_Td(h), 'wind_mean': f_w(h),
                'wind_dir': 225.0, 'rain': 0.0, 'cloud': aft, 'tau': 0.95 if aft < 0.1 else 0.85,
                'pressure': 1008.0, 'visibility': 15.0, 'fc_rain': fc}
    return assemble(sc, point, extra_keys=('fc_rain',))


# ─────────────────────────────────────────────────────────────────────────────
# 8) 습한 밤 + 관측소 두절 + 자정의 이슬비 — 2027-10-10 12:00 시작, 24 h
# ─────────────────────────────────────────────────────────────────────────────
# 김제 2026-10-10 밤을 그린다: 흐리고 고요한 가을 저녁(바깥 16~23 °C, RH 80~93 %, 이슬점 15~19 °C). 작물 증산으로 닫힌
# 집의 실내 RH 가 90 % 를 넘으면 하드 습도 상한(`humid_max` 90)이 야간 파킹을 풀어 창이 열린다. 22:30 에 기상청 값이 끊기고
# (`outdoor_stale`, 01:30 까지) 그 사이 00:00 부터 이슬비(0.6~1.5 mm/h)가 내린다 — 제어기는 비를 볼 수 없다. 두절 중 비를
# 맞으며 열려 있던 분·'더 열기' 명령·두절 닫기(근거 58)를 잰다. h 는 시작(12:00) 이후 시간.
# ⚠ 이 단일 구역 시설에서는 습도 상한이 연 창(21:40~22:00, 40 %)을 과습 구간 파킹(근거 24 — 바깥도 습하다)이 두절 전후로
#   이미 감쇠해 닫는다(2026-10-12 실행: 22:50 에 0 %, 비 중 열림 0 분). 그래서 '30 분 넘은 두절의 단계 닫기' 경로까지는 가지
#   않는다 — 그 경로의 정본 시험은 단위 시험(`test_outage_dehumid_close`)이고, 여기서는 회귀(비 중 열림·더 열기 0)를 지킨다.

NO_OUTAGE_H = (10.5, 13.5)           # 22:30 ~ 01:30 두절
NO_RAIN_H = (12.0, 15.5)             # 00:00 ~ 03:30 이슬비

_NO_T = [(0, 23.5), (3, 22.5), (5, 21.5), (7, 19.5), (9, 18.3), (12, 17.2), (15, 16.6), (18, 16.2),
         (19.5, 16.6), (21, 18.5), (24, 21.5)]
_NO_TD = [(0, 18.6), (6, 18.2), (9, 17.3), (10.5, 16.4), (12, 15.9), (15, 15.3), (18, 14.8), (21, 15.0),
          (24, 15.5)]
_NO_W = [(0, 2.2), (3, 1.8), (6, 1.2), (9, 0.8), (15, 0.6), (19, 0.8), (24, 1.8)]


def build_humid_outage_night(sc) -> WeatherSeries:
    f_T, f_Td, f_w = kf(_NO_T, ease=True), kf(_NO_TD, ease=True), kf(_NO_W)
    r0, r1 = NO_RAIN_H

    def point(h, t, st):
        rain = 0.0
        if r0 <= h < r1:
            # 가는 비 — 들고 나는 0.5 h 와 한가운데 1.5 mm/h 안팎(15 분 누적 0.4 mm 남짓, 게이트 문턱 0.5 mm 아래로 시작).
            edge = min(1.0, (h - r0) / 0.5, (r1 - h) / 0.5)
            rain = 0.6 + 0.9 * edge
        vis = 20.0 if rain <= 0.3 else 6.0
        return {'T': f_T(h) - min(0.6, 0.3 * rain), 'Td': f_Td(h), 'wind_mean': f_w(h),
                'wind_dir': 200.0, 'rain': rain, 'rain_cap': 2.5, 'cloud': 0.85, 'tau': 0.35,
                'pressure': 1009.0, 'visibility': vis, 'rh_rain': 97.0}
    return assemble(sc, point)


__all__ = ['build_typhoon', 'build_squall', 'build_heatwave', 'build_foehn', 'build_frost',
           'build_fog', 'build_forecast_rain', 'build_humid_outage_night', 'kf', 'bump',
           'diurnal_extrema',
           'rh_from_dewpoint', 'svp_kpa', 'WIND_GATE_MS', 'GUST_HAZARD_MS', 'SQ_TF',
           'FOG_ON_H', 'FOG_OFF_H', 'NO_OUTAGE_H', 'NO_RAIN_H']
