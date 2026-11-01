# coding=utf-8
"""극한 고온(폭염) 보호 — 판정과 정책은 **이 모듈 한 곳**이다 (2026-10-09).

## 왜 있는가

목표가 바뀐다. 실내가 작물이 견디는 선(기본 30 °C)을 넘으면 설정값을 좇는 것보다
**열·수분 스트레스를 줄이는 것**이 먼저다. 예전에는 그 일을 안전 게이트의 폭염
비상(실외 ≥45 °C **그리고** 실내 ≥35 °C → 창 100 · 차광 · 냉방 100)이 맡았는데,
그 조건에서는 대개 바깥이 더 덥다 — 창 100 은 물리적으로 반대 방향이었다. 그리고
실외 45 °C 는 한국 시설에서 거의 오지 않아, 30~35 °C 의 실제 고온 구간에는 아무것도
서지 않았다. 그 게이트는 없앴고(옛 CH70 기록 해독용으로 `GATE_BIT_HEAT` 상수만
남는다), 이 모듈이 그 자리를 대신한다.

## 단계

    0  보호 아님
    1  실내(필터된 **평균** `internal['T']`) 가 사용자 문턱(`heat_protect_threshold`,
       기본 30 °C)을 넘었다. 평균인 이유: 극값(T_max)으로 재면 30 °C 에서 너무 잦다.
    2  하드 상한(`temp_max`, 기본 35 °C)의 기존 래치(`_force_cool`)가 서 있다 — 새
       옵션을 만들지 않는다.

진입: 문턱 이상이 `HP_ENTER_DWELL_S` 이어지거나, 예측(T + 상승률 × 제어주기)이
문턱 + `HP_PREDICT_MARGIN_C` 이상이면 즉시. 해제: 문턱 − 해제여유 이하가
`HP_RELEASE_DWELL_S` 이어지고 **그리고** 진입 후 최소 유지 시간이 지나야 한다.
30 °C 근처에서 오르내리는 날에 보호가 켜졌다 꺼졌다 하지 않게 하는 장치들이다.

실내를 모르면: 보호 중이 아니면 켜지 않는다. 보호 중이면 `HP_STALE_MAX_S` 까지
유지하고(`stale`) 그 뒤 푼다 — 그동안 차광은 그대로, 난방 0, 분무 차단(습구를 모른다),
창은 코디네이터의 근거-21 경로대로 제자리.

## 조치 (위가 이긴다)

1. 강우·강풍 폐쇄 — 안전 게이트가 마지막에 덮거나 발동 시 L1~L3 를 건너뛴다.
2. 실외를 모른다(`_ext_synthetic`) → 환기 장치 제자리(코디네이터 2.6).
3. 환기(vent 도메인 전부): 실외가 실내보다 `HP_VENT_OPEN_DELTA_C` 이상 차면 "열어도
   됨"(래치 — 실외가 실내보다 더워지면 풀린다). 열어도 됨 → 야간 파킹·냉난방 연동·
   환기 무익·반응 없음 판정에서 뺀다. 안 됨 → 파킹(근거 28). 단 직전 사이클에
   분무가 돌았으면 하한 `HP_VENT_FLOOR_PCT`(팬이 있으면 팬, 없으면 창) — 습기를 빼야
   증발냉각이 이어진다.
4. 온도 우선: 보호 중 `coordinator._temperature_ceiling` 은 하드(맞서는 VPD·습도 항을
   뺀다)이고 선은 문턱을 넘지 않는다. 온·습도 직접 모드에서는 `situation.assess` 가
   온도 우선순위를 `HP_T_PRIORITY` 이상으로 올린다.
5. 분무는 물이 있고(`internal['_water_available']`), 증발 여력(T − 습구)이 있고, 습도가
   `HP_FOG_RH_BLOCK` 아래일 때만. 하나라도 어기면 파킹(근거 29). 육묘 일소 잠금이
   최종적으로 이긴다(안전 게이트가 마지막).
6. 차광(0 = 전개): 실외 일사가 있을 때만. 단계 1 에서는 "걷었을 때 광량 × 차광
   투과율 ≥ light_min" 일 때만 — 단계 2 거나 실내가 문턱 + `HP_SEVERE_EXTRA_C`
   이상이면 light_min 보다 우선. 보호 중 한 번 친 차광은 해가 있는 동안 고정이다.
7. 난방 0 · 유동팬 100 · 냉방(단계 1 은 PI 의 하드 상한 항, 단계 2 는 100) · 환기 우선 끔.

## 쓰는 곳 — 결과를 **읽기만** 한다

    decide_parking·_temperature_ceiling (PI 안 — 적분이 제약을 안다)
    apply_heat_protect_overrides         (PI 가 안 다루는 장치 / PI 를 거치지 않는 경로)
    _run_control                         (보호 중 MPC·greybox-PI 를 건너뛴다)

서리(`safety_gates.evaluate_frost`)와는 **함께 서지 않는다** — `internal['_frost_level']` 이 양수면 보호는
풀리고 새로 서지 않는다.

⚠ 여기 밖에서 문턱·래치를 다시 판정하지 말 것. 두 벌이 되면 갈라지고, 갈라지면
  느슨한 쪽이 실질 규칙이 된다.
⚠ `HeatProtectState` 는 재시작을 넘는다(`cycle_memory`, 30 분 안의 기억만) — 예전에는 버렸는데,
  그러면 서 있던 보호가 재시작에 풀려 진입 지연만큼 다시 기다렸다(2026-10-10, 같은 결함의 일사 쪽:
  `cycle_memory` 머리말).
"""
# @manual ai/env-control#heat-protect
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional

