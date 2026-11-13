# coding=utf-8
"""강우 게이트 — 출처(실측·예보 모델)와 세기로 단계를 가른다 (2026-10-10 구마모토, 근거 52).

현장: 구마모토 코디네이터 7753aa42 의 유일한 강우 근거가 Open-Meteo 예보(시간 강수
0.3~1.0 mm)였는데 강우계와 같은 대우를 받아 12~16시·17시~ **개구부 전부**가 닫혔다.
실내 29~30 °C(극한 고온 보호 1단계)였고, 게이트가 L1~L3 를 건너뛰어 그 시각의 최종
명령 기록(CH100+)도 비었다.

지키는 것:
  · 출처 판정 — 드라이버의 `data_origin`. 모르면 **실측**(엄격한 쪽).
  · 예보 강수: 약하면 천창 상한 30 %, 1.0 mm 이상이면 천창 닫음 + 측창 상한 30 %.
  · 실측 강우: 바람 없는 약한 비(< 1.0)만 천창 닫음 + 측창 상한, 나머지는 전부 닫음.
  · 규칙 A — 잃은 실측 강우는 완화 없이 닫는다.
  · 고온 — 보호는 상한까지만 쓰고, 닫힌 천창은 못 연다.
  · 게이트 사이클도 최종 명령을 남긴다.
"""
import time
import types

import pytest

import aot.functions.custom_functions.env_coordinator_impl._cycle_mixin as cycle_mod
from aot.functions.custom_functions.env_coordinator_impl._cycle_mixin import (
    CycleMixin, apply_rain_vent_caps, apply_threshold_and_gate_overrides)
from aot.functions.custom_functions.env_coordinator_impl._helpers_mixin import (
    HelpersMixin)
from aot.functions.utils.env_control.coordinator import (
    CoordinatorState, coordinate, rain_vent_caps)
from aot.functions.utils.env_control.effect_functions import build_effect_model
from aot.functions.utils.env_control.heat_protect import HeatProtectDecision
from aot.functions.utils.env_control.log_channels import (
    GATE_BIT_COLD, GATE_BIT_EXT_EXP, GATE_BIT_RAIN, GATE_BIT_RAIN_LIGHT,
    REASON_RAIN_RESTRICT, REASON_SAFETY_PRE_GATE)
from aot.functions.utils.env_control.safety_gates import (
    RAIN_LEVEL_CLOSE, RAIN_LEVEL_HOLD_ROOF, RAIN_LEVEL_NONE, RAIN_LEVEL_RESTRICT,
    RAIN_ROOF_FORECAST_CAP_PCT,
    RAIN_SIDE_CAP_PCT, PreGateConfig, SafetyPreGate, classify_rain)
from aot.functions.utils.env_control.situation import assess, compute_vpd
from aot.functions.utils.env_control.types import TargetVar

from .conftest import make_opening_profile

CFG = PreGateConfig(gate_ttl=0.0)
TH = CFG.rain_threshold        # 0.5


def _vents(roof_form='ridge'):
    roof = make_opening_profile('roof', azimuth_deg=180.0)
    roof.vent_form = roof_form
    side_s = make_opening_profile('side_s', azimuth_deg=180.0)
    side_s.vent_form = 'side'
    side_n = make_opening_profile('side_n', azimuth_deg=0.0)
    side_n.vent_form = 'side'
    for p in (roof, side_s, side_n):
        p.effect_model = build_effect_model('opening', {})
    return [roof, side_s, side_n]


def _env(rain, origin=None, wind=1.0, wind_dir=None, T_in=29.5):
    ext = {'T': 24.0, 'RH': 70.0, 'rain': rain, 'wind': wind, 'wind_dir': wind_dir,
           'solar': 300.0}
    if origin is not None:
        ext['rain_origin'] = origin
    return {'internal': {'T': T_in, 'T_max': T_in, 'T_min': T_in, 'RH': 70.0},
            'external': ext}


# ─────────────────────────────────────────────────────────────────────────────
# 단계 판정(순수 함수)
# ─────────────────────────────────────────────────────────────────────────────

