# coding=utf-8
"""CO₂ 주입은 **팬이 공기를 바꾸는 동안**에도 쉰다 — 창 개도만 보던 보존율의 구멍.

`test_co2_vent_retention` 은 창만 다뤘다. 그런데 팬은 창이 닫힌 채로도 공기를 빼므로,
개도 0 · 팬 100 % 인 시설에서 주입기가 부족분을 좇아 계속 돌았다(주입 → 팬이 배출 → 부족 →
주입). 여기서 고정하는 것:

  · 팬의 환기량(정격 풍량 × 명령 / 체적 = ACH)이 창 개도와 **같은 잣대**로 보존율을 깎는다.
  · 창이 열려 팬이 힘을 못 쓰는 구간은 팬 몫을 이중으로 세지 않는다(압력 유효도).
  · 배기팬과 흡기팬은 한 흐름의 양끝이라 **큰 쪽**만 센다. 풍량을 모르는 팬은 0.
  · 계수 오버라이드 경로(`build_effect_model(kind, k)`)도 같은 보존율을 곱한다.
"""
from types import SimpleNamespace

import pytest

from aot.functions.utils.env_control import effect_functions as ef
from aot.functions.utils.env_control.coordinator import CoordinatorState, coordinate
from aot.functions.utils.env_control.log_channels import REASON_NO_GRADIENT
from aot.functions.utils.env_control.types import (
    ActuatorProfile, CmdConstraints, EffectResult, TargetVar)


def _fan(aid='fan', kind='exhaust_fan', rated=3000.0, volume=500.0):
    meta = {}
    if rated is not None:
        meta['rated_m3h'] = rated
    if volume is not None:
        meta['volume_m3'] = volume
    return SimpleNamespace(actuator_id=aid, kind=kind, capacity_meta=meta,
                           calibrated_K={})


# ─────────────────────────────────────────────────────────────────────────────
# 보존율 식
# ─────────────────────────────────────────────────────────────────────────────

class TestRetention:
    def test_no_fan_no_window_keeps_everything(self):
        assert ef.co2_retention({}) == 1.0

    def test_fan_alone_derates_even_with_closed_windows(self):
        """개도 0 이어도 팬이 6 회/시 바꾸면(= 창을 F0 만큼 연 것과 같다) 보존율 0."""
        ach0 = ef.CO2_FAN_ACH_PER_OPEN * ef.CO2_VENT_LOSS_F0
        assert ef.co2_retention({'vent_open_frac': 0.0, 'fan_ach': ach0}) == pytest.approx(0.0)
        assert ef.co2_retention({'fan_ach': ach0 / 2}) == pytest.approx(0.5)

    def test_window_and_fan_losses_add(self):
        window = ef.CO2_VENT_LOSS_F0 / 4                 # 보존율 −25 %
        fan = ef.CO2_FAN_ACH_PER_OPEN * ef.CO2_VENT_LOSS_F0 / 4   # 창으로 치면 −25 %
        r = ef.co2_retention({'vent_open_frac': window, 'fan_ach': fan})
        # 창이 조금 열렸으니 팬은 압력 유효도만큼만 힘을 쓴다.
        pf = 1.0 - window / ef.VENT_PRESSURE_F0
        assert r == pytest.approx(1.0 - 0.25 - 0.25 * pf)
        assert r < ef.co2_retention({'vent_open_frac': window})

    def test_fan_is_not_counted_when_windows_cancel_its_pressure(self):
        """창이 VENT_PRESSURE_F0 이상 열리면 벽면 팬은 무력 — 창 몫만 센다(이중 계상 금지)."""
        f = ef.VENT_PRESSURE_F0
        with_fan = ef.co2_retention({'vent_open_frac': f, 'fan_ach': 10.0})
        without = ef.co2_retention({'vent_open_frac': f})
        assert with_fan == pytest.approx(without)

    def test_retention_never_negative(self):
        assert ef.co2_retention({'vent_open_frac': 0.0, 'fan_ach': 1e6}) == 0.0

    def test_injector_effect_uses_the_fan_term(self):
        full = ef.co2_injector_co2_effect({}, 100.0).magnitude_native
        env = {'fan_ach': ef.CO2_FAN_ACH_PER_OPEN * ef.CO2_VENT_LOSS_F0 / 2}
        assert ef.co2_injector_co2_effect(env, 100.0).magnitude_native == \
            pytest.approx(full / 2)


