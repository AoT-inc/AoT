# coding=utf-8
"""강풍 게이트 — 10분 평균과 돌풍으로 단계를 가르고, 내려갈 때 늦춘다 (2026-10-10, 근거 55).

폭풍 시뮬(`sim/storm.py`, PR #127)이 찾은 것:
  · 푄(10분 평균 10~12 m/s 정속 + 돌풍)에서 12 m/s 문턱을 오가며 개구부 **전부**가 한 사이클에
    닫혔다 열렸다(하루 6번) — 맑은 한낮에 실내 32 → 42 °C.
  · 풍향별 닫기는 모든 개구부에 방위각이 있어야만 섰다 — 김제 측창 둘 다 방위각이 없다.
  · 돌풍 입력이 없어 10분 평균이 문턱 아래인 동안 돌풍 > 15 m/s 에 창이 열려 있었다(84 분).

지키는 것:
  · 단계 — 1단계(평균 ≥ 0.6×문턱 또는 돌풍 ≥ 0.9×문턱): 풍상측·방위각 모르는 천창 닫음, 천창 30 %·
    측창 50 % 상한. 2단계(평균 ≥ 문턱 또는 돌풍 ≥ 1.5×문턱): 전부 닫음.
  · 돌풍은 잰 값만 — 없으면 추정하지 않는다.
  · 내려가기 — 단계가 선 뒤 최근 20 분 표본 평균이 내려가는 문턱(×0.85) 아래일 때 한 단계씩(2026-10-12,
    예전 "20 분 연속"). 올라가기는 즉시. 고온 빠른 내림은 `test_wind_fast_release.py`.
  · 규칙 A — 잃은 "강풍" 은 닫는 근거로 남고, 잃은 동안은 내려가지 않는다.
  · 고온 — 보호는 상한까지, 2단계는 보호가 못 연다.
  · 방위각 미설정은 바뀔 때만 한 번 남긴다.
"""
import logging
import types

import pytest

import aot.functions.utils.env_control.safety_gates as sg
from aot.functions.custom_functions.env_coordinator_impl._cycle_mixin import (
    CycleMixin, apply_rain_vent_caps, apply_threshold_and_gate_overrides)
from aot.functions.custom_functions.env_coordinator_impl._helpers_mixin import (
    HelpersMixin)
from aot.functions.utils.env_control.heat_protect import (
    HeatProtectDecision, apply_heat_protect_overrides)
from aot.functions.utils.env_control.log_channels import (
    GATE_BIT_EXT_EXP, GATE_BIT_RAIN_LIGHT, GATE_BIT_WIND, GATE_BIT_WIND_LIGHT,
    REASON_RAIN_RESTRICT, REASON_SAFETY_PRE_GATE, REASON_WIND_RESTRICT)
from aot.functions.utils.env_control.safety_gates import (
    WIND_LEVEL_CLOSE, WIND_LEVEL_HOLD_S, WIND_LEVEL_NONE, WIND_LEVEL_RESTRICT,
    WIND_ROOF_CAP_PCT, WIND_SIDE_CAP_PCT, PreGateConfig, SafetyPreGate,
    _merge_vent_caps, classify_wind)
from aot.functions.utils.env_control.types import ActuatorProfile

CFG = PreGateConfig(gate_ttl=0.0)
TH = CFG.wind_threshold       # 12.0


def _vent(aid, az=None, form='side'):
    return ActuatorProfile(actuator_id=aid, kind='opening', azimuth_deg=az, vent_form=form)


def _gimje():
    """김제 육묘장3 — 측창 둘, 방위각 없음."""
    return [_vent('right'), _vent('left')]


def _env(wind, gust=None, wind_dir=None, rain=0.0, T_in=30.0):
    ext = {'T': 30.0, 'RH': 20.0, 'wind': wind, 'wind_dir': wind_dir, 'rain': rain,
           'solar': 900.0}
    if gust is not None:
        ext['wind_gust'] = gust
    return {'internal': {'T': T_in, 'T_max': T_in, 'T_min': T_in, 'RH': 20.0},
            'external': ext}


