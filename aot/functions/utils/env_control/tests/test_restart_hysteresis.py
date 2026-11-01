# coding=utf-8
"""재시작 직후 첫 사이클 — 이력 띠를 '밖' 으로 읽던 기억 다섯 가지 (2026-10-13, #170 의 후속).

#170 은 일사·스크린·고온 보호·온도 상한 항·강우 마지막 실측을 `cycle_memory` 로 재시작 너머로 넘겼다. 같은 모양으로
**프로세스 메모리에만 있던** 이력이 더 있었다. 모두 '들어갈 때 문턱과 나올 때 문턱이 다른' 이력이라, 띠 안의 값은
재시작 전과 재시작 직후가 정반대로 읽힌다.

  1. `CoordinatorState.humid_zone`  과습 구간 — 들어가는 문턱(VPD 0.30 · 여유 2 °C)이 나오는 문턱(0.40 · 3 °C)보다 낮다.
     띠 안(RH 88 %/22 °C: VPD 0.32 · 여유 2.6 °C)의 집이 재시작 직후 '구간 밖' 으로 읽혀, 실외가 더 습해도 닫지 않고
     (근거 24) 열림 상한 30 % 도 풀린 채 PI 가 100 % 까지 열었다.
  2. `CoordinatorState.purge`  아침 습기 빼기 — 켜짐·직전 실내 온도·평활한 변화율. 재시작 직후는 켬 문턱(더 엄격)과
     '오르는 중인지 모름' 으로 읽혀 5~15 % 하한이 사라졌다.
  3. `SafetyPreGate._rain_hold`  강우 단계 유지 — (단계, 만료 시각). 예보 0.9/1.0 경계에서 천창이 사이클마다 오가지
     않게 붙드는 30 분 시한. 재시작이 지우면 유지 중이던 제한이 풀린 채 출발한다(만료 시각은 벽시계라 뜻이 그대로다).
  4. `rain_seen`  비를 보던 실측 강우계가 끊긴 채 재시작하면 예보 모델이 강우를 넘겨받아, 게이트의 실측 래치(규칙 A)를
     지운다. 비어 있는 기억은 '마지막 실측이 0' 과 같다.
  5. `SafetyPreGate._cold_latched`  한파 비상 래치(들어갈 때 문턱, 나올 때 +2 °C) — 띠 안에서 전면 폐쇄가 한 사이클 풀린다.
  6. `SafetyPreGate._nursery_locked`  육묘 일소 분무 잠금(250 켬 · 150 끔) — 띠 안에서 습윤 분무가 한 사이클 풀린다.
  7. `_gate_held_positions`  전체 게이트가 닫아 둔 장치의 위치 — 잃으면 해제되는 첫 사이클에 적분이 게이트 전 평형 개도로
     남아 그 개도로 돌아가려 한다. 복원은 지금 등록된 장치만 남긴다.

정본은 `env_control/cycle_memory.py`. 각 수정을 끄면 이 파일의 해당 시험이 실패한다.
"""
import copy
import json
from types import SimpleNamespace

import pytest

from aot.functions.custom_functions.env_coordinator_impl import _runtime_state_mixin as RSM
from aot.functions.utils.env_control import cycle_memory as CM
from aot.functions.utils.env_control import humid_regime as HR
from aot.functions.utils.env_control import log_channels as LC
from aot.functions.utils.env_control.coordinator import CoordinatorState
from aot.functions.utils.env_control.log_channels import GATE_BIT_COLD
from aot.functions.utils.env_control.safety_gates import (
    RAIN_LEVEL_CLOSE, RAIN_LEVEL_HOLD_ROOF, RAIN_LEVEL_NONE, RAIN_LEVEL_RESTRICT,
    PreGateConfig, SafetyPreGate,
)

from .test_cycle_memory import T_FIRST, T_SAVE, _coord, _restart, runtime_db  # noqa: F401
from .test_morning_purge import T_LOW, _cctx, _p, _run
from .test_outdoor_rain_merge import _GAUGE_FC, env  # noqa: F401 (fixture)
from .test_rain_gate_grading import _env as _rain_env, _vents

CFG = PreGateConfig(gate_ttl=0.0)


def _save(c, monkeypatch, at=T_SAVE):
    monkeypatch.setattr(RSM.time, 'time', lambda: at)
    c._save_runtime_state()


def _with_gate(c):
    c._pre_gate = SafetyPreGate(CFG)
    return c._pre_gate


def _restart_with_gate(monkeypatch, now):
    """새 프로세스 — 게이트가 먼저 있고(`initialize` 가 그렇게 한다), 저장된 행에서 되살린다."""
    monkeypatch.setattr(RSM.time, 'time', lambda: now)
    c = _coord()
    _with_gate(c)
    c._load_runtime_state()
    return c


def _roundtrip(owner, **kw):
    return json.loads(json.dumps(CM.export_memory(owner, kw.get('now', T_SAVE))))


