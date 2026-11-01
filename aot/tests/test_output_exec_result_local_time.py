# coding=utf-8
"""출력 켜기·끄기 결과 문구의 시각이 같은 형식(장치 위치 현지 시각)인가.

실측(2026-10-29, 개발서버): 같은 출력 장치의 MCP 응답 `execution_result` 가
- 켜기: "... ON at 2026-10-29 04:09:41.908037+00:00 ..."  (UTC, 마이크로초)
- 끄기: "... OFF at 2026-10-29 13:09:54 ..."                (서버 프로세스 현지, 오프셋 없음)
으로 서로 달랐다. 켜기는 aware UTC datetime 을 문자열로 찍었고, 끄기는
`datetime.fromtimestamp()` 로 naive 서버 시각을 찍었기 때문이다.
이제 둘 다 `AbstractOutput._local_stamp()` 를 거쳐 장치 현지 시각·초 단위·오프셋
포함(`2026-10-29T13:09:41+09:00`)으로 나온다.
"""
import re
from types import SimpleNamespace
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from aot.outputs.base_output import AbstractOutput

CH = 0
ISO_SEC_OFFSET = re.compile(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[+-]\d{2}:\d{2}')
UTC_INSTANT = datetime(2026, 10, 29, 4, 9, 41, 908037, tzinfo=timezone.utc)


def make_output(timezone_name='Asia/Seoul'):
    inst = object.__new__(AbstractOutput)
    inst.unique_id = 'out-test-0000'
    inst.output_name = 'v311'
    inst.output_type = 'on_off_gpio'
    inst.logger = MagicMock()
    inst.OUTPUT_INFORMATION = {'output_types': ['on_off']}
    inst.output_types = {'on_off': ['on_off_gpio'], 'pwm': [], 'volume': []}
    inst.options_channels = {'command_force': {CH: False}, 'state_shutdown': {CH: 0}}
    inst.output_time_turned_on = {CH: None}
    inst.output_on_duration = {CH: False}
    inst.output_on_until = {CH: UTC_INSTANT}
    inst.output_last_duration = {CH: 0}
    inst.output_session_start = {CH: None}
    inst.output_session_max = {CH: 0}
    inst.output_off_triggered = {CH: False}
    inst.output_off_until = {CH: None}
    inst._command_dispatched = {}
    inst._started_at_written = {}
    inst.output_states = {CH: None}
    inst.is_setup = lambda: True
    # 장치 row 흉내 — MagicMock 은 resolve_timezone 이 있는 도형으로 오인된다.
    inst.output = SimpleNamespace(unique_id='out-test-0000', timezone=timezone_name,
                                  tz_source='coords', latitude=35.0, longitude=127.0)
    return inst


def test_stamp_is_device_local_seconds_with_offset():
    out = make_output('Asia/Seoul')
    assert out._local_stamp(UTC_INSTANT) == '2026-10-29T13:09:41+09:00'


def test_stamp_follows_the_device_not_the_server():
    """다른 대륙의 장치는 그 장소의 시각·오프셋으로 나온다(시간대 하드코딩 없음)."""
    out = make_output('America/Los_Angeles')
    assert out._local_stamp(UTC_INSTANT) == '2026-10-28T21:09:41-07:00'


def test_naive_input_is_treated_as_utc():
    out = make_output('Asia/Seoul')
    assert out._local_stamp(UTC_INSTANT.replace(tzinfo=None)) == '2026-10-29T13:09:41+09:00'


def test_unknown_location_uses_farm_default_tz():
    """장치 위치를 모르면 기존 해석 체인의 농장 기본 시간대(Misc.timezone)를 쓴다."""
    out = make_output(timezone_name=None)
    out.output.latitude = None
    out.output.longitude = None
    with patch('aot.utils.timekit.system_tz_name', return_value='Asia/Seoul'), \
            patch('aot.utils.timekit._inherited_tz_for_device', return_value=None):
        assert out._local_stamp(UTC_INSTANT) == '2026-10-29T13:09:41+09:00'


def test_nothing_known_falls_back_to_utc():
    out = make_output(timezone_name=None)
    out.output.latitude = None
    out.output.longitude = None
    with patch('aot.utils.timekit.system_tz_name', return_value=None), \
            patch('aot.utils.timekit._inherited_tz_for_device', return_value=None):
        assert out._local_stamp(UTC_INSTANT) == '2026-10-29T04:09:41+00:00'


def test_resolver_failure_does_not_break_the_message():
    out = make_output()
    with patch('aot.outputs.base_output.resolve_tz', side_effect=RuntimeError('detached')), \
            patch('aot.outputs.base_output.system_tz') as sys_tz:
        import pytz
        sys_tz.return_value = pytz.timezone('Asia/Seoul')
        assert out._local_stamp(UTC_INSTANT) == '2026-10-29T13:09:41+09:00'


def _run(out, state):
    out.output_switch = MagicMock(return_value=None)
    out._ensure_started_marked = MagicMock()
    out._record_on_duration = MagicMock()
    out.confirmation_capable = MagicMock(return_value=False)
    out.check_triggers = MagicMock()
    out.is_on = MagicMock(return_value=(state == 'off'))
    return out.output_on_off(state, output_channel=CH, trigger_conditionals=False)


def _logged(out):
    return ' '.join(str(c.args[0]) for c in out.logger.debug.call_args_list if c.args)


@pytest.mark.parametrize('state,word', [('on', 'ON'), ('off', 'OFF')])
def test_on_and_off_messages_share_one_format(state, word):
    out = make_output('Asia/Seoul')
    _run(out, state)
    text = _logged(out)
    m = re.search(rf'{word} at (\S+)\.', text)
    assert m, text
    assert ISO_SEC_OFFSET.fullmatch(m.group(1)), m.group(1)
    assert m.group(1).endswith('+09:00')
