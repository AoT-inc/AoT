# coding=utf-8
"""
greybox/model.py — 시설 열·수분·CO₂ 수지 ODE (그레이박스 모델, v2).

바깥 인터페이스는 [T_int, RH_int, CO2_int] 이지만, 내부는 **수증기량**으로 적분한다
(2026-09-22, 계획서 env-mpc-reinforcement A 단계 D1). 적분 상태는 보존량인 절대습도
AH 이고, 수증기압 e·RH·VPD 는 매 순간 (T, AH) 에서 계산한다.

⚠ e 를 직접 적분하지 않는 이유: de/dt 에 AH·dT/dt 항이 들어가는데, 온도가 물리
  범위에서 잘리는 순간에도 e 는 잘리지 않은 dT 로 움직여 발산한다(실측: 강한 가열에서
  RH 100 %). 보존량을 적분하면 그 결합이 사라진다.

## v1 에서 바뀐 것과 이유

- **수분은 수증기량으로 섞인다.** v1 은 환기를 상대습도 차(RH_ext − RH)로 섞었다.
  차고 습한 외기는 RH 가 높아도 실내에 들어오면 실내 RH 를 내릴 수 있다 — 섞이는
  것은 수증기량이다. 이제 절대습도 AH 로 수지를 세우고 e 로 바꾼다.
- **온도가 RH 를 바꾼다.** v1 은 이 효과를 무시했다(주석에 명시). 상태가 e 라서
  가온하면 RH 가 내려가는 것이 저절로 나온다.
- **증산**(k_transp, 일사·VPD 비례)과 그 잠열, **광합성 CO₂ 흡수**(k_photo).
- **환기량 풍속 보정**(legacy `_wind_boost` 와 같은 식).
- **분무 = 증발냉각**: 잠열 출력 m_fog_evap 을 증발량 E 로 보고, 같은 E 가 냉각과
  수분을 동시에 만든다. 포화에 가까울수록 증발이 줄어든다(legacy 증발 가용도와 같은
  기준 70 %).
- **차광막**: 일사 유입 × (tau_shade + (1 − tau_shade)·개도). 입력 `cmds['shade']`
  (개도 %, 100 = 걷힘). 없으면 걷힌 것으로 본다.
- **CO₂ 환기**: v1 의 `vent_m3s / tau_co2` 는 차원이 맞지 않았다. 이제 V̇/V.

상태벡터(내부): [T, AH, CO2]  입력: ext{T_ext, RH_ext, CO2_ext, solar, wind},
cmds{heat, cool, vent, fog, co2_inj, shade}. 단계 적분: RK4 + 안정 서브스텝.
"""

from __future__ import annotations

import math

from typing import Dict, Optional, Tuple

from .params import GreyboxParams

# 공기 물성 상수
RHO_CP_AIR = 1200.0   # J/(m³·K): 공기 체적비열
CP_AIR     = 1006.0   # J/(kg·K)
RHO_AIR    = 1.2      # kg/m³


