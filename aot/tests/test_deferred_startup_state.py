# coding=utf-8
"""Boot must not be held hostage by rate-limited Startup State downlinks.

From the 2026-08-07 audit. OutputController built outputs one at a time and
each ChirpStack driver sent its Startup State inline, where every downlink
waits on the site-wide 4 s LoRaWAN pacing slot. At two slots per command that
is ~8 s per output, and it is all on the boot path: initialize_variables() has
not returned, so ready.set() has not fired, no Input controller has started,
and OutputController.loop() is not yet supervising timed outputs. Measured at
~254 s for 30 outputs, on 19 consecutive boots.

The fix holds the Startup State back for drivers that opt in, then replays it
from a background thread once every output exists. It is opt-in rather than
blanket because Startup State is not applied uniformly: on_off_gpio derives
the pin level from the option value, so blanking it there would drive the pin
instead of skipping it.
"""
import logging

import pytest


# --- who defers ---------------------------------------------------------------

def test_drivers_do_not_defer_by_default():
    """Blanket deferral would change what non-output_switch drivers do."""
    from aot.outputs.base_output import AbstractOutput

    out = AbstractOutput.__new__(AbstractOutput)
    assert out.startup_state_is_deferrable() is False


def test_chirpstack_defers():
    from aot.outputs.on_off_chirpstack import OutputModule

    out = OutputModule.__new__(OutputModule)
    assert out.startup_state_is_deferrable() is True


def test_a_direct_gpio_driver_still_applies_inline():
    """on_off_gpio reads the option as a level, not as a command -- it must
    keep the default so nothing blanks it out from under the driver."""
    pytest.importorskip('RPi', reason='GPIO module needs its vendor package')
    from aot.outputs.on_off_gpio import OutputModule

    out = OutputModule.__new__(OutputModule)
    assert out.startup_state_is_deferrable() is False


# --- apply_startup_state() ----------------------------------------------------

def _make_output(state_startup, switch_returns=(0, 'success')):
    from aot.outputs.base_output import AbstractOutput

    out = AbstractOutput.__new__(AbstractOutput)
    out.logger = logging.getLogger('test_deferred_startup')
    out.unique_id = 'out-1'
    out.output_states = {}
    out.options_channels = {
        'state_startup': dict(state_startup),
        'trigger_functions_startup': {ch: False for ch in state_startup},
    }
    out.sent = []
    out.output_switch = lambda state, output_channel=0, **kw: (
        out.sent.append((state, output_channel)) or switch_returns)
    out.check_triggers = lambda *a, **kw: None
    return out


def test_startup_state_on_and_off_are_sent():
    out = _make_output({0: 1, 1: 0})
    out.apply_startup_state()

    assert ('on', 0) in out.sent
    assert ('off', 1) in out.sent
    assert out.output_states[0] is True
    assert out.output_states[1] is False


def test_do_nothing_sends_nothing():
    """-1 is the user's explicit 'Do Nothing'."""
    out = _make_output({0: -1})
    out.apply_startup_state()

    assert out.sent == []


def test_a_suppressed_channel_sends_nothing():
    """None is what suppress_state_transition() leaves behind; if the replay
    ever ran against a still-blanked option it must stay silent, not guess."""
    out = _make_output({0: None})
    out.apply_startup_state()

    assert out.sent == []


def test_a_failed_send_does_not_record_the_state():
    """A Startup State that never reached the device must not read as applied."""
    out = _make_output({0: 1}, switch_returns=(1, 'enqueue_failed'))
    out.apply_startup_state()

    assert out.sent, "the send was attempted"
    assert 0 not in out.output_states, \
        "a failed Startup State was recorded as if the device had switched"


# --- the controller side ------------------------------------------------------

def _make_controller():
    from aot.controllers.controller_output import OutputController

    ctrl = OutputController.__new__(OutputController)
    ctrl.logger = logging.getLogger('test_deferred_startup_ctrl')
    ctrl.output = {}
    ctrl.audited = []
    ctrl._audit_lifecycle = lambda *a: ctrl.audited.append(a)
    return ctrl


def test_deferring_blanks_the_option_and_returns_the_original():
    ctrl = _make_controller()
    out = _make_output({0: 1, 1: 0})
    out.startup_state_is_deferrable = lambda: True

    saved = ctrl._defer_startup_state('out-1', out)

    assert saved == {0: 1, 1: 0}
    assert out.options_channels['state_startup'] == {0: None, 1: None}, \
        "the driver would still send during try_initialize()"


def test_a_non_deferring_driver_is_left_alone():
    ctrl = _make_controller()
    out = _make_output({0: 1})
    out.startup_state_is_deferrable = lambda: False

    saved = ctrl._defer_startup_state('out-1', out)

    assert saved is None
    assert out.options_channels['state_startup'] == {0: 1}, \
        "a driver that never opted in had its Startup State blanked"


def test_the_replay_restores_and_sends():
    ctrl = _make_controller()
    out = _make_output({0: 1})
    out.startup_state_is_deferrable = lambda: True

    saved = ctrl._defer_startup_state('out-1', out)
    ctrl.output['out-1'] = out
    assert out.sent == [], "nothing may go out while booting"

    ctrl._apply_deferred_startup_states([('out-1', saved)])

    assert out.sent == [('on', 0)]
    assert out.options_channels['state_startup'] == {0: 1}, \
        "the option must be restored so later reloads behave normally"


def test_the_deferred_send_is_audited():
    """_audit_lifecycle() skips a channel whose value is None, and these were
    blanked for the whole boot -- so auditing at construction would leave the
    physical state change with no record anywhere, which is the gap that
    method exists to close."""
    ctrl = _make_controller()
    out = _make_output({0: 1})
    out.startup_state_is_deferrable = lambda: True

    saved = ctrl._defer_startup_state('out-1', out)
    ctrl.output['out-1'] = out
    ctrl._apply_deferred_startup_states([('out-1', saved)])

    assert ('out-1', 'state_startup', 'daemon_startup') in ctrl.audited


def test_the_replay_survives_an_output_removed_during_boot():
    ctrl = _make_controller()  # empty self.output
    ctrl._apply_deferred_startup_states([('gone', {0: 1})])  # must not raise


def test_one_failing_output_does_not_stop_the_rest():
    ctrl = _make_controller()
    bad = _make_output({0: 1})
    bad.apply_startup_state = lambda: (_ for _ in ()).throw(RuntimeError("boom"))
    good = _make_output({0: 1})
    ctrl.output = {'bad': bad, 'good': good}

    ctrl._apply_deferred_startup_states([('bad', {0: 1}), ('good', {0: 1})])

    assert good.sent == [('on', 0)]
