# coding=utf-8
"""
env_control/psychro.py — 습공기 계산과 분무 증발(증발냉각 액추에이터).

계획서 `env-mpc-reinforcement.md` 4.1 (2026-09-22). PI 효과 모델과 greybox/MPC 가
**같은 계산**을 쓰게 하려는 공용 모듈이다 — 두 엔진이 같은 분무를 다르게 알면
엔진을 바꿀 때 동작이 갈린다. 순수 함수만 둔다(상태·DB·로그 없음).

## 단위 (고정)

    온도 T         °C
    수증기압 e·p   kPa          (기압 p 는 시설 고도에서, 모르면 101.325)
    습도비 w       kg 물 / kg 건공기
    엔탈피 h       kJ / kg 건공기   (기준 0 °C 건공기·0 °C 액체 물)
    질량유량       kg/s          (분무 ṁ_w, 건공기 ṁ_da)
    열량           kW

## 분무 = 증발냉각 액추에이터

증발은 한 번 일어나 냉각과 가습을 **동시에** 만든다. 그래서 증발량 E 를 먼저 구하고
출구 공기를 **질량·에너지 보존**으로 푼다 — 냉각과 가습을 따로 추정하지 않는다.

    w_max = w_sat(T_as(T_in, w_in))           유입 공기의 단열포화 한계
    E     = min(η·ṁ_w,  ε·ṁ_da·(w_max − w_in))
    질량   ṁ_da·(w_out − w_in) = E
    에너지 ṁ_da·h_in + E·h_물(T_물) = ṁ_da·h_out

- η: 노즐이 물을 증발 가능하게 쪼개는 비율. ε: 공기가 포화에 다가가는 정도.
  물리가 달라 나눈다 — 나눠야 학습에서 식별된다.
- **유입 공기**는 팬·창으로 들어오면 외기, 실내 순환이면 실내 상태다. 이 모듈은
  어느 쪽인지 모른다 — 호출자가 고른다.
- 잠열이 1차다. 못 날린 물의 현열은 2차 보정이며 기본으로 끈다
  (`include_unevaporated_sensible`) — 분무 1 kg 중 0.8 kg 증발 시 잠열 ≈ 1,950 kJ,
  못 날린 물 현열 ≈ 6 kJ. 물방울은 공기 온도가 아니라 습구온도 근처까지만 데워진다.

⚠ 포화 수증기압은 이 저장소의 다른 곳과 **같은 Magnus 식**이다
  (`situation.svp`). 식이 둘이면 같은 상태에서 VPD 가 두 값이 된다.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

P_STD_KPA = 101.325
R_DA      = 287.055       # J/(kg·K) 건공기 기체상수
EPS_MW    = 0.621945      # 물/건공기 분자량 비
CP_DA     = 1.006         # kJ/(kg·K) 건공기
CP_V      = 1.86          # kJ/(kg·K) 수증기
CP_W      = 4.186         # kJ/(kg·K) 액체 물
L_V0      = 2501.0        # kJ/kg 0 °C 증발잠열


# ─────────────────────────────────────────────────────────────────────────────
# 기본 상태량
# ─────────────────────────────────────────────────────────────────────────────

def svp(T: float) -> float:
    """포화 수증기압 [kPa] (Magnus). `situation.svp` 와 같은 식이다."""
    return 0.6108 * math.exp(17.27 * T / (T + 237.3))


def pressure_from_elevation(z_m: Optional[float]) -> float:
    """표준 대기 기압 [kPa]. 고도를 모르면 해면 기압."""
    if z_m is None:
        return P_STD_KPA
    return P_STD_KPA * (1.0 - 2.25577e-5 * float(z_m)) ** 5.25588


def vapor_pressure(T: float, RH: float) -> float:
    """수증기압 [kPa]. RH 는 % (0~100 으로 자른다)."""
    return max(0.0, min(100.0, RH)) / 100.0 * svp(T)


def relative_humidity(T: float, e: float) -> float:
    """상대습도 [%] (0~100 으로 자른다)."""
    return max(0.0, min(100.0, 100.0 * e / svp(T)))


def humidity_ratio(e: float, p: float = P_STD_KPA) -> float:
    """습도비 w [kg/kg_da]."""
    e = max(0.0, min(e, p * 0.99))
    return EPS_MW * e / (p - e)


def vapor_pressure_from_ratio(w: float, p: float = P_STD_KPA) -> float:
    """습도비 → 수증기압 [kPa]."""
    w = max(0.0, w)
    return p * w / (EPS_MW + w)


def w_sat(T: float, p: float = P_STD_KPA) -> float:
    """포화 습도비 [kg/kg_da]."""
    return humidity_ratio(svp(T), p)


def enthalpy(T: float, w: float) -> float:
    """습공기 엔탈피 [kJ/kg_da]."""
    return CP_DA * T + w * (L_V0 + CP_V * T)


def temperature_from_enthalpy(h: float, w: float) -> float:
    """엔탈피·습도비 → 온도 [°C]."""
    return (h - w * L_V0) / (CP_DA + w * CP_V)


def dewpoint(e: float) -> Optional[float]:
    """이슬점 [°C]. 수증기압이 0 이면 None."""
    if e is None or e <= 0.0:
        return None
    a = math.log(e / 0.6108)
    return 237.3 * a / (17.27 - a)


def vpd(T: float, e: float) -> float:
    """VPD [kPa]."""
    return max(0.0, svp(T) - e)


def adiabatic_saturation_temperature(T: float, w: float,
                                     p: float = P_STD_KPA) -> float:
    """단열포화온도 [°C] — 이 공기를 단열 가습해 포화시켰을 때의 온도(≈ 습구온도).

    정의(에너지 보존, 가습수는 그 온도의 액체):
        h(T, w) + (w_s(T_s) − w)·c_w·T_s = h(T_s, w_s(T_s))
    T_s 는 이슬점과 건구온도 사이에 있다 — 이분법으로 푼다.
    """
    def f(Ts: float) -> float:
        ws = w_sat(Ts, p)
        return enthalpy(T, w) + (ws - w) * CP_W * Ts - enthalpy(Ts, ws)

    lo = dewpoint(vapor_pressure_from_ratio(w, p))
    lo = T - 60.0 if lo is None else min(lo, T) - 0.5
    hi = T
    if f(hi) >= 0.0:          # 이미 포화(또는 과포화)
        return T
    for _ in range(80):
        mid = 0.5 * (lo + hi)
        if f(mid) > 0.0:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


def dry_air_density(T: float, e: float, p: float = P_STD_KPA) -> float:
    """건공기 밀도 [kg_da/m³] — 습공기 1 m³ 안의 건공기 질량."""
    return (p - e) * 1000.0 / (R_DA * (T + 273.15))


def dry_air_mass_flow(volume_m3s: float, T: float, e: float,
                      p: float = P_STD_KPA) -> float:
    """체적 풍량 [m³/s] → 건공기 질량유량 [kg_da/s]."""
    return max(0.0, volume_m3s) * dry_air_density(T, e, p)


# ─────────────────────────────────────────────────────────────────────────────
# 분무 증발
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class Evaporation:
    E: float                 # 증발량 [kg/s]
    limited_by: str          # 'spray'(노즐) | 'air'(공기 수분 여유) | 'none'
    w_in: float
    w_out: float
    T_out: float             # 출구 공기 온도 [°C]
    RH_out: float            # 출구 공기 상대습도 [%]
    T_as: float              # 유입 공기의 단열포화온도 [°C]
    unevaporated: float      # 못 날린 물 [kg/s] — 잎 젖음
    Q_latent: float          # 증발 잠열 [kW] (양수 = 공기에서 뺀 열)


def evaporate(T_in: float, RH_in: float, m_da: float, m_w: float,
              eta: float = 1.0, eps: float = 1.0,
              p: float = P_STD_KPA, T_water: Optional[float] = None,
              include_unevaporated_sensible: bool = False) -> Evaporation:
    """유입 공기 (T_in, RH_in) 를 건공기 ṁ_da 로 흘리며 물 ṁ_w 를 분무했을 때.

    Args:
        m_da:    처리 풍량 [kg_da/s] (`dry_air_mass_flow` 로 환산)
        m_w:     분무량 [kg/s]
        eta:     노즐 증발 가능 비율 [0, 1]
        eps:     포화효율 [0, 1]
        T_water: 물 온도 [°C]. 없으면 유입 공기의 단열포화온도로 본다(현열 0).
        include_unevaporated_sensible: 못 날린 물이 T_물 → T_as 로 데워지며 공기에서
                 가져가는 현열(2차 보정). 기본 끔.

    처리 풍량이나 분무량이 0 이면 증발도 0 이다 — 모르는 풍량을 지어내지 않는다.
    """
    eta = max(0.0, min(1.0, eta))
    eps = max(0.0, min(1.0, eps))
    e_in = vapor_pressure(T_in, RH_in)
    w_in = humidity_ratio(e_in, p)
    T_as = adiabatic_saturation_temperature(T_in, w_in, p)
    Tw = T_as if T_water is None else float(T_water)

    if m_da <= 0.0 or m_w <= 0.0:
        return Evaporation(0.0, 'none', w_in, w_in, T_in,
                           relative_humidity(T_in, e_in), T_as,
                           max(0.0, m_w), 0.0)

    cap_air = eps * m_da * max(0.0, w_sat(T_as, p) - w_in)
    cap_spray = eta * m_w
    E = min(cap_spray, cap_air)
    limited = 'spray' if cap_spray <= cap_air else 'air'
    if E <= 0.0:
        limited = 'air'

    w_out = w_in + E / m_da
    h_out = enthalpy(T_in, w_in) + E * CP_W * Tw / m_da
    unevap = max(0.0, m_w - E)
    if include_unevaporated_sensible and unevap > 0.0:
        # 못 날린 물은 T_물 → T_as 까지만 데워진다(물방울은 습구온도로 간다).
        h_out -= unevap * CP_W * (T_as - Tw) / m_da
    T_out = temperature_from_enthalpy(h_out, w_out)
    e_out = vapor_pressure_from_ratio(w_out, p)
    return Evaporation(
        E=E, limited_by=limited, w_in=w_in, w_out=w_out, T_out=T_out,
        RH_out=relative_humidity(T_out, e_out), T_as=T_as,
        unevaporated=unevap, Q_latent=E * (L_V0 + CP_V * T_out - CP_W * Tw))


__all__ = [
    'P_STD_KPA', 'svp', 'pressure_from_elevation', 'vapor_pressure',
    'relative_humidity', 'humidity_ratio', 'vapor_pressure_from_ratio', 'w_sat',
    'enthalpy', 'temperature_from_enthalpy', 'dewpoint', 'vpd',
    'adiabatic_saturation_temperature', 'dry_air_density', 'dry_air_mass_flow',
    'Evaporation', 'evaporate',
]