def step(
    T_int: float,
    RH_int: float,
    CO2_int: float,
    ext: Dict[str, float],
    cmds: Dict[str, float],
    params: GreyboxParams,
    dt: float = 60.0,
) -> Tuple[float, float, float]:
    """ODE 1-step RK4 적분. 입력·출력은 (T, RH, CO2), 내부는 (T, e, CO2).

    Args:
        ext:  {'T_ext', 'RH_ext', 'CO2_ext', 'solar', 'wind'}
        cmds: {'heat', 'cool', 'vent', 'fog', 'co2_inj', 'shade'} (0~100 %)
    """
    ah0 = _ah(T_int, _vp(T_int, RH_int))

    def deriv(s):
        return _ode(s, ext, cmds, params)

    # 적분 안정화: 환기로 이완 rate 가 빠르면(시정수 ≪ dt) 단일 RK4 스텝이 발산한다.
    # 물리식은 그대로 두고 가장 빠른 이완 rate 기준으로 서브스텝을 나눈다.
    n_sub = _substeps_for_stability(ext, cmds, params, dt)
    h = dt / n_sub
    T_n, ah_n, CO2_n = T_int, ah0, CO2_int
    for _ in range(n_sub):
        s = (T_n, ah_n, CO2_n)
        k1 = deriv(s)
        k2 = deriv(_add(s, _scale(k1, h / 2)))
        k3 = deriv(_add(s, _scale(k2, h / 2)))
        k4 = deriv(_add(s, _scale(k3, h)))
        T_n   = T_n   + h / 6 * (k1[0] + 2*k2[0] + 2*k3[0] + k4[0])
        ah_n  = ah_n  + h / 6 * (k1[1] + 2*k2[1] + 2*k3[1] + k4[1])
        CO2_n = CO2_n + h / 6 * (k1[2] + 2*k2[2] + 2*k3[2] + k4[2])
        # 포화를 넘는 수증기는 맺힌다(결로) — 포화량으로 자른다.
        T_n  = max(-10.0, min(60.0, T_n))
        ah_n = max(0.0, min(ah_n, _ah(T_n, _svp(T_n))))

    CO2_n = max(300.0, min(5000.0, CO2_n))
    RH_n = max(0.0, min(100.0, 100.0 * _e_of(T_n, ah_n) / _svp(T_n)))
    return T_n, RH_n, CO2_n


def _substeps_for_stability(ext, cmds, p: GreyboxParams, dt: float) -> int:
    """가장 빠른 선형 이완 rate 기준으로 안정 서브스텝 수 산출.

    각 상태의 이완 계수 A [1/s]:
      A_T   = (UA_eff + ρcp·V̇) / (tau_T·UA_eff)
      A_hum = A_CO2 = V̇ / V
    명시적 RK4 안정영역(A·h ≲ 0.25)을 만족하도록 n = ceil(A_max·dt/0.25), [1,600] 클램프.
    """
    vent_m3s = _vent_m3s(ext, cmds, p)
    thermal_mass = max(p.tau_T * p.UA_eff, 1.0)
    a_t = (p.UA_eff + RHO_CP_AIR * vent_m3s) / thermal_mass
    a_x = vent_m3s / _volume(p)
    a_max = max(a_t, a_x, 1e-9)
    n = int(a_max * dt / 0.25) + 1
    return max(1, min(600, n))


def predict_horizon(
    T_int: float,
    RH_int: float,
    CO2_int: float,
    ext_seq: list,        # [ext_dict] 길이 H
    cmds_seq: list,       # [cmds_dict] 길이 H
    params: GreyboxParams,
    dt: float = 60.0,
) -> list:
    """H 스텝 lookahead 예측. Returns: [(T, RH, CO2)] 길이 H"""
    trajectory = []
    T, RH, CO2 = T_int, RH_int, CO2_int
    for ext, cmds in zip(ext_seq, cmds_seq):
        T, RH, CO2 = step(T, RH, CO2, ext, cmds, params, dt)
        trajectory.append((T, RH, CO2))
    return trajectory


# ── ODE 내부 구현 ─────────────────────────────────────────────────────────────

L_V_J       = 2.45e6      # J/kg 증발잠열(20 °C 부근)
R_V         = 461.5       # J/(kg·K) 수증기 기체상수
SOLAR_REF   = 500.0       # W/m² 증산·광합성 기준 일사
TRANSP_BASE = 0.15        # 밤(일사 0)의 증산 비율
EVAP_REF_RH = 70.0        # 분무 증발 가용도 기준 습도(legacy `_EVAP_REF_RH` 와 같다)
CO2_HALF    = 300.0       # ppm 광합성 CO₂ 반포화


def _svp(T: float) -> float:
    return 0.6108 * math.exp(17.27 * T / (T + 237.3))


def _vp(T: float, RH: float) -> float:
    return max(0.0, min(100.0, RH)) / 100.0 * _svp(T)


def _ah(T: float, e: float) -> float:
    """절대습도 [kg/m³]."""
    return e * 1000.0 / (R_V * (T + 273.15))


