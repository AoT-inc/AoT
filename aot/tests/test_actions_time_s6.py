# coding=utf-8
"""Function 액션의 시간 처리 (Function 시간 점검 S6).

- output_ramp_pwm: duration 0(설정 기본값)이 **무한 루프**였고, 단계 사이를
  sleep 없이 시계만 보는 바쁜 루프였으며, 벽시계(time.time)로 경과를 쟀다.
- pause_actions: 음수·문자열 duration 이 TypeError/ValueError 로 액션을 죽였다.
- output_on_off: 문자열·None duration 이 출력 쪽 abs() 에서 TypeError.
- get_condition_value: measurement_past_average 가 창 안에 측정이 없으면
  ZeroDivisionError.
"""
import threading
from unittest.mock import MagicMock, patch

import pytest

from aot.actions import base_action, output_on_off, output_ramp_pwm, pause_actions
from aot.actions.base_action import coerce_seconds
from aot.actions.output_ramp_pwm import ramp_plan


# ---------------------------------------------------------------- 공통 ----

def _module(mod):
    """DB·데몬 없이 액션 모듈 인스턴스를 만든다(__init__ 우회)."""
    inst = object.__new__(mod.ActionModule)
    inst.logger = MagicMock()
    inst.control = MagicMock()
    inst.running = True
    inst.output_channel_id = None
    return inst


@pytest.fixture(autouse=True)
def _inline_threads(monkeypatch):
    """run_in_thread 를 동기로 — 호출 인자를 control 에서 바로 본다."""
    def _run(target, args=(), kwargs=None):
        target(*args, **(kwargs or {}))
    monkeypatch.setattr(output_ramp_pwm, 'run_in_thread', _run)
    monkeypatch.setattr(output_on_off, 'run_in_thread', _run)


# ----------------------------------------------------------- coerce_seconds

@pytest.mark.parametrize('raw,expected', [
    (30, 30.0), ('30', 30.0), (' 2.5 ', 2.5), (-5, -5.0), (0, 0.0),
    (None, 0.0), ('', 0.0), ('abc', 0.0), (float('nan'), 0.0),
    (float('inf'), 0.0),
])
def test_coerce_seconds(raw, expected):
    assert coerce_seconds(raw) == expected


# ---------------------------------------------------------------- ramp_plan

def test_ramp_plan_up_ends_exactly_on_end_within_duration():
    start, steps, interval = ramp_plan(0, 10, 3, 12)
    assert start == 0
    assert steps == [3, 6, 9, 10]            # 증분이 나누어떨어지지 않아도 end 로 끝
    assert interval * len(steps) == pytest.approx(12)   # 전체가 duration 안


def test_ramp_plan_down():
    _, steps, interval = ramp_plan(100, 40, 20, 30)
    assert steps == [80, 60, 40]
    assert interval == pytest.approx(10)


def test_ramp_plan_duration_zero_jumps_to_end_without_waiting():
    """기본값 duration=0.0 이 예전에는 무한 루프였다."""
    assert ramp_plan(10, 50, 1, 0) == (10, [50], 0.0)


def test_ramp_plan_start_equals_end_is_single_write():
    """예전에는 steps=0 으로 ZeroDivisionError."""
    assert ramp_plan(30, 30, 1, 60) == (30, [], 0.0)


@pytest.mark.parametrize('args', [
    (0, 10, 0, 5), (0, 10, -1, 5), (0, 10, 1, -5), ('x', 10, 1, 5),
    (0, 10, None, 5), (0, 10, 1, None),
])
def test_ramp_plan_rejects_unusable_input(args):
    assert ramp_plan(*args) is None


def test_ramp_plan_accepts_strings():
    assert ramp_plan('0', '4', '2', '8') == (0.0, [2.0, 4.0], 4.0)


# ------------------------------------------------------- ramp run_action ---

def _ramp_instance(**opts):
    inst = _module(output_ramp_pwm)
    inst.output_device_id = 'out-1'
    inst.get_output_channel_from_channel_id = lambda _c: 0
    inst.start, inst.end, inst.increment, inst.duration = (
        opts.get('start', 0.0), opts.get('end', 50.0),
        opts.get('increment', 25.0), opts.get('duration', 0.0))
    return inst


def _run_ramp(inst, dict_vars=None):
    out = MagicMock()
    out.name = 'PWM'
    with patch.object(output_ramp_pwm, 'db_retrieve_table_daemon', return_value=out):
        return inst.run_action(dict_vars if dict_vars is not None else {'message': ''})


def _amounts(inst):
    return [c.kwargs['amount'] for c in inst.control.output_on.call_args_list]


def test_ramp_duration_zero_terminates_and_sets_end():
    inst = _ramp_instance(duration=0.0)
    result = {}

    def go():
        result['v'] = _run_ramp(inst)
    t = threading.Thread(target=go, daemon=True)
    t.start()
    t.join(5)
    assert not t.is_alive(), 'duration 0 램프가 끝나지 않는다(무한 루프)'
    assert _amounts(inst) == [0.0, 50.0]


def test_ramp_start_equals_end_does_not_raise():
    inst = _ramp_instance(start=20.0, end=20.0, increment=1.0, duration=10.0)
    _run_ramp(inst)
    assert _amounts(inst) == [20.0]


def test_ramp_invalid_increment_reports_error_and_does_not_touch_output():
    inst = _ramp_instance(increment=0.0, duration=10.0)
    out = _run_ramp(inst)
    assert 'Error' in out['message']
    inst.control.output_on.assert_not_called()


