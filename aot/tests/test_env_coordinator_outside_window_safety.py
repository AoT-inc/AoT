# coding=utf-8
"""운전 시간대 밖에서도 사전 안전 게이트는 돈다.

설정 화면과 매뉴얼은 "창 밖 시간에는 제어가 멈추지만 안전 한계는 그래도
작동한다" 고 말한다. 그런데 시간대 판정이 게이트 평가보다 앞에서 사이클을
끝내고 있어, 창 밖 시간에는 비·강풍·폭염·한파 게이트가 한 번도 평가되지
않았다 — 밤에 비가 들이쳐도 창은 열린 채였다.

또 시간대는 서버 시각으로 재고 있었다. 같은 서버가 다른 시간대의 시설을
돌리면 시설이 서버의 하루를 따라 켜지고 꺼진다.
"""
from datetime import datetime, timezone, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from aot.functions.custom_functions.env_coordinator import CustomModule


def _gate(triggered, forced=None, mask=0, partial=False):
    return SimpleNamespace(triggered=triggered, forced_commands=forced or {},
                           gate_mask=mask, partial=partial)


@pytest.fixture()
def coord():
    c = CustomModule.__new__(CustomModule)
    c.logger = MagicMock()
    c.unique_id = 'fn-test'
    c._profiles = [MagicMock()]
    c.time_enable = True
    c._in_time_window = MagicMock(return_value=False)
    c._sensor_max_age = MagicMock(return_value=None)
    c._collect_external_context = MagicMock(return_value=({'rain': 1.0}, {}))
    c._collect_internal = MagicMock(return_value={'T': 20.0})
    c._compute_light_est = MagicMock()
    c._build_gate_env = MagicMock(return_value={'internal': {}, 'external': {}})
    c._pre_gate = MagicMock()
    c._act_on_triggered_gate = MagicMock()
    c._apply_end_behaviors = MagicMock()
    c._check_hard_constraints = MagicMock()
    c._dispatch = MagicMock()
    return c


def test_gate_fires_outside_window(coord):
    """비가 오면 창 밖 시간에도 게이트 집행이 돌고, 종료 동작은 그 사이클에 겨루지 않는다."""
    coord._pre_gate.evaluate.return_value = _gate(True, {'vent': 0.0}, mask=1)

    coord._run_cycle(600.0)

    coord._act_on_triggered_gate.assert_called_once()
    coord._apply_end_behaviors.assert_not_called()
    assert coord._control_paused == 'outside_time_window'


def test_end_behavior_when_gate_quiet(coord):
    coord._pre_gate.evaluate.return_value = _gate(False)

    coord._run_cycle(600.0)

    coord._pre_gate.evaluate.assert_called_once()
    coord._act_on_triggered_gate.assert_not_called()
    coord._apply_end_behaviors.assert_called_once_with(skip_ids=set())
    coord._dispatch.assert_not_called()


def test_gate_still_evaluated_without_indoor_values(coord):
    """실내 센서가 죽은 밤에도 강우·강풍은 실외 값으로 선다 — 여기서 멈추면 보호가 빠진다."""
    coord._collect_internal.return_value = None
    coord._pre_gate.evaluate.return_value = _gate(True, {'vent': 0.0}, mask=1)

    coord._run_cycle(600.0)

    coord._act_on_triggered_gate.assert_called_once()


def test_gate_failure_still_sends_end_behavior(coord):
    """보호를 더하려다 기존 종료 동작까지 잃으면 안 된다."""
    coord._pre_gate.evaluate.side_effect = RuntimeError('boom')

    coord._run_cycle(600.0)

    coord._apply_end_behaviors.assert_called_once()
    assert coord.logger.error.called


def test_intentional_stop_does_not_act_by_itself(coord):
    """판정 함수는 판정만 한다 — 종료 동작을 여기서 보내면 게이트보다 먼저 나간다."""
    assert coord._intentional_stop() == 'outside_time_window'
    coord._apply_end_behaviors.assert_not_called()


def test_time_window_uses_facility_local_time():
    """서버는 UTC 23:30, 시설(UTC+9)은 08:30 — 06:00~20:00 창 안이다."""
    c = CustomModule.__new__(CustomModule)
    c.logger = MagicMock()
    c._get_time_window = MagicMock(return_value=('06:00', '20:00'))
    kst = timezone(timedelta(hours=9))
    c._facility_local_now = MagicMock(
        return_value=datetime(2026, 9, 22, 8, 30, tzinfo=kst))

    assert c._in_time_window() is True
    c._facility_local_now.return_value = datetime(2026, 9, 22, 21, 0, tzinfo=kst)
    assert c._in_time_window() is False


def _profile(aid, kind):
    return SimpleNamespace(actuator_id=aid, kind=kind)


def test_temp_min_breach_closes_vents_outside_window(coord):
    """20:00 에 창이 끝나고 20:10 에 실내가 temp_min 아래로 — 창은 닫혀야 한다.

    하드 한계는 금지·예방만 한다(난방기를 켜지는 않는다) — 창 닫기·커튼 치기·
    냉방 금지. 그 장치들은 종료 동작 대신 보호 명령을 받는다.
    """
    coord._profiles = [_profile('v1', 'opening'), _profile('h1', 'heater'),
                       _profile('c1', 'curtain')]
    coord._pre_gate.evaluate.return_value = _gate(False)

    def breach(internal):
        internal['_force_heat'] = True
    coord._check_hard_constraints.side_effect = breach

    coord._run_cycle(600.0)

    sent = coord._dispatch.call_args[0][0]
    assert sent['v1']['value'] == 0.0 and sent['c1']['value'] == 0.0
    assert 'h1' not in sent, '하드 한계는 구동하지 않는다 — 난방은 켜지 않는다'
    coord._apply_end_behaviors.assert_called_once_with(skip_ids={'v1', 'c1'})


def test_partial_gate_applies_outside_window(coord):
    """풍향 차등 폐쇄는 triggered 가 아니라서 예전엔 시간대 밖에서 빠졌다."""
    coord._pre_gate.evaluate.return_value = _gate(
        False, {'v1': {'value': 0.0, 'reason': 21}}, partial=True)

    coord._run_cycle(600.0)

    assert coord._dispatch.call_args[0][0] == {'v1': {'value': 0.0, 'reason': 21}}
    coord._apply_end_behaviors.assert_called_once_with(skip_ids={'v1'})


def test_light_limits_do_not_run_outside_window(coord):
    """light_min 은 보광등을 켜는 구동이다 — 밤에 불을 켜면 안 된다."""
    coord._profiles = [_profile('L1', 'lighting')]
    coord._pre_gate.evaluate.return_value = _gate(False)

    def breach(internal):
        internal['_force_light_min'] = True
        internal['_light_below_min'] = True
    coord._check_hard_constraints.side_effect = breach

    coord._run_cycle(600.0)

    coord._dispatch.assert_not_called()