# ─────────────────────────────────────────────────────────────────────────────
# 1. 과습 구간 이력
# ─────────────────────────────────────────────────────────────────────────────

_T = 22.0
# 들어가는 문턱은 넘었고 나오는 문턱은 아직 못 넘은 습도 — 이력 띠 안.
_RH_BAND = next(r for r in range(99, 50, -1)
                if HR.vpd_kpa(_T, r) >= HR.ENTER_VPD_KPA
                and (_T - HR.dewpoint_c(_T, r)) >= HR.ENTER_MARGIN_C
                and (HR.vpd_kpa(_T, r) < HR.EXIT_VPD_KPA
                     or (_T - HR.dewpoint_c(_T, r)) < HR.EXIT_MARGIN_C))


def _band(**kw):
    """띠 안의 한 사이클 — 실외가 더 덥고 더 습하다(창으로 해소 불가: 근거 24, 닫는 쪽)."""
    return _cctx(T_int=_T, RH_int=float(_RH_BAND), T_ext=24.0, RH_ext=90.0, **kw)


def _in_zone_state():
    """과습 구간에 들어가 있던 집의 사이클 끝 상태."""
    st = CoordinatorState()
    _, st = _run([_p('v')], _cctx(T_int=21.6, RH_int=96.0, T_ext=24.0, RH_ext=90.0),
                 cycles=2, state=st)
    assert st.humid_zone
    return st


class TestHumidZoneSurvivesRestart:

    def test_the_premise_the_band_reads_opposite_ways(self):
        assert HR.in_overhumid_zone(_T, _RH_BAND, was_in=True)
        assert not HR.in_overhumid_zone(_T, _RH_BAND, was_in=False)

    def test_the_premise_a_forgotten_zone_opens_the_window_all_the_way(self):
        """결함 — 같은 입력에 이력이 있으면 닫혀 있고(근거 24), 없으면 PI 가 연다."""
        kept = _in_zone_state()
        cmds, _ = _run([_p('v')], _band(), prev=0.0, cycles=1, state=copy.deepcopy(kept))
        assert cmds['v'].control_value() == pytest.approx(0.0)
        assert cmds['v'].reason == LC.REASON_HUMID_NO_RELIEF

        lost = CoordinatorState()
        cmds, _ = _run([_p('v')], _band(), prev=0.0, cycles=1, state=lost)
        assert cmds['v'].control_value() > 50.0
        assert cmds['v'].reason != LC.REASON_HUMID_NO_RELIEF

    def test_the_restored_first_cycle_equals_the_cycle_without_a_restart(
            self, runtime_db, monkeypatch):  # noqa: F811
        straight, _ = _run([_p('v')], _band(), prev=0.0, cycles=1,
                           state=copy.deepcopy(_in_zone_state()))

        before = _coord()
        before._coord_state = _in_zone_state()
        _save(before, monkeypatch)
        after = _restart(monkeypatch, T_FIRST)
        assert after._coord_state.humid_zone is True
        cmds, _ = _run([_p('v')], _band(), prev=0.0, cycles=1, state=after._coord_state)
        assert cmds['v'].control_value() == pytest.approx(straight['v'].control_value())
        assert cmds['v'].reason == straight['v'].reason == LC.REASON_HUMID_NO_RELIEF

    def test_a_house_outside_the_zone_stays_outside(self, runtime_db, monkeypatch):  # noqa: F811
        before = _coord()
        before._coord_state = CoordinatorState()
        _save(before, monkeypatch)
        assert _restart(monkeypatch, T_FIRST)._coord_state.humid_zone is False

    def test_a_stale_memory_is_dropped(self, runtime_db, monkeypatch):  # noqa: F811
        before = _coord()
        before._coord_state = _in_zone_state()
        _save(before, monkeypatch)
        late = _restart(monkeypatch, T_SAVE + CM.MEMORY_MAX_AGE_S + 60.0)
        assert late._coord_state.humid_zone is False


# ─────────────────────────────────────────────────────────────────────────────
# 2. 아침 습기 빼기 이력
# ─────────────────────────────────────────────────────────────────────────────

def _purging_state():
    """하한 아래 2 °C 에서 오르며 습기를 빼고 있던 집 — 오르는 중이라 '켜진 뒤' 문턱(추세 0)으로 이어 간다."""
    st = CoordinatorState()
    for T in (T_LOW - 2.4, T_LOW - 2.0, T_LOW - 1.6):
        _, st = _run([_p('v')], _cctx(T_int=T), cycles=1, state=st)
    assert st.purge.on and st.purge.dT_h is not None
    return st


