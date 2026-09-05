# coding=utf-8
"""Verify SequenceTriggerController resumes an in-progress cycle across a
daemon restart instead of restarting it from elapsed=0 (which would force
already-running outputs off, then immediately back on).

Fully isolated from any real DB: a temp SQLite file is created with just the
function_runtime_state table, and AOT_DB_PATH is monkeypatched inside
controller_trigger_sequence's module namespace to point at it. No fixture
touches the project's real aot.db.
"""
import json
import os
import tempfile
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine

import aot.controllers.controller_trigger_sequence as seq_mod
from aot.databases.models import FunctionRuntimeState


@pytest.fixture
def temp_runtime_db(monkeypatch):
    fd, path = tempfile.mkstemp(suffix='.db')
    os.close(fd)
    db_uri = f'sqlite:///{path}'
    engine = create_engine(db_uri)
    FunctionRuntimeState.__table__.create(bind=engine)
    engine.dispose()

    monkeypatch.setattr(seq_mod, 'AOT_DB_PATH', db_uri)
    yield db_uri

    try:
        os.remove(path)
    except OSError:
        pass


def make_controller():
    """Bare SequenceTriggerController with just the attributes the
    persistence methods touch — bypasses __init__ (which would build a real
    DaemonControl/Pyro5 client and thread state we don't need here)."""
    inst = object.__new__(seq_mod.SequenceTriggerController)
    inst.unique_id = 'test-function-id-0000'
    inst.logger = MagicMock()
    inst.cycle_start_time = None
    inst.active_weekday = None
    inst.active_actions = set()
    inst.sequence_cycle_duration = 43200.0
    inst.build_cycle_schedule = MagicMock()
    return inst


# ---- save / load round trip ----

def test_save_then_load_restores_cycle_state(temp_runtime_db, monkeypatch):
    inst = make_controller()
    inst.cycle_start_time = 1785100000.0
    inst.active_weekday = 3
    inst.active_actions = {'action-a', 'action-b'}
    inst._save_runtime_state()

    inst2 = make_controller()
    inst2.sequence_cycle_duration = 43200.0
    # simulate "we're 100s into the persisted cycle" so it isn't stale
    monkeypatch.setattr(seq_mod.time, 'time', lambda: inst.cycle_start_time + 100)
    inst2._load_runtime_state()

    assert inst2.cycle_start_time == 1785100000.0
    assert inst2.active_weekday == 3
    assert inst2.active_actions == {'action-a', 'action-b'}
    inst2.build_cycle_schedule.assert_called_once()


def test_load_with_no_persisted_row_leaves_fresh_state(temp_runtime_db):
    inst = make_controller()
    inst._load_runtime_state()
    assert inst.cycle_start_time is None
    assert inst.active_actions == set()
    inst.build_cycle_schedule.assert_not_called()


def test_load_ignores_stale_cycle_older_than_period(temp_runtime_db, monkeypatch):
    saver = make_controller()
    # persisted 2 full periods ago -> stale
    monkeypatch.setattr(seq_mod.time, 'time', lambda: 2_000_000.0)
    saver.cycle_start_time = 2_000_000.0 - (2 * 43200.0)
    saver.active_actions = {'action-a'}
    saver._save_runtime_state()

    loader = make_controller()
    monkeypatch.setattr(seq_mod.time, 'time', lambda: 2_000_000.0)
    loader._load_runtime_state()

    assert loader.cycle_start_time is None
    assert loader.active_actions == set()
    loader.build_cycle_schedule.assert_not_called()


def test_stale_cycle_still_counts_as_having_run(temp_runtime_db, monkeypatch):
    """낡아서 복원을 포기해도 "저장된 사이클이 있었다" 는 사실은 남긴다.

    이 신호가 없으면 `initialize_variables` 가 데몬 장기 정지 후 재기동을
    "사용자가 방금 켰다" 로 오인해 첫 사이클을 격자가 아니라 재기동 시각에
    맞춘다 — 그날 남은 사이클이 전부 그만큼 밀려, 정각으로 5일 연속 검증했던
    격자 앵커링(2026-08-28 표류 수정)이 깨진다.
    """
    saver = make_controller()
    monkeypatch.setattr(seq_mod.time, 'time', lambda: 2_000_000.0)
    saver.cycle_start_time = 2_000_000.0 - (2 * 43200.0)
    saver._save_runtime_state()

    loader = make_controller()
    monkeypatch.setattr(seq_mod.time, 'time', lambda: 2_000_000.0)
    loader._load_runtime_state()

    assert loader.cycle_start_time is None          # 복원은 안 했지만
    assert loader._had_persisted_cycle is True      # 돌던 시퀀스였다는 것은 안다