class TestClassifyRain:

    @pytest.mark.parametrize('rain,level', [
        (None, RAIN_LEVEL_NONE), (0.0, RAIN_LEVEL_NONE), (0.05, RAIN_LEVEL_NONE),
        (0.1, RAIN_LEVEL_HOLD_ROOF), (0.6, RAIN_LEVEL_HOLD_ROOF),
        (0.99, RAIN_LEVEL_HOLD_ROOF), (1.0, RAIN_LEVEL_RESTRICT),
        (8.0, RAIN_LEVEL_RESTRICT),
    ])
    def test_예보_강수는_전부_닫지_않는다(self, rain, level):
        assert classify_rain(rain, 'model', 1.0, threshold=TH) == level

    def test_예보_닫힘_문턱은_사용자_문턱보다_낮아지지_않는다(self):
        assert classify_rain(1.5, 'model', 1.0, threshold=2.0) == RAIN_LEVEL_HOLD_ROOF
        assert classify_rain(2.0, 'model', 1.0, threshold=2.0) == RAIN_LEVEL_RESTRICT

    def test_예보는_바람이_있어도_단계_제한이다(self):
        """강풍은 바람 게이트가 따로 닫는다 — 예보 강수 자체로는 전면 폐쇄가 없다."""
        assert classify_rain(3.0, 'model', 8.0, threshold=TH) == RAIN_LEVEL_RESTRICT

    def test_실측_문턱_아래는_제한_없음(self):
        assert classify_rain(0.3, 'measured', 0.5, threshold=TH) == RAIN_LEVEL_NONE

    def test_실측_바람_없는_약한_비는_단계_제한(self):
        assert classify_rain(0.6, 'measured', 1.0, threshold=TH) == RAIN_LEVEL_RESTRICT

    @pytest.mark.parametrize('rain,wind', [
        (0.6, 2.0),     # 바람
        (0.6, None),    # 풍속 센서 없음 — 모르는 바람으로 완화하지 않는다
        (1.0, 0.5),     # 감우기(0/1)의 1 — 약한 비가 아니다
        (6.0, 0.0),     # 강한 비
    ])
    def test_실측_그_밖은_전부_닫는다(self, rain, wind):
        assert classify_rain(rain, 'measured', wind, threshold=TH) == RAIN_LEVEL_CLOSE

    def test_출처를_모르면_실측(self):
        assert classify_rain(0.6, None, 3.0, threshold=TH) == RAIN_LEVEL_CLOSE
        assert classify_rain(0.6, 'weird', 3.0, threshold=TH) == RAIN_LEVEL_CLOSE

    def test_규칙A_잃은_실측은_완화하지_않는다(self):
        assert classify_rain(0.6, 'measured', 1.0, threshold=TH,
                             rain_lost=True) == RAIN_LEVEL_CLOSE
        assert classify_rain(0.6, 'measured', 1.0, threshold=TH,
                             wind_lost=True) == RAIN_LEVEL_CLOSE

    def test_이상한_값은_비가_아니다(self):
        assert classify_rain(float('nan'), 'measured', 1.0, threshold=TH) == RAIN_LEVEL_NONE
        assert classify_rain('x', 'measured', 1.0, threshold=TH) == RAIN_LEVEL_NONE


# ─────────────────────────────────────────────────────────────────────────────
# 게이트 — 천창·측창·상한
# ─────────────────────────────────────────────────────────────────────────────

