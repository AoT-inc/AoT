# coding=utf-8
"""
env_control/safety_gates.py — 안전 게이트 프레임워크 (P8).

P8 원칙: 안전은 조율 알고리즘 외부에 있다.
  - Pre-Gate: L1~L3 진입 전 평가. 발동 시 조율 우회 → 직접 강제 명령 생성.
  - Post-Gate: L3 결과를 L4 전달 전 정합성 검사·보정.

Phase A 에서는 호출 지점을 확보하고 기본 구현체를 제공한다.
각 Gate 조건의 임계값은 Function custom_options 로 사용자 설정 가능.

참조: docs/dev/integrated_env_control_design.md §6
"""

from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from .log_channels import (
    GATE_BIT_RAIN, GATE_BIT_WIND, GATE_BIT_EXT_EXP,
    GATE_BIT_INT_EXP, GATE_BIT_COLD,
    GATE_BIT_FOG_SUNBURN, GATE_BIT_RAIN_LIGHT, GATE_BIT_WIND_LIGHT,
    GATE_BIT_FROST, GATE_BIT_FROST_WATCH,
    REASON_SAFETY_PRE_GATE, REASON_SAFETY_POST_GATE, REASON_RAIN_RESTRICT,
    REASON_WIND_RESTRICT, REASON_FROST_PROTECT,
    write_decision_log, CH_SAFETY_GATE,
)
from .types import (
    ActuatorProfile, EnvContext, ManualLockState, VENTILATING_KINDS,
)

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Gate 발동 결과
# ─────────────────────────────────────────────────────────────────────────────

def _first_num(*values):
    """앞에서부터 **숫자인 첫 값**, 없으면 None.

    `dict.get(k, 기본)` 은 키가 있고 값이 None 이면 기본을 쓰지 않는다. 실내
    측정이 없는 사이클의 `T`/`T_max` 가 그 모양이라, 폴백을 기본값 인자로
    적어 두면 그 자리에 닿지 못한 채 None 이 비교식으로 흘러간다.
    """
    for v in values:
        if v is None:
            continue
        try:
            return float(v)
        except (TypeError, ValueError):
            continue
    return None


@dataclass
class GateResult:
    triggered: bool = False
    gate_mask: int = 0                              # 활성 게이트 비트마스크
    forced_commands: Dict[str, dict] = field(default_factory=dict)
    # {actuator_id: {'value': float, 'reason': int, 'ttl': float}}
    description: str = ''
    partial: bool = False
    # True 일 경우: triggered=False 라도 forced_commands 가 비어있지 않을 수 있다.
    # 호출자는 L1~L3 를 정상 실행하고 마지막 단계에서 forced_commands 를 override 로 적용해야 한다.
    # 예: 풍향 차등 폐쇄 — windward openings 만 강제 폐쇄, leeward 는 정상 운용.
    vent_open_ceiling: bool = False
    # True: 강우·풍속을 **잃었다**(전에 받던 값이 끊겼다). 개구부는 제자리 또는
    # 닫기만 하고 **더 열지 않는다.** 강제 명령이 아니라 코디네이터에게 주는
    # 제약이다 — 호출자는 `situation.context['vent_open_ceiling']` 로 넘겨
    # coordinate() 안에서 걸어야 한다. 밖에서 명령을 자르면 적분이 그 사실을
    # 모른 채 감겨, 풀리는 순간 창이 튄다(`coordinator` 2.6 주석 참조).
    vent_caps: Dict[str, Optional[float]] = field(default_factory=dict)
    # 강우 **단계 제한**(근거 52)의 개구부 상한 {actuator_id: 상한 % | None}.
    # 숫자 = 그 개도 위로 열지 않는다(측창 30 %), None = 지금 개도 위로 열지 않는다
    # (약한 예보 강우의 천창). 강제 명령이 아니다 — 호출자가
    # `situation.context['vent_open_caps']` 로 coordinate() 안에서 걸고(적분이 상한을
    # 안다), 최종 오버라이드에서 숫자 상한을 한 번 더 자른다(극한 고온 보호도 상한을
    # 못 넘는다). 닫는 개구부(천창)는 `forced_commands` 에 0 으로 실린다.
    vent_cap_reasons: Dict[str, int] = field(default_factory=dict)
    # 상한마다 그 근거 {actuator_id: 52(비) | 55(바람) | 56(서리)} — 상한에 걸린 명령의 근거가
    # 된다. 없는 id 는 52 로 본다(예전 호출자). 강풍 1단계(근거 55)의 상한도 같은 자리에 싣는다 —
    # 둘이 겹치면 낮은 쪽이다. 서리 주의의 "더 열지 않음"이 여기서 56 을 단다 — 52 로 두면 화면이
    # "비 때문에 제한" 이라고 거짓을 말한다.
    frost_level: int = 0
    # 서리 단계(`FROST_LEVEL_*`) — 0 없음 · 1 주의 · 2 보호. 호출자가 사이클 안내·알림·열 보호와의
    # 배타(`internal['_frost_level']`)에 쓴다.


# **값을 잃었다**는 게이트 — 비상이 아니라 제약이다. 강제 명령을 만들지 않고,
# TTL 도 잡지 않으며, 이것만 서 있으면 L1~L3 가 정상 실행된다.
_GATE_BITS_LOST = GATE_BIT_EXT_EXP | GATE_BIT_INT_EXP
# 강우 단계 제한도 같은 무리다 — 제어는 돌고 개구부만 묶는다. TTL(전체 홀드)을 잡지
# 않는다: 잡으면 비가 그친 뒤 300초 동안 L1~L3 가 통째로 멈춘다. 단계 자체의 유지는
# `_latch_rain_level` 이 맡는다.
# 강풍 1단계(`GATE_BIT_WIND_LIGHT`)도 같다 — 단계 유지는 `_latch_wind_level` 이 맡는다.
_GATE_BITS_SOFT = (_GATE_BITS_LOST | GATE_BIT_RAIN_LIGHT | GATE_BIT_WIND_LIGHT
                   | GATE_BIT_FROST_WATCH)


# ─────────────────────────────────────────────────────────────────────────────
# 강우 — 출처(실측·예보 모델)와 세기로 단계를 가른다 (2026-10-10 구마모토)
# ─────────────────────────────────────────────────────────────────────────────
# 예전에는 강우 값 하나가 `rain_threshold`(0.5) 를 넘으면 **개구부 전부**를 닫고
# L1~L3 를 건너뛰었다. 그 값이 강우계가 아니라 예보 모델(Open-Meteo 시간 강수
# 0.3~1.0 mm)이어도 같았다 — 구마모토 2026-10-10 12~16시·17시~ 실내 29~30 °C(극한 고온
# 보호 1단계)인데 창이 전부 닫혀 있었다. 모델 강수는 "이 격자 이 시간에 비가 올
# 수도 있다" 이지 "지금 여기 비가 들이친다" 가 아니다.
#
# 단계(높을수록 엄격):
#   NONE       제한 없음
#   HOLD_ROOF  천창 상한 RAIN_ROOF_FORECAST_CAP_PCT(넘으면 그만큼 닫는다). 측창은 그대로.
#   RESTRICT   천창 닫음(0) · 측창 상한 RAIN_SIDE_CAP_PCT(풍상측 측창은 닫음)
#   CLOSE      개구부 전부 닫음 — 예전 강우 게이트 그대로(L1~L3 건너뜀)
#
# 출처 판정은 `aot.utils.inputs.rain_origin_of`(드라이버의 `data_origin`) 하나다.
# **모르면 실측**이다 — 실측 쪽이 엄격하므로 판정 실패가 보호를 줄이지 않는다.
#
# ⚠ 단위 — 여기 오는 강우 값은 **mm/h**(감우기는 0/1)다. 상류(`read_outdoor_sensors`·수집기)가
#   채널마다 바꿔 준다(`aot.utils.inputs.rain_unit_scale`: 15 분 누적 ×4, 시간 합 ×1, 모르는
#   단위는 그대로). 감우기의 1 은 약한 비가 아니라 "비" 이므로 실측의 "약한 비"(< 1.0)가
#   아니다 — 전부 닫는다. 같은 자리의 실측·예보는 상류에서 섞지 않는다(실측이 있으면 실측만).
RAIN_LEVEL_NONE      = 0
RAIN_LEVEL_HOLD_ROOF = 1
RAIN_LEVEL_RESTRICT  = 2
RAIN_LEVEL_CLOSE     = 3

RAIN_ORIGIN_MODEL    = 'model'
RAIN_ORIGIN_MEASURED = 'measured'

# 예보 모델 강수가 이 값 이상이면 천창을 상한(RAIN_ROOF_FORECAST_CAP_PCT)까지만 연다(모델 최소 분해능 0.1 mm).
RAIN_MODEL_HOLD_MM      = 0.1
# 약한 예보 강수(HOLD_ROOF) 동안 천창의 열림 상한(%). 예전에는 "더 열지 않음"(지금 개도)이라
# 이미 65 % 로 열려 있던 천창이 예보 비 내내 그대로였다(구마모토 2026-10-10 리플레이) —
# 예보가 맞으면 빗물이 든다. 사용자 결정(2026-10-10): 천창도 30 % 상한.
RAIN_ROOF_FORECAST_CAP_PCT = 30.0
# 예보 모델 강수가 이 값(과 사용자 `rain_threshold` 중 큰 것) 이상이면 천창을 닫고 측창은
# 상한까지만 — 모델 강수만으로는 개구부를 **전부** 닫지 않는다.
RAIN_MODEL_CLOSE_MM     = 1.0
# 실측 강우가 문턱 이상이어도 이 값 **미만**이고 바람이 고요하면(아래) 천창만 닫고 측창은
# 상한까지 둔다. 이 값 이상(감우기 1 포함)·바람·풍속 모름·값 끊김이면 전부 닫는다.
RAIN_MEASURED_LIGHT_MAX = 1.0
# 비가 옆으로 들이치지 않는다고 볼 풍속(m/s). 실측 약한 비의 완화는 풍속을 **이번에 잰**
# 값이 이보다 작을 때만이다. 예보 강우에서는 이 이상이면 풍상측 측창을 닫는다.
RAIN_CALM_WIND_MS       = 2.0
# 단계 제한 중 측창의 열림 상한(%).
RAIN_SIDE_CAP_PCT       = 30.0
# 단계 제한을 **내리는** 데 걸리는 최소 시간(초) — `gate_ttl` 과 큰 쪽. 코디네이터 주기가
# 600초면 gate_ttl(300)로는 다음 사이클에 이미 풀려 유지가 없는 것과 같다. 약한 실측 비는
# 끊겼다 이어지고, 예보 강수는 시간 경계에서 0.9/1.0 을 오간다 — 그때마다 천창이 닫혔다
# 열리면 모터 이동만 는다.
RAIN_LEVEL_HOLD_S       = 1800.0


