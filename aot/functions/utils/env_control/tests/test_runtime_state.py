# coding=utf-8
"""
P2-5: FunctionRuntimeState persistence 단위 테스트.

env_coordinator 의 _load_runtime_state / _save_runtime_state 를 직접
테스트하는 대신, 동등한 직렬화/역직렬화 로직을 검증한다
(Flask/DB 없이 실행 가능).

검증 항목:
  - CoordinatorState → JSON 직렬화 → 역직렬화 왕복 무결성
  - active_vars bool 강제 변환
  - 빈 상태 초기값
  - watchdog 임계값 계산
"""

import json

import pytest

from aot.functions.utils.env_control.coordinator import CoordinatorState


# ─────────────────────────────────────────────────────────────────────────────
# 직렬화/역직렬화 왕복
# ─────────────────────────────────────────────────────────────────────────────

class TestStateSerialisation:
    def test_integral_roundtrip(self):
        """integral dict → JSON → dict 왕복 무결성."""
        state = CoordinatorState(
            integral={'temperature': 3.14, 'humidity': -1.5, 'co2': 0.0},
        )
        blob = json.dumps(state.integral)
        restored = json.loads(blob)
        assert restored == state.integral

    def test_prev_commands_roundtrip(self):
        """prev_commands → JSON → dict 왕복 무결성."""
        state = CoordinatorState(
            prev_commands={'vent_01': 45.0, 'heater_01': 0.0},
        )
        blob = json.dumps(state.prev_commands)
        restored = json.loads(blob)
        assert restored == {'vent_01': 45.0, 'heater_01': 0.0}

    def test_active_vars_bool_cast(self):
        """active_vars 는 저장 시 bool 강제 변환."""
        state = CoordinatorState(
            active_vars={'temperature': True, 'humidity': False},
        )
        serialised = {k: bool(v) for k, v in state.active_vars.items()}
        blob = json.dumps(serialised)
        restored = json.loads(blob)
        assert restored['temperature'] is True
        assert restored['humidity'] is False

    def test_empty_state_serialises_to_empty_dicts(self):
        """초기 빈 상태 → JSON '{}' 직렬화."""
        state = CoordinatorState()
        assert json.dumps(state.integral) == '{}'
        assert json.dumps(state.prev_commands) == '{}'
        assert json.dumps(state.active_vars) == '{}'

    def test_float_precision_preserved(self):
        """float 정밀도 손실 없이 왕복."""
        val = 3.141592653589793
        blob = json.dumps({'temperature': val})
        restored = json.loads(blob)
        assert abs(restored['temperature'] - val) < 1e-12

    def test_negative_integral_preserved(self):
        """음수 적분값도 올바르게 복원."""
        state = CoordinatorState(integral={'humidity': -22.5})
        blob = json.dumps(state.integral)
        assert json.loads(blob)['humidity'] == pytest.approx(-22.5)


# ─────────────────────────────────────────────────────────────────────────────
# Watchdog 임계값 계산
# ─────────────────────────────────────────────────────────────────────────────

class TestWatchdogThreshold:
    """watchdog: now - last_cycle_ts > 3 × period → 경고 발동."""

    @pytest.mark.parametrize("period,gap,should_warn", [
        (60.0,  200.0, True),   # 200s > 3×60=180s → 경고
        (60.0,  179.9, False),  # 179.9s < 180s → 정상
        (30.0,  91.0,  True),   # 91s > 3×30=90s → 경고
        (30.0,  89.9,  False),  # 89.9s < 90s → 정상
        (120.0, 360.1, True),   # 360.1s > 3×120=360s → 경고
    ])
    def test_watchdog_trigger(self, period, gap, should_warn):
        last_ts = 1000.0
        now = last_ts + gap
        triggered = last_ts > 0 and (now - last_ts) > period * 3
        assert triggered == should_warn

    def test_first_cycle_no_warn(self):
        """첫 사이클(last_ts=0)은 watchdog 미발동."""
        last_ts = 0.0
        now = 99999.0
        period = 60.0
        triggered = last_ts > 0 and (now - last_ts) > period * 3
        assert not triggered


# ─────────────────────────────────────────────────────────────────────────────
# 상태 복원 후 coordinator 동작
# ─────────────────────────────────────────────────────────────────────────────

