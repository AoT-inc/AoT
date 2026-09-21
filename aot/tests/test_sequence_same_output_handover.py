# coding=utf-8
"""같은 출력은 스텝·사이클 경계에서 **끊지 않고 이어받는다**.

## 왜 이 테스트가 있나

스텝이 주기를 꽉 채우는 설정(스텝 하나짜리 시퀀스, 주기 전체를 도는 펌프 total)
에서는 지난 사이클의 마지막 스텝과 새 사이클의 첫 스텝이 같은 출력을 쓴다. 예전
`start_new_cycle()` 은 경계에서 전부 끄고 곧바로 다시 켜서, 같은 출력에 **수
밀리초 간격으로 OFF→ON** 이 나갔다. 펄스로 구동하는 밸브는 CLOSE 코일이 도는
중에 OPEN 이 오고, 펌프는 매 주기 멈췄다 선다(보고: C동 예전 설정, 2026-09-21).

그리고 더 나쁜 경우가 있었다. 사이클 **안에서** 이웃한 두 스텝이 같은 출력을
쓰면(그룹 a·b 가 액비 밸브를 함께 씀) 새 스텝을 먼저 켜고(이미 켜져 있음) 옛
스텝을 끄므로, **출력은 꺼졌는데 컨트롤러는 켜져 있다고 믿는다** — 한 슬롯 내내
밸브가 닫힌다. 판정을 스텝이 아니라 출력으로 해야 하는 이유다.

## 함정 — "OFF 도 ON 도 안 보낸다" 로는 부족하다

출력에 타이머가 걸려 있으면(스텝 옵션에 지속시간을 준 경우, 또는 한 번 이어받은
뒤) 출력층이 **옛 끝 시각에 스스로 끈다.** 일반 ON 을 다시 보내도 소용없다 —
출력층은 이미 켜진 출력의 연장을 **첫 세션 끝에서 자른다**(PID 가 매 주기 ON 을
보내 끝없이 연장하는 것을 막는 상한). 시퀀스는 켜져 있다고 믿으므로 다시 켜지
않는다. 그래서 이어받는 스텝은 출력층에 **세션 갱신(`renew_session`)** 을 요청한다
— 장치에는 아무것도 나가지 않고 타이머만 새 스텝의 길이로 바뀐다.

스텝 길이는 원래 출력층에 닿지 않았다(한 겹 덜 감싸 넘겨 무기한으로 폴백 —
`_action_value` 참조, 2026-09-21 수정). 이제는 시퀀스의 ON 마다 스텝 길이만큼의
타이머가 걸리므로 위 함정이 기본 설정에서도 그대로 성립한다.
"""
import json
from datetime import timedelta
from unittest.mock import MagicMock, patch

import pytest

import aot.controllers.controller_trigger_sequence as seq_mod
from aot.outputs.base_output import AbstractOutput
from aot.utils.timekit import utc_now

PERIOD = 3600.0
T0 = 1_000_000.0


# ---------------------------------------------------------------------------
# 시퀀스 쪽: 출력층을 가로채 (출력, 명령) 순서를 기록한다
# ---------------------------------------------------------------------------

class Rig:
    def __init__(self, schedule):
        self.log = []
        self.by_uid = {i['action'].unique_id: i['action'] for i in schedule}
        inst = object.__new__(seq_mod.SequenceTriggerController)
        inst.unique_id = 'seq-handover-test'
        inst.logger = MagicMock()
        inst.active_actions = set()
        inst._completed_actions = set()
        inst._handover = {}
        inst._out_key_cache = {}
        inst.current_schedule = schedule
        inst.dict_actions = {}
        inst.sequence_cycle_duration = PERIOD
        inst.device_tz = 'UTC'
        inst._runt_logged_start = None
        inst._skip_logged_start = None
        inst._save_runtime_state = lambda: None
        inst.build_cycle_schedule = lambda: None        # 같은 계획이 되풀이된다
        inst._resolve_output_target = lambda a: (a.OUT, 0)
        inst.control = MagicMock()
        inst.control.output_off = self._off
        inst.control.output_on = self._on
        self.inst = inst

    def _off(self, out, output_channel=0):
        self.log.append((out, 'OFF'))
        return 0, 'ok'

    def _on(self, out, output_type=None, amount=0, output_channel=0,
            additional_options=None):
        renew = bool((additional_options or {}).get('renew_session'))
        self.log.append((out, 'RENEW' if renew else 'ON', amount))
        return 0, 'ok'

    def trigger_action(self, dict_actions, uid, value=None):
        self.log.append((self.by_uid[uid].OUT, 'ON', (value.get('value') or {}).get('duration')))

    def boundary(self):
        """loop() 한 바퀴를 경계 직후 그대로 흉내 낸다."""
        inst = self.inst
        inst.cycle_start_time = T0
        inst.process_cycle(T0 + PERIOD - 1)              # 경계 직전 상태
        self.log.clear()
        now = T0 + PERIOD + 0.05
        nxt = inst._next_cycle_start({}, now, PERIOD)
        assert nxt is not None
        inst.start_new_cycle(nxt, period=PERIOD, at=now)
        inst.process_cycle(now)
        return list(self.log)