# @manual ai/env-control#safety-gates
def classify_rain(rain: Optional[float], origin: Optional[str],
                  wind: Optional[float], *, threshold: float,
                  rain_lost: bool = False, wind_lost: bool = False) -> int:
    """강우 값 → 단계(`RAIN_LEVEL_*`). 순수 함수다.

    rain:   강우 값(잃었으면 마지막 값 — 규칙 A 의 래치). None·0 이하 = 비 없음.
    origin: 'model' 이면 예보 모델, 그 밖(None 포함)은 실측.
    wind:   **이번에 잰** 풍속(잃었으면 마지막 값), 풍속 센서가 없으면 None.
    threshold: 사용자 강우 문턱(`PreGateConfig.rain_threshold`).
    rain_lost·wind_lost: 값을 잃고 마지막 값으로 보는 중(규칙 A).

    규칙 A(오래된 값은 닫는 쪽으로만): 잃은 **실측** 강우는 완화 없이 닫는다. 잃은
    예보 강우는 같은 모델 규칙으로 보되(그것도 닫거나 묶는 쪽뿐이다) 호출자가
    "더 열지 않음"(EXT_EXP)을 따로 건다.
    """
    if rain is None:
        return RAIN_LEVEL_NONE
    try:
        r = float(rain)
    except (TypeError, ValueError):
        return RAIN_LEVEL_NONE
    if not math.isfinite(r) or r <= 0.0:
        return RAIN_LEVEL_NONE
    if origin == RAIN_ORIGIN_MODEL:
        if r >= max(RAIN_MODEL_CLOSE_MM, float(threshold)):
            return RAIN_LEVEL_RESTRICT
        if r >= RAIN_MODEL_HOLD_MM:
            return RAIN_LEVEL_HOLD_ROOF
        return RAIN_LEVEL_NONE
    if r < float(threshold):
        return RAIN_LEVEL_NONE
    calm = (wind is not None and not wind_lost
            and float(wind) < RAIN_CALM_WIND_MS)
    if rain_lost or not calm or r >= RAIN_MEASURED_LIGHT_MAX:
        return RAIN_LEVEL_CLOSE
    return RAIN_LEVEL_RESTRICT


# ─────────────────────────────────────────────────────────────────────────────
# 강풍 — 10분 평균과 돌풍으로 단계를 가르고, 내려갈 때는 여유와 시간을 둔다
# (2026-10-10 폭풍 시뮬 `foehn_dry_wind`·`squall_heat`)
# ─────────────────────────────────────────────────────────────────────────────
# 예전에는 풍속이 `wind_threshold`(12 m/s)를 넘는 사이클에 개구부 **전부**를 닫고, 문턱
# 아래로 내려온 다음 사이클(gate_ttl 300 s 뒤)에 풀었다. 푄(10분 평균 10~12 m/s 정속 +
# 돌풍)에서는 문턱을 오가며 하루 여섯 번 전부 닫혔다 열렸고, 맑은 한낮에는 한 사이클에
# 실내가 32 → 42 °C 로 튀었다. 반대로 10분 평균이 문턱 아래인 동안 돌풍이 15 m/s 를 넘어도
# (84 분) 창은 다 열려 있었다 — 돌풍 입력이 없었다. 풍향별 닫기는 개구부 방위각이 전부
# 있어야만 섰는데, 김제 측창 둘 다 방위각이 없어 한 번도 서지 못했다.
#
# 단계(높을수록 엄격):
#   NONE      제한 없음
#   RESTRICT  1단계 — 평균 ≥ 문턱×WIND_L1_MEAN_FRAC 또는 돌풍 ≥ 문턱×WIND_L1_GUST_FRAC.
#             풍상측 개구부 닫음 · 방위각(또는 풍향)을 모르는 천창 닫음 · 그 밖의 천창 상한
#             WIND_ROOF_CAP_PCT · 측창 상한 WIND_SIDE_CAP_PCT. 제어는 돈다(근거 55).
#   CLOSE     2단계 — 평균 ≥ 문턱 또는 돌풍 ≥ 문턱×WIND_L2_GUST_FRAC. 개구부 전부 닫음(예전
#             강풍 게이트, L1~L3 건너뜀). 극한 고온 보호도 못 연다.
#
# 기준은 사용자 `wind_threshold` 하나다 — 나머지 문턱은 그 배수라 문턱을 옮기면 같이 움직인다.
#
# 돌풍 채널이 없으면 **추정하지 않는다.** 10분 평균 대비 돌풍 계수는 평지 1.3~1.5(거친 지면은
# 더 크다)라 1단계의 평균 문턱 0.6 은 계수 1.5 를 가정한 돌풍 0.9 와 같은 자리다 — 추정 돌풍은
# 1단계에서는 평균 문턱과 겹칠 뿐이고, 2단계에 쓰면 잰 적 없는 돌풍으로 한낮 창을 전부 닫는다
# (평균 10 m/s 면 추정 15 → 푄 낮 내내 2단계). 2단계로 가는 돌풍은 **잰 값**뿐이다.
#
# 내려가기(2026-10-12 바꿈): 그 단계가 (다시) 선 뒤 **최근 WIND_LEVEL_HOLD_S 의 표본 평균**(평균 풍속과
# 잰 돌풍 각각)이 지금 단계 문턱의 WIND_RELEASE_FRAC 배 아래면 한 단계 내려간다. 올라가기는 즉시이고,
# 지금 단계의 들어가는 문턱을 다시 넘으면 창을 처음부터 다시 연다. 값을 잃으면 창을 비운다 — 오래된
# "잔잔함" 은 여는 근거가 아니다(규칙 A).
#   예전에는 "내려가는 문턱 아래 20 분 **연속**" 이었다. 폭풍 시뮬 `foehn_dry_wind` 이튿날 10분 평균이
#   9.6~11 m/s 로 10.2 언저리를 오가자 한 번 위로 튈 때마다 시계가 다시 서서, 맑은 31 °C 아래 개구부가
#   80 분 전부 닫혔다(실내 44 °C, 40 °C 초과 22 → 258 분). 평균은 한 번 튄 값을 묽힐 뿐 시계를 세우지 않는다.
#
# 고온 빠른 내림(2 → 1): 실내가 극한 고온 보호 문턱 이상이거나 보호 단계가 서 있으면(`_wind_hot`) 2단계
# 근거(평균 ≥ 문턱 · 잰 돌풍 ≥ 문턱×WIND_L2_GUST_FRAC)가 사라진 **첫 사이클**에 1단계로 내린다 — 풍상측은
# 닫힌 채, 천창 30 %·측창 50 % 상한으로 연다. 2단계 근거가 다시 서면 즉시 전부 닫는다(구조 안전은 들어가는
# 문턱이 지킨다 — 유지 시간은 들락거림을 막는 장치이지 안전 여유가 아니다). 값을 잃었으면 하지 않는다
# (규칙 A). 1 → 0 은 빠르지 않다 — 1단계 근거가 남은 바람에 상한을 푸는 일은 없다.
WIND_LEVEL_NONE     = 0
WIND_LEVEL_RESTRICT = 1
WIND_LEVEL_CLOSE    = 2

# 1단계 문턱 — 문턱(기본 12 m/s)의 배수: 평균 7.2 m/s · 돌풍 10.8 m/s.
WIND_L1_MEAN_FRAC  = 0.6
WIND_L1_GUST_FRAC  = 0.9
# 2단계의 돌풍 문턱 — 평균 문턱의 1.5 배(기본 18 m/s). 1단계와 같은 돌풍 계수(1.5)로 맞춘 자리다
# (평균 1 배 ↔ 돌풍 1.5 배). ⚠ 1.25 배(15 m/s)로 두지 말 것 — 돌풍계 값은 10분 **최대** 돌풍이라
# 평균 10 m/s 의 푄에서 늘 13~17 m/s 이고, 내려가는 문턱(×0.85 = 12.75)을 영영 못 내려가 시뮬
# `foehn_dry_wind_gust` 에서 개구부가 33 시간 내내 닫혔다(실내 최고 45.4 °C, 35 °C 초과 6969 °C·분 —
# 1.5 배면 평균만 볼 때와 같은 35 사이클, 2026-10-10). 문턱 아래 돌풍은 1단계 상한이 맡는다.
WIND_L2_GUST_FRAC  = 1.5
# 내려가는 문턱 = 들어가는 문턱 × 이 값(기본 2단계 → 평균 10.2·돌풍 15.3 m/s 아래). 띠는 좁아도
# 된다 — 돌풍 섞인 분 단위 들락거림은 아래 평균 창이 거른다.
WIND_RELEASE_FRAC  = 0.85
# 풀림 평균 창(초) — 단계가 선 **뒤**의 표본이 이만큼을 덮어야 평균을 본다(600 s 주기면 세 표본: 선 뒤
# 30 분이 가장 이르다, 예전 "20 분 연속" 과 같은 자리).
WIND_LEVEL_HOLD_S  = 1200.0
# 주기 흔들림 여유(초) — 창 길이를 이만큼 넘는 표본까지 넣고, 덮었는지는 이만큼 모자라도 인정한다.
WIND_WINDOW_SLACK_S = 60.0
# 1단계 상한(%) — 천창은 비가 아니어도 바람을 정면으로 받는 자리라 낮게, 측창은 반만.
WIND_ROOF_CAP_PCT  = 30.0
WIND_SIDE_CAP_PCT  = 50.0


def _finite_or_none(v) -> Optional[float]:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


# @manual ai/env-control#safety-gates
def classify_wind(wind: Optional[float], gust: Optional[float], *,
                  threshold: float) -> int:
    """10분 평균 풍속·돌풍 → 단계(`WIND_LEVEL_*`). 순수 함수다.

    wind:  10분 평균 풍속(m/s). None·숫자 아님 = 바람 없음(센서 없는 설치).
    gust:  **잰** 돌풍(m/s). 없으면 None — 추정하지 않는다(위 주석).
    threshold: 사용자 강풍 문턱(`PreGateConfig.wind_threshold`). 내려가는 문턱을 볼 때는
      호출자가 `threshold × WIND_RELEASE_FRAC` 를 넘긴다(문턱이 전부 그 배수다).
    """
    try:
        th = float(threshold)
    except (TypeError, ValueError):
        return WIND_LEVEL_NONE
    if not math.isfinite(th) or th <= 0.0:
        return WIND_LEVEL_NONE
    w = _finite_or_none(wind)
    g = _finite_or_none(gust)
    if (w is not None and w >= th) or (g is not None and g >= th * WIND_L2_GUST_FRAC):
        return WIND_LEVEL_CLOSE
    if ((w is not None and w >= th * WIND_L1_MEAN_FRAC)
            or (g is not None and g >= th * WIND_L1_GUST_FRAC)):
        return WIND_LEVEL_RESTRICT
    return WIND_LEVEL_NONE


@dataclass
class WindState:
    """강풍 단계의 기억 — 재시작을 넘는다(`cycle_memory`, 코디네이터 속성 `_wind_state`).

    level:   지금 단계(`WIND_LEVEL_*`).
    since:   그 단계가 (다시) 선 시각 — 풀림 평균 창은 이 **뒤**의 표본만 본다. None = 모름(지금부터 센다).
    samples: 잃지 않은 사이클의 표본 [시각, 10분 평균, 잰 돌풍|None] — 창(WIND_LEVEL_HOLD_S + 여유)
             보다 오래된 것은 버린다. 값을 잃으면 비운다(규칙 A).
    """
    level: int = WIND_LEVEL_NONE
    since: Optional[float] = None
    samples: List[list] = field(default_factory=list)


