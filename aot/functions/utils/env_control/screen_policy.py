# coding=utf-8
"""차광막·보온커튼 판단 — 정책은 **이 모듈 한 곳**이다 (Phase 5b·6, 2026-10-09).

## 왜 있는가

스크린은 효과 모델(`effect_functions`)이 아는 것보다 아는 것이 많아야 하는 장치다.
차광막을 치면 열부하와 증산이 줄지만 **빛도 준다** — 빛은 효과 모델 밖이라, 맡겨 두면
PI 는 "공짜 냉방" 인 차광을 언제든 친다. 보온커튼도 같다(빛·결로는 모델 밖). 그래서
"지금 이 막을 열·수분 조절에 써도 되는가" 를 여기서 정하고, 코디네이터·PI 는 그 결론을
**읽기만** 한다(`heat_protect` 와 같은 구조).

## 차광막의 광 상태 (`SHADE_FREE` · `SHADE_TRADE` · `SHADE_PROTECT`)

    판단 근거   _light_shaded_est   차광막을 **다 쳤을 때** 작물이 받는 광량(W/m²)
                DLI 예상           오늘 받은 광 + 남은 맑은 하늘 × 구름비(30 분 EMA) × 피복 τ
                                   × 차광 τ — "지금부터 해 질 때까지 닫아 둔다" 고 가정
    PROTECT     DLI 예상 < 목표, 또는 다 쳤을 때 광량 < light_min
                → 차광막은 걷어 둔다(바닥 100 %, 근거 44)
    FREE        다 쳤을 때도 광포화 이상, 또는 습윤형 분무의 일소 잠금이 걸릴 만큼 밝다
                → 열·VPD 조절에 마음대로 쓴다(근거 43)
    TRADE       그 사이(차광하면 광포화 아래지만 DLI 는 남는다). DLI 목표·광량 미상도 여기
                → 더 싼 수단(창·분무)을 다 쓴 뒤에만 쓴다. 그 전에는 걷어 둔다(근거 44)

순서 — 창 → (FREE 차광) → 분무 → (TRADE 차광) → 팬 → 냉방 — 을 **비용**으로 만들지
않는다. 코디네이터의 부하 분담은 도메인마다 따로라(`types.ACTUATOR_DOMAIN`) 차광(screen)과
분무(hvac)의 비용 순서는 서로의 명령에 닿지 않는다. 그래서 TRADE 는 "창·분무를 다 썼는가"
(`_cheap_cooling_spent`)로 직접 거른다.

## 쓰는 곳 — 결과를 **읽기만** 한다

    `_cycle_mixin._evaluate_screens`   판단을 부르고 `situation.context['screen']` 에 싣는다
    `coordinator.coordinate`           `adjust_pi_command`(바닥·근거)·온도 상한 항('screen')
    `heat_protect.evaluate_heat_protect` `shaded_below_light_min`(light_min 양보)

⚠ 극한 고온 보호가 켜져 있고 차광을 쥐면(전개 또는 light_min 양보) **보호가 주인이다** —
  이 모듈은 그 사이클의 차광막에 바닥·왕복 방지를 걸지 않는다.
⚠ light_max·light_min·온도 하드 한계·안전 게이트의 강제는 여기 판단을 **이긴다**(뒤에서 덮는다).
⚠ `ScreenState` 는 재시작을 넘는다(`cycle_memory`) — 버리면 오늘 받은 광(DLI)·차광막 하루 이동 수가
  재시작마다 0 으로 돌아가고, 일사 이력이 '해 없음' 에서 다시 시작한다.
"""
# @manual ai/env-control#shade-heat
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Tuple

from . import humid_regime as HR
from .dispatch_adapters import SCREEN_KINDS, SCREEN_OPEN_AT, snap_screen_value
from .log_channels import (
    REASON_HEAT_PROTECT, REASON_LIMIT_LIGHT_MAX, REASON_LIMIT_LIGHT_MIN,
    REASON_LIMIT_TEMP_MAX, REASON_LIMIT_TEMP_MIN, REASON_MANUAL_OVERRIDE,
    REASON_NO_GRADIENT, REASON_PRIMARY, REASON_SAFETY_POST_GATE, REASON_SAFETY_PRE_GATE,
    REASON_CURTAIN_DAY_OPEN, REASON_CURTAIN_GAP, REASON_CURTAIN_NIGHT_CLOSE,
    REASON_CURTAIN_RAMP, REASON_SCREEN_HOLD,
    REASON_SHADE_HEAT, REASON_SHADE_LIGHT_KEEP,
)
from .types import VENTILATING_KINDS

# ─────────────────────────────────────────────────────────────────────────────
# 상수 — 재배자가 판단할 값이 아니다
# ─────────────────────────────────────────────────────────────────────────────
SHADE_FREE = 'free'
SHADE_TRADE = 'trade'
SHADE_PROTECT = 'protect'

# 실외 일사(W/m²) 히스테리시스 — 해가 있다고 볼 때만 차광을 판단한다. 극한 고온 보호의
# 차광 판정(`heat_protect.HP_SHADE_SOLAR_*`)도 이 값을 쓴다(한 곳).
SHADE_SOLAR_ON = 150.0
SHADE_SOLAR_OFF = 100.0
CLOUD_EMA_S = 1800.0          # 구름비(실측 ÷ 맑은 하늘) 평활 시간
CLOUD_MIN_CLEAR_W = 50.0      # 맑은 하늘이 이보다 약하면 구름비를 갱신하지 않는다(새벽·저녁)
SPENT_PCT = 80.0              # 창·분무가 이만큼 이상 열려/돌고 있으면 '다 썼다'
VENT_USELESS_DELTA_C = 1.0    # 실외가 실내 − 이만큼보다 따뜻하면 창은 식히지 못한다
DEFAULT_LIGHT_SAT = 600.0     # `situation._LIGHT_SAT` 와 같은 값(광포화 미상)