from . import psychro
from .safety_gates import is_wetting_fogger
from .screen_policy import (
    SHADE_SOLAR_OFF, SHADE_SOLAR_ON, shaded_below_light_min,
)
from .types import VENTILATING_KINDS

# ─────────────────────────────────────────────────────────────────────────────
# 상수 — 재배자가 판단할 값이 아니다(옵션으로 내지 않는다)
# ─────────────────────────────────────────────────────────────────────────────
HP_ENTER_DWELL_S = 180.0      # 문턱 이상이 이만큼 이어져야 진입(순간 스파이크 무시)
HP_PREDICT_MARGIN_C = 1.0     # 예측이 문턱 + 이만큼이면 기다리지 않고 진입
HP_RELEASE_DWELL_S = 600.0    # 해제선 이하가 이만큼 이어져야 해제
HP_STALE_MAX_S = 1800.0       # 실내를 잃은 채 보호를 유지하는 최대 시간
HP_SEVERE_EXTRA_C = 3.0       # 문턱 + 이만큼이면 차광이 light_min 보다 우선
HP_VENT_OPEN_DELTA_C = 1.0    # 실외 ≤ 실내 − 이만큼 → 열어도 됨
HP_VENT_CLOSE_DELTA_C = 0.0   # 열어도 됨이던 것은 실외 > 실내 − 이만큼이 되어야 풀린다
HP_FOG_WETBULB_ENTER_C = 4.0  # 증발 여력(T − 습구)이 이만큼이어야 분무 허용
HP_FOG_WETBULB_EXIT_C = 2.5   # 허용 중이면 이 아래로 떨어질 때 차단
HP_FOG_RH_BLOCK = 85.0        # 이 습도 이상이면 분무 차단
HP_FOG_RH_RELEASE = 80.0      # 차단 중이면 이 아래로 와야 다시 허용
HP_VENT_FLOOR_PCT = 15.0      # 바깥이 더 더워도 분무가 돌았으면 이만큼은 연다
# 실외 일사(W/m²) 히스테리시스 — 정본은 `screen_policy`(차광 판단의 주인)다.
HP_SHADE_SOLAR_ON = SHADE_SOLAR_ON     # 이 이상이면 차광 대상
HP_SHADE_SOLAR_OFF = SHADE_SOLAR_OFF   # 차광 대상이던 것은 이 아래로 와야 풀린다
HP_T_PRIORITY = 2.0           # 온·습도 직접 모드에서 보호 중 온도 우선순위 하한

# 옵션의 허용 범위 — 화면 검증(`_function_info`)과 코드 쪽 자르기가 **같은 표**를 본다.
HP_OPTION_RANGES = {
    'heat_protect_threshold':      (20.0, 45.0),   # °C
    'heat_protect_release_margin': (0.5, 5.0),     # °C
    'heat_protect_min_hold_min':   (5.0, 120.0),   # 분
}

# 오버라이드의 문자열 근거 — `log_channels.STRING_REASON_CODES` 가 정수로 옮긴다.
HEAT_PROTECT_REASON = 'heat_protect'