def _wind_hot(heat: Optional[dict]) -> bool:
    """강풍 2단계를 바로 1단계로 내릴 만큼 더운가 — 극한 고온 보호가 서 있거나 실내가 그 문턱 이상.

    heat: 게이트 환경의 `heat_protect`(`_build_gate_env`) — {'T': 실내 평균, 'threshold': 문턱 | None
      (보호를 껐다), 'tier': 직전 보호 단계}. 없으면 덥지 않다(예전 동작).
    문턱·래치를 여기서 다시 판정하지 않는다 — 단계는 `heat_protect` 의 것을 그대로 읽고, 문턱은 단순 비교다
    (보호의 진입 지연이 닫힌 집에서 실내를 몇 °C 더 올린 뒤에야 서는 것을 기다리지 않는다).
    """
    if not isinstance(heat, dict):
        return False
    try:
        if int(heat.get('tier') or 0) >= 1:
            return True
    except (TypeError, ValueError):
        pass
    T = _finite_or_none(heat.get('T'))
    thr = _finite_or_none(heat.get('threshold'))
    return T is not None and thr is not None and T >= thr


def _wind_window_mean(st: WindState, now: float
                      ) -> Tuple[bool, Optional[float], Optional[float]]:
    """단계가 선 뒤 최근 WIND_LEVEL_HOLD_S 표본의 평균 → (창을 덮었나, 평균 풍속, 평균 돌풍).

    창을 덮었다 = 그 단계가 선 뒤의 표본이 있고 가장 오랜 것이 창 길이(여유 빼고)만큼 지났다. 돌풍은 잰
    표본만 평균한다(하나도 없으면 None — 추정하지 않는다).
    """
    since = st.since if st.since is not None else now
    lo = now - WIND_LEVEL_HOLD_S - WIND_WINDOW_SLACK_S
    winds: List[float] = []
    gusts: List[float] = []
    oldest = None
    for s in st.samples:
        ts = _finite_or_none(s[0]) if isinstance(s, (list, tuple)) and len(s) >= 3 else None
        if ts is None or ts <= since or ts < lo or ts > now:
            continue
        oldest = ts if oldest is None else min(oldest, ts)
        w, g = _finite_or_none(s[1]), _finite_or_none(s[2])
        if w is not None:
            winds.append(w)
        if g is not None:
            gusts.append(g)
    covered = (oldest is not None
               and now - oldest >= WIND_LEVEL_HOLD_S - WIND_WINDOW_SLACK_S)
    mean = (lambda xs: sum(xs) / len(xs) if xs else None)
    return covered, mean(winds), mean(gusts)


def _merge_vent_caps(rain_caps: Dict[str, Optional[float]],
                     wind_caps: Dict[str, Optional[float]]
                     ) -> Tuple[Dict[str, Optional[float]], Dict[str, int]]:
    """강우·강풍 단계 제한의 상한을 합친다 → (상한, 근거). 같은 창이면 **낮은** 쪽이 이긴다.

    None(지금 개도 위로 열지 않음)은 숫자가 있으면 숫자에 진다 — None 은 고온일 때 풀리는
    약한 제약이라(`coordinator.rain_vent_caps`) 숫자 상한을 지우면 바람 상한까지 같이 풀린다.
    """
    caps: Dict[str, Optional[float]] = {}
    reasons: Dict[str, int] = {}
    for src, reason in ((rain_caps, REASON_RAIN_RESTRICT), (wind_caps, REASON_WIND_RESTRICT)):
        for aid, cap in (src or {}).items():
            if aid in caps:
                old = caps[aid]
                if cap is None or (old is not None and float(old) <= float(cap)):
                    continue
            caps[aid] = cap
            reasons[aid] = reason
    return caps, reasons


# ─────────────────────────────────────────────────────────────────────────────
# 서리 — 한파 비상보다 훨씬 일찍 서는 두 단계 (2026-10-10 극단 날씨 폐루프 cold_snap_frost)
# ─────────────────────────────────────────────────────────────────────────────
# 한파 비상(실외 ≤ −5 °C **그리고** 실내 ≤ 5 °C)은 −4 °C 의 맑고 바람 없는 밤에 서지 않았다 —
# 실내가 −4.1 °C 까지 내려가 작물이 392 분 얼었는데 경보도 조치도 없었다. 그 비상은 시설이
# 얼어붙는 날(배관·보온재)을 위한 것이고, 작물은 그보다 한참 일찍 상한다: 맑고 바람 없는 밤에는
# 잎·피복이 공기보다 2~4 K 낮아(복사냉각) 공기 2~4 °C 에서 잎이 이미 0 °C 다.
#
# 판정은 **실내**가 주인이다(`T_min` — 가장 찬 자리, 없으면 `T`). 단계:
#   NONE     서리 위험 없음
#   WATCH    유효 실내 ≤ 주의선(기본 4 °C) — 커튼 닫음, 개구부는 **더 열지 않음**. L1~L3 는 그대로 돈다.
#   PROTECT  유효 실내 ≤ 보호선(기본 2 °C) — 개구부·커튼 닫음, 난방 100, 유동팬 100(공기 섞음),
#            분무·CO₂·냉방 끔. 한파 비상처럼 L1~L3 를 건너뛴다.
# 유효 실내 = 실내 − (복사냉각이면 FROST_RADIATIVE_DROP_C). 복사냉각 = 실외 ≤ 2 °C · 바람 < 2 m/s ·
# 비 없음 · 해가 없음. 맑은지(구름)는 **제어기가 받지 않는다** — 모르면 맑은 것으로 본다(서리는
# 놓치는 쪽이 비싸고, 흐린 밤에 올리는 비용은 주의 단계의 커튼 닫음뿐이다).
#
# 문턱은 작물의 하드 하한(`temp_min`)을 **넘지 않는다**: 보호선 = min(2 °C, temp_min − 1 °C). 서리는
# 얼음이 맺히는 물리의 선이라 작물과 무관하게 고정하되, 어는점 근처를 견디는 작물(temp_min 이
# 그보다 낮다)을 사용자가 정한 한계보다 먼저 몰아세우지 않는다. 영양(temp_min 9 °C)은 min 이
# 2 °C 라 그대로다 — 9 °C 아래는 서리가 아니라 저온이고, 그것은 최저 온도 한계(근거 33)가 맡는다.
#
# 히스테리시스: 들어갈 때는 즉시, 나올 때는 문턱 + FROST_RELEASE_MARGIN_C 를 넘어야 하고 **그리고**
# 마지막으로 그 단계의 근거를 받은 뒤 FROST_MIN_HOLD_S 가 지나야 한다(새벽 최저 전후의 들락거림을
# 막는다). 실내를 잃으면 서 있던 단계를 FROST_STALE_MAX_S 까지 유지한다(가장 찬 시각에 센서가
# 끊겨 보호가 풀리는 것을 막는다) — 새로 서지는 않는다. 상태는 재시작을 넘는다(`cycle_memory`).
FROST_LEVEL_NONE    = 0
FROST_LEVEL_WATCH   = 1
FROST_LEVEL_PROTECT = 2

FROST_PROTECT_C          = 2.0     # 보호선 [°C, 유효 실내 이하]
FROST_WATCH_GAP_C        = 2.0     # 주의선 = 보호선 + 이만큼
FROST_TEMP_MIN_MARGIN_C  = 1.0     # 보호선은 temp_min − 이만큼을 넘지 않는다
FROST_RELEASE_MARGIN_C   = 1.0     # 나올 때 문턱에 더하는 여유
FROST_MIN_HOLD_S         = 1800.0  # 마지막 근거 이후 최소 유지
FROST_STALE_MAX_S        = 1800.0  # 실내를 잃은 채 단계를 유지하는 최대 시간
FROST_RADIATIVE_DROP_C   = 2.0     # 복사냉각 때 잎·피복이 공기보다 낮은 정도 — 유효 실내에서 뺀다
FROST_RADIATIVE_EXT_C    = 2.0     # 복사냉각을 보는 실외 상한
FROST_RADIATIVE_WIND_MS  = RAIN_CALM_WIND_MS   # 이보다 바람이 약해야 복사냉각 — 강우의 "고요" 와 같은 선
FROST_NIGHT_SOLAR_WM2    = 20.0    # 이 이상이면 해가 있다(복사냉각 아님)


@dataclass
class WeatherMemory:
    """강우·풍속의 **마지막 실측** 기억 — 재시작을 넘는다(`cycle_memory`, 코디네이터 속성 `_weather_memory`).

    seen:        {'rain'|'wind'|'wind_gust'|'wind_dir': 마지막 값}. 값이 끊겼을 때 "모른다" 와 "원래 없던
                 센서" 를 가르는 근거이자 위험 값을 이어 쥐는 래치다(`SafetyPreGate._weather_view`).
    rain_origin: 마지막 강우 값의 출처('model'|'measured').

    ⚠ 프로세스 메모리에만 두면 재시작 뒤 끊긴 센서가 '원래 없던 센서' 로 읽혀 "더 열지 않음" 천장(EXT_EXP)이
      사라진다 — 김제 육묘장3 2026-10-12 22:14: 비·바람 값이 21:56 부터 끊겨 있었는데 재시작 직후 사이클이
      측창을 15 % 열었다.
    """
    seen: Dict[str, float] = field(default_factory=dict)
    rain_origin: str = RAIN_ORIGIN_MEASURED


@dataclass
class FrostState:
    """서리 단계의 사이클 간 기억. 재시작을 넘는다(`cycle_memory`)."""
    level: int = FROST_LEVEL_NONE
    held_since: Optional[float] = None    # 마지막으로 현재 단계가 근거를 받은 시각
    stale_since: Optional[float] = None   # 실내를 잃은 시각


@dataclass
class FrostDecision:
    level: int = FROST_LEVEL_NONE
    prev_level: int = FROST_LEVEL_NONE
    T_eff: Optional[float] = None         # 유효 실내 온도(복사냉각 보정 뒤)
    radiative: bool = False
    stale: bool = False
    watch_c: float = FROST_PROTECT_C + FROST_WATCH_GAP_C
    protect_c: float = FROST_PROTECT_C

    @property
    def changed(self) -> bool:
        return self.level != self.prev_level


# @manual ai/env-control#frost
def frost_thresholds(temp_min: Optional[float] = None) -> Tuple[float, float]:
    """(주의선, 보호선) [°C]. 보호선 = min(2 °C, temp_min − 1 °C), 주의선 = 보호선 + 2 °C.

    temp_min 을 모르면(None·숫자 아님) 기본선이다.
    """
    protect = FROST_PROTECT_C
    try:
        tm = None if temp_min is None else float(temp_min)
    except (TypeError, ValueError):
        tm = None
    if tm is not None and math.isfinite(tm):
        protect = min(protect, tm - FROST_TEMP_MIN_MARGIN_C)
    return protect + FROST_WATCH_GAP_C, protect