# ── 왕복 방지(`apply_screen_hold`) ───────────────────────────────────────────
# 차광막은 편도 수 분을 달린다(aot-005 285 초). PI 의 요구가 문턱 근처에서 오르내리면
# 그 주행이 그대로 왕복이 된다. 아래 넷이 PI 가 시킨 이동만 거른다 — 한계·안전·보호가
# 시킨 이동은 언제나 통과한다(`HOLD_EXEMPT`).
SCREEN_HOLD_MIN_S = 900.0        # 한 번 움직이면 적어도 이만큼 제자리
SCREEN_HOLD_STROKES = 3.0        # … 또는 전 주행 시간의 이 배(긴 쪽)
SCREEN_ENTER_DWELL_S = 300.0     # 같은 쪽 요구가 이만큼 이어져야 움직인다
SCREEN_MAX_MOVES_PER_DAY = 8     # 하루(시설 현지 날짜) 이동 한도 — 넘으면 PI 의 요구는 제자리
# ── 밤 결로 틈(보온커튼, `_curtain_gap`) ─────────────────────────────────────
# 닫힌 보온커튼 아래 밤공기가 이슬점에 가까워지면 창보다 먼저 커튼을 **조금** 연다 — 커튼
# 위(지붕 밑) 공간이 습기를 받아 피복으로 내보낸다. 부분 개도가 되는 커튼만(`screen_positional`).
# 진입·해제 문턱은 과습 구간·야간 결로 탈출과 같은 `humid_regime` 의 이슬점 여유다(한 곳).
GAP_STEPS = (3.0, 6.0, 10.0)     # % — 단계마다 GAP_STEP_S 유지, 여유가 회복되지 않을 때만 다음
GAP_STEP_S = 900.0
GAP_ENTER_POS_PCT = 5.0          # 커튼이 이 이하(닫힘)일 때만 들어간다
GAP_RECOVER_C = 0.2              # 단계 동안 이슬점 여유가 이만큼 늘면 '회복 중' — 다음 단계로 가지 않는다
HEATER_BUSY_PCT = 80.0           # 난방기가 이만큼 이상 돌면 틈은 GAP_STEPS[0] 까지

# ── 아침 램프(보온커튼, `_curtain_ramp`) ─────────────────────────────────────
# 밤새 친 커튼을 일출에 한 번에 걷으면 커튼 위의 찬 공기가 내려앉아 실내가 몇 도 떨어진다.
# 10 → 30 → 60 → 100 % 로 걷되, 직전 단계 동안 실내가 `RAMP_MAX_DROP_C` 넘게 떨어졌거나 목표 하한
# 아래면 그 단계에 머문다. 실내외 차이가 `RAMP_SKIP_DELTA_C` 보다 작으면 내려앉을 찬 공기가 없다 —
# 곧장 걷는다. 부분 개도가 되는 커튼만(그 밖은 종전대로 낮이면 100).
RAMP_STEPS = (10.0, 30.0, 60.0, 100.0)
RAMP_STEP_S = 600.0
RAMP_MAX_DROP_C = 1.0
RAMP_SKIP_DELTA_C = 5.0
# 온도 범위 아래 끝 조건은 램프를 시작하고 이만큼만 건다 — 그 뒤에는 하락 조건만 본다. 난방이
# 범위까지 못 데우는 날 그 조건이 커튼을 하루 내내 10 % 에 붙잡았다(폐루프 cold_night + 가상 난방기:
# 유도 하한 22 °C, 실내 최고 21 °C — 낮 광량 28 % 손실).
RAMP_FLOOR_MAX_S = 7200.0

# ── 밤 보온(보온커튼, `_curtain_night_close`) ────────────────────────────────
# 밤에 열(보온) 수요가 있으면 커튼을 닫는다. 판단은 **목표·실외**로 한다 — 지금의 안팎 공기
# 온도차로 하지 않는다. 걷힌 커튼 아래 실내는 바깥을 따라가므로 그 차이는 커튼이 스스로 지운
# 것이고, 그것으로 "닫아도 소용없다" 를 판정하면 걷힌 채로 굳는다(2026-10-09 영양: 실내 9~12 °C,
# 안팎 차 1~2 °C, 밤새 100 %·근거 15, 05:57 최저 온도 한계가 닫을 때까지). 닫힌 커튼은 맑은 밤
# 하늘로의 복사 손실(하늘은 공기보다 훨씬 차다)과 피복 대류 손실을 함께 끊는다 — 공기 온도차가
# 0 이어도 효과가 있다. 부분 개도와 무관하게 모든 보온커튼에 건다.
#   들어감: 실내 < 목표 하한 + NIGHT_CLOSE_MARGIN_C, 또는 실외 < 목표 하한(걷어 두면 범위 밖으로 끌린다)
#           — 단, 실내가 목표 상한 − NIGHT_CLOSE_HYST_C 아래이고 실외가 실내보다 따뜻하지 않을 때
#           (식힐 일이 있거나 바깥 공기가 더 따뜻하면 종전대로 PI 가 온도로 판단한다).
#   나옴:   실내 > 목표 상한(식힐 일) · 실외 > 실내 + NIGHT_CLOSE_HYST_C · 실내·실외 모두 들어간
#           선보다 NIGHT_CLOSE_HYST_C 이상 위 · 낮 · 실내 온도나 목표를 모름.
NIGHT_CLOSE_MARGIN_C = 2.0
NIGHT_CLOSE_HYST_C = 1.0
# **이슬 수요도 밤 보온의 수요다**(2026-10-12 최종 폐루프 회귀 R2). 실내 이슬점 여유가 이 아래인 밤이면 열 수요가 없어도
# 닫는다 — 걷힌 커튼 아래 작물은 맑은 밤 하늘로 복사 냉각되어 공기보다 먼저 이슬점 아래로 내려간다. 무구배(근거 15)는
# 걷힌 커튼을 제자리에 붙잡을 뿐이라 닫을지 말지를 사이클의 운(그 사이클 PI 의 구동력)에 맡겼다: 폐루프 squall_heat/screens
# 에서 같은 저녁이 19:30 에 PI(근거 1)로 닫히면 밤 젖음 173 분, 무구배로 걷힌 채 남으면 433 분이었다. 닫힌 뒤의 습기는
# 결로 틈(`_curtain_gap`, 근거 46)이 뺀다. 나옴: 여유가 이 + `NIGHT_CLOSE_HYST_C` 이상(열 수요도 없을 때)·식힐 일·바깥이 더
# 따뜻함·낮. 문턱은 과습 구간의 풀림 문턱(`humid_regime.EXIT_MARGIN_C`)과 같다. 비 오는 밤(실외 강우 > 0)이나 바깥 RH 가
# `NIGHT_CLOSE_DEW_OUT_RH` 이상인 밤은 이슬 수요를 보지 않는다 — 구름이 덮어 하늘 복사 냉각이 작다.
NIGHT_CLOSE_DEW_MARGIN_C = HR.EXIT_MARGIN_C
NIGHT_CLOSE_DEW_OUT_RH = 95.0
NIGHT_CLOSE_DEW_RAIN_S = 3600.0      # 비가 그친 뒤 이만큼은 아직 하늘이 덮여 있다고 본다(태풍의 비 띠 사이)
# **난방이 돌고 있으면 열 수요가 있는 것이다**(2026-10-14). VPD 직접 모드의 난방기는 유도 온도 목표를 좇아 데우는데, 커튼의
# 열 수요 선은 유도 **범위**(아래 끝 + `NIGHT_CLOSE_MARGIN_C`)라 둘이 어긋나면 난방기는 데우고 커튼은 걷힌 채 열을 버린다
# (폐루프 normal/screens_heated: 난방 kWh +7.7 %). 그래서 밤에 난방 장치의 직전 명령이 0 보다 크고 실외가 실내보다 차면
# 열 수요로 본다. 난방 명령이 0 이 되는 사이클이 끼므로 `NIGHT_CLOSE_HEAT_HOLD_S` 동안은 난방 중으로 친다(커튼이 그때마다
# 왕복하지 않게). 기존 예외(실내가 상한 근처·실외가 더 따뜻함)는 그대로 이기고, 풀림은 난방 중에는 '들어간 선에서 멀다' 로
# 풀리지 않는다(들어온 이유가 그대로이므로) — 난방이 멎은 뒤에는 기존 규칙이다.
HEATING_KINDS = frozenset({'heater'})        # 난방 kind 는 이 표 한 곳 — 새 난방 장치는 여기 더한다
NIGHT_CLOSE_HEAT_HOLD_S = 1800.0

