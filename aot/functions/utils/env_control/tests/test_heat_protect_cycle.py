# coding=utf-8
"""극한 고온 보호의 사이클 배선 — 판정을 부르고, 말하고, 엔진·긴급·분무·유동팬에 싣는가.

판정 자체는 `test_heat_protect.py`, PI 안은 `test_heat_protect_parking.py` 가 본다.
여기는 `CycleMixin` 의 이음매들이다:

  · 단계·플래그(CH75·76)는 **debug 와 무관하게 매 사이클** 남는다.
  · 단계 2 진입에 한 번 경보 메일(예전 폭염 게이트의 자리). 문턱 ≥ temp_max 면 한 번 error.
  · 보호 중이면 MPC·greybox-PI 를 건너뛰어 레거시로(폴백 사유 'heat_protect').
  · 긴급은 단계가 **올라가는** 사이클에만 한 번.
  · 분무 차단은 전달 비율 0, 보호 중 습윤 분무의 습도 상한은 min(humid_max, 85).
  · 보호 중 유동팬 100.
"""
import logging
import types as _types

import pytest

import aot.functions.custom_functions.env_coordinator_impl._cycle_mixin as cycle_mod
from aot.functions.custom_functions.env_coordinator_impl._cycle_mixin import CycleMixin
from aot.functions.utils.env_control.coordinator import CoordinatorState
from aot.functions.utils.env_control.greybox.mpc import MPCConfig
from aot.functions.utils.env_control.greybox.params import GreyboxParams
from aot.functions.utils.env_control.heat_protect import HeatProtectDecision
from aot.functions.utils.env_control.log_channels import (
    CH_HEAT_PROTECT_FLAGS, CH_HEAT_PROTECT_TIER,
)
from aot.functions.utils.env_control.safety_gates import GateResult
from aot.functions.utils.env_control.situation import assess
from aot.functions.utils.env_control.types import (
    ActuatorProfile, CmdConstraints, TargetVar,
)

from .conftest import make_ctx, make_opening_profile, make_target


def _p(aid, kind):
    return ActuatorProfile(actuator_id=aid, kind=kind, effect_model={},
                           cmd_constraints=CmdConstraints(), gains={})


def _host(profiles=None, **opts):
    c = CycleMixin.__new__(CycleMixin)
    c._profiles = profiles if profiles is not None else [
        _p('win', 'opening'), _p('fog', 'fogger'), _p('circ', 'circulation_fan')]
    c._coord_state = CoordinatorState()
    c._trend_state = None
    c.unique_id = 'fn-heat'
    c.temp_max = 35.0
    c.humid_max = 90.0
    c.light_min = None
    c.logger = logging.getLogger('test_heat_protect_cycle')
    c._constraint_breach_state = {'T_max': False, 'T_min': False, 'RH_max': False,
                                  'RH_min': False, 'fog_RH': False}
    c.emails = []
    c._send_critical_email = lambda key, msg: c.emails.append(key)
    for k, v in opts.items():
        setattr(c, k, v)
    return c


@pytest.fixture
def logs(monkeypatch):
    rec = []
    monkeypatch.setattr(cycle_mod, 'write_decision_log',
                        lambda uid, meas, ch, val: rec.append((meas, ch, val)))
    return rec


@pytest.fixture
def clock(monkeypatch):
    t = {'now': 1_767_240_000.0}
    monkeypatch.setattr(cycle_mod.time, 'time', lambda: t['now'])
    return t


# ─────────────────────────────────────────────────────────────────────────────
# _evaluate_heat_protect
# ─────────────────────────────────────────────────────────────────────────────