class TestPurgeStateSurvivesRestart:

    def test_the_premise_a_forgotten_purge_closes_the_window_for_a_cycle(self):
        nxt = _cctx(T_int=T_LOW - 1.2)
        kept, _ = _run([_p('v')], nxt, prev=5.0, cycles=1, state=copy.deepcopy(_purging_state()))
        assert kept['v'].reason == LC.REASON_MORNING_PURGE

        fresh = CoordinatorState()
        lost, _ = _run([_p('v')], nxt, prev=5.0, cycles=1, state=fresh)
        assert lost['v'].reason != LC.REASON_MORNING_PURGE

    def test_the_restored_first_cycle_equals_the_cycle_without_a_restart(
            self, runtime_db, monkeypatch):  # noqa: F811
        nxt = _cctx(T_int=T_LOW - 1.2)
        straight, st_s = _run([_p('v')], nxt, prev=5.0, cycles=1,
                              state=copy.deepcopy(_purging_state()))

        before = _coord()
        before._coord_state = _purging_state()
        _save(before, monkeypatch)
        after = _restart(monkeypatch, T_FIRST)
        assert after._coord_state.purge == before._coord_state.purge
        cmds, st_r = _run([_p('v')], nxt, prev=5.0, cycles=1, state=after._coord_state)
        assert cmds['v'].reason == straight['v'].reason == LC.REASON_MORNING_PURGE
        assert cmds['v'].control_value() == pytest.approx(straight['v'].control_value())
        assert st_r.purge == st_s.purge

    def test_no_purge_state_means_none_after_the_restart(self, runtime_db, monkeypatch):  # noqa: F811
        before = _coord()
        before._coord_state = CoordinatorState()
        _save(before, monkeypatch)
        assert _restart(monkeypatch, T_FIRST)._coord_state.purge is None

    @pytest.mark.parametrize('broken', [
        'x', 7, {'on': 'yes', 'T_prev': 20.0, 'dT_h': 0.0},
        {'on': True, 'T_prev': 'warm', 'dT_h': 0.0},
        {'on': True, 'T_prev': float('nan'), 'dT_h': 0.0},
        {'on': True, 'T_prev': 20.0, 'dT_h': float('inf')},
        {'on': True, 'T_prev': 20.0, 'dT_h': 5000.0},
        {'on': True, 'T_prev': True, 'dT_h': 0.0},
    ])
    def test_a_broken_value_is_dropped_but_the_flags_ride(self, broken):
        owner = SimpleNamespace(_coord_state=CoordinatorState())
        blob = {'ts': T_SAVE, '_coord_state': {'humid_zone': True, 'purge': broken}}
        assert CM.restore_memory(owner, blob, T_SAVE) == ['_coord_state']
        assert owner._coord_state.humid_zone is True
        assert owner._coord_state.purge is None

    def test_unknown_values_survive_as_none(self):
        owner = SimpleNamespace(_coord_state=CoordinatorState())
        owner._coord_state.purge = HR.PurgeState(on=True, T_prev=None, dT_h=None)
        blob = _roundtrip(owner)
        other = SimpleNamespace(_coord_state=CoordinatorState())
        CM.restore_memory(other, blob, T_SAVE)
        assert other._coord_state.purge == HR.PurgeState(on=True, T_prev=None, dT_h=None)


# ─────────────────────────────────────────────────────────────────────────────
# 3. 강우 단계 유지
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def wall(monkeypatch):
    """게이트와 저장·복원이 같이 읽는 벽시계(`time.time`) — 한 곳에서 움직인다."""
    t = {'now': T_SAVE}
    monkeypatch.setattr(RSM.time, 'time', lambda: t['now'])
    return t


def _forecast(rain):
    return _rain_env(rain, 'model')


