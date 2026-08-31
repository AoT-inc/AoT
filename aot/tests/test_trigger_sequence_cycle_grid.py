# coding=utf-8
"""시퀀스 사이클이 **격자 위**에 남는지, 그리고 출력 명령이 출처를 밝히는지.

## 왜 이 테스트가 있나

예전 `loop()` 은 새 사이클의 기준점을 `self.cycle_start_time = now` 로 잡았다.
`now` 는 루프가 실제로 도달한 시각이라, 직전 반복에서 스텝 전환에 걸린 시간이
그대로 기준점에 흡수된다. 그리고 그 기준점이 다음 사이클의 기준이 되므로 오차가
**영구 누적**된다. 원격 출력(`remote_output_on_off`)은 동기 HTTP 라 왕복이 0.2초일
수도 60초일 수도 있어서, 누적량이 매번 달라 "설정한 시각과 다르게 들쭉날쭉" 이 된다.

같은 원격 출력을 쓰는데도 타이머 트리거는 시각이 맞았다 —
`controller_trigger.py` 가 `+= period` / `epoch_of_next_time` 으로 격자를 지키기
때문이다. 이 테스트는 시퀀스가 같은 성질을 갖는지 못박는다.

`test_no_drift_accumulates_over_many_cycles` 가 핵심이다. 옛 `= now` 구현에서는
반드시 실패한다.
"""
from datetime import datetime
from unittest.mock import MagicMock

import pytest
import pytz

import aot.controllers.controller_trigger_sequence as seq_mod
from aot.utils.command_origin import AUDITED_TYPES, TYPE_SEQUENCE, should_audit
from aot.utils.execution_context import clear_execution_context, get_context
from aot.utils.weekly_schedule import window_start_epoch

KST = pytz.timezone('Asia/Seoul')
TZ_NAME = 'Asia/Seoul'

PERIOD = 3600.0
ENTRY = {'enabled': True, 'start': '05:00', 'end': '15:00', 'period': int(PERIOD)}


def kst_epoch(y, mo, d, h, mi, s=0):
    return KST.localize(datetime(y, mo, d, h, mi, s)).timestamp()


# 2026-08-28 05:00 KST — 감사로그에 남은 실제 사건의 창 시작.
ANCHOR = kst_epoch(2026, 8, 28, 5, 0)


def make_controller():
    """격자 계산이 건드리는 속성만 갖춘 컨트롤러.

    `__init__` 을 우회한다 — 실제 DaemonControl/Pyro5 클라이언트를 만들 이유가
    없다(기존 test_trigger_sequence_restart_resume.py 와 같은 방식).
    """
    inst = object.__new__(seq_mod.SequenceTriggerController)
    inst.unique_id = 'seq-grid-test-0000'
    inst.logger = MagicMock()
    inst.cycle_start_time = None
    inst.device_tz = TZ_NAME
    inst.sequence_cycle_duration = PERIOD
    inst.active_actions = set()
    inst._runt_logged_start = None
    # 활성 시퀀스가 기본이다 — 재개 재동기화는 활성일 때만 돈다(비활성 시퀀스가
    # 밸브를 여는 사고가 있어 가드가 붙었다, test_trigger_sequence_restart_resume
    # 의 test_deactivated_sequence_does_not_reopen_outputs 참조).
    inst.is_activated = True
    return inst


# ---- window_start_epoch: 격자의 원점 ----

def test_window_start_epoch_is_todays_local_window_start():
    # 창 시작 뒤 5시간 123초 지난 시점에 물어도 원점은 그날 05:00 이다.
    got = window_start_epoch(ENTRY, TZ_NAME, ANCHOR + 5 * 3600 + 123)
    assert got == ANCHOR


def test_window_start_epoch_uses_device_tz_not_utc():
    # 같은 순간이라도 기기 tz 가 다르면 원점이 다르다. UTC 로 계산하면 둘이 같아진다.
    seoul = window_start_epoch(ENTRY, 'Asia/Seoul', ANCHOR + 60)
    utc = window_start_epoch(ENTRY, 'UTC', ANCHOR + 60)
    assert seoul != utc