HOLD_EXEMPT = frozenset({
    'light_max', 'light_min', 'temp_max', 'temp_min', 'heat_protect',
    REASON_LIMIT_LIGHT_MAX, REASON_LIMIT_LIGHT_MIN, REASON_LIMIT_TEMP_MAX,
    REASON_LIMIT_TEMP_MIN, REASON_HEAT_PROTECT, REASON_SAFETY_PRE_GATE,
    REASON_SAFETY_POST_GATE, REASON_MANUAL_OVERRIDE, REASON_SHADE_LIGHT_KEEP,
})

_FOG_KIND = 'fogger'


@dataclass
class ScreenConfig:
    """옵션 + 사이클 정보."""
    shade_heat_assist: bool = True
    curtain_humidity_gap: bool = True
    light_min: Optional[float] = None
    light_sat: Optional[float] = None     # 작물 광포화 [W/m²] — None 이면 DEFAULT_LIGHT_SAT
    dli_target: Optional[float] = None    # [mol/m²/d] — None 이면 DLI 를 판단하지 않는다
    cycle_sec: float = 60.0


@dataclass
class ScreenState:
    """사이클을 넘는 기억. 재시작을 넘는다(`cycle_memory`)."""
    day_key: Optional[str] = None
    dli_mol: float = 0.0                   # 오늘 작물이 받은 광 [mol/m²] (light_est 적분)
    last_ts: Optional[float] = None
    cloud_ratio: Optional[float] = None
    cloud_ts: Optional[float] = None
    sun_on: bool = False
    shade_mode: Optional[str] = None
    # 스크린마다 마지막으로 **나간** 개도(0/100 결정 뒤) · 마지막 이동 시각 · 오늘 이동 수 ·
    # 기다리는 요구(목표, 처음 본 시각).
    screen_pos: Dict[str, float] = field(default_factory=dict)
    last_move: Dict[str, float] = field(default_factory=dict)
    moves_today: Dict[str, int] = field(default_factory=dict)
    pending: Dict[str, Tuple[float, float]] = field(default_factory=dict)
    cap_warned: Dict[str, str] = field(default_factory=dict)
    # 밤 결로 틈
    gap_on: bool = False
    gap_idx: int = 0
    gap_since: Optional[float] = None
    gap_margin_ref: Optional[float] = None
    # 아침 램프 — 단계 번호(None = 시작 전), 램프·단계 시작 시각·그때 실내 온도, 오늘 끝났는가
    ramp_idx: Optional[int] = None
    ramp_start: Optional[float] = None
    ramp_since: Optional[float] = None
    ramp_T_ref: Optional[float] = None
    ramp_done: bool = False
    # 밤 보온 — 열 수요로 닫아 두는 중인가(히스테리시스 기억)
    night_close_on: bool = False
    rain_seen_at: Optional[float] = None   # 마지막으로 실외 강우를 본 시각 — 밤 보온의 이슬 수요(`NIGHT_CLOSE_DEW_RAIN_S`)
    heat_seen_at: Optional[float] = None   # 마지막으로 난방 명령을 본 시각 — 밤 보온의 열 수요(`NIGHT_CLOSE_HEAT_HOLD_S`)


@dataclass
class ScreenDecision:
    """한 사이클의 결론. 쓰는 곳은 이것만 읽는다."""
    shade_ids: frozenset = frozenset()
    shade_mode: Optional[str] = None       # None = 해가 없다·기능 꺼짐·차광막 없음
    shade_heat_ok: bool = False            # 열·VPD 조절에 써도 된다(온도 상한 항 'screen')
    shade_floor_ids: frozenset = frozenset()   # 걷어 둔다(바닥 100 %, 근거 44)
    hp_owns_shade: bool = False
    dli_projected: Optional[float] = None
    mode_changed: bool = False
    curtain_day_open: bool = False
    hold_enabled: bool = False             # 차광막 왕복 방지를 건다(기능 켬 · 보호가 안 쥠)
    daylight: bool = False                 # 해가 있다(일사 이력 또는 시설 위치의 일출~일몰)
    # 보온커튼 — 밤 결로 틈 {id: %}(0 이면 싣지 않는다)와 결로의 주인. 창의 야간 결로 탈출은
    # `vent_escape_allowed` 일 때만 — 틈을 다 쓰고도 남을 때(위치를 잡는 커튼이 없으면 언제나 참).
    curtain_gap: Dict[str, float] = field(default_factory=dict)
    vent_escape_allowed: bool = True
    cond_stage: int = 0                    # 0 결로 아님 · 1 커튼 틈 · 2 창 탈출까지
    curtain_day_target: Dict[str, float] = field(default_factory=dict)   # 낮 — 램프 단계(%)
    curtain_night_close: frozenset = frozenset()   # 밤 — 열 수요로 닫아 둘 보온커튼(근거 49)

    def describe(self) -> str:
        parts = ['차광 %s' % {SHADE_FREE: '자유', SHADE_TRADE: '절충',
                             SHADE_PROTECT: '빛 지킴'}.get(self.shade_mode, '해당 없음')]
        if self.dli_projected is not None:
            parts.append('DLI 예상 %.1f mol' % self.dli_projected)
        if self.hp_owns_shade:
            parts.append('극한 고온 보호가 쥠')
        return ' · '.join(parts)


def _num(v) -> Optional[float]:
    try:
        return None if v is None else float(v)
    except (TypeError, ValueError):
        return None


