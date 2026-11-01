# coding=utf-8
"""강우·강풍 폐쇄는 고온 대응을 이긴다 (B1 회귀 — 2026-10-09 의미 갱신).

1단계(B1)에서는 `_build_forced_commands` 의 폭염 블록이 강우·강풍으로 닫은 창을 다시
100 으로 덮어쓰는 것을 막았다. 그 폭염 비상 게이트는 없앴고(실외 ≥45 °C 에서는 대개
바깥이 더 더워 창 100 이 반대 방향이었다), 고온은 극한 고온 보호(`heat_protect`)가
맡는다. 지켜야 할 뜻은 그대로다:

  · 비·강풍으로 닫힌 창은 고온 대응이 다시 열지 못한다.
  · 그래도 차광·냉방·팬은 일한다 — 비가 온다고 더위 대응을 통째로 멈추지 않는다.
  · 풍하측처럼 게이트가 닫지 않은 창은 (바깥이 더 시원하면) 보호가 열 수 있다.

두 경로를 본다: 게이트가 L1~L3 를 건너뛰는 사이클(`_act_on_triggered_gate` → direct
모드, 게이트가 명령한 장치는 건너뜀)과 부분 게이트 사이클(정상 PI + 오버라이드 순서에서
게이트가 마지막).
"""
import logging

import pytest

from aot.functions.custom_functions.env_coordinator_impl._cycle_mixin import (
    CycleMixin, apply_threshold_and_gate_overrides)
from aot.functions.utils.env_control.coordinator import CoordinatorState
from aot.functions.utils.env_control.heat_protect import (
    HeatProtectDecision, apply_heat_protect_overrides)
from aot.functions.utils.env_control.log_channels import GATE_BIT_HEAT
from aot.functions.utils.env_control.safety_gates import (
    GATE_BIT_RAIN, GATE_BIT_WIND, PreGateConfig, SafetyPreGate)
from aot.functions.utils.env_control.types import ActuatorProfile, CmdConstraints

import aot.functions.custom_functions.env_coordinator_impl._cycle_mixin as cycle_mod

from .conftest import make_opening_profile

CFG = PreGateConfig(gate_ttl=0.0)


def _p(aid, kind):
    return ActuatorProfile(actuator_id=aid, kind=kind, effect_model={},
                           cmd_constraints=CmdConstraints(), gains={},
                           safe_default=0.0)


def _forced(mask, profiles, ext=None, per_opening=False):
    return SafetyPreGate(CFG)._build_forced_commands(mask, profiles, ext or {}, per_opening)


def _hot_cool_outside(open_ids):
    """보호 단계 1 · 바깥이 더 시원 · 차광 전개."""
    return HeatProtectDecision(tier=1, vent_open_ok=True,
                               vent_open_ids=frozenset(open_ids), shade_deploy=True)


def test_rain_closes_openings_and_forces_nothing_else():
    profiles = [make_opening_profile('v1'), _p('shade', 'shade'), _p('cool', 'cooler')]
    cmds = _forced(GATE_BIT_RAIN, profiles)
    assert cmds['v1']['value'] == pytest.approx(0.0)
    assert 'shade' not in cmds and 'cool' not in cmds


def test_rain_plus_heat_keeps_openings_closed_but_shade_and_cooler_work():
    profiles = [make_opening_profile('v1'), make_opening_profile('v2'),
                _p('shade', 'shade'), _p('cool', 'cooler'), _p('fan', 'exhaust_fan')]
    cmds = _forced(GATE_BIT_RAIN, profiles)
    apply_heat_protect_overrides(_hot_cool_outside({'v1', 'v2', 'fan'}), profiles,
                                 cmds, mode='direct', skip_ids=set(cmds))
    assert cmds['v1']['value'] == pytest.approx(0.0)
    assert cmds['v2']['value'] == pytest.approx(0.0)
    assert cmds['shade']['value'] == pytest.approx(0.0)
    assert cmds['cool']['value'] == pytest.approx(100.0)
    assert cmds['fan']['value'] == pytest.approx(100.0)


def test_wind_per_opening_plus_heat_windward_closed_leeward_opened():
    east = make_opening_profile('east', azimuth_deg=90.0)
    west = make_opening_profile('west', azimuth_deg=270.0)
    profiles = [east, west, _p('cool', 'cooler')]
    cmds = _forced(GATE_BIT_WIND, profiles, ext={'wind_dir': 90.0}, per_opening=True)
    apply_heat_protect_overrides(_hot_cool_outside({'east', 'west'}), profiles,
                                 cmds, mode='direct', skip_ids=set(cmds))
    assert cmds['east']['value'] == pytest.approx(0.0)      # 풍상측 — 닫힌 채
    assert cmds['west']['value'] == pytest.approx(100.0)    # 풍하측 — 보호가 연다
    assert cmds['cool']['value'] == pytest.approx(100.0)