_FAN_KINDS = frozenset({'exhaust_fan', 'intake_fan'})

# ── CH76 비트마스크 ───────────────────────────────────────────────────────────
HP_FLAG_VENT_OPEN_OK = 1 << 0      # 열어도 됨(실외가 더 차다)
HP_FLAG_HOT_OUTSIDE = 1 << 1       # 바깥이 더 덥다 — 환기 파킹
HP_FLAG_FOG_ALLOWED = 1 << 2       # 분무 허용
HP_FLAG_FOG_WETBULB = 1 << 3       # 증발 여력 부족으로 분무 차단
HP_FLAG_FOG_HUMID = 1 << 4         # 습도(또는 습도 미상)로 분무 차단
HP_FLAG_NO_WATER = 1 << 5          # 물 공급 없음으로 분무 차단
HP_FLAG_SHADE_DEPLOY = 1 << 6      # 차광 전개
HP_FLAG_LIGHT_MIN_YIELD = 1 << 7   # light_min 때문에 차광을 양보했다
HP_FLAG_INDOOR_STALE = 1 << 8      # 실내 값이 끊긴 채 보호 유지 중


@dataclass
class HeatProtectConfig:
    """사용자 옵션 + 사이클 정보. 상수(`HP_*`)는 여기 두지 않는다."""
    enabled: bool = True
    threshold: float = 30.0
    release_margin: float = 1.5
    min_hold_s: float = 1200.0
    light_min: Optional[float] = None     # 광량 하한(옵션 `light_min`) — 차광 양보 판정
    cycle_sec: float = 60.0


@dataclass
class HeatProtectState:
    """사이클을 넘는 래치. 재시작을 넘는다(`cycle_memory`)."""
    latched: bool = False
    tier: int = 0
    above_since: Optional[float] = None
    below_since: Optional[float] = None
    entered_at: Optional[float] = None
    stale_since: Optional[float] = None
    vent_open_ok: Optional[bool] = None
    fog_wb_ok: bool = False
    fog_rh_ok: bool = True
    sun_on: bool = False
    shade_on: bool = False
    # 직전 사이클에 분무가 실제로 나갔는가 — `record_dispatch` 가 채운다.
    fog_ran: bool = False


@dataclass
class HeatProtectDecision:
    """한 사이클의 결론. 쓰는 곳은 이것만 읽는다."""
    tier: int = 0
    threshold: float = 30.0
    # 보호 기능이 켜져 있는가(옵션). 꺼져 있으면 문턱은 아무 데도 쓰이지 않는다 —
    # 켜져 있으면 보호 밖에서도 PI 의 온도 상한이 문턱을 넘지 않는다
    # (`coordinator._temperature_ceiling`).
    enabled: bool = True
    escalated: bool = False       # 이번 사이클에 단계가 **올라갔다**(긴급은 이때 한 번만)
    released: bool = False        # 이번 사이클에 풀렸다
    stale: bool = False
    vent_open_ok: Optional[bool] = None
    vent_open_ids: frozenset = frozenset()
    vent_closed_ids: frozenset = frozenset()
    fog_allowed: bool = True
    fog_block_reason: Optional[str] = None   # 'water' | 'wetbulb' | 'humidity' | 'stale'
    fog_blocked_ids: frozenset = frozenset()
    # 보호가 **증발냉각기로 쓰는** 분무기 — 잎을 적시지 않는 것(고압 미세포그)만.
    # 습윤형(아래 향 살수·미니스프링클러)은 여기 없다: 하드 온도 항이 그것을 몰지
    # 않고, 그것이 돌았다고 환기 하한을 열지 않는다(`cooling_foggers` 주석).
    cooling_fog_ids: frozenset = frozenset()
    floor_pct: float = 0.0
    floor_ids: frozenset = frozenset()
    shade_deploy: bool = False
    light_min_yield: bool = False
    flags: int = 0
    vent_only: bool = False       # 환기 말고는 쓸 수단이 없는 시설(진입 로그용)

    @property
    def active(self) -> bool:
        return self.tier >= 1


def _num(v) -> Optional[float]:
    try:
        return None if v is None else float(v)
    except (TypeError, ValueError):
        return None


