# coding=utf-8
"""컨트롤러 루프가 점검 주기(sample_rate)가 아니라 '다음 할 일 시각' 에 깨어난다.

2026-11-12 맥북 8084 실측: 점검 주기를 15초로 둔 설치에서
- 시간 트리거가 격자보다 10~12초 늦게 발화했고(최대 15초),
- 출력의 '5초 켜짐' 이 약 15초 켜져 있었다(OFF 를 출력 루프가 15초마다만 봄).

본 것:
- `_loop_wait` = min(점검 주기, 다음 할 일까지), 지난 시각·NaN·예외·잘못된 주기 처리,
  할 일 시각이 계속 지나 있으면(타이머가 안 밀림) 바쁜 대기 대신 점검 주기로 물러섬.
- 실제 스레드: 점검 주기 15초여도 할 일 시각에 깨어나고, `wake()` 로 즉시 깨어나며,
  stop 은 바로 끝난다.
- 트리거·조건문·PID·출력의 '다음 할 일까지' 계산과, 출력 ON 이 루프를 깨우는 것.
"""
import datetime as dt
import threading
import time
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from aot.controllers.base_controller import AbstractController


class _Probe(AbstractController, threading.Thread):
    """기반 루프만 쓰는 시험용 컨트롤러."""

    def __init__(self, sample_rate=15.0, due=None):
        threading.Thread.__init__(self, daemon=True)
        super().__init__(threading.Event(), unique_id=None, name='test_probe')
        self.sample_rate_value = sample_rate
        self.due_at = due          # time.monotonic() 기준 할 일 시각, None 이면 없음
        self.calls = []

    def initialize_variables(self):
        self.sample_rate = self.sample_rate_value
        self.running = True

    def seconds_until_due(self):
        if self.due_at is None:
            return None
        return self.due_at - time.monotonic()

    def loop(self):
        now = time.monotonic()
        self.calls.append(now)
        if self.due_at is not None and now >= self.due_at:
            self.due_at = None     # 할 일을 했다

    def run_finally(self):
        pass


def _bare(sample_rate=15.0, due=None):
    p = object.__new__(_Probe)
    p.sample_rate = sample_rate
    p.logger = MagicMock()
    p._overdue_last_wait = False
    p.seconds_until_due = (lambda: due) if not callable(due) else due
    return p


# ---------------------------------------------------------------------------
# 대기 길이
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('due,expected', [
    (None, 15.0),
    (2.0, 2.01),
    (30.0, 15.0),
    (float('nan'), 15.0),
    ('abc', 15.0),
])
def test_loop_wait_is_min_of_rate_and_due(due, expected):
    assert _bare(15.0, due)._loop_wait() == pytest.approx(expected)


@pytest.mark.parametrize('rate', [None, 0, -1, 'x', float('nan')])
def test_bad_sample_rate_falls_back(rate):
    assert _bare(rate, None)._loop_wait() == pytest.approx(0.25)


def test_seconds_until_due_error_falls_back_to_rate():
    def boom():
        raise RuntimeError('x')
    p = _bare(15.0, boom)
    assert p._loop_wait() == 15.0
    p.logger.exception.assert_called()


def test_overdue_twice_backs_off_instead_of_busy_loop():
    """타이머가 앞으로 안 밀리면(주기 0 설정 등) 0.01초마다 돌지 않는다."""
    p = _bare(15.0, -5.0)
    assert p._loop_wait() == pytest.approx(0.01)
    assert p._loop_wait() == 15.0
    assert p._loop_wait() == pytest.approx(0.01)
    # 정상으로 돌아오면 표시도 풀린다
    p.seconds_until_due = lambda: 3.0
    assert p._loop_wait() == pytest.approx(3.01)


# ---------------------------------------------------------------------------
# 실제 스레드
# ---------------------------------------------------------------------------

def test_thread_wakes_at_due_not_at_sample_rate():
    p = _Probe(sample_rate=15.0)
    p.due_at = time.monotonic() + 0.4
    t0 = time.monotonic()
    p.start()
    try:
        deadline = t0 + 3
        while p.due_at is not None and time.monotonic() < deadline:
            time.sleep(0.02)
        assert p.due_at is None, '할 일 시각에 깨어나지 않았다'
        fired = p.calls[-1] - t0
        assert 0.35 <= fired < 1.0
    finally:
        p.stop_controller()
        p.join(2)
    assert not p.is_alive()


def test_wake_runs_loop_immediately():
    p = _Probe(sample_rate=15.0)
    p.start()
    try:
        time.sleep(0.2)
        before = len(p.calls)
        t0 = time.monotonic()
        p.wake()
        while len(p.calls) == before and time.monotonic() - t0 < 2:
            time.sleep(0.01)
        assert len(p.calls) > before
        assert time.monotonic() - t0 < 0.5
    finally:
        p.stop_controller()
        p.join(2)


def test_stop_is_immediate_with_long_sample_rate():
    p = _Probe(sample_rate=15.0)
    p.start()
    time.sleep(0.1)
    t0 = time.monotonic()
    p.stop_controller()
    p.join(2)
    assert not p.is_alive()
    assert time.monotonic() - t0 < 1.0


# ---------------------------------------------------------------------------
# 컨트롤러별 '다음 할 일까지'
# ---------------------------------------------------------------------------