class _Clock:
    def __init__(self, t=1_800_000_000.0):
        self.t = t

    def __call__(self):
        return self.t


@pytest.fixture
def clock(monkeypatch):
    c = _Clock()
    monkeypatch.setattr(sg.time, 'time', c)
    return c


# ─────────────────────────────────────────────────────────────────────────────
# 단계 판정(순수 함수)
# ─────────────────────────────────────────────────────────────────────────────

class TestClassifyWind:

    @pytest.mark.parametrize('wind,level', [
        (None, WIND_LEVEL_NONE), (0.0, WIND_LEVEL_NONE), (7.1, WIND_LEVEL_NONE),
        (7.2, WIND_LEVEL_RESTRICT), (10.0, WIND_LEVEL_RESTRICT), (11.99, WIND_LEVEL_RESTRICT),
        (12.0, WIND_LEVEL_CLOSE), (25.0, WIND_LEVEL_CLOSE),
    ])
    def test_10분_평균(self, wind, level):
        assert classify_wind(wind, None, threshold=TH) == level

    @pytest.mark.parametrize('gust,level', [
        (10.7, WIND_LEVEL_NONE), (10.8, WIND_LEVEL_RESTRICT), (17.9, WIND_LEVEL_RESTRICT),
        (18.0, WIND_LEVEL_CLOSE),
    ])
    def test_잰_돌풍(self, gust, level):
        assert classify_wind(3.0, gust, threshold=TH) == level

    def test_돌풍이_없으면_추정하지_않는다(self):
        """평균 10 m/s 에 계수 1.5 를 곱하면 15 = 2단계다 — 잰 적 없는 돌풍으로 전부 닫지 않는다."""
        assert classify_wind(10.0, None, threshold=TH) == WIND_LEVEL_RESTRICT

    def test_문턱이_전부의_기준이다(self):
        assert classify_wind(6.0, None, threshold=10.0) == WIND_LEVEL_RESTRICT
        assert classify_wind(10.0, None, threshold=10.0) == WIND_LEVEL_CLOSE
        assert classify_wind(3.0, 15.0, threshold=10.0) == WIND_LEVEL_CLOSE

    @pytest.mark.parametrize('bad', [float('nan'), float('inf'), 'x'])
    def test_이상한_값은_바람이_아니다(self, bad):
        assert classify_wind(bad, bad, threshold=TH) == WIND_LEVEL_NONE

    def test_문턱이_0_이하면_판정하지_않는다(self):
        assert classify_wind(30.0, 40.0, threshold=0.0) == WIND_LEVEL_NONE


# ─────────────────────────────────────────────────────────────────────────────
# 게이트 계획 — 1단계는 제약, 2단계는 전부 닫음
# ─────────────────────────────────────────────────────────────────────────────