def test_window_start_epoch_returns_none_on_broken_entry():
    assert window_start_epoch({}, TZ_NAME, ANCHOR) is None
    assert window_start_epoch({'start': '25:99'}, TZ_NAME, ANCHOR) is None


# ---- 첫 사이클: 창 시작 앵커에 정렬 ----

def test_first_cycle_snaps_to_grid_not_to_now():
    inst = make_controller()
    # 창이 열리고 2시간 47초 지나 컨트롤러가 붙었다(데몬 재기동 등).
    now = ANCHOR + 2 * PERIOD + 47
    assert inst._next_cycle_start(ENTRY, now, PERIOD) == ANCHOR + 2 * PERIOD


def test_first_cycle_at_window_open_is_the_anchor():
    inst = make_controller()
    assert inst._next_cycle_start(ENTRY, ANCHOR, PERIOD) == ANCHOR


def test_first_cycle_falls_back_to_now_when_anchor_unavailable():
    inst = make_controller()
    now = ANCHOR + 123
    # start 가 없으면 격자를 세울 수 없다 — 멈추지 말고 지금부터 시작한다.
    assert inst._next_cycle_start({'period': PERIOD}, now, PERIOD) == now


# ---- 진행 중: += period 로 격자 유지 ----

def test_late_arrival_does_not_move_the_grid():
    inst = make_controller()
    inst.cycle_start_time = ANCHOR
    # 스텝 전환이 5초 늦어 루프가 5초 늦게 도달했다.
    start = inst._next_cycle_start(ENTRY, ANCHOR + PERIOD + 5, PERIOD)
    assert start == ANCHOR + PERIOD          # now(=+3605) 가 아니다
    assert start != ANCHOR + PERIOD + 5


def test_returns_none_before_the_period_elapses():
    inst = make_controller()
    inst.cycle_start_time = ANCHOR
    assert inst._next_cycle_start(ENTRY, ANCHOR + 100, PERIOD) is None


def test_no_drift_accumulates_over_many_cycles():
    """핵심 회귀. 매 사이클 5초씩 늦게 도달해도 격자는 그대로여야 한다.

    옛 `cycle_start_time = now` 구현이면 10번째 시작이 45초 밀린다.
    """
    inst = make_controller()
    now = ANCHOR
    starts = []
    for _ in range(10):
        start = inst._next_cycle_start(ENTRY, now, PERIOD)
        if start is not None:
            inst.cycle_start_time = start
            starts.append(start)
        now += PERIOD + 5      # 왕복 지연으로 매번 5초씩 늦게 도달

    assert starts == [ANCHOR + i * PERIOD for i in range(10)]
    # 마지막 시작이 벽시계로 정확히 09시가 아니라면 표류한 것이다.
    assert starts[-1] == kst_epoch(2026, 8, 28, 14, 0)


def test_drift_does_not_accumulate_even_with_erratic_delays():
    """원격 HTTP 는 왕복이 일정하지 않다 — 지연이 들쭉날쭉해도 격자는 고정."""
    inst = make_controller()
    inst.cycle_start_time = ANCHOR
    now = ANCHOR
    for i, delay in enumerate([0.2, 47, 3, 61, 0.5, 12], start=1):
        now = ANCHOR + i * PERIOD + delay
        start = inst._next_cycle_start(ENTRY, now, PERIOD)
        assert start == ANCHOR + i * PERIOD
        inst.cycle_start_time = start


def test_skipped_cycles_are_warned_not_silently_swallowed():
    inst = make_controller()
    inst.cycle_start_time = ANCHOR
    # 한 스텝 전환이 3주기를 넘겨 잡아먹었다.
    start = inst._next_cycle_start(ENTRY, ANCHOR + 3 * PERIOD + 10, PERIOD)
    assert start == ANCHOR + 3 * PERIOD          # 격자는 지킨다
    # ERROR 로 남긴다 — log_level_debug 가 꺼지면 로거가 ERROR 레벨이라
    # warning 으로는 기본 설정에서 아무 데도 남지 않는다.
    assert inst.logger.error.called


def test_single_late_cycle_is_not_warned():
    inst = make_controller()
    inst.cycle_start_time = ANCHOR
    inst._next_cycle_start(ENTRY, ANCHOR + PERIOD + 5, PERIOD)
    assert not inst.logger.error.called