# @manual ai/env-control#shade-heat, ai/env-control#heat-protect
def shaded_below_light_min(light_min, shaded) -> bool:
    """차광막을 다 치면 작물 광량이 light_min 아래로 가는가. 모르면 False.

    극한 고온 보호의 'light_min 양보'(`heat_protect`)와 이 모듈의 PROTECT 가 같은 질문을
    한다 — 판정은 여기 하나다.
    """
    lm, sh = _num(light_min), _num(shaded)
    return bool(lm and lm > 0.0 and sh is not None and sh < lm)


def _update_light_memory(state: ScreenState, internal: dict, now: float,
                         day_key: Optional[str], clear_sky_now: Optional[float],
                         cycle_sec: float) -> None:
    """오늘의 DLI 적분·구름비 EMA·일사 래치를 갱신한다."""
    from .cumulative_tracker import light_to_ppfd
    if day_key is not None and day_key != state.day_key:
        state.day_key = day_key
        state.dli_mol = 0.0
        state.moves_today = {}
    dt = float(cycle_sec or 60.0)
    if state.last_ts is not None and now > state.last_ts:
        dt = min(now - state.last_ts, 2.0 * float(cycle_sec or 60.0))
    state.last_ts = now
    light = _num(internal.get('light_est'))
    ppfd = light_to_ppfd(light, internal.get('light_unit')) if light else None
    if ppfd and ppfd > 0.0:
        state.dli_mol += ppfd * dt * 1e-6

    solar = _num(internal.get('_outdoor_solar'))
    cs = _num(clear_sky_now)
    if solar is not None and solar > 0.0 and cs is not None and cs >= CLOUD_MIN_CLEAR_W:
        ratio = max(0.0, min(1.2, solar / cs))
        if state.cloud_ratio is None or state.cloud_ts is None:
            state.cloud_ratio = ratio
        else:
            a = min(1.0, max(0.0, now - state.cloud_ts) / CLOUD_EMA_S)
            state.cloud_ratio += a * (ratio - state.cloud_ratio)
        state.cloud_ts = now
    if solar is None:
        state.sun_on = False
    else:
        state.sun_on = solar >= (SHADE_SOLAR_OFF if state.sun_on else SHADE_SOLAR_ON)


def project_dli(state: ScreenState, clear_rest_j: Optional[float],
                cover_tau: float, shade_tau: float) -> Optional[float]:
    """오늘 DLI 예상 [mol/m²] — 지금부터 해 질 때까지 차광막을 **친다고** 가정.

    `clear_rest_j` 는 남은 맑은 하늘 전천일사 [J/m²]. 모르면 None.
    """
    if clear_rest_j is None:
        return None
    from .cumulative_tracker import light_to_ppfd
    cloud = state.cloud_ratio if state.cloud_ratio is not None else 1.0
    rest_w = float(clear_rest_j) * cloud * float(cover_tau or 1.0) * float(shade_tau or 1.0)
    per_w = light_to_ppfd(1.0) or 2.02
    return state.dli_mol + rest_w * per_w * 1e-6


def classify_shade(cfg: ScreenConfig, internal: dict, dli_projected: Optional[float],
                   sunburn_if_open: bool) -> str:
    """광 상태 → SHADE_FREE / SHADE_TRADE / SHADE_PROTECT (해가 있을 때만 부른다)."""
    shaded = _num(internal.get('_light_shaded_est'))
    if shaded is None:
        return SHADE_TRADE
    if shaded_below_light_min(cfg.light_min, shaded):
        return SHADE_PROTECT
    target = _num(cfg.dli_target)
    if target and target > 0.0 and dli_projected is not None and dli_projected < target:
        return SHADE_PROTECT
    if sunburn_if_open:
        return SHADE_FREE
    if not target or dli_projected is None:
        return SHADE_TRADE
    sat = _num(cfg.light_sat) or DEFAULT_LIGHT_SAT
    return SHADE_FREE if shaded >= sat else SHADE_TRADE


def _cheap_cooling_spent(profiles: List, prev: Dict[str, float], internal: dict,
                         external: dict, fog_blocked: bool) -> bool:
    """창(환기)과 분무를 다 썼는가 — TRADE 차광의 조건.

    창: 환기 장치가 모두 `SPENT_PCT` 이상이거나, 실외가 실내 − `VENT_USELESS_DELTA_C` 보다
        따뜻해 열어도 식지 않는다. 환기 장치가 없으면 다 쓴 것이다.
    분무: 분무기가 없거나, 막혔거나(물·일소 잠금·보호), 모두 `SPENT_PCT` 이상 돌고 있다.
    """
    vents = [p for p in profiles if getattr(p, 'kind', '') in VENTILATING_KINDS]
    T_in, T_out = _num(internal.get('T')), _num((external or {}).get('T'))
    vent_useless = (T_in is not None and T_out is not None
                    and T_out > T_in - VENT_USELESS_DELTA_C)
    vents_spent = vent_useless or all(
        float(prev.get(p.actuator_id, 0.0) or 0.0) >= SPENT_PCT for p in vents)
    fogs = [p for p in profiles if getattr(p, 'kind', '') == _FOG_KIND]
    fog_spent = (not fogs or fog_blocked
                 or internal.get('_water_available', True) is False
                 or all(float(prev.get(p.actuator_id, 0.0) or 0.0) >= SPENT_PCT
                        for p in fogs))
    return bool(vents_spent and fog_spent)


def _dew_margin(T, RH) -> Optional[float]:
    td = HR.dewpoint_c(T, RH)
    return None if td is None else float(T) - td