class TestGatePlan:

    def test_김제_푄_10ms_는_측창을_상한까지만(self, clock):
        res = SafetyPreGate(CFG).evaluate(_env(10.0), _gimje())
        assert res.gate_mask & GATE_BIT_WIND_LIGHT and not res.gate_mask & GATE_BIT_WIND
        assert res.partial and not res.triggered
        assert res.forced_commands == {}
        assert res.vent_caps == {'right': WIND_SIDE_CAP_PCT, 'left': WIND_SIDE_CAP_PCT}
        assert res.vent_cap_reasons == {'right': REASON_WIND_RESTRICT,
                                        'left': REASON_WIND_RESTRICT}
        assert 'wind_restricted' in res.description

    def test_2단계는_전부_닫고_L1_L3_를_건너뛴다(self, clock):
        res = SafetyPreGate(CFG).evaluate(_env(12.3), _gimje())
        assert res.gate_mask & GATE_BIT_WIND and res.triggered and not res.partial
        assert {a: c['value'] for a, c in res.forced_commands.items()} == {
            'right': 0.0, 'left': 0.0}
        assert res.forced_commands['right']['reason'] == REASON_SAFETY_PRE_GATE
        assert res.vent_caps == {}

    def test_잰_돌풍_18ms_는_평균이_낮아도_2단계(self, clock):
        res = SafetyPreGate(CFG).evaluate(_env(9.0, gust=18.5), _gimje())
        assert res.gate_mask & GATE_BIT_WIND and res.triggered

    def test_방위각을_알면_풍상측만_닫는다(self, clock):
        vents = [_vent('east', 90.0), _vent('west', 270.0),
                 _vent('roof_w', 270.0, 'ridge'), _vent('roof_e', 90.0, 'ridge')]
        res = SafetyPreGate(CFG).evaluate(_env(9.0, wind_dir=80.0), vents)
        assert set(res.forced_commands) == {'east', 'roof_e'}
        assert all(c['reason'] == REASON_WIND_RESTRICT for c in res.forced_commands.values())
        assert res.vent_caps == {'west': WIND_SIDE_CAP_PCT, 'roof_w': WIND_ROOF_CAP_PCT}

    def test_방위각을_모르면_천창은_닫고_측창은_상한(self, clock):
        vents = [_vent('side'), _vent('roof', form='ridge'), _vent('unknown_form', form=None)]
        res = SafetyPreGate(CFG).evaluate(_env(9.0, wind_dir=80.0), vents)
        assert set(res.forced_commands) == {'roof', 'unknown_form'}
        assert res.vent_caps == {'side': WIND_SIDE_CAP_PCT}

    def test_비_단계_제한과_겹치면_낮은_상한(self, clock):
        """예보 비(측창 30 %)와 강풍 1단계(측창 50 %) — 측창은 30 % 비 근거."""
        env = _env(9.0, rain=1.2)
        env['external']['rain_origin'] = 'model'
        res = SafetyPreGate(CFG).evaluate(env, _gimje())
        assert res.gate_mask & GATE_BIT_RAIN_LIGHT and res.gate_mask & GATE_BIT_WIND_LIGHT
        assert res.vent_caps == {'right': 30.0, 'left': 30.0}
        assert res.vent_cap_reasons['right'] == REASON_RAIN_RESTRICT

    def test_상한_합치기(self):
        caps, why = _merge_vent_caps({'a': 30.0, 'b': None, 'c': 60.0},
                                     {'a': 50.0, 'b': 50.0, 'c': 30.0, 'd': 30.0})
        assert caps == {'a': 30.0, 'b': 50.0, 'c': 30.0, 'd': 30.0}
        assert why == {'a': REASON_RAIN_RESTRICT, 'b': REASON_WIND_RESTRICT,
                       'c': REASON_WIND_RESTRICT, 'd': REASON_WIND_RESTRICT}


# ─────────────────────────────────────────────────────────────────────────────
# 내려가기 — 여유와 시간
# ─────────────────────────────────────────────────────────────────────────────

