# coding=utf-8
"""극한 고온·건조의 짧은 펄스 분무 — 판정과 상수는 **이 모듈 한 곳**이다 (2026-10-12).

## 왜 있는가

습윤형 분무는 낮에는 일소 잠금(`nursery_solar_lockout` 250 W/m², 해제 150)이, 저녁에는 해 질 녘 제한
(`wet_fog_dusk`, 근거 53)이 막는다. 평범한 날에는 옳다. 그런데 **극한 날**에는 분무가 하루 종일 0 이다:

    heatwave_tropical_night   실내 42.5 °C, 40 °C 초과 337 분, VPD 가 목표 안에 있던 몫 7 %
    foehn_dry_wind            RH 15 %, VPD 최대 7 kPa 인데 낮 가습 0

일소 잠금의 이유는 "분무가 마르며 지하수의 염분·경도를 잎에 남긴다" 는 것이었는데, 사용자가 확인했다
(2026-10-11): **관찰 없이 한 추측이었다.** 물방울 렌즈 효과도 털 있는 잎 말고는 근거가 약하다. 그래서
잠금은 두되, 정말 덥고 건조해 증발이 빠른 날에는 **짧은 펄스**를 허용한다(기본 켜짐, 옵션 하나로 끈다).

## 규칙 — 모두 참이어야 한다

    잠금 중        일소 잠금(`GATE_BIT_FOG_SUNBURN`)이 서 있다. 안 서 있으면 이 규칙은 아무 일도 하지 않는다
                   (일소 잠금이 없는 설치·시간은 종전 그대로 — 육묘 모드가 아니면 애초에 잠금이 없다).
    더운가·마른가   극한 고온 보호 단계 ≥ 1 이거나 실내 VPD > `PF_VPD_KPA`(3 kPa).
    증발 여력      건구 − 습구 ≥ `PF_WETBULB_DEPRESSION_C`(8 °C) — 젖은 잎이 몇 분 안에 마른다.
    습도           습윤형 분무 습도 상한(`_fog_humidity_block`)에 걸리지 않고, 하드 습도 상한(`humid_max`)
                   과 보호의 습도 문턱(85 %) 아래다.
    물             분무용 물이 있다(`water_supply`).
    저녁 아님       해 질 녘 제한(53)이 서기 `PF_DUSK_MARGIN_MIN`(240분) 전보다 앞이고 육묘 저녁 차단도 아니다 —
                   **오후 끝자락·저녁·밤 펄스는 없다.** 마지막 펄스의 물이 저녁에 닫혀 가는 집에서 마저 증발해 밤 이슬을
                   앞당기는 것을 폐루프(`heatwave_tropical_night`)로 쟀다: 여유 0 → 밤 젖음 +61분(+5 %), 60분 +39, 120분 +25,
                   180분 +13, 240분 +5(+0.4 %). 더 줄이면 낮 냉각이 같이 준다(40 °C 초과 분 −70 → −28).
    다른 게이트 없음 강우(전면·단계)·강풍 2단계·한파·서리(주의 포함)·실외/실내 값 잃음 중 하나라도 서 있으면
                   이 규칙은 서지 않는다. 강풍 1단계(개구부 상한)만 분무와 무관하므로 막지 않는다.

## 펄스의 모양

    PF_ON_SEC(10 초) 켬, 끝난 뒤 PF_MIN_OFF_SEC(900 초 = 15 분) 이상 쉼.

켜는 시간은 습윤형 분무기가 이미 타는 `PulsedDoseAdapter`(관수식 펄스 도징, 분무기의 `nursery_max_on_sec`·
`nursery_min_off_sec`)에 **상한만 얹는다**: 켜는 시간은 min(사용자 설정, 10 초), 어댑터가 막는 쉬는 시간은
max(사용자 설정, 900 초). 사용자가 더 짧게·더 드물게 정했으면 그쪽이 이긴다.

⚠ **쉬는 15분의 시계는 어댑터가 아니라 디스패치(코디네이터)가 쥔다**(`_pulse_fog_next_ok`, 분무기별). 어댑터 맵은
10분(`_PROFILE_RELOAD_INTERVAL_S`)마다 다시 지어져 어댑터의 `_blocked_until` 이 지워졌다 — 폐루프에서 600초
주기 펄스가 그대로 매 사이클 나간 것으로 드러났다. 코디네이터의 시계는 재적재와 무관하다(재시작은 넘지 못한다).
(10/13 부터 재적재는 어댑터의 쉼을 새 어댑터로 넘긴다 — `carry_adapter_state`. 이 시계는 그와 별개로 남긴다.)

명령은 근거 57(`extreme_pulse_fog`)·100 % 로 나간다. 코디네이터(PI)가 가습을 **요구하고 있을 때만**
(`PF_MIN_DEMAND_PCT` 이상) 펄스가 되고, 요구가 없으면 0 이다 — 잠금이 풀린 것이 아니라 펄스만 허용한 것이다.
습도 상한·물·저녁 제한·게이트는 이 규칙 앞에서 이미 판정되어 있고, 위 조건이 그 결론을 다시 읽는다.
"""
# @manual ai/env-control#pulse-fog
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .heat_protect import HP_FOG_RH_BLOCK, wetbulb_depression
from .safety_gates import is_wetting_fogger
from .log_channels import (
    GATE_BIT_COLD, GATE_BIT_EXT_EXP, GATE_BIT_FOG_SUNBURN, GATE_BIT_FROST,
    GATE_BIT_FROST_WATCH, GATE_BIT_INT_EXP, GATE_BIT_RAIN, GATE_BIT_RAIN_LIGHT,
    GATE_BIT_WIND, GATE_BIT_WIND_LIGHT,
)
from . import psychro