def is_radiative_night(T_ext: Optional[float], wind: Optional[float],
                       rain: Optional[float], light: Optional[float]) -> bool:
    """맑고 바람 없는 찬 밤인가(복사냉각). 순수 함수다.

    T_ext·wind: 실외 기온·풍속(모르면 False / 풍속은 센서가 없으면 0 으로 들어온다).
    rain: 비가 오면(>0) 구름이 있다 — 복사냉각이 아니다.
    light: 해의 세기 W/m²(측정, 없으면 맑은 하늘 어림). None(둘 다 모름)이면 밤으로 본다 —
           서리는 놓치는 쪽이 비싸다.
    """
    if T_ext is None or T_ext > FROST_RADIATIVE_EXT_C:
        return False
    if wind is not None and wind >= FROST_RADIATIVE_WIND_MS:
        return False
    if rain is not None and rain > 0.0:
        return False
    if light is not None and light >= FROST_NIGHT_SOLAR_WM2:
        return False
    return True


# @manual ai/env-control#frost
def evaluate_frost(state: FrostState, T_int: Optional[float], radiative: bool,
                   temp_min: Optional[float], now: float) -> FrostDecision:
    """이번 사이클의 서리 단계 → `FrostDecision`. `state` 를 제자리에서 고친다. 순수 함수다.

    T_int: 실내 최저(`T_min`, 없으면 `T`). None 이면 새로 서지 않고 서 있던 단계만 유지한다.
    """
    watch_c, protect_c = frost_thresholds(temp_min)
    prev = int(state.level or FROST_LEVEL_NONE)
    if T_int is None:
        if prev:
            if state.stale_since is None:
                state.stale_since = now
            if now - state.stale_since >= FROST_STALE_MAX_S:
                state.level = FROST_LEVEL_NONE
                state.held_since = None
                state.stale_since = None
            else:
                return FrostDecision(level=prev, prev_level=prev, stale=True,
                                     radiative=radiative, watch_c=watch_c,
                                     protect_c=protect_c)
        return FrostDecision(level=state.level, prev_level=prev, stale=False,
                             radiative=radiative, watch_c=watch_c, protect_c=protect_c)

    state.stale_since = None
    eff = float(T_int) - (FROST_RADIATIVE_DROP_C if radiative else 0.0)
    m = FROST_RELEASE_MARGIN_C
    if eff <= protect_c + (m if prev >= FROST_LEVEL_PROTECT else 0.0):
        target = FROST_LEVEL_PROTECT
    elif eff <= watch_c + (m if prev >= FROST_LEVEL_WATCH else 0.0):
        target = FROST_LEVEL_WATCH
    else:
        target = FROST_LEVEL_NONE
    if target >= prev:
        state.level = target
        state.held_since = now if target else None
    else:
        held = state.held_since if state.held_since is not None else now
        if now - held >= FROST_MIN_HOLD_S:
            state.level = target
            state.held_since = now if target else None
    return FrostDecision(level=state.level, prev_level=prev, T_eff=eff,
                         radiative=radiative, watch_c=watch_c, protect_c=protect_c)


# ─────────────────────────────────────────────────────────────────────────────
# Pre-Gate 설정
# ─────────────────────────────────────────────────────────────────────────────

# @manual ai/env-control#pre-gate-checked-before-l1l3, ai/env-control#safety-gates
@dataclass
class PreGateConfig:
    """사용자 설정 가능한 Pre-Gate 임계값."""
    rain_threshold:       float = 0.5    # 강우 임계 mm/h (감우기 0/1 은 1 이 넘는다) — 상류가 mm/h 로 맞춘다
    # 강풍 문턱(10분 평균, m/s) — 2단계(전부 닫음)의 평균 문턱이자 1단계·돌풍·해제 문턱의 기준
    # (`classify_wind`). 이 하나만 사용자 설정이다.
    wind_threshold:       float = 12.0   # m/s
    # 실외 온습도의 **승계 유예**(초) — 이 시간 동안은 마지막 실측을 그대로 쓰고,
    # 넘으면 `build_fallback_context` 로 넘긴다(`_cycle_mixin` P2-2).
    # ⚠ **게이트는 이 값으로 나이를 재지 않는다**(2026-09-19). 값이 쓸 만한가는
    #   `measurement_freshness.effective_max_age`(장치값 > 요청 > 주기 파생)가
    #   장치마다 이미 정했고, 게이트는 그 결과(값이 왔는가)만 본다. 여기서 한
    #   번 더 재면 판정이 두 벌이 되고 느슨한 쪽이 실질이 된다.
    ext_context_max_age:  float = 300.0
    # ⚠ `int_sensor_max_age` 는 **없다**(2026-09-20 제거). 실내 만료도 실외와
    #   같은 규칙으로 옮겼다 — 값이 쓸 만한가는 `measurement_freshness` 가
    #   센서마다 이미 정하고, 게이트는 그 결과(값이 왔는가)만 본다. 게다가 그
    #   타이머는 한 번도 돈 적이 없었다: 호출자가 `last_int_ts` 에 매번
    #   `time.time()` 을 실어 보내 나이가 언제나 0 이었다.
    # 한파 외부 문턱의 **정본은 여기 하나**다(2026-09-27). 예전에는 기본값이
    # −2 °C 인데 `EnvCoordinator.initialize` 가 −5 °C 를 따로 넘겨, 운영(과 매뉴얼)은
    # −5 로 돌고 인자 없이 만드는 곳(IEC 미리보기·테스트)은 다른 문턱으로 돌았다.
    # 호출자는 이 값을 넘기지 않는다.
    #
    # ⚠ **폭염 비상 게이트는 없다**(2026-10-09 폐지). 실외 ≥45 °C **그리고** 실내
    #   ≥35 °C 에서 창 100 · 차광 · 냉방 100 을 강제했는데, 그 조건에서는 대개 바깥이
    #   더 덥다 — 창 100 은 물리적으로 반대 방향이었다. 고온은 극한 고온 보호
    #   (`heat_protect`)가 사용자 문턱(기본 실내 30 °C)에서 맡는다: 바깥이 더 시원할
    #   때만 열고, 분무는 증발 여력이 있을 때만, 차광·냉방은 같은 자리에서. 여기에
    #   `heat_*_threshold` 를 되살리지 말 것 — 판정이 두 벌이 된다.
    cold_ext_threshold:   float = -5.0   # 한파: 외부 온도 임계 (°C)
    cold_int_threshold:   float = 5.0    # 한파: 내부 온도 임계 (°C)
    gate_ttl:             float = 300.0  # 게이트 발동 후 최소 유지 시간 (초)
    # 한파 **해제 여유**(°C). 들어가는 문턱과 나오는 문턱을 나눈다 — 문턱 바로
    # 위아래에서 값이 흔들리면 300 초 유지(gate_ttl)만으로는 5 분마다 전 장비가
    # 비상 운전과 정상 운전을 오간다. 들어갈 때는 두 조건(실외·실내)이 모두 문턱을
    # 넘어야 하고, 나올 때는 둘 중 하나라도 문턱에서 이만큼 물러나야 한다.
    cold_release_margin:  float = 2.0
    windward_arc_deg:     float = 60.0   # 풍향 ±이 각도 이내 = windward (강제 폐쇄 대상)
    # ── 육묘 일소 방지 (2026-07-31 aot-005) ───────────────────────────────
    nursery_mode:         bool  = False  # 육묘장 모드 — 습윤형 분무 일사 잠금
    nursery_solar_lockout: float = 250.0  # 실내 추정 광량 이 값 이상이면 분무 금지 (W/m²)
    nursery_solar_release: float = 150.0  # 이 값 미만으로 내려가야 잠금 해제 (히스테리시스)
    nursery_evening_fog:  bool  = True   # 일몰 전 분무 허용 여부 (끄면 야간 습윤 차단)


# @manual ai/env-control#settings-hvac
def is_wetting_fogger(profile: ActuatorProfile) -> bool:
    """이 액추에이터가 잎을 적시는 분무기인가.

    시설 도면의 노즐 배치에서 산출된 capacity_meta['nozzle']['wetting'] 을
    따른다. 노즐 정보가 없으면 (수동 등록 등) 보수적으로 습윤형으로 본다 —
    육묘장 모드를 켠 사용자의 의도는 "확실치 않으면 뿌리지 말 것"이다.
    """
    if getattr(profile, 'kind', None) != 'fogger':
        return False
    cap = getattr(profile, 'capacity_meta', None) or {}
    nozzle = cap.get('nozzle')
    if not nozzle:
        return True
    return bool(nozzle.get('wetting'))


# ─────────────────────────────────────────────────────────────────────────────
# Pre-Gate
# ─────────────────────────────────────────────────────────────────────────────