# @manual ai/env-control#curtain-gap
def _curtain_gap(cfg: ScreenConfig, state: ScreenState, internal: dict, external: dict,
                 profiles: List, prev: Dict[str, float], day: bool,
                 T_low: Optional[float], now: float) -> Tuple[Dict[str, float], bool, int]:
    """밤 결로 틈 → ({커튼 id: %}, 창 결로 탈출 허락, 결로 단계).

    들어감: 밤 · 위치를 잡는 커튼이 `GAP_ENTER_POS_PCT` 이하 · 이슬점 여유 < `HR.ENTER_MARGIN_C`.
    나옴:   여유 > `HR.EXIT_MARGIN_C` · 낮 · 커튼이 틈보다 크게 열렸다(PI·게이트).
    단계:   3 → 6 → 10 %, 단계마다 `GAP_STEP_S` 유지, 그동안 여유가 `GAP_RECOVER_C` 넘게 늘지
            않았을 때만 다음으로.
    열 손실: `_force_heat` 거나 난방기가 없는데 실내가 목표 하한(`T_low`) 이하면 0. 실내 − 실외가
            `HR.MAX_COLD_DELTA_C` 를 넘거나 난방기가 `HEATER_BUSY_PCT` 이상이면 첫 단계까지.
    창 탈출: 틈을 쓸 수 있는 데까지 쓰고(그 단계를 `GAP_STEP_S` 유지하고)도 여유가 진입선 아래일
            때, 또는 열 손실 때문에 틈이 0 일 때(그 판단은 야간 파킹의 탈출구가 온도로 다시 한다).
    """
    curtains = [p for p in profiles if getattr(p, 'kind', '') == 'curtain'
                and (getattr(p, 'capacity_meta', None) or {}).get('screen_positional')]

    def _reset():
        state.gap_on, state.gap_idx = False, 0
        state.gap_since = state.gap_margin_ref = None
    if not curtains or not cfg.curtain_humidity_gap or day:
        _reset()
        return {}, True, 0
    T, RH = _num(internal.get('T')), _num(internal.get('RH'))
    margin = None if T is None or RH is None else _dew_margin(T, RH)
    if margin is None:
        _reset()
        return {}, True, 0
    pos = min(float(state.screen_pos.get(p.actuator_id,
                                         prev.get(p.actuator_id, 100.0)) or 0.0)
              for p in curtains)
    if not state.gap_on:
        if pos <= GAP_ENTER_POS_PCT and margin < HR.ENTER_MARGIN_C:
            state.gap_on, state.gap_idx = True, 0
            state.gap_since, state.gap_margin_ref = now, margin
    elif margin > HR.EXIT_MARGIN_C or pos > GAP_STEPS[-1] + 0.5:
        _reset()
    elif (now - (now if state.gap_since is None else state.gap_since) >= GAP_STEP_S
          and margin <= (margin if state.gap_margin_ref is None
                         else state.gap_margin_ref) + GAP_RECOVER_C
          and state.gap_idx < len(GAP_STEPS) - 1):
        state.gap_idx += 1
        state.gap_since, state.gap_margin_ref = now, margin
    if not state.gap_on:
        return {}, True, 0

    heaters = [p for p in profiles if getattr(p, 'kind', '') == 'heater']
    zero = bool(internal.get('_force_heat')) or (
        not heaters and T_low is not None and T <= float(T_low))
    cap_idx = len(GAP_STEPS) - 1
    T_ext = _num((external or {}).get('T'))
    if T_ext is not None and T - T_ext > HR.MAX_COLD_DELTA_C:
        cap_idx = 0
    if any(float(prev.get(h.actuator_id, 0.0) or 0.0) >= HEATER_BUSY_PCT for h in heaters):
        cap_idx = 0
    if zero:
        return {}, True, 2
    idx = min(state.gap_idx, cap_idx)
    spent = (state.gap_idx >= cap_idx
             and state.gap_since is not None and now - state.gap_since >= GAP_STEP_S
             and margin < HR.ENTER_MARGIN_C)
    pct = GAP_STEPS[idx]
    return ({p.actuator_id: pct for p in curtains}, bool(spent), 2 if spent else 1)


# @manual ai/env-control#curtain-gap
def _curtain_ramp(state: ScreenState, internal: dict, external: dict, profiles: List,
                  prev: Dict[str, float], day: bool, T_low: Optional[float],
                  now: float) -> Dict[str, float]:
    """아침 램프 → {커튼 id: 낮 목표 %}. 비어 있으면 종전대로 100(곧장 걷기).

    낮이 되었을 때 위치를 잡는 커튼이 덜 걷혀 있으면 `RAMP_STEPS` 로 걷는다. 단계마다
    `RAMP_STEP_S` 뒤에 보고, 그동안 실내가 `RAMP_MAX_DROP_C` 이하로만 떨어졌고 (램프 시작 후
    `RAMP_FLOOR_MAX_S` 동안은) 온도 범위의
    아래 끝(`T_low` — 호출자가 유도 하한을 넘긴다. VPD 를 풀어 낸 목표 온도가 아니다: 그것은
    난방이 다 데우기 전까지 몇 시간이고 커튼을 붙잡는다) 이상이면 다음 단계, 아니면 그 자리에서
    한 단계 시간 더. 실내 − 실외 <
    `RAMP_SKIP_DELTA_C` 면 곧장 100. 밤이 되면 처음으로.
    """
    curtains = [p for p in profiles if getattr(p, 'kind', '') == 'curtain'
                and (getattr(p, 'capacity_meta', None) or {}).get('screen_positional')]
    if not day:
        state.ramp_idx = state.ramp_since = state.ramp_T_ref = state.ramp_start = None
        state.ramp_done = False
        return {}
    if not curtains or state.ramp_done:
        return {}
    T = _num(internal.get('T'))
    T_ext = _num((external or {}).get('T'))
    small_gap = T is not None and T_ext is not None and T - T_ext < RAMP_SKIP_DELTA_C
    if state.ramp_idx is None:
        pos = min(float(state.screen_pos.get(p.actuator_id,
                                             prev.get(p.actuator_id, 100.0)) or 0.0)
                  for p in curtains)
        if pos >= 99.5 or small_gap or T is None:
            state.ramp_done = True
            return {}
        state.ramp_idx, state.ramp_since, state.ramp_T_ref = 0, now, T
        state.ramp_start = now
    elif small_gap:
        state.ramp_done = True
        return {}
    elif T is not None and now - state.ramp_since >= RAMP_STEP_S:
        floor_on = (state.ramp_start is not None
                    and now - state.ramp_start < RAMP_FLOOR_MAX_S)
        ok = (state.ramp_T_ref - T <= RAMP_MAX_DROP_C
              and (T_low is None or not floor_on or T >= float(T_low)))
        if ok:
            state.ramp_idx += 1
        state.ramp_since, state.ramp_T_ref = now, T
        if state.ramp_idx >= len(RAMP_STEPS) - 1:
            state.ramp_done = True
            return {}
    return {p.actuator_id: RAMP_STEPS[state.ramp_idx] for p in curtains}


