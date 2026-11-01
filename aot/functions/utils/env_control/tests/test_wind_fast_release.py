# coding=utf-8
"""강풍 2단계의 고온 빠른 내림과 최근 20 분 평균 풀림 (2026-10-12, 근거 55·12).

폭풍 시뮬 `foehn_dry_wind` 이튿날(2026-10-11 보고 `env_storm_final.md`): 13:40 2단계가 선 뒤 10분
평균이 9.6~11 m/s 로 내려가는 문턱(12 × 0.85 = 10.2) 언저리를 오가, 한 번 위로 튈 때마다 "20 분 연속"
시계가 처음부터 다시 섰다. 맑은 31 °C 아래 개구부가 80 분 전부 닫혀 실내 44 °C, 40 °C 초과 22 → 258 분.

지키는 것:
  · 고온(실내 ≥ 극한 고온 보호 문턱, 또는 보호 단계 ≥ 1)이면 2단계 근거(평균 ≥ 문턱 · 잰 돌풍 ≥ 1.5 배)가
    사라진 첫 사이클에 바로 1단계(풍상측 닫음 · 천창 30 % · 측창 50 %)로 내린다. 값이 끊겼으면 안 한다.
  · 2단계 근거가 다시 서면 즉시 전부 닫는다(올라가기는 언제나 즉시).
  · 풀림은 그 단계가 (다시) 선 뒤 **최근 20 분 표본의 평균**으로 — 한 번 튄 값이 시계를 다시 세우지 않는다.
    한 단계씩, 끊긴 값은 창을 비운다(규칙 A).
  · 단계·평균 창은 재시작을 넘는다(`cycle_memory`).
"""
import json
import types

import pytest

import aot.functions.utils.env_control.safety_gates as sg
from aot.functions.custom_functions.env_coordinator import CustomModule
from aot.functions.custom_functions.env_coordinator_impl._cycle_mixin import (
    apply_threshold_and_gate_overrides)
from aot.functions.custom_functions.env_coordinator_impl._helpers_mixin import (
    HelpersMixin)
from aot.functions.utils.env_control import cycle_memory
from aot.functions.utils.env_control.heat_protect import (
    HeatProtectDecision, HeatProtectState)
from aot.functions.utils.env_control.log_channels import (
    GATE_BIT_EXT_EXP, GATE_BIT_RAIN_LIGHT, GATE_BIT_WIND, GATE_BIT_WIND_LIGHT,
    REASON_RAIN_RESTRICT, REASON_WIND_RESTRICT)
from aot.functions.utils.env_control.safety_gates import (
    WIND_LEVEL_CLOSE, WIND_LEVEL_HOLD_S, WIND_LEVEL_NONE, WIND_LEVEL_RESTRICT,
    WIND_SIDE_CAP_PCT, PreGateConfig, SafetyPreGate, WindState)

from .test_wind_gate_grading import _env, _gimje, _vent, clock  # noqa: F401 (fixture)

CFG = PreGateConfig(gate_ttl=0.0)


def _heat(env, T=33.0, tier=0, thr=30.0):
    env['heat_protect'] = {'T': T, 'threshold': thr, 'tier': tier}
    return env


def _lv(res):
    if res.gate_mask & GATE_BIT_WIND:
        return WIND_LEVEL_CLOSE
    return WIND_LEVEL_RESTRICT if res.gate_mask & GATE_BIT_WIND_LIGHT else WIND_LEVEL_NONE


def _step(gate, clock, wind, gust=None, dt=600.0, profiles=None, **heat):
    clock.t += dt
    env = _env(wind, gust)
    if heat:
        _heat(env, **heat)
    return gate.evaluate(env, profiles or _gimje())


HOT = {'T': 33.0}
MILD = {'T': 27.0}


# ─────────────────────────────────────────────────────────────────────────────
# 1. 고온이면 2 → 1 바로
# ─────────────────────────────────────────────────────────────────────────────

