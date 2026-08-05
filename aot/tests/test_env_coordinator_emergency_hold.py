# coding=utf-8
"""긴급정지 보류가 우회되지 않는지 확인한다.

`cmd_emergency_stop()` 은 모든 액추에이터를 안전값으로 보낸 뒤 60초간 조율기가
다시 명령을 내지 않게 미룬다. 그 지연을 `timer_loop` 하나로만 표현하면
`cmd_run_now()` 가 `timer_loop = 0.0` 으로 되돌려 보류가 통째로 뚫린다 —
긴급정지 직후 사용자가 "지금 실행" 을 누르면 조율기가 즉시 재개해 방금 안전값으로
보낸 액추에이터를 다시 움직이는 셈이다.

보류를 `_emergency_hold_until` 이라는 별도 상태로 두고, `cmd_run_now()` 와
`loop()` 양쪽에서 지킨다. 두 곳인 이유는 나중에 `timer_loop` 를 되돌리는 경로가
새로 생겨도 보류만은 뚫리지 않게 하기 위함이다.
"""
from unittest.mock import MagicMock

import pytest

from aot.functions.custom_functions.env_coordinator import CustomModule


@pytest.fixture()
def coord():
    """__init__ 을 거치지 않고 이 테스트에 필요한 상태만 갖춘 인스턴스."""
    c = CustomModule.__new__(CustomModule)
    c.logger = MagicMock()
    c.timer_loop = 0.0
    c._force_immediate = False
    c._emergency_hold_until = 0.0
    c._last_cycle_ts = 0.0
    c.update_period = 600.0
    return c


def test_run_now_is_refused_during_hold(coord, monkeypatch):
    """보류 중 cmd_run_now 는 timer_loop 를 되돌리지 못한다."""
    monkeypatch.setattr('time.time', lambda: 1000.0)
    coord._emergency_hold_until = 1030.0     # 30초 남음
    coord.timer_loop = 1030.0

    result = coord.cmd_run_now({})

    assert coord.timer_loop == 1030.0, '보류 중인데 timer_loop 가 리셋됐다'
    assert coord._force_immediate is False, '보류 중인데 즉시실행 플래그가 섰다'
    assert '긴급정지' in result
    assert coord.logger.warning.called


def test_run_now_works_after_hold_expires(coord, monkeypatch):
    """보류가 끝나면 평소대로 즉시 실행할 수 있어야 한다 — 영구 차단이 아니다."""
    monkeypatch.setattr('time.time', lambda: 2000.0)
    coord._emergency_hold_until = 1030.0     # 이미 지남
    coord.timer_loop = 2500.0

    coord.cmd_run_now({})

    assert coord.timer_loop == 0.0
    assert coord._force_immediate is True


def test_loop_returns_during_hold_even_if_timer_reset(coord, monkeypatch):
    """timer_loop 가 어떤 경로로든 0 이 되어도 보류 중에는 사이클이 돌지 않는다."""
    monkeypatch.setattr('time.time', lambda: 1000.0)
    coord._emergency_hold_until = 1030.0
    coord.timer_loop = 0.0                   # 다른 경로가 되돌려 놓은 상황
    coord._run_cycle = MagicMock()

    coord.loop()

    coord._run_cycle.assert_not_called()


def test_loop_runs_after_hold_expires(coord, monkeypatch):
    """보류가 끝나면 사이클이 정상 재개된다."""
    monkeypatch.setattr('time.time', lambda: 2000.0)
    coord._emergency_hold_until = 1030.0
    coord.timer_loop = 0.0
    coord._run_cycle = MagicMock()

    coord.loop()

    coord._run_cycle.assert_called_once()


def test_emergency_stop_sets_hold(monkeypatch):
    """긴급정지가 보류 상태를 실제로 남기는지 — 이게 없으면 위 방어가 전부 무의미."""
    c = CustomModule.__new__(CustomModule)
    c.logger = MagicMock()
    c.timer_loop = 0.0
    c._emergency_hold_until = 0.0
    c._profiles = []
    c._channel_map = {}
    c.control = MagicMock()
    monkeypatch.setattr('time.time', lambda: 5000.0)

    c.cmd_emergency_stop({})

    assert c._emergency_hold_until == 5060.0
    assert c.timer_loop == 5060.0
