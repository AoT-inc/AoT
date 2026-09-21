# coding=utf-8
"""시퀀스의 스텝 길이가 **출력에 실제로 닿는가**.

## 왜 이 테스트가 있나

시퀀스는 스텝을 켤 때 그 스텝의 길이를 안전 타이머로 싣는다 — 시퀀스가 멈춰도
밸브가 제때 닫히게 하려는 것이다. 그런데 예전에는 `trigger_action(value=
{'message': …, 'duration': 길이})` 로 넘겼고, 액션(`output_on_off`)은
`dict_vars["value"]["duration"]` — **한 겹 더 감싼 자리**를 읽는다. 그래서
KeyError → 스텝 옵션의 `duration`(기본 0 = 무기한)으로 조용히 폴백했다.

즉 **시퀀스가 켠 출력은 전부 무기한**이었다. 에러도 경고도 없고, 시퀀스가 제때
OFF 를 보내는 한 겉으로 아무 차이가 없어서 드러나지 않았다. 감사 로그의 ON 이
`amount=0.0` 인 것을 보고서야 알았다(2026-09-21 실측).

여기서는 (1) 시퀀스가 무엇을 넘기는지, (2) **실제 액션 모듈**이 그것을 받아 출력
명령에 싣는지를 끝까지 따라가 고정한다. 모양만 맞추고 액션이 여전히 못 읽으면
똑같이 조용하기 때문이다.
"""
import json
from unittest.mock import MagicMock

import pytest

import aot.controllers.controller_trigger_sequence as seq_mod

GRACE = seq_mod.SequenceTriggerController.RENEW_GRACE_S


def _action(action_type='output_on_off', duration=0.0, state='on'):
    a = MagicMock()
    a.unique_id = 'act-1'
    a.action_type = action_type
    a.custom_options = json.dumps({'state': state, 'duration': duration,
                                   'output': 'out-1,ch-1'})
    return a


def _controller():
    inst = object.__new__(seq_mod.SequenceTriggerController)
    inst.unique_id = 'seq-duration-test'
    inst.logger = MagicMock()
    inst.active_actions = set()
    inst.dict_actions = {}
    inst._save_runtime_state = lambda: None
    return inst


# ---- 시퀀스가 넘기는 모양 ----

def test_the_step_length_is_nested_where_the_action_reads_it():
    value = _controller()._action_value(_action(), 1800.0)
    assert value['value']['duration'] == 1800.0 + GRACE
    assert 'duration' not in value, '바깥 자리는 아무 액션도 읽지 않는다 — 두면 다시 헷갈린다'


def test_an_explicit_step_duration_is_respected():
    """사람이 넣어 둔 지속시간(펄스처럼 쓰는 스텝)은 덮지 않는다."""
    value = _controller()._action_value(_action(duration=10.0), 1800.0)
    assert 'value' not in value


@pytest.mark.parametrize('action_type', ['output_ramp_pwm', 'create_note', 'output_pwm'])
def test_other_actions_are_not_given_the_step_length(action_type):
    """`output_ramp_pwm` 은 같은 자리를 램프 시간으로, `create_note` 는 `value` 를
    스칼라로 읽는다 — 스텝 길이를 넣으면 뜻이 바뀐다."""
    value = _controller()._action_value(_action(action_type=action_type), 1800.0)
    assert 'value' not in value


def test_turn_on_action_uses_it(monkeypatch):
    seen = {}
    monkeypatch.setattr(seq_mod, 'trigger_action',
                        lambda d, uid, value=None: seen.update(value=value))
    inst = _controller()
    inst.turn_on_action(_action(), {'start': 0.0, 'end': 1800.0})
    assert seen['value']['value']['duration'] == 1800.0 + GRACE


# ---- 실제 액션 모듈까지 ----

def test_the_real_output_on_off_action_puts_it_on_the_command(monkeypatch):
    """모양만 맞추고 액션이 못 읽으면 예전처럼 조용하다 — 실제 모듈로 확인한다."""
    import aot.actions.output_on_off as mod

    sent = {}

    class FakeControl:
        def output_on_off(self, output_id, state, output_type=None, amount=0.0,
                          output_channel=None):
            sent.update(state=state, amount=amount)
            return 0, 'ok'

    action = object.__new__(mod.ActionModule)
    action.logger = MagicMock()
    action.control = FakeControl()
    action.output_device_id = 'out-1'
    action.output_channel_id = 'ch-1'
    action.state = 'on'
    action.duration = 0.0
    action.get_output_channel_from_channel_id = lambda cid: 0

    monkeypatch.setattr(mod, 'db_retrieve_table_daemon',
                        lambda *a, **kw: MagicMock(name='v311'))
    monkeypatch.setattr(mod, 'run_in_thread',
                        lambda fn, args=(), kwargs=None: fn(*args, **(kwargs or {})))

    value = _controller()._action_value(_action(), 1800.0)
    action.run_action(value)

    assert sent == {'state': 'on', 'amount': 1800.0 + GRACE}, (
        f'스텝 길이가 출력 명령에 실리지 않았다: {sent} — 무기한으로 켜진다')


def test_the_old_shape_really_was_ignored(monkeypatch):
    """회귀의 근거: 예전 모양이면 액션은 스텝 옵션(0)으로 폴백한다."""
    import aot.actions.output_on_off as mod

    sent = {}

    class FakeControl:
        def output_on_off(self, output_id, state, output_type=None, amount=0.0,
                          output_channel=None):
            sent.update(amount=amount)
            return 0, 'ok'

    action = object.__new__(mod.ActionModule)
    action.logger = MagicMock()
    action.control = FakeControl()
    action.output_device_id = 'out-1'
    action.output_channel_id = 'ch-1'
    action.state = 'on'
    action.duration = 0.0
    action.get_output_channel_from_channel_id = lambda cid: 0
    monkeypatch.setattr(mod, 'db_retrieve_table_daemon',
                        lambda *a, **kw: MagicMock(name='v311'))
    monkeypatch.setattr(mod, 'run_in_thread',
                        lambda fn, args=(), kwargs=None: fn(*args, **(kwargs or {})))

    action.run_action({'message': '', 'duration': 1800.0})
    assert sent['amount'] == 0.0


# ---- 이어받기 판정과 맞물림 ----

def test_a_step_with_an_explicit_duration_is_not_handed_over():
    """"그 시간만 켜고 끈다" 는 스텝을 켜진 채로 이어받으면 뜻이 바뀐다."""
    inst = _controller()
    inst._out_key_cache = {}
    inst._resolve_output_target = lambda a: ('out-1', 0)
    assert inst._output_key(_action(duration=0.0)) == ('out-1', 0)
    assert inst._output_key(_action(duration=10.0)) is None