# ─────────────────────────────────────────────────────────────────────────────
# 팬 환기량 집계
# ─────────────────────────────────────────────────────────────────────────────

class TestFanAch:
    def test_ach_is_flow_times_command_over_volume(self):
        f = _fan(rated=3000.0, volume=500.0)             # 100 % → 6 회/시
        assert ef.fan_ach_total([f], {'fan': 100.0}) == pytest.approx(6.0)
        assert ef.fan_ach_total([f], {'fan': 50.0}) == pytest.approx(3.0)
        assert ef.fan_ach_total([f], {'fan': 0.0}) == 0.0

    def test_missing_previous_command_counts_as_zero(self):
        assert ef.fan_ach_total([_fan()], {}) == 0.0

    def test_unknown_flow_or_volume_is_zero_not_a_guess(self):
        assert ef.fan_ach_total([_fan(rated=None)], {'fan': 100.0}) == 0.0
        assert ef.fan_ach_total([_fan(volume=None)], {'fan': 100.0}) == 0.0

    def test_exhaust_fans_add_among_themselves(self):
        fans = [_fan('a'), _fan('b')]
        assert ef.fan_ach_total(fans, {'a': 100.0, 'b': 100.0}) == pytest.approx(12.0)

    def test_exhaust_and_intake_are_the_two_ends_of_one_flow(self):
        """같은 공기를 두 번 세지 않는다 — 큰 쪽."""
        fans = [_fan('e', 'exhaust_fan', rated=3000.0),
                _fan('i', 'intake_fan', rated=1500.0)]
        assert ef.fan_ach_total(fans, {'e': 100.0, 'i': 100.0}) == pytest.approx(6.0)
        fans = [_fan('e', 'exhaust_fan', rated=1000.0),
                _fan('i', 'intake_fan', rated=3000.0)]
        assert ef.fan_ach_total(fans, {'e': 100.0, 'i': 100.0}) == pytest.approx(6.0)

    def test_circulation_fans_and_other_kinds_do_not_count(self):
        circ = _fan('c', 'circulation_fan')
        assert ef.fan_ach_total([circ], {'c': 100.0}) == 0.0

    def test_garbage_command_is_ignored(self):
        assert ef.fan_ach_total([_fan()], {'fan': 'x'}) == 0.0
        assert ef.fan_ach_total(None, None) == 0.0


# ─────────────────────────────────────────────────────────────────────────────
# 계수 오버라이드 경로
# ─────────────────────────────────────────────────────────────────────────────

class TestOverridePath:
    """`build_effect_model(kind, k)` — 계수를 손본 주입기도 같은 보존율을 곱한다."""

    def test_override_with_closed_house_keeps_the_override_gain(self):
        model = ef.build_effect_model('co2_injector', {'K_CO2_INJ': 50.0})
        assert model['co2']({}, 100.0).magnitude_native == pytest.approx(50.0)

    def test_override_loses_retention_to_open_windows(self):
        model = ef.build_effect_model('co2_injector', {'K_CO2_INJ': 50.0})
        env = {'vent_open_frac': ef.CO2_VENT_LOSS_F0 / 2}
        assert model['co2'](env, 100.0).magnitude_native == pytest.approx(25.0)
        assert model['co2']({'vent_open_frac': ef.CO2_VENT_LOSS_F0}, 100.0
                            ).magnitude_native == 0.0

    def test_override_loses_retention_to_fans(self):
        model = ef.build_effect_model('co2_injector', {'K_CO2_INJ': 50.0})
        env = {'fan_ach': ef.CO2_FAN_ACH_PER_OPEN * ef.CO2_VENT_LOSS_F0 / 2}
        assert model['co2'](env, 100.0).magnitude_native == pytest.approx(25.0)

    def test_override_and_default_agree_when_the_gain_is_the_same(self):
        env = {'vent_open_frac': 0.1, 'fan_ach': 2.0}
        default = ef.build_effect_model('co2_injector', {})['co2']
        override = ef.build_effect_model(
            'co2_injector', {'K_CO2_INJ': ef.K_CO2_INJ})['co2']
        assert override(env, 80.0).magnitude_native == pytest.approx(
            default(env, 80.0).magnitude_native)