class TestEvaluate:
    def test_tier_and_flags_are_logged_every_cycle_without_debug(self, logs, clock):
        c = _host(log_level_debug=False)
        for T in (25.0, 25.0, 31.5):
            c._evaluate_heat_protect({'T': T, 'RH': 50.0}, {'T': 26.0}, 60.0)
            clock['now'] += 60.0
        tiers = [v for m, ch, v in logs if ch == CH_HEAT_PROTECT_TIER]
        flags = [v for m, ch, v in logs if ch == CH_HEAT_PROTECT_FLAGS]
        assert tiers == [0.0, 0.0, 1.0] and len(flags) == 3
        assert {m for m, ch, v in logs} == {'heat_protect_tier', 'heat_protect_flags'}

    def test_decision_is_carried_in_internal(self, logs, clock):
        c = _host()
        internal = {'T': 31.5, 'RH': 50.0}
        dec = c._evaluate_heat_protect(internal, {'T': 26.0}, 60.0)
        assert internal['_heat_protect'] is dec and dec.tier == 1

    def test_tier2_entry_sends_one_alert(self, logs, clock):
        c = _host()
        for _ in range(3):
            c._evaluate_heat_protect({'T': 36.0, 'RH': 50.0, '_force_cool': True},
                                     {'T': 30.0}, 60.0)
            clock['now'] += 60.0
        assert c.emails == ['extreme_heat']

    def test_tier1_does_not_send_the_alert(self, logs, clock):
        c = _host()
        c._evaluate_heat_protect({'T': 31.5, 'RH': 50.0}, {'T': 26.0}, 60.0)
        assert c.emails == []

    def test_threshold_at_or_above_temp_max_is_reported_once(self, logs, clock, caplog):
        c = _host(temp_max=30.0, heat_protect_threshold=32.0)
        with caplog.at_level(logging.ERROR, logger='test_heat_protect_cycle'):
            for _ in range(4):
                c._evaluate_heat_protect({'T': 25.0, 'RH': 50.0}, {'T': 20.0}, 60.0)
        assert sum('문턱' in r.getMessage() for r in caplog.records) == 1

    def test_options_are_clamped_to_their_range(self):
        cfg = _host(heat_protect_threshold=5.0, heat_protect_release_margin=99.0,
                    heat_protect_min_hold_min=1.0)._heat_protect_config(60.0)
        assert cfg.threshold == 20.0 and cfg.release_margin == 5.0
        assert cfg.min_hold_s == 5.0 * 60.0

    def test_unset_options_read_as_defaults(self):
        cfg = _host()._heat_protect_config(60.0)
        assert cfg.enabled is True and cfg.threshold == 30.0
        assert cfg.release_margin == 1.5 and cfg.min_hold_s == 1200.0

    def test_disabled_option_is_honoured(self, logs, clock):
        c = _host(heat_protect_enabled=False)
        assert c._evaluate_heat_protect({'T': 40.0, 'RH': 50.0}, {}, 60.0).tier == 0


# ─────────────────────────────────────────────────────────────────────────────
# 긴급 — 단계가 올라가는 사이클에만
# ─────────────────────────────────────────────────────────────────────────────

def test_emergency_only_on_the_escalating_cycle():
    c = _host(_force_immediate=False, emergency_deviation_mult=3.0,
              emergency_rate_c_per_10min=2.0)

    def sit(dec):
        return _types.SimpleNamespace(
            deviation_native={}, target={}, context={'T_trend': 0.0,
                                                     'heat_protect': dec})
    up = HeatProtectDecision(tier=1, escalated=True)
    steady = HeatProtectDecision(tier=1, escalated=False)
    calm = GateResult(triggered=False)
    assert c._classify_emergency(calm, sit(up)) == (True, 'heat_protect')
    assert c._classify_emergency(calm, sit(steady)) == (False, '')


# ─────────────────────────────────────────────────────────────────────────────
# 엔진 선택 이음매 — 보호 중에는 레거시
# ─────────────────────────────────────────────────────────────────────────────

def _mpc_host(profiles):
    c = _host(profiles)
    c._greybox_active = True
    c._mpc_enabled = True
    c._greybox_shadow_inst = _types.SimpleNamespace(params=GreyboxParams())
    c._mpc_config = MPCConfig(horizon=8)
    c._actuator_idx = {}
    return c


def _report(tier):
    ctx = make_ctx(T_int=31.0, T_ext=26.0)
    report, _ = assess(make_target(vpd=1.5, T=22.0), dict(ctx['internal']),
                       ctx['external'], cycle_sec=60.0, now_ts=ctx['now_ts'],
                       heat_protect_tier=tier)
    report.context['heat_protect'] = HeatProtectDecision(tier=tier)
    return report


