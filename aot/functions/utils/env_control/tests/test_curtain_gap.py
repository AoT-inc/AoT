# coding=utf-8
"""밤 결로 — 보온커튼 틈이 먼저, 창은 그다음 (Phase 6-2, 2026-10-09).

닫힌 보온커튼 아래 밤공기가 이슬점에 가까워지면 창을 열기 전에 커튼을 조금(3 → 6 → 10 %)
연다. 열 손실이 크면 덜 열거나 안 연다. 틈을 다 쓰고도 남으면 그때 창(야간 결로 탈출).
"""
import types

import pytest

from aot.functions.utils.env_control import humid_regime as HR
from aot.functions.utils.env_control import screen_policy as SP
from aot.functions.utils.env_control.log_channels import (
    REASON_CURTAIN_GAP, REASON_NO_GRADIENT,
)


def _cur(positional=True):
    return types.SimpleNamespace(actuator_id='c', kind='curtain',
                                 capacity_meta={'screen_positional': positional})


def _heater():
    return types.SimpleNamespace(actuator_id='h', kind='heater', capacity_meta={})


def _cfg(**kw):
    return SP.ScreenConfig(**{'cycle_sec': 600.0, **kw})


# 15 °C · RH 92 % → 이슬점 여유 ≈ 1.3 °C(진입선 2.0 아래)
WET = {'T': 15.0, 'RH': 92.0}
DRY = {'T': 15.0, 'RH': 70.0}        # 여유 ≈ 5.3 °C(해제선 3.0 위)


def _gap(state, internal=WET, profiles=None, prev=None, ext=None, now=0.0, day=False,
         T_low=None, **cfg):
    return SP._curtain_gap(_cfg(**cfg), state, internal, ext or {'T': 10.0},
                           profiles or [_cur()], prev or {'c': 0.0}, day, T_low, now)


def test_enters_with_the_first_step():
    st = SP.ScreenState()
    gap, escape, stage = _gap(st)
    assert gap == {'c': 3.0} and not escape and stage == 1


def test_binary_curtain_gets_no_gap_and_vents_keep_their_escape():
    gap, escape, stage = _gap(SP.ScreenState(), profiles=[_cur(False)])
    assert gap == {} and escape and stage == 0


def test_option_off():
    gap, escape, _ = _gap(SP.ScreenState(), curtain_humidity_gap=False)
    assert gap == {} and escape


def test_steps_up_only_without_recovery():
    st = SP.ScreenState()
    _gap(st, now=0.0)
    assert _gap(st, now=600.0)[0] == {'c': 3.0}               # 아직 900 s 전
    assert _gap(st, now=900.0)[0] == {'c': 6.0}               # 회복 없음 → 다음
    better = {'T': 15.0, 'RH': 89.5}                         # 여유 +0.4 °C
    assert _gap(st, internal=better, now=1800.0)[0] == {'c': 6.0}   # 회복 중 → 그대로


def test_leaves_when_dry_again():
    st = SP.ScreenState()
    _gap(st)
    assert _gap(st, internal=DRY, now=600.0)[0] == {}
    assert not st.gap_on


def test_day_resets():
    st = SP.ScreenState()
    _gap(st)
    assert _gap(st, day=True, now=600.0)[0] == {} and not st.gap_on


def test_does_not_enter_when_curtain_is_open():
    gap, escape, _ = _gap(SP.ScreenState(), prev={'c': 100.0})
    assert gap == {} and escape


def test_no_gap_when_heating_is_forced_or_too_cold_without_heater():
    gap, escape, stage = _gap(SP.ScreenState(), internal={**WET, '_force_heat': True})
    assert gap == {} and escape and stage == 2
    gap, _, _ = _gap(SP.ScreenState(), T_low=16.0)
    assert gap == {}
    # 난방기가 있으면 목표 하한 아래여도 막지 않는다(난방이 메운다)
    gap, _, _ = _gap(SP.ScreenState(), T_low=16.0, profiles=[_cur(), _heater()],
                     prev={'c': 0.0, 'h': 20.0})
    assert gap == {'c': 3.0}