# ─────────────────────────────────────────────────────────────────────────────
# coordinate() — 주입기가 실제로 쉬는가
# ─────────────────────────────────────────────────────────────────────────────

class _Situation:
    def __init__(self, dev):
        self.target = {'co2': TargetVar(value=800.0, tolerance=100.0,
                                        priority=0.8, unit='ppm')}
        self.deviation_native = {'co2': dev}
        self.context = {'cycle_sec': 60.0}


def _injector():
    return ActuatorProfile(
        actuator_id='inj', kind='co2_injector',
        effect_model=ef.build_effect_model('co2_injector', {}),
        cost_fn=lambda env, pct: 1.0,
        cmd_constraints=CmdConstraints(slew_per_cycle=100.0, min_on_pct=0.0),
        gains={'kp': 1.0, 'ki': 0.2}, safe_default=0.0)


def _exhaust_fan(rated=3000.0, volume=500.0):
    p = ActuatorProfile(
        actuator_id='fan', kind='exhaust_fan',
        effect_model={'temperature': lambda e, c, pp=None: EffectResult('0', 0.0)},
        cost_fn=lambda env, pct: 1.0,
        cmd_constraints=CmdConstraints(slew_per_cycle=100.0, min_on_pct=0.0),
        gains={'kp': 1.0, 'ki': 0.2}, safe_default=0.0)
    p.capacity_meta = {'rated_m3h': rated, 'volume_m3': volume}
    return p


def _run(fan_pct, **fan_kw):
    inj, fan = _injector(), _exhaust_fan(**fan_kw)
    st = CoordinatorState()
    st.prev_commands = {'inj': 0.0, 'fan': fan_pct}
    st.integral = {'inj': 0.0, 'fan': fan_pct}
    sit = _Situation(-400.0)
    cmds, _ = coordinate(sit, [inj, fan], st, unique_id='t')
    return cmds['inj'], sit.context


def test_injector_runs_while_the_fan_is_idle():
    c, ctx = _run(0.0)
    assert ctx['fan_ach'] == 0.0
    assert c.control_value() > 0.0


def test_injector_rests_while_the_fan_exchanges_air_with_closed_windows():
    """개도 0 · 팬 100 % (6 회/시) — 창 보존율만 보면 1.0 이라 예전엔 풀 출력이었다."""
    c, ctx = _run(100.0)
    assert ctx['vent_open_frac'] == 0.0
    assert ctx['fan_ach'] == pytest.approx(6.0)
    assert c.control_value() == 0.0
    assert c.reason == REASON_NO_GRADIENT


def test_a_weak_fan_only_trims_the_injector():
    strong, _ = _run(0.0)
    weak, _ = _run(100.0, rated=300.0)               # 0.6 회/시 → 보존율 0.9
    assert 0.0 < weak.control_value() <= strong.control_value()


def test_a_fan_without_a_rated_flow_does_not_stop_the_injector():
    """풍량을 모르면 지어내지 않는다 — 주입기를 멈출 근거가 없다."""
    c, ctx = _run(100.0, rated=None)
    assert ctx['fan_ach'] == 0.0
    assert c.control_value() > 0.0
