# coding=utf-8
"""안전 게이트가 풀린 뒤 적분(평형 개도 기억)은 게이트가 둔 자리에서 다시 시작한다.

비로 창이 2시간 닫혀 있다가 그치면, 예전에는 적분이 비 오기 전 평형(예: 60 %)
그대로 살아 있어 조건이 바뀌었는데도 곧장 그 개도로 돌아가려 했다. 무충격
전환의 규칙대로 지금 장치가 있는 자리(게이트가 둔 값)에서 PI 가 다시 찾는다.
"""
from types import SimpleNamespace
from unittest.mock import MagicMock

from aot.functions.custom_functions.env_coordinator import CustomModule


def _coord():
    c = CustomModule.__new__(CustomModule)
    c.logger = MagicMock()
    c.unique_id = 'fn'
    c._coord_state = SimpleNamespace(integral={'vent': 60.0, 'heater': 30.0})
    c._dispatch = MagicMock(return_value=set())
    c._send_critical_email = MagicMock()
    c._write_gate_only_summary = MagicMock()
    c._refresh_capability = MagicMock()
    return c


def _gate(forced):
    return SimpleNamespace(forced_commands=forced, gate_mask=1)


def test_release_rebases_only_the_devices_the_gate_moved(monkeypatch):
    import aot.functions.custom_functions.env_coordinator_impl._cycle_mixin as cm
    monkeypatch.setattr(cm, 'write_decision_log', lambda *a, **k: None)
    c = _coord()
    c._act_on_triggered_gate(_gate({'vent': {'value': 0.0}}), {}, 600.0, 0.0, {})
    assert c._coord_state.integral['vent'] == 60.0, '게이트 동안에는 건드리지 않는다'

    c._rebase_integral_after_gate()

    assert c._coord_state.integral['vent'] == 0.0
    assert c._coord_state.integral['heater'] == 30.0, '게이트가 안 건드린 장치의 기억은 유효하다'


def test_rebase_happens_once():
    c = _coord()
    c._gate_held_positions = {'vent': 0.0}
    c._rebase_integral_after_gate()
    c._coord_state.integral['vent'] = 25.0      # PI 가 다시 찾아가는 중
    c._rebase_integral_after_gate()
    assert c._coord_state.integral['vent'] == 25.0, '해제 뒤 매 사이클 되돌리면 PI 가 못 움직인다'


def test_the_last_forced_position_wins(monkeypatch):
    """게이트가 오래 서 있는 동안 강제값이 바뀌면(예: 부분 폐쇄→전체 폐쇄) 마지막 값."""
    import aot.functions.custom_functions.env_coordinator_impl._cycle_mixin as cm
    monkeypatch.setattr(cm, 'write_decision_log', lambda *a, **k: None)
    c = _coord()
    c._act_on_triggered_gate(_gate({'vent': {'value': 30.0}}), {}, 600.0, 0.0, {})
    c._act_on_triggered_gate(_gate({'vent': {'value': 0.0}}), {}, 600.0, 0.0, {})
    c._rebase_integral_after_gate()
    assert c._coord_state.integral['vent'] == 0.0