class TestHysteresis:

    def _level(self, gate, clock, wind, gust=None, dt=600.0):
        clock.t += dt
        res = gate.evaluate(_env(wind, gust), _gimje())
        if res.gate_mask & GATE_BIT_WIND:
            return WIND_LEVEL_CLOSE
        return WIND_LEVEL_RESTRICT if res.gate_mask & GATE_BIT_WIND_LIGHT else WIND_LEVEL_NONE

    def test_푄_문턱_근처에서_오가지_않는다(self, clock):
        """시뮬 6/3 13:00~14:30 의 10분 평균 그대로 — 예전에는 0→2→2→0 이었다."""
        gate = SafetyPreGate(CFG)
        seen = [self._level(gate, clock, w) for w in
                (9.4, 9.7, 10.0, 11.0, 12.3, 12.3, 11.9, 11.0, 9.8, 10.8)]
        assert seen[:4] == [WIND_LEVEL_RESTRICT] * 4
        assert seen[4:] == [WIND_LEVEL_CLOSE] * 6, '내려가는 문턱(10.2) 아래 20 분이 안 됐다'

    def test_내려가는_문턱_아래_20분이면_한_단계(self, clock):
        gate = SafetyPreGate(CFG)
        assert self._level(gate, clock, 13.0) == WIND_LEVEL_CLOSE
        assert self._level(gate, clock, 9.0) == WIND_LEVEL_CLOSE          # 아래 시작
        assert self._level(gate, clock, 9.0) == WIND_LEVEL_CLOSE          # 10 분
        assert self._level(gate, clock, 9.0) == WIND_LEVEL_RESTRICT       # 20 분 → 1단계
        # 1단계에서 0 으로도 같은 규칙(1단계 내려가는 문턱 = 7.2×0.85 = 6.12)
        assert self._level(gate, clock, 3.0) == WIND_LEVEL_RESTRICT
        assert self._level(gate, clock, 3.0) == WIND_LEVEL_RESTRICT
        assert self._level(gate, clock, 3.0) == WIND_LEVEL_NONE

    def test_2단계에서_잔잔해져도_1단계를_거친다(self, clock):
        gate = SafetyPreGate(CFG)
        self._level(gate, clock, 13.0)
        seen = [self._level(gate, clock, 1.0) for _ in range(6)]
        assert seen == [WIND_LEVEL_CLOSE, WIND_LEVEL_CLOSE, WIND_LEVEL_RESTRICT,
                        WIND_LEVEL_RESTRICT, WIND_LEVEL_RESTRICT, WIND_LEVEL_NONE]

    def test_내려가는_문턱_위로_한_번_튀어도_시간을_다시_세지_않는다(self, clock):
        """2026-10-12 바꿈 — 예전에는 11.0 한 번에 20 분을 처음부터 다시 셌다(푄 이튿날 80 분 닫힘)."""
        gate = SafetyPreGate(CFG)
        self._level(gate, clock, 13.0)
        self._level(gate, clock, 9.0)
        self._level(gate, clock, 9.0)
        assert self._level(gate, clock, 11.0) == WIND_LEVEL_RESTRICT  # 평균 (9 + 9 + 11)/3 = 9.7

    def test_들어가는_문턱_위로_튀면_시간을_다시_센다(self, clock):
        gate = SafetyPreGate(CFG)
        self._level(gate, clock, 13.0)
        self._level(gate, clock, 9.0)
        self._level(gate, clock, 9.0)
        assert self._level(gate, clock, 12.5) == WIND_LEVEL_CLOSE     # 12 위 — 다시
        assert self._level(gate, clock, 9.0) == WIND_LEVEL_CLOSE
        assert self._level(gate, clock, 9.0) == WIND_LEVEL_CLOSE
        assert self._level(gate, clock, 9.0) == WIND_LEVEL_RESTRICT

    def test_돌풍도_내려가는_문턱_아래여야_한다(self, clock):
        gate = SafetyPreGate(CFG)
        self._level(gate, clock, 5.0, gust=19.0)
        for _ in range(4):
            assert self._level(gate, clock, 5.0, gust=16.0) == WIND_LEVEL_CLOSE  # 15.3 위

    def test_올라가기는_즉시(self, clock):
        gate = SafetyPreGate(CFG)
        assert self._level(gate, clock, 3.0) == WIND_LEVEL_NONE
        assert self._level(gate, clock, 3.0, gust=18.5, dt=60.0) == WIND_LEVEL_CLOSE

    def test_유지_시간은_한_곳(self):
        assert WIND_LEVEL_HOLD_S >= 900.0


# ─────────────────────────────────────────────────────────────────────────────
# 규칙 A — 오래된 값은 닫는 쪽으로만
# ─────────────────────────────────────────────────────────────────────────────