def wetbulb_depression(T: Optional[float], RH: Optional[float]) -> Optional[float]:
    """건구 − 습구(단열포화온도) [°C]. 모르면 None. 식은 `psychro` 의 것이다."""
    T, RH = _num(T), _num(RH)
    if T is None or RH is None:
        return None
    w = psychro.humidity_ratio(psychro.vapor_pressure(T, RH))
    return T - psychro.adiabatic_saturation_temperature(T, w)


def _outdoor_solar(internal: dict, external: dict) -> Optional[float]:
    """차광 판정용 **실외** 일사. 양수만 측정값으로 인정한다(0.0 은 '센서 없음' 일 수
    있다 — `_cycle_mixin._compute_light_est` 주석과 같은 판단)."""
    for v in (internal.get('_outdoor_solar'), external.get('solar')):
        v = _num(v)
        if v is not None and v > 0.0:
            return v
    return None


def cooling_foggers(profiles: Iterable) -> frozenset:
    """보호가 증발냉각기로 쓰는 분무기 id — 습윤형은 뺀다.

    습윤형 분무(아래 향 살수, 굵은 물방울)는 공중에서 거의 날지 않는다 — 물은 잎·
    트레이에 떨어지고 냉각은 그 젖은 면이 마르며 생긴다. 그 증발 속도는 잎 온도와
    공기의 습도 차로 정해지고 분무량과는 무관하다: 젖은 면이 이미 젖어 있으면 더
    뿌린 물은 흘러내린다. 폐루프(김제 육묘장3, 40 L/h × 56 노즐, 2026-10-09):
    보호가 하드 온도 항으로 이 살수를 몰자 hot_dry 에서 분무량이 277 → 938 kg,
    흘러내린 물이 9 → 429 kg 이었다 — 일소 잠금 때문에 해가 약한 저녁·밤에만
    돌았고, 그 시간에는 잎이 공기보다 차서 마를 틈이 없다(잿빛곰팡이 조건).
    그래서 습윤형은 평소 제어(VPD·습도 + 습윤형 습도 상한)가 그대로 다루고, 보호는
    그것을 막기만(물·증발 여력·습도 85 %) 한다. 판정 기준은 `is_wetting_fogger` 하나다.
    """
    return frozenset(p.actuator_id for p in (profiles or [])
                     if getattr(p, 'kind', '') == 'fogger' and not is_wetting_fogger(p))


