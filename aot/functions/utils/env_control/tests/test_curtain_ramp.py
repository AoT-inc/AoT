# coding=utf-8
"""아침 램프 — 밤새 친 보온커튼을 단계로 걷는다 (Phase 6-3, 2026-10-09).

한 번에 걷으면 커튼 위의 찬 공기가 내려앉아 실내가 몇 도 떨어진다. 10 → 30 → 60 → 100 %,
단계마다 600 s, 그동안 실내가 1 °C 넘게 떨어졌거나 목표 하한 아래면 그 단계에 머문다.
"""
import types

from aot.functions.utils.env_control import screen_policy as SP
from aot.functions.utils.env_control.coordinator import CoordinatorState, coordinate
from aot.functions.utils.env_control.log_channels import (
    REASON_CURTAIN_DAY_OPEN, REASON_CURTAIN_RAMP,
)
from aot.functions.utils.env_control.types import ActuatorProfile, CmdConstraints


def _cur(positional=True):
    return types.SimpleNamespace(actuator_id='c', kind='curtain',
                                 capacity_meta={'screen_positional': positional})


def _ramp(st, T=14.0, T_ext=0.0, now=0.0, day=True, prev=None, T_low=12.0, profiles=None):
    return SP._curtain_ramp(st, {'T': T}, {'T': T_ext}, profiles or [_cur()],
                            prev if prev is not None else {'c': 0.0}, day, T_low, now)


def test_steps_through_when_the_house_holds_its_heat():
    st = SP.ScreenState()
    got = [_ramp(st, now=t).get('c', 100.0) for t in (0.0, 600.0, 1200.0, 1800.0)]
    assert got == [10.0, 30.0, 60.0, 100.0]
    assert st.ramp_done


def test_stays_on_a_step_when_the_house_cools_too_fast():
    st = SP.ScreenState()
    _ramp(st, T=14.0, now=0.0)
    assert _ramp(st, T=12.8, now=600.0) == {'c': 10.0}      # 1.2 °C 떨어짐 → 머문다
    assert _ramp(st, T=12.7, now=1200.0) == {'c': 30.0}     # 그다음 단계 동안은 0.1 °C


def test_stays_below_the_target_floor():
    st = SP.ScreenState()
    _ramp(st, T=12.5, now=0.0)
    assert _ramp(st, T=11.9, now=600.0, T_low=12.0) == {'c': 10.0}


def test_skips_when_inside_and_outside_are_close():
    st = SP.ScreenState()
    assert _ramp(st, T=14.0, T_ext=10.0) == {}
    assert st.ramp_done


def test_nothing_to_ramp_when_already_open_or_binary():
    assert _ramp(SP.ScreenState(), prev={'c': 100.0}) == {}
    assert _ramp(SP.ScreenState(), profiles=[_cur(False)]) == {}


def test_night_resets():
    st = SP.ScreenState()
    _ramp(st, now=0.0)
    assert _ramp(st, day=False, now=600.0) == {}
    assert st.ramp_idx is None and not st.ramp_done


def test_day_command():
    dec = SP.ScreenDecision(curtain_day_target={'c': 30.0})
    assert SP.curtain_day_command(dec, 'c') == (30.0, REASON_CURTAIN_RAMP)
    assert SP.curtain_day_command(dec, 'x') == (100.0, REASON_CURTAIN_DAY_OPEN)
    assert SP.curtain_day_command(None, 'c') == (100.0, REASON_CURTAIN_DAY_OPEN)


class _Sit:
    def __init__(self, ctx):
        self.target, self.deviation_native, self.context = {}, {}, ctx


def test_coordinate_uses_the_step_and_aligns_the_integral():
    p = ActuatorProfile(actuator_id='c', kind='curtain', safe_default=100.0,
                        cmd_constraints=CmdConstraints(slew_per_cycle=100.0, min_on_pct=0.0))
    ctx = {'cycle_sec': 600.0, 'curtain_day_open': True,
           'screen': SP.ScreenDecision(curtain_day_target={'c': 30.0})}
    cmds, st = coordinate(_Sit(ctx), [p], CoordinatorState(prev_commands={'c': 10.0}),
                          unique_id='t')
    assert cmds['c'].value == 30.0 and cmds['c'].reason == REASON_CURTAIN_RAMP
    assert st.integral['c'] == 30.0
    ctx['screen'] = SP.ScreenDecision()
    cmds, _ = coordinate(_Sit(ctx), [p], CoordinatorState(prev_commands={'c': 60.0}),
                         unique_id='t')
    assert cmds['c'].value == 100.0 and cmds['c'].reason == REASON_CURTAIN_DAY_OPEN


def test_the_floor_does_not_hold_the_curtain_all_day():
    """난방이 범위까지 못 데우는 날 — 2시간 뒤에는 하락 조건만 본다(폐루프 cold_night)."""
    st = SP.ScreenState()
    _ramp(st, T=8.0, T_ext=-4.0, now=0.0, T_low=22.0)
    t, T = 0.0, 8.0
    while t < SP.RAMP_FLOOR_MAX_S - 600.0:
        t += 600.0
        T += 0.5
        assert _ramp(st, T=T, T_ext=-4.0, now=t, T_low=22.0) == {'c': 10.0}
    got = []
    for _ in range(4):
        t += 600.0
        T += 0.5
        got.append(_ramp(st, T=T, T_ext=-4.0, now=t, T_low=22.0).get('c', 100.0))
    assert got[-1] == 100.0