def _e_of(T: float, ah: float) -> float:
    """절대습도 → 수증기압 [kPa]."""
    return ah * R_V * (T + 273.15) / 1000.0


def _volume(p: GreyboxParams) -> float:
    v = getattr(p, 'volume_m3', None)
    if v and v > 0:
        return float(v)
    # 모르면 열용량에서 어림(ρcp V = tau_T·UA_eff). 구조체 열용량이 섞여 과대다.
    return max(p.tau_T * p.UA_eff / RHO_CP_AIR, 1.0)


def _vent_m3s(ext: dict, cmds: dict, p: GreyboxParams) -> float:
    wind = max(0.0, float(ext.get('wind', 0.0) or 0.0))
    boost = 1.0 + 0.15 * min(wind, 8.0)          # legacy `_wind_boost`
    return max(p.m_vent_coef, 0.0) * (cmds.get('vent', 0.0) / 100.0) * boost


def _ode(
    state: Tuple[float, float, float],
    ext: dict,
    cmds: dict,
    p: GreyboxParams,
) -> Tuple[float, float, float]:
    T, AH, CO2 = state
    e = _e_of(T, AH)
    T_e   = ext.get('T_ext',   20.0)
    RH_e  = ext.get('RH_ext',  60.0)
    CO2_e = ext.get('CO2_ext', 400.0)
    solar = ext.get('solar',    0.0) or 0.0

    cmd_heat    = cmds.get('heat',    0.0) / 100.0
    cmd_cool    = cmds.get('cool',    0.0) / 100.0
    cmd_fog     = cmds.get('fog',     0.0) / 100.0
    cmd_co2_inj = cmds.get('co2_inj', 0.0) / 100.0
    shade_open  = max(0.0, min(100.0, cmds.get('shade', 100.0))) / 100.0

    V = _volume(p)
    vent_m3s = _vent_m3s(ext, cmds, p)
    e_sat = _svp(T)
    vpd = max(0.0, e_sat - e)
    shade_f = p.tau_shade + (1.0 - p.tau_shade) * shade_open
    solar_in = solar * shade_f

    # ── 수분원 [kg/s] ──────────────────────────────────────────────────────
    # 분무: 잠열 출력 m_fog_evap[W] 을 증발량으로. 포화에 가까울수록 줄어든다.
    avail = max(0.0, min(1.0, (1.0 - e / max(e_sat, 1e-6)) / (1.0 - EVAP_REF_RH / 100.0)))
    E_fog = p.m_fog_evap * cmd_fog * avail / L_V_J
    # 증산: 일사·VPD 비례(밤에도 기저 15 %).
    light_f = TRANSP_BASE + (1.0 - TRANSP_BASE) * min(solar_in / SOLAR_REF, 2.0)
    E_tr = p.k_transp * vpd * light_f

    # ── 온도 수지 dT/dt [K/s] ──────────────────────────────────────────────
    thermal_mass = max(p.tau_T * p.UA_eff, 1.0)
    Q = (p.UA_eff * (T_e - T)
         + p.alpha_sol * solar_in
         + p.Q_heat * cmd_heat - p.Q_cool * cmd_cool
         + RHO_CP_AIR * vent_m3s * (T_e - T)
         - (E_fog + E_tr) * L_V_J
         - p.Q_plant_base)
    dT = Q / thermal_mass

    # ── 수분 수지: V·dAH/dt = E_fog + E_tr − V̇·(AH − AH_ext) ────────────────
    AH_e = _ah(T_e, _vp(T_e, RH_e))
    dAH = (E_fog + E_tr - vent_m3s * (AH - AH_e)) / V

    # ── CO₂ 수지 [ppm/s] ────────────────────────────────────────────────────
    dCO2 = (vent_m3s / V * (CO2_e - CO2)
            + p.K_CO2_inj * cmd_co2_inj
            - p.k_photo * min(solar_in / SOLAR_REF, 2.0) * CO2 / (CO2 + CO2_HALF))

    return dT, dAH, dCO2


def _add(a, b):
    return tuple(x + y for x, y in zip(a, b))


def _scale(a, s):
    return tuple(x * s for x in a)