class TestGatePlan:

    def test_구마모토_예보_0_6mm_천창만_30_상한(self):
        # 예전에는 "더 열지 않음"(None)이라 65 % 로 열려 있던 천창이 예보 비 내내 그대로였다.
        res = SafetyPreGate(CFG).evaluate(_env(0.6, 'model'), _vents())
        assert not res.triggered and res.partial
        assert res.gate_mask == GATE_BIT_RAIN_LIGHT
        assert res.forced_commands == {}
        assert res.vent_caps == {'roof': RAIN_ROOF_FORECAST_CAP_PCT} == {'roof': 30.0}
        assert 'rain_hold' in res.description

    def test_예보_약한_비_열려_있던_천창은_30_으로_닫힌다(self):
        ctx = {'vent_open_caps': {'roof': RAIN_ROOF_FORECAST_CAP_PCT}}
        assert rain_vent_caps(ctx, _vents()) == {'roof': 30.0}
        final = {'roof': {'value': 65.0, 'reason': 1}}
        apply_rain_vent_caps(final, ctx['vent_open_caps'])
        assert final['roof']['value'] == 30.0

    def test_예보_1mm_천창_닫고_측창_상한(self):
        res = SafetyPreGate(CFG).evaluate(_env(1.0, 'model'), _vents())
        assert not res.triggered and res.partial
        assert res.forced_commands == {
            'roof': {'value': 0.0, 'reason': REASON_RAIN_RESTRICT, 'ttl': 300.0}}
        assert res.vent_caps == {'side_s': RAIN_SIDE_CAP_PCT, 'side_n': RAIN_SIDE_CAP_PCT}

    def test_형태를_모르는_개구부는_천창으로_본다(self):
        res = SafetyPreGate(CFG).evaluate(_env(1.0, 'model'), _vents(roof_form=None))
        assert res.forced_commands['roof']['value'] == 0.0

    def test_예보_비_바람이_있으면_풍상측_측창은_닫는다(self):
        # 남풍(180°) 5 m/s — 남쪽 측창이 풍상측
        res = SafetyPreGate(CFG).evaluate(
            _env(1.0, 'model', wind=5.0, wind_dir=180.0), _vents())
        assert res.forced_commands['side_s']['value'] == 0.0
        assert res.vent_caps == {'side_n': RAIN_SIDE_CAP_PCT}

    def test_실측_약한_비_바람_없음(self):
        res = SafetyPreGate(CFG).evaluate(_env(0.6, 'measured', wind=1.0), _vents())
        assert not res.triggered
        assert res.forced_commands['roof']['reason'] == REASON_RAIN_RESTRICT
        assert set(res.vent_caps) == {'side_s', 'side_n'}

    def test_실측_비_바람이면_예전대로_전부_닫는다(self):
        res = SafetyPreGate(CFG).evaluate(_env(0.6, 'measured', wind=3.0), _vents())
        assert res.triggered and res.gate_mask & GATE_BIT_RAIN
        assert {a: c['value'] for a, c in res.forced_commands.items()} == {
            'roof': 0.0, 'side_s': 0.0, 'side_n': 0.0}
        assert all(c['reason'] == REASON_SAFETY_PRE_GATE
                   for c in res.forced_commands.values())
        assert res.vent_caps == {}

    def test_출처_표식이_없으면_예전과_같다(self):
        """수집기·시설 센서가 출처를 싣지 않던 설치 — 실측으로 본다."""
        res = SafetyPreGate(CFG).evaluate(_env(0.6, None, wind=3.0), _vents())
        assert res.triggered and res.gate_mask & GATE_BIT_RAIN

    def test_한파가_서면_상한_대신_전부_닫는다(self):
        env = _env(1.0, 'model', T_in=2.0)
        env['external']['T'] = -8.0
        res = SafetyPreGate(CFG).evaluate(env, _vents())
        assert res.gate_mask & GATE_BIT_COLD
        assert res.vent_caps == {}
        assert all(c['value'] == 0.0 for c in res.forced_commands.values())

    def test_단계_제한은_TTL_전체_홀드를_잡지_않는다(self):
        gate = SafetyPreGate(PreGateConfig())         # gate_ttl 300
        gate.evaluate(_env(1.0, 'model'), _vents())
        assert gate._triggered_until == 0.0
        res = gate.evaluate(_env(0.0, 'model'), _vents())
        assert not res.triggered, '비가 그친 뒤 L1~L3 를 멈추면 안 된다'


# ─────────────────────────────────────────────────────────────────────────────
# 오래된 강우(규칙 A)·유지
# ─────────────────────────────────────────────────────────────────────────────