class TestStale:

    def test_잃은_강풍은_닫힌_채_내려가지_않는다(self, clock):
        gate = SafetyPreGate(CFG)
        gate.evaluate(_env(13.0), _gimje())
        for _ in range(6):                              # 한 시간 — 값이 없다
            clock.t += 600.0
            res = gate.evaluate(_env(None), _gimje())
            assert res.gate_mask & GATE_BIT_WIND and res.gate_mask & GATE_BIT_EXT_EXP
            assert res.triggered
        clock.t += 600.0
        res = gate.evaluate(_env(2.0), _gimje())       # 돌아온 값이 잔잔해도 바로 안 풀린다
        assert res.gate_mask & GATE_BIT_WIND

    def test_잃은_1단계는_상한과_더_열지_않음(self, clock):
        gate = SafetyPreGate(CFG)
        gate.evaluate(_env(9.0, wind_dir=90.0), [_vent('east', 90.0), _vent('west', 270.0)])
        clock.t += 3600.0
        res = gate.evaluate(_env(None), [_vent('east', 90.0), _vent('west', 270.0)])
        assert res.gate_mask & GATE_BIT_WIND_LIGHT and res.vent_open_ceiling
        # 잃은 풍향은 믿지 않는다 — 측창은 둘 다 상한(풍상측을 가리지 못함)
        assert res.forced_commands == {}
        assert res.vent_caps == {'east': WIND_SIDE_CAP_PCT, 'west': WIND_SIDE_CAP_PCT}

    def test_잃은_돌풍도_마지막_값으로_닫는다(self, clock):
        gate = SafetyPreGate(CFG)
        gate.evaluate(_env(5.0, gust=19.0), _gimje())
        clock.t += 600.0
        res = gate.evaluate(_env(5.0), _gimje())        # 돌풍 채널만 끊김
        assert res.gate_mask & GATE_BIT_WIND and res.gate_mask & GATE_BIT_EXT_EXP

    def test_돌풍_센서가_원래_없으면_제약하지_않는다(self, clock):
        res = SafetyPreGate(CFG).evaluate(_env(3.0), _gimje())
        assert not res.triggered and not res.partial and not res.vent_open_ceiling


# ─────────────────────────────────────────────────────────────────────────────
# 고온과 함께 — 보호는 상한까지, 2단계는 못 연다
# ─────────────────────────────────────────────────────────────────────────────

class TestHeatAndWind:

    def test_보호는_1단계_상한까지만_연다(self, clock):
        vents = _gimje()
        res = SafetyPreGate(CFG).evaluate(_env(10.0, T_in=36.0), vents)
        final = {p.actuator_id: {'value': 20.0, 'reason': 1} for p in vents}
        internal = {'T': 36.0, 'RH': 20.0,
                    '_heat_protect': HeatProtectDecision(
                        tier=2, vent_open_ok=True,
                        vent_open_ids=frozenset({'right', 'left'}))}
        apply_threshold_and_gate_overrides(internal, vents, final, res.forced_commands,
                                           res.vent_caps, res.vent_cap_reasons)
        for aid in ('right', 'left'):
            assert final[aid] == {'value': WIND_SIDE_CAP_PCT, 'reason': REASON_WIND_RESTRICT}

    def test_2단계는_보호가_열지_못한다(self, clock):
        vents = _gimje() + [ActuatorProfile(actuator_id='cool', kind='cooler')]
        res = SafetyPreGate(CFG).evaluate(_env(13.0, T_in=36.0), vents)
        cmds = dict(res.forced_commands)
        apply_heat_protect_overrides(
            HeatProtectDecision(tier=2, vent_open_ok=True,
                                vent_open_ids=frozenset({'right', 'left'})),
            vents, cmds, mode='direct', skip_ids=set(res.forced_commands))
        assert cmds['right']['value'] == 0.0 and cmds['left']['value'] == 0.0
        assert cmds['cool']['value'] == pytest.approx(100.0)

    def test_상한_근거는_따로_실린다(self):
        final = {'a': {'value': 80.0, 'reason': 1}, 'b': {'value': 80.0, 'reason': 1}}
        apply_rain_vent_caps(final, {'a': 50.0, 'b': 30.0}, {'a': REASON_WIND_RESTRICT})
        assert final['a'] == {'value': 50.0, 'reason': REASON_WIND_RESTRICT}
        assert final['b'] == {'value': 30.0, 'reason': REASON_RAIN_RESTRICT}   # 옛 호출자

    def test_운전_시간대_밖도_바람_근거(self):
        gr = types.SimpleNamespace(vent_caps={'right': 50.0, 'left': 50.0},
                                   vent_cap_reasons={'right': REASON_WIND_RESTRICT,
                                                     'left': REASON_WIND_RESTRICT})
        final = {'left': {'value': 90.0, 'reason': 'heat_protect'}}
        assert CycleMixin._outside_window_rain_caps(gr, final) == set()
        assert final['right'] == {'value': 0.0, 'reason': REASON_WIND_RESTRICT}
        assert final['left'] == {'value': 50.0, 'reason': REASON_WIND_RESTRICT}