def act(uid, out, action_type='output_on_off', state='on'):
    a = MagicMock()
    a.unique_id = uid
    a.action_type = action_type
    a.do_unique_id = None
    a.custom_options = json.dumps({'output': f'{out},0', 'state': state})
    a.OUT = out
    return a


def item(a, start, end, typ='single'):
    return {'action': a, 'start': start, 'end': end, 'is_output': True, 'type': typ}


@pytest.fixture
def rig_factory(monkeypatch):
    def make(schedule):
        rig = Rig(schedule)
        monkeypatch.setattr(seq_mod, 'trigger_action', rig.trigger_action)
        return rig
    return make


def commands_for(log, out):
    return [c[1] for c in log if c[0] == out]


# ---- 사이클 경계 ----

def test_single_step_filling_the_period_is_not_switched_off_and_on(rig_factory):
    """C동 예전 설정. 경계에서 OFF·ON 없이 이어받기 하나만 나가야 한다."""
    rig = rig_factory([item(act('s', 'V1'), 0, PERIOD)])
    log = rig.boundary()
    assert commands_for(log, 'V1') == ['RENEW'], log


def test_the_renewal_carries_the_new_steps_length(rig_factory):
    """갱신 길이가 곧 출력층의 새 끝 시각이다 — 틀리면 엉뚱한 때 꺼진다."""
    rig = rig_factory([item(act('s', 'V1'), 0, PERIOD)])
    log = rig.boundary()
    renew = [c for c in log if c[:2] == ('V1', 'RENEW')]
    grace = seq_mod.SequenceTriggerController.RENEW_GRACE_S
    assert renew and renew[0][2] == PERIOD + grace


def test_a_pump_spanning_the_whole_period_keeps_running(rig_factory):
    """펌프(total)는 이어받고, 밸브는 예전처럼 바뀐다."""
    rig = rig_factory([
        item(act('a1', 'V1'), 0, 1800),
        item(act('a2', 'V2'), 1800, PERIOD),
        item(act('p', 'PUMP'), 0, PERIOD, 'total'),
    ])
    log = rig.boundary()
    assert commands_for(log, 'PUMP') == ['RENEW'], log
    assert commands_for(log, 'V2') == ['OFF']
    assert commands_for(log, 'V1') == ['ON']


def test_different_outputs_at_the_boundary_still_switch(rig_factory):
    """서로 다른 밸브가 경계에서 바뀌는 것은 문제가 아니다 — 건드리지 않는다."""
    rig = rig_factory([item(act('x', 'VA'), 0, 1800), item(act('y', 'VB'), 1800, PERIOD)])
    log = rig.boundary()
    assert commands_for(log, 'VB') == ['OFF']
    assert commands_for(log, 'VA') == ['ON']
    assert not [c for c in log if c[1] == 'RENEW']


def test_a_pwm_step_is_never_merged(rig_factory):
    """"켜진 채로 둔다" 는 on/off 에만 성립한다."""
    rig = rig_factory([item(act('p', 'P1', action_type='output_pwm'), 0, PERIOD)])
    log = rig.boundary()
    assert commands_for(log, 'P1') == ['OFF', 'ON']


def test_an_unclaimed_handover_is_switched_off(rig_factory):
    """넘겨 두었는데 아무도 이어 쓰지 않으면 끈다 — 넘긴 채 잊히면 안 된다."""
    rig = rig_factory([item(act('s', 'V1'), 0, PERIOD)])
    inst = rig.inst
    inst.cycle_start_time = T0
    inst.active_actions = set()
    # V1 을 넘겨 두었지만 이번 판정 시각에는 V1 을 쓰는 스텝이 없다.
    ghost = act('old', 'V9')
    rig.by_uid['old'] = ghost
    inst._handover = {('V9', 0): 'old'}
    inst._force_off_unscheduled = MagicMock()
    inst.process_cycle(T0 + 10)
    inst._force_off_unscheduled.assert_called_once_with('old')


# ---- 사이클 안: 이웃한 스텝이 같은 출력을 쓴다 ----

def test_adjacent_steps_sharing_an_output_keep_it_open(rig_factory):
    """예전에는 새 스텝을 켠 뒤 옛 스텝을 꺼서 최종이 OFF 였다."""
    rig = rig_factory([
        item(act('g1a', 'V11'), 0, 1800), item(act('g1b', 'LIQ'), 0, 1800),
        item(act('g2a', 'V12'), 1800, PERIOD), item(act('g2b', 'LIQ'), 1800, PERIOD),
    ])
    inst = rig.inst
    inst.cycle_start_time = T0
    inst.process_cycle(T0 + 1799)
    rig.log.clear()
    inst.process_cycle(T0 + 1800.05)

    assert commands_for(rig.log, 'LIQ') == ['RENEW'], rig.log
    assert commands_for(rig.log, 'V11') == ['OFF']
    assert inst.active_actions == {'g2a', 'g2b'}