# @manual ai/env-control#curtain-gap
def _curtain_night_close(state: ScreenState, internal: dict, external: dict,
                         profiles: List, day: bool, T_low: Optional[float],
                         T_high: Optional[float], now: Optional[float] = None,
                         heating: bool = False) -> frozenset:
    """밤 보온 → 닫아 둘 보온커튼 id 들(비면 종전대로 PI·제자리).

    열 수요를 **목표와 실외**로, 이슬 수요를 **실내 이슬점 여유**로 본다(`NIGHT_CLOSE_*` 주석). 지금의 안팎 공기 온도차는 쓰지
    않는다 — 걷힌 커튼이 스스로 지운 차이라 판정이 자기 정당화가 된다. 목표 하한(`T_low`)이나
    실내 온도를 모르면 판단하지 않는다(종전과 같다). 결로 틈(`_curtain_gap`)은 이 결정 **위에서**
    커튼을 조금 연다 — 닫혀 있어야 틈이 선다.

    `heating` — 직전 사이클에 난방 장치(`HEATING_KINDS`)가 0 보다 크게 명령을 받았는가. 그렇고 실외가 실내보다 차면 열 수요다
    (`NIGHT_CLOSE_HEAT_HOLD_S` 동안 유지). 이슬 수요·결로 틈은 건드리지 않는다.
    """
    curtains = frozenset(p.actuator_id for p in profiles
                         if getattr(p, 'kind', '') == 'curtain')
    T = _num(internal.get('T'))
    lo = _num(T_low)
    if day or not curtains or T is None or lo is None:
        state.night_close_on = False
        return frozenset()
    hi = _num(T_high)
    T_ext = _num((external or {}).get('T'))
    in_line, out_line = lo + NIGHT_CLOSE_MARGIN_C, lo
    dew = _dew_margin(T, internal.get('RH')) if internal.get('RH') is not None else None
    # 비 오는 밤·포화된 바깥 공기(RH ≥ `NIGHT_CLOSE_DEW_OUT_RH`)는 구름이 하늘을 덮어 작물의 복사 냉각이 작다 — 이슬 수요의
    # 근거가 없다(폐루프 typhoon/screens: 비 띠 사이 30 분에 닫았더니 작물 이슬은 줄었지만 잎 젖음이 550 → 645 분으로 늘었다).
    # 비 띠 사이의 짧은 그침도 비로 본다 — 그친 뒤 `NIGHT_CLOSE_DEW_RAIN_S` 까지(typhoon 21:30: 강우 0 이 30 분).
    _rain = _num((external or {}).get('rain'))
    _rh_out = _num((external or {}).get('RH'))
    if _rain is not None and _rain > 0.0 and now is not None:
        state.rain_seen_at = float(now)
    raining = ((_rain is not None and _rain > 0.0)
               or (_rh_out is not None and _rh_out >= NIGHT_CLOSE_DEW_OUT_RH)
               or (now is not None and state.rain_seen_at is not None
                   and 0.0 <= float(now) - state.rain_seen_at < NIGHT_CLOSE_DEW_RAIN_S))
    if heating and now is not None:
        state.heat_seen_at = float(now)
    # 난방 중 — 난방 명령이 있었거나 멎은 지 얼마 안 됨. 실외가 실내보다 찰 때만 열 수요다(더 따뜻하면 커튼이 지킬 열이 없다).
    heat_run = ((heating or (now is not None and state.heat_seen_at is not None
                             and 0.0 <= float(now) - state.heat_seen_at < NIGHT_CLOSE_HEAT_HOLD_S))
                and T_ext is not None and T_ext < T)
    if not state.night_close_on:
        heat = T < in_line or (T_ext is not None and T_ext < out_line) or heat_run
        # 이슬 수요는 '식힐 일' 을 더 좁게 본다 — 실내가 목표 위 선을 넘었고 **바깥 공기가 1 °C 넘게 차서** 걷으면 실제로
        # 식을 때만. 바깥이 비슷하면 걷어도 공기는 안 식고 작물만 밤하늘로 식어 젖는다(squall_heat/screens: 실내 26 °C,
        # 밤 유도 상한 22 °C, 바깥 25.2 °C).
        damp = dew is not None and dew < NIGHT_CLOSE_DEW_MARGIN_C and not raining
        cool_avail = T_ext is None or T_ext < T - NIGHT_CLOSE_HYST_C
        warm = hi is not None and T >= hi - NIGHT_CLOSE_HYST_C
        warm_d = hi is not None and T > hi and cool_avail
        outside_warmer = T_ext is not None and T_ext > T
        state.night_close_on = bool(((heat and not warm) or (damp and not warm_d))
                                    and not outside_warmer)
    else:
        damp = dew is not None and dew < NIGHT_CLOSE_DEW_MARGIN_C and not raining
        hot = (hi is not None and T > hi
               and (not damp or T_ext is None or T_ext < T - NIGHT_CLOSE_HYST_C))
        outside_warmer = T_ext is not None and T_ext > T + NIGHT_CLOSE_HYST_C
        relieved = (not heat_run and T > in_line + NIGHT_CLOSE_HYST_C
                    and (T_ext is None or T_ext > out_line + NIGHT_CLOSE_HYST_C)
                    and (dew is None or dew >= NIGHT_CLOSE_DEW_MARGIN_C + NIGHT_CLOSE_HYST_C))
        if hot or outside_warmer or relieved:
            state.night_close_on = False
    return curtains if state.night_close_on else frozenset()


def curtain_day_command(decision: Optional[ScreenDecision], actuator_id: str
                        ) -> Tuple[float, int]:
    """낮에 걷어 두는 보온커튼의 (개도, 근거) — 램프 중이면 단계 값·근거 47, 아니면 100·근거 22."""
    v = ((getattr(decision, 'curtain_day_target', None) or {}).get(actuator_id)
         if decision is not None else None)
    if v is not None and v < 100.0:
        return float(v), REASON_CURTAIN_RAMP
    return 100.0, REASON_CURTAIN_DAY_OPEN