# ---- period 방어 ----

@pytest.mark.parametrize('bad', [None, 0, '', 'x'])
def test_entry_period_falls_back_when_unusable(bad):
    inst = make_controller()
    assert inst._entry_period({'period': bad}) == PERIOD


def test_entry_period_prefers_the_days_own_period():
    inst = make_controller()
    assert inst._entry_period({'period': 6000}) == 6000.0


# ---- 실행 컨텍스트: 출력 명령이 출처를 밝히는가 ----

@pytest.fixture(autouse=True)
def _clean_context():
    clear_execution_context()
    yield
    clear_execution_context()


def test_turn_on_action_declares_sequence_origin(monkeypatch):
    inst = make_controller()
    inst.dict_actions = {}
    inst._save_runtime_state = MagicMock()

    seen = {}

    def fake_trigger_action(dict_actions, action_id, value=None):
        seen.update(get_context())

    monkeypatch.setattr(seq_mod, 'trigger_action', fake_trigger_action)

    action = MagicMock()
    action.unique_id = 'act-1'
    inst.turn_on_action(action, {'start': 0.0, 'end': 2400.0})

    assert seen.get('source_type') == TYPE_SEQUENCE
    assert seen.get('source_id') == inst.unique_id
    # 스레드는 재사용된다 — 명령이 끝나면 반드시 비워져 있어야 한다.
    assert not get_context().get('source_type')


def test_turn_on_action_clears_context_even_when_dispatch_raises(monkeypatch):
    inst = make_controller()
    inst.dict_actions = {}
    inst._save_runtime_state = MagicMock()

    def boom(*_a, **_kw):
        raise RuntimeError("remote host unreachable")

    monkeypatch.setattr(seq_mod, 'trigger_action', boom)

    action = MagicMock()
    action.unique_id = 'act-1'
    with pytest.raises(RuntimeError):
        inst.turn_on_action(action, {'start': 0.0, 'end': 2400.0})

    # 여기서 새면 다음 명령이 이 시퀀스의 출처를 뒤집어쓴다.
    assert not get_context().get('source_type')


def test_turn_off_action_declares_sequence_origin():
    inst = make_controller()
    inst.active_actions = {'act-1'}
    inst._save_runtime_state = MagicMock()

    seen = {}
    inst.control = MagicMock()
    inst.control.output_off.side_effect = lambda *a, **kw: seen.update(get_context())

    action = MagicMock()
    action.unique_id = 'act-1'
    action.do_unique_id = 'out-1,0'
    action.custom_options = None

    inst.turn_off_action(action, {'is_output': True})

    assert seen.get('source_type') == TYPE_SEQUENCE
    assert seen.get('source_id') == inst.unique_id
    assert not get_context().get('source_type')


def test_sequence_origin_is_audited():
    """시퀀스 명령은 감사로그에 남아야 한다.

    'automation' 은 고빈도(PID 30초)라 일부러 제외돼 있다. 시퀀스를 거기에
    묶으면 밸브가 언제 열렸는지가 관계형 감사에서 통째로 사라진다.
    """
    assert TYPE_SEQUENCE in AUDITED_TYPES
    assert should_audit({'type': TYPE_SEQUENCE})
    # 고빈도 자동화는 여전히 제외된 채로 남는다.
    assert not should_audit({'type': 'automation'})


# ---- 창 끝 자투리 사이클: 남은 창이 부족하면 시작하지 않는다 ----

def _with_plan(inst, one_pass):
    """한 pass 가 `one_pass` 초인 계획을 세워둔 것처럼."""
    inst.current_schedule = [{'end': one_pass}]
    return inst


def test_runt_cycle_is_not_started():
    """창 05:00~15:03, 주기 1시간, 한 pass 40분.

    마지막 격자점(15:00)에서 시작하면 3분 만에 창이 닫혀 밸브가 끊긴다.
    """
    entry = {'enabled': True, 'start': '05:00', 'end': '15:03', 'period': 3600}
    inst = _with_plan(make_controller(), 2400)
    inst.cycle_start_time = ANCHOR + 9 * PERIOD          # 14:00 사이클 진행 중
    now = ANCHOR + 10 * PERIOD + 1                        # 15:00 직후
    assert inst._next_cycle_start(entry, now, PERIOD) is None