def test_no_persisted_row_means_no_prior_cycle(temp_runtime_db):
    """행이 아예 없으면(신규 시퀀스, 또는 '처음부터 시작'으로 비운 뒤) 방금 켠 것이다."""
    loader = make_controller()
    loader._had_persisted_cycle = False
    loader._load_runtime_state()
    assert loader._had_persisted_cycle is False


def test_turn_on_action_persists_state(temp_runtime_db, monkeypatch):
    inst = make_controller()
    inst.cycle_start_time = 1785100000.0
    inst.dict_actions = {}
    monkeypatch.setattr(seq_mod, 'trigger_action', lambda *a, **k: None)

    action = MagicMock(unique_id='action-x')
    item = {'start': 0.0, 'end': 3600.0}
    inst.turn_on_action(action, item)

    assert 'action-x' in inst.active_actions
    with seq_mod.session_scope(seq_mod.AOT_DB_PATH) as sess:
        row = sess.query(FunctionRuntimeState).filter(
            FunctionRuntimeState.function_id == inst.unique_id).first()
        assert row is not None
        assert 'action-x' in json.loads(row.active_vars_json)['active_actions']


# ---- run_finally(): restart vs genuine deactivation ----

def test_run_finally_skips_force_off_when_still_activated_in_db(temp_runtime_db, monkeypatch):
    inst = make_controller()
    inst.cycle_start_time = 1785100000.0
    inst.active_actions = {'action-a'}
    inst.stop_all_active = MagicMock()

    fake_trigger = MagicMock(is_activated=True)
    monkeypatch.setattr(seq_mod, 'db_retrieve_table_daemon', lambda *a, **k: fake_trigger)

    inst.run_finally()

    inst.stop_all_active.assert_not_called()
    with seq_mod.session_scope(seq_mod.AOT_DB_PATH) as sess:
        row = sess.query(FunctionRuntimeState).filter(
            FunctionRuntimeState.function_id == inst.unique_id).first()
        assert row is not None


def test_run_finally_forces_off_on_genuine_deactivation(temp_runtime_db, monkeypatch):
    inst = make_controller()
    inst.cycle_start_time = 1785100000.0
    inst.active_actions = {'action-a'}
    inst.stop_all_active = MagicMock()

    fake_trigger = MagicMock(is_activated=False)  # controller_deactivate() already flipped this
    monkeypatch.setattr(seq_mod, 'db_retrieve_table_daemon', lambda *a, **k: fake_trigger)

    inst.run_finally()

    inst.stop_all_active.assert_called_once()


def test_run_finally_forces_off_when_trigger_row_missing(temp_runtime_db, monkeypatch):
    inst = make_controller()
    inst.cycle_start_time = 1785100000.0
    inst.stop_all_active = MagicMock()

    monkeypatch.setattr(seq_mod, 'db_retrieve_table_daemon', lambda *a, **k: None)

    inst.run_finally()

    inst.stop_all_active.assert_called_once()


def test_resume_resyncs_against_the_real_output_state(temp_runtime_db, monkeypatch):
    """재개는 복원으로 끝나지 않고 장치의 실제 상태와 맞춰야 한다.

    출력의 state_shutdown 이 OFF 면 장치는 꺼진 채 올라오는데, 재개가
    "이미 돌고 있다" 고만 보면 그 사이클의 남은 시간이 통째로 사라진다.
    """
    import time as _time

    inst = make_controller()
    inst.cycle_start_time = _time.time() - 100
    inst.active_actions = {'act-1'}
    inst._save_runtime_state()

    fresh = make_controller()
    fresh._resync_after_resume = MagicMock()
    fresh._load_runtime_state()

    assert fresh.cycle_start_time is not None      # 재개했고
    fresh._resync_after_resume.assert_called_once()  # 실제 상태와 맞췄다


def _resync_controller(state_returned):
    """`_resync_after_resume` 가 실제로 도는 데 필요한 최소 상태만 갖춘 컨트롤러."""
    import time as _time

    inst = make_controller()
    inst.cycle_start_time = _time.time() - 100
    inst.active_actions = {'act-1'}
    # 기본은 '활성' — 재개 재동기화가 원래 도는 상황이다. 비활성 케이스는
    # 아래 test_deactivated_sequence_does_not_reopen_outputs 가 따로 세운다.
    inst.is_activated = True

    action = MagicMock()
    action.unique_id = 'act-1'
    inst.current_schedule = [{'action': action, 'is_output': True, 'end': 1800.0}]
    inst._resolve_output_target = MagicMock(return_value=('out-1', 0))

    inst.control = MagicMock()
    inst.control.output_state.return_value = state_returned
    inst.control.output_on.return_value = (0, 'ok')
    return inst