# @manual ai/env-control#heat-protect
def evaluate_heat_protect(cfg: HeatProtectConfig, state: HeatProtectState,
                          internal: dict, external: dict,
                          profiles: Iterable, now: float,
                          T_trend: float = 0.0) -> HeatProtectDecision:
    """이번 사이클의 보호 단계와 조치 → `HeatProtectDecision`. `state` 를 제자리에서 고친다.

    `internal` 은 사이클의 실내 dict(`_force_cool` 이 이미 심겨 있어야 한다 —
    `_check_hard_constraints` 뒤에 부를 것), `external` 은 판단용 실외(평활 또는
    fallback — `_ext_synthetic` 가 실릴 수 있다). `T_trend` 는 °C/min.
    """
    internal = internal or {}
    external = external or {}
    profiles = list(profiles or [])
    prev_tier = int(state.tier or 0)
    thr = float(cfg.threshold)

    if not cfg.enabled:
        # 꺼져 있으면 래치를 모두 비운다 — 다시 켰을 때 옛 진입 시각으로 서지 않게.
        fog_ran = state.fog_ran
        state.__dict__.update(HeatProtectState().__dict__)
        state.fog_ran = fog_ran
        return HeatProtectDecision(tier=0, threshold=thr, enabled=False,
                                   released=prev_tier > 0)

    if int(internal.get('_frost_level') or 0) > 0:
        # 서리와 극한 고온 보호는 **함께 서지 않는다**(서리 = 개구부·커튼 닫고 난방, 보호 = 반대).
        # 서리가 서 있으면 보호 래치를 비우고 새로 서지 않는다 — 센서 끊김으로 래치만 남은 보호(실내를
        # 잃은 채 30 분 유지)가 서리 보호의 난방 100 과 맞서는 것을 막는다(`safety_gates.evaluate_frost`).
        fog_ran = state.fog_ran
        state.__dict__.update(HeatProtectState().__dict__)
        state.fog_ran = fog_ran
        return HeatProtectDecision(tier=0, threshold=thr, enabled=True,
                                   released=prev_tier > 0)

    T = _num(internal.get('T'))
    RH = _num(internal.get('RH'))
    force_cool = bool(internal.get('_force_cool'))
    stale = False

    # ── 단계 1 래치 ───────────────────────────────────────────────────────────
    if T is None:
        state.above_since = None
        state.below_since = None
        if state.latched:
            if state.stale_since is None:
                state.stale_since = now
            if now - state.stale_since >= HP_STALE_MAX_S:
                state.latched = False
                state.entered_at = None
                state.stale_since = None
            else:
                stale = True
    else:
        state.stale_since = None
        projected = T + max(0.0, float(T_trend or 0.0)) * float(cfg.cycle_sec or 60.0) / 60.0
        if not state.latched:
            state.below_since = None
            if T >= thr:
                if state.above_since is None:
                    state.above_since = now
            else:
                state.above_since = None
            dwell_ok = (state.above_since is not None
                        and now - state.above_since >= HP_ENTER_DWELL_S)
            if dwell_ok or projected >= thr + HP_PREDICT_MARGIN_C or force_cool:
                state.latched = True
                state.entered_at = now
                state.above_since = None
        else:
            state.above_since = None
            if T <= thr - float(cfg.release_margin):
                if state.below_since is None:
                    state.below_since = now
            else:
                state.below_since = None
            held = now - (state.entered_at if state.entered_at is not None else now)
            if (state.below_since is not None
                    and now - state.below_since >= HP_RELEASE_DWELL_S
                    and held >= float(cfg.min_hold_s)
                    and not force_cool):
                state.latched = False
                state.entered_at = None
                state.below_since = None

    tier = 0
    if state.latched:
        tier = 2 if force_cool else 1
    state.tier = tier

    # ── 환기 래치(실외 vs 실내) — 보호 밖에서도 따뜻하게 유지한다 ────────────
    T_ext = _num(external.get('T'))
    if T is None or T_ext is None or bool(external.get('_ext_synthetic')):
        state.vent_open_ok = None
    else:
        delta = HP_VENT_CLOSE_DELTA_C if state.vent_open_ok else HP_VENT_OPEN_DELTA_C
        state.vent_open_ok = T_ext <= T - delta

    # ── 분무 래치(증발 여력·습도) ──────────────────────────────────────────────
    dep = wetbulb_depression(T, RH)
    if dep is None:
        state.fog_wb_ok = False
    else:
        state.fog_wb_ok = dep >= (HP_FOG_WETBULB_EXIT_C if state.fog_wb_ok
                                  else HP_FOG_WETBULB_ENTER_C)
    if RH is None:
        state.fog_rh_ok = False
    else:
        state.fog_rh_ok = RH < (HP_FOG_RH_BLOCK if state.fog_rh_ok
                                else HP_FOG_RH_RELEASE)

    # ── 일사 래치 ─────────────────────────────────────────────────────────────
    solar = _outdoor_solar(internal, external)
    if solar is None:
        state.sun_on = False
    else:
        state.sun_on = solar >= (HP_SHADE_SOLAR_OFF if state.sun_on else HP_SHADE_SOLAR_ON)

    if tier == 0:
        state.shade_on = False
        return HeatProtectDecision(tier=0, threshold=thr, released=prev_tier > 0)

    kinds = {p.actuator_id: getattr(p, 'kind', '') for p in profiles}
    vent_ids = frozenset(a for a, k in kinds.items() if k in VENTILATING_KINDS)
    fogger_ids = frozenset(a for a, k in kinds.items() if k == 'fogger')
    cooling_ids = cooling_foggers(profiles)
    flags = 0

    # 환기 — 실내를 모르면(stale) 아무 판정도 하지 않는다: 코디네이터 근거 21 이 제자리.
    vent_ok = None if stale else state.vent_open_ok
    open_ids = closed_ids = frozenset()
    if vent_ok is True:
        open_ids = vent_ids
        flags |= HP_FLAG_VENT_OPEN_OK
    elif vent_ok is False:
        closed_ids = vent_ids
        flags |= HP_FLAG_HOT_OUTSIDE

    # 분무
    water = bool(internal.get('_water_available', True))
    block = None
    if stale:
        block = 'stale'
        flags |= HP_FLAG_FOG_HUMID
    else:
        if not water:
            block = block or 'water'
            flags |= HP_FLAG_NO_WATER
        if not state.fog_wb_ok:
            block = block or 'wetbulb'
            flags |= HP_FLAG_FOG_WETBULB
        if not state.fog_rh_ok:
            block = block or 'humidity'
            flags |= HP_FLAG_FOG_HUMID
    fog_allowed = block is None
    if fog_allowed:
        flags |= HP_FLAG_FOG_ALLOWED

    # 하한 — 바깥이 더 더워 닫는 중인데 분무가 돌았다: 습기를 뺄 만큼은 연다.
    floor_pct = 0.0
    floor_ids = frozenset()
    if closed_ids and state.fog_ran:
        fans = frozenset(a for a in closed_ids if kinds.get(a) in _FAN_KINDS)
        floor_ids = fans or frozenset(a for a in closed_ids if kinds.get(a) == 'opening')
        if floor_ids:
            floor_pct = HP_VENT_FLOOR_PCT

    # 차광 — 한 번 친 것은 해가 있는 동안 고정이다(30 °C 근처의 들락거림이 막을
    # 흔들지 않게). 정할 때만 light_min 을 본다.
    light_yield = False
    if not state.sun_on:
        state.shade_on = False
    elif not state.shade_on:
        severe = tier >= 2 or (T is not None and T >= thr + HP_SEVERE_EXTRA_C)
        # 빛 양보 판정은 차광 판단의 주인(`screen_policy`)이 한다 — 한 곳. light_min 아래로
        # 가거나, 그 판단이 '빛 지킴'(DLI 모자람 — 직전 사이클 결론 `_shade_light_keep`)이면
        # 단계 1 에서는 치지 않는다. 심각하면 상관없이 친다.
        if not severe and (shaded_below_light_min(
                cfg.light_min, internal.get('_light_shaded_est'))
                or bool(internal.get('_shade_light_keep'))):
            light_yield = True
        else:
            state.shade_on = True
    if state.shade_on:
        flags |= HP_FLAG_SHADE_DEPLOY
    if light_yield:
        flags |= HP_FLAG_LIGHT_MIN_YIELD
    if stale:
        flags |= HP_FLAG_INDOOR_STALE

    vent_only = not any(k in ('fogger', 'cooler', 'shade') or k in _FAN_KINDS
                        for k in kinds.values())

    return HeatProtectDecision(
        tier=tier, threshold=thr,
        escalated=tier > prev_tier, released=False, stale=stale,
        vent_open_ok=vent_ok, vent_open_ids=open_ids, vent_closed_ids=closed_ids,
        fog_allowed=fog_allowed, fog_block_reason=block,
        fog_blocked_ids=(frozenset() if fog_allowed else fogger_ids),
        cooling_fog_ids=cooling_ids,
        floor_pct=floor_pct, floor_ids=floor_ids,
        shade_deploy=state.shade_on, light_min_yield=light_yield,
        flags=flags, vent_only=vent_only)