# @manual ai/env-control#pre-gate-checked-before-l1l3, ai/env-control#safety-gates
class SafetyPreGate:
    """L1~L3 진입 전 안전 검사.

    evaluate() 를 매 사이클 호출.
    GateResult.triggered == True 이면 forced_commands 를 그대로 L4 에 전달하고
    L1~L3 를 건너뛴다.

    게이트 해제 후 L3 적분의 무충격 복귀는 호출자가 맡는다 — 게이트가 움직인
    장치의 평형 기억을 게이트가 둔 위치로 맞춘다(`_cycle_mixin.
    _rebase_integral_after_gate`, 2026-09-22). `reset_after_release()` 는 이
    객체의 래치만 푸는 것이라 그 일과 무관하다.
    """

    def __init__(self, config: PreGateConfig = None):
        self.config = config or PreGateConfig()
        self._last_triggered = False
        self._triggered_until: float = 0.0  # gate_ttl 보장용
        self._nursery_locked = False        # 육묘 일소 잠금 래치 (히스테리시스)
        self._cold_latched = False          # 한파 래치 (cold_release_margin)
        # 잠금 사유 — 'sunburn'(광량 임계) | 'evening'(저녁 잎마름병 방지) | None.
        # ⚠ **`_nursery_locked` bool 하나로는 화면에 거짓말을 하게 된다.**
        #   저녁 차단은 광량과 **무관하게** 잠그는데, 이 값이 없으면 호출자가
        #   무조건 "햇빛에 잎이 델 수 있어" 라고 말한다 — 비 오는 밤에도 그
        #   문장이 나갔다(2026-08-28 사용자 지적: 강우 중 "일소" 안내는 모순).
        self._nursery_lock_reason: str | None = None
        # 강우·풍속의 **마지막 실측** — {'rain': 값, 'wind': 값, 'wind_dir': 값}.
        # 값이 끊겼을 때 "모른다" 와 "원래 없던 센서" 를 가르는 근거이자,
        # 끊기기 직전이 위험했는지를 기억하는 래치다(`_weather_view` 참조).
        # 코디네이터가 `_weather_memory` 로 노출해 재시작을 넘긴다(`cycle_memory`) — 안 그러면 재시작 뒤
        # 끊긴 센서가 "원래 없던 센서" 로 읽혀 천장이 사라진다.
        # 마지막 강우 값의 출처('model'|'measured') 도 같이 쥔다 — 값을 잃은 동안에도 같은 규칙으로
        # 본다(`classify_rain`). 모르면 실측.
        self.weather_memory: WeatherMemory = WeatherMemory()
        self._weather_lost_logged: set = set()
        # 강우 단계 제한의 유지 — (단계, 만료 시각). 예보 값이 시간 경계에서 0.9/1.0 을
        # 오가거나 약한 실측 비가 끊겼다 이어질 때 창이 사이클마다 오가지 않게 한다.
        self._rain_hold: Tuple[int, float] = (RAIN_LEVEL_NONE, 0.0)
        # 강풍 단계·선 시각·풀림 평균 창(`_latch_wind_level`) — 코디네이터가 `_wind_state` 로 노출해
        # 재시작을 넘긴다(`cycle_memory`).
        self.wind_state: WindState = WindState()
        self._wind_level_logged: int = WIND_LEVEL_NONE   # 단계가 바뀔 때만 남긴다
        self._wind_fast_step: bool = False               # 이번 사이클이 고온 빠른 내림이었나(로그용)
        # 방위각을 모르는 개구부 — 바뀔 때만 한 번 남긴다(`_wind_restrict_plan`).
        self._azimuth_missing_logged: frozenset = frozenset()
        # 서리 단계의 기억(`evaluate_frost`) — 코디네이터가 `_frost_state` 로 노출해 재시작을 넘긴다.
        self.frost_state: FrostState = FrostState()
        self.last_frost: Optional[FrostDecision] = None   # 이번 사이클의 판정(말하기용)

    @property
    def _weather_seen(self) -> Dict[str, float]:
        return self.weather_memory.seen

    @property
    def _rain_origin_seen(self) -> str:
        return self.weather_memory.rain_origin

    @_rain_origin_seen.setter
    def _rain_origin_seen(self, value: str) -> None:
        self.weather_memory.rain_origin = value

    def _weather_view(self, ext: dict) -> Tuple[dict, List[str]]:
        """강우·풍속을 **안전한 방향으로만** 쓰는 판정용 값과 잃은 항목.

        `docs/design/sensor-freshness-and-control-cadence.md` 규칙 A 다:

            오래된 "비 옴"·"바람 셈"   → 닫는 근거로 **쓴다** (래치)
            오래된 "비 안 옴"·"바람 없음" → 여는 근거로 **안 쓴다** (더 열지 않음)

        값 셋 중 하나다:
          - 이번에 왔다(None 이 아님)   → 그대로 쓰고 기억한다.
          - 안 왔는데 전에 봤다(잃음)   → 마지막 값을 쓴다. 위험했으면 그 게이트가
            계속 서고, 평온했으면 호출자가 "더 열지 않음" 을 건다.
          - 한 번도 못 봤다             → 그 센서가 없는 설치다. 예전과 같이
            제약하지 않는다(강우계 없는 시설은 원래 강우를 모른 채 돈다).

        "왔는가" 는 여기서 재지 않는다 — 상류(`read_outdoor_sensors`·수집기)가
        `measurement_freshness` 로 이미 가려 None 을 준다.
        """
        view = dict(ext)
        lost: List[str] = []
        # 돌풍(`wind_gust`)도 같은 규칙이다 — 다만 원래 없는 설치면 0 이 아니라 None 이다
        # (`classify_wind` 는 돌풍을 추정하지 않는다. 0 을 채우면 "잰 돌풍 0" 이 된다).
        for key in ('rain', 'wind', 'wind_gust'):
            v = ext.get(key)
            if v is not None:
                self._weather_seen[key] = float(v)
                if key == 'wind' and ext.get('wind_dir') is not None:
                    self._weather_seen['wind_dir'] = float(ext['wind_dir'])
                if key in self._weather_lost_logged:
                    logger.error('실외 %s 값이 돌아왔습니다', key)
                    self._weather_lost_logged.discard(key)
                continue
            if key in self._weather_seen:
                lost.append(key)
                view[key] = self._weather_seen[key]
                if key == 'wind' and view.get('wind_dir') is None:
                    view['wind_dir'] = self._weather_seen.get('wind_dir')
                if key not in self._weather_lost_logged:
                    # `error` — 컨트롤러 로거 기본 레벨이 ERROR 라 warning 은
                    # 아무 데도 안 남는다(`_cycle_mixin._clamp_key` 주석).
                    logger.error(
                        '실외 %s 값이 끊겼습니다 — 마지막 값 %.2f 기준으로 '
                        '개구부를 더 열지 않습니다(위험 값이면 닫힌 채 유지)',
                        key, self._weather_seen[key])
                    self._weather_lost_logged.add(key)
            else:
                # 원래 없는 센서 — 예전 기본값과 같다(돌풍은 None, 위 주석)
                view[key] = None if key == 'wind_gust' else 0.0
        return view, lost

    def _wind_level_now(self, ext: dict, weather_lost: List[str], now: float,
                        hot: bool = False) -> int:
        """이번 사이클의 강풍 단계 — 평균·돌풍으로 가르고(`classify_wind`) 내려갈 때 늦춘다.

        hot: 극한 고온(`_wind_hot`) — 2단계 근거가 사라지면 유지 없이 1단계로 내린다.
        """
        th = self.config.wind_threshold
        wind, gust = ext.get('wind'), ext.get('wind_gust')
        level = classify_wind(wind, gust, threshold=th)
        lost = 'wind' in weather_lost or 'wind_gust' in weather_lost
        held = self._latch_wind_level(level, wind, gust, lost, hot, now)
        if held != self._wind_level_logged:
            # `error` — 컨트롤러 로거 기본 레벨이 ERROR 라 warning 은 안 남는다.
            logger.error('강풍 단계 %d → %d (10분 평균 %s m/s, 돌풍 %s m/s%s%s)',
                         self._wind_level_logged, held,
                         'None' if _finite_or_none(wind) is None else f'{float(wind):.1f}',
                         'None' if _finite_or_none(gust) is None else f'{float(gust):.1f}',
                         ', 값 끊김 — 마지막 값' if lost else '',
                         ', 실내 고온 — 유지 없이 1단계로' if self._wind_fast_step else '')
            self._wind_level_logged = held
        return held

    def _latch_wind_level(self, level: int, wind, gust, lost: bool, hot: bool,
                          now: float) -> int:
        """강풍 단계 유지 — 올라가기는 즉시, 내려가기는 한 단계씩.

        - 2 → 1 고온 빠른 내림: `hot` 이고 2단계 근거가 없으면(`level` < 2) 바로.
        - 그 밖: 단계가 선 뒤 최근 WIND_LEVEL_HOLD_S 표본의 평균을 내려가는 문턱(×WIND_RELEASE_FRAC)으로
          가른 단계가 지금보다 낮으면(`_wind_window_mean`).

        값을 잃었으면(`lost`) 표본을 남기지 않고 창을 비우며 내려가지 않는다 — 규칙 A(오래된 값은 닫는
        쪽으로만). 지금 단계의 들어가는 문턱을 다시 넘으면(`level` ≥ 지금) 창을 처음부터 센다.
        """
        st = self.wind_state
        self._wind_fast_step = False
        try:
            held = max(WIND_LEVEL_NONE, min(WIND_LEVEL_CLOSE, int(st.level)))
        except (TypeError, ValueError):
            held = WIND_LEVEL_NONE
        st.level = held
        if not isinstance(st.samples, list):
            st.samples = []
        lo = now - WIND_LEVEL_HOLD_S - WIND_WINDOW_SLACK_S
        if lost:
            st.samples = []
        else:
            st.samples = [s for s in st.samples
                          if isinstance(s, (list, tuple)) and len(s) >= 3
                          and _finite_or_none(s[0]) is not None and float(s[0]) >= lo]
            st.samples.append([float(now), _finite_or_none(wind), _finite_or_none(gust)])
        if level >= held:
            st.level, st.since = level, now
            return level
        if st.since is None:
            st.since = now               # 언제 섰는지 모르는 기억 — 지금부터 센다
        if lost:
            return held
        if held == WIND_LEVEL_CLOSE and hot:
            st.level, st.since = WIND_LEVEL_RESTRICT, now
            self._wind_fast_step = True
            return st.level
        covered, mean_w, mean_g = _wind_window_mean(st, now)
        if not covered:
            return held
        try:
            release = classify_wind(mean_w, mean_g,
                                    threshold=float(self.config.wind_threshold) * WIND_RELEASE_FRAC)
        except (TypeError, ValueError):
            return held
        if release < held:
            # 한 단계씩 — 2단계에서 잔잔해져도 1단계(상한)를 한 번 더 거친다.
            st.level, st.since = held - 1, now
        return st.level

    def _wind_restrict_plan(self, profiles: List[ActuatorProfile], ext: dict,
                            wind_lost: bool
                            ) -> Tuple[Dict[str, dict], Dict[str, Optional[float]]]:
        """강풍 1단계 → (강제 명령, 개구부 상한). 근거 55.

        - 풍상측(풍향 ± `windward_arc_deg`) 개구부: 닫음(0).
        - 방위각이나 풍향을 모르면 풍상측으로 **볼 수 있는 쪽**으로 다룬다: 천창은 닫고, 측창은
          상한(WIND_SIDE_CAP_PCT)만 — 측창까지 닫으면 방위각 없는 시설(현장 대부분)은 1단계가
          곧 전부 닫음이 되어 2단계와 구분이 없어진다.
        - 그 밖: 천창 WIND_ROOF_CAP_PCT · 측창 WIND_SIDE_CAP_PCT 상한.

        천창은 `vent_form != 'side'`(모르는 형태 포함 — 강우와 같은 규칙)다. 풍속을 잃었으면
        마지막 풍향을 믿지 않는다(규칙 A).
        """
        forced: Dict[str, dict] = {}
        caps: Dict[str, Optional[float]] = {}
        wind_dir = None if wind_lost else _finite_or_none(ext.get('wind_dir'))
        missing: List[ActuatorProfile] = []
        for p in profiles:
            if p.kind != 'opening':
                continue
            aid = p.actuator_id
            roof = getattr(p, 'vent_form', None) != 'side'
            az = _finite_or_none(p.azimuth_deg)
            if az is None:
                missing.append(p)
            windward = None
            if az is not None and wind_dir is not None:
                diff = abs(((wind_dir - az + 180) % 360) - 180)
                windward = diff < self.config.windward_arc_deg
            if windward or (windward is None and roof):
                forced[aid] = {'value': 0.0, 'reason': REASON_WIND_RESTRICT, 'ttl': 300.0}
            else:
                caps[aid] = WIND_ROOF_CAP_PCT if roof else WIND_SIDE_CAP_PCT
        self._note_missing_azimuth(missing)
        return forced, caps

    def _note_missing_azimuth(self, missing: List[ActuatorProfile]) -> None:
        """방위각 없는 개구부를 **바뀔 때만** 한 번 남긴다(강풍 1단계에서 풍향별로 못 가른다)."""
        ids = frozenset(p.actuator_id for p in missing)
        if ids == self._azimuth_missing_logged:
            return
        self._azimuth_missing_logged = ids
        if not ids:
            return
        side = [p for p in missing if getattr(p, 'vent_form', None) == 'side']
        what = '측창' if len(side) == len(missing) else '개구부'
        logger.error(
            '%s 방위각 미설정 — 풍향별 닫기를 못 함(강풍 1단계: 천창은 닫고 측창은 상한 %.0f %%): %s',
            what, WIND_SIDE_CAP_PCT, ', '.join(sorted(i[:8] for i in ids)))

    def _rain_level(self, raw_ext: dict, ext: dict, weather_lost: List[str],
                    now: float) -> int:
        """이번 사이클의 강우 단계 — 출처·세기·바람으로 가르고(`classify_rain`) 유지한다."""
        rain_lost = 'rain' in weather_lost
        if raw_ext.get('rain') is not None:
            self._rain_origin_seen = (RAIN_ORIGIN_MODEL
                                      if raw_ext.get('rain_origin') == RAIN_ORIGIN_MODEL
                                      else RAIN_ORIGIN_MEASURED)
        wind_lost = 'wind' in weather_lost
        # 풍속 센서가 없는 설치는 view 가 0.0 을 채운다 — 그것을 "고요함" 으로 읽으면
        # 모르는 바람으로 완화하게 된다. 이번에 왔거나 잃은(마지막 값) 것만 바람이다.
        wind = ext.get('wind') if (raw_ext.get('wind') is not None or wind_lost) else None
        level = classify_rain(ext.get('rain'), self._rain_origin_seen, wind,
                              threshold=self.config.rain_threshold,
                              rain_lost=rain_lost, wind_lost=wind_lost)
        return self._latch_rain_level(level, now)

    def _latch_rain_level(self, level: int, now: float) -> int:
        """단계 제한(HOLD_ROOF·RESTRICT)을 max(`gate_ttl`, RAIN_LEVEL_HOLD_S) 동안 유지한다
        — 내려가기만 늦춘다.

        CLOSE 는 여기서 잡지 않는다 — 전면 폐쇄는 예전대로 게이트 TTL 이 유지한다.
        """
        held, until = self._rain_hold
        if now >= until:
            held = RAIN_LEVEL_NONE
        if RAIN_LEVEL_NONE < level < RAIN_LEVEL_CLOSE and level >= held:
            self._rain_hold = (level, now + max(float(self.config.gate_ttl),
                                                RAIN_LEVEL_HOLD_S))
            return level
        return max(level, held)

    def _rain_restrict_plan(self, level: int, profiles: List[ActuatorProfile],
                            ext: dict) -> Tuple[Dict[str, dict], Dict[str, Optional[float]]]:
        """강우 단계 제한 → (강제 명령, 개구부 상한). CLOSE·NONE 이면 둘 다 비어 있다.

        천창은 `vent_form == 'ridge'` 와 **모르는 형태**다 — 모르면 엄격한 쪽(천창)으로
        본다. 측창은 'side' 로 적힌 것만이다.
        """
        forced: Dict[str, dict] = {}
        caps: Dict[str, Optional[float]] = {}
        if level not in (RAIN_LEVEL_HOLD_ROOF, RAIN_LEVEL_RESTRICT):
            return forced, caps
        wind = ext.get('wind')
        wind_dir = ext.get('wind_dir')
        for p in profiles:
            if p.kind != 'opening':
                continue
            aid = p.actuator_id
            roof = getattr(p, 'vent_form', None) != 'side'
            if level == RAIN_LEVEL_HOLD_ROOF:
                if roof:
                    caps[aid] = RAIN_ROOF_FORECAST_CAP_PCT
                continue
            windward = False
            if (not roof and wind_dir is not None and p.azimuth_deg is not None
                    and wind is not None and float(wind) >= RAIN_CALM_WIND_MS):
                diff = abs(((float(wind_dir) - p.azimuth_deg + 180) % 360) - 180)
                windward = diff < self.config.windward_arc_deg
            if roof or windward:
                forced[aid] = {'value': 0.0, 'reason': REASON_RAIN_RESTRICT,
                               'ttl': 300.0}
            else:
                caps[aid] = RAIN_SIDE_CAP_PCT
        return forced, caps

    def _eval_frost(self, env: EnvContext, ext: dict, T_int: Optional[float],
                    now: float) -> FrostDecision:
        """서리 단계를 갱신한다(`evaluate_frost`). 입력을 모으는 일만 한다.

        해의 세기는 측정(양수만 — 0.0 은 센서 없음일 수 있다)이 먼저고, 없으면 맑은 하늘 어림
        (`_nursery_light_fallback`)이다. 풍속·강우는 규칙 A 로 본 값(`ext`)이다 — 센서가 없으면
        0 으로 들어와 "고요·비 없음" 이 된다(서리는 놓치는 쪽이 비싸다).
        """
        solar = (env.get('external', {}) or {}).get('solar')
        light = solar if (solar is not None and solar > 0.0) else None
        if light is None:
            light = (env.get('internal', {}) or {}).get('_nursery_light_fallback')
        # 예보 모델 강수(0.1 mm/h 이상)는 "여기 지금 구름이 있다" 의 증거가 못 된다 — 실측 비만 뺀다.
        rain = (None if self._rain_origin_seen == RAIN_ORIGIN_MODEL
                else _first_num(ext.get('rain')))
        radiative = is_radiative_night(
            _first_num(ext.get('T')), _first_num(ext.get('wind')), rain,
            _first_num(light))
        return evaluate_frost(self.frost_state, T_int, radiative,
                              env.get('temp_min'), now)

    @staticmethod
    def _frost_plan(level: int, profiles: List[ActuatorProfile]
                    ) -> Tuple[Dict[str, dict], Dict[str, Optional[float]]]:
        """서리 단계 → (강제 명령, 개구부 상한). 장치가 없으면 그 줄은 없다.

        PROTECT: 개구부·흡배기팬 0(닫음) · 커튼 0(닫음) · 난방 100 · 유동팬 100(잎 위 찬 공기를 섞어
                 복사냉각을 깬다) · 분무·CO₂·냉방 0(물이 마르며 식고 얼어붙는다). 차광막·보광등은
                 건드리지 않는다.
        WATCH:   커튼 0 · 개구부 상한 None(지금 개도 위로 열지 않음 — 적분이 알도록 코디네이터가
                 건다, `coordinator.rain_vent_caps`). 흡배기팬은 개구부가 아니다 — 비 제한과 같다.
        """
        forced: Dict[str, dict] = {}
        caps: Dict[str, Optional[float]] = {}
        if level < FROST_LEVEL_WATCH:
            return forced, caps
        for p in profiles:
            kind = getattr(p, 'kind', '')
            value: Optional[float] = None
            if kind == 'curtain':
                value = 0.0
            elif level >= FROST_LEVEL_PROTECT:
                if kind in VENTILATING_KINDS or kind in ('fogger', 'co2_injector', 'cooler'):
                    value = 0.0
                elif kind in ('heater', 'circulation_fan'):
                    value = 100.0
            elif kind == 'opening':
                caps[p.actuator_id] = None
            if value is not None:
                forced[p.actuator_id] = {'value': value,
                                         'reason': REASON_FROST_PROTECT, 'ttl': 300.0}
        return forced, caps

    # @manual ai/env-control#settings-hvac
    def _eval_nursery_lock(self, env: EnvContext) -> bool:
        """육묘 일소 잠금 상태를 갱신하고 반환한다.

        판정 광량은 실내 추정 광량(internal['light_est'])을 우선한다 — 차광막을
        닫아 이미 그늘이 진 상태까지 잠글 이유가 없기 때문이다. 추정값이 없으면
        실외 일사(양수인 것만), 그것도 없으면 태양고도 어림값 순으로 폴백한다.

        lockout 에서 걸리고 release 아래로 내려가야 풀리는 래치라, 구름이
        지나갈 때마다 분무가 켜졌다 꺼졌다 하지 않는다.

        저녁 차단(internal['evening_block'])은 광량과 무관하게 우선한다 —
        해가 진 뒤에는 광량이 낮아 일소 게이트가 풀리지만, 밤새 잎이 젖어
        있으면 병해(잿빛곰팡이·노균병) 위험이 커진다. 육묘장은 밀식이라
        확산이 빠르다.
        """
        cfg = self.config
        # **육묘 모드에서만 잠근다** (2026-08-30 되돌림).
        #
        # 2026-08-25 `c6d0ec0b` 이 이 잠금을 육묘 밖으로 꺼내 습윤형 분무기가
        # 있으면 늘 걸리게 했다. 근거는 "물방울이 렌즈가 되는 것은 어린 모종만의
        # 일이 아니다" 였고 물리로는 맞지만, **과한 적용이었다.**
        #
        # 잎을 마른 상태로 관리하는 육묘에서는 옳다. 그러나 이미 자란 개체를
        # 키우는 쪽에서는 강일사야말로 증산이 가장 심한 때이고, 그때 분무를
        # 끊으면 일소를 막으려다 건조 스트레스를 만든다 — 보호가 아니라
        # 역효과다. 실측(2026-08-30 영양): 저녁 차단과 이어 붙어 하루 중
        # 분무 허용 창이 한 시간 남짓으로 좁혀졌고, 가습이 필요한 31 사이클
        # **전부**에서 코디네이터의 요청이 버려졌다.
        #
        # 화면도 원래 이쪽이었다 — 임계 두 필드는 `depends_on: nursery_mode`
        # 라 육묘 모드를 꺼면 보이지도 않는데 로직만 전원에게 적용됐다.
        # 즉 화면은 "육묘 전용"이라 말하고 동작은 아니었다.
        #
        # ⚠ 되돌리면 `c6d0ec0b` 이 막으려던 경우(육묘 모드를 끈 채 두상 살수를
        # 쓰는 딸기 온실)가 다시 열린다. 그 설치는 육묘 모드를 켜서 보호를
        # 받는다 — 보호의 유무를 사람이 정하게 두는 것이 이 되돌림의 요지다.
        #
        # 대상은 어디까지나 **습윤형 분무기**다(호출부의 `is_wetting_fogger`).
        # 드립과 고압 미세포그는 여기 걸리지 않는다.
        if env.get('internal', {}).get('evening_block'):
            # 래치는 건드리지 않는다 — 저녁 차단은 시간 기반이라 자체 해제된다.
            self._nursery_lock_reason = 'evening'
            return True

        if not cfg.nursery_mode:
            self._nursery_locked = False
            self._nursery_lock_reason = None
            return False

        light = env.get('internal', {}).get('light_est')
        if light is None:
            # 실외 일사는 **양수일 때만** 측정값으로 인정한다. 일사 센서를 지정하지
            # 않은 ext_context_collector 는 solar 를 0.0 으로 채워 공유하므로,
            # 0.0 을 측정값으로 받아들이면 "센서 없음"이 "한밤중"으로 둔갑해
            # 아래 어림값 폴백에 영원히 도달하지 못한다(일사 센서 없는 육묘장의
            # 하드 잠금이 통째로 죽는다).
            # 진짜 야간 0.0 을 흘려보내도 결과는 같다 — 어림값도 해가 지면 0.0 이라
            # 어느 쪽이든 잠기지 않는다. 대낮에 0.0 이 나오는 경우는 센서 고장이며,
            # 그때 어림값으로 잠그는 것은 일소 보호에서 안전한 방향이다.
            solar = env.get('external', {}).get('solar')
            if solar is not None and solar > 0.0:
                light = solar
        if light is None:
            # 측정값이 하나도 없으면 태양고도로 어림한 맑은날 일사로 판정한다.
            # 이 폴백이 없으면 일사 센서가 없는 시설은 일소 보호가 통째로 꺼진 채
            # 돌아간다(정오에 분무가 그대로 나간다). 어림값은 밤에 0 이므로
            # "야간에 계속 잠기는" 예전 우려도 생기지 않는다.
            light = env.get('internal', {}).get('_nursery_light_fallback')
        if light is None:
            # 좌표조차 없어 어림도 못 하면 잠그지 않는다 — 야간에도 계속 잠기면
            # 정상 가습까지 막혀 오히려 작물이 상한다.
            self._nursery_locked = False
            return False

        if self._nursery_locked:
            if light < cfg.nursery_solar_release:
                self._nursery_locked = False
        elif light >= cfg.nursery_solar_lockout:
            self._nursery_locked = True
        if self._nursery_locked:
            self._nursery_lock_reason = 'sunburn'
        return self._nursery_locked

    def evaluate(
        self,
        env: EnvContext,
        profiles: List[ActuatorProfile],
        unique_id: str = '',
    ) -> GateResult:
        """안전 조건을 평가하고 GateResult 를 반환."""
        cfg = self.config
        now = time.time()
        mask = 0
        reasons: List[str] = []

        now_ts = env.get('now_ts', now)
        # 강우·풍속은 규칙 A 로 본 값이다 — 잃었으면 마지막 실측(`_weather_view`).
        raw_ext = env.get('external', {}) or {}
        ext, weather_lost = self._weather_view(raw_ext)

        # ── 강우 — 출처·세기·바람으로 단계를 가른다(`classify_rain`) ──────────────
        # CLOSE 만 예전의 강우 게이트(전부 닫고 L1~L3 건너뜀)다. 단계 제한은 제약이다
        # (근거 52, `_GATE_BITS_SOFT`).
        rain_level = self._rain_level(raw_ext, ext, weather_lost, now)
        if rain_level == RAIN_LEVEL_CLOSE:
            mask |= GATE_BIT_RAIN
            reasons.append('rain')
        elif rain_level == RAIN_LEVEL_RESTRICT:
            mask |= GATE_BIT_RAIN_LIGHT
            reasons.append('rain_restricted')
        elif rain_level == RAIN_LEVEL_HOLD_ROOF:
            mask |= GATE_BIT_RAIN_LIGHT
            reasons.append('rain_hold')

        # ── 강풍 — 10분 평균·돌풍으로 단계를 가른다(`classify_wind`) ────────────────
        # CLOSE(2단계)만 예전의 강풍 게이트(전부 닫고 L1~L3 건너뜀)다. 1단계는 제약이다
        # (근거 55, `_GATE_BITS_SOFT`).
        wind_level = self._wind_level_now(ext, weather_lost, now,
                                          hot=_wind_hot(env.get('heat_protect')))
        if wind_level == WIND_LEVEL_CLOSE:
            mask |= GATE_BIT_WIND
            reasons.append('wind')
        elif wind_level == WIND_LEVEL_RESTRICT:
            mask |= GATE_BIT_WIND_LIGHT
            reasons.append('wind_restricted')

        # ── 강우·풍속을 잃음 (2026-09-19 재정의) ───────────────────────────────
        # 예전에는 `last_ext_ts` 가 `ext_context_max_age`(300초)를 넘으면 개구부와
        # 차광막을 **0 으로 강제**했다. 그것은 두 가지로 틀렸다:
        #   - 실외를 모를 때 개구부를 제자리에 두는 코디네이터(2.6, 2026-08-22)와
        #     정반대였고, 뒤에서 덮어써 늘 이겼다 — 한여름 기상대 두절 = 창 폐쇄.
        #   - 차광막은 강우·강풍에서도 강제하지 않는 내부 시설인데, 두절이 실제
        #     비바람보다 더 세게 개입했다(0 = 전면 차광).
        # 지금은 규칙 A 다: 위험했던 마지막 값은 위 두 게이트가 이어서 닫고,
        # 평온했던 값은 "더 열지 않음"(vent_open_ceiling)만 건다.
        if weather_lost:
            mask |= GATE_BIT_EXT_EXP
            reasons.append('ext_context_expired')

        # ── 실내 값을 잃음 (2026-09-20 재정의) ─────────────────────────────────
        # 예전에는 `last_int_ts` 로 나이를 재서 **모든 액추에이터를 safe_default
        # 로 강제**했다. 둘 다 틀렸다:
        #   - 호출자가 그 키에 매번 `time.time()` 을 실어 보내 나이가 언제나
        #     0 이었다 — 게이트도, 화면 문구도, 설정값도 있는데 **한 번도 발동한
        #     적이 없었다**(2026-09-20 발견).
        #   - 되살리면 실내 값을 잃는 순간 개구부가 닫히고 스크린이 걷힌다.
        #     근거가 없다는 이유로 장비를 움직이는 것이고, EXT_EXP 가 2026-09-19
        #     에 똑같은 이유로 그만둔 동작이다.
        # 지금은 **강제 명령을 만들지 않는다.** 실내를 모르면 편차를 못 재므로
        # 코디네이터가 그 축을 제어에서 빼고 근거를 잃은 장치를 제자리에 세운다
        # (`coordinator` 2.8 · 근거 21). 게이트가 하는 일은 그 사실에 이름을
        # 붙여 화면과 로그에 남기는 것뿐이다.
        #
        # 판정은 실외와 같은 기준이다 — **이번에 값이 왔는가**. 나이를 여기서
        # 다시 재면 판정이 두 벌이 되고 느슨한 쪽이 실질이 된다(`PreGateConfig.
        # ext_context_max_age` 주석).
        int_state = env.get('internal', {})
        if int_state.get('T') is None and int_state.get('RH') is None:
            mask |= GATE_BIT_INT_EXP
            reasons.append('int_sensor_expired')

        # ── 한파 ──────────────────────────────────────────────────────────────
        # 등가 환경 전제 + 공간 outlier 제거 후의 극값으로 판정.
        # T_min 이 없으면 (단일 센서) T 로 폴백.
        #
        # ⚠ **모르면 발동하지 않는다.** 비상 게이트는 전 장비를 한쪽으로 몰기
        #   때문에(완전 폐쇄·난방 100) 근거가 확실할 때만 서야 한다. 예전
        #   폴백값(−999)은 키가 **없을 때만** 걸렸는데, 이제 실내 측정이
        #   없으면 키가 있고 값이 None 이라 그 폴백에 닿지 못한다.
        # ⚠ 폭염은 여기 없다 — 극한 고온 보호(`heat_protect`)가 맡는다(`PreGateConfig`
        #   주석). `GATE_BIT_HEAT` 는 옛 CH70 기록 해독용으로만 남는다.
        T_int_cold = _first_num(int_state.get('T_min'), int_state.get('T'))
        T_ext_now  = _first_num(ext.get('T'))

        # 래치: 들어갈 때는 문턱, 나올 때는 문턱에서 여유만큼 물러난 값.
        # 값을 모르면 래치도 푼다 — "모르면 발동하지 않는다" 와 같은 규칙이다.
        if T_ext_now is None or T_int_cold is None:
            self._cold_latched = False
        else:
            m = 0.0 if not self._cold_latched else cfg.cold_release_margin
            self._cold_latched = (T_ext_now <= cfg.cold_ext_threshold + m
                                  and T_int_cold <= cfg.cold_int_threshold + m)
        if self._cold_latched:
            mask |= GATE_BIT_COLD
            reasons.append('cold_emergency')

        # ── 서리 — 한파 비상보다 일찍 서는 두 단계(위 `FROST_*` 주석) ──────────────
        # 한파 비상과 같은 실내 극값(`T_int_cold`)을 본다. 둘은 겹칠 수 있다 — 비상이 이미 닫고
        # 데우는 것에 서리의 유동팬·분무·CO₂ 끄기가 더해질 뿐이다(`forced.setdefault`).
        frost = self._eval_frost(env, ext, T_int_cold, now_ts)
        self.last_frost = frost            # 호출자가 전환을 말할 때 읽는다(`_note_frost`)
        frost_level = frost.level
        if frost_level >= FROST_LEVEL_PROTECT:
            mask |= GATE_BIT_FROST
            reasons.append('frost_protect')
        elif frost_level == FROST_LEVEL_WATCH:
            mask |= GATE_BIT_FROST_WATCH
            reasons.append('frost_watch')

        # ── 육묘 일소: 고일사 중 습윤형 분무 잠금 ──────────────────────────────
        # 다른 게이트와 성격이 다르다 — 시설 전체를 비상 운전으로 돌리는 게
        # 아니라 분무기 하나만 끄는 국소 잠금이다. 따라서 gate_ttl 을 잡지 않고
        # (다른 제어를 얼려버리면 안 된다) 자체 히스테리시스 래치만 쓴다.
        nursery_lock = self._eval_nursery_lock(env)
        if nursery_lock and any(is_wetting_fogger(p) for p in profiles):
            mask |= GATE_BIT_FOG_SUNBURN
            # ⚠ **비트 이름(`_SUNBURN`)과 화면 문구를 혼동하지 말 것.** 비트는
            #   "습윤형 분무가 잠겨 있다" 는 사실 하나를 담지만, 잠근 이유는
            #   둘이다 — 광량 임계(진짜 일소)와 저녁 시간대(잎마름병 방지)는
            #   서로 무관하고 동시에 참일 이유가 없다(맑은 대낮 vs 비 오는
            #   밤). 사유 문자열은 실제로 잠근 근거를 따라간다.
            reasons.append('nursery_fog_evening'
                           if self._nursery_lock_reason == 'evening'
                           else 'nursery_fog_sunburn')

        # 아래 판정들은 "시설 비상 게이트"만 대상으로 한다. 육묘 분무 잠금이
        # 함께 켜졌다고 해서 풍향 차등 폐쇄 같은 기존 동작이 바뀌면 안 된다.
        mask_core = mask & ~GATE_BIT_FOG_SUNBURN

        # ── 값을 잃은 것은 **제약**이지 비상이 아니다 ──────────────────────────
        # EXT_EXP(강우·풍속을 잃음)와 INT_EXP(실내 값을 잃음)는 둘 다 강제
        # 명령을 만들지 않는다 — 앞은 개구부에 "더 열지 않음" 을 걸고, 뒤는
        # 코디네이터가 근거를 잃은 장치를 제자리에 세운다. 이 둘만 서 있으면
        # L1~L3 를 정상 실행해야 한다: 잴 수 있는 축(CO₂·광량 임계)은 계속
        # 제어해야 하고, 전체를 멈추면 그것까지 함께 선다.
        # 강우 단계 제한(RAIN_LIGHT)도 같다 — 제어는 돌고 개구부만 묶는다.
        lost_only = bool(mask_core) and not (mask_core & ~_GATE_BITS_SOFT)

        triggered = bool(mask) or (now < self._triggered_until)
        # 값을 잃은 게이트는 TTL 을 잡지 않는다. 잡으면 값이 돌아온 뒤에도
        # 300초 동안 L1~L3 가 통째로 멈춘다(TTL 구간은 강제 명령 없는 전체
        # 홀드다) — 돌아온 값으로 곧바로 제어를 재개해야 한다.
        if triggered and (mask_core & ~_GATE_BITS_SOFT):
            self._triggered_until = now + cfg.gate_ttl

        if not triggered:
            if self._last_triggered:
                logger.info('SafetyPreGate released')
            self._last_triggered = False
            return GateResult(triggered=False)

        if not self._last_triggered:
            logger.warning('SafetyPreGate triggered: %s', ', '.join(reasons))
        self._last_triggered = True

        # ── 풍향 차등은 강풍 **1단계**의 일이다(2026-10-10) ──────────────────────
        # 예전에는 "강풍 단독 + 풍향 + 모든 개구부 방위각" 일 때 2단계(문턱 이상)에서 풍상측만
        # 닫았다 — 그 조건이 현장에서 한 번도 서지 못했고(방위각 없음), 문턱 위에서는 돌풍이
        # 문턱의 1.4 배를 넘나들어 풍하측도 안전하지 않다. 지금 2단계는 언제나 전부 닫고,
        # 풍향 차등은 1단계(`_wind_restrict_plan`)가 개구부마다 한다. `_build_forced_commands`
        # 의 `per_opening_mode` 는 그 함수를 직접 부르는 자리를 위해 남는다.

        # 값을 잃은 게이트·단계 제한만: partial=True, triggered=False → L1-L3 계속.
        # 육묘 분무 잠금 단독(mask_core == 0)도 마찬가지 — 분무기만 끄고 나머지
        # 제어는 그대로 돈다. mask == 0 인 TTL 유지 구간은 기존대로 전체 홀드.
        is_partial = lost_only
        if mask and mask_core == 0:
            is_partial = True

        forced = self._build_forced_commands(mask, profiles, ext, False)
        caps: Dict[str, Optional[float]] = {}
        cap_reasons: Dict[str, int] = {}
        if not (mask & (GATE_BIT_RAIN | GATE_BIT_COLD | GATE_BIT_WIND)):
            # 강우·강풍 단계 제한 — 전면 폐쇄(강우·한파·강풍 2단계)가 서면 그것이 이긴다.
            # 둘이 함께 서면 닫힘은 합치고 상한은 낮은 쪽(`_merge_vent_caps`). 닫힘이 상한보다
            # 엄격하므로 닫는 창의 상한은 버린다.
            _rf, _rc = self._rain_restrict_plan(rain_level, profiles, ext)
            _wf, _wc = ((self._wind_restrict_plan(profiles, ext, 'wind' in weather_lost))
                        if wind_level == WIND_LEVEL_RESTRICT else ({}, {}))
            for aid, cmd in list(_rf.items()) + list(_wf.items()):
                forced.setdefault(aid, cmd)
            caps, cap_reasons = _merge_vent_caps(_rc, _wc)
            caps = {aid: c for aid, c in caps.items() if aid not in forced}
            cap_reasons = {aid: r for aid, r in cap_reasons.items() if aid in caps}
        # 서리 — 강제 명령은 이미 있는 것(비·바람·한파가 같은 값을 박았다)을 건드리지 않고, 상한은
        # 강우가 건 것이 있으면 그것을 둔다(숫자 상한이 "더 열지 않음" 보다 구체적이다).
        frost_forced, frost_caps = self._frost_plan(frost_level, profiles)
        for aid, cmd in frost_forced.items():
            forced.setdefault(aid, cmd)
        for aid, c in frost_caps.items():
            if aid not in forced and aid not in caps:
                caps[aid] = c
                cap_reasons[aid] = REASON_FROST_PROTECT

        if unique_id:
            write_decision_log(unique_id, 'safety_gate_active', CH_SAFETY_GATE, float(mask))

        return GateResult(
            triggered=(not is_partial),   # partial 모드는 triggered=False
            gate_mask=mask,
            forced_commands=forced,
            description=', '.join(reasons),
            partial=is_partial,
            vent_open_ceiling=bool(mask & GATE_BIT_EXT_EXP),
            vent_caps=caps,
            vent_cap_reasons=cap_reasons,
            frost_level=frost_level,
        )

    def reset_after_release(self):
        """게이트 해제 후 호출 — 적분 상태 리셋 신호."""
        self._last_triggered = False
        self._triggered_until = 0.0

    def _build_forced_commands(
        self, mask: int, profiles: List[ActuatorProfile],
        ext: dict = None, per_opening_mode: bool = False,
    ) -> Dict[str, dict]:
        """비트마스크에 따라 액추에이터별 강제 명령 생성.

        per_opening_mode=True 일 때 강풍 단독 발동: opening 별 azimuth 와
        ext['wind_dir'] 비교해 windward (±windward_arc_deg) 만 폐쇄.

        개도 규약은 장치 전부 **100 = 열림(걷힘), 0 = 닫힘(전개)** 이다:
          opening:       0 = 닫힘     (강풍·강우·한파 시 안전)
          shade:         0 = 차광막 침, 100 = 걷힘(safe_default)
          curtain:       0 = 보온커튼 침(단열), 100 = 걷힘(safe_default)
          cooler/heater: 0 = OFF
        (예전 이 자리의 "curtain: 0 = 걷힘" 은 틀린 말이었다 — 아래 한파 분기가 0 으로
        커튼을 **친다**.)

        ⚠ 폭염 강제(창 100 · 차광 0 · 냉방 100)는 **없다**(2026-10-09 폐지). 강우·강풍과
          고온이 겹치면 이 함수는 창을 닫기만 하고, 차광·냉방·팬은 극한 고온 보호가
          게이트가 명령하지 않은 장치에만 건다(`_cycle_mixin._act_on_triggered_gate` —
          `heat_protect.apply_heat_protect_overrides(mode='direct', skip_ids=…)`).
          그래서 "비바람이 들이치는 창을 냉각하려고 연다" 는 일은 구조적으로 없다.
        """
        cfg = self.config
        ext = ext or {}
        wind_dir = ext.get('wind_dir')

        cmds = {}
        for p in profiles:
            value: Optional[float] = None

            if mask & (GATE_BIT_RAIN | GATE_BIT_WIND):
                # 강풍·강우는 외부 개구부(측창/천창)만 위협한다. 차광막·보온커튼은
                # 내부 시설이라 비바람에 노출되지 않으므로 강제하지 않는다(미명령 →
                # 직전 위치 유지). 외부 개구부만 폐쇄한다.
                if p.kind == 'opening':
                    if (per_opening_mode
                            and not (mask & GATE_BIT_RAIN)
                            and p.azimuth_deg is not None
                            and wind_dir is not None):
                        # 풍향 차등: windward 만 폐쇄, leeward 는 명령 없음
                        angle_diff = abs(((wind_dir - p.azimuth_deg + 180) % 360) - 180)
                        if angle_diff < cfg.windward_arc_deg:
                            value = 0.0
                        # else leeward → value 미설정 (조율자 정상 운용)
                    else:
                        value = 0.0                      # 일괄 폐쇄

            if mask & GATE_BIT_COLD:
                if p.kind == 'opening':
                    value = 0.0                          # 완전 폐쇄
                elif p.kind == 'curtain':
                    value = 0.0                          # 보온 = 커튼 닫음(단열)
                elif p.kind == 'heater':
                    value = 100.0

            # INT_EXP(실내 값 잃음)·EXT_EXP(강우·풍속 잃음)는 **강제 명령을
            # 만들지 않는다.**
            #
            # ⚠ **예전의 "모두 safe_default" 를 되살리지 말 것**(2026-09-20 제거).
            #   그것은 실내 값을 잃는 순간 개구부를 닫고 스크린을 걷는 **결정**
            #   이다 — 한여름에 실내 노드가 끊기면 창이 닫힌다는 뜻이고, 근거가
            #   없다는 이유로 장비를 움직이는 것이다. 실내를 모르는 동안 할 일은
            #   아무것도 하지 않는 것이고, 그 판단은 코디네이터가 축별로 한다
            #   (`coordinator` 2.8 — 잴 수 있는 축이 남아 있으면 그쪽은 계속
            #   제어한다. 여기서 일괄로 덮으면 그 구분이 사라진다).
            #
            # "더 열지
            # 않음" 은 GateResult.vent_open_ceiling 으로 코디네이터가 건다 —
            # 여기서 값을 박으면 코디네이터 적분이 모르는 제약이 된다.
            # ⚠ 예전의 "개구부·차광막 0 강제" 를 되살리지 말 것(evaluate 주석).

            # 육묘 일소 잠금은 마지막에 적용해 다른 게이트를 이긴다. 극한 고온
            # 보호의 분무도 이 잠금을 넘지 못한다 — 부분 게이트(이 명령)가 오버라이드
            # 순서의 마지막이라 정상 사이클에서도 이긴다(`apply_threshold_and_gate_overrides`).
            # 한여름 정오는 고온이자 일소 위험이 최대인 시각이다.
            if (mask & GATE_BIT_FOG_SUNBURN) and is_wetting_fogger(p):
                value = 0.0

            if value is not None:
                cmds[p.actuator_id] = {
                    'value': value,
                    'reason': REASON_SAFETY_PRE_GATE,
                    'ttl': 300.0,
                }

        return cmds