def test_ramp_sleeps_between_steps_instead_of_spinning(monkeypatch):
    """단계 사이는 sleep, 경과는 단조 시계(time.monotonic)로."""
    clock = {'t': 1000.0}
    sleeps = []

    def fake_sleep(sec):
        sleeps.append(sec)
        clock['t'] += sec

    monkeypatch.setattr(output_ramp_pwm.time, 'monotonic', lambda: clock['t'])
    monkeypatch.setattr(output_ramp_pwm.time, 'sleep', fake_sleep)
    # 벽시계가 거꾸로 가도(NTP 보정) 램프 시간에 영향이 없어야 한다.
    monkeypatch.setattr(output_ramp_pwm.time, 'time', lambda: 1.0)

    inst = _ramp_instance(start=0.0, end=50.0, increment=25.0, duration=20.0)
    _run_ramp(inst)
    assert _amounts(inst) == [0.0, 25.0, 50.0]
    assert sum(sleeps) == pytest.approx(20.0)
    assert len(sleeps) == 2


def test_ramp_value_override_as_strings():
    inst = _ramp_instance()
    _run_ramp(inst, {'message': '', 'value': {
        'start': '10', 'end': '30', 'increment': '10', 'duration': '0'}})
    assert _amounts(inst) == [10.0, 30.0]


def test_ramp_without_message_key_does_not_keyerror():
    inst = _ramp_instance()
    out = _run_ramp(inst, {})
    assert 'Ramp output' in out['message']


# ------------------------------------------------------------------ pause ---

def _pause(duration, value=None):
    inst = _module(pause_actions)
    inst.duration = duration
    d = {'message': ''}
    if value is not None:
        d['value'] = value
    with patch.object(pause_actions.time, 'sleep') as sl:
        out = inst.run_action(d)
    return out, sl


def test_pause_sleeps_configured_seconds():
    out, sl = _pause(2.5)
    sl.assert_called_once_with(2.5)
    assert 'Pause for 2.5 seconds' in out['message']


def test_pause_negative_does_not_raise_and_does_not_sleep():
    """time.sleep(-1) 은 ValueError — 뒤따르는 액션까지 끊었다."""
    out, sl = _pause(-1)
    sl.assert_not_called()
    assert 'Pause for 0 seconds' in out['message']


def test_pause_string_value_override():
    out, sl = _pause(1.0, value={'duration': '3'})
    sl.assert_called_once_with(3.0)


def test_pause_none_duration_is_no_pause():
    out, sl = _pause(None)
    sl.assert_not_called()


# ------------------------------------------------------------- output_on_off

def _onoff(state='on', duration=0.0, value=None):
    inst = _module(output_on_off)
    inst.output_device_id = 'out-1'
    inst.get_output_channel_from_channel_id = lambda _c: 0
    inst.state, inst.duration = state, duration
    out = MagicMock()
    out.name = 'Valve'
    d = {'message': ''}
    if value is not None:
        d['value'] = value
    with patch.object(output_on_off, 'db_retrieve_table_daemon', return_value=out):
        res = inst.run_action(d)
    return inst, res


def test_on_off_duration_goes_out_as_float_seconds():
    inst, res = _onoff(duration=300.0)
    inst.control.output_on_off.assert_called_once_with(
        'out-1', 'on', output_type='sec', amount=300.0, output_channel=0)
    assert 'for 300 seconds' in res['message']


def test_on_off_string_duration_is_coerced():
    inst, _ = _onoff(value={'duration': '90'})
    assert inst.control.output_on_off.call_args.kwargs['amount'] == 90.0


def test_on_off_none_or_garbage_duration_means_stay_on():
    for bad in (None, 'abc'):
        inst, res = _onoff(value={'duration': bad})
        assert inst.control.output_on_off.call_args.kwargs['amount'] == 0.0
        assert 'seconds' not in res['message']


def test_on_off_negative_duration_keeps_sign():
    """음수 지속 시간은 출력 쪽에서 역방향 구동을 뜻할 수 있어 부호를 보존한다."""
    inst, _ = _onoff(value={'duration': -5})
    assert inst.control.output_on_off.call_args.kwargs['amount'] == -5.0


# ---------------------------------------- get_condition_value / 과거 평균 ---

def test_past_average_with_no_measurements_returns_none_not_zerodivision():
    from aot.utils import actions as ua

    cond = MagicMock()
    cond.condition_type = 'measurement_past_average'
    cond.measurement = 'dev-1,meas-1'
    cond.max_age = 300
    query = MagicMock()
    query.filter.return_value.first.return_value = cond

    with patch.object(ua, 'db_retrieve_table_daemon') as db, \
            patch.object(ua, 'return_measurement_info', return_value=(0, 'C', 'temperature')), \
            patch.object(ua, 'get_past_measurements', return_value=[]):
        db.side_effect = lambda *a, **k: query if not k else MagicMock()
        assert ua.get_condition_value('c-1') is None


def test_past_average_still_averages():
    from aot.utils import actions as ua

    cond = MagicMock()
    cond.condition_type = 'measurement_past_average'
    cond.measurement = 'dev-1,meas-1'
    cond.max_age = 300
    query = MagicMock()
    query.filter.return_value.first.return_value = cond

    with patch.object(ua, 'db_retrieve_table_daemon') as db, \
            patch.object(ua, 'return_measurement_info', return_value=(0, 'C', 'temperature')), \
            patch.object(ua, 'get_past_measurements',
                         return_value=[(1, '10'), (2, 20)]):
        db.side_effect = lambda *a, **k: query if not k else MagicMock()
        assert ua.get_condition_value('c-1') == 15.0