@pytest.mark.parametrize('ext,prev', [
    ({'T': 15.0 - HR.MAX_COLD_DELTA_C - 1.0}, {'c': 0.0, 'h': 0.0}),   # 바깥이 너무 차다
    ({'T': 10.0}, {'c': 0.0, 'h': 90.0}),                              # 난방기가 바쁘다
])
def test_heat_loss_caps_at_the_first_step(ext, prev):
    st = SP.ScreenState()
    for t in (0.0, 900.0, 1800.0):
        gap, _, _ = _gap(st, ext=ext, prev=prev, profiles=[_cur(), _heater()], now=t)
    assert gap == {'c': 3.0}


def test_vents_only_after_the_gap_is_spent():
    st = SP.ScreenState()
    stages = []
    for t in (0.0, 900.0, 1800.0, 2700.0):
        gap, escape, stage = _gap(st, now=t)
        stages.append((gap.get('c'), escape, stage))
    assert stages == [(3.0, False, 1), (6.0, False, 1), (10.0, False, 1), (10.0, True, 2)]


def test_pi_reads_the_gap():
    dec = SP.ScreenDecision(curtain_gap={'c': 6.0})
    assert SP.adjust_pi_command(dec, _cur(), 0.0, 0.0, REASON_NO_GRADIENT, None) == (
        6.0, 6.0, REASON_CURTAIN_GAP)
    # PI 가 걷자고 하면 그쪽이 이긴다
    assert SP.adjust_pi_command(dec, _cur(), 100.0, 100.0, 1, 'vpd') == (100.0, 100.0, 1)


def test_night_parking_asks_the_screen_policy_first():
    import inspect
    from aot.functions.custom_functions.env_coordinator_impl import _helpers_mixin as hm
    src = inspect.getsource(hm.HelpersMixin._night_vent_decide)
    assert "_screen_vent_escape_allowed" in src


def test_cold_gate_and_forced_heat_win_after_the_gap():
    """한파 게이트·temp_min 은 오버라이드 단계에서 커튼을 0 으로 — 근거가 46 이 아니라 0/100 이 된다."""
    from aot.functions.utils.env_control.dispatch_adapters import snap_screen_commands
    cmds = {'c': {'value': 0.0, 'reason': 'temp_min'}}
    snap_screen_commands(cmds, [_cur()], {'c': 6.0})
    assert cmds['c']['value'] == 0.0


def test_a_pi_request_that_would_still_close_keeps_the_gap():
    """50~60 의 PI 명령은 0/100 결정에서 닫힌다 — 그 사이에도 틈을 지킨다(폐루프 humid_gap_night)."""
    dec = SP.ScreenDecision(curtain_gap={'c': 10.0})
    assert SP.adjust_pi_command(dec, _cur(), 55.0, 55.0, 1, 'vpd') == (
        10.0, 10.0, REASON_CURTAIN_GAP)


def test_the_first_step_survives_min_on():
    """3 % 틈이 min-ON(기본 5 %)에 0 으로 잘리지 않는다."""
    from aot.functions.utils.env_control.coordinator import finalize_command
    from aot.functions.utils.env_control.types import ActuatorProfile, CmdConstraints
    p = ActuatorProfile(actuator_id='c', kind='curtain',
                        cmd_constraints=CmdConstraints(min_on_pct=5.0))
    assert finalize_command(p, 3.0, 0.0, 600.0, REASON_CURTAIN_GAP).value == 3.0
    v = ActuatorProfile(actuator_id='w', kind='opening',
                        cmd_constraints=CmdConstraints(min_on_pct=5.0, slew_per_cycle=100.0))
    assert finalize_command(v, 3.0, 0.0, 600.0, 1).value == 0.0