def test_trigger_seconds_until_due():
    import aot.controllers.controller_trigger as ct
    c = object.__new__(ct.TriggerController)
    c.pause_loop, c.is_activated = False, True
    c.timer_period = time.time() + 3
    assert c.seconds_until_due() == pytest.approx(3, abs=0.2)
    c.pause_loop = True
    assert c.seconds_until_due() is None
    c.pause_loop, c.is_activated = False, False
    assert c.seconds_until_due() is None
    c.is_activated, c.timer_period = True, None
    assert c.seconds_until_due() is None


def test_conditional_seconds_until_due():
    import aot.controllers.controller_conditional as cc
    c = object.__new__(cc.ConditionalController)
    c.pause_loop, c.is_activated = False, True
    c.timer_period = time.time() + 7
    assert c.seconds_until_due() == pytest.approx(7, abs=0.2)
    c.is_activated = False
    assert c.seconds_until_due() is None


def test_pid_seconds_until_due_uses_monotonic():
    import aot.controllers.controller_pid as cp
    c = object.__new__(cp.PIDController)
    c.timer = time.monotonic() + 4
    assert c.seconds_until_due() == pytest.approx(4, abs=0.2)
    c.timer = 0
    assert c.seconds_until_due() is None


def _output_ctrl():
    import aot.controllers.controller_output as co
    c = object.__new__(co.OutputController)
    c.output = {}
    c.output_unique_id = {}
    c._auto_off_retry_at = {}
    c._on_origin = {}
    c.logger = MagicMock()
    return co, c


def _fake_output(until, duration=True, triggered=False, setup=True):
    return SimpleNamespace(output_setup=setup, output_on_until={0: until},
                           output_on_duration={0: duration},
                           output_off_triggered={0: triggered})


def test_output_seconds_until_due_picks_soonest_pending_off():
    co, c = _output_ctrl()
    now = co.utc_now()
    c.output = {
        'a': _fake_output(now + dt.timedelta(seconds=5)),
        'b': _fake_output(now + dt.timedelta(seconds=2), triggered=True),    # 이미 끄는 중
        'c': _fake_output(now + dt.timedelta(seconds=1), duration=False),    # 지속 시간 없음
        'd': _fake_output(now + dt.timedelta(seconds=1), setup=False),       # 준비 안 됨
        'e': _fake_output(None),
    }
    c.output_unique_id = {k: [0] for k in c.output}
    assert c.seconds_until_due() == pytest.approx(5, abs=0.2)


def test_output_seconds_until_due_respects_retry_backoff():
    co, c = _output_ctrl()
    now = co.utc_now()
    c.output = {'a': _fake_output(now - dt.timedelta(seconds=1))}
    c.output_unique_id = {'a': [0]}
    c._auto_off_retry_at[('a', 0)] = time.monotonic() + 10
    assert c.seconds_until_due() == pytest.approx(10, abs=0.2)


def test_output_seconds_until_due_none_when_nothing_pending():
    _, c = _output_ctrl()
    assert c.seconds_until_due() is None


@pytest.mark.parametrize('state,ret,woken', [
    ('on', (0, 'ok'), True),
    ('on', (1, 'fail'), False),
    ('off', (0, 'ok'), False),
])
def test_output_on_wakes_loop(state, ret, woken):
    _, c = _output_ctrl()
    c.output = {'a': MagicMock(output_on_off=MagicMock(return_value=ret))}
    c._interlock_paired_legs = MagicMock()
    c._audit_command = MagicMock()
    c.wake = MagicMock()
    c.output_on_off('a', state, output_channel=0, amount=5)
    assert c.wake.called is woken


def test_output_auto_off_on_time_with_long_sample_rate():
    """출력 루프를 실제 스레드로: 점검 주기 15초여도 0.5초 켜짐이 제때 꺼진다."""
    co, c = _output_ctrl()
    threading.Thread.__init__(c, daemon=True)
    AbstractController.__init__(c, threading.Event(), unique_id=None, name='test_output')
    c.output, c.output_unique_id = {}, {}
    c._auto_off_retry_at, c._on_origin = {}, {}
    off_at = []
    out = _fake_output(None)
    c.output['a'] = out
    c.output_unique_id['a'] = [0]

    def fake_on_off(output_id, state, output_channel=0, origin=None, **kw):
        if state == 'off':
            off_at.append(time.monotonic())
            out.output_on_duration[0] = False
        return 0, 'ok'
    c.output_on_off = fake_on_off
    c.initialize_variables = lambda: setattr(c, 'sample_rate', 15.0) or setattr(c, 'running', True)
    c.run_finally = lambda: None
    c.start()
    try:
        time.sleep(0.2)                  # 루프가 15초 대기에 들어간다
        t0 = time.monotonic()
        out.output_on_until[0] = co.utc_now() + dt.timedelta(seconds=0.5)
        out.output_on_duration[0] = True
        out.output_off_triggered[0] = False
        c.wake()                         # 실제로는 output_on_off('on') 이 부른다
        while not off_at and time.monotonic() - t0 < 3:
            time.sleep(0.02)
        assert off_at, '꺼지지 않았다'
        assert 0.45 <= off_at[0] - t0 < 1.2
    finally:
        c.stop_controller()
        c.join(2)