# ─────────────────────────────────────────────────────────────────────────────
# 상수 — 재배자가 판단할 값이 아니다(옵션으로 내지 않는다). 켜고 끄는 스위치만 옵션이다(`extreme_pulse_fog`).
# ─────────────────────────────────────────────────────────────────────────────
PF_ON_SEC = 10.0                  # 펄스 한 번의 길이
PF_MIN_OFF_SEC = 900.0            # 펄스 뒤 최소 쉬는 시간(15 분)
PF_VPD_KPA = 3.0                  # 이 값 초과의 실내 VPD 는 극한 건조(보호 단계가 아니어도)
PF_HEAT_TIER = 1                  # 극한 고온 보호 단계가 이 이상이면 극한 고온
PF_WETBULB_DEPRESSION_C = 8.0     # 건구 − 습구가 이 이상이어야 젖은 잎이 곧 마른다
PF_DUSK_MARGIN_MIN = 240.0       # 해 질 녘 제한(53)이 서기 이만큼 전에 이미 펄스를 멈춘다 — 마지막 펄스의 물이 저녁 닫힌 집에서 마저 증발해 이슬을 앞당기지 않게
PF_MIN_DEMAND_PCT = 5.0           # 코디네이터의 가습 요구가 이 이상이어야 펄스(어댑터의 최소 켬 %와 같다)

PULSE_FOG_REASON = 'extreme_pulse_fog'   # 오버라이드의 문자열 근거 → `log_channels` 가 57 로 옮긴다

# 이 규칙을 막는 게이트 비트 — 일소 잠금 자신(필수 조건)과 강풍 1단계(개구부만 묶는다)만 빠진다.
_BLOCKING_GATE_BITS = (
    GATE_BIT_RAIN | GATE_BIT_RAIN_LIGHT | GATE_BIT_WIND | GATE_BIT_COLD
    | GATE_BIT_FROST | GATE_BIT_FROST_WATCH | GATE_BIT_EXT_EXP | GATE_BIT_INT_EXP)
_ALLOWED_GATE_BITS = GATE_BIT_FOG_SUNBURN | GATE_BIT_WIND_LIGHT


