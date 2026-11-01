# coding=utf-8
"""분무용 물 공급(`water_supply`) — 판정·파킹·최종 오버라이드·사이클 배선.

  · 판정: 묶지 않았으면 있다 / 유효하고 문턱 아래면 없다 / 없거나 만료면 없다 / 이력.
  · 코디네이터: 분무기 **전부**가 폭염과 무관하게 파킹(근거 41)되고, 폭염 분무 차단(29)과
    겹치면 41 이 이긴다. 환기 장치는 건드리지 않는다.
  · 최종 오버라이드: 어느 엔진이든 분무기는 0(문자열 근거 'no_water' → 41).
  · 사이클: 옵션을 읽어 internal 에 싣고, **바뀔 때만** 말하고, CH92 를 남긴다.
"""
import logging

import pytest

import aot.functions.custom_functions.env_coordinator_impl._cycle_mixin as cycle_mod
from aot.functions.custom_functions.env_coordinator_impl._cycle_mixin import (
    CycleMixin, apply_no_water_override)
from aot.functions.custom_functions.env_coordinator_impl._helpers_mixin import HelpersMixin
from aot.functions.utils.env_control import water_supply as WS
from aot.functions.utils.env_control.coordinator import (
    CoordinatorState, coordinate, decide_parking)
from aot.functions.utils.env_control.heat_protect import HeatProtectDecision
from aot.functions.utils.env_control.log_channels import (
    CH_WATER_SUPPLY, REASON_HEAT_FOG_BLOCKED, REASON_NO_WATER, reason_code)
from aot.functions.utils.env_control.types import (
    ActuatorProfile, CmdConstraints, EffectResult, TargetVar)


# ─────────────────────────────────────────────────────────────────────────────
# 판정
# ─────────────────────────────────────────────────────────────────────────────

def _cfg(**kw):
    base = dict(bound=True, threshold=10.0, direction='above')
    base.update(kw)
    return WS.WaterSupplyConfig(**base)


class TestJudge:
    def test_unbound_means_water_is_there(self):
        """옵션을 켜지 않았으면 종전과 같다 — 값이 뭐든 있다."""
        assert WS.judge(WS.WaterSupplyConfig(bound=False), None) == (True, WS.WATER_UNBOUND)
        assert WS.judge(WS.WaterSupplyConfig(bound=False), 0.0) == (True, WS.WATER_UNBOUND)

    def test_valid_value_above_threshold(self):
        assert WS.judge(_cfg(), 40.0) == (True, WS.WATER_OK)
        assert WS.judge(_cfg(), 10.0) == (True, WS.WATER_OK)       # 문턱 '이상'

    def test_valid_value_below_threshold_is_low(self):
        assert WS.judge(_cfg(), 9.9) == (False, WS.WATER_LOW)

    def test_missing_or_stale_value_is_unavailable(self):
        """모르는 것은 '없다' — 물이 있는지 모르는 채 펌프를 돌리지 않는다."""
        assert WS.judge(_cfg(), None) == (False, WS.WATER_STALE)
        assert WS.judge(_cfg(), float('nan')) == (False, WS.WATER_STALE)
        assert WS.judge(_cfg(), 'x') == (False, WS.WATER_STALE)

    def test_below_direction_is_an_empty_alarm_switch(self):
        """바닥 경보 스위치: 1 이 '비었다'. 문턱 0.5, 방향 below."""
        cfg = _cfg(threshold=0.5, direction='below')
        assert WS.judge(cfg, 0.0) == (True, WS.WATER_OK)
        assert WS.judge(cfg, 1.0) == (False, WS.WATER_LOW)

    def test_unknown_direction_falls_back_to_above(self):
        assert WS.normalise_direction('sideways') == WS.DIR_ABOVE
        assert WS.normalise_direction(None) == WS.DIR_ABOVE
        assert WS.judge(_cfg(direction='sideways'), 40.0) == (True, WS.WATER_OK)

    def test_recovery_needs_the_hysteresis_margin(self):
        """한 번 '없다' 가 되면 문턱에서 5 % 더 와야 풀린다 — 펌프가 만드는 출렁임에 안 뒤집힌다."""
        cfg = _cfg(threshold=100.0)
        avail, st = WS.judge(cfg, 99.0, WS.WATER_OK)
        assert (avail, st) == (False, WS.WATER_LOW)
        assert WS.judge(cfg, 102.0, st) == (False, WS.WATER_LOW)       # 문턱은 넘었으나 여유 미달
        assert WS.judge(cfg, 105.0, st) == (True, WS.WATER_OK)

    def test_recovery_hysteresis_for_below_direction(self):
        cfg = _cfg(threshold=100.0, direction='below')
        _a, st = WS.judge(cfg, 101.0, WS.WATER_OK)
        assert st == WS.WATER_LOW
        assert WS.judge(cfg, 98.0, st) == (False, WS.WATER_LOW)
        assert WS.judge(cfg, 95.0, st) == (True, WS.WATER_OK)

    def test_stale_recovers_with_the_same_margin(self):
        cfg = _cfg(threshold=100.0)
        assert WS.judge(cfg, 101.0, WS.WATER_STALE) == (False, WS.WATER_LOW)
        assert WS.judge(cfg, 106.0, WS.WATER_STALE) == (True, WS.WATER_OK)

    def test_zero_threshold_has_no_margin(self):
        cfg = _cfg(threshold=0.0)
        _a, st = WS.judge(cfg, -1.0, WS.WATER_OK)
        assert st == WS.WATER_LOW
        assert WS.judge(cfg, 0.0, st) == (True, WS.WATER_OK)


