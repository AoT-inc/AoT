# coding=utf-8
"""OutputController settings-reload behaviour.

Covers the two fixes for "Modify Output: Could not connect to Daemon:
receiving: timeout":

1. suppress_state_transition() stops a settings save from replaying the
   Startup/Shutdown State, which physically actuates the device and (on
   LoRaWAN) spends downlink slots.
2. output_setup() answers immediately instead of blocking the caller for the
   length of the reload, which exceeded the 10 s RPC cap in aot_client.py.

OutputController is built with __new__ so the tests touch neither the database
nor a running daemon — only the two methods under test are exercised.
"""
import logging
import threading
import time

import pytest

from aot.controllers.controller_output import OutputController


def make_controller():
    """An OutputController with just the state the two methods under test use."""
    ctrl = OutputController.__new__(OutputController)
    ctrl.logger = logging.getLogger('test_output_setup')
    ctrl._setup_locks = {}
    ctrl._setup_locks_guard = threading.Lock()
    return ctrl


class FakeOutput:
    def __init__(self, options_channels):
        self.options_channels = options_channels


# --- suppress_state_transition ------------------------------------------------

def test_suppress_blanks_every_channel():
    """0/1 mean on/off; anything else means "do nothing" to every driver."""
    out = FakeOutput({'state_shutdown': {0: 1, 1: 0, 2: 1}})
    make_controller().suppress_state_transition(out, 'state_shutdown')
    assert out.options_channels['state_shutdown'] == {0: None, 1: None, 2: None}


def test_suppress_leaves_other_options_alone():
    out = FakeOutput({'state_startup': {0: 1}, 'state_shutdown': {0: 1}})
    make_controller().suppress_state_transition(out, 'state_startup')
    assert out.options_channels['state_startup'] == {0: None}
    assert out.options_channels['state_shutdown'] == {0: 1}


def test_suppress_is_a_noop_for_modules_without_the_option():
    """Not every driver defines these; a missing key must not raise."""
    out = FakeOutput({'state_startup': {0: 1}})
    make_controller().suppress_state_transition(out, 'state_shutdown')
    assert out.options_channels == {'state_startup': {0: 1}}


def test_suppress_survives_a_module_with_no_options_channels():
    ctrl = make_controller()
    ctrl.suppress_state_transition(object(), 'state_shutdown')  # must not raise


# --- output_setup -------------------------------------------------------------

def test_output_setup_returns_before_a_slow_reload_finishes():
    """The regression: a reload longer than the 10 s RPC cap timed the caller out."""
    ctrl = make_controller()
    released = threading.Event()
    finished = threading.Event()

    def slow_add_mod(output_id):
        released.wait(timeout=10)
        finished.set()
        return 0, 'done'

    ctrl.add_mod_output = slow_add_mod

    started = time.monotonic()
    error, msg = ctrl.output_setup('Modify', 'abc12345-0000')
    elapsed = time.monotonic() - started

    assert error == 0
    assert 'background' in msg
    assert elapsed < 1.0, f"output_setup blocked for {elapsed:.2f}s"
    assert not finished.is_set(), "reload ran synchronously"

    released.set()
    assert finished.wait(timeout=10), "reload never ran"


def test_output_setup_routes_delete_to_del_output():
    ctrl = make_controller()
    called = threading.Event()

    def del_output(output_id):
        called.set()
        return 0, 'deleted'

    ctrl.del_output = del_output
    ctrl.add_mod_output = lambda output_id: pytest.fail("Delete must not add/modify")

    assert ctrl.output_setup('Delete', 'abc12345-0000')[0] == 0
    assert called.wait(timeout=10)


def test_output_setup_serializes_reloads_of_the_same_output():
    """Back-to-back saves must not race on self.output[output_id]."""
    ctrl = make_controller()
    concurrent = []
    active = 0
    guard = threading.Lock()
    done = threading.Semaphore(0)

    def reload(output_id):
        nonlocal active
        with guard:
            active += 1
            concurrent.append(active)
        time.sleep(0.05)
        with guard:
            active -= 1
        done.release()
        return 0, 'ok'

    ctrl.add_mod_output = reload
    for _ in range(4):
        ctrl.output_setup('Modify', 'abc12345-0000')
    for _ in range(4):
        assert done.acquire(timeout=10), "a reload never ran"

    assert max(concurrent) == 1, f"reloads overlapped: {concurrent}"


def test_output_setup_allows_different_outputs_to_reload_in_parallel():
    """The lock is per output ID, so one slow device must not stall the rest."""
    ctrl = make_controller()
    first_running = threading.Event()
    second_done = threading.Event()

    def reload(output_id):
        if output_id.startswith('slow'):
            first_running.set()
            second_done.wait(timeout=10)
        else:
            assert first_running.wait(timeout=10)
            second_done.set()
        return 0, 'ok'

    ctrl.add_mod_output = reload
    ctrl.output_setup('Modify', 'slow1234-0000')
    assert first_running.wait(timeout=10)
    ctrl.output_setup('Modify', 'fast1234-0000')
    assert second_done.wait(timeout=10), "a second output was blocked by the first"


def test_output_setup_rejects_an_unknown_action():
    ctrl = make_controller()
    ctrl.add_mod_output = lambda output_id: pytest.fail("must not run")
    ctrl.del_output = lambda output_id: pytest.fail("must not run")

    error, msg = ctrl.output_setup('Frobnicate', 'abc12345-0000')
    assert error == 1
    assert 'Invalid' in msg


def test_output_setup_logs_a_failing_reload(caplog):
    """Async means failures no longer reach the flash message — they must be logged."""
    ctrl = make_controller()
    done = threading.Event()

    def failing(output_id):
        try:
            return 1, 'driver exploded'
        finally:
            done.set()

    ctrl.add_mod_output = failing
    with caplog.at_level(logging.ERROR):
        ctrl.output_setup('Modify', 'abc12345-0000')
        assert done.wait(timeout=10)
        for _ in range(100):          # let the worker finish logging
            if 'driver exploded' in caplog.text:
                break
            time.sleep(0.01)

    assert 'driver exploded' in caplog.text


def test_output_setup_logs_a_raising_reload(caplog):
    ctrl = make_controller()
    done = threading.Event()

    def raising(output_id):
        try:
            raise RuntimeError('boom')
        finally:
            done.set()

    ctrl.add_mod_output = raising
    with caplog.at_level(logging.ERROR):
        ctrl.output_setup('Modify', 'abc12345-0000')
        assert done.wait(timeout=10)
        for _ in range(100):
            if 'boom' in caplog.text:
                break
            time.sleep(0.01)

    assert 'boom' in caplog.text
