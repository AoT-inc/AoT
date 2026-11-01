# coding=utf-8
"""재시작 직후 첫 사이클의 측창 열림 — 천장 두 곳이 재시작에 사라졌다 (2026-10-12 김제 육묘장3).

## 실측

    21:56  비·바람 값이 끊김(`실외 rain 값이 끊겼습니다`) — 게이트 EXT_EXP, 측창 좌/우 0 %
    22:06  0 % (데드존 물러남)
    22:14:57  데몬 재시작
    22:14:58  첫 사이클: 측창 좌/우 **14.8 %**(근거 1, PI) · 게이트 기록 없음
    22:25     0 % (근거 1)

같은 입력(실내 16.6 °C · 93 % · 실외 21.3 °C · 85 %)이 재시작 전후 사이클에서 0 / 14.8 / 0 으로 갈렸다.
리플레이(재시작 시각을 넣어 되돌림)로 재현했고, 필드별로 이어 가며 가려냈다:

  · `CoordinatorState.t_ceiling_active`(온도 상한 항의 히스테리시스 이력)만 이으면 14.8 → 0 %.
    `gradient_active`·`drive_sign`·`deadzone_wrong_side` 를 이어도 14.8 % 그대로.
    켜진 항은 선 아래로 `T_CEILING_HYST` 만큼 더 내려가야 꺼지고 그동안 초과분이 커서 '닫기' 쪽을 더 민다. 비영속이라
    첫 사이클만 그 힘이 작아 습도·VPD 항이 이겼다.
  · 사전 게이트의 `_weather_seen`(마지막 실측 강우·풍속)도 프로세스 메모리에만 있어, 끊긴 비 센서가 재시작 뒤
    '원래 없던 센서' 로 읽혀 EXT_EXP("더 열지 않음" 천장)가 사라졌다. 22:25 에도 비 값은 여전히 없었는데 게이트
    기록이 없었다.

둘 다 정본은 `env_control/cycle_memory.py` 한 곳이다.
"""
import json

import pytest

from aot.functions.custom_functions.env_coordinator_impl import _runtime_state_mixin as RSM
from aot.functions.utils.env_control import cycle_memory as CM
from aot.functions.utils.env_control.coordinator import CoordinatorState, coordinate
from aot.functions.utils.env_control.log_channels import GATE_BIT_EXT_EXP
from aot.functions.utils.env_control.safety_gates import (
    RAIN_ORIGIN_MEASURED, RAIN_ORIGIN_MODEL, PreGateConfig, SafetyPreGate, WeatherMemory,
)

from .test_cycle_memory import T_FIRST, T_SAVE, _coord, _restart, runtime_db  # noqa: F401
from .test_heat_protect_tuning import _ctx, _effect, _profile, _Situation, _state, _TARGET
from .test_wind_gate_grading import _env, _gimje, clock  # noqa: F401 (fixture)

CFG = PreGateConfig(gate_ttl=0.0)


# ─────────────────────────────────────────────────────────────────────────────
# 1. 온도 상한 항의 이력 — 재시작이 '닫기' 힘을 지운다
# ─────────────────────────────────────────────────────────────────────────────

def _open_scenario(state):
    """습해서(VPD 낮음) VPD 항은 열어 말리자고 하고, 따뜻한 외기는 온도를 올려 상한 항은 닫자고 하는 밤.
    측창 하나, 직전 개도 0 %, 온도가 상한 선 바로 아래(29.5 °C, 상한 30 °C)."""
    w = _profile('w', 'opening', temp_mag=2.0, vpd_dir='↑', vpd_mag=0.1)
    w.effect_model['temperature'] = _effect('↑', 2.0)
    sit = _Situation(_TARGET, {'vpd': -0.5}, _ctx(T_ceiling=30.0, T_int=29.5))
    cmds, new = coordinate(sit, [w], state, unique_id='')
    return cmds['w'].value, new