# ─────────────────────────────────────────────────────────────────────────────
# 코디네이터 — 분무기 파킹(근거 41)
# ─────────────────────────────────────────────────────────────────────────────

def _effect(direction, magnitude):
    def fn(env, cmd_pct, profile=None):
        return EffectResult(direction, magnitude * (cmd_pct / 100.0))
    return fn


class _Sit:
    def __init__(self, target, deviation, context):
        self.target = target
        self.deviation_native = deviation
        self.context = context


def _fogger(aid='fog'):
    return ActuatorProfile(
        actuator_id=aid, kind='fogger',
        effect_model={'humidity': _effect('↑', 8.0)},
        cost_fn=lambda env, pct: 3.0,
        cmd_constraints=CmdConstraints(slew_per_cycle=100.0, min_on_pct=0.0),
        gains={'kp': 1.0, 'ki': 0.2}, safe_default=0.0)


def _window(aid='win'):
    return ActuatorProfile(
        actuator_id=aid, kind='opening',
        effect_model={'humidity': _effect('↓', 8.0)},
        cost_fn=lambda env, pct: 5.0,
        cmd_constraints=CmdConstraints(slew_per_cycle=100.0, min_on_pct=0.0),
        gains={'kp': 1.0, 'ki': 0.2}, safe_default=0.0)


# 습도가 목표보다 낮다(−20) → 분무기는 켜고 싶고 창은 닫고 싶다.
_TARGET = {'humidity': TargetVar(value=70.0, tolerance=5.0, priority=1.0, unit='%')}
_DEV = {'humidity': -20.0}


def _ctx(internal=None, **kw):
    ctx = {'cycle_sec': 60.0, 'vent_futility_gate': False, 'T_int': 24.0,
           'T_ext': 20.0, 'internal': internal if internal is not None else {},
           'external': {}}
    ctx.update(kw)
    return ctx


def _run(profiles, ctx, prev=None):
    st = CoordinatorState()
    st.prev_commands = dict(prev or {})
    st.integral = dict(prev or {})
    return coordinate(_Sit(_TARGET, dict(_DEV), ctx), profiles, st, unique_id='t')[0]