def test_partial_gate_beats_heat_protection_in_a_normal_cycle():
    """풍향 차등(부분 게이트)은 정상 사이클의 오버라이드 순서에서 마지막이다."""
    east = make_opening_profile('east', azimuth_deg=90.0)
    west = make_opening_profile('west', azimuth_deg=270.0)
    profiles = [east, west, _p('shade', 'shade')]
    partial = _forced(GATE_BIT_WIND, profiles, ext={'wind_dir': 90.0}, per_opening=True)
    final = {'east': {'value': 80.0, 'reason': 1}, 'west': {'value': 80.0, 'reason': 1},
             'shade': {'value': 100.0, 'reason': 1}}
    apply_threshold_and_gate_overrides(
        {'_heat_protect': _hot_cool_outside({'east', 'west'})}, profiles, final, partial)
    assert final['east']['value'] == pytest.approx(0.0)
    assert final['west']['value'] == pytest.approx(80.0)    # PI 의 몫 그대로
    assert final['shade']['value'] == pytest.approx(0.0)    # 보호의 차광


def test_the_gate_no_longer_carries_a_heat_emergency():
    gate = SafetyPreGate(CFG)
    env = {'internal': {'T': 36.0, 'T_max': 36.0, 'T_min': 36.0, 'RH': 60.0},
           'external': {'T': 46.0, 'rain': 3.0, 'wind': 1.0}}
    res = gate.evaluate(env, [make_opening_profile('v'), _p('shade', 'shade')])
    assert res.gate_mask & GATE_BIT_RAIN and not res.gate_mask & GATE_BIT_HEAT
    assert res.forced_commands['v']['value'] == pytest.approx(0.0)
    assert 'shade' not in res.forced_commands


# ─────────────────────────────────────────────────────────────────────────────
# 끝에서 끝 — 비가 오는 폭염 사이클(`_act_on_triggered_gate`)
# ─────────────────────────────────────────────────────────────────────────────

class _Host(CycleMixin):
    def __init__(self, profiles):
        self._profiles = profiles
        self._coord_state = CoordinatorState()
        self._trend_state = None
        self.unique_id = ''
        self.temp_max = 35.0
        self.temp_min = 5.0
        self.humid_max = 90.0
        self.humid_min = 30.0
        self.light_max = None
        self.light_min = None
        self.logger = logging.getLogger('test_gate_weather_vs_heat')
        self._constraint_breach_state = {'T_max': False, 'T_min': False,
                                         'RH_max': False, 'RH_min': False,
                                         'fog_RH': False}
        self._light_breach_state = {'max': False, 'min': False}
        self.sent = []
        self.emails = []

    def _dispatch(self, commands, cycle_sec=60.0, emergency=False):
        self.sent.append((dict(commands), emergency))
        return set()

    def _send_critical_email(self, key, msg):
        self.emails.append(key)

    def _refresh_capability(self, *a, **k):
        pass

    def _write_gate_only_summary(self, *a, **k):
        pass


def test_rain_during_heat_end_to_end(monkeypatch):
    monkeypatch.setattr(cycle_mod, 'write_decision_log', lambda *a, **k: None)
    profiles = [make_opening_profile('vent'), _p('fan', 'exhaust_fan'),
                _p('shade', 'shade'), _p('cool', 'cooler'), _p('fog', 'fogger'),
                _p('heat', 'heater'), _p('circ', 'circulation_fan')]
    host = _Host(profiles)
    gate = SafetyPreGate(CFG)
    gate_env = {'internal': {'T': 33.0, 'T_max': 33.0, 'T_min': 33.0, 'RH': 55.0},
                'external': {'T': 29.0, 'rain': 3.0, 'wind': 1.0, 'solar': 700.0}}
    res = gate.evaluate(gate_env, profiles)
    assert res.triggered
    internal = {'T': 33.0, 'RH': 55.0, '_outdoor_solar': 700.0}
    host._act_on_triggered_gate(res, gate_env, 60.0, 0.0, internal,
                                {'T': 29.0})
    (gate_cmds, gate_emerg), (heat_cmds, heat_emerg) = host.sent
    assert gate_emerg is True
    assert gate_cmds == {'vent': {'value': 0.0, 'reason': 12, 'ttl': 300.0}}
    assert 'vent' not in heat_cmds                           # 비가 닫은 창은 그대로
    assert heat_cmds['fan']['value'] == 100.0                # 바깥이 더 시원 — 팬은 돈다
    assert heat_cmds['shade']['value'] == 0.0
    assert heat_cmds['cool']['value'] == 100.0
    assert heat_cmds['fog']['value'] == 0.0                  # 되먹임 없는 경로 — 분무 0
    assert heat_cmds['heat']['value'] == 0.0
    assert heat_cmds['circ']['value'] == 100.0
    assert heat_emerg is True                                # 이번 사이클에 진입(단계 상승)
    assert internal['_heat_protect'].tier == 1
    # 다음 사이클 — 단계가 그대로면 보호 명령은 구동 주기를 지킨다
    host.sent.clear()
    host._act_on_triggered_gate(res, gate_env, 60.0, 60.0,
                                {'T': 33.0, 'RH': 55.0, '_outdoor_solar': 700.0},
                                {'T': 29.0})
    assert host.sent[1][1] is False
