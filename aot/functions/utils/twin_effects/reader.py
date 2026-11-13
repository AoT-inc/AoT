# coding=utf-8
"""시설 통합 payload(`facility_integration.get_facility_integration`) → 효과 목록표의 `Device` (설계서 §3, 결정 2 = B).

코디네이터 로더(`env_coordinator_impl/_profile_loader_mixin.py::_reload_profiles`)는 같은 payload 에서 장치별 정격을 만든다.
운영 제어 코드를 건드리지 않으려고 이 모듈이 **읽는 규칙을 한 벌 더** 가진다. 두 벌이 어긋나지 않게 일치 시험
(`tests/test_reader_parity.py`)이 가짜 시설 하나에서 로더 결과와 이 모듈 결과를 견준다.

읽는 정격(로더의 규칙 그대로)

| 정격 | 규칙 |
|---|---|
| `area_m2` | 장치별 개구부 면적 `vent_openings_area_m2` > 0 이면 그것. 아니면 슬롯별: 천창/측창(`vent` 포함 슬롯)은 환기 면적을 슬롯 수로 나눈 몫(피팅 권위 모드가 아닐 때만), 보온커튼은 외피 면적, 차광막은 지붕 면적. 그래도 0 이면 도형 면적(`shape_areas`) |
| `rated_m3h` | 장치 값 > 종류 기본값(배기·흡기 3000, 순환 1500). 기본값이면 `sources` 가 `default` 로 적힌다 |
| `rated_kW_thermal` | 장치 값. 없으면 모름 — 전기 소비량으로 지어내지 않는다 |
| `fog_flow_lpm` | 노즐 요약의 `sprinkler_flow_lph / 60`. 없으면 모름(시설 전체 관수 유량으로 메우지 않는다). 물 회로의 공급 한계가 있으면 합이 그 아래로 내려오게 같은 비율로 낮춘다(`supply_lpm`) |
| `vent_form` | 개구부 형태(ridge/side) |

공급 한계는 이 모듈만 읽는다 — 코디네이터 로더는 물 회로를 모르므로 일치 시험은 `supply_lpm` 없이 견준다.

로더가 하는 두 가지는 하지 않는다: 구역(`bay_scope`) 비례 축소와 사용자가 자동 제어에서 뺀 장치 제외 — 트윈은 시설
전체를 본다. 습윤형 분무의 환경 제어 제외도 하지 않는다(트윈에서는 `fogger` 행으로 '잎 젖음 미반영' 표시).

순수 데이터 변환이다 — DB·Flask 를 import 하지 않는다(원격 트윈 노드가 import 해도 안전).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Mapping, Optional

from . import catalog as C
from .aggregate import Device

#: 로더의 `_KIND_DEFAULT_RATED_M3H` 와 같아야 한다 — 일치 시험이 맞춰 본다.
KIND_DEFAULT_RATED_M3H = {"exhaust_fan": 3000.0, "intake_fan": 3000.0, "circulation_fan": 1500.0}

#: 정격이 어디서 왔는지 — 화면이 '추정' 표시에 쓴다. `catalog.SRC_*` 와 같은 어휘.
FROM_DEVICE, FROM_GEOMETRY, FROM_DEFAULT, FROM_SUPPLY = C.SRC_DEVICE, C.SRC_GEOMETRY, C.SRC_DEFAULT, C.SRC_SUPPLY


@dataclass
class ReadResult:
    devices: List[Device] = field(default_factory=list)
    names: Dict[str, str] = field(default_factory=dict)                 # 장치 id → 이름
    sources: Dict[str, Dict[str, str]] = field(default_factory=dict)    # 장치 id → {정격 키: 출처}
    unknown: List[Dict[str, object]] = field(default_factory=list)      # 종류를 못 알아본 설비
    supply: Dict[str, object] = field(default_factory=dict)             # 물 회로 공급 사실(`water_net_link.facility_supply`)


def _num(v) -> float:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return 0.0
    return x if x == x and x > 0 else 0.0


def _area(ar: Mapping, kind: str, integ: Mapping, vent_fallback_per_slot: float,
          shape_area: Optional[float]):
    """(면적, 출처). 로더의 G1 면적 규칙."""
    cm = integ.get("capacity_meta") or {}
    g1 = _num(ar.get("vent_openings_area_m2"))
    slot_key = ar.get("slot_key") or ""
    if g1 > 0:
        return g1, FROM_GEOMETRY
    if "vent" in slot_key:
        area = vent_fallback_per_slot
    elif slot_key == "thermal_curtain":
        area = _num(cm.get("envelope_m2"))
    elif slot_key == "shade_curtain":
        area = _num((integ.get("computed") or {}).get("roof_m2"))
    else:
        area = 0.0
    if area > 0:
        return area, FROM_GEOMETRY
    if shape_area and shape_area > 0:                           # 로더는 면적이 0 일 때만 도형 면적을 쓴다
        return float(shape_area), FROM_GEOMETRY
    return 0.0, ""


def _limit_fog(out: ReadResult, supply_lpm: float) -> None:
    """분무 유량 합을 공급 한계 아래로 — 같은 회로를 나눠 쓰므로 수요 비례로 낮춘다(`water_net.balance` 와 같다)."""
    fog = [d for d in out.devices if d.ratings.get("fog_flow_lpm")]
    total = sum(d.ratings["fog_flow_lpm"] for d in fog)
    if total <= supply_lpm:
        return
    for d in fog:
        d.ratings["fog_flow_lpm"] *= supply_lpm / total
        out.sources[d.actuator_id]["fog_flow_lpm"] = FROM_SUPPLY


def devices_from_integration(integ: Mapping, shape_areas: Optional[Mapping[str, float]] = None,
                             supply_lpm: Optional[float] = None) -> ReadResult:
    """통합 payload → 장치 목록. `shape_areas` = {장치 id: 도형 면적 m²}, `supply_lpm` = 물 회로의 공급 한계 L/min (DB 쪽이 채우는 선택 입력)."""
    out = ReadResult()
    cm = integ.get("capacity_meta") or {}
    actuators = [a for a in (integ.get("actuators_resolved") or []) if a.get("output_uuid")]
    vent_source = cm.get("vent_open_source") or "none"
    per_slot = 0.0
    if "fittings" not in vent_source:                           # 피팅 권위 모드가 아닐 때만 균등 분할
        slots = [a for a in actuators if a.get("kind") == "opening" and a.get("slot_key")
                 and "vent" in (a.get("slot_key") or "")]
        per_slot = (_num(cm.get("vent_open_m2")) / len(slots)) if slots else 0.0
    shape_areas = shape_areas or {}
    for ar in actuators:
        uid, kind = ar["output_uuid"], ar.get("kind")
        out.names[uid] = ar.get("output_name") or uid[:8]
        if not kind:
            out.unknown.append({"actuator_id": uid, "name": out.names[uid],
                                "fitting_kind": ar.get("fitting_kind") or None})
            continue
        ratings: Dict[str, Optional[float]] = {}
        src: Dict[str, str] = {}
        area, a_src = _area(ar, kind, integ, per_slot, shape_areas.get(uid))
        if area > 0:
            ratings["area_m2"], src["area_m2"] = area, a_src
        m3h = _num(ar.get("rated_m3h"))
        if m3h > 0:
            ratings["rated_m3h"], src["rated_m3h"] = m3h, FROM_DEVICE
        elif KIND_DEFAULT_RATED_M3H.get(kind):
            ratings["rated_m3h"], src["rated_m3h"] = KIND_DEFAULT_RATED_M3H[kind], FROM_DEFAULT
        kw = _num(ar.get("rated_kW_thermal"))
        if kw > 0:
            ratings["rated_kW_thermal"], src["rated_kW_thermal"] = kw, FROM_DEVICE
        lph = _num((ar.get("nozzle") or {}).get("sprinkler_flow_lph"))
        if lph > 0:
            ratings["fog_flow_lpm"], src["fog_flow_lpm"] = lph / 60.0, FROM_GEOMETRY
        out.devices.append(Device(uid, str(kind), ratings, ar.get("vent_form")))
        out.sources[uid] = src
    if supply_lpm:
        _limit_fog(out, supply_lpm)
    return out


def rating_view(dev: Device, sources: Optional[Mapping[str, str]] = None,
                domain: str = C.FACILITY) -> List[Dict[str, object]]:
    """목록표가 요구하는 정격마다 {key, unit, value, source} — 읽은 값, 없으면 종류 기본값('추정'), 없으면 모름."""
    out = []
    for r in C.row_for(dev.kind, domain).ratings:
        v = dev.ratings.get(r.key)
        if v:
            src = (sources or {}).get(r.key) or C.SRC_DEVICE
        elif r.default is not None:
            v, src = r.default, C.SRC_DEFAULT
        else:
            v, src = None, C.SRC_UNKNOWN
        out.append({"key": r.key, "unit": r.unit, "value": v, "source": src})
    return out