class TestStateRestoredBehaviour:
    """복원된 상태가 다음 사이클에 올바르게 적용된다."""

    def test_restored_prev_commands_used_in_slew(self):
        """prev_commands 를 복원하면 slew rate 가 이전값 기준으로 계산됨."""
        from aot.functions.utils.env_control.coordinator import CoordinatorState, coordinate, _clamp
        from aot.functions.utils.env_control.situation import assess
        from aot.functions.utils.env_control.types import CmdConstraints

        from .conftest import make_ctx, make_target, make_opening_profile

        # 이전 사이클에서 vent_01=50% 로 저장됐다고 가정
        restored_state = CoordinatorState(
            prev_commands={'vent_01': 50.0},
        )

        ctx = make_ctx(T_int=35.0, RH_int=50.0)
        target = make_target(vpd=1.8, T=22.0, RH=65.0)
        p = make_opening_profile('vent_01')
        p.cmd_constraints = CmdConstraints(slew_per_cycle=10.0)

        report, _ = assess(target, ctx['internal'], ctx['external'],
                           cycle_sec=60.0, now_ts=ctx['now_ts'])
        cmds, _ = coordinate(report, [p], restored_state)

        # slew: prev=50, slew=10 → 명령은 [40, 60] 범위
        assert cmds['vent_01'].value <= 50.0 + 10.0 + 1e-6
        assert cmds['vent_01'].value >= 50.0 - 10.0 - 1e-6

    def test_restored_integral_continues_accumulation(self):
        """복원된 integral(=액추에이터별 평형 개도 %)이 다음 사이클에서 이어진다.

        P6 재설계: integral 키는 actuator_id, 값은 평형 개도(%). 복원된 평형을
        0 에서 재시작하지 않고, 편차가 있으면 그 값을 기준으로 누적/유지한다.
        """
        from aot.functions.utils.env_control.coordinator import CoordinatorState, coordinate
        from aot.functions.utils.env_control.situation import assess
        from .conftest import make_ctx, make_target, make_opening_profile

        # 평형 개도 10% 복원 (액추에이터별 키)
        restored_state = CoordinatorState(
            integral={'vent_01': 10.0},
            active_vars={'temperature': True},
        )

        # 밴드 내 작은 편차(+0.6°C) + 냉방 구동력(외기 22<내부 24.6) → 포화 없이
        # 적분이 복원값 기준으로 누적되어야 한다. (큰 편차는 anti-windup 으로 적분
        # 이 0 으로 가는 게 정상이므로 '지속' 검증엔 부적절)
        ctx = make_ctx(T_int=24.6, T_ext=22.0)
        target = make_target(vpd=1.5, T=24.0)   # VPD_int=0(미측정) → T 폴백 제어
        p = make_opening_profile('vent_01')

        report, _ = assess(target, ctx['internal'], ctx['external'],
                           cycle_sec=60.0, now_ts=ctx['now_ts'])
        _, new_state = coordinate(report, [p], restored_state)

        # 평형 개도가 복원값(10%)을 기준으로 증가했어야 함 (0 재시작 아님)
        vent_integral = new_state.integral.get('vent_01', 0.0)
        assert vent_integral > 10.0

    def test_legacy_var_keyed_integral_discarded(self):
        """P6 이전의 변수별 native 적분(예: humidity=-394)은 진입 시 자동 폐기된다."""
        from aot.functions.utils.env_control.coordinator import CoordinatorState, coordinate
        from aot.functions.utils.env_control.situation import assess
        from .conftest import make_ctx, make_target, make_opening_profile

        # 구 스키마: 변수명 키 + 범위 밖(폭주) 값
        restored_state = CoordinatorState(
            integral={'humidity': -394.0, 'temperature': 0.0},
        )

        ctx = make_ctx(T_int=22.0, RH_int=65.0)
        target = make_target(vpd=1.2, T=22.0, RH=65.0)
        p = make_opening_profile('vent_01')

        report, _ = assess(target, ctx['internal'], ctx['external'],
                           cycle_sec=60.0, now_ts=ctx['now_ts'])
        _, new_state = coordinate(report, [p], restored_state)

        # 변수별 키는 사라지고, 액추에이터별 키만 [0,100] 범위로 남는다
        assert 'humidity' not in new_state.integral
        assert 'temperature' not in new_state.integral
        for aid, val in new_state.integral.items():
            assert 0.0 <= val <= 100.0