# ─────────────────────────────────────────────────────────────────────────────
# PI — 강풍 상한도 coordinate() 안에서, 근거 55
# ─────────────────────────────────────────────────────────────────────────────

def test_PI_상한에_바람_근거가_실린다():
    from .test_rain_gate_grading import _vents, HUMID_NIGHT, DRY_OUTSIDE
    import time
    from aot.functions.utils.env_control.coordinator import CoordinatorState, coordinate
    from aot.functions.utils.env_control.situation import assess, compute_vpd
    from aot.functions.utils.env_control.types import TargetVar
    profiles = _vents()
    state = CoordinatorState()
    for p in profiles:
        state.integral[p.actuator_id] = 55.0
        state.prev_commands[p.actuator_id] = 55.0
    internal = dict(HUMID_NIGHT, VPD=compute_vpd(HUMID_NIGHT['T'], HUMID_NIGHT['RH']))
    for _ in range(3):
        target = {'vpd': TargetVar(value=0.46, tolerance=0.1, priority=1.2, unit='kPa')}
        report, _ = assess(target, internal, dict(DRY_OUTSIDE), cycle_sec=600.0,
                           now_ts=time.time(), last_ext_ts=time.time())
        report.context['vent_open_caps'] = {'side_s': 50.0, 'side_n': 30.0}
        report.context['vent_open_cap_reasons'] = {'side_s': REASON_WIND_RESTRICT}
        l3, state = coordinate(report, profiles, state)
    assert l3['side_s'].control_value() <= 50.0 + 1e-9
    assert l3['side_s'].reason == REASON_WIND_RESTRICT
    assert state.integral['side_s'] <= 50.0 + 1e-9
    assert l3['side_n'].reason == REASON_RAIN_RESTRICT


# ─────────────────────────────────────────────────────────────────────────────
# 기록 — 단계 변화·방위각 미설정은 바뀔 때만
# ─────────────────────────────────────────────────────────────────────────────

class _Grab(logging.Handler):
    """게이트 로거에 직접 붙는 수집기 — 다른 테스트가 전파·레벨을 바꿔도 흔들리지 않는다."""

    def __init__(self):
        super().__init__(level=logging.DEBUG)
        self.msgs = []

    def emit(self, record):
        self.msgs.append(record.getMessage())


@pytest.fixture
def grab():
    h = _Grab()
    prev_level, prev_disabled = sg.logger.level, sg.logger.disabled
    sg.logger.addHandler(h)
    sg.logger.setLevel(logging.DEBUG)
    sg.logger.disabled = False
    prev_disable = logging.root.manager.disable
    logging.disable(logging.NOTSET)
    try:
        yield h
    finally:
        sg.logger.removeHandler(h)
        sg.logger.setLevel(prev_level)
        sg.logger.disabled = prev_disabled
        logging.disable(prev_disable)


