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
    I       = clamp(I + ki·e_norm, 0, 100)    # 적분 = '평형 개도(%)' 기억, 항상 [0,100]
    cmd     = clamp(kp·e_norm·100 + I, 0,100)  # P(전이) + I(평형 유지)

  성질:
    - 평형/밴드 내 → e_norm≈0 → P≈0, I 유지 → 직전 개도 hold (진동 제거)
    - 오버슈트(너무 차가움 등) → drive<0 → I 감소 → 점진적 폐쇄
    - "올림" 방향도 effect_sign 으로 대칭 처리 (기존 부호 버그 제거)
    - I 는 [0,100] 하드클램프 + back-calculation anti-windup (무한 와인드업 제거)

  integral 키 규약 변경: 변수별(native) → 액추에이터별(개도 %). 과거 var-키/범위
  밖 값은 coordinate() 진입 시 자동 폐기(마이그레이션)된다.

Unit convention R1:
  All deviation, accumulated, residual, magnitude are in native units.
  Normalization is used only for priority sorting and proportional-band scaling.

Reference: docs/dev/integrated_env_control_design.md §4
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from .log_channels import (
    write_decision_log,
    ch_coord_cmd, ch_coord_reason, ch_integral,
    REASON_IDLE, REASON_PRIMARY, REASON_SECONDARY,
    REASON_WRONG_DIRECTION, REASON_SIDE_EFFECT, REASON_MANUAL_OVERRIDE,
    REASON_NO_GRADIENT,
)
from .authority import is_natural_var
from .types import ActuatorProfile, SituationReport

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Control-law tuning constants (profile.gains 로 액추에이터별 오버라이드 가능)
# ─────────────────────────────────────────────────────────────────────────────
PBAND_MULT = 6.0     # 비례 밴드 폭 = PBAND_MULT × tolerance (native). 편차가 이만큼이면 P=100%.
                     # 6 = 허용오차의 6배 편차에서 완전동작 → 작은 편차엔 부드럽게 반응
                     # (작게 할수록 민감/급격, 크게 할수록 완만). 평형개도는 적분이 찾음.
POS_KP     = 1.0     # 비례 이득 (e_norm → 명령 %)
POS_KI     = 0.2     # 적분 이득 (사이클당 e_norm 만큼 평형 개도 누적)
HOLD_FRAC  = 0.5     # |residual| < tolerance×HOLD_FRAC → 평형 유지(적분 동결)
RELAX_FACTOR = 0.6   # 폐쇄해야 할 때(충돌·gradient 없음) 평형 개도 감쇠 비율
AW_BETA    = 0.5     # back-calculation anti-windup 강도
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


# ─────────────────────────────────────────────────────────────────────────────
# Command result
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class ActuatorCommand:
    value: float                       # dispatch value (motor position %, after operating-range mapping)
    reason: int
    var_source: Optional[str] = None   # the variable that triggered this command
    aperture: Optional[float] = None   # control coordinate (aperture %, for slew/prev computation)

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

    # ── 3. Per-actuator position-form PI (다목적 결합 drive) ───────────────────
    # accumulated: 이미 확정된 명령들이 만든 효과(native). 부하분담에 사용.
    accumulated: Dict[str, float] = {var: 0.0 for var in situation.deviation_native}

    # 저렴한 액추에이터부터 확정 → 이후 것들은 잔여 편차를 보고 적게 동작(부하분담).
    order = sorted(available, key=lambda p: p.cost_fn(ctx, 100.0))

    for p in order:
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
            residual_v  = situation.deviation_native[v] - accumulated.get(v, 0.0)
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

        if den <= 1e-12 or max_g < G_MIN_EFFECT:
            # 제어 가능 변수 없음 OR 유효 구동력 없음(무구배 환기 등) → 안전 idle
            # 위치(safe_default)로 부드럽게 수렴하고 적분을 풀어준다. 100% 가동해도
            # 효과 없는 액추에이터를 편차 비례로 켜 두면 성과 없이 작동시간만 늘고
            # 적분이 와인드업한다. safe_default 기준으로 감쇠하므로 개구부(sd=0)는
            # 닫힘, 스크린(보온커튼·차광막 sd=100)은 걷힘으로 수렴한다.
            sd = p.safe_default
            I = sd + (I - sd) * RELAX_FACTOR
            cmd_raw = _clamp(I, 0.0, 100.0)
            reason = REASON_NO_GRADIENT
        else:
            e_norm = num / den
            if abs(e_norm) < HOLD_FRAC / PBAND_MULT:
                # 평형 근방(결합오차 작음) → 적분 동결, 직전 평형 개도 유지
                cmd_raw = _clamp(I, 0.0, 100.0)
                reason = REASON_PRIMARY
            else:
                I = _clamp(I + ki * e_norm, 0.0, 100.0)
                p_term = kp * e_norm * 100.0
                cmd_unclamped = p_term + I
                cmd_raw = _clamp(cmd_unclamped, 0.0, 100.0)
                # back-calculation anti-windup: 포화분만큼 적분을 되돌림
                if cmd_unclamped != cmd_raw:
                    I = _clamp(I - (cmd_unclamped - cmd_raw) * AW_BETA, 0.0, 100.0)
                reason = REASON_PRIMARY

        new_state.integral[p.actuator_id] = I

        cmd = finalize_command(p, cmd_raw, prev_val, cycle_sec,
                               reason=reason, var_source=primary_var)
        commands[p.actuator_id] = cmd

        # 확정 효과 누적 (모든 변수) — 부하분담용. slew 적용된 개도 사용.
        cmd_ap = cmd.aperture if cmd.aperture is not None else cmd.value
        for v, e in p.live_effect.items():
            s = 1.0 if e.direction == '↑' else (-1.0 if e.direction == '↓' else 0.0)
            accumulated[v] = accumulated.get(v, 0.0) + e.magnitude_native * (cmd_ap / 100.0) * s

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
    # 스크린(curtain/shade)은 디스패치에서 0/100 binary 로 스냅된다. slew 를 적용하면
    # 50% 경계를 못 넘어(예: 100→80→여전히 열림) 닫힘/열림 전환이 봉쇄되므로 우회한다.
    if getattr(p, 'kind', '') in ('curtain', 'shade'):
        cmd_slew = aperture_pct
    else:
        slew = p.cmd_constraints.effective_slew(cycle_sec)
        cmd_slew = _clamp(aperture_pct, prev_aperture - slew, prev_aperture + slew)
    if 0.0 < cmd_slew < p.cmd_constraints.min_on_pct:
        cmd_slew = 0.0
    cmd_motor = p.cmd_constraints.map_aperture_to_motor(cmd_slew)
    return ActuatorCommand(value=cmd_motor, reason=reason,
                           var_source=var_source, aperture=cmd_slew)


def _clamp(val: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, val))


def _same_sign(a: float, b: float) -> bool:
    return (a > 0 and b > 0) or (a < 0 and b < 0)


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
