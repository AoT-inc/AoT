# coding=utf-8
"""확인 실패(fault) 채널에는 "이미 켜져 있다" 를 믿지 않고 같은 명령도 다시 보낸다.

## 왜 이 테스트가 있나

2026-09-21 koat v341: 밸브 OFF 다운링크가 유실돼 확인이 오지 않았고, AoT 는
명령 전 상태(켜짐)로 되돌린 뒤 fault 를 붙였다. 사람이 켜기를 누르자
`output_on_off()` 가 로컬 캐시(켜짐)를 믿고 "is already on" 으로 돌려보내,
**다운링크가 한 건도 나가지 않았다.** 사람에게는 켤 수단이 없었고, 끄기를
먼저 보내 fault 를 푸는 우회만 통했다.

fault/offline 채널의 on/off 는 장치 상태가 아니라 추정값이다. 그것으로 명령을
걸러내면 안 된다.
"""
from unittest.mock import MagicMock

import pytest

from aot.outputs.base_output import AbstractOutput
from aot.utils.timekit import utc_now

CH = 0


class _Out(AbstractOutput):
    def __init__(self):  # noqa — 부모 초기화(DB·설정)를 건너뛴다
        pass

    def is_on(self, output_channel=0):
        return self._cached_on

    def is_setup(self):
        return True

    def confirmation_capable(self):
        return self._confirmable

    def output_switch(self, state, output_type=None, amount=None, output_channel=0):
        self.sent.append((state, amount))
        return 0


def make(cached_on=True, fault=False, offline=False, confirmable=True):
    o = object.__new__(_Out)
    o.unique_id = 'out-fault-test'
    o.output_name = 'v341'
    o.logger = MagicMock()
    o.output_type = 'chirpstack_downlink'
    o.output_types = {'on_off': ['chirpstack_downlink']}
    o.OUTPUT_INFORMATION = {'output_types': ['on_off']}
    o.options_channels = {'command_force': {CH: False}}
    o.output_states = {CH: cached_on}
    o._cached_on = cached_on
    o._confirmable = confirmable
    o.sent = []

    now = utc_now()
    o._command_dispatched = {}
    o.output_off_until = {CH: None}
    o.output_time_turned_on = {CH: now}
    o.output_on_duration = {CH: False}
    o.output_on_until = {CH: now}
    o.output_last_duration = {CH: 0}
    o.output_session_start = {CH: None}
    o.output_session_max = {CH: 0}
    o.output_off_triggered = {CH: False}
    o._started_at_written = {CH: False}
    o._ensure_started_marked = lambda ch: None
    o.defer_duration_to_confirm = lambda ch, amount: None
    o.supports_device_duration = lambda: False

    o._cmd_pending = {}
    o._cmd_fault_at = {CH: now} if fault else {}
    o._offline = {CH} if offline else set()
    return o


@pytest.mark.parametrize('fault,offline', [(True, False), (False, True)])
def test_on_is_sent_to_a_channel_whose_state_is_unknown(fault, offline):
    out = make(cached_on=True, fault=fault, offline=offline)
    code, msg = out.output_on_off('on', output_channel=CH, trigger_conditionals=False)
    assert code == 0, msg
    assert out.sent == [('on', None)], "fault 채널의 켜기가 전송되지 않았다"


def test_timed_on_is_sent_to_a_fault_channel():
    """시간 지정 켜기도 "이미 켜져 있다" 로 연장 처리하지 말고 보내야 한다."""
    out = make(cached_on=True, fault=True)
    out.output_on_duration[CH] = True
    code, msg = out.output_on_off('on', output_channel=CH, amount=60,
                                  trigger_conditionals=False)
    assert code == 0, msg
    assert out.sent == [('on', 60)]


def test_a_healthy_channel_still_refuses_a_redundant_on():
    """정상 채널의 중복 켜기 차단은 그대로다 — 이 수정은 fault 에만 적용된다."""
    out = make(cached_on=True, fault=False)
    code, msg = out.output_on_off('on', output_channel=CH, trigger_conditionals=False)
    assert code == 1 and 'already on' in msg
    assert out.sent == []


def test_a_one_way_output_is_unaffected():
    """확인 기능이 없는 출력은 fault 개념이 없으므로 기존 동작 그대로다."""
    out = make(cached_on=True, fault=True, confirmable=False)
    code, msg = out.output_on_off('on', output_channel=CH, trigger_conditionals=False)
    assert code == 1 and 'already on' in msg
    assert out.sent == []


def test_in_flight_identical_command_is_still_ignored():
    """확인 대기 중인 같은 명령은 여전히 무시한다(재전송 누적 방지). 대기 중이면
    fault 가 아니므로 새 판정에 걸리지 않는다."""
    out = make(cached_on=True, fault=True)
    out._cmd_pending = {CH: {'intent': 'on', 'deadline': utc_now().timestamp() + 30}}
    code, msg = out.output_on_off('on', output_channel=CH, trigger_conditionals=False)
    assert code == 0 and 'in flight' in msg
    assert out.sent == []
