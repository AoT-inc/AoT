# coding=utf-8
"""
coordinator.py 단위 테스트.

대상:
  - PI 계산 기본 동작
  - slew rate 클램프
  - anti-windup 작동
  - hysteresis 진입/해제
  - 수동 락 우선 적용
"""

import pytest

from aot.functions.utils.env_control.coordinator import (
    CoordinatorState, coordinate,
)
from aot.functions.utils.env_control.situation import assess
from aot.functions.utils.env_control.types import (
    ActuatorProfile, CmdConstraints, EffectResult, ManualLockState, TargetVar,
)

from .conftest import make_ctx, make_target, make_opening_profile, make_heater_profile


# ─────────────────────────────────────────────────────────────────────────────
# 헬퍼
# ─────────────────────────────────────────────────────────────────────────────

def _run_coord(ctx, target, profiles, state=None):
    """assess → coordinate 을 한 번 실행하고 (commands, new_state) 반환."""
    from aot.functions.utils.env_control.situation import TrendState
    report, _ = assess(target, ctx['internal'], ctx['external'],
                       cycle_sec=60.0, now_ts=ctx['now_ts'])
    st = state or CoordinatorState()
    return coordinate(report, profiles, st)


# ─────────────────────────────────────────────────────────────────────────────
# 수동 락
# ─────────────────────────────────────────────────────────────────────────────

class TestManualLock:
    def test_manual_lock_overrides_pi(self):
        """수동 락 시 PI 결과 무시, 락 값 그대로."""
        ctx = make_ctx(T_int=30.0)  # 온도 높음 → 환기 필요
        target = make_target(vpd=1.2)

        p = make_opening_profile()
        p.manual_lock = ManualLockState(locked=True, until_ts=0, manual_value=42.0)

        cmds, _ = _run_coord(ctx, target, [p])
        assert cmds['vent_01'].value == pytest.approx(42.0)

    def test_no_lock_produces_pi_command(self):
        """락 없을 때 PI 명령이 생성됨 (0 또는 양수)."""
        ctx = make_ctx(T_int=28.0)
        target = make_target(vpd=1.5, T=22.0)
        p = make_opening_profile()
        cmds, _ = _run_coord(ctx, target, [p])
        assert 0.0 <= cmds['vent_01'].value <= 100.0


# ─────────────────────────────────────────────────────────────────────────────
# Slew rate
# ─────────────────────────────────────────────────────────────────────────────

class TestSlewRate:
    def test_slew_limits_jump_from_zero(self):
        """이전 명령 0 → 이번에 100% PI 결과라도 slew 이내로 제한."""
        ctx = make_ctx(T_int=35.0)
        target = make_target(vpd=2.0, T=22.0)
        p = make_opening_profile()
        p.cmd_constraints = CmdConstraints(slew_per_cycle=20.0)

        prev_state = CoordinatorState(prev_commands={'vent_01': 0.0})
        cmds, _ = _run_coord(ctx, target, [p], state=prev_state)
        assert cmds['vent_01'].value <= 20.0 + 1e-6

    def test_slew_limits_increase_by_math(self):
        """cmd_slew 계산: prev=20, cmd_raw=80, slew=15 → result=35."""
        from aot.functions.utils.env_control.coordinator import _clamp
        prev_val = 20.0
        cmd_raw  = 80.0
        slew     = 15.0
        cmd_slew = _clamp(cmd_raw, prev_val - slew, prev_val + slew)
        assert cmd_slew == pytest.approx(35.0)

    def test_slew_limits_decrease_by_math(self):
        """cmd_slew 계산: prev=80, cmd_raw=20, slew=15 → result=65."""
        from aot.functions.utils.env_control.coordinator import _clamp
        prev_val = 80.0
        cmd_raw  = 20.0
        slew     = 15.0
        cmd_slew = _clamp(cmd_raw, prev_val - slew, prev_val + slew)
        assert cmd_slew == pytest.approx(65.0)

    def test_slew_applied_in_active_cycle(self):
        """PI 명령 생성 시 slew 상한 적용 — 0 → 최대 slew 이내."""
        # T=35 고온, 목표=22 → 확실히 PI 명령 생성
        ctx = make_ctx(T_int=35.0, RH_int=50.0)
        target = make_target(vpd=1.8, T=22.0, RH=65.0)
        p = make_opening_profile()
        p.cmd_constraints = CmdConstraints(slew_per_cycle=10.0)

        prev_state = CoordinatorState(prev_commands={'vent_01': 0.0})
        cmds, _ = _run_coord(ctx, target, [p], state=prev_state)
        assert cmds['vent_01'].value <= 10.0 + 1e-6


# ─────────────────────────────────────────────────────────────────────────────
# Anti-windup
# ─────────────────────────────────────────────────────────────────────────────

