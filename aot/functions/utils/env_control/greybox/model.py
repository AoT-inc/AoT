# coding=utf-8
"""
greybox/model.py — 시설 열·수분·CO₂ 수지 ODE (그레이박스 모델).

상태벡터: [T_int, RH_int, CO2_int]
입력벡터: [T_ext, RH_ext, CO2_ext, solar, wind, cmd_heat, cmd_cool,
           cmd_vent(opening), cmd_fog, cmd_co2_inj]
파라미터: GreyboxParams

단계 적분: RK4 (1 cycle_sec)

설계 의도:
  - 물리식 구조 고정 (over-fit 방지, 외삽 안정)
  - 계수 10개만 학습 (identification.py, EKF)
  - prediction(1-step ahead) 을 coordinator 가 사용 (Stage 3 MPC)
"""

from __future__ import annotations

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
    """ODE 1-step RK4 적분.

    Args:
        T_int, RH_int, CO2_int: 현재 내부 상태
        ext: {'T_ext', 'RH_ext', 'CO2_ext', 'solar', 'wind'}
        cmds: {'heat', 'cool', 'vent', 'fog', 'co2_inj'} (0~100 %)
        params: GreyboxParams
        dt: 적분 스텝 [초]

    Returns:
        (T_new, RH_new, CO2_new)
    """
    def deriv(s):
        return _ode(s, ext, cmds, params)

    # 적분 안정화: 환기 등으로 이완(relaxation) rate 가 빠르면(시정수 ≪ dt) 단일 RK4
    # 스텝이 불안정해져 RH/CO2 가 발산·클램프(예: RH→0)된다. 물리식은 그대로 두고,
    # 가장 빠른 이완 rate 기준으로 dt 를 서브스텝으로 분할해 정확·안정하게 적분한다.
    n_sub = _substeps_for_stability(ext, cmds, params, dt)
    h = dt / n_sub
    T_n, RH_n, CO2_n = T_int, RH_int, CO2_int
    for _ in range(n_sub):
        s = (T_n, RH_n, CO2_n)
        k1 = deriv(s)
        k2 = deriv(_add(s, _scale(k1, h / 2)))
        k3 = deriv(_add(s, _scale(k2, h / 2)))
        k4 = deriv(_add(s, _scale(k3, h)))
        T_n   = T_n   + h / 6 * (k1[0] + 2*k2[0] + 2*k3[0] + k4[0])
        RH_n  = RH_n  + h / 6 * (k1[1] + 2*k2[1] + 2*k3[1] + k4[1])
        CO2_n = CO2_n + h / 6 * (k1[2] + 2*k2[2] + 2*k3[2] + k4[2])

    # 물리 범위 클램프
    T_n   = max(-10.0, min(60.0,   T_n))
    RH_n  = max(0.0,   min(100.0, RH_n))
    CO2_n = max(300.0, min(5000.0, CO2_n))
    return T_n, RH_n, CO2_n


def _substeps_for_stability(ext, cmds, p: GreyboxParams, dt: float) -> int:
    """가장 빠른 선형 이완 rate 기준으로 안정 서브스텝 수 산출.

    각 상태의 이완 계수 A [1/s] (X→X_e 로 수렴하는 rate):
      A_T   = (UA_eff + ρcp·vent_m3s) / (tau_T·UA_eff)
      A_RH  = K_RH_vent · vent_m3s
      A_CO2 = vent_m3s / tau_co2
    명시적 RK4 안정영역(A·h ≲ 0.25)을 만족하도록 n = ceil(A_max·dt/0.25), [1,600] 클램프.
    """
    vent_m3s = max(p.m_vent_coef, 0.0) * (cmds.get('vent', 0.0) / 100.0)
    thermal_mass = max(p.tau_T * p.UA_eff, 1.0)
    a_t = (p.UA_eff + RHO_CP_AIR * vent_m3s) / thermal_mass
    a_rh = p.K_RH_vent * vent_m3s
    tau_co2 = max(p.tau_T * 0.5, 60.0)
    a_co2 = vent_m3s / tau_co2
    a_max = max(a_t, a_rh, a_co2, 1e-9)
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
    """H 스텝 lookahead 예측.

    Returns: [(T, RH, CO2)] 길이 H
    """
    trajectory = []
    T, RH, CO2 = T_int, RH_int, CO2_int
    for ext, cmds in zip(ext_seq, cmds_seq):
        T, RH, CO2 = step(T, RH, CO2, ext, cmds, params, dt)
        trajectory.append((T, RH, CO2))
    return trajectory