class TestStaleAndLatch:

    def test_잃은_실측_약한_비는_전부_닫는다(self):
        gate = SafetyPreGate(CFG)
        assert not gate.evaluate(_env(0.6, 'measured', wind=1.0), _vents()).triggered
        res = gate.evaluate(_env(None, None, wind=1.0), _vents())
        assert res.triggered and res.gate_mask & GATE_BIT_RAIN
        assert res.gate_mask & GATE_BIT_EXT_EXP

    def test_잃은_예보는_같은_예보_규칙으로_묶고_더_열지_않음을_건다(self):
        gate = SafetyPreGate(CFG)
        gate.evaluate(_env(1.0, 'model'), _vents())
        res = gate.evaluate(_env(None, None), _vents())
        assert not res.triggered
        assert res.gate_mask & GATE_BIT_EXT_EXP and res.vent_open_ceiling
        assert res.forced_commands['roof']['value'] == 0.0
        assert set(res.vent_caps) == {'side_s', 'side_n'}

    def test_단계는_유지_시간_동안_내려가지_않는다(self):
        gate = SafetyPreGate(PreGateConfig(gate_ttl=300.0))
        gate.evaluate(_env(1.0, 'model'), _vents())
        res = gate.evaluate(_env(0.9, 'model'), _vents())
        assert 'rain_restricted' in res.description, '1.0 ↔ 0.9 로 창이 오가면 안 된다'
        assert gate._rain_hold[1] - time.time() > 1700.0, '주기 600초보다 길어야 유지가 된다'
        gate._rain_hold = (gate._rain_hold[0], time.time() - 1.0)   # 유지 만료
        res = gate.evaluate(_env(0.9, 'model'), _vents())
        assert 'rain_hold' in res.description
        gate._rain_hold = (gate._rain_hold[0], time.time() - 1.0)
        res = gate.evaluate(_env(0.0, 'model'), _vents())
        assert res.gate_mask == 0 and not res.vent_caps


# ─────────────────────────────────────────────────────────────────────────────
# 출처 판정 — 드라이버의 data_origin
# ─────────────────────────────────────────────────────────────────────────────

