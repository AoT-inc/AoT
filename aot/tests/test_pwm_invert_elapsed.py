# coding=utf-8
"""Invert Signal 을 켠 PWM 채널의 경과 시간·상태가 요청 듀티를 따른다.

## 왜 이 테스트가 있나 (2026-11-11 PWM 위젯 시간 동작 점검, R5)

`/outputstate_unique_id` 는 반전 채널의 물리 듀티를 100 - x 로 되돌려 보여 주는데
`runtime.get_elapsed_seconds` 는 물리값을 그대로 써서 둘이 반대로 갔다.
요청 0% (물리 100) 인데 경과가 흐르고, 요청 100% (물리 0) 는 `'off'` 문자열이
보정 없이 내려와 "0%" 로 보이고 경과도 0 이었다.
"""
import time
from unittest.mock import patch

import pytest

from aot.utils import runtime
from aot.utils.outputs import pwm_logical_state


@pytest.mark.parametrize('state, invert, expected', [
    (60.0, False, 60.0),
    ('off', False, 'off'),
    (None, False, None),
    (100.0, True, 0.0),         # 물리 100 = 요청 0%
    (20.0, True, 80.0),
    ('off', True, 100.0),       # 물리 0 (is_on False) = 요청 100%
    ('pending', True, 'pending'),
    ('fault', True, 'fault'),
    (None, True, None),
])
def test_pwm_logical_state(state, invert, expected):
    assert pwm_logical_state(state, invert) == expected


def _elapsed(physical_state, invert):
    started = int(time.time()) - 3600
    with patch.object(runtime, 'DaemonControl') as dc, \
            patch.object(runtime, 'get_started_at', return_value=started), \
            patch.object(runtime, 'get_pwm_invert_signal', return_value=invert):
        dc.return_value.output_state.return_value = physical_state
        return runtime.get_elapsed_seconds('u', 0)


def test_inverted_requested_zero_percent_is_not_running():
    assert _elapsed(100.0, invert=True) == 0


def test_inverted_requested_full_is_running_even_though_state_is_off():
    assert _elapsed('off', invert=True) >= 3600


def test_inverted_partial_duty_is_running():
    assert _elapsed(20.0, invert=True) >= 3600


def test_not_inverted_is_unchanged():
    assert _elapsed(60.0, invert=False) >= 3600
    assert _elapsed('off', invert=False) == 0
