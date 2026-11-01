# coding=utf-8
"""
facility_twin/model.py — 그레이박스 v3 + 숨은 열질량 Tm + 느린 파라미터 2개.

상태 z = [T, AH, CO2, Tm, lnθ_UA, lnθ_leak, lnθ_sol, lnθ_vent, lnθ_tr]  (계약 §3 ①~⑦ + 일사·환기·증산 배율)

    T     실내 기온 [°C]                    측정
    AH    절대습도 [g/m³]                   측정(RH 로 환산)      ← 그레이박스는 kg/m³ 로 적분, 밖은 g/m³ 로 다뤄 조건수를 낮춘다
    CO2   [ppm]                             측정
    Tm    열질량(바닥·작물·구조) 온도 [°C]   숨은 상태
    lnθ_UA    외피 열손실 배율의 로그(0 = 기준)  느린 파라미터 — 기준 UA_eff 는 `GreyboxParams`
    lnθ_leak  누기·틈새 환기 배율의 로그(0 = 기준)  느린 파라미터 — 기준 누기는 `FacilityConfig.leak_ach`
    lnθ_sol   일사 수열 배율의 로그(0 = 기준 `alpha_sol`)  느린 파라미터 — 피복 투과율·오염·그늘이 여기로 모인다
    lnθ_vent  환기 능력 배율의 로그(0 = 기준 `m_vent_coef`)  느린 파라미터 — 개구부 유효 면적·방충망 막힘
    lnθ_tr    증산 배율의 로그(0 = 기준 `k_transp`)  느린 파라미터 — 잎 면적(생육)·작물 종류. 기준값이 시설 크기를 몰라 100배도 어긋난다

⚠ 계약 §3 은 ⑥⑦(UA·누기)만 적었다. 일사·환기 배율은 plant 독립 참값 검증(plans/twin_fac)에서 낮 편향(-4~-5 °C)의
  주범이라, 증산 배율은 습도(RH 1 h 선행 13 %p)의 주범이라 추가했다 — 시설 사전값(capacity_meta)의 가장 큰 오차가 이 둘이다. 밖으로는 안 나간다(진단 P3 로만).

## 그레이박스와의 관계 (원칙 3: 모델은 한 벌)

공기·수분·CO₂ 수지는 `greybox.model._ode` 를 **그대로 부른다**. 이 모듈이 더하는 것은 그 도함수에 **더하는 항**뿐이다:

- θ_UA : `UA_eff` 만 곱하고 열용량(`tau_T·UA_eff`)은 그대로 둔다 — 외피를 바꾸면 UA 가 변하지 열용량이 변하지 않는다.
- 누기 : 환기량 `V̇` 에 선형으로 들어가는 항이라 같은 식(열·수증기·CO₂ 혼합)을 `L = θ_leak·leak_ach·V/3600` 로 더한다.
- Tm : 공기 ↔ 열질량 결합 `k_m (Tm − T)` 을 공기 열수지에, 반대 부호를 열질량 열수지에 넣는다.
  `Tm = T` 이면 더한 항이 모두 0(누기만 빼고)이라 Tm 이 없는 그레이박스와 같은 식이다.

열질량 용량·결합은 그레이박스 열용량 `M = tau_T·UA_eff [J/K]` 에 대한 배수로 둔다(`FacilityConfig`).
시설을 모르면 맞는 값이 아니라 **가정값**이다 — 동기화가 θ_UA·θ_leak·Tm 으로 이를 흡수한다.
"""
from __future__ import annotations

import dataclasses
import math
from dataclasses import dataclass
from typing import Dict, Mapping, Optional, Sequence

import numpy as np

from aot.functions.utils.env_control.greybox import model as gb
from aot.functions.utils.env_control.greybox.params import GreyboxParams

MODEL_REV = 1       # env_twin_meta.model_rev (시설 모델 판. 더하는 식이 바뀌면 올린다)

I_T, I_AH, I_CO2, I_TM, I_LUA, I_LLK, I_LSOL, I_LVENT, I_LTR = range(9)
N_STATE = 9
STATE_NAMES = ("T", "AH", "CO2", "Tm", "lnUA", "lnLeak", "lnSol", "lnVent", "lnTr")
PARAM_NAMES = ("theta_UA", "theta_leak", "theta_sol", "theta_vent", "theta_tr")

KG_TO_G = 1000.0
LN_BOUND = math.log(10.0)         # 배율은 기준의 1/10 ~ 10 배 안 — 그레이박스 환기 계수(개구 면적×0.5)는 독립 참값보다
#                                    3 배쯤 크게 나와 옛 한계 1/3 에 붙었다(plans/twin_fac)
LN_BOUND_TR = math.log(300.0)     # 증산 기준값은 시설 크기를 모른다 — 범위를 넓게


