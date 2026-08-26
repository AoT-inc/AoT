# coding=utf-8
"""
env_control/coordinator.py — Layer 3 actuator coordination algorithm (C2~C5).

Implements the design §4 pseudocode:
  - C2: live_effect evaluation engine
  - C3: coordination algorithm (position-form PI, slew, deadband-hold, anti-windup)
  - C4: side-effect conflict detection
  - C5: decision logging (caller passes unique_id)

Control law (P6 재설계 — position-form PI):
  기존 deadbeat 법칙(cmd = residual/unit_mag×100)은 작은 편차도 100% 로 포화시켜
  창호가 0↔100 릴레이 진동을 일으켰다. 이를 다음으로 교체한다.

    drive   = -residual × effect_sign        # 액추에이터 자기 프레임의 부호 있는 오차
                                             #  ( + = 더 열어야 함, - = 닫아야 함 )
    e_norm  = drive / pband                   # 비례 밴드(=PBAND_MULT×tolerance)로 정규화
    e_eff   = sign(e_norm)·max(0,|e_norm|-hb) # 데드존(hb=HOLD_FRAC/PBAND_MULT)을 '뺀' 유효오차
    I       = clamp(I + ki·e_eff, 0, 100)     # 적분 = '평형 개도(%)' 기억, 항상 [0,100]
    cmd     = clamp(kp·e_eff·100 + I, 0,100)  # P(전이) + I(평형 유지)

  성질:
    - 평형/밴드 내 → e_eff=0 → P=0, I 유지 → 직전 개도 hold (진동 제거)
    - 오버슈트(너무 차가움 등) → drive<0 → I 감소 → 점진적 폐쇄
    - "올림" 방향도 effect_sign 으로 대칭 처리 (기존 부호 버그 제거)
    - I 는 [0,100] 하드클램프 + back-calculation anti-windup (무한 와인드업 제거)

  레일 고착 회복 (2026-08-20):
    back-calculation 은 포화 **직후** 한 사이클에만 맡기고, 레일에 계속 눌러붙어
    있으면 적분을 실제 개도 쪽으로 기하 감쇠시킨다. 이유는 back-calc 의 부호에
    있다 — 아래쪽 레일(u<0)에서는 `I -= (u−c)·β` 가 I 를 **위로** 밀고, 요구값
    −P 가 100 을 넘으면 상한에 눌러붙어 그대로 굳는다. 그렇게 굳은 I 는 '기억된
    평형 개도'가 아니라 포화 부산물인데, 편차가 풀리는 순간 `cmd = P + I` 의
    I 가 통째로 계단으로 튀어나온다.
    위쪽 레일에서는 대칭으로 반대 사고가 난다 — dispatch 는 며칠째 100% 인데
    I 만 조용히 0 근처로 깎여, 무구배로 전환되는 순간 명령이 급락한다
    (2026-07-29 aot-005 폭염 중 보온커튼 오폐쇄). 회복 경로는 이 괴리 자체를
    없앤다: 레일에 눌러붙어 있는 동안 I 는 그 레일 값으로 수렴한다.
    편차가 반대로 서면 `cmd = P + I ≈ P` 라 **편차에 비례해서** 되돌아온다.

  데드존을 '빼는' 이유 (2026-08-06 aot-005 야간 창호 진동):
    이전 구현은 |e_norm|<hb 이면 cmd=I, 아니면 cmd=I+kp·e_norm·100 으로 **분기**했다.
    경계에서 P항이 0 에서 kp·hb·100(=8.33%p, 부호 반전 시 16.7%p)으로 **계단 점프**해,
    입력이 경계를 넘나들기만 하면 평형 상태에서도 명령이 그만큼 튄다. 그런데 경계를
    넘나들게 하는 데는 실제 외란이 필요 없다 — 습도 센서 1% 눈금(≈0.028kPa)이
    데드존 반폭(tolerance×HOLD_FRAC=0.05kPa)의 절반을 넘으므로 센서 최소 눈금
    하나로 충분하다. 실측: 새벽 VPD 편차 0.00~0.05kPa(허용오차 이내)인데 천창 명령이
    ±8/±16%p 로 계속 튀어 6시간 동안 12회 움직였다.
    데드존을 빼면 경계에서 P항이 0 으로 **연속** 수렴해 이 계단이 사라진다. 밴드 밖
    기울기(kp·100)는 그대로이고, 완전동작 도달점만 e_norm=1 → 1+hb 로 밀린다.

  integral 키 규약 변경: 변수별(native) → 액추에이터별(개도 %). 과거 var-키/범위
  밖 값은 coordinate() 진입 시 자동 폐기(마이그레이션)된다.

Unit convention R1:
  All deviation, accumulated, residual, magnitude are in native units.
  Normalization is used only for priority sorting and proportional-band scaling.

Reference: docs/dev/integrated_env_control_design.md §4
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from .log_channels import (
    write_decision_log,
    ch_coord_cmd, ch_coord_reason, ch_integral,
    REASON_IDLE, REASON_PRIMARY, REASON_SECONDARY,
    REASON_WRONG_DIRECTION, REASON_SIDE_EFFECT, REASON_MANUAL_OVERRIDE,
    REASON_NO_GRADIENT, REASON_NO_OUTDOOR_DATA, REASON_OPPOSING_PARKED,
    REASON_DEADZONE_BACKOFF,
)
from .authority import is_natural_var
from .types import (
    ACTUATOR_DOMAIN, DEFAULT_DOMAIN, VENTILATING_KINDS,
    ActuatorProfile, SituationReport, domain_of,
)

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Control-law tuning constants (profile.gains 로 액추에이터별 오버라이드 가능)
# ─────────────────────────────────────────────────────────────────────────────
PBAND_MULT = 6.0     # 비례 밴드 폭 = PBAND_MULT × tolerance (native). 편차가 이만큼이면 P=100%.
                     # 6 = 허용오차의 6배 편차에서 완전동작 → 작은 편차엔 부드럽게 반응
                     # (작게 할수록 민감/급격, 크게 할수록 완만). 평형개도는 적분이 찾음.
POS_KP     = 1.0     # 비례 이득 (e_norm → 명령 %)
POS_KI     = 0.2     # 적분 이득 (사이클당 e_norm 만큼 평형 개도 누적)
HOLD_FRAC  = 0.5     # 데드존 반폭 = tolerance×HOLD_FRAC. 이 안에서는 P·I 모두 0 이라
                     # 직전 평형 개도를 유지한다. 데드존은 '분기'가 아니라 유효오차에서
                     # '빼는' 방식이라 경계에서 P항이 연속이다(모듈 docstring 참조).
# 데드존 안에서 잔여 편차의 부호가 **반대쪽**으로 넘어간 채 몇 사이클 이어지면
# 그 장치는 물러난다(REASON_DEADZONE_BACKOFF). 단위가 초가 아니라 **사이클**인
# 이유는 여기서 거르려는 것이 시간이 아니라 **잡음**이기 때문이다 — 잡음은
# 사이클마다 부호가 뒤집히므로 표본 수로 세는 것이 맞다. 데드존이 존재하는 이유가
# 그 잡음이고, 한 사이클의 부호로 물러나면 데드존을 만든 이유가 사라진다.
# 3 = 잡음으로 세 번 연속 같은 쪽이 나올 확률이 낮으면서, 편차가 허용오차 안이라
#     그동안의 손해가 제한적인 지점.
DEADZONE_BACKOFF_CYCLES = 3

RELAX_FACTOR = 0.6   # 평형 개도 기하 감쇠 비율. **세** 자리가 쓴다 —
                     #  (a) 무구배·파킹: safe_default 로 수렴
                     #  (b) 레일 고착 회복: 실제 개도(0 또는 100)로 수렴
                     #  (c) 데드존 역부호 물러남: safe_default 로 수렴 (a 와 같다)
                     # 100 → 1 미만까지 약 11 사이클.
AW_BETA    = 0.5     # back-calculation anti-windup 강도 (포화 **직후** 한정)
RAIL_EPS   = 0.5     # 직전 개도가 레일에 있다고 볼 허용오차 [%]

# ─────────────────────────────────────────────────────────────────────────────
# 액추에이터 도메인 — 부하분담이 미치는 범위 (2026-08-26)
# ─────────────────────────────────────────────────────────────────────────────
# 부하분담(accumulated)은 "앞이 이미 한 만큼 뒤가 적게 한다" 인데, 이는 둘이
# **같은 일의 대체재**일 때만 뜻이 있다. 대체재가 아닌 것끼리 나누면, 한쪽이
# 낸 잘못된 주장이 다른 쪽을 **거꾸로 켠다**.
#
# 실사고(2026-08-25 イチゴ): 측창 하나의 적분이 폭주해 88.7% 를 확정했고 그
# 물리 기여가 accumulated['vpd']=+1.2556 — 원래 편차(−0.2215)의 5.7배였다.
# 뒤에 처리된 분무기·냉방기는 "이미 크게 과했다" 고 읽어 반대 방향으로 켜졌다:
# 습도 92% 인데 가습이, 목표보다 시원한데 냉방이 올라갔다. 실제 온실에서
# 측창 모터가 고장 나도 같은 경로로 재현되고, 실패 방향이 최악이다 — 하나가
# 고장 나면 나머지가 그 몫까지 떠안아야 하는데 정확히 반대로 나머지를 끈다.
#
# 그래서 누적은 **도메인 안에서만** 흐른다. 표의 정본은 `types.ACTUATOR_DOMAIN`
# 이다 — effect_functions 의 도달 한계 클램프가 같은 표를 본다.
#
# ⚠ **도메인을 넘는 조율은 명시적 인터록이 맡는다** — `hvac_interlock`(냉난방
# 가동 중 개구부 잠금)·`vent_futility_gate` 가 이미 그 자리에 있다. 인터록은
# 선언돼 있어 감사 가능하고 안전한 쪽으로 실패하지만, 효과 누적은 암묵적이라
# **조용히** 실패한다. 이번 사고가 정확히 그것이었다.
# **여기에 "에너지 절약" 을 이유로 도메인 간 누적을 되살리지 말 것.** 그것을
# 원하면 인터록으로 선언할 것 — 그래야 왜 그렇게 됐는지 답할 수 있다.


# ── 환기 무익 게이트 (사용자 옵션 vent_futility_gate) ─────────────────────────
# 외기와 공기를 바꾸는 장치는 실내 상태를 **실외 상태 쪽으로**밖에 못 민다.
# 목표가 실외의 반대쪽에 있으면 아무리 열어도 목표에 가까워질 수 없다 — 야간
# 제습이 대표적이다(실외 노점이 실내보다 높으면 창을 열수록 더 습해진다).
# G_MIN_EFFECT 는 '구동력 크기'만 보므로 이 경우를 못 걸러낸다: 면적이 큰 천창은
# 방향이 반대라도 magnitude 가 커서 항상 문턱을 통과한다. 실측(2026-08-06 aot-005)
# 에서 밤새 근거코드가 전부 PRIMARY 였고 창이 40~70% 열린 채 유지됐다.
#
# 어휘를 둘로 두지 않는다 — types 의 도메인 명부에서 파생한 것을 재수출한다.
# (기존 import 경로를 유지하려고 여기 이름을 남긴다)

# 판정 문턱 — 잡음으로 게이트가 깜빡이지 않게 한다.
#   need  : |목표-측정| 이 tolerance×VENT_NEED_FRAC 미만이면 '중립'(찬반 근거 아님)
#   avail : |실외-측정| 이 tolerance 미만이면 환기로 의미 있게 못 옮긴다고 본다
VENT_NEED_FRAC = HOLD_FRAC   # 데드존과 같은 기준 — 제어가 쉬는 구간은 판정도 쉰다

# ── 환기 우선 (사용자 옵션 vent_first) ────────────────────────────────────────
# `hvac_interlock`(냉난방 가동 중 창 잠금)의 짝이다. 실외가 목표 **너머**에
# 있으면 환기만으로 목표에 닿을 수 있고, 그때 냉난방을 함께 돌리는 것은 바깥
# 공기가 공짜로 할 일을 돈 주고 하는 것이다.
#
# 실측(2026-08-26 イチゴ): 실내 VPD 0.253 · 목표 0.579 · 실외 0.895 에서 창을
# 다 열면 한 사이클에 0.588 kPa 를 옮길 수 있는데, 난방기가 80% 로 올라가고
# 있었다. 도메인 분리 이후 난방기는 창이 하는 일을 모르기 때문이다 —
# 도메인 간 조율은 암묵적 누적이 아니라 **이렇게 선언된 인터록**이 맡는다.
#
# 파킹 조건 셋을 모두 만족해야 한다(하나라도 어긋나면 냉난방을 그대로 둔다):
#   ① 실외가 목표를 **여유(tolerance×VENT_REACH_MARGIN)만큼 지나** 있다.
#      딱 걸치면 환기는 목표에 점근할 뿐 닿지 못하고 경계에서 깜빡인다.
#   ② 제어 대상 변수가 **전부** 그렇다. 하나라도 환기로 못 가면 냉난방이 필요하다.
#   ③ 환기에 **여력이 남아 있다**. 창이 이미 만개인데 편차가 남으면 그때는
#      냉난방이 도와야 한다 — 여기서 파킹하면 아무도 일하지 않는다.
#   ④ 파킹한 지 얼마 안 됐다. 아래 '실패하면 넘긴다' 참조.
VENT_REACH_MARGIN  = 1.0     # 실외가 목표를 넘어서야 할 여유 (tolerance 배수)

# ⚠ **평균이 아니라 최댓값이다.** 평균을 쓰면 안 열리는 창 하나가 escalation 을
#   통째로 막는다 — 개구부 셋 중 하나가 0% 에 고착되면 나머지 둘이 만개해도
#   평균은 67% 라 90% 에 영영 못 닿고, 냉난방은 어떤 경우에도 안 켜진다
#   (2026-08-26 実測: 側面窓 9%/33% · 天窓 0% 인 채로 난방기가 계속 파킹됐다).
#   한 창이라도 만개면 그 창은 더 밀 데가 없다 — 그것이 '여력 없음' 의 뜻이다.
VENT_HEADROOM_PCT  = 90.0    # 직전 **최대** 개도가 이보다 낮아야 '여력 있음'

# ── 실패하면 넘긴다 ──────────────────────────────────────────────────────────
# ③ 만으로는 부족하다. "여력이 있나" 는 물어도 "실제로 되고 있나" 는 안 묻기
# 때문에, 창이 조금 열린 채 목표에 안 닿아도 냉난방은 무한정 파킹된다.
# 예측(실외가 목표 너머)이 맞다면 편차는 줄어들어 판정이 스스로 꺼진다 —
# 그러지 않고 계속 벗어나 있다는 것은 **예측이 틀렸다**는 뜻이고, 그때는
# 냉난방에 넘긴다.
#
# 값은 strain 판정(`_STRAIN_MIN_SEC`)과 같은 15분이다. 둘 다 "한두 사이클의
# 흔들림과 가른다" 는 같은 이유이고, 다르게 두면 화면이 "못 따라가고 있다"고
# 말하는 동안에도 냉난방은 파킹돼 있는 구간이 생긴다.
VENT_FIRST_PATIENCE_S = 900.0

G_MIN_EFFECT = 0.025 # 유효도(g=magnitude/pband) 하한. 100% 가동해도 변수를 비례밴드의
                     # 2.5%/cycle 미만으로밖에 못 움직이면(예: 환기인데 내외차 거의 없음)
                     # 권한 없음으로 보고 idle — 헛돌며 적분 와인드업 하는 것 방지.
                     # 측정상 무구배 g≈0.008~0.011, 약구배(ΔT≥1°C) g≳0.05 로 명확히 분리.


# ─────────────────────────────────────────────────────────────────────────────
# Coordination state (preserved across cycles)
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class CoordinatorState:
    """Returned as the result of each cycle, passed as prev to the next cycle.

    integral: 액추에이터별 평형 개도(%) 기억. 키 = actuator_id, 값 ∈ [0,100].
              (P6 이전엔 변수별 native 누적이었음 — 자동 마이그레이션됨)
    """
    prev_commands: Dict[str, float] = field(default_factory=dict)
    integral:      Dict[str, float] = field(default_factory=dict)
    active_vars:   Dict[str, bool]  = field(default_factory=dict)  # 텔레메트리/hysteresis
    # 직전 사이클의 구동 방향(+1 더 열기 / −1 닫기). 방향 전환 감지 전용.
    # **일부러 영속화하지 않는다** — 재시작 직후 한 사이클만 전환 감지를 쉬면
    # 되고(보수적), 그것 때문에 마이그레이션을 만들 값어치가 없다.
    drive_sign:    Dict[str, int]   = field(default_factory=dict)
    # 환기 우선이 냉난방을 파킹한 채 목표를 못 맞추고 있는 누적 시간(초).
    # 판정이 꺼지면(=편차가 사라졌거나 환기로 못 간다고 판단) 0 으로 되돌린다.
    # **영속화하지 않는다** — 재시작 직후 인내를 처음부터 세는 것은 보수적인
    # 쪽이고(냉난방을 늦게 켠다), 그 때문에 마이그레이션을 만들 값어치가 없다.
    vent_first_held_s: float = 0.0
    # 데드존 안에서 잔여 편차가 **반대쪽**으로 넘어간 연속 사이클 수.
    # 한 번이라도 되돌아오면 0 이다 — 잡음으로 한 사이클 뒤집힌 것과
    # 진짜로 넘어간 것을 가르는 유일한 수단이다.
    # `drive_sign` 과 같은 이유로 **영속화하지 않는다**(재시작 후 한 사이클만
    # 보수적으로 쉬면 된다).
    deadzone_wrong_side: Dict[str, int] = field(default_factory=dict)


# ─────────────────────────────────────────────────────────────────────────────
# Command result
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class ActuatorCommand:
    value: float                       # dispatch value (motor position %, after operating-range mapping)
    reason: int
    var_source: Optional[str] = None   # the variable that triggered this command
    aperture: Optional[float] = None   # control coordinate (aperture %, for slew/prev computation)
    slewed: Optional[float] = None     # 슬루까지만 적용한 개도 (min-ON 스냅 **전**).
                                       # 적분 되먹임이 "속도에 막힌 것"과 "너무 작아
                                       # 버린 것"을 갈라 보기 위한 값 — 섞으면 안 된다
                                       # (coordinate() 의 되먹임 주석 참조).

    def control_value(self) -> float:
        """Coordinate value for slew/prev_commands computation — aperture preferred, otherwise value."""
        return self.aperture if self.aperture is not None else self.value


CoordResult = Dict[str, ActuatorCommand]


# ─────────────────────────────────────────────────────────────────────────────
# Main entry point
# ─────────────────────────────────────────────────────────────────────────────

def coordinate(
    situation: SituationReport,
    profiles: List[ActuatorProfile],
    state: CoordinatorState,
    unique_id: str = '',
    actuator_index: Dict[str, int] = None,
) -> Tuple[CoordResult, CoordinatorState]:
    """
    Run the L3 coordination algorithm (position-form PI).

    Args:
        situation:      L2 SituationReport
        profiles:       list of registered actuators (result of get_profile())
        state:          previous cycle state (pass CoordinatorState() for the first cycle)
        unique_id:      Function unique_id for InfluxDB recording
        actuator_index: {actuator_id: idx} — for logging channel computation

    Returns:
        (commands dict, updated CoordinatorState)
    """
    commands: CoordResult = {}
    ctx = situation.context
    cycle_sec = ctx.get('cycle_sec', 60.0)
    a_idx = actuator_index or {}

    valid_ids = {p.actuator_id for p in profiles}

    # ── 0. integral 마이그레이션/정합 ─────────────────────────────────────────
    # 키가 actuator_id 이고 값이 [0,100] 인 항목만 보존. 과거 변수별 native 누적
    # (예: 'humidity': -394) 은 키가 actuator_id 가 아니므로 자동 폐기된다.
    migrated_integral: Dict[str, float] = {}
    for aid, val in (state.integral or {}).items():
        if aid in valid_ids and isinstance(val, (int, float)):
            migrated_integral[aid] = _clamp(float(val), 0.0, 100.0)

    new_state = CoordinatorState(
        prev_commands=dict(state.prev_commands),
        integral=migrated_integral,
        active_vars=dict(state.active_vars),
        drive_sign=dict(state.drive_sign or {}),
        vent_first_held_s=float(getattr(state, 'vent_first_held_s', 0.0) or 0.0),
        # ⚠ **복사하지 않는다 — 매 사이클 새로 센다.** 이 카운터는 "지금
        # 데드존 안에서 반대쪽에 있다" 의 연속 횟수인데, 복사해 들고 다니면
        # 데드존을 벗어났다 돌아온 장치가 **옛 횟수를 이어받아** 한 사이클
        # 만에 물러난다. 이번 사이클에 그 경로를 지난 장치만 항목을 갖는다.
    )

    # 개구부 평균 개도(직전 명령 기준)를 ctx 에 주입 → 배기팬 압력 모델이 사용.
    # 덕트 없는 벽면 배기팬은 창이 열려 있으면 압력차가 안 생겨 무력하다.
    _op_aps = [state.prev_commands.get(p.actuator_id, 0.0)
               for p in profiles if getattr(p, 'kind', '') == 'opening']
    ctx['vent_open_frac'] = (sum(_op_aps) / len(_op_aps) / 100.0) if _op_aps else 0.0

    # ── 1. Manual-lock handling + live_effect computation (C2) ───────────────
    for p in profiles:
        if p.manual_lock.is_active():
            commands[p.actuator_id] = ActuatorCommand(
                value=p.manual_lock.manual_value,
                reason=REASON_MANUAL_OVERRIDE,
            )
            _log_cmd(unique_id, p.actuator_id, a_idx, p.manual_lock.manual_value,
                     REASON_MANUAL_OVERRIDE)
            continue

        p.live_effect = {
            var: p.effect_model[var](ctx, 100.0, p)   # G3: pass profile
            for var in p.effect_model
        }

    available = [p for p in profiles if p.actuator_id not in commands]

    # ── 2. Hysteresis 텔레메트리 (active_vars) ────────────────────────────────
    for var in situation.deviation_native:
        tgt = situation.target.get(var)
        if tgt is None:
            continue
        residual = situation.deviation_native[var]
        was_active = new_state.active_vars.get(var, False)
        thr = tgt.tolerance * (0.5 if was_active else 1.0)
        new_state.active_vars[var] = abs(residual) >= thr

    # ── P5-2: NATURAL 변수는 제어 대상에서 제외 (능동 권한 없음) ────────────────
    authority = getattr(situation, 'authority', {})
    natural_vars = {
        v for v in situation.deviation_native
        if authority and is_natural_var(authority, v)
    }

    # ── 2.5. 개구부 파킹 판정 (사용자 옵션 2종) ────────────────────────────────
    # 파킹된 액추에이터는 편차 비례로 조금씩 여는 대신 NO_GRADIENT 완화 경로로
    # 보내 safe_default 로 수렴시킨다. 두 판정은 성격이 다르다.
    #   (a) 환기 무익  — 실외 상태로는 목표에 갈 수 없다 (도달 가능성)
    #   (b) 냉난방 연동 — 갈 수는 있으나 냉난방과 맞서 에너지를 버린다 (상충)
    park_ids: set = set()
    vents = [p for p in available if getattr(p, 'kind', '') in VENTILATING_KINDS]

    if bool(ctx.get('vent_futility_gate', False)):
        futile = {p.actuator_id for p in vents
                  if _ventilation_is_futile(p, situation, ctx)}
        if futile:
            park_ids |= futile
            logger.debug(
                '환기 무익 — 실외 상태로는 목표에 못 감, %d개 파킹: %s',
                len(futile), sorted(i[:8] for i in futile))

    if bool(ctx.get('hvac_interlock', False)) and bool(ctx.get('hvac_running', False)):
        locked = {p.actuator_id for p in vents}
        if locked:
            park_ids |= locked
            logger.debug(
                '냉난방 연동 — 가동 중이라 개구부 %d개 잠금: %s',
                len(locked), sorted(i[:8] for i in locked))

    # ── 환기 우선 — 실외가 목표 너머면 냉난방을 쉬게 한다 ──────────────────────
    # `hvac_interlock` 의 짝이다. 둘 다 켜도 교착하지 않는다: 이 판정은 실외
    # 조건만 보므로 냉난방이 파킹되면 hvac_running 이 내려가고 개구부 잠금이
    # 풀린다. 반대로 환기 여력이 없으면 여기서 파킹하지 않으므로 냉난방이 계속
    # 일한다 — 아무도 일하지 않는 상태로 떨어지지 않는다.
    #
    # ⚠ 판정이 참인 동안 **인내 시간을 센다.** 예측이 맞다면 편차가 줄어 판정이
    #   스스로 꺼지므로 시간은 쌓이지 않는다. 쌓인다는 것은 곧 예측이 틀렸다는
    #   뜻이고, 그때는 파킹을 풀어 냉난방에 넘긴다(VENT_FIRST_PATIENCE_S).
    #
    # ⚠ **의지하는 정도는 둘이 아니라 연속이다** (2026-08-26). 예전에는
    #   "전부 된다"(파킹) 아니면 "아니다"(냉난방이 전체 편차를 혼자 계산)뿐이라,
    #   흔한 중간(실외가 목표의 일부를 메운다)에서 냉난방이 과다 가동했다.
    #   `_ventilation_credit` 이 그 몫을 재서 냉난방의 편차에서 뺀다.
    #   판단 기준은 스위치가 아니라 **내외 환경 차이**다 — 실외가 못 도우면
    #   크레딧이 0 이라 저절로 예전 동작이 된다.
    vent_credit: Dict[str, float] = {}
    if bool(ctx.get('vent_first', False)):
        hvac_ids = {p.actuator_id for p in available
                    if ACTUATOR_DOMAIN.get(getattr(p, 'kind', '')) == 'hvac'}
        _reaches = _ventilation_reaches_all_targets(
            situation, ctx, vents, state.prev_commands)
        _credit = ({} if _reaches else
                   _ventilation_credit(situation, ctx, vents, park_ids))
        if _reaches or _credit:
            # 환기에 **의지하고 있는** 동안 인내를 센다. 전부 맡기든 일부만
            # 맡기든, 목표에 못 닿은 채 시간이 흐르면 예측이 틀린 것이다.
            new_state.vent_first_held_s += float(cycle_sec)
            if new_state.vent_first_held_s >= VENT_FIRST_PATIENCE_S:
                # 넘겼다는 사실은 남긴다 — 안 그러면 "왜 갑자기 켜졌나" 에
                # 답할 근거가 어디에도 없다.
                logger.error(
                    '환기 우선 — %.0f분째 목표에 못 닿아 냉난방 %d개에 '
                    '전부 넘깁니다(실외 예측이 빗나갔습니다)',
                    new_state.vent_first_held_s / 60.0, len(hvac_ids))
            elif _reaches and hvac_ids:
                park_ids |= hvac_ids
                logger.debug(
                    '환기 우선 — 실외로 목표에 닿으므로 냉난방 %d개 파킹: %s',
                    len(hvac_ids), sorted(i[:8] for i in hvac_ids))
            else:
                vent_credit = _credit
                logger.debug(
                    '환기 우선 — 실외가 대신 해 주는 몫: %s',
                    {k: round(v, 3) for k, v in _credit.items()})
        else:
            new_state.vent_first_held_s = 0.0
    else:
        new_state.vent_first_held_s = 0.0

    # ── 2.55. 맞서는 짝은 **온도 축의 요구가 한쪽만 고른다** ──────────────────
    # 냉방과 난방은 온도 축에서 정확히 raise/lower 쌍이다. PID 는 오차 부호가
    # 한쪽만 고르므로 **방향을 정하는 행위 자체가 인터록**인데, 코디네이터는
    # 액추에이터마다 따로 PI 를 돌려서 그 성질이 공짜로 따라오지 않는다.
    # 그래서 여기서 명시적으로 준다 — 요구 방향의 반대편을 이 사이클의 후보에서
    # 뺀다(파킹).
    #
    # ⚠ **뒤에서 끄는 것으로는 부족하다.** 디스패치 직전 인터록
    # (`_cycle_mixin.apply_hvac_opposition_interlock`)은 마지막 방어선이지만,
    # 그때까지 진 쪽은 **매 사이클 100% 를 원하며 적분을 쌓는다.** 여기서 빼면
    # 적분이 safe_default 로 풀린다(아래 NO_GRADIENT 경로).
    #
    # ⚠ **VPD 직접 제어 모드에서는 온도가 제어목표에 없다.** `_decompose_vpd`
    # 가 'temperature' 를 `_temperature_constraint` 로 강등하므로
    # `deviation_native` 에 온도가 아예 없다 — 그래서 편차 부호만 보면 이 판정이
    # **통째로 서지 않는다.** 실측(2026-08-26 温室環境制御)에서 난방기를 100%
    # 로 만든 근거는 온도가 아니라 VPD 였고, 그동안 실내는 하드 상한을 4°C
    # 넘겨 있었다. 그래서 하드 임계를 **먼저** 본다.
    #
    #   1) 하드 임계 위반(temp_max/temp_min) — 사용자가 정한 문턱. 최우선.
    #   2) 온도 잔여 편차의 부호 — 허용오차 밖일 때만. 제어목표에서 강등됐어도
    #      목표·허용오차는 `_temperature_constraint` 에 그대로 남아 있다.
    #   3) 둘 다 없으면 제한하지 않는다 — 온도가 편안한 구간이면 VPD 를 위해
    #      가온하거나 냉방하는 것이 옳다.
    # 파킹 사유를 구분해 두는 집합. 같은 파킹이라도 **왜** 쉬는지가 다르면
    # 화면이 다른 말을 해야 한다(0% 로 쉬는 난방기에게 "할 수 있는 만큼 하고
    # 있다" 는 정반대의 말이다).
    opposing_ids: set = set()
    _internal = (ctx.get('internal') or {})
    _demand = None
    if bool(_internal.get('_force_cool')):
        _demand = 'cool'
    elif bool(_internal.get('_force_heat')):
        _demand = 'heat'
    else:
        _t_now = ctx.get('T_int')
        _t_tv = ((situation.target or {}).get('temperature')
                 or (situation.target or {}).get('_temperature_constraint'))
        _tol = float(getattr(_t_tv, 'tolerance', 0.0) or 0.0) if _t_tv else 0.0
        if _t_now is not None and _t_tv is not None and _tol > 0:
            _t_dev = float(_t_now) - float(_t_tv.value)
            if _t_dev > _tol:
                _demand = 'cool'
            elif _t_dev < -_tol:
                _demand = 'heat'
    if _demand:
        _losing_kind = 'heater' if _demand == 'cool' else 'cooler'
        _losers = {p.actuator_id for p in available
                   if getattr(p, 'kind', '') == _losing_kind}
        if _losers:
            park_ids |= _losers
            opposing_ids |= _losers
            logger.debug(
                '온도 축 요구=%s — 반대편 %s %d개 파킹: %s',
                _demand, _losing_kind, len(_losers),
                sorted(i[:8] for i in _losers))

    # ── 2.6. 실외 근거가 지어낸 것이면 → **제자리 유지**(hold) ──────────────────
    # 환기는 실내를 실외 쪽으로만 밀 수 있으므로, 실외를 모르면 열지 닫을지 말할
    # 근거가 없다. 그런데 지금 구조는 실외를 모를 때 fallback 이 **실외=실내**로
    # 가정해 채운다(`ext_context_fallback`, 캐시가 비었을 때). 그러면 내외 차이가
    # 0 이라 환기 무익 판정이 서고 개구부가 safe_default(닫힘)로 수렴한다 —
    # 한여름에 기상대가 죽으면 창이 닫힌다는 뜻이다. 실측(리플레이에서 기상대만
    # 제거): 71 사이클 전부 NO_GRADIENT, 개도가 0 까지 내려갔다.
    #
    # 파킹(위 2.5)과 다르다 — 파킹은 닫는 것이고, 여기서 해야 할 일은 **아무것도
    # 하지 않는 것**이다. 근거가 없다는 이유로 장비를 움직여서는 안 된다.
    #
    # 판정은 `_ext_synthetic`(캐시조차 없어 지어낸 실외) 하나로 한다. 마지막
    # 실측이 남아 있으면(캐시 hit) 그것은 근거이므로 여기 걸리지 않는다.
    if bool((ctx.get('external') or {}).get('_ext_synthetic')):
        hold_ids = {p.actuator_id for p in vents}
    else:
        hold_ids = set()
    if hold_ids:
        # 근거 없음이 근거 있는 판정을 이겨서는 안 되므로 파킹에서 뺀다.
        park_ids -= hold_ids
        logger.debug(
            '실외 측정 없음(지어낸 값) — 개구부 %d개 제자리 유지: %s',
            len(hold_ids), sorted(i[:8] for i in hold_ids))

    # ── 3. Per-actuator position-form PI (다목적 결합 drive) ───────────────────
    # accumulated: 이미 확정된 명령들이 만들 **부호 있는 물리 변화량**(native).
    # 부호는 물리 방향 그대로다('↑'=+, '↓'=−, 아래 축적부 참조). 따라서 잔여
    # 편차는 deviation **+** accumulated 다 — 편차가 current−target 이고
    # accumulated 가 current 에 더해질 변화량이므로, 확정 후 예상 편차는
    # (current + accumulated) − target 이다.
    #
    # **도메인마다 따로 쌓는다**(ACTUATOR_DOMAIN 주석 참조). 창의 기여는 창끼리만
    # 보고, 냉방·가습은 그것을 아예 모른다 — 한 장비의 오작동이 남을 거꾸로
    # 켜는 경로를 구조적으로 없앤다.
    accumulated: Dict[str, Dict[str, float]] = {
        dom: {var: 0.0 for var in situation.deviation_native}
        for dom in set(ACTUATOR_DOMAIN.values()) | {DEFAULT_DOMAIN}
    }

    # 저렴한 액추에이터부터 확정 → 이후 것들은 잔여 편차를 보고 적게 동작(부하분담).
    order = sorted(available, key=lambda p: p.cost_fn(ctx, 100.0))

    for p in order:
        accum = accumulated[domain_of(p)]
        _is_hvac = ACTUATOR_DOMAIN.get(getattr(p, 'kind', '')) == 'hvac'
        prev_val = state.prev_commands.get(p.actuator_id, 0.0)
        I = new_state.integral.get(p.actuator_id, 0.0)
        kp = p.gains.get('kp', POS_KP)
        ki = p.gains.get('ki', POS_KI)

        # ── 결합 drive: 이 액추에이터가 제어 가능한 모든 변수의 정규화 drive 를
        #    priority × 유효도(effect magnitude)로 가중합한다. 이는 가중 오차제곱합의
        #    음의 기울기(gradient-descent) 방향으로, "냉방 개방 이득 vs 습도 악화"
        #    같은 다목적 트레이드오프를 단일 평형으로 수렴시킨다.
        #    (기존 primary-var 선택 + binary conflict 의 toggle limit-cycle 제거)
        #    effect 방향이 외기차 부호에 따라 뒤집히므로(외기가 더 더우면 개방=가온),
        #    역방향 개방도 자동 음(─) drive 로 차단된다.
        #    주의: g_v 는 변수 간 '상대' 가중치만 정한다. e_norm=num/den 은 정규화되어
        #    절대 유효도를 반영하지 못하므로(무구배에도 편차 비례로 명령 → 헛돎),
        #    아래에서 max_g(절대 유효도)로 권한 게이트를 따로 건다.
        num = 0.0
        den = 0.0
        max_g = 0.0
        primary_var = None
        primary_score = -1.0
        for v, eff in p.live_effect.items():
            if eff.direction not in ('↑', '↓'):
                continue
            if v in natural_vars or v not in situation.deviation_native:
                continue
            t = situation.target.get(v)
            if t is None or t.tolerance <= 0:
                continue
            # 부호 주의: 빼면 부하'분담'이 부하'증폭'이 된다. 앞 장비가 −3°C 를
            # 확정했는데 편차 +5 에서 5−(−3)=8 을 보면 뒤 장비는 혼자일 때보다
            # 더 세게 돈다. 실제로 2026-08-20 로컬 육묘장에서 분무 64.9%(모델상
            # −29.6°C)가 냉방기에 +29.6°C 로 넘어가 편차 0 인데도 냉방 100%,
            # 난방 0% 로 고착됐다. 위 주석의 "적게 동작"과도 반대였다.
            residual_v  = situation.deviation_native[v] + accum.get(v, 0.0)
            if _is_hvac:
                # 실외가 대신 해 주는 몫만큼 냉난방의 짐을 던다. 부호는 편차를
                # **0 쪽으로** 옮기는 방향이고(`_ventilation_credit` 이 need 를
                # 넘지 않게 잘라 놓는다), 그래서 부호가 뒤집힐 수 없다.
                # ⚠ 환기 자신에게는 적용하지 않는다 — 자기가 할 일을 자기
                #   편차에서 빼면 창이 열리지 않는다.
                residual_v += vent_credit.get(v, 0.0)
            effect_sign = 1.0 if eff.direction == '↑' else -1.0
            pband_v     = max(PBAND_MULT * t.tolerance, 1e-9)
            e_v         = (-residual_v * effect_sign) / pband_v    # + = 더 열기
            g_v         = eff.magnitude_native / pband_v           # 유효도(구동력)
            w_v         = max(t.priority, 1e-6) * g_v
            num += w_v * e_v
            den += w_v
            max_g = max(max_g, g_v)
            score = abs(residual_v) / t.tolerance * t.priority
            if score > primary_score:
                primary_score = score
                primary_var = v

        if p.actuator_id in hold_ids:
            # 실외 근거 없음 → **제자리**. 감쇠하지 않는다(그건 닫는 것이다).
            # 적분도 그대로 둔다 — 모르는 동안 '평형 개도 기억'을 흔들면 실외가
            # 돌아왔을 때 엉뚱한 자리에서 다시 출발한다.
            cmd_raw = _clamp(prev_val, 0.0, 100.0)
            reason = REASON_NO_OUTDOOR_DATA
        elif den <= 1e-12 or max_g < G_MIN_EFFECT or p.actuator_id in park_ids:
            # 제어 가능 변수 없음 OR 유효 구동력 없음(무구배 환기 등) OR 파킹 대상
            # (환기 무익 / 냉난방 연동 — 2.5 참조) → 안전 idle
            # 위치(safe_default)로 부드럽게 수렴하고 적분을 풀어준다. 100% 가동해도
            # 효과 없는 액추에이터를 편차 비례로 켜 두면 성과 없이 작동시간만 늘고
            # 적분이 와인드업한다. safe_default 기준으로 감쇠하므로 개구부(sd=0)는
            # 닫힘, 스크린(보온커튼·차광막 sd=100)은 걷힘으로 수렴한다.
            #
            # 주의: 여기서 반드시 prev_val(직전 실제 dispatch 위치)에서 감쇠해야
            # 한다. I(적분)에서 감쇠하면 안 된다 — I 는 포화(saturation) 중
            # anti-windup back-calculation(아래 else 분기, L266~267)에 의해
            # dispatch 값과 무관하게 낮아질 수 있다. 예: 스크린이 며칠째 100%로
            # 열려 있어도(강한 냉방 수요로 P+I 가 100을 크게 초과) I 는 그 이면에서
            # 조용히 0 근처까지 깎일 수 있고, 그 상태에서 갑자기 무구배로 전환되면
            # "표시상 100%였는데 다음 사이클에 40%로 뚝 떨어지는" 것처럼 보이는
            # 명령 급변이 발생한다(2026-07-29 aot-005 폭염 중 보온커튼 오폐쇄 사건의
            # 원인). prev_val 은 dispatch 좌표 그대로이므로 이 괴리가 없다.
            sd = p.safe_default
            I = sd + (prev_val - sd) * RELAX_FACTOR
            cmd_raw = _clamp(I, 0.0, 100.0)
            # 같은 감쇠 경로를 쓰되 **사유는 나눈다** — 맞서는 짝의 진 쪽은
            # "밀어도 안 움직인다"(무구배)가 아니라 "지금 밀 방향이 아니다"다.
            reason = (REASON_OPPOSING_PARKED
                      if p.actuator_id in opposing_ids else REASON_NO_GRADIENT)
        else:
            e_norm = num / den
            # 데드존을 분기가 아니라 '빼기'로 적용한다 — 경계에서 P항이 0 으로
            # 연속 수렴하므로 입력이 경계를 넘나들어도 명령 계단이 생기지 않는다.
            # (분기 구현이 만들던 ±kp·hb·100 계단 = 야간 창호 진동의 직접 원인)
            e_eff = math.copysign(
                max(0.0, abs(e_norm) - HOLD_FRAC / PBAND_MULT), e_norm)
            if e_eff == 0.0:
                # ── 평형 근방(결합오차 작음) → 적분 동결, 직전 평형 개도 유지
                #
                # ⚠ 그런데 **넘어선 채로 얼어붙을 수 있다.** 데드존 안에서는
                # e_eff=0 이라 구동이 없고, 구동이 없으면 방향 판정도 서지
                # 않는다 — 그래서 잔여 편차가 부호를 넘어가도 그 순간의 명령이
                # 그대로 유지되고 근거는 PRIMARY 로 남는다.
                #
                # 실측(2026-08-26 영양 육묘장): 낮에 VPD 가 목표보다 높아 냉방기
                # 적분이 100% 까지 감겼고, VPD 가 목표로 내려와 편차가 −0.0 이
                # 된 순간 그 100% 가 얼어붙었다. 그 시점의 냉방기는 VPD 를
                # **내리는** 쪽(모델: vpd ↓0.484)이라 방향이 이미 반대였다.
                # **목표에 도달했다는 사실이 잘못된 출력을 고정한 것이다.**
                #
                # 그래서 데드존 안이라도 부호가 반대면 물러난다. 다만 **한
                # 사이클의 부호로 판단하지 않는다** — 데드존이 있는 이유가
                # 센서 잡음이고, 잡음은 매 사이클 부호가 뒤집힌다. 연속으로
                # 같은 쪽이어야 "넘어갔다" 이고, 한 번이라도 되돌아오면 0 이다.
                # 읽기는 직전 상태, 쓰기는 새 상태 — 새 상태는 비어서 출발하므로
                # 이 경로를 안 지난 장치는 자동으로 0 이 된다.
                if e_norm < 0.0:
                    _n = (state.deadzone_wrong_side or {}).get(
                        p.actuator_id, 0) + 1
                    new_state.deadzone_wrong_side[p.actuator_id] = _n
                else:
                    _n = 0
                if _n >= DEADZONE_BACKOFF_CYCLES:
                    # 파킹과 **같은 감쇠 경로**를 쓴다(RELAX_FACTOR, safe_default
                    # 기준). 감쇠율을 여기만 따로 두면 "왜 이 장치만 다르게
                    # 내려오는가" 에 답할 자리가 없어진다.
                    sd = p.safe_default
                    I = sd + (prev_val - sd) * RELAX_FACTOR
                    cmd_raw = _clamp(I, 0.0, 100.0)
                    reason = REASON_DEADZONE_BACKOFF
                else:
                    cmd_raw = _clamp(I, 0.0, 100.0)
                    reason = REASON_PRIMARY
            else:
                # ── 방향 전환 시 적분을 실제 개도로 되앉힌다 (PID 컨트롤러 차용)
                # PID 는 direction='both' 에서 올림↔내림이 뒤집히는 순간
                # `integrator = 0.0` 으로 지운다. 한쪽에서 쌓은 누적이 반대쪽으로
                # 넘어가면, 이미 방향이 바뀌었는데도 그 값이 명령을 계속 밀기
                # 때문이다 — 실측: 냉방기가 I=97.9 를 들고 있어, VPD 를 올려야
                # 하는 상황으로 바뀐 뒤에도 계속 돌았다.
                #
                # ⚠ **0 으로 지우면 안 된다.** 여기서 적분은 PID 의 '누적 오차'가
                # 아니라 **'기억된 평형 개도(%)'** 다. 0 = "완전히 닫아라" 라서,
                # 그대로 베끼면 방향이 바뀔 때마다 창이 쾅 닫혔다 다시 열린다.
                # 같은 뜻을 갖는 조치는 **실제 서 있는 자리로 되앉히는 것**이다:
                # 옛 방향의 기억은 지우면서 물리적 연속성은 지킨다.
                _sign = 1 if e_eff > 0 else -1
                if new_state.drive_sign.get(p.actuator_id, 0) == -_sign:
                    I = _clamp(prev_val, 0.0, 100.0)
                new_state.drive_sign[p.actuator_id] = _sign

                I = _clamp(I + ki * e_eff, 0.0, 100.0)
                p_term = kp * e_eff * 100.0
                cmd_unclamped = p_term + I
                cmd_raw = _clamp(cmd_unclamped, 0.0, 100.0)
                if cmd_unclamped != cmd_raw:
                    if abs(prev_val - cmd_raw) <= RAIL_EPS:
                        # ── 레일 고착 회복 경로 ────────────────────────────
                        # 직전 dispatch 가 이미 이 레일이다 = 최소 한 사이클
                        # 이상 여기 눌러붙어 있었다. 그 상태의 적분은 '기억된
                        # 평형 개도'가 아니라 **포화 부산물**이라 값에 뜻이 없다.
                        # 실제 개도(cmd_raw) 쪽으로 기하 감쇠시켜 적분이 자기
                        # 정의(=이 액추에이터가 서 있는 자리)를 되찾게 한다.
                        I = cmd_raw + (I - cmd_raw) * RELAX_FACTOR
                    else:
                        # 갓 포화 — 표준 back-calculation(포화분만큼 되돌림).
                        # 첫 사이클의 빠른 anti-windup 은 그대로 둔다.
                        I = _clamp(I - (cmd_unclamped - cmd_raw) * AW_BETA,
                                   0.0, 100.0)
                reason = REASON_PRIMARY

        cmd = finalize_command(p, cmd_raw, prev_val, cycle_sec,
                               reason=reason, var_source=primary_var)
        commands[p.actuator_id] = cmd
        cmd_ap = cmd.control_value()

        # ── 속도에 막힌 몫만 적분에 되먹인다 (2026-08-26) ────────────────────
        # 적분의 뜻은 '기억된 평형 개도'다. 그런데 anti-windup 이 [0,100] 클램프
        # 만 되먹이고 **슬루(변화율) 제한은 되먹이지 않아**, PI 가 88.7% 를
        # 원하고 실제로는 25% 만 나가도 적분은 88.7 이 나간 것처럼 계속 자랐다.
        # 그렇게 부풀려진 적분은 자기 정의를 잃고(실측: 側面窓右 I=67.9 인데
        # 실제 개도 25.0), 그 값이 만든 과장된 물리 기여가 부하분담을 타고
        # 남을 거꾸로 켰다 — 2026-08-25 사고의 근원이다.
        #
        # ⚠⚠ **min-ON 스냅은 되먹이면 안 된다.** 둘은 "요구만큼 못 나갔다" 로
        # 같아 보이지만 뜻이 정반대다.
        #
        #   슬루     장치가 **가고는 있다**. 덜 간 몫은 허구이므로 되돌린다.
        #   min-ON  장치가 **아무것도 안 했다**. 몇 초 켜서는 실제 출력이 안
        #           나오는 장치가 많아 일부러 버린 것이다. 여기서 적분까지
        #           깎으면 적분이 문턱을 **영영 못 넘어** 장치가 한 번도 안
        #           도는 교착이 된다.
        #
        # 그래서 버린 몫은 적분에 남긴다 — 쌓여서 의미 있는 한 번을 만들 때
        # 몰아서 켜진다. 펄스 **폭**이 아니라 **빈도**로 조절하는 것이고,
        # PID 컨트롤러의 on/off 경로가 같은 판단을 한다(`raise_min_duration`
        # 미만이면 출력을 건너뛰되 integrator 는 그대로 쌓는다). 적분은
        # [0,100] 하드클램프가 있으므로 이래도 무한히 자라지 않는다.
        #
        # ⚠ 세 분기(hold·무구배·평형)는 적분을 이미 자기 규칙으로 정했으므로
        # 건드리지 않는다 — 그 값들은 요구가 아니라 **의도된 위치**다.
        reachable = cmd.slewed if cmd.slewed is not None else cmd_ap
        if reason == REASON_PRIMARY and abs(cmd_raw - reachable) > 1e-9:
            I = _clamp(I - (cmd_raw - reachable) * AW_BETA, 0.0, 100.0)

        new_state.integral[p.actuator_id] = I

        # 확정 효과 누적 (모든 변수) — 부하분담용. slew 적용된 개도 사용.
        # **자기 도메인 안에만** 쌓는다(위 accumulated 주석 참조).
        for v, e in p.live_effect.items():
            s = 1.0 if e.direction == '↑' else (-1.0 if e.direction == '↓' else 0.0)
            accum[v] = accum.get(v, 0.0) + e.magnitude_native * (cmd_ap / 100.0) * s

        _log_cmd(unique_id, p.actuator_id, a_idx, cmd_ap, reason)

    # ── 4. 명령을 못 받은 프로필(이론상 없음) → 안전 기본값 ──────────────────────
    for p in profiles:
        if p.actuator_id not in commands:
            commands[p.actuator_id] = ActuatorCommand(
                value=p.safe_default, reason=REASON_IDLE)
            _log_cmd(unique_id, p.actuator_id, a_idx, p.safe_default, REASON_IDLE)

    # prev_commands 갱신 — slew 계산은 개도(aperture) 좌표 사용.
    new_state.prev_commands = {
        aid: cmd.control_value() for aid, cmd in commands.items()}

    return commands, new_state


# ─────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────────────────────────────────


def finalize_command(
    p: ActuatorProfile,
    aperture_pct: float,
    prev_aperture: float,
    cycle_sec: float,
    reason: int,
    var_source: Optional[str] = None,
) -> ActuatorCommand:
    """0–100% aperture 명령에 slew·min-ON·operating-range 매핑을 적용.

    PI(coordinator), greybox-PI, MPC 세 경로가 공유하는 명령 최종화 단계.
    - slew: 물리 속도 한계 내로 이전 명령 대비 변화량 제한
    - min-ON: 미세 개도(0<x<min_on)는 0 으로 스냅
    - operating-range: aperture 0–100 을 실제 모터 작동범위로 선형 매핑
    """
    # ── 이 사이클의 전달 비율을 **먼저** 반영한다 (2026-08-26) ──────────────────
    # 풍향 가중치·게이트 차단처럼 "요구대로 다 못 나가는" 물리 제약은 반드시
    # 여기를 지나야 한다. coordinate() **밖**에서 명령에 곱하면 코디네이터는
    # 원래 값이 나갔다고 믿어 ① 적분이 영영 수렴하지 못하고 ② 부하분담에
    # 과장된 효과가 실리고 ③ 제약이 풀리는 순간 쌓인 적분이 계단으로 튀어나온다.
    # 셋 다 실측했다 — 側面窓右(24.6% 명령 / 5.0% 실제, 풍향 가중치 0.2)와
    # 습윤형 분무기(61% 명령 / 0% 실제, 습도 상한 게이트).
    #
    # 슬루보다 앞이다: 실제 움직임이 속도 한계를 받아야 하기 때문이다.
    # ⚠ **0 은 슬루를 지나지 않는다.** 비율(0<s<1)은 "위치 목표를 이만큼 낮춰라"
    # 라서 장치가 자기 속도로 이동하는 게 맞지만, 0 은 "이번 사이클엔 아예 주지
    # 마라"(게이트 차단)라 중간 위치를 거칠 것이 없다. 슬루를 태우면 직전 60%
    # 였던 분무기가 차단 후에도 40% → 20% 로 계속 뿌리고, 코디네이터는 그 값이
    # 나갔다고 배워 적분도 안 내려간다 — 막았다는 사실이 아무 데도 안 닿는다.
    scale = getattr(p, 'cmd_scale', 1.0)
    if scale is not None and float(scale) <= 0.0:
        return ActuatorCommand(
            value=p.cmd_constraints.map_aperture_to_motor(0.0), reason=reason,
            var_source=var_source, aperture=0.0, slewed=0.0)
    if scale is not None and scale != 1.0:
        aperture_pct = _clamp(aperture_pct * float(scale), 0.0, 100.0)

    # 스크린(curtain/shade)은 디스패치에서 0/100 binary 로 스냅된다. slew 를 적용하면
    # 50% 경계를 못 넘어(예: 100→80→여전히 열림) 닫힘/열림 전환이 봉쇄되므로 우회한다.
    if getattr(p, 'kind', '') in ('curtain', 'shade'):
        cmd_slew = aperture_pct
    else:
        slew = p.cmd_constraints.effective_slew(cycle_sec)
        cmd_slew = _clamp(aperture_pct, prev_aperture - slew, prev_aperture + slew)
    reachable = cmd_slew                 # 속도 한계까지만 반영 — 되먹임의 기준
    if 0.0 < cmd_slew < p.cmd_constraints.min_on_pct:
        cmd_slew = 0.0
    cmd_motor = p.cmd_constraints.map_aperture_to_motor(cmd_slew)
    return ActuatorCommand(value=cmd_motor, reason=reason,
                           var_source=var_source, aperture=cmd_slew,
                           slewed=reachable)


def _clamp(val: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, val))


def _same_sign(a: float, b: float) -> bool:
    return (a > 0 and b > 0) or (a < 0 and b < 0)


def _outdoor_reachable(var: str, ctx: Dict) -> Optional[float]:
    """환기를 최대로 했을 때 실내 변수가 수렴하는 값(= 실외 값). 모르면 None.

    환기는 실내 공기를 실외 공기로 바꾸는 것이므로, 도달 가능한 끝점은 실외
    상태다. 그 사이 어디까지 갈지는 개도와 풍량이 정하지만, **어느 쪽 방향으로
    갈 수 있는지**는 이 값 하나로 정해진다.
    """
    if var == 'temperature':
        return ctx.get('T_ext')
    if var == 'humidity':
        return ctx.get('RH_ext')
    if var == 'co2':
        return ctx.get('CO2_ext')
    if var == 'vpd':
        T_e, RH_e = ctx.get('T_ext'), ctx.get('RH_ext')
        if T_e is None or RH_e is None:
            return None
        svp = 0.6108 * math.exp(17.27 * float(T_e) / (float(T_e) + 237.3))
        return svp * (1.0 - float(RH_e) / 100.0)
    return None


def _ventilation_reaches_all_targets(
        situation: SituationReport, ctx: Dict, vents: List[ActuatorProfile],
        prev_commands: Dict[str, float]) -> bool:
    """환기만으로 **모든** 제어 목표에 닿을 수 있는가 (vent_first 판정).

    닿는다 = 실외가 목표를 tolerance×VENT_REACH_MARGIN 만큼 **지나** 있다.
    딱 걸치면 환기는 목표에 점근할 뿐이라 닿았다고 할 수 없고, 경계에서
    켜졌다 꺼졌다 한다.

    ⚠ 판정 대상은 **벗어난 변수만**이다. 이미 범위 안인 변수는 찬반 근거가
    못 되므로 건너뛴다 — 포함시키면 "평형이라 avail 이 0" 이라는 이유로 항상
    False 가 되어 이 기능이 한 번도 서지 않는다.

    ⚠ 벗어난 변수가 하나도 없으면 False 다. 평형 상태에서 냉난방을 파킹하는
    것은 이 옵션이 하려는 일이 아니다(그건 데드존이 이미 한다).
    """
    if not vents:
        return False
    # 환기 여력이 없으면(창이 이미 만개) 냉난방이 도와야 한다.
    # ⚠ **최댓값**이다 — 평균이면 0% 에 고착된 창 하나가 escalation 을 영영
    #   막는다(VENT_HEADROOM_PCT 주석 참조).
    aps = [prev_commands.get(p.actuator_id, 0.0) for p in vents]
    if aps and max(aps) >= VENT_HEADROOM_PCT:
        return False

    decisive = False
    for var, dev in situation.deviation_native.items():
        t = situation.target.get(var)
        if t is None or t.tolerance <= 0:
            continue
        need = -dev                                  # + = 값을 올려야 함
        if abs(need) <= t.tolerance * VENT_NEED_FRAC:
            continue                                 # 범위 안 — 판정 대상 아님
        reachable = _outdoor_reachable(var, ctx)
        if reachable is None:
            return False                             # 실외를 모르면 단정하지 않는다
        measured = t.value + dev
        avail = float(reachable) - measured
        decisive = True
        if not _same_sign(need, avail):
            return False                             # 방향이 반대 — 환기로는 못 간다
        if abs(avail) < abs(need) + t.tolerance * VENT_REACH_MARGIN:
            return False                             # 목표에 못 미친다(점근만)
    return decisive


def _ventilation_credit(
        situation: SituationReport, ctx: Dict, vents: List[ActuatorProfile],
        blocked: set) -> Dict[str, float]:
    """실외가 **대신 해 줄 수 있는 몫** → {변수: 편차 보정값}.

    ## 왜 필요한가 — `vent_first` 는 이분법이었다

    파킹 판정은 "환기로 **전부** 되는가" 하나만 묻는다. 그래서 상태가 둘뿐이다:

        전부 된다  → 냉난방 파킹
        아니다     → 냉난방이 **전체 편차**를 자기 혼자 메울 값으로 계산

    실제로 흔한 것은 그 중간이다. 실측(2026-08-26 쿠마모토 イチゴ):

        실내 VPD 0.67   목표 1.0   실외 0.897
        실외가 메울 수 있는 몫 = (0.897−0.67)/(1.0−0.67) = 69%

    실외가 목표까지의 69% 를 공짜로 해 주는데, 난방기는 그것을 **모른 채**
    −0.33 전부를 자기 몫으로 계산해 46.5% 로 돌고 있었다. 창은 열려 있고
    난방기는 과다 가동 — 열을 버리며 데운다.

    ## 왜 `hvac_interlock`(창 잠금)이 답이 아닌가

    잠그면 그 69% 를 통째로 버리고 난방 부하가 3배가 된다. 열 손실은 막지만
    더 많은 에너지를 쓴다. 판단 기준은 스위치가 아니라 **내외 환경 차이**여야
    한다 — 실외가 도울 수 있으면 맡기고, 못 하면 그만큼만 냉난방이 진다.
    실외가 전혀 못 도우면 이 함수가 0 을 돌려주므로 냉난방이 전부 맡는다
    (= 잠금 없이도 겨울에는 저절로 예전 동작이 된다).

    ## ⚠ 도메인 간 부하분담을 되살리는 것이 아니다

    2026-08-25 사고는 액추에이터가 **주장한 효과**(모델 출력)를 도메인 너머로
    넘기다 부호가 뒤집혀 반대편을 켰다. 여기서 넘기는 것은 모델 출력이 아니라
    **실외 측정값**이다 — 어떤 액추에이터의 주장도 아닌 독립적인 물리 상한이고,
    한 장치가 고장 나도 값이 바뀌지 않는다. 그래서 그 사고의 성립 조건
    ("남의 주장을 근거로 내 방향을 정한다")이 여기엔 없다.

    ## 안전 조건 — 하나라도 어긋나면 그 변수는 크레딧 0

    창이 못 열리면(비·바람 게이트, 무익 판정, 실외 근거 없음) 실외는 아무것도
    못 해 준다. 그때 크레딧을 주면 **냉난방이 있지도 않은 도움을 믿고 물러난다**
    — 비 오는 날 난방이 모자라는 모양이 된다.
    """
    out: Dict[str, float] = {}
    live = [p for p in vents if p.actuator_id not in blocked]
    if not live:
        return out                          # 창이 하나도 못 움직인다 → 도움 없음
    if bool((ctx.get('external') or {}).get('_ext_synthetic')):
        return out                          # 실외를 지어낸 값이면 근거가 아니다

    for var, dev in situation.deviation_native.items():
        t = situation.target.get(var)
        if t is None or t.tolerance <= 0:
            continue
        need = -dev                                  # + = 값을 올려야 함
        if abs(need) <= t.tolerance * VENT_NEED_FRAC:
            continue                                 # 범위 안 — 나눌 것이 없다
        reachable = _outdoor_reachable(var, ctx)
        if reachable is None:
            continue
        measured = t.value + dev
        help_ = float(reachable) - measured          # 실외가 데려다 줄 수 있는 거리
        if not _same_sign(need, help_):
            continue                                 # 방향이 반대 — 도움이 아니다
        # ⚠ **need 를 넘겨선 안 된다.** 넘기면 보정된 편차의 부호가 뒤집혀
        #   냉난방이 반대로 돈다 — 2026-08-25 사고와 같은 모양이다.
        #   목표를 지나는 경우는 파킹 판정이 이미 전부 맡으므로 여기선 자른다.
        if abs(help_) > abs(need):
            help_ = need
        out[var] = help_
    return out


def _ventilation_is_futile(profile: ActuatorProfile,
                           situation: SituationReport,
                           ctx: Dict) -> bool:
    """이 환기 장치가 **어떤 제어변수도** 목표 쪽으로 못 옮기는가.

    변수마다 세 가지를 본다.
      need  = 목표 - 측정        (+ 면 값을 올려야 함)
      avail = 실외 - 측정        (환기로 갈 수 있는 방향과 여유)
      부호가 같고 둘 다 문턱을 넘으면 그 변수는 '환기로 개선 가능'.

    하나라도 개선 가능하면 무익이 아니다(False). 판단 근거가 될 만큼 벗어난
    변수가 하나도 없으면(전부 중립) 역시 False — 이때는 평상시 hold 가 맞다.
    실외값을 모르면 보수적으로 False(게이트 미발동).

    deviation_native 는 '측정 - 목표' 규약이므로 need = -deviation 이다.
    """
    decisive = False
    for var in profile.live_effect:
        if var not in situation.deviation_native:
            continue
        t = situation.target.get(var)
        if t is None or t.tolerance <= 0:
            continue
        dev = situation.deviation_native[var]      # 측정 - 목표
        need = -dev
        if abs(need) <= t.tolerance * VENT_NEED_FRAC:
            continue                              # 중립 — 찬반 근거가 못 된다
        reachable = _outdoor_reachable(var, ctx)
        if reachable is None:
            return False                          # 판정 불가 → 미발동
        measured = t.value + dev
        avail = float(reachable) - measured
        decisive = True
        if abs(avail) >= t.tolerance and _same_sign(need, avail):
            return False                          # 하나라도 환기로 개선 가능
    return decisive


def _log_cmd(
    unique_id: str,
    actuator_id: str,
    a_idx: Dict[str, int],
    value: float,
    reason: int,
):
    if not unique_id or actuator_id not in a_idx:
        return
    idx = a_idx[actuator_id]
    write_decision_log(unique_id, f'coord_actuator_{actuator_id[:8]}_command',
                       ch_coord_cmd(idx), value)
    write_decision_log(unique_id, f'coord_actuator_{actuator_id[:8]}_reason',
                       ch_coord_reason(idx), float(reason))