# ── ODE 내부 구현 ─────────────────────────────────────────────────────────────

def _ode(
    state: Tuple[float, float, float],
    ext: dict,
    cmds: dict,
    p: GreyboxParams,
) -> Tuple[float, float, float]:
    T, RH, CO2 = state
    T_e   = ext.get('T_ext',   20.0)
    RH_e  = ext.get('RH_ext',  60.0)
    CO2_e = ext.get('CO2_ext', 400.0)
    solar = ext.get('solar',    0.0)

    cmd_heat    = cmds.get('heat',    0.0) / 100.0
    cmd_cool    = cmds.get('cool',    0.0) / 100.0
    cmd_vent    = cmds.get('vent',    0.0) / 100.0
    cmd_fog     = cmds.get('fog',     0.0) / 100.0
    cmd_co2_inj = cmds.get('co2_inj', 0.0) / 100.0

    # ── 온도 수지 dT/dt [K/s] ──────────────────────────────────────────────
    # 열용량 [J/K] = tau_T [s] × UA_eff [W/K] = ρVcp
    thermal_mass = max(p.tau_T * p.UA_eff, 1.0)

    # 외피 열손실 / 획득 [W]
    Q_envelope = p.UA_eff * (T_e - T)
    # 일사 수열 [W]
    Q_solar = p.alpha_sol * solar
    # 난방·냉방 [W] — Q_heat/Q_cool 단위: W (at 100%, cmd 는 0~1 분율)
    Q_hvac = (p.Q_heat * cmd_heat - p.Q_cool * cmd_cool)
    # 환기 [W]: 외내부 온도차 × 환기 질량유량
    vent_m3s = p.m_vent_coef * cmd_vent   # m³/s
    Q_vent = RHO_CP_AIR * vent_m3s * (T_e - T)
    # 증발 냉각 (포그) [W]
    Q_fog = -p.m_fog_evap * cmd_fog
    # 작물 증산 열흡수 [W] (음수: 냉각)
    Q_plant = -p.Q_plant_base

    # dT = ΣQ / (ρVcp) [K/s]
    dT = (Q_envelope + Q_solar + Q_hvac + Q_vent + Q_fog + Q_plant) / thermal_mass

    # ── 습도 수지 dRH/dt [%/s] ────────────────────────────────────────────
    # 환기로 외기 습도 끌어당김
    dRH_vent = p.K_RH_vent * vent_m3s * (RH_e - RH)
    # 포그 가습
    dRH_fog = 0.05 * p.m_fog_evap * cmd_fog
    # 온도 변화에 따른 RH 변동 (이상기체 근사: dRH ≈ -RH/T × dT × T에서 무시)
    dRH = dRH_vent + dRH_fog

    # ── CO₂ 수지 dCO₂/dt [ppm/s] ─────────────────────────────────────────
    # 환기로 외기 CO₂ 수렴
    tau_co2 = max(p.tau_T * 0.5, 60.0)
    dCO2_vent = (CO2_e - CO2) * vent_m3s / tau_co2
    # CO₂ 주입
    dCO2_inj = p.K_CO2_inj * cmd_co2_inj
    dCO2 = dCO2_vent + dCO2_inj

    return dT, dRH, dCO2


def _add(a, b):
    return tuple(x + y for x, y in zip(a, b))


def _scale(a, s):
    return tuple(x * s for x in a)