class TestFastStep:

    def test_푄_이튿날_한_사이클_만에_1단계(self, clock):
        """시뮬 6/3 13:40~14:30 — 예전에는 전부 닫힘이 80 분이었다."""
        gate = SafetyPreGate(CFG)
        seen = [_lv(_step(gate, clock, w, **HOT)) for w in (12.3, 11.9, 11.0, 9.8, 10.8)]
        assert seen == [WIND_LEVEL_CLOSE] + [WIND_LEVEL_RESTRICT] * 4

    def test_1단계_상한으로_연다(self, clock):
        gate = SafetyPreGate(CFG)
        _step(gate, clock, 13.0, **HOT)
        res = _step(gate, clock, 11.0, **HOT)
        assert not res.triggered and res.partial
        assert res.forced_commands == {}
        assert res.vent_caps == {'right': WIND_SIDE_CAP_PCT, 'left': WIND_SIDE_CAP_PCT}
        assert res.vent_cap_reasons == {'right': REASON_WIND_RESTRICT,
                                        'left': REASON_WIND_RESTRICT}

    def test_방위각을_알면_풍상측은_닫힌_채(self, clock):
        vents = [_vent('east', 90.0), _vent('west', 270.0), _vent('roof', 90.0, form='roof')]
        gate = SafetyPreGate(CFG)
        clock.t += 600.0
        gate.evaluate(_heat(_env(13.0, wind_dir=90.0)), vents)
        clock.t += 600.0
        res = gate.evaluate(_heat(_env(11.0, wind_dir=90.0)), vents)
        assert res.forced_commands['east']['value'] == 0.0
        assert res.forced_commands['roof']['value'] == 0.0
        assert res.vent_caps == {'west': WIND_SIDE_CAP_PCT}

    def test_덥지_않으면_종전대로_유지(self, clock):
        gate = SafetyPreGate(CFG)
        seen = [_lv(_step(gate, clock, w, **MILD)) for w in (13.0, 11.0, 11.0)]
        assert seen == [WIND_LEVEL_CLOSE] * 3

    def test_보호_단계가_서_있으면_문턱_아래여도(self, clock):
        gate = SafetyPreGate(CFG)
        _step(gate, clock, 13.0, T=29.0, tier=1)
        assert _lv(_step(gate, clock, 11.0, T=29.0, tier=1)) == WIND_LEVEL_RESTRICT

    def test_보호를_끈_설치는_빠른_내림이_없다(self, clock):
        gate = SafetyPreGate(CFG)
        _step(gate, clock, 13.0, T=40.0, thr=None, tier=0)
        assert _lv(_step(gate, clock, 11.0, T=40.0, thr=None, tier=0)) == WIND_LEVEL_CLOSE

    def test_고온_정보가_없으면_종전대로(self, clock):
        gate = SafetyPreGate(CFG)
        _step(gate, clock, 13.0)
        assert _lv(_step(gate, clock, 11.0)) == WIND_LEVEL_CLOSE

    def test_실내를_모르면_보호_단계만_본다(self, clock):
        gate = SafetyPreGate(CFG)
        _step(gate, clock, 13.0, T=None)
        assert _lv(_step(gate, clock, 11.0, T=None)) == WIND_LEVEL_CLOSE
        gate = SafetyPreGate(CFG)
        _step(gate, clock, 13.0, T=None, tier=2)
        assert _lv(_step(gate, clock, 11.0, T=None, tier=2)) == WIND_LEVEL_RESTRICT

    @pytest.mark.parametrize('wind', [12.0, 14.0])
    def test_평균이_문턱_이상이면_닫힌_채(self, clock, wind):
        gate = SafetyPreGate(CFG)
        _step(gate, clock, 13.0, **HOT)
        assert _lv(_step(gate, clock, wind, **HOT)) == WIND_LEVEL_CLOSE

    def test_잰_돌풍이_2단계_문턱_이상이면_닫힌_채(self, clock):
        gate = SafetyPreGate(CFG)
        _step(gate, clock, 13.0, gust=19.0, **HOT)
        assert _lv(_step(gate, clock, 9.0, gust=18.5, **HOT)) == WIND_LEVEL_CLOSE
        assert _lv(_step(gate, clock, 9.0, gust=17.0, **HOT)) == WIND_LEVEL_RESTRICT

    def test_돌풍_센서가_없으면_평균만_본다(self, clock):
        gate = SafetyPreGate(CFG)
        _step(gate, clock, 13.0, **HOT)
        assert _lv(_step(gate, clock, 11.5, **HOT)) == WIND_LEVEL_RESTRICT

    def test_풍속이_끊기면_빠른_내림이_없다(self, clock):
        gate = SafetyPreGate(CFG)
        _step(gate, clock, 13.0, **HOT)
        res = _step(gate, clock, None, **HOT)       # 마지막 값 13 — 닫는 근거로 남는다
        assert _lv(res) == WIND_LEVEL_CLOSE and res.gate_mask & GATE_BIT_EXT_EXP
        gate = SafetyPreGate(CFG)
        _step(gate, clock, 11.0, gust=19.0, **HOT)
        _step(gate, clock, 11.0, gust=19.0, **HOT)
        res = _step(gate, clock, 11.0, **HOT)        # 돌풍만 끊김 — 마지막 19
        assert _lv(res) == WIND_LEVEL_CLOSE

    def test_끊긴_뒤_돌아온_첫_값은_빠른_내림을_허락한다(self, clock):
        """돌아온 값은 이번에 잰 값이다 — 낡은 값이 아니므로 규칙 A 와 부딪히지 않는다."""
        gate = SafetyPreGate(CFG)
        _step(gate, clock, 13.0, **HOT)
        _step(gate, clock, None, **HOT)
        assert _lv(_step(gate, clock, 11.0, **HOT)) == WIND_LEVEL_RESTRICT

    def test_2단계_근거가_다시_서면_즉시_닫는다(self, clock):
        gate = SafetyPreGate(CFG)
        seen = [_lv(_step(gate, clock, w, **HOT)) for w in (13.0, 11.0, 12.4, 11.0)]
        assert seen == [WIND_LEVEL_CLOSE, WIND_LEVEL_RESTRICT, WIND_LEVEL_CLOSE,
                        WIND_LEVEL_RESTRICT]
        gate = SafetyPreGate(CFG)
        _step(gate, clock, 13.0, **HOT)
        _step(gate, clock, 11.0, **HOT)
        res = _step(gate, clock, 8.0, gust=18.2, dt=60.0, **HOT)    # 사이클 사이 돌풍
        assert _lv(res) == WIND_LEVEL_CLOSE and res.triggered

    def test_빠른_내림은_1단계까지만_그_뒤는_평균(self, clock):
        gate = SafetyPreGate(CFG)
        seen = [_lv(_step(gate, clock, w, **HOT)) for w in (13.0, 2.0, 2.0, 2.0, 2.0)]
        assert seen == [WIND_LEVEL_CLOSE] + [WIND_LEVEL_RESTRICT] * 3 + [WIND_LEVEL_NONE]

    def test_1단계에서_0_으로는_빠르지_않다(self, clock):
        """빠른 내림은 2 → 1 하나뿐 — 1단계 근거가 남은 바람에 천창 상한을 푸는 일은 없다."""
        gate = SafetyPreGate(CFG)
        _step(gate, clock, 9.0, **HOT)
        assert _lv(_step(gate, clock, 5.0, **HOT)) == WIND_LEVEL_RESTRICT