class TestCeilingHysteresisSurvivesRestart:

    def test_the_premise_a_forgotten_term_opens_the_window(self):
        """결함의 전제 — 이력이 켜져 있으면 닫혀 있고, 없으면 같은 입력에 열린다."""
        kept, _ = _open_scenario(_state({'w': 0.0}, ceiling_active=True))
        lost, _ = _open_scenario(_state({'w': 0.0}, ceiling_active=False))
        assert kept == pytest.approx(0.0)
        assert lost > 10.0

    def test_the_restored_first_cycle_stays_closed(self, runtime_db, monkeypatch):  # noqa: F811
        before = _coord()
        before._coord_state = _state({'w': 0.0}, ceiling_active=True)
        monkeypatch.setattr(RSM.time, 'time', lambda: T_SAVE)
        before._save_runtime_state()

        after = _restart(monkeypatch, T_FIRST)             # 새 인스턴스 + 저장된 행에서 복원
        assert after._coord_state.t_ceiling_active is True
        first, _ = _open_scenario(after._coord_state)
        assert first == pytest.approx(0.0)

    def test_the_flag_rides_the_cycle_end_state_too(self, runtime_db, monkeypatch):  # noqa: F811
        """사이클이 돌려준 새 상태(`new_state`)의 이력이 저장된다 — 켜졌다 꺼졌다를 그대로."""
        _v, new = _open_scenario(_state({'w': 0.0}, ceiling_active=True))
        assert new.t_ceiling_active
        before = _coord()
        before._coord_state = new
        monkeypatch.setattr(RSM.time, 'time', lambda: T_SAVE)
        before._save_runtime_state()
        assert _restart(monkeypatch, T_FIRST)._coord_state.t_ceiling_active is True

        off = _state({'w': 0.0}, ceiling_active=False)
        before._coord_state = off
        before._save_runtime_state()
        assert _restart(monkeypatch, T_FIRST)._coord_state.t_ceiling_active is False

    def test_a_stale_memory_is_dropped_like_the_others(self, runtime_db, monkeypatch):  # noqa: F811
        before = _coord()
        before._coord_state = _state({'w': 0.0}, ceiling_active=True)
        monkeypatch.setattr(RSM.time, 'time', lambda: T_SAVE)
        before._save_runtime_state()
        late = _restart(monkeypatch, T_SAVE + CM.MEMORY_MAX_AGE_S + 60.0)
        assert late._coord_state.t_ceiling_active is False

    def test_other_pi_fields_stay_unpersisted(self, runtime_db, monkeypatch):  # noqa: F811
        """이어 가는 것은 이 한 가지뿐이다 — 나머지는 종전대로 '재시작 직후 한 사이클은 종전 규칙'."""
        before = _coord()
        st = _state({'w': 0.0}, ceiling_active=True)
        st.drive_sign = {'w': 1}
        st.gradient_active = {'w': True}
        st.humid_zone = True
        before._coord_state = st
        monkeypatch.setattr(RSM.time, 'time', lambda: T_SAVE)
        before._save_runtime_state()
        after = _restart(monkeypatch, T_FIRST)._coord_state
        assert after.drive_sign == {} and after.gradient_active == {}
        assert after.humid_zone is True             # 이력 띠가 있는 것은 이어 간다(`test_restart_hysteresis`)

    def test_a_memory_without_the_section_leaves_the_state_alone(self):
        from types import SimpleNamespace
        owner = SimpleNamespace(_coord_state=CoordinatorState())
        assert CM.restore_memory(owner, {'ts': T_SAVE}, T_SAVE) == []
        assert owner._coord_state.t_ceiling_active is False
        assert CM.restore_memory(owner, {'ts': T_SAVE, '_coord_state': 'broken'}, T_SAVE) == []
        assert CM.restore_memory(
            SimpleNamespace(), {'ts': T_SAVE, '_coord_state': {'t_ceiling_active': True}},
            T_SAVE) == []


# ─────────────────────────────────────────────────────────────────────────────
# 2. 강우·풍속의 마지막 실측 — 끊긴 센서가 '원래 없던 센서' 가 되지 않는다
# ─────────────────────────────────────────────────────────────────────────────

def _lost_rain_env():
    return _env(0.1, rain=None)             # 풍속은 오고 비 값만 끊겼다(김제 22:06~)


def _gate_with_memory(coord):
    coord._pre_gate = SafetyPreGate(CFG)
    return coord._pre_gate