# @manual ai/env-control#shade-heat
def evaluate_screens(cfg: ScreenConfig, state: ScreenState, internal: dict,
                     external: dict, profiles: Iterable, hp_decision, now: float, *,
                     day_key: Optional[str] = None,
                     clear_sky_now: Optional[float] = None,
                     clear_rest_j: Optional[float] = None,
                     cover_tau: float = 1.0, shade_tau: float = 0.5,
                     prev_commands: Optional[Dict[str, float]] = None,
                     fog_blocked: bool = False,
                     curtain_day_open: bool = False,
                     T_low: Optional[float] = None,
                     T_floor: Optional[float] = None,
                     T_high: Optional[float] = None,
                     daytime: Optional[bool] = None) -> ScreenDecision:
    """이번 사이클의 스크린 판단 → `ScreenDecision`. `state` 를 제자리에서 고친다.

    `internal` 은 `_compute_light_est` 뒤의 실내 dict(`light_est`·`_light_shaded_est`·
    `light_open_est`·`_outdoor_solar`), `external` 은 판단용 실외. `fog_blocked` 는 분무가
    이번 사이클 막혀 있는가(일소 잠금·보호의 분무 차단). `curtain_day_open` 은 시설
    위치의 낮인가(보온커튼 낮 걷기). `T_low`·`T_high` 는 목표 온도의 아래·위 선(목표 ∓ 허용
    오차, 없으면 유도 범위) — 결로 틈의 열 손실과 밤 보온이 읽는다.
    """
    internal = internal or {}
    profiles = list(profiles or [])
    prev = dict(prev_commands or {})
    _update_light_memory(state, internal, now, day_key, clear_sky_now, cfg.cycle_sec)

    shade_ids = frozenset(p.actuator_id for p in profiles
                          if getattr(p, 'kind', '') == 'shade')
    hp_on = bool(getattr(hp_decision, 'active', False))
    hp_owns = bool(hp_on and (getattr(hp_decision, 'shade_deploy', False)
                              or getattr(hp_decision, 'light_min_yield', False)))
    dli_proj = project_dli(state, clear_rest_j, cover_tau, shade_tau)

    mode = None
    if shade_ids and cfg.shade_heat_assist and state.sun_on:
        sunburn = False
        lock = _num(internal.get('_nursery_solar_lockout'))
        open_est = _num(internal.get('light_open_est'))
        if lock and open_est is not None and open_est >= lock:
            from .safety_gates import is_wetting_fogger
            sunburn = any(getattr(p, 'kind', '') == _FOG_KIND and is_wetting_fogger(p)
                          for p in profiles)
        mode = classify_shade(cfg, internal, dli_proj, sunburn)

    heating = any(float(prev.get(p.actuator_id, 0.0) or 0.0) > 0.0 for p in profiles
                  if getattr(p, 'kind', '') in HEATING_KINDS)
    heat_ok = False
    floor = frozenset()
    if mode == SHADE_FREE:
        heat_ok = True
    elif mode == SHADE_TRADE:
        heat_ok = _cheap_cooling_spent(profiles, prev, internal, external or {},
                                       fog_blocked)
        if not heat_ok:
            floor = shade_ids
    elif mode == SHADE_PROTECT:
        floor = shade_ids
    if hp_on and getattr(hp_decision, 'shade_deploy', False):
        # 보호가 차광을 쥐었다 — 바닥을 걸지 않는다(보호의 전개가 뒤에서 이긴다).
        floor = frozenset()

    changed = mode != state.shade_mode
    state.shade_mode = mode
    gap, escape, cond = _curtain_gap(cfg, state, internal, external or {}, profiles, prev,
                                     bool(curtain_day_open), T_low, now)
    ramp = _curtain_ramp(state, internal, external or {}, profiles, prev,
                         bool(curtain_day_open), T_floor, now)
    # 밤 보온은 틈보다 **먼저** 정해도 되고 나중에 정해도 된다 — 틈은 나간 개도(`screen_pos`)를
    # 보고 들어가므로, 이번 사이클 닫으면 다음 사이클부터 틈이 설 수 있다.
    night_close = _curtain_night_close(state, internal, external or {}, profiles,
                                       bool(curtain_day_open), T_low, T_high, now=now,
                                       heating=heating)
    return ScreenDecision(
        curtain_day_target=ramp, curtain_night_close=night_close,
        curtain_gap=gap, vent_escape_allowed=escape, cond_stage=cond,
        shade_ids=shade_ids, shade_mode=mode, shade_heat_ok=heat_ok,
        shade_floor_ids=floor, hp_owns_shade=hp_owns, dli_projected=dli_proj,
        mode_changed=changed, curtain_day_open=bool(curtain_day_open),
        hold_enabled=bool(cfg.shade_heat_assist and not hp_owns),
        # 실외 일사를 재면 그 이력(150/100 W/m²)만 — 해 지기 직전 시계상 '낮' 에 걷히면 밤새 걷힌
        # 채로 남는다(폐루프 hot_dry 19:30). 일사를 모르면 시설 위치의 일출~일몰.
        daylight=bool(state.sun_on if _num(internal.get('_outdoor_solar')) is not None
                      else daytime))


# @manual ai/env-control#shade-heat
def adjust_pi_command(decision: Optional[ScreenDecision], profile, cmd_raw: float,
                      integral: float, reason: int,
                      primary_var: Optional[str] = None) -> Tuple[float, float, int]:
    """PI 가 정한 (개도, 적분, 근거)에 스크린 판단을 얹는다 → 새 (개도, 적분, 근거).

    coordinate() 안에서 부른다 — 적분이 이 결정을 알아야 판단이 풀릴 때 계단이 생기지
    않는다(과습 상한·보호 하한과 같은 방식).
    """
    if decision is None:
        return cmd_raw, integral, reason
    aid = profile.actuator_id
    if getattr(profile, 'kind', '') == 'shade':
        if aid in decision.shade_floor_ids:
            if cmd_raw < 100.0:
                return 100.0, 100.0, REASON_SHADE_LIGHT_KEEP
            return cmd_raw, integral, reason
        if reason == REASON_NO_GRADIENT and cmd_raw < 100.0 and decision.daylight:
            # 밀 것이 없는 차광막은 **낮에는 곧장** 걷힘(safe_default)으로 간다. 무구배 경로는 직전
            # 개도에서 기하 감쇠(×0.6)하는데, 닫힌(0) 막이면 한 사이클 값이 40 이라 0/100
            # 결정(열려면 60)을 영영 못 넘는다 — 위치를 장치에서 되읽는 paired 막은 다음
            # 사이클에도 0 에서 다시 40 이 되어 **닫힌 채 굳는다**(폐루프 hot_dry: temp_max 로
            # 한 번 친 막이 이틀 내내 0 %). 스크린에 중간 개도는 뜻이 없다.
            # ⚠ **밤에는 제자리**다. 닫힌 막은 작물을 하늘 복사냉각에서 가린다 — 밤에 걷으면
            #   잎이 이슬점 아래로 식는다(폐루프 hot_humid: 작물 이슬 657 → 943 분). 걷는 것은
            #   해가 있을 때다 — 일사를 재면 그 이력(`SHADE_SOLAR_ON/OFF`), 모르면 일출~일몰.
            return 100.0, 100.0, reason
        if (decision.shade_heat_ok and reason == REASON_PRIMARY and cmd_raw < 100.0
                and primary_var in ('temperature', 'vpd', 'humidity')):
            return cmd_raw, integral, REASON_SHADE_HEAT
    if getattr(profile, 'kind', '') == 'curtain':
        if aid in decision.curtain_night_close:
            # 밤 보온(`_curtain_night_close`) — 닫는다. 무구배 제자리(근거 15)·평형 유지가 걷힌
            # 커튼을 붙잡던 자리다. 적분도 0 에 둔다 — 풀린 뒤 PI 는 '닫혀 있다' 에서 출발한다.
            # 식힐 일(목표 상한 초과)이 있으면 판단이 이미 풀려 있어 PI 가 연다. 아래 틈이 이 위에서
            # 조금 연다. 한계·안전 게이트는 뒤에서 이긴다.
            cmd_raw, integral, reason = 0.0, 0.0, REASON_CURTAIN_NIGHT_CLOSE
        gap = decision.curtain_gap.get(aid)
        if gap and cmd_raw < SCREEN_OPEN_AT:
            # 닫힌 쪽에 남을 명령(0/100 결정에서 닫힘 — 닫힌 커튼은 `SCREEN_OPEN_AT` 이상이라야
            # 걷힌다)이면 틈만큼 연다 — 적분도 그 자리. PI 가 정말 걷자고 하면 그쪽이 이긴다.
            # ⚠ 50 으로 자르면 50~60 의 PI 명령이 틈을 끄고 0/100 결정에서 다시 닫혀, 틈이 소진 전에
            #   사라졌다(폐루프 humid_gap_night 23:20, 이슬점 여유 1.0 °C 인데 커튼 0).
            return gap, gap, REASON_CURTAIN_GAP
    return cmd_raw, integral, reason


