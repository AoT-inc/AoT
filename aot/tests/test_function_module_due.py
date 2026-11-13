# coding=utf-8
"""사용자 Function 모듈이 점검 주기가 아니라 모듈 자신의 다음 실행 시각에 돈다.

#682 로 트리거·조건문·PID·출력은 '다음 할 일 시각' 에 깨어나게 됐지만, Function
컨트롤러는 모듈 `loop()` 를 점검 주기(sample_rate)마다만 불렀다. 점검 주기를
15초로 둔 설치에서는 60초 주기 모듈도 최대 15초씩 늦게 돌았다.

본 것:
- `AbstractFunction.seconds_until_due()` 가 모듈 공통의 `timer_loop` 를 읽는다.
- 환경 조정기는 긴급정지 보류가 풀리는 때까지 기다린다(loop 와 같은 규칙).
- Function 컨트롤러가 모듈 할 일 시각에 `loop()` 를 부르고(실제 스레드),
  모듈 명령(버튼) 뒤에는 루프를 깨운다.
"""
import logging
import threading
import time
from unittest.mock import MagicMock

import pytest

from aot.controllers.base_controller import AbstractController
from aot.functions.base_function import AbstractFunction


class _Fn(AbstractFunction):
    def __init__(self):  # DB 없이
        self.logger = logging.getLogger('test.fn_due')


# ---------------------------------------------------------------------------
# AbstractFunction
# ---------------------------------------------------------------------------

def test_module_due_reads_timer_loop():
    f = _Fn()
    f.timer_loop = time.time() + 42
    assert f.seconds_until_due() == pytest.approx(42, abs=0.2)
    f.timer_loop = time.time() - 3
    assert f.seconds_until_due() == pytest.approx(-3, abs=0.2)


@pytest.mark.parametrize('value', [None, True, 'abc', float('nan'), float('inf')])
def test_module_due_unknown_is_none(value):
    f = _Fn()
    f.timer_loop = value
    assert f.seconds_until_due() is None


def test_module_without_timer_loop_is_none():
    assert _Fn().seconds_until_due() is None


def test_env_coordinator_waits_for_emergency_hold():
    from aot.functions.custom_functions.env_coordinator import CustomModule
    m = object.__new__(CustomModule)
    now = time.time()
    m.timer_loop = now + 10
    m._emergency_hold_until = now + 100
    assert m.seconds_until_due() == pytest.approx(100, abs=0.2)
    m._emergency_hold_until = 0.0
    assert m.seconds_until_due() == pytest.approx(10, abs=0.2)


# ---------------------------------------------------------------------------
# Function 컨트롤러
# ---------------------------------------------------------------------------

class _Module:
    """`while timer_loop < now: timer_loop += period` 규칙의 흔한 모듈 흉내."""

    def __init__(self, period, start=None):
        self.period = period
        self.timer_loop = time.time() if start is None else start
        self.runs = []

    def seconds_until_due(self):
        return self.timer_loop - time.time()

    def loop(self):
        if self.timer_loop > time.time():
            return
        while self.timer_loop < time.time():
            self.timer_loop += self.period
        self.runs.append(time.monotonic())

    def run_now(self, args):
        self.timer_loop = 0.0


def _ctrl(module, sample_rate=15.0):
    import aot.controllers.controller_function as cf
    c = object.__new__(cf.FunctionController)
    c.logger = MagicMock()
    c.run_function = module
    c.has_loop = True
    c.sample_rate = sample_rate
    c.timer_loop = time.time() + 10       # 점검 주기(15초) 격자는 아직 오지 않았다
    c._bad_rate_logged = False
    return c


def test_controller_calls_module_when_module_due_even_off_grid():
    m = _Module(60, start=time.time() - 1)
    c = _ctrl(m)
    c.loop()
    assert len(m.runs) == 1


def test_controller_skips_module_not_due_and_off_grid():
    m = _Module(60, start=time.time() + 30)
    c = _ctrl(m)
    c.loop()
    assert m.runs == []


def test_controller_seconds_until_due_follows_module():
    m = _Module(60, start=time.time() + 7)
    c = _ctrl(m)
    assert c.seconds_until_due() == pytest.approx(7, abs=0.2)
    c.has_loop = False
    assert c.seconds_until_due() is None


def test_controller_module_without_hook_keeps_old_grid():
    m = MagicMock(spec=['loop'])
    c = _ctrl(m)
    assert c.seconds_until_due() is None
    c.loop()
    m.loop.assert_not_called()          # 격자 전이고 모듈은 시각을 모른다
    c.timer_loop = time.time() - 1
    c.loop()
    m.loop.assert_called_once()         # 격자가 오면 예전처럼 부른다


def test_controller_module_hook_error_is_ignored():
    m = MagicMock(spec=['loop', 'seconds_until_due'])
    m.seconds_until_due.side_effect = RuntimeError('x')
    c = _ctrl(m)
    assert c.seconds_until_due() is None


@pytest.mark.parametrize('thread', [False, True])
def test_module_command_wakes_controller(thread):
    m = _Module(60, start=time.time() + 30)
    c = _ctrl(m)
    c.wake = MagicMock()
    ret = c.call_module_function('run_now', {}, thread=thread)
    assert ret[0] == 0
    deadline = time.monotonic() + 2
    while not c.wake.called and time.monotonic() < deadline:
        time.sleep(0.01)
    c.wake.assert_called_once()
    assert m.timer_loop == 0.0


def test_function_action_wakes_controller():
    m = _Module(60, start=time.time() + 30)
    c = _ctrl(m)
    c.wake = MagicMock()
    c.function_action('run_now', {}, thread=False)
    c.wake.assert_called_once()


def test_thread_runs_module_on_its_own_period_with_long_sample_rate():
    """실제 스레드: 점검 주기 15초, 모듈 주기 0.5초 → 0.5초 간격으로 돈다."""
    import aot.controllers.controller_function as cf
    m = _Module(0.5)
    c = object.__new__(cf.FunctionController)
    threading.Thread.__init__(c, daemon=True)
    AbstractController.__init__(c, threading.Event(), unique_id=None, name='test_function_due')
    c.run_function, c.has_loop, c._bad_rate_logged = m, True, False

    def init():
        c.sample_rate = 15.0
        c.timer_loop = time.time() + 10
        c.running = True
    c.initialize_variables = init
    c.run_finally = lambda: None
    c.start()
    try:
        deadline = time.monotonic() + 4
        while len(m.runs) < 4 and time.monotonic() < deadline:
            time.sleep(0.02)
        assert len(m.runs) >= 4, f'모듈이 제 주기에 돌지 않았다: {len(m.runs)}회'
        gaps = [b - a for a, b in zip(m.runs, m.runs[1:])]
        assert all(0.35 <= g <= 0.8 for g in gaps), gaps
    finally:
        c.stop_controller()
        c.join(2)
    assert not c.is_alive()
