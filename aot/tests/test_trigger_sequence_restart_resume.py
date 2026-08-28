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
