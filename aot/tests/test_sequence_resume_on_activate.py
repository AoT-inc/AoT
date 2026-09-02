# coding=utf-8
"""시퀀스를 껐다 켤 때 **이어서 갈지 처음부터 갈지**를 사용자가 정한다.

## 왜 이 설정이 있나

껐다 켜면 지금까지는 **언제나 이어서** 갔다. 비활성화해도 그 사이클의 런타임
상태가 남고, 재활성화 때 `_load_runtime_state()` 가 그것을 복원하기 때문이다.
그 복원은 원래 **데몬 재시작**을 위한 것이다 — 재시작이 관수를 끊지 않게 하려고
만들었다. 그런데 사용자가 의도적으로 끈 경우와 구분되지 않았다.

두 요구는 실제로 다르다. 잠깐 멈췄다 재개하는 것이면 이어서가 맞고, 설정을 고치고
다시 돌리는 것이면 처음부터가 맞다. 예전에는 후자를 하려면 주기가 지나기를 기다리는
수밖에 없었다(`_load_runtime_state` 는 주기보다 오래된 상태만 버린다).

**데몬 재시작은 이 설정과 무관하다.** 옵션은 "비활성화될 때 저장된 상태를 지울지"
만 정하고, 재시작은 `is_activated` 를 건드리지 않아 그 분기를 지나지 않는다.
"""
from unittest.mock import MagicMock

import pytest

import aot.controllers.controller_trigger_sequence as seq_mod


class _Trigger:
    def __init__(self, is_activated=False, resume=True):
        self.is_activated = is_activated
        self.resume_on_activate = resume


def make_controller(cycle_start=1000.0, active=None):
    inst = object.__new__(seq_mod.SequenceTriggerController)
    inst.unique_id = 'seq-resume-test'
    inst.logger = MagicMock()
    inst.cycle_start_time = cycle_start
    inst.active_actions = set(active or [])
    inst.current_schedule = []
    inst.stop_all_active = MagicMock()
    inst._save_runtime_state = MagicMock()
    inst._clear_runtime_state = MagicMock()
    return inst


def run_finally_with(monkeypatch, inst, trigger):
    monkeypatch.setattr(seq_mod, 'db_retrieve_table_daemon',
                        lambda *a, **kw: trigger)
    inst.run_finally()


# ---- 옵션 읽기: 모르면 기존 동작 ----

@pytest.mark.parametrize('value,expected', [
    (True, True), (1, True), (False, False), (0, False), (None, True),
])
def test_option_reading(value, expected):
    assert seq_mod.SequenceTriggerController._resume_on_activate(
        _Trigger(resume=value)) is expected


def test_a_missing_column_means_continue():
    """마이그레이션 전 설치에서 '처음부터' 로 넘어가면, 아무도 그렇게 정하지
    않았는데 진행 중이던 관수가 사라진다."""
    class NoColumn:
        is_activated = False

    assert seq_mod.SequenceTriggerController._resume_on_activate(NoColumn()) is True


def test_a_broken_trigger_row_means_continue():
    class Boom:
        @property
        def resume_on_activate(self):
            raise RuntimeError('db gone')

    assert seq_mod.SequenceTriggerController._resume_on_activate(Boom()) is True


# ---- 비활성화 경로 ----

def test_deactivating_with_restart_clears_the_saved_cycle(monkeypatch):
    inst = make_controller()
    run_finally_with(monkeypatch, inst, _Trigger(is_activated=False, resume=False))

    inst._clear_runtime_state.assert_called_once()
    inst.stop_all_active.assert_called_once()


def test_deactivating_with_resume_keeps_the_saved_cycle(monkeypatch):
    """기본값이다 — 업그레이드했다고 관수 동작이 달라지면 안 된다."""
    inst = make_controller()
    run_finally_with(monkeypatch, inst, _Trigger(is_activated=False, resume=True))

    inst._clear_runtime_state.assert_not_called()
    inst.stop_all_active.assert_called_once()


def test_a_daemon_restart_never_clears_regardless_of_the_option(monkeypatch):
    """핵심 회귀. 재시작은 사용자가 끈 것이 아니다 — 진행 중이던 관수를 이어야
    한다. 옵션이 '처음부터' 여도 마찬가지다."""
    inst = make_controller()
    run_finally_with(monkeypatch, inst, _Trigger(is_activated=True, resume=False))

    inst._clear_runtime_state.assert_not_called()
    inst.stop_all_active.assert_not_called()
    inst._save_runtime_state.assert_called_once()


def test_an_idle_sequence_still_stops_cleanly(monkeypatch):
    """사이클이 없으면 저장할 것도 없다 — 끄기만 한다."""
    inst = make_controller(cycle_start=None)
    run_finally_with(monkeypatch, inst, _Trigger(is_activated=True, resume=True))

    inst.stop_all_active.assert_called_once()
    inst._save_runtime_state.assert_not_called()


# ---- 위젯 옵션이 실제로 이어져 있는가 ----

def _widget_source():
    import pathlib
    return (pathlib.Path(__file__).parent.parent
            / 'widgets' / 'widget_trigger_sequence.py').read_text()


def test_widget_exposes_the_option():
    src = _widget_source()
    assert "'id': 'resume_on_activate'" in src, "위젯 설정에 옵션이 없다"
    assert "'default_value': 'resume'" in src, (
        "기본값이 '이어서' 가 아니다 — 업그레이드가 동작을 바꾼다")


def test_widget_pushes_the_option_to_the_trigger():
    """위젯에만 저장되면 데몬은 그 값을 영영 보지 못한다."""
    src = _widget_source()
    assert 'trigger.resume_on_activate =' in src


def test_the_model_carries_the_column():
    from aot.databases.models import Trigger
    assert hasattr(Trigger, 'resume_on_activate')


def test_the_migration_is_the_alembic_head():
    """마이그레이션을 넣고 상수를 안 올리면 그 마이그레이션은 영영 실행되지
    않는다 — 앱은 'up to date' 를 남기고 정상 기동하며, 모델은 존재하지 않는
    컬럼을 참조한 채 돈다."""
    from aot.config import ALEMBIC_VERSION
    assert ALEMBIC_VERSION == 'p6_61_sequence_resume_on_activate_20260901'