# ─────────────────────────────────────────────────────────────────────────────
# Post-Gate
# ─────────────────────────────────────────────────────────────────────────────

# @manual ai/env-control#post-gate-checked-after-l3-before-dispatch
class SafetyPostGate:
    """L3 결과를 L4 전달 전 정합성 검사·보정.

    check() 는 L3 commands dict 를 받아 보정된 commands dict 를 반환한다.
    """

    def check(
        self,
        commands: Dict[str, dict],
        profiles: List[ActuatorProfile],
        unique_id: str = '',
    ) -> Tuple[Dict[str, dict], bool]:
        """
        Returns:
            (보정된 commands, 보정 발생 여부)
        """
        result = dict(commands)
        corrected = False
        profile_map = {p.actuator_id: p for p in profiles}

        for aid, cmd in list(result.items()):
            p = profile_map.get(aid)
            if p is None:
                continue

            value = cmd.get('value', 0.0)

            # ── NaN / Inf 방어 ──────────────────────────────────────────────
            if not math.isfinite(value):
                result[aid] = {'value': p.safe_default, 'reason': REASON_SAFETY_POST_GATE}
                corrected = True
                logger.warning('PostGate: NaN/Inf on %s → safe_default', aid)
                continue

            # ── 하드 한계 [0, 100] ──────────────────────────────────────────
            clamped = max(0.0, min(100.0, value))
            if clamped != value:
                result[aid]['value'] = clamped
                result[aid]['reason'] = REASON_SAFETY_POST_GATE
                corrected = True

            # ── 수동 락 ─────────────────────────────────────────────────────
            if p.manual_lock.is_active():
                result[aid] = {
                    'value': p.manual_lock.manual_value,
                    'reason': 20,   # REASON_MANUAL_OVERRIDE
                }
                corrected = True

        # ── 모순 검출(냉방+난방 동시 ON)은 **여기가 아니다** ──────────────
        # 2026-08-26 에 `_cycle_mixin.apply_hvac_opposition_interlock` 으로
        # 옮겼다. 이 Post-Gate 는 임계 오버라이드보다 **앞**에서 도는데, 충돌은
        # 그 뒤 `_force_cool` 이 냉방을 100 으로 올리면서 새로 생긴다 — 여기서
        # 검사하면 아직 없는 것을 검사하고 통과시킨다(실측: 검사 통과 후
        # 난방 100% + 냉방 100% 가 그대로 나갔다).
        #
        # ⚠ **되살리지 말 것.** 같은 규칙을 두 곳에 두면 갈라지고, 갈라지면
        #   늦게 도는 쪽이 실질 규칙이 된다.

        if corrected and unique_id:
            write_decision_log(unique_id, 'safety_gate_active', CH_SAFETY_GATE, -1.0)

        return result, corrected