def test_resume_notice_is_a_warning_that_survives_the_default_log_level():
    """재개 재동기화 알림은 오류가 아니라 경고다 — 그런데 **기본 설정에서 보여야** 한다.

    `log_level_debug` 는 기본이 꺼짐이고, 그때 컨트롤러 로거는 ERROR 로 올라간다
    (base_controller.set_log_level_debug). 그래서 이 알림을 컨트롤러 로거에
    warning 으로 남기면 한 줄도 기록되지 않는다 — 등급만 낮추면 안전장치가
    조용해지는 것이다. 게이트를 받지 않는 알림 로거로 남겨야 둘 다 성립한다.
    """
    import logging

    inst = _resync_controller('off')

    aot_root = logging.getLogger('aot')
    records = []

    class _Capture(logging.Handler):
        def emit(self, record):
            records.append(record)

    handler = _Capture()
    handler.setLevel(logging.INFO)
    prev_level = aot_root.level
    # 실제 파일 핸들러를 잠시 떼어 둔다 — 안 그러면 이 테스트가 돌 때마다
    # 운영 로그(aot.log)에 가짜 Action 줄이 쌓인다. 검증하려는 계약(알림이
    # `aot` 로 전파돼 그 핸들러에 잡힌다)은 그대로 확인된다.
    prev_handlers = aot_root.handlers[:]
    aot_root.handlers = [handler]
    aot_root.setLevel(logging.INFO)
    # log_level_debug 가 꺼진 상태 재현
    seq_mod.logger.setLevel(logging.ERROR)
    try:
        inst._resync_after_resume()
    finally:
        aot_root.handlers = prev_handlers
        aot_root.setLevel(prev_level)
        seq_mod.logger.setLevel(logging.NOTSET)

    resume = [r for r in records if '재개했으나 출력이 꺼져 있습니다' in r.getMessage()]
    assert resume, "재개 알림이 기본 로그 설정에서 통째로 사라졌다"
    assert resume[0].levelno == logging.WARNING, (
        f"오류가 아니라 경고여야 한다 (현재 {resume[0].levelname})")

    # 알림만 바뀌었을 뿐, 실제 조치(남은 시간만큼 재전송)는 그대로여야 한다.
    inst.control.output_on.assert_called_once()
    assert inst.control.output_on.call_args.kwargs['amount'] > 0


def test_resume_stays_silent_and_hands_off_when_output_is_already_on():
    """이미 켜져 있으면 알림도 재전송도 없다 — 켜진 밸브를 연장하면 더 나쁘다."""
    inst = _resync_controller('on')
    inst._resync_after_resume()
    inst.control.output_on.assert_not_called()


# ---- 비활성 시퀀스는 어떤 경로로도 출력을 켜지 않는다 ----
#
# 운영 농장 사고: 시퀀스를 꺼 두었는데 다음 날 오전에 밸브가 열렸다.
# initialize_variables() 는 데몬 기동 때만 도는 게 아니라 refresh_settings()
# 를 통해 설정 변경·순서 저장·활성 토글에서도 돈다. 거기에 활성 여부 가드가
# 없어서, 꺼 놓은 시퀀스도 _load_runtime_state -> _resync_after_resume ->
# output_on 까지 내려가 "남은 시간만큼" 밸브를 다시 열었다.

def test_deactivated_sequence_does_not_reopen_outputs():
    """비활성 시퀀스에서는 재개 재동기화가 출력을 켜지 않는다."""
    inst = _resync_controller('off')
    inst.is_activated = False

    inst._resync_after_resume()

    inst.control.output_on.assert_not_called()


def test_activated_sequence_still_reopens_outputs():
    """활성 시퀀스에서는 예전처럼 남은 시간만큼 다시 켠다(가드가 과하지 않은지)."""
    inst = _resync_controller('off')
    inst.is_activated = True

    inst._resync_after_resume()

    inst.control.output_on.assert_called_once()


def test_initialize_variables_guards_resume_on_activation():
    """비활성이면 initialize_variables 가 사이클 재개 자체를 건너뛴다.

    재개해야 _resync_after_resume 이 돌고, 그게 밸브를 여는 유일한 경로다.
    """
    import inspect
    src = inspect.getsource(seq_mod.SequenceTriggerController.initialize_variables)
    i_act = src.index('self.is_activated = self.trigger.is_activated')
    i_load = src.index('self._load_runtime_state()')
    between = src[i_act:i_load]
    assert 'if self.is_activated' in between, \
        "_load_runtime_state 앞에 활성 여부 가드가 없다 — 꺼진 시퀀스가 밸브를 연다"


def test_deactivated_controller_keeps_active_actions_for_shutdown():
    """가드가 걸려도 active_actions 는 남아 loop 이 끌 수 있어야 한다.

    로드를 건너뛰는 대신 진행 중이던 스텝 정보를 지워 버리면, 비활성화 순간
    열려 있던 밸브를 아무도 닫지 않게 된다 — 원래 버그보다 나쁘다.
    """
    inst = _resync_controller('off')
    inst.is_activated = False
    before = set(inst.active_actions)

    inst._resync_after_resume()

    assert inst.active_actions == before, "끌 대상을 잃어버렸다"
