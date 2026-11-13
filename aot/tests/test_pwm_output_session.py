# coding=utf-8
"""PWM 출력의 "작동 구간" 장부 — 듀티 0 <-> 양수 전환 시점에만 열고 닫는다.

## 왜 이 테스트가 있나 (2026-11-11 PWM 위젯 시간 동작 점검)

PWM 분기는 on/off 출력과 달리 작동 구간 장부(`output_time_turned_on`)를 아예
쓰지 않았다. 그 결과 세 가지가 어긋났다.

- R2: 켰다 꺼도 `duration_time` 이 기록되지 않는다 — 위젯의 "마지막 작동" 이 늘 비고
  누적 가동 시간 집계에서 PWM 이 빠진다.
- R3: PID·bang-bang·트리거는 끌 때 `on pwm 0` 을 보낸다. 시작 표지는 `off` 에서만
  초기화되므로 0 -> 40 으로 다시 켜도 새 표지가 안 써져, 꺼져 있던 시간까지 이어
  "N시간째 작동" 으로 보인다.
- R4: 데몬 재시작 때 드라이버가 시작 듀티를 `output_on_off` 를 거치지 않고 직접
  거므로 시작 표지가 없다. 그 뒤 첫 듀티 변경이 "새 시작" 이 된다.

같은 듀티를 주기마다 다시 보내는 자동화(PID 등)가 기록을 늘리면 안 되므로,
**전환 시점에만** 처리하는 것이 핵심이다.
"""
from datetime import timedelta
from unittest.mock import MagicMock, patch

import pytest

from aot.outputs.base_output import AbstractOutput
from aot.utils.timekit import utc_now

CH = 0


class Clock:
    def __init__(self):
        self.now = utc_now()

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now = self.now + timedelta(seconds=seconds)


class FakePwm(AbstractOutput):
    """장부만 갖춘 PWM 출력. 하드웨어는 `duty` 한 칸."""

    def __init__(self, clock):
        self.logger = MagicMock()
        self.unique_id = 'pwm-test'
        self.output_name = 'fan'
        self.output = MagicMock()
        self.output_type = 'pwm_gpio'
        self.output_types = {'pwm': ['pwm_gpio'], 'on_off': [], 'value': [], 'volume': []}
        self.OUTPUT_INFORMATION = {
            'output_types': ['pwm'],
            'channels_dict': {CH: {'measurements': [0]}},
            'measurements_dict': {0: {'unit': 'percent'}}}
        self.options_channels = {'state_shutdown': {CH: 0}}
        self.output_states = {CH: None}
        self.output_time_turned_on = {CH: None}
        self.output_on_duration = {CH: False}
        self.output_last_duration = {CH: 0}
        self.output_on_until = {CH: clock()}
        self.output_off_until = {CH: 0}
        self.output_off_triggered = {CH: False}
        self._started_at_written = {CH: False}
        self.output_session_start = {CH: None}
        self.output_session_max = {CH: 0}
        self._command_dispatched = {}
        self.duty = 0
        self.output_setup = True
        self.starts = 0

    def _confirm_init(self): pass
    def is_setup(self): return True
    def is_on(self, output_channel=None): return self.duty or False
    def confirmation_capable(self): return False
    def comm_is_fault(self, c=0): return False
    def comm_is_pending(self, c=0): return False
    def _state_unknown(self, c=0): return False
    def is_pending(self, c=0): return False
    def stop_output(self): pass

    def output_switch(self, state, output_type=None, amount=None,
                      output_channel=None, additional_options=None):
        self.duty = amount if state == 'on' else 0

    def check_triggers(self, *a, **k): pass
    def _write_output_started_at_async(self, ch): self.starts += 1


@pytest.fixture
def clock():
    c = Clock()
    with patch('aot.outputs.base_output.utc_now', c):
        yield c


@pytest.fixture
def writes():
    """duration_time 으로 넘어간 (초, 시각) 목록."""
    with patch('aot.outputs.base_output.threading.Thread') as thread:
        class W:
            @property
            def values(self_inner):
                return [c.kwargs['args'][2] for c in thread.call_args_list]
        yield W()


def on(o, duty):
    return o.output_on_off('on', output_channel=CH, output_type='pwm', amount=duty)


def off(o):
    return o.output_on_off('off', output_channel=CH, output_type='sec', amount=0)


def test_r3_on_pwm_zero_closes_the_session_and_next_on_restarts_it(clock, writes):
    """핵심 회귀(R3). 60 -> 0 -> 40 이면 시작 표지가 두 번, 개방 시간 기록은 한 번."""
    o = FakePwm(clock)
    on(o, 60)
    clock.advance(600)
    on(o, 0)                      # 자동화의 "끄기"
    assert o.starts == 1
    assert writes.values == [pytest.approx(600.0)]
    assert o.output_time_turned_on[CH] is None
    clock.advance(3600)           # 꺼져 있던 한 시간
    on(o, 40)
    assert o.starts == 2          # 새 시작 표지 — 경과가 꺼진 시간부터 이어지지 않는다


def test_r2_on_then_off_records_the_open_time(clock, writes):
    """R2. 켰다 끄면 열려 있던 시간이 duration_time 으로 남는다."""
    o = FakePwm(clock)
    on(o, 60)
    clock.advance(125)
    off(o)
    assert writes.values == [pytest.approx(125.0)]
    # 슬라이더 off 뒤 다음 ON 도 새 표지
    on(o, 30)
    assert o.starts == 2


def test_same_duty_resent_every_period_adds_nothing(clock, writes):
    """PID·bang-bang 이 주기마다 같은(또는 다른 양수) 듀티를 보내도 기록·표지가 늘지 않는다."""
    o = FakePwm(clock)
    for duty in (60, 60, 60, 70, 55):
        on(o, duty)
        clock.advance(10)
    assert o.starts == 1
    assert writes.values == []


def test_on_pwm_zero_while_off_writes_nothing(clock, writes):
    """꺼져 있는데 0 을 보내면 시작 표지도 개방 시간 기록도 없다."""
    o = FakePwm(clock)
    on(o, 0)
    on(o, 0)
    assert o.starts == 0
    assert writes.values == []


def test_r4_boot_adopts_a_running_startup_duty(clock, writes):
    """R4. 드라이버가 시작 듀티를 직접 걸었으면 기동 훅이 그 순간을 시작으로 적는다."""
    o = FakePwm(clock)
    o.duty = 60                   # 시작 상태가 이미 걸림
    o.adopt_running_pwm()
    assert o.starts == 1
    clock.advance(30)
    on(o, 70)                     # 이어진 듀티 변경은 새 시작이 아니다
    assert o.starts == 1
    clock.advance(30)
    off(o)
    assert writes.values == [pytest.approx(60.0)]


def test_r4_boot_with_duty_off_does_nothing(clock, writes):
    o = FakePwm(clock)
    o.duty = 0
    o.adopt_running_pwm()
    assert o.starts == 0
    assert o.output_time_turned_on[CH] is None


def test_shutdown_records_the_open_time_of_a_pwm_session(clock, writes):
    """종료로 꺼지는 PWM 의 개방 시간도 남는다(Shutdown State = Off)."""
    o = FakePwm(clock)
    on(o, 60)
    clock.advance(90)
    o.shutdown(0.0)
    assert writes.values == [pytest.approx(90.0)]
