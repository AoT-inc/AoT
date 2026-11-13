# coding=utf-8
"""효과 목록표 — 장치 종류(시설) 또는 역할(노지)이 트윈에서 무엇을 바꾸는지의 **단일 출처**.

트윈 모델은 장치를 모르고 **효과 채널**만 안다. 장치 → 채널 번역은 이 표가 맡는다(설계서
`plans/2026-10-25_twin_actuator_effects_design.md` §2). 표에 없는 종류와, 표에 있어도 모델이 못 받는 효과는
**조용히 빼지 않고** `status` 와 `unmodeled_effects` 로 결과에 남긴다.

이 모듈은 **순수 데이터**다. 원격 트윈 노드가 서버 모듈(flask·DB·Influx)을 끌어오지 않도록 env_control 을
import 하지 않는다. env_control 의 어휘(`ACTUATOR_KINDS`·`KIND_TO_CHANNEL`·`UNMODELED_KINDS`)와 어긋나지 않는지는
시험(`tests/test_catalog.py`)이 검사한다 — 새 종류를 더하고 표를 안 고치면 CI 가 깨진다.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, Optional, Tuple

# 정격 출처 이름(앞에서부터 찾는다). 결과마다 어디서 왔는지 표시하기 위한 어휘다.
SRC_DEVICE = "device"        # 장치(Output) 설정
SRC_GEOMETRY = "geometry"    # 시설 형상·피팅(면적·노즐 …)
SRC_SENSOR = "sensor"        # 측정
SRC_USER = "user"            # 사용자가 트윈 탭에서 적음
SRC_SUPPLY = "supply"        # 물 회로의 공급 한계로 낮춘 값
SRC_DEFAULT = "default"      # 종류 기본값 — '추정' 으로 표시한다
SRC_UNKNOWN = "unknown"      # 모름

# 합치는 법
MERGE_VENT_FLOW = "vent_flow"        # 창/팬 풍량 비율 (env_control.vent_channel_value)
MERGE_CAPACITY = "capacity"          # 정격 가중 평균 Σ(정격·가동률)/Σ정격
MERGE_MEAN_OPEN = "mean_open"        # 개도 평균 (차광·커튼)
MERGE_SUM_MM = "sum_mm"              # 물 깊이 합 (노지 관수)
MERGE_NONE = "none"

# 모델 상태. SUPPLY 는 효과가 아니라 **공급 제약**이다 — 물 회로가 깊이·유량에 이미 넣었으니 '미반영'이 아니다.
MODELED, PARTIAL, UNMODELED, SUPPLY = "modeled", "partial", "unmodeled", "supply"

FACILITY, FIELD = "facility", "field"

# 위치로 풀린 관수 출력의 역할. 노즐이 전부 점적이면 점적, 나머지는 살수다 — 사용자가 고른 역할이 이긴다.
IRRIGATION_DEFAULT, IRRIGATION_DRIP = "irrigation_sprinkler", "irrigation_drip"


@dataclass(frozen=True)
class Rating:
    """채널 값을 물리량으로 바꾸는 데 필요한 정격 하나."""
    key: str
    unit: str
    sources: Tuple[str, ...]
    default: Optional[float] = None          # 종류 기본값(있으면 '추정'으로 쓸 수 있다)


@dataclass(frozen=True)
class EffectRow:
    name: str
    domain: str                              # facility | field
    kinds: Tuple[str, ...]                   # 시설: 장치 kind, 노지: 역할 이름
    channel: Optional[str]                   # 효과 채널. None 이면 어느 채널에도 못 넣는다
    merge: str
    modeled_effects: Tuple[str, ...] = ()    # 모델이 지금 반영하는 효과
    unmodeled_effects: Tuple[str, ...] = ()  # 물리로는 있으나 모델이 못 받는 효과(명시)
    ratings: Tuple[Rating, ...] = ()
    slot: str = ""                           # 못 담는 효과를 나중에 담을 자리(측정 이름 등)
    note: str = ""
    supply: bool = False                     # 공급 제약 부품(펌프·탱크) — 효과 채널이 없다

    @property
    def status(self) -> str:
        if self.supply:
            return SUPPLY
        if not self.modeled_effects or self.channel is None:
            return UNMODELED
        return PARTIAL if self.unmodeled_effects else MODELED


# ── 시설 ─────────────────────────────────────────────────────────────────────────
_ROWS: Tuple[EffectRow, ...] = (
    EffectRow("window", FACILITY, ("opening", "vent", "side_vent", "roof_vent", "window"), "vent", MERGE_VENT_FLOW,
              modeled_effects=("air_T", "air_AH", "air_CO2"),
              ratings=(Rating("area_m2", "m2", (SRC_GEOMETRY, SRC_DEVICE, SRC_USER), 1.0),),
              note="형태(ridge/side)는 정격과 별개로 읽는다"),
    EffectRow("vent_fan", FACILITY, ("exhaust_fan", "intake_fan"), "vent", MERGE_VENT_FLOW,
              modeled_effects=("air_T", "air_AH", "air_CO2"),
              ratings=(Rating("rated_m3h", "m3/h", (SRC_DEVICE, SRC_USER), 3000.0),)),
    EffectRow("heater", FACILITY, ("heater",), "heat", MERGE_CAPACITY,
              modeled_effects=("air_T",),
              ratings=(Rating("rated_kW_thermal", "kW", (SRC_DEVICE, SRC_USER)),)),
    EffectRow("cooler", FACILITY, ("cooler", "ac"), "cool", MERGE_CAPACITY,
              modeled_effects=("air_T",),
              unmodeled_effects=("dehumidification",),
              ratings=(Rating("rated_kW_thermal", "kW", (SRC_DEVICE, SRC_USER)),)),
    EffectRow("fogger", FACILITY, ("fogger", "humidifier"), "fog", MERGE_CAPACITY,
              modeled_effects=("air_T", "air_AH"),
              unmodeled_effects=("leaf_wetness",),
              ratings=(Rating("fog_flow_lpm", "L/min", (SRC_GEOMETRY, SRC_DEVICE, SRC_USER)),),
              note="습윤형 노즐(스프링클러 패턴)은 증발 효율이 달라 노즐 요약을 같이 읽는다"),
    EffectRow("co2_injector", FACILITY, ("co2_injector",), "co2_inj", MERGE_CAPACITY,
              modeled_effects=("air_CO2",),
              ratings=(Rating("co2_kg_h", "kg/h", (SRC_DEVICE, SRC_USER)),)),
    EffectRow("shade", FACILITY, ("shade",), "shade", MERGE_MEAN_OPEN,
              modeled_effects=("solar_in",),
              ratings=(Rating("tau_shade", "-", (SRC_DEVICE, SRC_GEOMETRY, SRC_USER)),)),
    EffectRow("curtain", FACILITY, ("curtain",), "curtain", MERGE_MEAN_OPEN,
              modeled_effects=("envelope_UA", "solar_in"),
              ratings=(Rating("tau_curtain", "-", (SRC_DEVICE, SRC_GEOMETRY, SRC_USER)),
                       Rating("curtain_ua_saving", "-", (SRC_DEVICE, SRC_GEOMETRY, SRC_USER)))),
    EffectRow("lighting", FACILITY, ("lighting", "supplemental_light"), None, MERGE_NONE,
              unmodeled_effects=("heat_gain", "par"),
              ratings=(Rating("rated_kW", "kW", (SRC_DEVICE, SRC_USER)),),
              slot="channel:light (후보 — 열 가산만 그레이박스에 항 하나로)",
              note="독립 참값(sim/plant)에는 있으나 그레이박스에는 없다"),
    EffectRow("circulation_fan", FACILITY, ("circulation_fan",), None, MERGE_NONE,
              unmodeled_effects=("leaf_boundary_layer", "leaf_wetness"),
              ratings=(Rating("rated_m3h", "m3/h", (SRC_DEVICE, SRC_USER)),),
              note="그레이박스에 잎 상태가 없어 지금은 반영 불가(plant 에는 있음)"),
    EffectRow("dehumidifier", FACILITY, ("dehumidifier",), None, MERGE_NONE,
              unmodeled_effects=("dehumidification",)),
    EffectRow("co2_scrubber", FACILITY, ("co2_scrubber",), None, MERGE_NONE,
              unmodeled_effects=("air_CO2_removal",)),
    EffectRow("water_supply", FACILITY, ("pump", "tank"), None, MERGE_NONE, supply=True,
              note="공급 제약 — 분무 유량 상한으로 읽는다(`reader`). 트윈은 펌프를 모른다"),

    # ── 노지 — 출력 종류가 범용이라 **역할**로 묶는다(사용자가 고르거나 자동 제안) ──────────
    EffectRow("irrigation_sprinkler", FIELD, ("irrigation_sprinkler",), "irrigation_mm", MERGE_SUM_MM,
              modeled_effects=("soil_water",),
              unmodeled_effects=("air_RH_near_surface", "air_T_near_surface", "surface_T", "leaf_wetness"),
              ratings=(Rating("flow_lpm", "L/min", (SRC_GEOMETRY, SRC_DEVICE, SRC_USER)),
                       Rating("area_m2", "m2", (SRC_GEOMETRY, SRC_USER))),
              slot="measurement:env_twin_field_h",
              note="공기·지표 효과는 일 격자 모델이 못 담는다 — 시간 격자 모듈로"),
    EffectRow("irrigation_drip", FIELD, ("irrigation_drip",), "irrigation_mm", MERGE_SUM_MM,
              modeled_effects=("soil_water",),
              unmodeled_effects=("wetted_fraction",),
              ratings=(Rating("flow_lpm", "L/min", (SRC_GEOMETRY, SRC_DEVICE, SRC_USER)),
                       Rating("area_m2", "m2", (SRC_GEOMETRY, SRC_USER))),
              slot="model:few(젖은 면적비)"),
    EffectRow("irrigation_mist", FIELD, ("irrigation_mist",), "irrigation_mm", MERGE_SUM_MM,
              modeled_effects=("soil_water",),
              unmodeled_effects=("air_RH_near_surface", "air_T_near_surface"),
              ratings=(Rating("flow_lpm", "L/min", (SRC_GEOMETRY, SRC_DEVICE, SRC_USER)),
                       Rating("area_m2", "m2", (SRC_GEOMETRY, SRC_USER))),
              slot="measurement:env_twin_field_h"),
    EffectRow("water_supply_field", FIELD, ("pump", "tank"), None, MERGE_NONE, supply=True,
              note="공급 제약 — 물 회로가 구획별 깊이에 넣는다. 트윈은 깊이만 받는다"),
    EffectRow("frost_fan", FIELD, ("frost_fan",), None, MERGE_NONE,
              unmodeled_effects=("night_min_T",),
              slot="measurement:env_twin_field_h", note="서리 겨울 검증 뒤 시간 격자 모듈로"),
    EffectRow("frost_sprinkler", FIELD, ("frost_sprinkler",), None, MERGE_NONE,
              unmodeled_effects=("night_min_T", "latent_heat_of_freezing"),
              slot="measurement:env_twin_field_h"),
    EffectRow("mulch_cover", FIELD, ("mulch", "tunnel_cover", "shade_net"), None, MERGE_NONE,
              unmodeled_effects=("soil_T", "soil_evaporation", "rain_interception"),
              note="상태형 — 장치 출력이 아니라 기간으로 입력"),
)

_BY_KIND: Dict[Tuple[str, str], EffectRow] = {}
for _r in _ROWS:
    for _k in _r.kinds:
        _BY_KIND[(_r.domain, _k)] = _r

UNKNOWN_KIND = EffectRow("unknown", "", (), None, MERGE_NONE, unmodeled_effects=("unknown_kind",),
                         note="목록표에 없는 종류 — 효과 미반영")


def rows(domain: Optional[str] = None) -> Tuple[EffectRow, ...]:
    return tuple(r for r in _ROWS if domain is None or r.domain == domain)


def all_kinds(domain: Optional[str] = None) -> frozenset:
    return frozenset(k for r in rows(domain) for k in r.kinds)


def row_for(kind: Optional[str], domain: str = FACILITY) -> EffectRow:
    """종류의 표 행. 없으면 `UNKNOWN_KIND`(미반영) — 호출자가 빼지 않고 결과에 남긴다."""
    return _BY_KIND.get((domain, str(kind or "").lower()), UNKNOWN_KIND)


def channels(domain: str) -> Tuple[str, ...]:
    seen = []
    for r in rows(domain):
        if r.channel and r.channel not in seen:
            seen.append(r.channel)
    return tuple(seen)


def summarize(kinds: Iterable[Optional[str]], domain: str = FACILITY) -> Dict[str, object]:
    """연결된 종류들의 반영 현황: modeled/partial/unmodeled/supply 개수와 미반영 종류·효과."""
    out = {"modeled": 0, "partial": 0, "unmodeled": 0, "supply": 0, "unmodeled_kinds": [], "unmodeled_effects": []}
    for k in kinds:
        r = row_for(k, domain)
        out[r.status] += 1
        if r.status not in (MODELED, SUPPLY):
            out["unmodeled_kinds"].append(str(k))
            out["unmodeled_effects"].extend(e for e in r.unmodeled_effects if e not in out["unmodeled_effects"])
    return out