def test_cycle_that_fits_the_window_is_started():
    entry = {'enabled': True, 'start': '05:00', 'end': '15:03', 'period': 3600}
    inst = _with_plan(make_controller(), 2400)
    inst.cycle_start_time = ANCHOR + 8 * PERIOD
    now = ANCHOR + 9 * PERIOD + 1                         # 14:00 시작 → 14:40 종료, 창 안
    assert inst._next_cycle_start(entry, now, PERIOD) == ANCHOR + 9 * PERIOD


def test_pass_ending_exactly_at_window_close_is_allowed():
    """딱 맞아떨어지는 설정(나주: 창 2시간, 한 pass 2시간)은 정상이다."""
    entry = {'enabled': True, 'start': '05:30', 'end': '07:30', 'period': 14400}
    inst = _with_plan(make_controller(), 7200)
    start = kst_epoch(2026, 8, 28, 5, 30)
    assert inst._next_cycle_start(entry, start, 14400.0) == start


def test_unknown_pass_length_does_not_block_the_cycle():
    """계획이 아직 없으면(첫 사이클) 판단하지 않고 진행한다."""
    inst = make_controller()
    inst.current_schedule = []
    assert inst._next_cycle_start(ENTRY, ANCHOR, PERIOD) == ANCHOR


# ---- OFF 실패를 삼키지 않는다 ----

def make_off_controller(off_result=(0, 'success')):
    inst = make_controller()
    inst.current_schedule = []
    inst._save_runtime_state = MagicMock()
    inst.control = MagicMock()
    inst.control.output_off.return_value = off_result
    inst.OFF_RETRY_INTERVAL_SEC = 0        # 테스트에서는 백오프 없이
    inst._off_failures = {}
    return inst


def _act(aid='act-1', target='out-1,0'):
    action = MagicMock()
    action.unique_id = aid
    action.do_unique_id = target
    action.custom_options = None
    return action


def test_successful_off_removes_from_active():
    inst = make_off_controller((0, 'success'))
    inst.active_actions = {'act-1'}
    assert inst.turn_off_action(_act(), {'is_output': True}) is True
    assert 'act-1' not in inst.active_actions


def test_failed_off_keeps_action_active_for_retry():
    """예전에는 실패해도 active 에서 빼서 '껐다'고 간주했다 — 밸브는 열린 채로."""
    inst = make_off_controller((1, 'Output OFF timed out'))
    inst.active_actions = {'act-1'}
    assert inst.turn_off_action(_act(), {'is_output': True}) is False
    assert 'act-1' in inst.active_actions          # 다음 주기에 다시 시도한다


def test_off_retries_then_gives_up_loudly():
    inst = make_off_controller((1, 'nope'))
    inst.active_actions = {'act-1'}
    for _ in range(inst.OFF_MAX_ATTEMPTS):
        inst.turn_off_action(_act(), {'is_output': True})
    assert inst.control.output_off.call_count == inst.OFF_MAX_ATTEMPTS
    assert 'act-1' not in inst.active_actions       # 무한 재시도는 하지 않는다
    assert inst.logger.error.called                 # 대신 조용히 지우지 않는다


def test_off_backoff_skips_immediate_retry():
    inst = make_off_controller((1, 'nope'))
    inst.OFF_RETRY_INTERVAL_SEC = 300              # 백오프 살림
    inst.active_actions = {'act-1'}
    inst.turn_off_action(_act(), {'is_output': True})
    inst.turn_off_action(_act(), {'is_output': True})
    # 0.1초마다 도는 루프가 명령을 연발하면 그것 자체가 장치를 두들긴다.
    assert inst.control.output_off.call_count == 1


def test_missing_target_is_an_error_not_a_silent_drop():
    inst = make_off_controller()
    inst.active_actions = {'act-1'}
    action = _act(target=None)
    assert inst.turn_off_action(action, {'is_output': True}) is False
    assert inst.control.output_off.call_count == 0
    assert inst.logger.error.called


