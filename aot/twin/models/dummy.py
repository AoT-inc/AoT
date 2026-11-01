# coding=utf-8
"""자리표시자 모델 — 뼈대의 왕복(읽기 → 예측 → 쓰기 → 유효기한)만 검증한다. 물리적 의미는 없다.

시설: 실내가 외기를 향해 지수적으로 끌려간다. 노지: 단일 버킷 토양수분이 마르고 비로 찬다.
진짜 모델(그레이박스 v3 · 노지 물 수지)은 이 인터페이스로 `registry.register()` 한다.
"""
from __future__ import annotations

import math
from typing import Dict, Mapping, Sequence

from ..types import TargetSpec
from . import registry

NAN = float("nan")


def _f(d: Mapping[str, float], k: str, default: float) -> float:
    v = d.get(k, NAN)
    return default if v is None or (isinstance(v, float) and math.isnan(v)) else float(v)


def _svp(t: float) -> float:       # kPa (Tetens)
    return 0.6108 * math.exp(17.27 * t / (t + 237.3))


class DummyFacilityModel:
    kind = "facility"
    model_rev = 0
    state_names = ("T", "RH", "CO2")
    param_names = ("tau_s",)
    dt_nominal_s = 60.0
    required_inputs = ("T_int", "RH_int")
    # 초기 상태·외기 예보에 넣는 표준편차 (뼈대가 앙상블을 만들 때 쓴다)
    noise_sigma = {"T": 0.5, "RH": 3.0, "CO2": 20.0}
    tau_s = 6 * 3600.0

    def init_state(self, target: TargetSpec, t0: float, obs: Mapping[str, float]) -> Dict[str, float]:
        return {"T": _f(obs, "T_int", 20.0), "RH": _f(obs, "RH_int", 60.0), "CO2": _f(obs, "CO2_int", 420.0)}

    def step(self, x, u, w, dt_s):
        a = dt_s / self.tau_s
        return {"T": x["T"] + a * (_f(w, "T_ext", x["T"]) - x["T"]),
                "RH": min(100.0, max(0.0, x["RH"] + a * (_f(w, "RH_ext", x["RH"]) - x["RH"]))),
                "CO2": x["CO2"] + a * (_f(w, "CO2_ext", 420.0) - x["CO2"])}

    def observe(self, x, name):
        return {"T_int": x["T"], "RH_int": x["RH"], "CO2_int": x["CO2"]}.get(name, NAN)

    def derived(self, x):
        vpd = _svp(x["T"]) * (1.0 - x["RH"] / 100.0)
        return {"T": x["T"], "RH": x["RH"], "VPD": vpd, "CO2": x["CO2"]}

    def risks(self, traj: Sequence[Mapping[str, float]], target: TargetSpec):
        o = target.options
        hi, lo, rh_hi = float(o.get("T_high", 32.0)), float(o.get("T_low", 5.0)), float(o.get("RH_high", 90.0))

        def dew(t, rh):
            g = math.log(max(rh, 1e-3) / 100.0) + 17.27 * t / (t + 237.3)
            return 237.3 * g / (17.27 - g)

        return {"heat": [float(s["T"] > hi) for s in traj],
                "frost": [float(s["T"] < lo) for s in traj],
                "humid": [float(s["RH"] > rh_hi) for s in traj],
                "condensation": [float(s["T"] - dew(s["T"], s["RH"]) < 1.0) for s in traj]}


class DummyFieldModel:
    kind = "field"
    model_rev = 0
    state_names = ("theta",)
    param_names = ("dry_rate",)
    dt_nominal_s = 86400.0
    required_inputs = ("theta",)
    noise_sigma = {"theta": 1.5}       # %p
    dry_per_day = 1.0                  # %p/일
    fc, wp = 40.0, 15.0

    def init_state(self, target, t0, obs):
        return {"theta": _f(obs, "theta", 30.0)}

    def step(self, x, u, w, dt_s):
        day = dt_s / 86400.0
        th = x["theta"] - self.dry_per_day * day + 0.8 * _f(w, "rain_mm", 0.0) + _f(u, "irr_mm", 0.0)
        return {"theta": min(60.0, max(self.wp - 5.0, th))}

    def observe(self, x, name):
        return x["theta"] if name == "theta" else NAN

    def derived(self, x):
        th = x["theta"]
        ks = min(1.0, max(0.0, (th - self.wp) / (0.6 * (self.fc - self.wp) + 1e-9)))
        return {"theta_root": th, "Ks": ks}

    def risks(self, traj, target):
        return {"water_deficit": [float(s["Ks"] < 1.0) for s in traj],
                "water_deficit_severe": [float(s["Ks"] < 0.7) for s in traj]}


registry.register("dummy_facility", "facility", DummyFacilityModel)
registry.register("dummy_field", "field", DummyFieldModel)
