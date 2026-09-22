# coding=utf-8
"""
env_control/energy.py — 장치 전력(kW)과 종류별 단가. PI 비용 순서와 MPC 에너지 항이 함께 쓴다.

## 어느 값을 쓰나 (우선순위)

1. **전기 kW** — 출력 채널의 전기소모량(`amps`) × 시스템 사용 전압(`Misc.output_usage_volts`)
   / 1000. 출력 사용량(kWh) 통계와 같은 값이다. 에너지 **비용**은 전기로 낸다.
2. 설비 정격(`capacity_meta['rated_kW_thermal']`) — 시설 도면에 적힌 값. 난방기는 **열
   출력**이라 전기 소모와 다를 수 있다(기름 보일러 등) — 전기 값이 없을 때만.
3. 종류별 기본값 `KIND_DEFAULT_KW`.

⚠ 한 곳에서만 고른다 — PI 의 비용 순서와 MPC 의 에너지 항이 다른 값을 쓰면 두 엔진이
  같은 장치의 비용을 다르게 알아 전환 때 동작이 갈린다.
"""

from __future__ import annotations

KIND_DEFAULT_KW = {
    'heater':       5.0,
    'cooler':       2.5,
    'co2_injector': 0.5,
    'fogger':       0.3,
    'lighting':     2.0,
    'exhaust_fan':  0.75,
    'intake_fan':   0.75,
    'circulation_fan': 0.2,
    'opening':      0.1,   # 모터 소비전력
    'shade':        0.1,
    'curtain':      0.1,
}

# 종류별 기본 단가(전기 1 kWh = 1.0 기준의 상대값, 결정 D4). CO₂ 주입은 가스 값이 든다.
KIND_UNIT_PRICE = {
    'co2_injector': 2.0,
}


def actuator_kw(kind: str, capacity_meta: dict | None) -> float:
    """장치 한 대의 kW(위 우선순위)."""
    cap = capacity_meta or {}
    for key in ('elec_kw', 'rated_kW_thermal'):
        try:
            v = float(cap.get(key) or 0.0)
        except (TypeError, ValueError):
            v = 0.0
        if v > 0.0:
            return v
    return float(KIND_DEFAULT_KW.get(kind, 1.0))


def unit_price(kind: str) -> float:
    return float(KIND_UNIT_PRICE.get(kind, 1.0))


def electric_kw(amps, volts) -> float:
    """전류(A)·전압(V) → kW. 모르면 0."""
    try:
        a, v = float(amps or 0.0), float(volts or 0.0)
    except (TypeError, ValueError):
        return 0.0
    return a * v / 1000.0 if a > 0.0 and v > 0.0 else 0.0


__all__ = ['KIND_DEFAULT_KW', 'KIND_UNIT_PRICE', 'actuator_kw', 'unit_price', 'electric_kw']