def test_off_dispatch_exception_is_treated_as_failure():
    inst = make_off_controller()
    inst.control.output_off.side_effect = RuntimeError("daemon gone")
    inst.active_actions = {'act-1'}
    assert inst.turn_off_action(_act(), {'is_output': True}) is False
    assert 'act-1' in inst.active_actions


def test_non_output_step_needs_no_dispatch():
    inst = make_off_controller()
    inst.active_actions = {'act-1'}
    assert inst.turn_off_action(_act(), {'is_output': False}) is True
    assert inst.control.output_off.call_count == 0
    assert 'act-1' not in inst.active_actions


# ---- 재시작 재개: 믿음과 장치의 실제 상태를 맞춘다 ----
#
# 데몬이 내려갈 때 출력의 state_shutdown 이 OFF 면 장치는 꺼진 채 올라오는데,
# 재개는 "이미 돌고 있다" 고 보고 재전송을 하지 않았다. 그래서 그 사이클의 남은
# 시간이 통째로 사라졌다 — 실측(2026-08-28)에서 52분째 열려 있던 밸브가 꺼진 채
# 올라왔고 남은 8분이 증발했다. 개방 시간 기록도 없어 아무도 모른다.

def make_resume_controller(state='off', end=3600.0, elapsed=3000.0):
    inst = make_controller()
    inst.cycle_start_time = 1787900000.0
    action = _act('act-1', 'out-1,0')
    inst.current_schedule = [{'action': action, 'start': 0.0, 'end': end,
                              'is_output': True, 'type': 'single'}]
    inst.active_actions = {'act-1'}
    inst.control = MagicMock()
    inst.control.output_state.return_value = state
    inst._elapsed_for_test = elapsed
    return inst


def _run_resync(inst, monkeypatch, elapsed):
    monkeypatch.setattr(seq_mod.time, 'time',
                        lambda: inst.cycle_start_time + elapsed)
    inst._resync_after_resume()


def test_resume_reissues_only_the_remaining_time(monkeypatch):
    inst = make_resume_controller(state='off', end=3600.0)
    _run_resync(inst, monkeypatch, 3000.0)

    assert inst.control.output_on.call_count == 1
    kwargs = inst.control.output_on.call_args.kwargs
    # 전체 3600 이 아니라 남은 600 이어야 한다. 전체로 켜면 재시작할 때마다
    # 그 스텝의 총 개방시간이 늘어난다.
    assert kwargs['amount'] == 600.0
    assert kwargs['output_type'] == 'sec'
    assert kwargs['output_channel'] == 0


def test_resume_leaves_an_already_running_output_alone(monkeypatch):
    inst = make_resume_controller(state='on')
    _run_resync(inst, monkeypatch, 3000.0)
    assert inst.control.output_on.call_count == 0
    assert 'act-1' in inst.active_actions


def test_resume_does_not_guess_when_state_is_unreadable(monkeypatch):
    """통신 오류로 None 이 오면 건드리지 않는다 — 모르는 채 켜면 이미 열린
    밸브를 연장하게 되고, 그쪽이 더 나쁘다."""
    inst = make_resume_controller(state=None)
    _run_resync(inst, monkeypatch, 3000.0)
    assert inst.control.output_on.call_count == 0


def test_resume_drops_a_step_whose_time_already_passed(monkeypatch):
    inst = make_resume_controller(state='off', end=3600.0)
    _run_resync(inst, monkeypatch, 4000.0)     # 데몬이 내려가 있는 사이 끝났다
    assert inst.control.output_on.call_count == 0
    assert 'act-1' not in inst.active_actions


def test_resume_reissue_declares_sequence_origin(monkeypatch):
    inst = make_resume_controller(state='off')
    seen = {}
    inst.control.output_on.side_effect = lambda *a, **kw: seen.update(get_context())
    _run_resync(inst, monkeypatch, 3000.0)
    assert seen.get('source_type') == TYPE_SEQUENCE
    assert not get_context().get('source_type')


def test_resume_survives_a_dispatch_error(monkeypatch):
    inst = make_resume_controller(state='off')
    inst.control.output_on.side_effect = RuntimeError("daemon not ready")
    _run_resync(inst, monkeypatch, 3000.0)     # 예외가 새면 컨트롤러가 못 뜬다
    assert inst.logger.error.called
    assert not get_context().get('source_type')