# ─────────────────────────────────────────────────────────────────────────────
# 2. 비·고온 보호와 함께
# ─────────────────────────────────────────────────────────────────────────────

class TestWithRainAndHeat:

    def test_예보_비_단계_제한과_겹치면_낮은_상한(self, clock):
        gate = SafetyPreGate(CFG)
        _step(gate, clock, 13.0, **HOT)
        clock.t += 600.0
        env = _heat(_env(11.0, rain=2.0))
        env['external']['rain_origin'] = 'model'
        res = gate.evaluate(env, _gimje())
        assert res.gate_mask & GATE_BIT_WIND_LIGHT and res.gate_mask & GATE_BIT_RAIN_LIGHT
        assert not res.gate_mask & GATE_BIT_WIND
        assert res.vent_caps == {'right': 30.0, 'left': 30.0}
        assert res.vent_cap_reasons == {'right': REASON_RAIN_RESTRICT,
                                        'left': REASON_RAIN_RESTRICT}

    def test_실측_비가_오면_전부_닫힌_채(self, clock):
        gate = SafetyPreGate(CFG)
        _step(gate, clock, 13.0, **HOT)
        clock.t += 600.0
        res = gate.evaluate(_heat(_env(11.0, rain=3.0)), _gimje())
        assert res.triggered
        assert all(c['value'] == 0.0 for c in res.forced_commands.values())

    def test_고온_보호는_빠른_내림_뒤에도_상한까지만(self, clock):
        gate = SafetyPreGate(CFG)
        vents = _gimje()
        _step(gate, clock, 13.0, **HOT)
        res = _step(gate, clock, 11.0, **HOT)
        final = {p.actuator_id: {'value': 20.0, 'reason': 1} for p in vents}
        internal = {'T': 36.0, 'RH': 20.0,
                    '_heat_protect': HeatProtectDecision(
                        tier=2, vent_open_ok=True,
                        vent_open_ids=frozenset({'right', 'left'}))}
        apply_threshold_and_gate_overrides(internal, vents, final, res.forced_commands,
                                           res.vent_caps, res.vent_cap_reasons)
        for aid in ('right', 'left'):
            assert final[aid] == {'value': WIND_SIDE_CAP_PCT, 'reason': REASON_WIND_RESTRICT}