class TestRainHoldSurvivesRestart:

    def test_the_premise_a_fresh_gate_has_no_hold(self, wall):
        gate = SafetyPreGate(CFG)
        res = gate.evaluate(_forecast(0.0), _vents())
        assert res.gate_mask == 0 and not res.vent_caps and not res.forced_commands

    def test_a_gate_that_is_still_holding_keeps_the_restriction(self, wall):
        gate = SafetyPreGate(CFG)
        gate.evaluate(_forecast(1.0), _vents())                       # 1.0 → 천창 닫음 · 측창 상한
        wall['now'] += 600.0
        res = gate.evaluate(_forecast(0.0), _vents())
        assert 'rain_restricted' in res.description and res.forced_commands

    def test_the_restriction_still_stands_on_the_first_cycle_after_a_restart(
            self, runtime_db, monkeypatch, wall):  # noqa: F811
        before = _coord()
        gate = _with_gate(before)
        gate.evaluate(_forecast(1.0), _vents())
        before._coord_state = CoordinatorState()
        _save(before, monkeypatch, wall['now'])
        saved_until = gate._rain_hold[1]

        wall['now'] += 600.0
        after = _restart_with_gate(monkeypatch, wall['now'])
        assert after._pre_gate._rain_hold == (RAIN_LEVEL_RESTRICT, saved_until)
        res = after._pre_gate.evaluate(_forecast(0.0), _vents())
        assert 'rain_restricted' in res.description
        assert res.forced_commands and res.vent_caps

    def test_a_weaker_forecast_after_the_restart_holds_the_stronger_level(
            self, runtime_db, monkeypatch, wall):  # noqa: F811
        """0.9 ↔ 1.0 의 경계 — 재시작이 사이에 끼어도 천창이 한 사이클 열리지 않는다."""
        before = _coord()
        _with_gate(before).evaluate(_forecast(1.0), _vents())
        before._coord_state = CoordinatorState()
        _save(before, monkeypatch, wall['now'])
        wall['now'] += 60.0
        after = _restart_with_gate(monkeypatch, wall['now'])
        res = after._pre_gate.evaluate(_forecast(0.9), _vents())
        assert 'rain_restricted' in res.description
        assert res.forced_commands['roof']['value'] == 0.0

    def test_the_hold_expires_on_the_wall_clock(self, runtime_db, monkeypatch, wall):  # noqa: F811
        before = _coord()
        gate = _with_gate(before)
        gate.evaluate(_forecast(1.0), _vents())
        before._coord_state = CoordinatorState()
        _save(before, monkeypatch, wall['now'])
        # 복원은 되지만(30 분 안) 첫 사이클이 만료 뒤라면 풀린다 — 만료 시각 그대로다.
        after = _restart_with_gate(monkeypatch, T_SAVE + 60.0)
        assert after._pre_gate._rain_hold[1] == gate._rain_hold[1]
        monkeypatch.setattr(RSM.time, 'time', lambda: gate._rain_hold[1] + 1.0)
        res = after._pre_gate.evaluate(_forecast(0.0), _vents())
        assert res.gate_mask == 0 and not res.vent_caps

    def test_a_stale_memory_is_dropped(self, runtime_db, monkeypatch, wall):  # noqa: F811
        before = _coord()
        _with_gate(before).evaluate(_forecast(1.0), _vents())
        before._coord_state = CoordinatorState()
        _save(before, monkeypatch, wall['now'])
        late = _restart_with_gate(monkeypatch, T_SAVE + CM.MEMORY_MAX_AGE_S + 60.0)
        assert late._pre_gate._rain_hold == (RAIN_LEVEL_NONE, 0.0)

    def test_an_expired_hold_is_not_saved(self, wall):
        c = _coord()
        gate = _with_gate(c)
        gate._rain_hold = (RAIN_LEVEL_RESTRICT, wall['now'] - 1.0)
        assert CM.RAIN_HOLD_ATTR not in CM.export_memory(c, wall['now'])

    def test_no_gate_no_error(self, wall):
        c = _coord()
        assert c._rain_hold is None
        assert CM.RAIN_HOLD_ATTR not in CM.export_memory(c, wall['now'])
        c._rain_hold = (RAIN_LEVEL_RESTRICT, wall['now'] + 100.0)       # 게이트가 없으면 무시
        assert c._rain_hold is None

    @pytest.mark.parametrize('bad', [
        'x', None, [], {}, {'level': 2}, {'until': T_SAVE + 900.0},
        {'level': RAIN_LEVEL_CLOSE, 'until': T_SAVE + 900.0},       # 전면 폐쇄는 게이트 TTL 이 맡는다
        {'level': RAIN_LEVEL_NONE, 'until': T_SAVE + 900.0},
        {'level': 99, 'until': T_SAVE + 900.0},
        {'level': True, 'until': T_SAVE + 900.0},
        {'level': '2', 'until': T_SAVE + 900.0},
        {'level': 2.5, 'until': T_SAVE + 900.0},
        {'level': 2, 'until': 'soon'},
        {'level': 2, 'until': float('nan')},
        {'level': 2, 'until': float('inf')},
        {'level': 2, 'until': T_SAVE - 1.0},                        # 이미 만료
        {'level': 2, 'until': T_SAVE + 10 * 3600.0},                # 시계가 어긋났거나 망가졌다 — 무한 유지 금지
    ])
    def test_a_broken_value_is_dropped(self, bad):
        c = _coord()
        gate = _with_gate(c)
        assert CM.restore_memory(c, {'ts': T_SAVE, '_rain_hold': bad}, T_SAVE) == []
        assert gate._rain_hold == (RAIN_LEVEL_NONE, 0.0)

    def test_a_good_value_is_restored_with_the_exact_expiry(self):
        c = _coord()
        gate = _with_gate(c)
        until = T_SAVE + 900.0
        assert CM.restore_memory(
            c, {'ts': T_SAVE, '_rain_hold': {'level': RAIN_LEVEL_HOLD_ROOF, 'until': until}},
            T_SAVE) == ['_rain_hold']
        assert gate._rain_hold == (RAIN_LEVEL_HOLD_ROOF, until)


# ─────────────────────────────────────────────────────────────────────────────
# 4. rain_seen — 비를 보던 강우계가 끊긴 채 재시작
# ─────────────────────────────────────────────────────────────────────────────