class TestLogging:

    def test_방위각_미설정은_바뀔_때만_한_번(self, clock, grab):
        gate = SafetyPreGate(CFG)
        for _ in range(3):
            clock.t += 600.0
            gate.evaluate(_env(9.0, wind_dir=80.0), _gimje())
        msgs = [m for m in grab.msgs if '방위각 미설정' in m]
        assert len(msgs) == 1
        assert msgs[0].startswith('측창 방위각 미설정 — 풍향별 닫기를 못 함')
        grab.msgs.clear()
        clock.t += 600.0
        gate.evaluate(_env(9.0, wind_dir=80.0), _gimje() + [_vent('third')])
        assert sum('방위각 미설정' in m for m in grab.msgs) == 1

    def test_방위각이_다_있으면_안_남긴다(self, clock, grab):
        SafetyPreGate(CFG).evaluate(_env(9.0, wind_dir=80.0),
                                    [_vent('e', 90.0), _vent('w', 270.0)])
        assert not any('방위각 미설정' in m for m in grab.msgs)

    def test_단계_변화를_남긴다(self, clock, grab):
        gate = SafetyPreGate(CFG)
        for w in (3.0, 9.0, 9.0, 13.0):
            clock.t += 600.0
            gate.evaluate(_env(w), _gimje())
        lv = [m for m in grab.msgs if m.startswith('강풍 단계')]
        assert len(lv) == 2
        assert lv[0].startswith('강풍 단계 0 → 1') and lv[1].startswith('강풍 단계 1 → 2')


# ─────────────────────────────────────────────────────────────────────────────
# 돌풍 배선 — 시설 실외 센서 → 실외 컨텍스트 → 게이트 환경
# ─────────────────────────────────────────────────────────────────────────────

class TestGustPlumbing:

    def test_시설_실외_센서의_돌풍은_가장_센_값(self, monkeypatch):
        import aot.space.facility_sensors as fs
        monkeypatch.setattr(fs, '_freshness_by_device', lambda ids: {})
        vals = {'g1': {'wind_gust_ms': 11.0}, 'g2': {'wind_gust_ms': 16.5},
                'wx': {'wind_ms': 8.0}}
        monkeypatch.setattr(fs, '_read_one_sensor',
                            lambda uid, mtype, max_age, **kw: dict(vals[uid]))
        out = fs.read_outdoor_sensors([
            {'input_uuid': 'g1', 'measurement_type': 'wind_gust'},
            {'input_uuid': 'g2', 'measurement_type': 'wind_gust'},
            {'input_uuid': 'wx', 'measurement_type': 'wind_speed'}], max_age=600)
        assert out['wind_gust_ms'] == 16.5 and out['wind_ms'] == 8.0
        out = fs.read_outdoor_sensors([
            {'input_uuid': 'wx', 'measurement_type': 'wind_speed'}], max_age=600)
        assert out['wind_gust_ms'] is None

    def test_채널_이름으로_돌풍을_가른다(self):
        from aot.space.facility_integration import _infer_mtype_from_dm
        dm = lambda m: types.SimpleNamespace(measurement=m)   # noqa: E731
        assert _infer_mtype_from_dm(dm('wind_gusts_10m')) == 'wind_gust'
        assert _infer_mtype_from_dm(dm('peak_wind_gust')) == 'wind_gust'
        assert _infer_mtype_from_dm(dm('gust')) == 'wind_gust'
        assert _infer_mtype_from_dm(dm('wind_speed')) == 'wind_speed'
        assert _infer_mtype_from_dm(dm('speed')) == 'wind_speed'

    def test_돌풍은_풍속과_같은_범위_검사(self):
        from aot.space import facility_sensors as fs
        res, probe = {}, {}
        fs._accept_reading(res, 'wind_gust_ms', 250.0, probe)
        assert res == {} and probe == {'wind_gust_ms': 'out_of_range'}

    def test_게이트_환경에_돌풍이_실린다(self):
        env = HelpersMixin._build_gate_env(
            types.SimpleNamespace(), {'T': 25.0, 'RH': 60.0},
            {'T_ext': 20.0, 'RH_ext': 70.0, 'wind': 8.0, 'wind_gust': 14.0})
        assert env['external']['wind_gust'] == 14.0
        env = HelpersMixin._build_gate_env(
            types.SimpleNamespace(), {'T': 25.0, 'RH': 60.0}, {'T_ext': 20.0, 'wind': 8.0})
        assert env['external']['wind_gust'] is None