# ─────────────────────────────────────────────────────────────────────────────
# 3. 최근 20 분 평균으로 풀기
# ─────────────────────────────────────────────────────────────────────────────

class TestRollingRelease:

    def test_한_번_튄_값이_시계를_다시_세우지_않는다(self, clock):
        gate = SafetyPreGate(CFG)
        seen = [_lv(_step(gate, clock, w, **MILD)) for w in (13.0, 9.0, 9.0, 11.0)]
        assert seen == [WIND_LEVEL_CLOSE] * 3 + [WIND_LEVEL_RESTRICT]   # (9+9+11)/3 = 9.7

    def test_평균이_내려가는_문턱_위면_유지(self, clock):
        gate = SafetyPreGate(CFG)
        seen = [_lv(_step(gate, clock, w, **MILD)) for w in (13.0, 10.5, 10.0, 10.4, 9.6)]
        # 10.30 > 10.2 → 유지, (10.0 + 10.4 + 9.6)/3 = 10.0 → 1단계
        assert seen == [WIND_LEVEL_CLOSE] * 4 + [WIND_LEVEL_RESTRICT]

    def test_2단계_근거가_다시_서면_창을_다시_연다(self, clock):
        gate = SafetyPreGate(CFG)
        seen = [_lv(_step(gate, clock, w, **MILD))
                for w in (13.0, 9.0, 9.0, 12.5, 9.0, 9.0, 9.0)]
        assert seen == [WIND_LEVEL_CLOSE] * 6 + [WIND_LEVEL_RESTRICT]

    def test_선_뒤_20분은_평균이_낮아도_유지(self, clock):
        gate = SafetyPreGate(CFG)
        seen = [_lv(_step(gate, clock, w, **MILD)) for w in (13.0, 1.0, 1.0, 1.0)]
        assert seen == [WIND_LEVEL_CLOSE] * 3 + [WIND_LEVEL_RESTRICT]

    def test_돌풍도_평균으로(self, clock):
        gate = SafetyPreGate(CFG)
        # 내려가는 돌풍 문턱 = 18 × 0.85 = 15.3
        seen = [_lv(_step(gate, clock, 5.0, gust=g)) for g in (19.0, 15.0, 15.0, 17.0)]
        assert seen[-1] == WIND_LEVEL_CLOSE                  # (15+15+17)/3 = 15.67
        assert _lv(_step(gate, clock, 5.0, gust=13.0)) == WIND_LEVEL_RESTRICT  # 15.0

    def test_끊긴_값은_창을_비운다(self, clock):
        gate = SafetyPreGate(CFG)
        seen = [_lv(_step(gate, clock, w)) for w in (13.0, 9.0, None, 9.0, 9.0, 9.0)]
        assert seen == [WIND_LEVEL_CLOSE] * 5 + [WIND_LEVEL_RESTRICT]

    def test_짧은_주기도_20분_창(self, clock):
        gate = SafetyPreGate(CFG)
        _step(gate, clock, 13.0)
        seen = []
        for k in range(1, 21):
            w = 11.0 if k == 10 else 9.0                     # 한 번 튄 값
            seen.append(_lv(_step(gate, clock, w, dt=60.0)))
        assert seen[:19] == [WIND_LEVEL_CLOSE] * 19
        assert seen[19] == WIND_LEVEL_RESTRICT               # 20 분째

    def test_창_길이는_유지_시간과_같다(self):
        assert WIND_LEVEL_HOLD_S == 1200.0
        assert sg.WIND_WINDOW_SLACK_S < 600.0 / 2