class TestRainSeenSurvivesRestart:

    def _dead_gauge(self, env, seen):
        return env({('om', 'oR'): 0.2}, _GAUGE_FC, rain_seen=seen)

    def test_the_premise_a_forgotten_gauge_lets_the_forecast_take_over(self, env):  # noqa: F811
        od = self._dead_gauge(env, {})
        assert od['rain_mm'] == 0.2 and od['rain_origin'] == 'model' and not od['rain_held']

    def test_the_restored_memory_keeps_the_forecast_out(self, env, runtime_db, monkeypatch):  # noqa: F811
        before = _coord()
        before._outdoor_rain_seen = {}
        env({('gauge', 'gR'): 3.0, ('om', 'oR'): 0.2}, _GAUGE_FC, rain_seen=before._outdoor_rain_seen)
        assert before._outdoor_rain_seen == {'measured_mm': 3.0, 'devices': ['gauge']}
        _save(before, monkeypatch)

        after = _restart(monkeypatch, T_FIRST)
        assert after._outdoor_rain_seen == {'measured_mm': 3.0, 'devices': ['gauge']}
        od = self._dead_gauge(env, after._outdoor_rain_seen)
        assert od['rain_mm'] is None and od['rain_held'] is True

    def test_the_gate_then_closes_on_the_last_measured_rain(
            self, env, runtime_db, monkeypatch, wall):  # noqa: F811
        """끝까지 — 재시작한 게이트가 잃은 실측 비를 마지막 값으로 보고 전부 닫는다(예보로 풀지 않는다)."""
        before = _coord()
        gate = _with_gate(before)
        before._outdoor_rain_seen = {}
        env({('gauge', 'gR'): 3.0}, _GAUGE_FC, rain_seen=before._outdoor_rain_seen)
        gate.evaluate(_rain_env(3.0, 'measured'), _vents())
        before._coord_state = CoordinatorState()
        _save(before, monkeypatch, wall['now'])

        wall['now'] += 600.0
        after = _restart_with_gate(monkeypatch, wall['now'])
        od = self._dead_gauge(env, after._outdoor_rain_seen)
        ext = _rain_env(od['rain_mm'], od['rain_origin'])
        res = after._pre_gate.evaluate(ext, _vents())
        assert res.triggered and res.gate_mask & LC.GATE_BIT_RAIN

    def test_a_dry_last_reading_is_not_saved(self):
        c = _coord()
        c._outdoor_rain_seen = {'measured_mm': 0.0, 'devices': ['gauge']}
        assert CM.RAIN_SEEN_ATTR not in CM.export_memory(c, T_SAVE)
        c._outdoor_rain_seen = {}
        assert CM.RAIN_SEEN_ATTR not in CM.export_memory(c, T_SAVE)

    def test_a_stale_memory_is_dropped(self, runtime_db, monkeypatch):  # noqa: F811
        before = _coord()
        before._outdoor_rain_seen = {'measured_mm': 3.0, 'devices': ['gauge']}
        before._coord_state = CoordinatorState()
        _save(before, monkeypatch)
        late = _restart(monkeypatch, T_SAVE + CM.MEMORY_MAX_AGE_S + 60.0)
        assert not hasattr(late, '_outdoor_rain_seen')

    @pytest.mark.parametrize('bad', [
        'x', None, [], {}, {'measured_mm': 3.0}, {'devices': ['g']},
        {'measured_mm': 'wet', 'devices': ['g']}, {'measured_mm': float('nan'), 'devices': ['g']},
        {'measured_mm': float('inf'), 'devices': ['g']}, {'measured_mm': True, 'devices': ['g']},
        {'measured_mm': -1.0, 'devices': ['g']}, {'measured_mm': 0.0, 'devices': ['g']},
        {'measured_mm': 3.0, 'devices': 'g'}, {'measured_mm': 3.0, 'devices': []},
        {'measured_mm': 3.0, 'devices': [1, None, '']},
    ])
    def test_a_broken_value_is_dropped(self, bad):
        c = SimpleNamespace()
        assert CM.restore_memory(c, {'ts': T_SAVE, '_outdoor_rain_seen': bad}, T_SAVE) == []
        assert not hasattr(c, '_outdoor_rain_seen')

    def test_foreign_device_ids_are_cleaned(self):
        c = SimpleNamespace()
        CM.restore_memory(c, {'ts': T_SAVE, '_outdoor_rain_seen': {
            'measured_mm': 3.0, 'devices': ['gauge', 5, None]}}, T_SAVE)
        assert c._outdoor_rain_seen == {'measured_mm': 3.0, 'devices': ['gauge']}


# ─────────────────────────────────────────────────────────────────────────────
# 5. 한파 비상 래치
# ─────────────────────────────────────────────────────────────────────────────

def _cold_env(T_ext, T_in=3.0):
    return {'internal': {'T': T_in, 'T_min': T_in, 'T_max': T_in, 'RH': 60.0},
            'external': {'T': T_ext, 'RH': 60.0, 'wind': 1.0, 'rain': 0.0, 'solar': 0.0}}