def record_dispatch(state: HeatProtectState, profiles: Iterable,
                    final_cmds: Dict) -> None:
    """이번 사이클에 분무가 **실제로 나갔는지** 기억한다(다음 사이클의 환기 하한).

    코디네이터의 요청값이 아니라 오버라이드·게이트까지 지난 최종 값으로 본다 —
    요청은 50 % 였어도 잠겨서 0 이 나갔다면 뺄 습기가 없다.
    """
    ran = False
    cooling = cooling_foggers(profiles)
    for p in profiles or []:
        # 습윤형은 세지 않는다 — 보호의 증발냉각이 아니다(`cooling_foggers`). 세면
        # 바깥이 더 더운데도 하한만큼 창을 열어 마른 외기를 들이고, 그 마른 공기가
        # VPD 제어의 살수를 다시 부른다(폐루프 hot_dry: 밤새 살수, 흘러내림 313 kg).
        if p.actuator_id not in cooling:
            continue
        cmd = (final_cmds or {}).get(p.actuator_id)
        if cmd is None:
            continue
        v = cmd.get('value', 0.0) if isinstance(cmd, dict) else getattr(cmd, 'value', 0.0)
        if (_num(v) or 0.0) > 0.0:
            ran = True
            break
    state.fog_ran = ran


# @manual ai/env-control#heat-protect
def apply_heat_protect_overrides(decision: Optional[HeatProtectDecision],
                                 profiles: Iterable, final_cmds: Dict,
                                 mode: str = 'pi',
                                 skip_ids: Iterable = ()) -> Dict[str, dict]:
    """보호 조치 중 **PI 가 다루지 않는 것**을 최종 명령에 싣는다 → 실은 것.

    mode='pi'     정상 사이클. 환기·분무는 코디네이터가 파킹·하한으로 이미 다뤘고
                  (적분이 그 사실을 안다), 유동팬은 `_apply_mixing_actuators` 가 켠다.
                  여기서는 난방 0 · 차광 전개 · (단계 2) 냉방 100 · (단계 2, 바깥이 더
                  시원) 환기 100 만 건다.
    mode='direct' PI 를 거치지 않는 경로(안전 게이트 발동 · 운전 시간대 밖). 되먹임이
                  없으므로 정해진 값으로 낸다 — 환기 100 또는 하한/0, 분무 0, 냉방 100,
                  유동팬 100, 난방 0, 차광 전개. `skip_ids`(게이트가 이미 명령한 장치)는
                  건드리지 않는다 — 강우·강풍 폐쇄가 이긴다.

    수동 잠금 장치는 건너뛴다.
    """
    out: Dict[str, dict] = {}
    if decision is None or not decision.active:
        return out
    direct = (mode == 'direct')
    skip = set(skip_ids or ())
    for p in profiles or []:
        aid = p.actuator_id
        if aid in skip:
            continue
        lock = getattr(p, 'manual_lock', None)
        if lock is not None and lock.is_active():
            continue
        kind = getattr(p, 'kind', '')
        val = None
        if kind == 'heater':
            val = 0.0
        elif kind == 'cooler':
            if direct or decision.tier >= 2:
                val = 100.0
        elif kind == 'shade':
            if decision.shade_deploy:
                val = 0.0
        elif (not direct and decision.tier >= 2 and kind in VENTILATING_KINDS
              and aid in decision.vent_open_ids):
            # 단계 2(하드 상한) · 바깥이 더 시원하다 — 환기(창·흡배기팬) 100. 냉방기와 같은
            # 판단이다: 심각 단계에서는 모델이 아니라 능력 전부를 쓴다. 폐루프 extreme_tunnel
            # (가상 터널팬 DB, 2026-10-09): 제어기 모델은 "창이 열리면 벽면 팬은 무력하다" 라
            # 팬을 0 에 세워 두었고(근거 21), 실제 개구는 그 모델보다 훨씬 작아 실내가 50 °C 를
            # 넘었다. 습도 하한(humid_min)의 팬 끄기보다 뒤에 걸리므로 그것도 이긴다 — 47 °C
            # 에서 습도를 지키려고 환기를 끄는 것은 맞바꿀 거래가 아니다. 강우·강풍 게이트는
            # 여전히 마지막에 이긴다.
            val = 100.0
        elif direct and kind == 'circulation_fan':
            val = 100.0
        elif direct and kind == 'fogger':
            val = 0.0
        elif direct and kind in VENTILATING_KINDS:
            if aid in decision.vent_open_ids:
                val = 100.0
            elif aid in decision.vent_closed_ids:
                val = decision.floor_pct if aid in decision.floor_ids else 0.0
        if val is None:
            continue
        cmd = {'value': val, 'reason': HEAT_PROTECT_REASON}
        final_cmds[aid] = cmd
        out[aid] = cmd
    return out


def describe(decision: HeatProtectDecision) -> str:
    """사람이 읽는 한 줄(진입·전환 로그용)."""
    parts: List[str] = ['단계 %d' % decision.tier]
    if decision.stale:
        parts.append('실내 값 끊김 — 유지 중')
    if decision.vent_open_ok is True:
        parts.append('환기 가능(바깥이 더 시원)')
    elif decision.vent_open_ok is False:
        parts.append('바깥이 더 더움 — 환기 닫음'
                     + (' (하한 %.0f %%)' % decision.floor_pct if decision.floor_pct else ''))
    parts.append('분무 허용' if decision.fog_allowed
                 else '분무 차단(%s)' % decision.fog_block_reason)
    if decision.shade_deploy:
        parts.append('차광 전개')
    elif decision.light_min_yield:
        parts.append('광량 하한 때문에 차광 보류')
    return ' · '.join(parts)