def test_resync_is_a_noop_without_an_active_cycle(monkeypatch):
    inst = make_resume_controller(state='off')
    inst.cycle_start_time = None
    inst._resync_after_resume()
    assert inst.control.output_on.call_count == 0


# ---- 창 끝 경계: 자연 종료를 빼앗지 않는다 ----
#
# 창 길이와 한 pass 가 딱 맞는 설정(문서가 권하는 기본형)에서는 마지막 스텝의
# duration 만료와 창 종료가 같은 순간에 온다. 창 판정이 먼저 이기면 드라이버가
# 스스로 끝내기 전에 바깥에서 OFF 가 들어가고, 그 세션의 개방 시간이 기록되지
# 않는다. 실측(2026-08-27): 07:30 창 끝에 걸린 v12·펌프는 ON 마커만 남고
# duration 이 없었던 반면, 06:30 에 창 안에서 끝난 v11 은 3600.09초로 남았다.

CYCLE_T0 = 1787900000.0


def make_grace_controller(end=7200.0):
    inst = make_controller()
    inst.cycle_start_time = CYCLE_T0
    inst._close_grace_started = None
    action = _act('act-1', 'out-1,0')
    inst.current_schedule = [{'action': action, 'start': 3600.0, 'end': end,
                              'is_output': True, 'type': 'single'}]
    inst.active_actions = {'act-1'}
    return inst


def test_grace_waits_when_the_step_is_about_to_finish_naturally():
    inst = make_grace_controller(end=7200.0)
    # 창이 닫히는 순간 = 스텝의 자연 종료 시각.
    assert inst._within_close_grace(CYCLE_T0 + 7200.0) is True
    assert inst._close_grace_started == CYCLE_T0 + 7200.0


def test_grace_does_not_wait_for_a_step_with_time_left():
    """한참 남은 스텝은 자연 종료가 아니라 진짜 절단이다 — 기다려도 소용없고
    기다리는 만큼 창을 넘긴다."""
    inst = make_grace_controller(end=7200.0)
    assert inst._within_close_grace(CYCLE_T0 + 3600.0) is False


def test_grace_expires_and_stops_waiting():
    inst = make_grace_controller(end=7200.0)
    close_at = CYCLE_T0 + 7200.0
    assert inst._within_close_grace(close_at) is True
    # 유예 안에서는 계속 기다린다
    assert inst._within_close_grace(close_at + 2.0) is True
    # 넘기면 더 기다리지 않는다 — 밸브를 열어 두는 쪽이 기록보다 나쁘다.
    assert inst._within_close_grace(close_at + inst.WINDOW_CLOSE_GRACE_SEC) is False


def test_grace_is_not_needed_when_nothing_is_running():
    inst = make_grace_controller()
    inst.active_actions = set()
    assert inst._within_close_grace(CYCLE_T0 + 7200.0) is False


def test_grace_is_skipped_without_an_active_cycle():
    inst = make_grace_controller()
    inst.cycle_start_time = None
    assert inst._within_close_grace(CYCLE_T0 + 7200.0) is False


def test_grace_ignores_steps_missing_from_the_plan():
    inst = make_grace_controller()
    inst.active_actions = {'ghost'}      # 계획에 없는 id
    assert inst._within_close_grace(CYCLE_T0 + 7200.0) is False


def test_grace_covers_a_step_that_already_passed_its_end():
    """만료 시각을 막 지난 스텝도 기다린다 — 드라이버 기록이 도착할 참이다."""
    inst = make_grace_controller(end=7200.0)
    assert inst._within_close_grace(CYCLE_T0 + 7201.0) is True


# ---- 자투리 스킵은 한 격자점당 한 번만 남긴다 ----
#
# `_reject_runt` 가 None 을 돌려주면 호출자는 `cycle_start_time` 을 갱신하지
# 않는다. 그래서 0.1초짜리 `loop()` 는 창이 닫힐 때까지 같은 판정을 되풀이하고,
# 매번 ERROR 를 찍는다. 실측(2026-08-29 로컬, 20:30~21:00 창): 같은 한 문장이
# **17,118줄** 남아 로그 3.4MB 를 채웠다. 판정은 옳았지만 그 옆의 진짜 경고가
# 묻힌다.