class TestColdLatchSurvivesRestart:
    BAND = -4.0          # 들어가는 문턱 −5 °C 와 나오는 문턱 −3 °C 사이

    def test_the_premise_the_band_reads_opposite_ways(self, wall):
        latched = SafetyPreGate(CFG)
        assert latched.evaluate(_cold_env(-6.0), _vents()).gate_mask & GATE_BIT_COLD
        assert latched.evaluate(_cold_env(self.BAND), _vents()).gate_mask & GATE_BIT_COLD
        fresh = SafetyPreGate(CFG)
        assert not fresh.evaluate(_cold_env(self.BAND), _vents()).gate_mask & GATE_BIT_COLD

    def test_the_emergency_still_stands_on_the_first_cycle_after_a_restart(
            self, runtime_db, monkeypatch, wall):  # noqa: F811
        before = _coord()
        _with_gate(before).evaluate(_cold_env(-6.0), _vents())
        before._coord_state = CoordinatorState()
        _save(before, monkeypatch, wall['now'])

        wall['now'] += 600.0
        after = _restart_with_gate(monkeypatch, wall['now'])
        assert after._pre_gate._cold_latched is True
        res = after._pre_gate.evaluate(_cold_env(self.BAND), _vents())
        assert res.gate_mask & GATE_BIT_COLD and res.triggered

    def test_it_releases_normally_once_out_of_the_band(
            self, runtime_db, monkeypatch, wall):  # noqa: F811
        before = _coord()
        _with_gate(before).evaluate(_cold_env(-6.0), _vents())
        before._coord_state = CoordinatorState()
        _save(before, monkeypatch, wall['now'])
        after = _restart_with_gate(monkeypatch, wall['now'] + 600.0)
        res = after._pre_gate.evaluate(_cold_env(-1.0), _vents())
        assert not res.gate_mask & GATE_BIT_COLD

    def test_an_unlatched_gate_stays_unlatched(self, runtime_db, monkeypatch, wall):  # noqa: F811
        before = _coord()
        _with_gate(before).evaluate(_cold_env(10.0), _vents())
        before._coord_state = CoordinatorState()
        _save(before, monkeypatch, wall['now'])
        after = _restart_with_gate(monkeypatch, wall['now'] + 600.0)
        assert after._pre_gate._cold_latched is False

    def test_a_stale_memory_is_dropped(self, runtime_db, monkeypatch, wall):  # noqa: F811
        before = _coord()
        _with_gate(before).evaluate(_cold_env(-6.0), _vents())
        before._coord_state = CoordinatorState()
        _save(before, monkeypatch, wall['now'])
        late = _restart_with_gate(monkeypatch, T_SAVE + CM.MEMORY_MAX_AGE_S + 60.0)
        assert late._pre_gate._cold_latched is False

    @pytest.mark.parametrize('bad', ['x', 1, [], {'cold_latched': 'yes'}, {'cold_latched': 1},
                                     {'other': True}, {}])
    def test_a_broken_value_is_ignored(self, bad):
        c = _coord()
        gate = _with_gate(c)
        CM.restore_memory(c, {'ts': T_SAVE, '_gate_latches': bad}, T_SAVE)
        assert gate._cold_latched is False

    def test_no_gate_no_error(self):
        c = _coord()
        assert c._gate_latches is None
        assert CM.restore_memory(c, {'ts': T_SAVE, '_gate_latches': {'cold_latched': True}},
                                 T_SAVE) == []


# ─────────────────────────────────────────────────────────────────────────────
# 6. 육묘 일소 분무 잠금 래치
# ─────────────────────────────────────────────────────────────────────────────

NURSERY = PreGateConfig(gate_ttl=0.0, nursery_mode=True,
                        nursery_solar_lockout=250.0, nursery_solar_release=150.0)


def _light_env(light):
    return {'internal': {'light_est': light}, 'external': {}}