class TestParking:
    def test_water_present_leaves_the_fogger_alone(self):
        cmds = _run([_fogger()], _ctx({'_water_available': True}))
        assert cmds['fog'].reason != REASON_NO_WATER
        assert cmds['fog'].control_value() > 0.0

    def test_key_missing_means_water_present(self):
        """옵션을 켜지 않은 설치는 internal 에 키가 없다 — 종전 동작."""
        cmds = _run([_fogger()], _ctx({}))
        assert cmds['fog'].reason != REASON_NO_WATER
        assert cmds['fog'].control_value() > 0.0

    def test_no_water_parks_every_fogger_without_any_heat_protect(self):
        profiles = [_fogger('f1'), _fogger('f2')]
        cmds = _run(profiles, _ctx({'_water_available': False}),
                    prev={'f1': 60.0, 'f2': 40.0})
        for aid in ('f1', 'f2'):
            assert cmds[aid].reason == REASON_NO_WATER
        # 파킹은 safe_default(0) 쪽으로 감쇠한다 — 올라가지 않는다.
        assert cmds['f1'].control_value() < 60.0 and cmds['f2'].control_value() < 40.0

    def test_no_water_does_not_touch_vents(self):
        cmds = _run([_fogger(), _window()], _ctx({'_water_available': False}))
        assert cmds['fog'].reason == REASON_NO_WATER
        assert cmds['win'].reason != REASON_NO_WATER

    def test_no_water_wins_over_the_heat_protect_fog_block(self):
        """폭염 보호도 분무를 막고 있으면 29 가 아니라 41 — 사람이 할 일이 보이게."""
        hp = HeatProtectDecision(
            tier=1, threshold=30.0, fog_allowed=False,
            fog_blocked_ids=frozenset({'fog'}), fog_block_reason='water')
        ctx = _ctx({'_water_available': False}, heat_protect=hp, T_ceiling=32.0)
        cmds = _run([_fogger()], ctx)
        assert cmds['fog'].reason == REASON_NO_WATER
        assert cmds['fog'].reason != REASON_HEAT_FOG_BLOCKED

    def test_heat_protect_alone_still_uses_29(self):
        hp = HeatProtectDecision(
            tier=1, threshold=30.0, fog_allowed=False,
            fog_blocked_ids=frozenset({'fog'}), fog_block_reason='wetbulb')
        cmds = _run([_fogger()], _ctx({'_water_available': True}, heat_protect=hp))
        assert cmds['fog'].reason == REASON_HEAT_FOG_BLOCKED

    def test_decide_parking_exposes_the_ids(self):
        ctx = _ctx({'_water_available': False})
        pk = decide_parking([_fogger('f'), _window('w')], _Sit(_TARGET, dict(_DEV), ctx),
                            ctx, 60.0, {}, log=False)
        assert pk.water_blocked_ids == {'f'}
        assert 'f' in pk.park_ids and 'w' not in pk.park_ids

    def test_cmd_scale_zero_gives_zero_on_the_first_cycle(self):
        """파킹은 몇 사이클에 걸쳐 줄지만 전달 비율 0 은 이번 사이클부터 0 이다."""
        f = _fogger()
        f.cmd_scale = 0.0
        cmds = _run([f], _ctx({'_water_available': False}), prev={'fog': 80.0})
        assert cmds['fog'].value == 0.0


# ─────────────────────────────────────────────────────────────────────────────
# 최종 오버라이드
# ─────────────────────────────────────────────────────────────────────────────

class TestFinalOverride:
    def test_forces_every_fogger_to_zero_with_a_string_reason(self):
        profiles = [_fogger('f1'), _fogger('f2'), _window('w')]
        final = {'f1': {'value': 70.0, 'reason': 1}, 'f2': {'value': 0.0, 'reason': 0},
                 'w': {'value': 30.0, 'reason': 1}}
        apply_no_water_override({'_water_available': False}, profiles, final)
        assert final['f1'] == {'value': 0.0, 'reason': 'no_water'}
        assert final['f2'] == {'value': 0.0, 'reason': 'no_water'}
        assert final['w'] == {'value': 30.0, 'reason': 1}

    def test_does_nothing_when_water_is_there_or_unknown_option(self):
        for internal in ({}, {'_water_available': True}):
            final = {'f': {'value': 70.0, 'reason': 1}}
            apply_no_water_override(internal, [_fogger('f')], final)
            assert final['f']['value'] == 70.0

    def test_string_reason_maps_to_the_dedicated_code(self):
        assert reason_code('no_water') == float(REASON_NO_WATER)

    def test_runs_inside_the_override_chain(self):
        final = {'fog': {'value': 55.0, 'reason': 1}}
        cycle_mod.apply_threshold_and_gate_overrides(
            {'_water_available': False}, [_fogger()], final, {})
        assert final['fog']['value'] == 0.0 and final['fog']['reason'] == 'no_water'


# ─────────────────────────────────────────────────────────────────────────────
# 사이클 배선
# ─────────────────────────────────────────────────────────────────────────────

class _Host(CycleMixin, HelpersMixin):
    pass


def _host(**opts):
    c = _Host.__new__(_Host)
    c.unique_id = 'fn-water'
    c.logger = logging.getLogger('test_water_supply')
    c._status_calls = []
    c._status_log = lambda level, msg, *a: c._status_calls.append((level, msg % a if a else msg))
    c.sensor_max_age = None
    c._reading = {'value': 40.0}
    c.get_last_measurement = lambda dev, meas, max_age=None: (
        (None, None) if c._reading['value'] is None else (1.0, c._reading['value']))
    for k, v in opts.items():
        setattr(c, k, v)
    return c


@pytest.fixture
def logs(monkeypatch):
    rec = []
    monkeypatch.setattr(cycle_mod, 'write_decision_log',
                        lambda uid, meas, ch, val: rec.append((meas, ch, val)))
    return rec