# ─────────────────────────────────────────────────────────────────────────────
# 4. 재시작을 넘는다 + 게이트 환경 배선
# ─────────────────────────────────────────────────────────────────────────────

class TestMemoryAndPlumbing:

    def test_코디네이터_속성은_게이트의_상태를_이어_준다(self):
        c = CustomModule.__new__(CustomModule)
        assert c._wind_state is None
        c._pre_gate = SafetyPreGate(CFG)
        c._wind_state = WindState(level=2, since=1.0)
        assert c._pre_gate.wind_state.level == 2 and c._wind_state is c._pre_gate.wind_state

    def test_저장하고_복원하면_평균_창이_이어진다(self, clock):
        a = CustomModule.__new__(CustomModule)
        a._pre_gate = SafetyPreGate(CFG)
        for w in (13.0, 9.0, 9.0):
            _step(a._pre_gate, clock, w)
        blob = json.loads(json.dumps(cycle_memory.export_memory(a, clock.t)))
        assert blob['_wind_state']['level'] == WIND_LEVEL_CLOSE

        b = CustomModule.__new__(CustomModule)
        b._pre_gate = SafetyPreGate(CFG)
        assert '_wind_state' in cycle_memory.restore_memory(b, blob, clock.t + 60)
        # 재시작 직후(선 뒤 20 분이 안 됨) — 기억이 2단계를 잇는다
        assert _lv(_step(b._pre_gate, clock, 9.0, dt=60.0)) == WIND_LEVEL_CLOSE
        fresh = SafetyPreGate(CFG)                           # 기억이 없으면 2단계를 잊는다
        assert _lv(_step(fresh, clock, 9.0, dt=0.0)) == WIND_LEVEL_RESTRICT
        # 재시작 전 표본까지 평균 창에 든다 — 선 뒤 20 분째(9, 9, 9, 9)
        assert _lv(_step(b._pre_gate, clock, 9.0, dt=540.0)) == WIND_LEVEL_RESTRICT

    def test_망가진_기억에_견딘다(self, clock):
        gate = SafetyPreGate(CFG)
        gate.wind_state = WindState(level=2, since=None, samples=[['x'], [1.0], None, 'a'])
        assert _lv(_step(gate, clock, 9.0)) == WIND_LEVEL_CLOSE
        assert _lv(_step(gate, clock, 13.0)) == WIND_LEVEL_CLOSE

    def test_게이트_환경에_고온_정보가_실린다(self):
        host = types.SimpleNamespace(
            _heat_state=HeatProtectState(tier=1),
            heat_protect_enabled=True, heat_protect_threshold=31.0)
        env = HelpersMixin._build_gate_env(host, {'T': 32.5, 'T_raw': 33.0, 'RH': 40.0},
                                           {'T_ext': 30.0, 'wind': 8.0})
        assert env['heat_protect'] == {'T': 32.5, 'threshold': 31.0, 'tier': 1}

    def test_보호를_끄면_문턱도_단계도_없다(self):
        host = types.SimpleNamespace(_heat_state=HeatProtectState(tier=1),
                                     heat_protect_enabled=False)
        env = HelpersMixin._build_gate_env(host, {'T': 40.0}, {})
        assert env['heat_protect'] == {'T': 40.0, 'threshold': None, 'tier': 0}

    def test_옵션이_없으면_기본_문턱(self):
        env = HelpersMixin._build_gate_env(types.SimpleNamespace(), {'T': 25.0}, {})
        assert env['heat_protect'] == {'T': 25.0, 'threshold': 30.0, 'tier': 0}

    def test_코디네이터는_보호_설정과_같은_함수로_읽는다(self):
        """범위 밖 문턱은 보호 설정처럼 잘린다(`HP_OPTION_RANGES`) — 두 벌이 되지 않게."""
        c = CustomModule.__new__(CustomModule)
        c.heat_protect_threshold = 60.0
        c._heat_state = HeatProtectState(tier=2)
        env = c._build_gate_env({'T': 41.0}, {})
        assert env['heat_protect'] == {'T': 41.0, 'threshold': 45.0, 'tier': 2}
        assert sg._wind_hot(env['heat_protect'])