class TestNurseryLockSurvivesRestart:
    BAND = 200.0         # 켬 250 과 끔 150 사이

    def _locked_coord(self):
        c = _coord()
        c._pre_gate = SafetyPreGate(NURSERY)
        assert c._pre_gate._eval_nursery_lock(_light_env(300.0))
        c._coord_state = CoordinatorState()
        return c

    def _restart_nursery(self, monkeypatch, now):
        monkeypatch.setattr(RSM.time, 'time', lambda: now)
        c = _coord()
        c._pre_gate = SafetyPreGate(NURSERY)
        c._load_runtime_state()
        return c

    def test_the_premise_the_band_reads_opposite_ways(self):
        locked = SafetyPreGate(NURSERY)
        locked._eval_nursery_lock(_light_env(300.0))
        assert locked._eval_nursery_lock(_light_env(self.BAND))
        assert not SafetyPreGate(NURSERY)._eval_nursery_lock(_light_env(self.BAND))

    def test_the_lock_still_stands_on_the_first_cycle_after_a_restart(
            self, runtime_db, monkeypatch):  # noqa: F811
        _save(self._locked_coord(), monkeypatch)
        after = self._restart_nursery(monkeypatch, T_FIRST)
        assert after._pre_gate._nursery_locked is True
        assert after._pre_gate._eval_nursery_lock(_light_env(self.BAND))
        assert after._pre_gate._nursery_lock_reason == 'sunburn'

    def test_it_releases_normally_below_the_release_line(self, runtime_db, monkeypatch):  # noqa: F811
        _save(self._locked_coord(), monkeypatch)
        after = self._restart_nursery(monkeypatch, T_FIRST)
        assert not after._pre_gate._eval_nursery_lock(_light_env(100.0))

    def test_the_cold_latch_rides_the_same_property_independently(
            self, runtime_db, monkeypatch):  # noqa: F811
        c = self._locked_coord()
        assert c._gate_latches == {'cold_latched': False, 'nursery_locked': True}
        _save(c, monkeypatch)
        after = self._restart_nursery(monkeypatch, T_FIRST)
        assert after._gate_latches == {'cold_latched': False, 'nursery_locked': True}

    def test_an_unlocked_gate_stays_unlocked(self, runtime_db, monkeypatch):  # noqa: F811
        c = self._locked_coord()
        c._pre_gate._eval_nursery_lock(_light_env(100.0))
        _save(c, monkeypatch)
        assert self._restart_nursery(monkeypatch, T_FIRST)._pre_gate._nursery_locked is False

    def test_a_stale_memory_is_dropped(self, runtime_db, monkeypatch):  # noqa: F811
        _save(self._locked_coord(), monkeypatch)
        late = self._restart_nursery(monkeypatch, T_SAVE + CM.MEMORY_MAX_AGE_S + 60.0)
        assert late._pre_gate._nursery_locked is False

    @pytest.mark.parametrize('bad', [{'nursery_locked': 'yes'}, {'nursery_locked': 1}, {'x': True}])
    def test_a_broken_value_is_ignored(self, bad):
        c = _coord()
        gate = _with_gate(c)
        CM.restore_memory(c, {'ts': T_SAVE, '_gate_latches': bad}, T_SAVE)
        assert gate._nursery_locked is False

    def test_an_old_memory_with_only_the_cold_key_still_restores_it(self):
        c = _coord()
        gate = _with_gate(c)
        assert CM.restore_memory(c, {'ts': T_SAVE, '_gate_latches': {'cold_latched': True}},
                                 T_SAVE) == ['_gate_latches']
        assert gate._cold_latched is True and gate._nursery_locked is False


# ─────────────────────────────────────────────────────────────────────────────
# 7. 게이트가 닫아 둔 위치
# ─────────────────────────────────────────────────────────────────────────────

def _profiles(*ids):
    return [SimpleNamespace(actuator_id=i) for i in ids]