class TestSourceClassification:

    def test_예보_드라이버가_표식을_단다(self):
        import importlib
        for mod, name in (('open_meteo_weather', 'OPEN_METEO_FORECAST'),
                          ('kma_weather_forecast', 'KMA_forecast'),
                          ('nasa_power', 'NASA_POWER_DAILY')):
            info = importlib.import_module('aot.inputs.' + mod).INPUT_INFORMATION
            assert info['input_name_unique'] == name
            assert info.get('data_origin') == 'model', name
        # 실측 기상대는 표식이 없다
        info = importlib.import_module('aot.inputs.kma_weather_500').INPUT_INFORMATION
        assert info.get('data_origin') is None

    def test_전부_모델일_때만_model(self, monkeypatch):
        import aot.utils.inputs as ui
        from aot.utils.inputs import rain_origin_of
        monkeypatch.setattr(ui, 'model_origin_device_ids', lambda ids: {'om'})
        assert rain_origin_of(['om']) == 'model'
        assert rain_origin_of(['om', 'gauge']) == 'measured'
        assert rain_origin_of([]) == 'measured'

    def test_판정_실패는_실측(self, monkeypatch):
        import aot.utils.inputs as ui
        from aot.utils.inputs import rain_origin_of

        def boom(ids):
            raise RuntimeError('db')
        monkeypatch.setattr(ui, 'model_origin_device_ids', boom)
        assert rain_origin_of(['om']) == 'measured'

    def test_model_origin_device_ids_는_드라이버로_가른다(self, monkeypatch):
        import aot.utils.database as udb
        import aot.utils.inputs as ui
        monkeypatch.setattr(ui, 'model_input_drivers',
                            lambda: frozenset({'OPEN_METEO_FORECAST'}))
        rows = [types.SimpleNamespace(unique_id='om', device='OPEN_METEO_FORECAST'),
                types.SimpleNamespace(unique_id='wx', device='KMA_weather_500')]

        class _T:
            def filter(self, *_a):
                return self

            def all(self):
                return rows
        monkeypatch.setattr(udb, 'db_retrieve_table_daemon', lambda model: _T())
        assert ui.model_origin_device_ids(['om', 'wx']) == {'om'}
        assert ui.model_origin_device_ids([]) == set()

    def test_시설_센서_강우에_출처가_실린다(self, monkeypatch):
        import aot.space.facility_sensors as fs
        import aot.utils.inputs as ui
        monkeypatch.setattr(fs, '_freshness_by_device', lambda ids: {})
        monkeypatch.setattr(fs, '_read_one_sensor',
                            lambda uid, mtype, max_age, **kw:
                            {'rain_mm': 0.6} if mtype == 'rain' else {'T': 25.0})
        monkeypatch.setattr(ui, 'model_origin_device_ids', lambda ids: {'om'})
        out = fs.read_outdoor_sensors([
            {'input_uuid': 'om', 'measurement_type': 'rain'},
            {'input_uuid': 'wx', 'measurement_type': 'temperature'}], max_age=600)
        assert out['rain_mm'] == 0.6 and out['rain_origin'] == 'model'
        # 메인에 실측 강우계가 있으면 그쪽만 쓰고 출처도 실측
        out = fs.read_outdoor_sensors([
            {'input_uuid': 'om', 'measurement_type': 'rain', 'sensor_priority': 'backup'},
            {'input_uuid': 'gauge', 'measurement_type': 'rain'}], max_age=600)
        assert out['rain_origin'] == 'measured'
        out = fs.read_outdoor_sensors([
            {'input_uuid': 'wx', 'measurement_type': 'temperature'}], max_age=600)
        assert out['rain_origin'] is None

    def test_게이트_환경에_출처가_실린다(self):
        env = HelpersMixin._build_gate_env(
            types.SimpleNamespace(), {'T': 25.0, 'RH': 60.0},
            {'T_ext': 20.0, 'RH_ext': 70.0, 'rain': 0.6, 'rain_origin': 'model'})
        assert env['external']['rain_origin'] == 'model'


# ─────────────────────────────────────────────────────────────────────────────
# PI — 상한은 coordinate() 안에서 적분과 함께
# ─────────────────────────────────────────────────────────────────────────────

HUMID_NIGHT = {'T': 22.8, 'RH': 86.0}          # 마른 실외면 창을 열고 싶어진다
DRY_OUTSIDE = {'T': 30.0, 'RH': 45.0, 'T_ext': 30.0, 'RH_ext': 45.0,
               'wind': 1.0, 'rain': 0.0}


def _pi(caps, start=55.0, internal_extra=None, cycles=1):
    profiles = _vents()
    state = CoordinatorState()
    for p in profiles:
        state.integral[p.actuator_id] = start
        state.prev_commands[p.actuator_id] = start
    internal = dict(HUMID_NIGHT, VPD=compute_vpd(HUMID_NIGHT['T'], HUMID_NIGHT['RH']))
    internal.update(internal_extra or {})
    l3 = None
    for _ in range(cycles):
        target = {'vpd': TargetVar(value=0.46, tolerance=0.1, priority=1.2, unit='kPa')}
        report, _ = assess(target, internal, dict(DRY_OUTSIDE), cycle_sec=600.0,
                           now_ts=time.time(), last_ext_ts=time.time())
        report.context['vent_open_caps'] = dict(caps)
        l3, state = coordinate(report, profiles, state)
    return l3, state