RUNT_ENTRY = {'enabled': True, 'start': '05:00', 'end': '15:03', 'period': 3600}


def _runt_setup():
    inst = _with_plan(make_controller(), 2400)
    inst.cycle_start_time = ANCHOR + 9 * PERIOD           # 14:00 사이클 진행 중
    return inst


def test_runt_skip_is_logged_once_not_every_loop():
    inst = _runt_setup()
    now = ANCHOR + 10 * PERIOD + 1                        # 15:00 격자점 직후
    for tick in range(200):                               # 루프 20초치
        assert inst._next_cycle_start(RUNT_ENTRY, now + tick * 0.1, PERIOD) is None
    assert inst.logger.error.call_count == 1


def test_a_later_grid_point_is_logged_again():
    """다음 격자점은 별개의 사건이다 — 억제가 다음 사이클까지 먹으면 안 된다."""
    inst = _runt_setup()
    inst._next_cycle_start(RUNT_ENTRY, ANCHOR + 10 * PERIOD + 1, PERIOD)
    inst.cycle_start_time = ANCHOR + 10 * PERIOD
    inst._next_cycle_start(RUNT_ENTRY, ANCHOR + 11 * PERIOD + 1, PERIOD)
    assert inst.logger.error.call_count == 2


# ---- 유예 중에도 스텝은 정상적으로 끝나야 한다 ----
#
# `_within_close_grace` 가 True 인 동안 `loop()` 이 `process_cycle` 을 건너뛰면
# `active_actions` 는 영영 비지 않는다. 유예는 매번 만료되고, 자연 종료한 스텝이
# "중간에 끊겼다" 로 보고된다. 실측(2026-08-30): 창 끝 07:30 에 매일 절단 ERROR 가
# 떴지만 v12 의 개방 시간은 3605초로 멀쩡히 기록돼 있었다 — 경고가 사실과 달랐다.

def _plan_two_steps():
    """0~3600 v11, 3600~7200 v12."""
    return [
        {'action': _act('act-a', 'out-a,0'), 'start': 0.0, 'end': 3600.0,
         'is_output': True, 'type': 'single'},
        {'action': _act('act-b', 'out-b,0'), 'start': 3600.0, 'end': 7200.0,
         'is_output': True, 'type': 'single'},
    ]


def make_off_only_controller():
    inst = make_controller()
    inst.cycle_start_time = CYCLE_T0
    inst.current_schedule = _plan_two_steps()
    inst.turn_on_action = MagicMock()
    inst.turn_off_action = MagicMock()
    inst._off_order = lambda ids: list(ids)
    return inst


def test_off_only_finishes_a_step_that_reached_its_end():
    inst = make_off_only_controller()
    inst.active_actions = {'act-b'}
    inst.process_cycle(CYCLE_T0 + 7200.0, off_only=True)
    assert inst.turn_off_action.call_count == 1
    assert inst.turn_off_action.call_args[0][0].unique_id == 'act-b'


def test_off_only_never_opens_a_valve_outside_the_window():
    """창이 닫힌 뒤 다음 스텝이 시작 시각에 들어와도 켜지 않는다."""
    inst = make_off_only_controller()
    inst.active_actions = set()
    inst.process_cycle(CYCLE_T0 + 3600.0, off_only=True)   # act-b 의 시작 시각
    inst.turn_on_action.assert_not_called()


def test_normal_cycle_still_turns_steps_on():
    inst = make_off_only_controller()
    inst.active_actions = set()
    inst.process_cycle(CYCLE_T0 + 3600.0)
    assert inst.turn_on_action.call_count == 1
    assert inst.turn_on_action.call_args[0][0].unique_id == 'act-b'


def test_off_only_leaves_a_step_that_is_still_running():
    inst = make_off_only_controller()
    inst.active_actions = {'act-b'}
    inst.process_cycle(CYCLE_T0 + 5000.0, off_only=True)   # 아직 진행 중
    inst.turn_off_action.assert_not_called()