@dataclass
class PulseFogDecision:
    """한 사이클의 결론. 쓰는 곳은 이것만 읽는다."""
    active: bool = False
    why: Optional[str] = None            # 켜진 이유 'heat' | 'dry' | 'heat+dry'
    blocked: Optional[str] = None        # 서지 않은 이유(기록·시험용). 켜졌으면 None
    vpd: Optional[float] = None
    depression: Optional[float] = None   # 건구 − 습구 [°C]

    def describe(self) -> str:
        if self.active:
            return '극한 %s — 일소 잠금 중 짧은 펄스 분무 허용(%d초 켬·%d분 이상 쉼, 건구−습구 %.1f °C)' % (
                {'heat': '고온', 'dry': '건조', 'heat+dry': '고온·건조'}.get(self.why, '날씨'),
                int(PF_ON_SEC), int(PF_MIN_OFF_SEC / 60), self.depression or 0.0)
        return '펄스 없음(%s)' % (self.blocked or '-')


def pulse_fog_ids(profiles) -> frozenset:
    """이 규칙이 다루는 분무기 — 습윤형이고 관수식 펄스 도징(`PulsedDoseAdapter`)을 타는 것만.

    펄스로 끊을 수 없는 분무기(도징이 꺼진 것)는 일소 잠금이 그대로 막는다.
    """
    return frozenset(
        p.actuator_id for p in profiles or []
        if is_wetting_fogger(p)
        and getattr(getattr(p, 'cmd_constraints', None), 'pulse_dosing', False))


def _num(v) -> Optional[float]:
    try:
        return None if v is None else float(v)
    except (TypeError, ValueError):
        return None


def indoor_vpd(internal: dict) -> Optional[float]:
    """실내 공기 VPD [kPa]. 센서값(`internal['VPD']`)이 없으면 T·RH 로 계산한다. 모르면 None."""
    v = _num(internal.get('VPD'))
    if v is not None:
        return v
    T, RH = _num(internal.get('T')), _num(internal.get('RH'))
    if T is None or RH is None:
        return None
    return psychro.vpd_from_rh(T, RH)


def evaluate_pulse_fog(*, enabled: bool, gate_mask: int, evening_block: bool, dusk_limited: bool,
                       heat_tier: int, fog_allowed: bool, internal: dict,
                       humid_max: Optional[float] = None) -> PulseFogDecision:
    """이번 사이클에 일소 잠금 중 펄스를 허용하는가. 순수 함수 — 위 규칙 그대로.

    `internal` 은 `T`·`RH`·`VPD`·`_fog_humidity_block`·`_water_available` 을 읽는다.
    """
    if not enabled:
        return PulseFogDecision(blocked='option_off')
    mask = int(gate_mask or 0)
    if not mask & GATE_BIT_FOG_SUNBURN:
        return PulseFogDecision(blocked='no_lock')
    if evening_block:
        return PulseFogDecision(blocked='evening')
    if mask & _BLOCKING_GATE_BITS:
        return PulseFogDecision(blocked='gate')
    if dusk_limited:
        return PulseFogDecision(blocked='dusk')

    T, RH = _num(internal.get('T')), _num(internal.get('RH'))
    if T is None or RH is None:
        return PulseFogDecision(blocked='no_indoor')
    vpd = indoor_vpd(internal)
    hot = int(heat_tier or 0) >= PF_HEAT_TIER
    dry = vpd is not None and vpd > PF_VPD_KPA
    if not (hot or dry):
        return PulseFogDecision(blocked='not_extreme', vpd=vpd)
    dep = wetbulb_depression(T, RH)
    if dep is None or dep < PF_WETBULB_DEPRESSION_C:
        return PulseFogDecision(blocked='low_evaporation', vpd=vpd, depression=dep)
    if internal.get('_fog_humidity_block'):
        return PulseFogDecision(blocked='humidity', vpd=vpd, depression=dep)
    ceiling = HP_FOG_RH_BLOCK
    hm = _num(humid_max)
    if hm is not None and hm > 0:
        ceiling = min(ceiling, hm)
    if RH >= ceiling:
        return PulseFogDecision(blocked='humidity', vpd=vpd, depression=dep)
    if internal.get('_water_available', True) is False:
        return PulseFogDecision(blocked='no_water', vpd=vpd, depression=dep)
    if not fog_allowed:
        return PulseFogDecision(blocked='heat_protect_fog', vpd=vpd, depression=dep)
    return PulseFogDecision(active=True, why='heat+dry' if hot and dry else ('heat' if hot else 'dry'),
                            vpd=vpd, depression=dep)