@pytest.fixture(autouse=True)
def _fresh_lookup(monkeypatch):
    """신선도 조회는 DB 를 친다 — 주기를 모르는 장치로 대신한다(상한은 `sensor_max_age` 정책)."""
    from aot.utils import measurement_freshness as mf
    monkeypatch.setattr(mf, 'freshness_by_device', lambda ids: {})


def _bound(**kw):
    base = dict(water_supply_check=True, water_supply_signal_device_id='dev',
                water_supply_signal_measurement_id='m', water_supply_threshold=10.0,
                water_supply_direction='above')
    base.update(kw)
    return base


class TestCycleWiring:
    def test_unbound_puts_nothing_in_internal_and_logs_nothing(self, logs):
        c = _host()
        internal = {}
        c._apply_water_supply(internal)
        assert '_water_available' not in internal
        assert logs == []

    def test_check_on_but_no_signal_warns_once_and_does_not_restrict(self, logs, caplog):
        c = _host(water_supply_check=True)
        internal = {}
        with caplog.at_level(logging.ERROR, logger='test_water_supply'):
            for _ in range(3):
                c._apply_water_supply(internal)
        assert '_water_available' not in internal
        assert sum('신호가 지정되지' in r.getMessage() for r in caplog.records) == 1

    def test_ok_is_carried_and_recorded_every_cycle(self, logs):
        c = _host(**_bound())
        for _ in range(3):
            internal = {}
            c._apply_water_supply(internal)
            assert internal['_water_available'] is True
        assert [(m, ch, v) for m, ch, v in logs] == [
            ('water_supply_state', CH_WATER_SUPPLY, float(WS.WATER_OK))] * 3
        assert c._status_calls == []              # 정상은 말하지 않는다

    def test_low_level_is_unavailable_and_announced_once(self, logs):
        c = _host(**_bound())
        c._reading['value'] = 3.0
        for _ in range(4):
            internal = {}
            c._apply_water_supply(internal)
            assert internal['_water_available'] is False
            assert internal['_water_state'] == WS.WATER_LOW
        assert len(c._status_calls) == 1
        assert c._status_calls[0][0] == logging.WARNING

    def test_stale_signal_is_unavailable(self, logs):
        c = _host(**_bound())
        c._reading['value'] = None
        internal = {}
        c._apply_water_supply(internal)
        assert internal['_water_available'] is False
        assert internal['_water_state'] == WS.WATER_STALE

    def test_recovery_is_announced_once_with_hysteresis(self, logs):
        c = _host(**_bound(water_supply_threshold=100.0))
        c._reading['value'] = 50.0
        c._apply_water_supply({})
        c._reading['value'] = 102.0                      # 문턱은 넘었으나 이력 여유 미달
        i = {}
        c._apply_water_supply(i)
        assert i['_water_available'] is False
        c._reading['value'] = 110.0
        i = {}
        c._apply_water_supply(i)
        assert i['_water_available'] is True
        levels = [lvl for lvl, _ in c._status_calls]
        assert levels == [logging.WARNING, logging.INFO]

    def test_turning_the_option_off_forgets_the_state(self, logs):
        c = _host(**_bound())
        c._reading['value'] = 1.0
        c._apply_water_supply({})
        c.water_supply_check = False
        internal = {}
        c._apply_water_supply(internal)
        assert '_water_available' not in internal

    def test_config_reads_options_with_defaults(self):
        cfg = _host()._water_supply_config()
        assert cfg.bound is False and cfg.threshold == 0.5 and cfg.direction == 'above'
        cfg = _host(**_bound(water_supply_threshold='7', water_supply_direction='below')
                    )._water_supply_config()
        assert cfg.bound and cfg.threshold == 7.0 and cfg.direction == 'below'

    def test_signal_without_the_toggle_is_not_bound(self):
        c = _host(water_supply_signal_device_id='d', water_supply_signal_measurement_id='m')
        assert c._water_supply_config().bound is False

    def test_read_failure_is_stale_not_an_exception(self, logs):
        c = _host(**_bound())

        def boom(*a, **k):
            raise RuntimeError('db down')
        c.get_last_measurement = boom
        internal = {}
        c._apply_water_supply(internal)
        assert internal['_water_available'] is False
        assert internal['_water_state'] == WS.WATER_STALE


def test_run_cycle_loads_water_before_anything_reads_it():
    """internal 에 싣는 줄이 보호 판정·L2 보다 **앞**이어야 한다 — 뒤면 한 사이클 늦은 값을 읽는다."""
    import inspect
    src = inspect.getsource(CycleMixin._run_cycle)
    i_water = src.index('self._apply_water_supply(internal)')
    assert i_water < src.index('self._evaluate_heat_protect(')
    assert i_water < src.index('assess(')
