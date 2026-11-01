# coding=utf-8
"""밤 이슬 순환팬 — 닫힌 집의 밤 결로를 공기 움직임으로 줄인다 (근거 59, 2026-10-12).

## 왜 있는가

열대야(밤에도 외기 이슬점이 실내보다 높다)에는 창을 열어도 습기가 빠지지 않는다 — 환기는 오히려 습기를 들인다
(`humid_regime` 의 WET 판정). 집은 닫히고, 밤새 잎이 젖은 채 남는다. 폐루프 `heatwave_tropical_night`(3 일, 밤 RH 90 %
이상)에서 밤 작물 젖음이 1148 분, 피복 결로 분은 697 → 975 로 늘었다(`.local/reports/env_storm_final.md`).

잎이 젖어 있는 시간이 병(잿빛곰팡이·노균병)을 부른다. 바람이 없는 잎 표면에는 두꺼운 정체 경계층이 있어 젖은 면의
증발이 느리고, 잎이 복사로 공기보다 차가워져 이슬이 더 쉽게 맺힌다. 공기를 **움직이면** 경계층이 얇아져 증발이 빨라지고
잎 온도가 공기에 가까워져 이슬이 덜 맺힌다. 습기를 집 밖으로 내보내는 것이 아니라 **젖어 있는 시간을 줄이는** 수단이다.

## 규칙

    밤이다            시설 위치의 일몰 ~ 일출 (`solar.is_daytime` 이 False). 모르면(좌표 없음) 아무것도 하지 않는다.
    이슬점 여유가 작다 실내 온도 − 이슬점 < `ENTER_MARGIN_C` (= `humid_regime.ENTER_MARGIN_C` 2 °C). 풀리는 문턱은
                      `EXIT_MARGIN_C` (= `humid_regime.EXIT_MARGIN_C` 3 °C) — 과습 구간·야간 결로 틈(46)과 같은 문턱·
                      같은 이력이라 셋이 다른 때에 서지 않는다.
    → 순환팬(kind `circulation_fan`) 100 %, 근거 59.

연속 100 % 이고 15 분 켜고 15 분 끄는 듀티가 아니다. 이유 ① 효과가 "공기가 움직이는 시간"에 비례한다 — 경계층은 팬이
서면 몇 분 안에 다시 두꺼워지고 잎은 다시 식는다. ② 코디네이터 주기가 5~10 분이라 15/15 는 사이클 2~3 번에 한 번
뒤집는 상태 기억이 따로 필요하다. ③ 순환팬은 가장 싼 장치(비용 0.2, 0.05~0.2 kW)이고 이 규칙은 여유가 작은 밤에만
선다 — 에너지는 듀티의 절반을 아끼는 정도이지만 효과는 절반 이하로 떨어진다. 대신 최소 가동 `MIN_ON_S`(30 분)를 둔다 —
센서 잡음으로 릴레이가 매 사이클 뒤집히지 않게.

## 앞서는 것

서리 보호(근거 56)는 안전 게이트라 걸린 사이클은 L1~L3 를 건너뛰고(이 규칙이 아예 돌지 않는다) 유동팬을 100 % 로 놓는다.
극한 고온 보호는 `_apply_mixing_actuators` 안에서 이 규칙보다 **먼저** 본다 — 같은 100 % 지만 근거는 1(`heat_protect`)
그대로다. 공간 불균일(`_spatial_hotspot_*`)로 선 팬도 근거 1 을 둔다. 이 규칙의 59 는 **이것만이 팬을 세운 사이클**에
붙는다. 순환팬이 없는 시설은 아무 일도 없다(판정조차 돌리지 않는다).

## 이 모듈이 하지 않는 것

팬을 직접 명령하지 않는다. 순환팬 결정의 주인은 `_cycle_mixin._apply_mixing_actuators` 하나이고, 이 모듈은 "지금 이
규칙이 팬을 세우라는가" 만 묻는 순수 판정이다.
"""
# @manual ai/env-control#night-dew-fan
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from . import humid_regime as HR

# 문턱의 정의는 `humid_regime` 하나다 — 따로 적으면 한쪽만 바뀐다.
ENTER_MARGIN_C = HR.ENTER_MARGIN_C
EXIT_MARGIN_C = HR.EXIT_MARGIN_C
MIN_ON_S = 30 * 60.0


@dataclass
class NightDewState:
    """사이클을 넘는 이력 — 켜짐 여부와 켜진 시각. 영속화하지 않는다(재시작 직후 한 사이클은 켬 문턱으로 읽을 뿐)."""
    on: bool = False
    since: Optional[float] = None


def margin_c(T_in, RH_in) -> Optional[float]:
    """실내 온도 − 이슬점(°C). 모르면 None."""
    td = HR.dewpoint_c(T_in, RH_in)
    return None if td is None or T_in is None else float(T_in) - td


def wanted(state: NightDewState, T_in, RH_in, night: Optional[bool],
           now: float) -> bool:
    """이 사이클에 밤 이슬 순환팬이 서야 하는가. `state` 를 갱신한다.

    밤이 아니거나(`night` 가 False·None) 실내를 모르면 즉시 끈다 — 낮의 팬은 다른 규칙(고온 보호·공간 불균일)이
    맡고, 모르는 값으로 팬을 세우지 않는다. 밤에는 여유 < 2 °C 에서 켜서 3 °C 에 닿을 때 끄되, 켠 뒤 `MIN_ON_S` 안에서는
    끄지 않는다.
    """
    if night is not True:
        state.on, state.since = False, None
        return False
    m = margin_c(T_in, RH_in)
    if m is None:
        state.on, state.since = False, None
        return False
    if not state.on:
        if m < ENTER_MARGIN_C:
            state.on, state.since = True, float(now)
    elif m >= EXIT_MARGIN_C and (state.since is None
                                 or float(now) - state.since >= MIN_ON_S):
        state.on, state.since = False, None
    return state.on