def _value_reason(cmd):
    if isinstance(cmd, dict):
        return cmd.get('value', 0.0), cmd.get('reason')
    return getattr(cmd, 'value', 0.0), getattr(cmd, 'reason', None)


def _set(cmd, value, reason):
    if isinstance(cmd, dict):
        cmd['value'], cmd['reason'] = value, reason
    else:
        cmd.value, cmd.reason = value, reason


def hold_seconds(profile) -> float:
    """최소 유지 시간 — max(SCREEN_HOLD_MIN_S, 전 주행 × SCREEN_HOLD_STROKES)."""
    stroke = 0.0
    for v in ((getattr(profile, 'capacity_meta', None) or {}).get('screen_stroke_s'),
              getattr(getattr(profile, 'cmd_constraints', None), 'full_stroke_sec', 0.0)):
        stroke = max(stroke, _num(v) or 0.0)
    return max(SCREEN_HOLD_MIN_S, SCREEN_HOLD_STROKES * stroke)


# @manual ai/env-control#shade-heat
def apply_screen_hold(decision: Optional[ScreenDecision], state: ScreenState,
                      final_cmds: Dict, profiles: Iterable,
                      positions: Dict[str, float], now: float) -> Dict[str, str]:
    """차광막 왕복 방지 — PI 가 시킨 이동을 거른다 → {id: 막은 이유}. `snap_screen_commands` 앞.

    지금 서 있는 쪽(마지막으로 나간 0/100, 모르면 `positions`)에서 반대쪽으로 넘어가려는
    명령만 본다. 막으면 개도를 제자리로 되돌리고 근거를 45(`REASON_SCREEN_HOLD`)로 바꾼다.

        min_hold   마지막 이동 뒤 `hold_seconds` 가 안 지났다
        dwell      같은 쪽 요구가 `SCREEN_ENTER_DWELL_S` 이어지지 않았다
        no_sun     해가 없는데(일사 히스테리시스) 치려 한다
        day_cap    오늘 `SCREEN_MAX_MOVES_PER_DAY` 번을 다 썼다(해가 졌을 때 걷는 것은 빼고)

    한계·안전·보호·빛 지킴(`HOLD_EXEMPT`)이 시킨 이동은 언제나 통과한다.
    """
    blocked: Dict[str, str] = {}
    if decision is None or not decision.hold_enabled:
        return blocked
    for p in profiles or []:
        aid = p.actuator_id
        if getattr(p, 'kind', '') != 'shade' or aid not in final_cmds:
            continue
        cmd = final_cmds[aid]
        val, reason = _value_reason(cmd)
        cur = state.screen_pos.get(aid)
        if cur is None:
            pos = positions.get(aid)
            cur = None if pos is None else (100.0 if float(pos) >= 50.0 else 0.0)
        want = snap_screen_value(val, cur)
        if cur is None or want == cur:
            state.pending.pop(aid, None)
            continue
        if reason in HOLD_EXEMPT:
            state.pending.pop(aid, None)
            continue
        opening_in_dark = want >= 50.0 and not state.sun_on
        why = None
        last = state.last_move.get(aid)
        if last is not None and now - last < hold_seconds(p):
            why = 'min_hold'
        pend = state.pending.get(aid)
        if pend is None or pend[0] != want:
            state.pending[aid] = (want, now)
            pend = state.pending[aid]
        if why is None and not opening_in_dark and now - pend[1] < SCREEN_ENTER_DWELL_S:
            why = 'dwell'
        if why is None and want < 50.0 and not state.sun_on:
            why = 'no_sun'
        if (why is None and not opening_in_dark
                and state.moves_today.get(aid, 0) >= SCREEN_MAX_MOVES_PER_DAY):
            why = 'day_cap'
        if why is not None:
            _set(cmd, cur, REASON_SCREEN_HOLD)
            blocked[aid] = why
        else:
            state.pending.pop(aid, None)
    return blocked


def record_screen_positions(state: ScreenState, final_cmds: Dict, profiles: Iterable,
                            now: float) -> None:
    """0/100 결정이 끝난 최종 개도를 기억하고 이동을 센다(`apply_screen_hold` 의 기준)."""
    for p in profiles or []:
        aid = p.actuator_id
        if getattr(p, 'kind', '') not in SCREEN_KINDS or aid not in final_cmds:
            continue
        val = _num(_value_reason(final_cmds[aid])[0])
        if val is None:
            continue
        prev = state.screen_pos.get(aid)
        if prev is not None and abs(prev - val) >= 0.5:
            state.last_move[aid] = now
            state.moves_today[aid] = state.moves_today.get(aid, 0) + 1
        state.screen_pos[aid] = val


def shade_ceiling_allowed(decision: Optional[ScreenDecision], profile) -> bool:
    """온도 상한 항(`coordinator._temperature_ceiling`)이 이 차광막을 몰아도 되는가."""
    return bool(decision is not None and decision.shade_heat_ok
                and getattr(profile, 'kind', '') == 'shade')


__all__ = [
    'SHADE_FREE', 'SHADE_TRADE', 'SHADE_PROTECT', 'SHADE_SOLAR_ON', 'SHADE_SOLAR_OFF',
    'ScreenConfig', 'ScreenState', 'ScreenDecision', 'evaluate_screens',
    'classify_shade', 'project_dli', 'shaded_below_light_min', 'adjust_pi_command',
    'shade_ceiling_allowed', 'apply_screen_hold', 'record_screen_positions', 'hold_seconds',
    'curtain_day_command',
]
