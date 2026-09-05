# coding=utf-8
"""작동 중에 **스텝 설정**을 바꾸면 어떻게 되는가.

## 왜 이 테스트가 있나

창(window) 변경은 `self.schedule` 을 다시 읽으므로 곧바로 반영된다. 그런데
스텝별 시작·끝을 담은 `self.current_schedule` 은 `start_new_cycle()` 에서만
세워져서, **작동 중에 스텝 길이·교차 시간·요일별 on/off 를 고치면 다음
사이클까지 반영되지 않았다** — 주기가 3시간이면 세 시간 뒤다. 저장은 되고
화면도 새 값을 보여주므로 사용자는 반영된 줄 안다.

`refresh_settings()` 가 계획을 다시 세우게 하면 그 갭은 닫히지만, 그 순간
함정이 둘 열린다. 이 파일은 그 둘을 고정한다.

**함정 1 — 이미 끝난 스텝이 다시 켜진다.** 슬롯은 앞 스텝의 끝에 이어 붙으므로
앞 스텝을 줄이면 뒤 스텝들이 통째로 앞당겨진다. 그러면 **이미 물을 준 스텝의
창이 지금 elapsed 를 다시 품게 되어** 그 밸브가 한 번 더 열린다. 설정을 고쳤을
뿐인데 관수가 두 번 되는 것이라 사용자는 원인을 짐작할 수 없다.

**함정 2 — 계획에서 빠진 스텝의 밸브가 열린 채 잊힌다.** 사용자가 그 스텝을
오늘 요일에서 끄거나 지우면 다음 재계산에서 사라지는데, 예전 `process_cycle`
은 그때 집합에서 빼기만 하고 **OFF 를 보내지 않았다**. 아무도 닫지 않으므로
창이 닫혀도, 시퀀스를 꺼도 그대로다.
"""
from unittest.mock import MagicMock

import pytest

import aot.controllers.controller_trigger_sequence as seq_mod


def _action(uid, action_type='output_on_off'):
    a = MagicMock()
    a.unique_id = uid
    a.action_type = action_type
    return a


def make_controller(schedule_items, active=(), completed=()):
    inst = object.__new__(seq_mod.SequenceTriggerController)
    inst.unique_id = 'seq-midcycle-test'
    inst.logger = MagicMock()
    inst.cycle_start_time = 1000.0
    inst.current_schedule = schedule_items
    inst.active_actions = set(active)
    inst._completed_actions = set(completed)
    inst.turn_on_action = MagicMock()
    inst.turn_off_action = MagicMock(return_value=True)
    inst._force_off_unscheduled = MagicMock()
    return inst


def item(uid, start, end, typ='single'):
    return {'action': _action(uid), 'start': start, 'end': end,
            'is_output': True, 'type': typ}


# ---- 함정 1: 이미 끝난 스텝을 다시 켜지 않는다 ----

def test_a_completed_step_is_not_switched_on_again():
    """앞 스텝을 줄여 슬롯이 앞당겨져도, 이번 사이클에 이미 끝난 스텝은 그대로 둔다."""
    inst = make_controller([item('step-a', 0.0, 1800.0)], completed={'step-a'})
    inst.process_cycle(inst.cycle_start_time + 900)      # 창 안이지만 이미 끝난 스텝
    inst.turn_on_action.assert_not_called()


def test_a_step_that_never_ran_still_switches_on():
    """가드가 과하면 정상 관수가 통째로 멈춘다."""
    inst = make_controller([item('step-a', 0.0, 1800.0)])
    inst.process_cycle(inst.cycle_start_time + 900)
    inst.turn_on_action.assert_called_once()


def test_finishing_a_step_records_it_as_completed():
    """끝난 사실이 기록돼야 위 가드가 동작한다."""
    inst = make_controller([item('step-a', 0.0, 600.0)], active={'step-a'})
    inst.process_cycle(inst.cycle_start_time + 900)      # 창을 지났다
    inst.turn_off_action.assert_called_once()
    assert 'step-a' in inst._completed_actions


def test_a_failed_off_is_not_recorded_as_completed():
    """OFF 가 실패하면 아직 열려 있다 — 완료로 적으면 재시도 대상에서 빠진다."""
    inst = make_controller([item('step-a', 0.0, 600.0)], active={'step-a'})
    inst.turn_off_action = MagicMock(return_value=False)
    inst.process_cycle(inst.cycle_start_time + 900)
    assert 'step-a' not in inst._completed_actions


def test_a_new_cycle_clears_the_completed_record():
    """다음 사이클에서는 당연히 다시 켜져야 한다."""
    inst = make_controller([], completed={'step-a'})
    inst.stop_all_active = MagicMock()
    inst.build_cycle_schedule = MagicMock()
    inst.start_new_cycle(2000.0)
    assert inst._completed_actions == set()


# ---- 함정 2: 계획에서 빠진 스텝은 끈다 ----

def test_a_step_dropped_from_the_plan_is_switched_off_not_forgotten():
    """예전에는 집합에서 빼기만 해 밸브가 열린 채 잊혔다."""
    inst = make_controller([], active={'ghost'})     # 계획에 없는데 켜져 있다
    inst.process_cycle(inst.cycle_start_time + 10)
    inst._force_off_unscheduled.assert_called_once_with('ghost')


def test_force_off_sends_off_for_output_steps(monkeypatch):
    inst = make_controller([], active={'ghost'})
    del inst._force_off_unscheduled                   # 진짜 구현을 쓴다
    monkeypatch.setattr(seq_mod, 'db_retrieve_table_daemon',
                        lambda *a, **kw: _action('ghost', 'output_on_off'))
    inst._force_off_unscheduled('ghost')
    inst.turn_off_action.assert_called_once()
    assert inst.turn_off_action.call_args[0][1] == {'is_output': True}


def test_force_off_just_drops_non_output_steps(monkeypatch):
    """알림 같은 스텝은 끌 것이 없다."""
    inst = make_controller([], active={'note'})
    del inst._force_off_unscheduled
    monkeypatch.setattr(seq_mod, 'db_retrieve_table_daemon',
                        lambda *a, **kw: _action('note', 'email'))
    inst._force_off_unscheduled('note')
    inst.turn_off_action.assert_not_called()
    assert 'note' not in inst.active_actions


def test_force_off_survives_a_db_failure(monkeypatch):
    """조회가 깨져도 루프가 죽으면 안 된다 — 대신 크게 남긴다."""
    def boom(*a, **kw):
        raise RuntimeError('db gone')
    inst = make_controller([], active={'ghost'})
    del inst._force_off_unscheduled
    monkeypatch.setattr(seq_mod, 'db_retrieve_table_daemon', boom)
    inst._force_off_unscheduled('ghost')
    assert 'ghost' not in inst.active_actions
    assert inst.logger.error.called


# ---- 재계산 배선 ----

def test_refresh_settings_rebuilds_the_running_cycles_plan():
    """이 배선이 빠지면 스텝 설정 변경이 다음 사이클까지 반영되지 않는다."""
    import inspect
    src = inspect.getsource(seq_mod.SequenceTriggerController.refresh_settings)
    assert 'self.build_cycle_schedule()' in src, (
        'refresh_settings 가 계획을 다시 세우지 않는다 — 작동 중 스텝 설정 '
        '변경이 다음 사이클까지 반영되지 않는다')
    # 사이클이 없을 때(창 밖)는 세울 것이 없다 — 굳이 돌면 헛일이고
    # `cycle_start_time` 이 None 인 상태에서 process_cycle 이 터진다.
    assert 'if self.cycle_start_time is not None:' in src
