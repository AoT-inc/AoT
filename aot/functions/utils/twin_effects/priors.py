# coding=utf-8
"""장치 정격 → 그레이박스 사전값 (설계서 §4 ⚠).

`GreyboxParams.from_capacity_meta` 는 `Q_heat`·`Q_cool`·`m_fog_evap`·`K_CO2_inj` 를 채우지 않아 기본값이 그대로 남는다.
채널 값(0~100 %)은 "설치 정격 합 대비 가동률"로 합쳐지므로(`aggregate.merge`), 이 계수들이 **정격 합**이어야 맞다.

| 계수 | 식 | 신뢰 |
|---|---|---|
| `Q_heat` [W] | Σ 정격 kW(열) × 1000 | 물리 |
| `Q_cool` [W] | 같음 | 물리 |
| `K_CO2_inj` [ppm/s] | Σ kg/h ÷ 3600 ÷ (1.83 kg/m³ × 부피) × 1e6 | 물리(부피를 알 때) |
| `m_fog_evap` [W] | Σ 유량 kg/s × 증발 효율 × 잠열 | **상한** — 실제 증발은 공기의 포화 여유에 막혀 이보다 작다. 단계 시험으로 확인 전에는 쓰지 않는다 |

모르는 정격은 건너뛴다(그 계수를 돌려주지 않는다 — 기본값을 쓰고 호출자가 "모름"으로 표시한다).
"""
from __future__ import annotations

from typing import Dict, Mapping, Optional, Sequence

from . import catalog as C
from .aggregate import Device

CO2_KG_M3 = 1.83            # 20 °C, 1 atm — sim/plant.py 와 같은 값
L_V_J = 2.45e6              # J/kg — greybox/model.py `L_V_J` 와 같은 값(시험이 맞춰 본다)
DEFAULT_FOG_ETA = 0.9       # 증발 효율을 모를 때. 습윤형 노즐은 이보다 낮다 → 상한으로만 쓴다


def _sum(devs: Sequence[Device], channel: str, key: str) -> Optional[float]:
    vals = [float(d.ratings[key]) for d in devs
            if C.row_for(d.kind).channel == channel and d.ratings.get(key) not in (None, 0)]
    return sum(vals) if vals else None


def grey_priors(devices: Sequence[Device], volume_m3: Optional[float] = None) -> Dict[str, Mapping[str, object]]:
    """{계수: {value, basis}} — basis 는 'physical' | 'upper_bound'. 모르는 계수는 빠진다."""
    out: Dict[str, Mapping[str, object]] = {}
    kw = _sum(devices, "heat", "rated_kW_thermal")
    if kw:
        out["Q_heat"] = {"value": kw * 1000.0, "basis": "physical"}
    kw = _sum(devices, "cool", "rated_kW_thermal")
    if kw:
        out["Q_cool"] = {"value": kw * 1000.0, "basis": "physical"}
    kg_h = _sum(devices, "co2_inj", "co2_kg_h")
    if kg_h and volume_m3 and volume_m3 > 0:
        out["K_CO2_inj"] = {"value": kg_h / 3600.0 / (CO2_KG_M3 * volume_m3) * 1e6, "basis": "physical"}
    lpm = _sum(devices, "fog", "fog_flow_lpm")
    if lpm:
        eta = [float(d.ratings.get("fog_eta")) for d in devices
               if C.row_for(d.kind).channel == "fog" and d.ratings.get("fog_eta")]
        e = sum(eta) / len(eta) if eta else DEFAULT_FOG_ETA
        out["m_fog_evap"] = {"value": lpm / 60.0 * e * L_V_J, "basis": "upper_bound"}
    return out