def test_overlapping_steps_on_one_output_renew_instead_of_capped_on(rig_factory):
    """교차 시간(overlap)이 있으면 새 스텝이 옛 스텝이 **돌고 있는 중에** 켜진다.
    일반 ON 은 출력층이 옛 세션 끝에서 자르므로 이어받기여야 한다."""
    rig = rig_factory([
        item(act('x', 'LIQ'), 0, 1830),
        item(act('y', 'LIQ'), 1770, PERIOD),
    ])
    inst = rig.inst
    inst.cycle_start_time = T0
    inst.process_cycle(T0 + 100)
    rig.log.clear()
    inst.process_cycle(T0 + 1800)            # 둘 다 창 안
    assert commands_for(rig.log, 'LIQ') == ['RENEW']
    rig.log.clear()
    inst.process_cycle(T0 + 1840)            # x 만 끝났다
    assert commands_for(rig.log, 'LIQ') == [], '같은 출력을 쓰는 y 가 돌고 있는데 껐다'


# ---- 배선 ----

def test_the_loop_passes_its_own_clock_to_the_boundary():
    """경계 판정과 바로 뒤 process_cycle 이 다른 시계를 보면 어긋난다."""
    import inspect
    src = inspect.getsource(seq_mod.SequenceTriggerController.loop)
    assert 'start_new_cycle(next_start, period=period, at=now)' in src


# ---------------------------------------------------------------------------
# 출력층: 이어받기만 세션 상한을 넘는다
# ---------------------------------------------------------------------------

def _running_output(total=3600, remaining=5):
    o = object.__new__(AbstractOutput)
    o.unique_id = 'out'
    o.output_name = 'v'
    o.logger = MagicMock()
    o.OUTPUT_INFORMATION = {}
    o.output_type = 'x'
    o.output_types = {'on_off': ['x']}
    o.output_states = {0: True}
    o.is_setup = lambda: True
    o.is_on = lambda ch=0: True
    o._command_dispatched = {}
    now = utc_now()
    o.output_off_until = {0: None}
    o.output_on_duration = {0: True}
    o.output_last_duration = {0: total}
    o.output_on_until = {0: now + timedelta(seconds=remaining)}
    o.output_session_start = {0: now - timedelta(seconds=total - remaining)}
    o.output_session_max = {0: total}
    o.output_switch = MagicMock(return_value=(0, 'ok'))
    return o


def _left(o):
    return (o.output_on_until[0] - utc_now()).total_seconds()


def test_a_plain_repeat_on_is_still_capped():
    """PID 가 매 주기 ON 을 보내 끝없이 연장하는 것을 막는 상한 — 그대로여야 한다."""
    o = _running_output()
    with patch('aot.outputs.base_output.threading.Thread'):
        o.output_on_off('on', output_channel=0, output_type='sec', amount=3600)
    assert _left(o) < 10
    o.output_switch.assert_not_called()


def test_a_renewal_starts_a_new_session_without_a_device_command():
    o = _running_output()
    with patch('aot.outputs.base_output.threading.Thread'):
        o.output_on_off('on', output_channel=0, output_type='sec', amount=3600,
                        additional_options={'renew_session': True})
    assert 3590 < _left(o) <= 3600
    assert o.output_session_max[0] == 3600
    o.output_switch.assert_not_called()


def test_a_renewal_records_the_previous_steps_open_time():
    """앞 스텝의 개방 시간은 기록돼야 한다 — OFF 를 안 보냈다고 사라지면 안 된다."""
    o = _running_output(total=3600, remaining=5)
    with patch('aot.outputs.base_output.threading.Thread') as th:
        o.output_on_off('on', output_channel=0, output_type='sec', amount=3600,
                        additional_options={'renew_session': True})
    written = [c.kwargs['args'][2] for c in th.call_args_list]
    assert written and 3590 <= written[0] <= 3600


def test_a_renewal_while_awaiting_confirmation_retargets_the_pending_duration():
    """확인형 출력이 아직 확인 전이면 끝 시각이 None 이다 — 비교하다 터지면 안 되고,
    확인이 오면 새 길이로 걸리게 해야 한다."""
    o = _running_output()
    o.output_on_until[0] = None
    o._cmd_duration = {0: 1800}
    with patch('aot.outputs.base_output.threading.Thread'):
        ret = o.output_on_off('on', output_channel=0, output_type='sec', amount=3600,
                              additional_options={'renew_session': True})
    assert ret[0] == 0
    assert o._cmd_duration[0] == 3600
    o.output_switch.assert_not_called()