def test_protection_skips_mpc_and_greybox(monkeypatch):
    p = make_opening_profile()
    p._legacy_effect_model = p.effect_model
    p.effect_model = {'temperature': lambda *a, **k: None}      # greybox 어댑터 대역
    c = _mpc_host([p])
    calls = []
    monkeypatch.setattr(c, '_run_mpc', lambda *a, **k: calls.append(1))
    c._run_control(_report(1), '')
    assert not calls and c._last_control_engine == 'legacy'
    assert c._last_control_fallback == 'heat_protect'
    assert p.effect_model is p._legacy_effect_model


def test_without_protection_mpc_runs():
    c = _mpc_host([make_opening_profile()])
    c._run_control(_report(0), '')
    assert c._last_control_engine == 'mpc' and c._last_control_fallback is None


def test_fallback_message_names_the_reason(caplog):
    c = _mpc_host([make_opening_profile()])
    with caplog.at_level(logging.WARNING, logger='test_heat_protect_cycle'):
        for _ in range(3):
            c._run_control(_report(1), '')
    msgs = [r.getMessage() for r in caplog.records if 'MPC/greybox' in r.getMessage()]
    assert len(msgs) == 1 and '극한 고온 보호' in msgs[0]


# ─────────────────────────────────────────────────────────────────────────────
# 분무 · 유동팬
# ─────────────────────────────────────────────────────────────────────────────

def test_blocked_fog_gets_zero_transfer_ratio():
    c = _host()
    c._vent_openings = []
    dec = HeatProtectDecision(tier=1, fog_allowed=False,
                              fog_blocked_ids=frozenset({'fog'}))
    c._apply_cmd_scales({'_heat_protect': dec}, {})
    by = {p.actuator_id: p for p in c._profiles}
    assert by['fog'].cmd_scale == 0.0 and by['win'].cmd_scale == 1.0


def test_wetting_fog_ceiling_during_protection_only_tightens():
    """보호 중에도 습윤형 습도 상한은 **좁아지기만** 한다 — min(목표+허용, humid_max, 85).

    예전에는 보호 중 상한을 85 로 넓혀 습윤형 상한을 우회했다(2026-10-09 폐루프 검토).
    습윤형은 보호의 증발냉각기가 아니다(`heat_protect.cooling_foggers`)."""
    c = _host()
    rh_target = TargetVar(value=60.0, tolerance=5.0)
    sit = _types.SimpleNamespace(target={'_humidity_constraint': rh_target})
    internal = {'RH': 75.0, '_heat_protect': HeatProtectDecision(tier=1)}
    c._judge_fog_humidity_block(sit, internal)
    assert internal.get('_fog_humidity_block')          # 목표+허용(65) 위 — 보호 중에도 잠근다
    c._constraint_breach_state['fog_RH'] = False
    internal = {'RH': 62.0, '_heat_protect': HeatProtectDecision(tier=1)}
    c._judge_fog_humidity_block(sit, internal)
    assert not internal.get('_fog_humidity_block')
    # 목표가 85 보다 넓으면 보호의 습도 문턱(85)이 이긴다
    wide = _types.SimpleNamespace(
        target={'_humidity_constraint': TargetVar(value=85.0, tolerance=5.0)})
    internal = {'RH': 86.0, '_heat_protect': HeatProtectDecision(tier=1)}
    c._judge_fog_humidity_block(wide, internal)
    assert internal.get('_fog_humidity_block')
    c._constraint_breach_state['fog_RH'] = False
    internal = {'RH': 86.0}
    c._judge_fog_humidity_block(wide, internal)
    assert not internal.get('_fog_humidity_block')      # 보호 밖에서는 종전대로 목표+허용(90)


def test_circulation_fan_runs_during_protection():
    from aot.functions.utils.env_control.coordinator import ActuatorCommand
    c = _host()
    cmds = {'circ': ActuatorCommand(value=0.0, reason=0)}
    c._apply_mixing_actuators(cmds, {'_heat_protect': HeatProtectDecision(tier=1)})
    assert cmds['circ'].value == 100.0 and cmds['circ'].var_source == 'heat_protect'
    cmds = {'circ': ActuatorCommand(value=0.0, reason=0)}
    c._apply_mixing_actuators(cmds, {})
    assert cmds['circ'].value == 0.0