class TestGateHeldPositionsSurviveRestart:

    def _gated(self):
        """강우로 천창이 닫히는 동안(적분은 게이트 전 평형 60 % 그대로) 저장된 상태."""
        c = _coord()
        c._coord_state = CoordinatorState()
        c._coord_state.integral = {'roof': 60.0, 'side': 40.0}
        c._gate_held_positions = {'roof': 0.0, 'side': 0.0}
        c._profiles = _profiles('roof', 'side')
        return c

    def _restart_with(self, monkeypatch, now, *ids):
        monkeypatch.setattr(RSM.time, 'time', lambda: now)
        c = _coord()
        c._load_runtime_state()
        c._profiles = _profiles(*ids)            # 프로필 적재는 상태 복원 뒤다(`initialize`)
        return c

    def test_the_premise_without_the_memory_the_stale_equilibrium_stays(
            self, runtime_db, monkeypatch):  # noqa: F811
        c = self._gated()
        _save(c, monkeypatch)
        monkeypatch.setattr(RSM.time, 'time', lambda: T_SAVE + CM.MEMORY_MAX_AGE_S + 60.0)
        late = _coord()
        late._load_runtime_state()
        late._profiles = _profiles('roof', 'side')
        late._rebase_integral_after_gate()
        assert late._coord_state.integral == {'roof': 60.0, 'side': 40.0}   # 되맞추지 못한다

    def test_the_first_release_after_a_restart_rebases_like_without_one(
            self, runtime_db, monkeypatch):  # noqa: F811
        straight = self._gated()
        straight._rebase_integral_after_gate()
        assert straight._coord_state.integral == {'roof': 0.0, 'side': 0.0}

        _save(self._gated(), monkeypatch)
        after = self._restart_with(monkeypatch, T_FIRST, 'roof', 'side')
        assert after._gate_held_positions == {'roof': 0.0, 'side': 0.0}
        after._coord_state.integral = {'roof': 60.0, 'side': 40.0}
        after._rebase_integral_after_gate()
        assert after._coord_state.integral == straight._coord_state.integral
        assert after._gate_held_positions == {}

    def test_only_the_registered_actuators_are_kept(self, runtime_db, monkeypatch):  # noqa: F811
        c = self._gated()
        c._gate_held_positions = {'roof': 0.0, 'gone': 0.0}
        _save(c, monkeypatch)
        after = self._restart_with(monkeypatch, T_FIRST, 'roof', 'new')
        after._coord_state.integral = {'roof': 60.0}
        after._rebase_integral_after_gate()
        assert after._coord_state.integral == {'roof': 0.0}          # 빠진 장치의 키를 적분에 만들지 않는다

    def test_restore_filters_at_once_when_the_profiles_are_known(self):
        c = SimpleNamespace(_profiles=_profiles('roof'))
        blob = {'ts': T_SAVE, '_gate_held_positions': {'roof': 0.0, 'gone': 5.0}}
        assert CM.restore_memory(c, blob, T_SAVE) == ['_gate_held_positions']
        assert c._gate_held_positions == {'roof': 0.0}

    def test_without_a_profile_list_nothing_is_filtered_like_before(self):
        c = self._gated()
        c._profiles = []
        c._rebase_integral_after_gate()
        assert c._coord_state.integral == {'roof': 0.0, 'side': 0.0}
        assert c._gate_held_positions == {}

    def test_all_gone_clears_it(self):
        c = self._gated()
        c._profiles = _profiles('other')
        c._rebase_integral_after_gate()
        assert c._coord_state.integral == {'roof': 60.0, 'side': 40.0}
        assert c._gate_held_positions == {}

    def test_an_empty_dict_is_not_saved(self, wall):
        c = _coord()
        c._gate_held_positions = {}
        assert CM.HELD_POSITIONS_ATTR not in CM.export_memory(c, wall['now'])

    def test_a_stale_memory_is_dropped(self, runtime_db, monkeypatch):  # noqa: F811
        _save(self._gated(), monkeypatch)
        late = self._restart_with(monkeypatch, T_SAVE + CM.MEMORY_MAX_AGE_S + 60.0, 'roof')
        assert not hasattr(late, '_gate_held_positions')

    @pytest.mark.parametrize('bad', ['x', None, 7, [], {}, {'roof': 'open'}, {'roof': None},
                                     {'roof': float('nan')}, {'roof': float('inf')},
                                     {'roof': True}, {'': 5.0}, {1: 5.0}])
    def test_a_broken_value_is_dropped(self, bad):
        c = SimpleNamespace()
        CM.restore_memory(c, {'ts': T_SAVE, '_gate_held_positions': bad}, T_SAVE)
        assert not getattr(c, '_gate_held_positions', None)

    def test_good_entries_survive_next_to_broken_ones_and_are_clamped(self):
        c = SimpleNamespace()
        CM.restore_memory(c, {'ts': T_SAVE, '_gate_held_positions': {
            'roof': 12.5, 'side': 140.0, 'low': -3.0, 'bad': 'x'}}, T_SAVE)
        assert c._gate_held_positions == {'roof': 12.5, 'side': 100.0, 'low': 0.0}


# ─────────────────────────────────────────────────────────────────────────────
# 저장 형식
# ─────────────────────────────────────────────────────────────────────────────

class TestStoredShape:

    def test_everything_is_json_clean_and_roundtrips(self, wall):
        c = _coord()
        gate = _with_gate(c)
        gate.evaluate(_forecast(1.0), _vents())
        gate._cold_latched = True
        gate._nursery_locked = True
        c._gate_held_positions = {'roof': 0.0}
        c._outdoor_rain_seen = {'measured_mm': 2.5, 'devices': ['gauge']}
        c._coord_state = _in_zone_state()
        c._coord_state.purge = HR.PurgeState(on=True, T_prev=20.5, dT_h=1.2)
        blob = _roundtrip(c, now=wall['now'])

        assert blob['_gate_latches'] == {'cold_latched': True, 'nursery_locked': True}
        assert blob['_gate_held_positions'] == {'roof': 0.0}
        assert blob['_rain_hold']['level'] == RAIN_LEVEL_RESTRICT
        assert blob['_outdoor_rain_seen'] == {'measured_mm': 2.5, 'devices': ['gauge']}
        assert blob['_coord_state']['humid_zone'] is True
        assert blob['_coord_state']['purge'] == {'on': True, 'T_prev': 20.5, 'dT_h': 1.2}

        d = _coord()
        gate2 = _with_gate(d)
        done = CM.restore_memory(d, blob, wall['now'])
        assert {'_gate_latches', '_rain_hold', '_outdoor_rain_seen', '_coord_state'} <= set(done)
        assert gate2._cold_latched and gate2._nursery_locked and gate2._rain_hold == gate._rain_hold
        assert d._gate_held_positions == {'roof': 0.0}
        assert d._outdoor_rain_seen == {'measured_mm': 2.5, 'devices': ['gauge']}
        assert d._coord_state.humid_zone is True
        assert d._coord_state.purge == HR.PurgeState(on=True, T_prev=20.5, dT_h=1.2)

    def test_a_non_finite_timestamp_restores_nothing(self):
        c = _coord()
        assert CM.restore_memory(c, {'ts': float('nan'), '_gate_latches': {}}, T_SAVE) == []


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
