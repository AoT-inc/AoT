# coding=utf-8
"""
greybox/params.py — 시설 단위 열·물 수지 모델 파라미터.

물리적 의미가 있는 10개 계수로 구성. EKF/batch fit 으로 학습.
prior: facility_integration.capacity_meta 기반 초기값.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Optional


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
    # ── 모델 v2 (2026-09-22, 계획서 env-mpc-reinforcement A 단계) ──────────
    # k_transp: 증산 [kg/s per kPa VPD] at 일사 기준(500 W/m²). 밤에는 기저 15 %.
    #   1,000 m² 잎 면적 · 0.2 L/m²/h 규모 ≈ 5.6e-5 kg/s — kPa 당으로 약 3e-5.
    k_transp:     float = 3.0e-5
    # k_photo: 광합성 CO₂ 흡수 [ppm/s] at 일사 500 W/m²·CO₂ 포화. 온실 약 0.05.
    k_photo:      float = 0.05
    # ⚠ 아래 둘은 **학습하지 않는다** — 시설이 안다.
    # volume_m3: 공기 체적 [m³]. 수분·CO₂ 수지의 분모. None 이면 열용량에서 어림한다
    #   (구조체·토양 열용량이 섞여 과대 — 알면 반드시 채운다).
    volume_m3:    Optional[float] = None
    # tau_shade: 차광막을 다 쳤을 때 일사 투과율. 시설 값이 정본(_facility_shade_transmittance).
    tau_shade:    float = 0.5
    # ── 모델 v3 (2026-09-22, E 단계) — 보온커튼. 역시 **학습하지 않는다**(커튼은 늘
    #   밤에 닫히고 낮에 걷혀 외기·일사와 함께 움직인다 — 데이터로 떼어낼 수 없다).
    # curtain_ua_saving: 다 닫았을 때 외피 열손실(UA)을 줄이는 비율. 에너지 스크린 문헌값
    #   30~50 %의 보수적인 쪽.
    curtain_ua_saving: float = 0.35
    # tau_curtain: 다 닫았을 때 일사 투과율(보온 전용 막 기준).
    tau_curtain:  float = 0.8
    # model_version: 물리식 판. 식이 바뀌면 옛 판으로 학습한 값·KPI 는 다시 검증한다.
    model_version: int = 3

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
        'k_transp':     (0.0,     1.0e-2),
        'k_photo':      (0.0,     2.0),
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
            p.volume_m3 = volume
        for key, attr in (('curtain_u_saving', 'curtain_ua_saving'),
                          ('curtain_transmittance', 'tau_curtain')):
            v = meta.get(key)
            if v is not None and 0.0 <= float(v) <= 1.0:
                setattr(p, attr, float(v))
        tau_sh = meta.get('shade_transmittance')
        if tau_sh is not None and 0.0 < float(tau_sh) <= 1.0:
            p.tau_shade = float(tau_sh)

        vent_m2 = float(meta.get('vent_open_m2') or 0.0)
        if vent_m2 > 0:
            p.m_vent_coef = vent_m2 * 0.5   # Bernoulli 0.5 근사

        return p

    def to_dict(self) -> dict:
        return {k: getattr(self, k) for k in _PERSIST_KEYS}

    @classmethod
    def from_dict(cls, d: dict) -> 'GreyboxParams':
        p = cls()
        for k in _PERSIST_KEYS:
            if k in d and k != 'model_version':
                setattr(p, k, d[k])
        # 옛 판(버전 없음 = 1)으로 학습한 값: 열 계수는 물리적으로 여전히 쓸 만해
        # 초기값으로 남기되, 학습 횟수·오차는 새 식에서 다시 잰다 — 옛 오차로
        # 새 모델을 통과시키지 않는다(`_greybox_control_gate_ok`).
        if int(d.get('model_version') or 1) != p.model_version:
            p.n_updates = 0
            p.rmse_T = 999.0
            p.rmse_RH = 999.0
        return p


_PERSIST_KEYS = ('UA_eff', 'alpha_sol', 'Q_heat', 'Q_cool', 'm_vent_coef',
                 'm_fog_evap', 'Q_plant_base', 'tau_T', 'K_RH_vent', 'K_CO2_inj',
                 'k_transp', 'k_photo', 'volume_m3', 'tau_shade',
                 'curtain_ua_saving', 'tau_curtain', 'model_version',
                 'n_updates', 'rmse_T', 'rmse_RH')
