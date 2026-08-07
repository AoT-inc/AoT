# coding=utf-8
"""Shutdown must always finish, and a recovered device must be usable again.

From the 2026-08-07 audit. logs/aot.log shows the last graceful shutdown
completing on 2026-07-28; the 37 daemon restarts after it were all SIGKILL.
Three separate defects kept shutdown from ever completing, and a fourth left
recovered radios permanently degraded.

  * run_finally() indexed self.output for every id in self.output_unique_id,
    but the latter is filled in before the 'no_run' check and before the module
    even loads -- so an output_spacer or a failed import raised KeyError out of
    a finally block, killing the thread and dropping the Shutdown State of
    every output after it. Shutdown then looked fast and clean.
  * The controller joins were unbounded, so one stuck loop() hung shutdown.
  * The Output join was a silent 15 s, while sending Shutdown States is O(N) on
    the LoRaWAN pacing slot (~8 s each) -- a 30-output site got through about
    two of them and never said so.
  * _offline was only ever cleared by confirm_command(), so a device that came
    back and was heartbeating stayed in single-shot probe mode.
"""
import logging
import threading

import pytest


# --- run_finally() must not abandon the rest of the site ----------------------

class _FakeOutput:
    def __init__(self, name, raises=None):
        self.name = name
        self.raises = raises
        self.shut_down = False

    def shutdown(self, _timer):
        if self.raises:
            raise self.raises
        self.shut_down = True


def _make_controller(outputs, unique_ids=None):
    from aot.controllers.controller_output import OutputController

    ctrl = OutputController.__new__(OutputController)
    ctrl.logger = logging.getLogger('test_shutdown')
    ctrl.output = dict(outputs)
    # output_unique_id is the authoritative iteration order and legitimately
    # holds ids that never got a driver.
    ctrl.output_unique_id = {k: {0: None} for k in (unique_ids or outputs)}
    ctrl._audit_lifecycle = lambda *a: None
    return ctrl


def test_an_output_with_no_driver_is_skipped():
    """output_spacer ('no_run') and failed module loads land here."""
    real = _FakeOutput('real')
    ctrl = _make_controller({'real': real},
                            unique_ids=['spacer', 'real'])

    ctrl.run_finally()  # used to raise KeyError on 'spacer'

    assert real.shut_down, \
        "an output with no driver aborted shutdown for everything after it"


def test_one_raising_driver_does_not_drop_the_rest():
    boom = _FakeOutput('boom', raises=RuntimeError("radio gone"))
    after = _FakeOutput('after')
    ctrl = _make_controller({'boom': boom, 'after': after})

    ctrl.run_finally()

    assert after.shut_down, \
        "one failing driver took the remaining Shutdown States down with it"


# --- join budgets -------------------------------------------------------------

def test_join_budgets_are_bounded_and_output_gets_the_larger_one():
    from aot.aot_daemon import (CONTROLLER_JOIN_TIMEOUT_S,
                                OUTPUT_JOIN_TIMEOUT_S)

    assert 0 < CONTROLLER_JOIN_TIMEOUT_S
    assert 0 < OUTPUT_JOIN_TIMEOUT_S
    # Sending Shutdown States is O(N) on the pacing slot; the controller joins
    # are not. The old code had this backwards -- unbounded controller joins
    # and a 15 s Output join.
    assert OUTPUT_JOIN_TIMEOUT_S > CONTROLLER_JOIN_TIMEOUT_S


def test_the_output_join_fits_inside_the_container_stop_grace_period():
    """docker-compose sends SIGKILL after stop_grace_period; a budget larger
    than that cannot be honoured and would just hide the cutoff again."""
    import re
    from pathlib import Path

    from aot.aot_daemon import OUTPUT_JOIN_TIMEOUT_S

    compose = Path(__file__).resolve().parents[2] / 'docker' / 'docker-compose.yml'
    grace = re.search(r'stop_grace_period:\s*(\d+)s', compose.read_text())
    assert grace, "stop_grace_period disappeared from docker-compose.yml"

    assert OUTPUT_JOIN_TIMEOUT_S < int(grace.group(1)), (
        "the Output join budget exceeds the container's stop grace period, so "
        "SIGKILL lands before the join can finish")


def test_startup_aborts_when_shutdown_is_requested():
    """A SIGTERM during boot used to be ignored until SIGKILL, because
    _graceful_stop only lowers daemon_run and nothing on the startup path
    read it. Boot is the slowest part of the run and therefore the most
    likely moment to be stopped."""
    import inspect

    from aot.aot_daemon import DaemonController

    src = inspect.getsource(DaemonController.start_all_controllers)
    assert 'self.daemon_run' in src, (
        "start_all_controllers() never checks daemon_run, so a stop requested "
        "during startup is ignored until the process is killed")


# --- a recovered device must leave probe mode ---------------------------------

def _confirmable():
    from aot.outputs.confirmable_output import ConfirmableOutputMixin

    obj = ConfirmableOutputMixin.__new__(ConfirmableOutputMixin)
    obj._confirm_init()
    return obj


def test_a_heartbeat_clears_the_offline_mark():
    obj = _confirmable()
    obj._offline.add(0)

    assert obj.note_device_alive(0) is True
    assert not obj.is_offline(0), \
        "a device that is demonstrably reachable stayed in probe mode"


def test_a_heartbeat_does_not_invent_a_state():
    """Proof of life is not proof of position. A heartbeat must not confirm
    on/off, and must not clear the 'last command was never confirmed' fault --
    that is still true."""
    obj = _confirmable()
    obj.output_states = {0: False}
    obj._cmd_fault_at[0] = 'earlier'
    obj._offline.add(0)

    obj.note_device_alive(0)

    assert obj._cmd_confirmed == {}, "a heartbeat fabricated a confirmed state"
    assert obj.is_fault(0), "the unconfirmed command was silently forgiven"


def test_note_device_alive_is_harmless_when_already_online():
    obj = _confirmable()
    assert obj.note_device_alive(0) is False


def test_note_device_alive_is_thread_safe():
    """It runs on the MQTT uplink thread while commands run elsewhere."""
    obj = _confirmable()
    errors = []

    def worker():
        try:
            for _ in range(200):
                obj._offline.add(0)
                obj.note_device_alive(0)
        except Exception as err:  # pragma: no cover - only on a real race
            errors.append(err)

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors


# --- the gRPC deadline --------------------------------------------------------

def test_grpc_enqueue_has_a_deadline():
    """Without one the call inherits no bound at all, and the thread it parks
    is sometimes the non-daemon auto-off worker that blocks interpreter exit."""
    import inspect

    from aot.outputs.on_off_chirpstack import (GRPC_ENQUEUE_TIMEOUT_S,
                                               OutputModule)

    assert GRPC_ENQUEUE_TIMEOUT_S > 0
    src = inspect.getsource(OutputModule._send_downlink)
    assert 'timeout=GRPC_ENQUEUE_TIMEOUT_S' in src, \
        "client.Enqueue() is called without a deadline"