# ─────────────────────────────────────────────────────────────────────────────
# 게이트 사이클에도 규칙의 기억은 나아간다 (`_gate_rule_upkeep`)
# ─────────────────────────────────────────────────────────────────────────────

class TestGateCycleKeepsRuleMemory:
    """강풍 2단계가 밤새 서면 L1~L3 가 한 번도 안 돈다 — 그 사이 스크린 광 기억(DLI·구름비·해 있음)·
    맑은 하늘 일사·일사 부하 환기의 '해 있음' 래치가 게이트가 선 시각에 굳어 있으면 풀린 첫 아침을
    낡은 값으로 판단한다(폭풍 시뮬 `foehn_dry_wind`). 판단의 결론은 게이트가 덮는다."""

    def _host(self, monkeypatch, cs=600.0):
        from .test_gate_weather_vs_heat import _Host
        import aot.functions.custom_functions.env_coordinator_impl._cycle_mixin as cm
        monkeypatch.setattr(cm, 'write_decision_log', lambda *a, **k: None)
        monkeypatch.setattr(cm, 'write_final_commands', lambda *a, **k: None)
        host = _Host(_gimje())
        host._actuator_idx = {}
        host._screen_clear_sky = lambda now: (cs, None)
        import datetime as _dt
        host._facility_local_now = lambda: _dt.datetime(2027, 6, 3, 7, 20)
        host.dusk_calls = 0

        def _dusk(internal, situation):
            host.dusk_calls += 1
            internal['_wet_fog_dusk'] = 'x'
        host._evaluate_wetting_fog_dusk = _dusk
        return host

    def test_2단계_사이클이_광_기억과_해_있음을_갱신한다(self, monkeypatch, clock):
        host = self._host(monkeypatch)
        res = SafetyPreGate(CFG).evaluate(_env(13.0), host._profiles)
        assert res.triggered
        internal = {'T': 26.0, 'RH': 60.0, 'light_est': 400.0, '_outdoor_solar': 420.0}
        for _ in range(2):
            clock.t += 600.0
            host._act_on_triggered_gate(res, _env(13.0), 600.0, clock.t, internal,
                                        {'T': 25.0, 'solar': 420.0})
        st = host._screen_state_obj()
        assert st.last_ts == clock.t and st.dli_mol > 0.0
        assert st.cloud_ratio == pytest.approx(0.7)
        assert host._clear_sky_now == 600.0
        assert host._solar_vent_state.sun_on is True
        assert host.dusk_calls == 2
        assert '_wet_fog_dusk' not in internal, '결론은 게이트 사이클 명령에 쓰지 않는다'

    def test_게이트_사이클은_게이트가_안_건드린_장치에_명령을_보내지_않는다(self, monkeypatch, clock):
        from .test_gate_weather_vs_heat import _p
        host = self._host(monkeypatch)
        host._profiles = _gimje() + [_p('fog', 'fogger')]
        host._coord_state.prev_commands = {'fog': 100.0}
        res = SafetyPreGate(CFG).evaluate(_env(13.0), host._profiles)
        host._act_on_triggered_gate(res, _env(13.0), 600.0, clock.t,
                                    {'T': 22.0, 'RH': 60.0}, {'T': 20.0})
        assert all('fog' not in cmds for cmds, _em in host.sent)

    def test_기억_갱신이_실패해도_게이트는_집행된다(self, monkeypatch, clock):
        host = self._host(monkeypatch)
        host._screen_clear_sky = lambda now: (_ for _ in ()).throw(RuntimeError('x'))
        res = SafetyPreGate(CFG).evaluate(_env(13.0), host._profiles)
        host._act_on_triggered_gate(res, _env(13.0), 600.0, clock.t,
                                    {'T': 22.0, 'RH': 60.0}, {'T': 20.0})
        assert host.sent and host.sent[0][0]['right']['value'] == 0.0
