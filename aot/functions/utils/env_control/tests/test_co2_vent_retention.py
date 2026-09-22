# coding=utf-8
"""CO₂ 주입과 환기가 따로 놀지 않는다 — 창이 열리면 주입 효과에서 빠지는 몫을 뺀다.

예전에는 주입 효과가 상수라, 더워서 창을 연 동안에도 주입기가 부족분을 좇아
계속 돌았다: 부족 → 주입 → 환기로 배출 → 또 부족. 보존율이 떨어지면 효과가
작아지고 기존 유효도 게이트가 주입기를 쉬게 한다.
"""
import pytest

from aot.functions.utils.env_control.coordinator import CoordinatorState, coordinate
from aot.functions.utils.env_control.effect_functions import (
    CO2_VENT_LOSS_F0, CO2_INJECTOR_EFFECT_MODEL, co2_injector_co2_effect)
from aot.functions.utils.env_control.log_channels import REASON_NO_GRADIENT
from aot.functions.utils.env_control.types import (
    ActuatorProfile, CmdConstraints, EffectResult, TargetVar)


def test_closed_house_keeps_full_effect():
    full = co2_injector_co2_effect({}, 100.0)
    assert co2_injector_co2_effect({'vent_open_frac': 0.0}, 100.0).magnitude_native == \
        pytest.approx(full.magnitude_native)


def test_open_vents_derate_linearly_then_to_zero():
    full = co2_injector_co2_effect({}, 100.0).magnitude_native
    half = co2_injector_co2_effect({'vent_open_frac': CO2_VENT_LOSS_F0 / 2}, 100.0)
    assert half.magnitude_native == pytest.approx(full / 2)
    assert co2_injector_co2_effect(
        {'vent_open_frac': CO2_VENT_LOSS_F0}, 100.0).magnitude_native == 0.0


class _Situation:
    def __init__(self, dev):
        self.target = {'co2': TargetVar(value=800.0, tolerance=100.0,
                                        priority=0.8, unit='ppm')}
        self.deviation_native = {'co2': dev}
        self.context = {'cycle_sec': 600.0}


def _profiles():
    inj = ActuatorProfile(
        actuator_id='inj', kind='co2_injector',
        effect_model=dict(CO2_INJECTOR_EFFECT_MODEL),
        cost_fn=lambda env, pct: 1.0,
        cmd_constraints=CmdConstraints(slew_per_cycle=100.0, min_on_pct=0.0),
        gains={'kp': 1.0, 'ki': 0.2}, safe_default=0.0)
    vent = ActuatorProfile(
        actuator_id='vent', kind='opening',
        effect_model={'temperature': lambda e, c, p=None: EffectResult('0', 0.0)},
        cost_fn=lambda env, pct: 1.0,
        cmd_constraints=CmdConstraints(slew_per_cycle=100.0, min_on_pct=0.0),
        gains={'kp': 1.0, 'ki': 0.2}, safe_default=0.0)
    return inj, vent


def _run(vent_pct):
    inj, vent = _profiles()
    st = CoordinatorState()
    st.prev_commands = {'inj': 0.0, 'vent': vent_pct}
    st.integral = {'inj': 0.0, 'vent': vent_pct}
    cmds, _ = coordinate(_Situation(-400.0), [inj, vent], st, unique_id='t')
    return cmds['inj']


def test_injector_runs_in_a_closed_house():
    c = _run(0.0)
    assert c.control_value() > 0.0


def test_injector_rests_while_vents_are_wide_open():
    """CO₂ 가 400 ppm 모자라도 창이 반쯤 열려 있으면 주입하지 않는다."""
    c = _run(50.0)
    assert c.control_value() == 0.0
    assert c.reason == REASON_NO_GRADIENT