class TestPiCaps:

    def test_기준_상한이_없으면_연다(self):
        l3, _ = _pi({})
        assert l3['side_s'].control_value() > 55.0

    def test_측창_상한_아래로_내리고_적분도_묶는다(self):
        l3, st = _pi({'side_s': 30.0}, cycles=4)
        assert l3['side_s'].reason == REASON_RAIN_RESTRICT
        assert l3['side_s'].control_value() <= 30.0 + 1e-9
        assert st.integral['side_s'] <= 30.0 + 1e-9

    def test_천창_더_열지_않음(self):
        l3, st = _pi({'roof': None})
        assert l3['roof'].reason == REASON_RAIN_RESTRICT
        assert l3['roof'].control_value() == pytest.approx(55.0)
        assert st.integral['roof'] <= 55.0 + 1e-9
        assert l3['side_s'].control_value() > 55.0, '측창은 그대로'

    def test_고온이면_더_열지_않음은_풀리고_숫자_상한은_남는다(self):
        caps = {'roof': None, 'side_s': 30.0}
        ctx = {'vent_open_caps': caps, 'internal': {'_force_cool': True}}
        assert rain_vent_caps(ctx, _vents()) == {'side_s': 30.0}
        ctx = {'vent_open_caps': caps,
               'heat_protect': types.SimpleNamespace(active=True, tier=2)}
        assert rain_vent_caps(ctx, _vents()) == {'side_s': 30.0}
        assert rain_vent_caps({'vent_open_caps': caps}, _vents()) == caps

    def test_보호_단계1_에서는_천창을_계속_묶는다(self):
        """구마모토 리플레이: 단계 1 에 풀었더니 예보 비 0.7 mm 에 천창이 100 % 까지 갔다.
        단계 1 에서 열 창은 측창이다."""
        caps = {'roof': None, 'side_s': 30.0}
        ctx = {'vent_open_caps': caps,
               'heat_protect': types.SimpleNamespace(active=True, tier=1)}
        assert rain_vent_caps(ctx, _vents()) == caps


# ─────────────────────────────────────────────────────────────────────────────
# 고온과 함께 — 보호는 상한까지, 닫힌 천창은 못 연다
# ─────────────────────────────────────────────────────────────────────────────

class TestHeatAndRain:

    def test_보호_단계2도_측창_상한을_넘지_못하고_천창을_못_연다(self):
        profiles = _vents()
        res = SafetyPreGate(CFG).evaluate(_env(1.0, 'model', T_in=36.0), profiles)
        final = {p.actuator_id: {'value': 10.0, 'reason': 1} for p in profiles}
        internal = {'T': 36.0, 'RH': 50.0,
                    '_heat_protect': HeatProtectDecision(
                        tier=2, vent_open_ok=True,
                        vent_open_ids=frozenset({'roof', 'side_s', 'side_n'}))}
        apply_threshold_and_gate_overrides(internal, profiles, final,
                                           res.forced_commands, res.vent_caps)
        assert final['roof'] == {'value': 0.0, 'reason': REASON_RAIN_RESTRICT,
                                 'ttl': 300.0}
        for aid in ('side_s', 'side_n'):
            assert final[aid] == {'value': RAIN_SIDE_CAP_PCT,
                                  'reason': REASON_RAIN_RESTRICT}

    def test_상한_아래_명령은_건드리지_않는다(self):
        final = {'side_s': {'value': 12.0, 'reason': 1}}
        apply_rain_vent_caps(final, {'side_s': 30.0, 'roof': None})
        assert final == {'side_s': {'value': 12.0, 'reason': 1}}


# ─────────────────────────────────────────────────────────────────────────────
# 운전 시간대 밖 · 게이트 사이클 기록
# ─────────────────────────────────────────────────────────────────────────────

def test_운전_시간대_밖_상한은_명령이_없으면_닫고_더_열지_않음은_제자리():
    gr = types.SimpleNamespace(vent_caps={'side_s': 30.0, 'side_n': 30.0, 'roof': None})
    final = {'side_n': {'value': 80.0, 'reason': 'heat_protect'}}
    hold = CycleMixin._outside_window_rain_caps(gr, final)
    assert hold == {'roof'}
    assert final['side_s'] == {'value': 0.0, 'reason': REASON_RAIN_RESTRICT}
    assert final['side_n'] == {'value': 30.0, 'reason': REASON_RAIN_RESTRICT}