@dataclass(frozen=True)
class FacilityConfig:
    """동기화가 학습하지 않는 가정값. 시설 설정(`TargetSpec.options`)이 덮어쓴다."""
    leak_ach: float = 0.5            # 기준 누기 [회/h] (θ_leak = 1 일 때)
    mass_cap_ratio: float = 8.0      # 열질량 열용량 / 그레이박스 열용량 M
    mass_coupling_ratio: float = 0.6   # 공기 ↔ 열질량 결합 k_m / UA_eff
    # 실내에서 허용하는 물리 범위(필터가 이 안으로 자른다)
    t_range: tuple = (-15.0, 55.0)
    co2_range: tuple = (250.0, 5000.0)

    @classmethod
    def from_options(cls, opts: Mapping[str, object]) -> "FacilityConfig":
        kw = {}
        for f in dataclasses.fields(cls):
            if f.name in opts:
                kw[f.name] = opts[f.name]
        return cls(**kw)


class FacilityTwinModel:
    """결정론 전파 `propagate` 와 관측식 `observe`. 확률은 모른다 — 필터·앙상블이 만든다."""

    def __init__(self, params: GreyboxParams, cfg: FacilityConfig = FacilityConfig()):
        self.p0 = params
        self.cfg = cfg
        self.V = gb._volume(params)
        self.M = max(params.tau_T * params.UA_eff, 1.0)          # 그레이박스 열용량 [J/K]
        self.C_m = cfg.mass_cap_ratio * self.M
        self.leak0 = cfg.leak_ach * self.V / 3600.0              # θ_leak = 1 일 때 누기 [m³/s]
        self._peff_cache = {}

    # ── 상태 변환 ───────────────────────────────────────────────────────────
    @staticmethod
    def ah_from_th(T: float, RH: float) -> float:
        """(T, RH) → AH [g/m³]."""
        return gb._ah(T, gb._vp(T, RH)) * KG_TO_G

    @staticmethod
    def rh_from_state(T: float, AH_g: float) -> float:
        return max(0.0, min(100.0, 100.0 * gb._e_of(T, AH_g / KG_TO_G) / gb._svp(T)))

    def init_state(self, T: float, RH: float, CO2: float, Tm: float = None) -> np.ndarray:
        return np.array([T, self.ah_from_th(T, RH), CO2, T if Tm is None else Tm, 0.0, 0.0, 0.0, 0.0, 0.0], dtype=float)

    def observe(self, z: np.ndarray) -> np.ndarray:
        """h(z) = [T, RH, CO2]."""
        return np.array([z[I_T], self.rh_from_state(z[I_T], z[I_AH]), z[I_CO2]])

    def derived(self, z: np.ndarray) -> Dict[str, float]:
        T, RH = float(z[I_T]), self.rh_from_state(z[I_T], z[I_AH])
        vpd = gb._svp(T) * (1.0 - RH / 100.0)
        return {"T": T, "RH": RH, "VPD": vpd, "CO2": float(z[I_CO2])}

    # ── 도함수 ──────────────────────────────────────────────────────────────
    def _params_eff(self, lua: float, lsol: float = 0.0, lvent: float = 0.0, ltr: float = 0.0) -> GreyboxParams:
        key = (round(lua, 4), round(lsol, 4), round(lvent, 4), round(ltr, 4))
        p = self._peff_cache.get(key)
        if p is None:
            th = math.exp(lua)
            # 열용량 M = tau_T·UA 는 그대로 — UA 만 θ 배.
            p = dataclasses.replace(self.p0, UA_eff=self.p0.UA_eff * th, tau_T=self.p0.tau_T / th,
                                    alpha_sol=self.p0.alpha_sol * math.exp(lsol),
                                    m_vent_coef=self.p0.m_vent_coef * math.exp(lvent),
                                    k_transp=self.p0.k_transp * math.exp(ltr))
            if len(self._peff_cache) > 256:
                self._peff_cache.clear()
            self._peff_cache[key] = p
        return p

    def _deriv(self, s: np.ndarray, ext: Mapping[str, float], cmds: Mapping[str, float],
               p: GreyboxParams, L: float, k_m: float) -> np.ndarray:
        T, AH_g, CO2, Tm = s[0], s[1], s[2], s[3]
        dT, dAH, dCO2 = gb._ode((T, AH_g / KG_TO_G, CO2), ext, cmds, p)   # 그레이박스 그대로
        T_e = ext.get("T_ext", 20.0)
        RH_e = ext.get("RH_ext", 60.0)
        CO2_e = ext.get("CO2_ext", 400.0)
        AH_e = gb._ah(T_e, gb._vp(T_e, RH_e))
        # 누기 — 환기량에 선형인 항을 같은 식으로
        dT += gb.RHO_CP_AIR * L * (T_e - T) / self.M
        dAH += -L * (AH_g / KG_TO_G - AH_e) / self.V
        dCO2 += L / self.V * (CO2_e - CO2)
        # 열질량 결합
        dT += k_m * (Tm - T) / self.M
        dTm = k_m * (T - Tm) / self.C_m
        return np.array([dT, dAH * KG_TO_G, dCO2, dTm, 0.0, 0.0, 0.0, 0.0, 0.0])

    def propagate(self, z: np.ndarray, ext: Mapping[str, float], cmds: Mapping[str, float],
                  dt: float) -> np.ndarray:
        """한 스텝(RK4 + 안정 서브스텝). 느린 파라미터 두 칸은 그대로 둔다. 입력 z 는 바꾸지 않는다."""
        p = self._params_eff(float(z[I_LUA]), float(z[I_LSOL]), float(z[I_LVENT]), float(z[I_LTR]))
        L = self.leak0 * math.exp(float(z[I_LLK]))
        k_m = self.cfg.mass_coupling_ratio * p.UA_eff
        vent = gb._vent_m3s(ext, cmds, p) + L
        a_t = (p.UA_eff + gb.RHO_CP_AIR * vent + k_m) / self.M
        a_m = k_m / self.C_m
        a_x = vent / self.V
        a_max = max(a_t, a_m, a_x, 1e-9)
        n = max(1, min(600, int(a_max * dt / 0.25) + 1))
        h = dt / n
        s = np.array(z, dtype=float)
        lo_t, hi_t = self.cfg.t_range
        lo_c, hi_c = self.cfg.co2_range
        for _ in range(n):
            k1 = self._deriv(s, ext, cmds, p, L, k_m)
            k2 = self._deriv(s + 0.5 * h * k1, ext, cmds, p, L, k_m)
            k3 = self._deriv(s + 0.5 * h * k2, ext, cmds, p, L, k_m)
            k4 = self._deriv(s + h * k3, ext, cmds, p, L, k_m)
            s = s + h / 6.0 * (k1 + 2 * k2 + 2 * k3 + k4)
            s[I_T] = min(hi_t, max(lo_t, s[I_T]))
            s[I_TM] = min(hi_t, max(lo_t, s[I_TM]))
            # 포화를 넘는 수증기는 맺힌다 — 그레이박스와 같은 규칙
            s[I_AH] = max(0.0, min(s[I_AH], gb._ah(s[I_T], gb._svp(s[I_T])) * KG_TO_G))
            s[I_CO2] = min(hi_c, max(lo_c, s[I_CO2]))
        return s

    def predict(self, z: np.ndarray, ext_fn, cmds, t0: float,
                step_s: float, n_steps: int, dt_s: float = 60.0,
                rng: Optional[np.random.Generator] = None,
                noise_sd_per_sqrt_h: Optional[Sequence[float]] = None) -> np.ndarray:
        """z 에서 출발해 `step_s` 격자 `n_steps` 점(k=0 포함)의 상태 궤적 (n_steps, 9).
        `ext_fn(t)` 는 외기 dict. `cmds` 는 dict(현재 설정 유지 — 정책 0) 또는 `t → dict`(검증에서 실제 명령을 줄 때).
        `rng` 와 `noise_sd_per_sqrt_h`(앞 네 상태 T·AH·CO2·Tm 의 √h 당 표준편차)를 주면 매 스텝 모델 오차 잡음을 더한다 —
        앙상블 멤버가 필터 사후 하나만으로 갈라서 띠가 너무 좁아지는 것을 막는다."""
        cmd_fn = cmds if callable(cmds) else (lambda _t: cmds)
        sub = max(1, int(math.ceil(step_s / dt_s)))
        h = step_s / sub
        out = np.empty((n_steps, N_STATE))
        s = np.array(z, dtype=float)
        out[0] = s
        t = t0
        for k in range(1, n_steps):
            for _ in range(sub):
                s = self.propagate(s, ext_fn(t), cmd_fn(t), h)
                if rng is not None and noise_sd_per_sqrt_h is not None:
                    s[:4] += np.asarray(noise_sd_per_sqrt_h[:4]) * math.sqrt(h / 3600.0) * rng.standard_normal(4)
                    s[I_AH] = max(0.0, s[I_AH])
                t += h
            out[k] = s
        return out