class TestWeatherMemorySurvivesRestart:

    def test_the_premise_a_fresh_gate_reads_a_lost_rain_sensor_as_absent(self, clock):  # noqa: F811
        gate = SafetyPreGate(CFG)
        res = gate.evaluate(_lost_rain_env(), _gimje())
        assert not res.gate_mask & GATE_BIT_EXT_EXP
        assert not res.vent_open_ceiling

    def test_a_gate_that_saw_the_sensor_holds_the_ceiling_when_it_drops(self, clock):  # noqa: F811
        gate = SafetyPreGate(CFG)
        gate.evaluate(_env(0.1, rain=0.0), _gimje())
        res = gate.evaluate(_lost_rain_env(), _gimje())
        assert res.gate_mask & GATE_BIT_EXT_EXP and res.vent_open_ceiling

    def test_the_ceiling_stands_on_the_first_cycle_after_a_restart(
            self, runtime_db, monkeypatch, clock):  # noqa: F811
        before = _coord()
        gate = _gate_with_memory(before)
        gate.evaluate(_env(0.1, rain=0.0), _gimje())          # 비·바람 다 보였다
        before._coord_state = CoordinatorState()
        monkeypatch.setattr(RSM.time, 'time', lambda: T_SAVE)
        before._save_runtime_state()

        after = _coord()
        after._pre_gate = SafetyPreGate(CFG)                   # 새 프로세스의 게이트
        monkeypatch.setattr(RSM.time, 'time', lambda: T_FIRST)
        after._load_runtime_state()
        assert after._weather_memory.seen == {'rain': 0.0, 'wind': 0.1}
        res = after._pre_gate.evaluate(_lost_rain_env(), _gimje())
        assert res.gate_mask & GATE_BIT_EXT_EXP and res.vent_open_ceiling

    def test_a_stale_memory_is_dropped_like_the_others(self, runtime_db, monkeypatch, clock):  # noqa: F811
        before = _coord()
        _gate_with_memory(before).evaluate(_env(0.1, rain=0.0), _gimje())
        before._coord_state = CoordinatorState()
        monkeypatch.setattr(RSM.time, 'time', lambda: T_SAVE)
        before._save_runtime_state()

        late = _coord()
        late._pre_gate = SafetyPreGate(CFG)
        monkeypatch.setattr(RSM.time, 'time', lambda: T_SAVE + CM.MEMORY_MAX_AGE_S + 60.0)
        late._load_runtime_state()
        assert late._weather_memory.seen == {}

    def test_an_installation_without_the_sensor_is_still_unconstrained(self, clock):  # noqa: F811
        """한 번도 못 본 센서는 종전대로다 — 기억을 이어도 없던 센서에 천장을 만들지 않는다."""
        owner = _coord()
        gate = _gate_with_memory(owner)
        blob = json.loads(json.dumps(CM.export_memory(owner, T_SAVE)))
        assert blob['_weather_memory'] == {'seen': {}, 'rain_origin': RAIN_ORIGIN_MEASURED}
        other = _coord()
        _gate_with_memory(other)
        CM.restore_memory(other, blob, T_SAVE)
        res = other._pre_gate.evaluate(_lost_rain_env(), _gimje())
        assert not res.gate_mask & GATE_BIT_EXT_EXP and gate is not other._pre_gate

    def test_the_rain_origin_rides_along(self, clock):  # noqa: F811
        a = _coord()
        gate = _gate_with_memory(a)
        ext = _env(0.1, rain=0.2)
        ext['external']['rain_origin'] = RAIN_ORIGIN_MODEL
        gate.evaluate(ext, _gimje())
        blob = json.loads(json.dumps(CM.export_memory(a, T_SAVE)))
        assert blob['_weather_memory']['rain_origin'] == RAIN_ORIGIN_MODEL
        b = _coord()
        _gate_with_memory(b)
        CM.restore_memory(b, blob, T_SAVE)
        assert b._pre_gate.weather_memory.rain_origin == RAIN_ORIGIN_MODEL

    def test_a_broken_memory_is_cleaned(self, clock):  # noqa: F811
        c = _coord()
        gate = _gate_with_memory(c)
        c._weather_memory = WeatherMemory(
            seen={'rain': 'x', 'wind': 3.0, 'wind_gust': float('nan'), 'wind_dir': None},
            rain_origin='???')
        assert gate.weather_memory.seen == {'wind': 3.0}
        assert gate.weather_memory.rain_origin == RAIN_ORIGIN_MEASURED

    def test_the_property_is_none_without_a_gate(self):
        assert _coord()._weather_memory is None


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