def test_게이트_사이클도_최종_명령을_남긴다(monkeypatch):
    from .test_gate_weather_vs_heat import _Host
    monkeypatch.setattr(cycle_mod, 'write_decision_log', lambda *a, **k: None)
    written = {}
    monkeypatch.setattr(cycle_mod, 'write_final_commands',
                        lambda uid, cmds, idx: written.update(cmds))
    profiles = _vents() + [make_opening_profile('never')]
    host = _Host(profiles)
    host._actuator_idx = {p.actuator_id: i for i, p in enumerate(profiles)}
    host._coord_state.prev_commands = {'roof': 40.0, 'side_s': 20.0, 'side_n': 20.0}
    res = SafetyPreGate(CFG).evaluate(_env(6.0, 'measured', T_in=25.0), profiles)
    assert res.triggered
    host._act_on_triggered_gate(res, _env(6.0, 'measured', T_in=25.0), 600.0, 0.0,
                                {'T': 25.0, 'RH': 70.0}, {'T': 24.0})
    assert written['roof']['value'] == 0.0
    assert written['roof']['reason'] == REASON_SAFETY_PRE_GATE
    assert written['never']['value'] == 0.0           # 게이트가 닫은 창
    assert set(written) == {'roof', 'side_s', 'side_n', 'never'}


def test_게이트가_안_건드린_장치는_직전_값으로_남긴다(monkeypatch):
    from .test_gate_weather_vs_heat import _Host
    written = {}
    monkeypatch.setattr(cycle_mod, 'write_final_commands',
                        lambda uid, cmds, idx: written.update(cmds))
    host = _Host(_vents())
    host._actuator_idx = {'roof': 0}
    host._coord_state.prev_commands = {'roof': 40.0}
    host._write_gate_final_commands(types.SimpleNamespace(forced_commands={}), {})
    assert written == {'roof': {'value': 40.0, 'reason': REASON_SAFETY_PRE_GATE}}


@pytest.mark.parametrize('model_ids,origin', [({'om'}, 'model'), (set(), 'measured')])
def test_수집기도_강우_출처를_싣는다(monkeypatch, model_ids, origin):
    import logging
    import aot.functions.ext_context_collector as ecc
    import aot.utils.inputs as ui
    monkeypatch.setattr(ecc, 'write_influxdb_value', lambda *a, **k: None)
    monkeypatch.setattr(ecc._freshness, 'freshness_by_device', lambda ids: {})
    monkeypatch.setattr(ecc, '_shared_context', {})
    monkeypatch.setattr(ecc, '_shared_context_ts', 0.0)
    monkeypatch.setattr(ui, 'model_origin_device_ids', lambda ids: set(model_ids))
    f = ecc.CustomFunction.__new__(ecc.CustomFunction)
    f.logger, f.unique_id = logging.getLogger('test.collector'), 'collector'
    f.update_period, f.sensor_max_age = 60.0, 0.0
    f.sensor_temperature, f.sensor_humidity = 'om,t', 'om,rh'
    f.sensor_rain, f.sensor_wind = 'om,rain', None
    f.sensor_solar = f.sensor_dewpoint = f.sensor_co2 = None
    vals = {'t': 25.0, 'rh': 70.0, 'rain': 0.6}
    now = time.time()
    f.get_last_measurement = lambda d, m, max_age=None: [now - 30, vals[m]]
    f._collect_and_publish()
    assert ecc.get_shared_context()['rain_origin'] == origin


def test_예보_드라이버_판정은_요청_밖에서도_돈다(monkeypatch):
    """앱 컨텍스트만 있고 요청이 없으면 `lazy_gettext` 가 로캘을 찾다 터진다 — 그때 빈
    집합이면 예보 강수가 조용히 실측으로 돌아간다(리플레이에서 실제로 그랬다)."""
    import aot.utils.inputs as ui
    calls = []

    def parse():
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError('Working outside of request context.')
        return {'OPEN_METEO_FORECAST': {'data_origin': 'model'}, 'X': {}}
    monkeypatch.setattr(ui, 'parse_input_information', parse)
    monkeypatch.setattr(ui, '_MODEL_DRIVERS', None)
    assert ui.model_input_drivers() == frozenset({'OPEN_METEO_FORECAST'})
