# coding=utf-8
"""
greybox/params.py — 시설 단위 열·물 수지 모델 파라미터.

물리적 의미가 있는 10개 계수로 구성. EKF/batch fit 으로 학습.
prior: facility_integration.capacity_meta 기반 초기값.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict


@dataclass
class GreyboxParams:
    """시설 열·수분·CO₂ 수지 ODE 파라미터.

    학습 대상 (10개):
      UA_eff      : 외피 열관류율×면적 합계 [W/K]  (U_eff × envelope_m2)
      alpha_sol   : 일사 수열 계수 (지붕 면적·투과율 포함) [W/(W/m²)]
      Q_heat      : 난방기 최대 출력 [W/% 단위 — cmd_pct 에 곱함]
      Q_cool      : 냉방기 최대 출력 [W/%]
      m_vent_coef : 환기 환기량 계수 [m³/s·% — 개구부 면적 기반]
      m_fog_evap  : 포그 증발 냉각 출력 [W/%]
      Q_plant_base: 작물 증산 열 흡수 기저값 [W]
      tau_T       : 온도 시정수 [s] (ρVcp 역수에 해당)
      K_RH_vent   : 환기 RH 변화 계수 [%·s/(m³·%)]
      K_CO2_inj   : CO₂ 주입 계수 [ppm/s/%]

    bounds: (min, max) — EKF 상태 클램프용
    """

    # ── 학습 파라미터 (물리 기반 초기값) ──────────────────────────────────────
    # UA_eff: 외피 열관류율×면적 [W/K]. 소형 온실(300m²×4W/m²K) ≈ 1200
    UA_eff:       float = 1200.0
    # alpha_sol: 지붕 일사 수열 계수 [W/(W/m²)]. 지붕50m²×투과0.8×흡수0.5 = 20
    alpha_sol:    float = 20.0
    # Q_heat/Q_cool: 최대 출력 [W at 100%]. 5kW 히터 / 3kW 냉방기
    Q_heat:       float = 5000.0
    Q_cool:       float = 3000.0
    # m_vent_coef: 환기 유량 계수 [m³/s per unit cmd(0~1)]. 100%시 0.5m³/s
    m_vent_coef:  float = 0.5
    # m_fog_evap: 포그 증발 냉각 출력 [W at 100%]
    m_fog_evap:   float = 500.0
    # Q_plant_base: 작물 증산 열흡수 기저값 [W]
    Q_plant_base: float = 200.0
    # tau_T: 온도 시정수 [s] = ρVcp / UA_eff. 200m³ × 1200J/m³K / 1200W/K = 200s
    tau_T:        float = 200.0
    # K_RH_vent: 환기 RH 변화 계수 [%/(m³/s · %차이 · s)]
    K_RH_vent:    float = 0.05
    # K_CO2_inj: CO₂ 주입 계수 [ppm/s at 100%]
    K_CO2_inj:    float = 2.0

    # ── 수렴 상태 ─────────────────────────────────────────────────────────────
    n_updates: int = 0
    rmse_T:    float = 999.0
    rmse_RH:   float = 999.0

    # ── 물리 범위 (클램프) ─────────────────────────────────────────────────────
    BOUNDS: Dict[str, tuple] = field(default_factory=lambda: {
        'UA_eff':       (10.0,    20000.0),
        'alpha_sol':    (0.0,     2000.0),
        'Q_heat':       (0.0,     100000.0),
        'Q_cool':       (0.0,     50000.0),
        'm_vent_coef':  (0.001,   10.0),
        'm_fog_evap':   (0.0,     5000.0),
        'Q_plant_base': (0.0,     5000.0),
        'tau_T':        (30.0,    7200.0),
        'K_RH_vent':    (0.001,   2.0),
        'K_CO2_inj':    (0.01,    50.0),
    })

    def clamp(self):
        """모든 파라미터를 물리 범위 내로 클램프."""
        for k, (lo, hi) in self.BOUNDS.items():
            v = getattr(self, k, None)
            if v is not None:
                setattr(self, k, max(lo, min(hi, v)))

    @classmethod
    def from_capacity_meta(cls, meta: dict) -> 'GreyboxParams':
        """facility capacity_meta 로부터 물리 기반 초기값 산출."""
        p = cls()
        volume = float(meta.get('volume_m3') or 0.0)
        u_eff  = float(meta.get('u_effective') or 0.0)
        env_m2 = float(meta.get('envelope_m2') or 0.0)
        trans  = float(meta.get('transmittance') or 0.80)

        if u_eff > 0 and env_m2 > 0:
            p.UA_eff = u_eff * env_m2

        # 지붕 면적 근사 (없으면 envelope의 40%)
        roof_m2 = float(meta.get('roof_m2') or env_m2 * 0.4)
        p.alpha_sol = roof_m2 * trans * 0.5   # 반사·식물 흡수 절반 가정

        if volume > 0:
            # tau_T = ρVcp / UA_eff  (공기: ρcp≈1200 J/m³K)
            p.tau_T = max(60.0, 1200.0 * volume / max(p.UA_eff, 1.0))

        vent_m2 = float(meta.get('vent_open_m2') or 0.0)
        if vent_m2 > 0:
            p.m_vent_coef = vent_m2 * 0.5   # Bernoulli 0.5 근사

        return p

    def to_dict(self) -> dict:
        keys = ['UA_eff', 'alpha_sol', 'Q_heat', 'Q_cool', 'm_vent_coef',
                'm_fog_evap', 'Q_plant_base', 'tau_T', 'K_RH_vent', 'K_CO2_inj',
                'n_updates', 'rmse_T', 'rmse_RH']
        return {k: getattr(self, k) for k in keys}

    @classmethod
    def from_dict(cls, d: dict) -> 'GreyboxParams':
        p = cls()
        for k in ['UA_eff', 'alpha_sol', 'Q_heat', 'Q_cool', 'm_vent_coef',
                  'm_fog_evap', 'Q_plant_base', 'tau_T', 'K_RH_vent', 'K_CO2_inj',
                  'n_updates', 'rmse_T', 'rmse_RH']:
            if k in d:
                setattr(p, k, d[k])
        return p