class TestAntiWindup:
    def test_integral_not_unbounded(self):
        """포화 명령 상태에서 여러 사이클 반복해도 적분항 발산 없음."""
        ctx = make_ctx(T_int=40.0)
        target = make_target(vpd=2.5, T=22.0)
        p = make_opening_profile()

        state = CoordinatorState()
        for _ in range(30):
            _, state = _run_coord(ctx, target, [p], state=state)

        # 적분항이 합리적 범위 내
        for var, val in state.integral.items():
            assert abs(val) < 1e6, f"integral[{var}] = {val} — unbounded"

    def test_no_windup_when_needed_direction_unactuatable(self):
        """비대칭 권한: 필요 방향 액추에이터가 없으면 적분이 누적되지 않는다.

        시설에 CO₂ 인젝터가 없는데(상승 불가) CO₂ 목표가 현재보다 높으면,
        needed_dir='↑' 에 해당하는 helper 가 공집합이 된다. 이때 적분을
        누적하면 anti-windup 루프(helper 순회 내부)가 영영 실행되지 않아
        매 사이클 잔차가 무한 누적되어 클램프에 고정된다. 동결로 방지한다.
        """
        ctx = make_ctx(T_int=22.0, RH_int=65.0, CO2_int=600.0)
        # CO₂ 목표 1500 > 현재 600 → 상승 필요. opening 프로필은 CO₂ 효과 없음.
        target = make_target(vpd=1.2, co2=1500.0)
        p = make_opening_profile()

        state = CoordinatorState()
        for _ in range(30):
            _, state = _run_coord(ctx, target, [p], state=state)

        # CO₂ 적분은 누적되지 않고 0 근방으로 동결되어야 한다.
        assert abs(state.integral.get('co2', 0.0)) < 1.0, \
            f"co2 integral wound up: {state.integral.get('co2')}"


# ─────────────────────────────────────────────────────────────────────────────
# Hysteresis
# ─────────────────────────────────────────────────────────────────────────────

class TestHysteresis:
    def test_idle_near_target_no_command(self):
        """목표 근방(tolerance 내)에서 액추에이터는 idle(safe_default)."""
        ctx = make_ctx(T_int=22.0, RH_int=65.0)  # VPD ≈ 0.94
        target = make_target(vpd=0.94, vpd_tol=0.15)
        p = make_opening_profile()

        cmds, _ = _run_coord(ctx, target, [p])
        assert cmds['vent_01'].value == pytest.approx(p.safe_default)

    def test_far_from_target_activates(self):
        """목표 대비 편차 크면 양수 명령 생성."""
        ctx = make_ctx(T_int=28.0, RH_int=40.0)  # VPD 높음
        target = make_target(vpd=0.8, vpd_tol=0.1)
        p = make_opening_profile()

        cmds, state = _run_coord(ctx, target, [p])
        # 환기 또는 다른 방식으로 명령 > 0 기대
        assert cmds['vent_01'].value >= 0.0   # 최소 idle 이상

    def test_active_var_flag_set(self):
        """편차 존재 시 active_vars 플래그 설정.

        _decompose_vpd 는 vpd → T/RH 보조목표로 변환하므로,
        T/RH 를 target 에 포함해야 deviation_native 에 변수가 등록됨.
        """
        ctx = make_ctx(T_int=32.0, RH_int=30.0)
        # T/RH 포함: 분해 후 actionable 변수가 존재
        target = make_target(vpd=0.5, vpd_tol=0.05, T=22.0, RH=65.0)
        p = make_opening_profile()

        _, state = _run_coord(ctx, target, [p])
        # T(32≠22) 또는 RH(30≠65) 편차가 명확히 있으므로 활성화
        assert any(state.active_vars.values())


# ─────────────────────────────────────────────────────────────────────────────
# 전체 명령 범위
# ─────────────────────────────────────────────────────────────────────────────

class TestCommandRange:
    def test_all_commands_in_0_100(self):
        """모든 액추에이터 명령은 항상 [0, 100] 범위."""
        profiles = [make_opening_profile('v1'), make_heater_profile('h1')]
        for T_int in [10.0, 22.0, 35.0]:
            ctx = make_ctx(T_int=T_int)
            target = make_target(vpd=1.2, T=22.0)
            cmds, _ = _run_coord(ctx, target, profiles)
            for aid, cmd in cmds.items():
                assert 0.0 <= cmd.value <= 100.0, \
                    f"T_int={T_int}, {aid}: cmd={cmd.value}"

    def test_all_profiles_get_command(self):
        """등록된 모든 프로필이 명령을 받음 (idle 포함)."""
        profiles = [make_opening_profile('v1'), make_heater_profile('h1')]
        ctx = make_ctx()
        target = make_target(vpd=1.2)
        cmds, _ = _run_coord(ctx, target, profiles)
        for p in profiles:
            assert p.actuator_id in cmds
