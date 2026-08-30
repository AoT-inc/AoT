# coding=utf-8
"""데몬이 내려갈 때 켜져 있던 출력의 **개방 시간**이 남는가.

## 왜 이 테스트가 있나

종료 경로는 드라이버의 `stop_output()` 이 하드웨어를 직접 끈다 —
`output_on_off()` 를 지나지 않으므로 개방 시간을 적는 코드가 돌지 않는다.
그래서 재시작을 낀 관수는 조각조각 사라지고, 마지막 조각만 남는다.

실측(2026-08-30 로컬, 3포장 v2 시퀀스): v331/v332 는 12:30~13:00 로 30분이
예정돼 있었는데 12:51 과 12:54 두 번의 재시작을 거쳐 **301초(5분)** 만
기록됐다. 앞의 21분과 3분은 어디에도 없다 — 조회하면 5분만 물을 준 것으로
보인다. 실제로는 30분 가까이 열려 있었다.

재시작 뒤 시퀀스는 남은 시간만큼만 다시 켜므로(`_resync_after_resume`),
종료 시점마다 그때까지의 개방 시간을 적으면 조각의 합이 실제 개방 시간이 된다.
"""
from datetime import timedelta
from unittest.mock import MagicMock, patch

import pytest

from aot.outputs.base_output import AbstractOutput
from aot.utils.timekit import utc_now

CH = 0


def make_output(state_shutdown=0, turned_on_ago=None, timed=None):
    """장부만 갖춘 출력.

    `turned_on_ago`: 무기한 ON 이 몇 초 전이었나.
    `timed`: (총 지속시간, 남은 시간) — duration 을 지정해 켠 경우.
    """
    inst = object.__new__(AbstractOutput)
    inst.unique_id = 'out-test-0000'
    inst.output_name = 'v331'
    inst.logger = MagicMock()
    inst.OUTPUT_INFORMATION = {}
    inst.options_channels = {'state_shutdown': {CH: state_shutdown}}

    now = utc_now()
    inst.output_time_turned_on = {CH: None}
    inst.output_on_duration = {CH: False}
    inst.output_on_until = {CH: now}
    inst.output_last_duration = {CH: 0}
    inst.output_session_start = {CH: None}
    inst.output_session_max = {CH: 0}

    if turned_on_ago is not None:
        inst.output_time_turned_on[CH] = now - timedelta(seconds=turned_on_ago)
    if timed is not None:
        total, remaining = timed
        inst.output_on_duration[CH] = True
        inst.output_last_duration[CH] = total
        inst.output_on_until[CH] = now + timedelta(seconds=remaining)
    return inst


def written_durations(mock_thread):
    """write 스레드에 넘어간 duration 값들."""
    return [call.kwargs['args'][2] if 'args' in call.kwargs else call[1]['args'][2]
            for call in mock_thread.call_args_list]


@pytest.fixture
def spy_thread():
    with patch('aot.outputs.base_output.threading.Thread') as thread:
        yield thread


def test_shutdown_records_the_open_time(spy_thread):
    """핵심 회귀. 21분째 열려 있는데 데몬이 내려간다 — 그 21분이 남아야 한다."""
    out = make_output(turned_on_ago=1316.0)
    out.stop_output = MagicMock()

    out.shutdown(0.0)

    assert spy_thread.call_count == 1
    kwargs = spy_thread.call_args.kwargs
    assert kwargs['args'][0] == out.unique_id
    assert kwargs['args'][1] == 's'
    assert kwargs['args'][2] == pytest.approx(1316.0, abs=2.0)
    assert kwargs['kwargs']['measure'] == 'duration_time'
    out.stop_output.assert_called_once()


def test_shutdown_records_the_elapsed_part_of_a_timed_run(spy_thread):
    """30분 예정으로 켠 지 25분 — 지난 25분만 적는다(예정된 30분이 아니라)."""
    out = make_output(timed=(1800.0, 300.0))
    out.stop_output = MagicMock()

    out.shutdown(0.0)

    assert spy_thread.call_args.kwargs['args'][2] == pytest.approx(1500.0, abs=2.0)


def test_channel_that_stays_on_is_not_recorded(spy_thread):
    """종료해도 안 꺼지는 채널은 아직 열려 있다 — 닫혔다고 적으면 틀린 기록이다."""
    out = make_output(state_shutdown=1, turned_on_ago=1316.0)
    out.stop_output = MagicMock()

    out.shutdown(0.0)

    spy_thread.assert_not_called()


def test_idle_output_writes_nothing(spy_thread):
    out = make_output()
    out.stop_output = MagicMock()

    out.shutdown(0.0)

    spy_thread.assert_not_called()


def test_recording_twice_does_not_double_count(spy_thread):
    """장부는 한 번만 닫힌다 — OFF 와 종료가 겹쳐도 두 번 적히지 않는다."""
    out = make_output(turned_on_ago=600.0)
    now = utc_now()

    assert out._record_on_duration(CH, now) is True
    assert out._record_on_duration(CH, now) is False
    assert spy_thread.call_count == 1


def test_a_write_failure_does_not_block_shutdown(spy_thread):
    """기록은 부수적이다 — 실패해도 출력은 반드시 꺼져야 한다."""
    spy_thread.side_effect = RuntimeError("influx down")
    out = make_output(turned_on_ago=600.0)
    out.stop_output = MagicMock()

    out.shutdown(0.0)

    out.stop_output.assert_called_once()


def test_missing_shutdown_option_is_treated_as_stays_on(spy_thread):
    """옵션을 못 읽으면 꺼진다고 단정하지 않는다 — 모르는 채 적는 것이 더 나쁘다."""
    out = make_output(turned_on_ago=600.0)
    out.options_channels = {}
    out.stop_output = MagicMock()

    out.shutdown(0.0)

    spy_thread.assert_not_called()
