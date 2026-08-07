# coding=utf-8
"""A control command that never reached the device must never read as success.

These lock in the 2026-08-07 audit findings. All three defects shared one
shape: the failure existed, but every layer above it was structurally unable
to see it, so the UI reported success while nothing had been commanded.

1. on_off_chirpstack called self._log_error() on the pacing-drop path, and
   that method did not exist anywhere in the tree. The drop path therefore
   raised AttributeError *before* begin_command(), so no pending window, no
   fault and no offline mark were recorded -- and the error log meant to
   announce the drop was itself the line that crashed.
2. output_switch() returned a plain string. AbstractOutput._switch_failed()
   only treats a (code, msg) tuple as failure, so every chirpstack failure --
   including the AttributeError caught by its own except -- was read as a
   completed command.
3. DaemonControl control calls swallow Pyro timeouts and return (code, msg)
   rather than raising, so callers that only used try/except reported
   ok. The e-stop route answered {'ok': True, 'failed': 0} with every
   channel timed out.

Nothing here touches the database, a daemon or a radio.
"""
import logging

import pytest


# --- 1. the logging helper the drop path depends on ---------------------------

def test_chirpstack_defines_every_log_helper_it_calls():
    """The pacing-drop path calls self._log_error; it must actually exist.

    Guards the exact regression: a call site shipped for a week against a
    method that was never defined, on a class with no __getattr__ fallback.
    """
    from aot.outputs.on_off_chirpstack import OutputModule

    for name in ('_log_info', '_log_warning', '_log_error'):
        assert callable(getattr(OutputModule, name, None)), \
            f"OutputModule.{name}() is called but not defined"


def test_log_error_is_not_gated_by_debug_logging(caplog):
    """A command that never went out must be visible with debug logging off.

    _log_info/_log_warning are deliberately gated so per-uplink chatter does
    not flood the log. Gating _log_error too is how a dropped downlink becomes
    invisible, which is the failure mode this whole file exists for.
    """
    from aot.outputs.on_off_chirpstack import OutputModule

    out = OutputModule.__new__(OutputModule)
    out.logger = logging.getLogger('test_chirpstack_log_error')
    out.debug_logging = False  # the production default

    with caplog.at_level(logging.ERROR, logger='test_chirpstack_log_error'):
        out._log_error("downlink dropped")

    assert "downlink dropped" in caplog.text


def test_log_warning_stays_gated(caplog):
    """The counterpart: routine chatter must still be suppressed."""
    from aot.outputs.on_off_chirpstack import OutputModule

    out = OutputModule.__new__(OutputModule)
    out.logger = logging.getLogger('test_chirpstack_log_warning')
    out.debug_logging = False

    with caplog.at_level(logging.WARNING, logger='test_chirpstack_log_warning'):
        out._log_warning("routine chatter")

    assert "routine chatter" not in caplog.text


# --- 2. output_switch() -> _switch_failed() contract --------------------------

def _make_output(enqueue_result, enqueue_raises=None):
    """A chirpstack output with only what output_switch() touches."""
    from aot.outputs.on_off_chirpstack import OutputModule

    out = OutputModule.__new__(OutputModule)
    out.logger = logging.getLogger('test_chirpstack_switch')
    out.output_states = {}
    out.debug_logging = False
    out.began = []

    def _enqueue(state):
        if enqueue_raises is not None:
            raise enqueue_raises
        return enqueue_result

    out._enqueue = _enqueue
    out.begin_command = lambda *a, **kw: out.began.append((a, kw))
    return out


def test_a_dispatched_command_reads_as_success():
    from aot.outputs.base_output import AbstractOutput

    out = _make_output(True)
    failed, _ = AbstractOutput._switch_failed(out.output_switch('off'))

    assert not failed


def test_a_refused_enqueue_reads_as_failure():
    """The regression: this used to return 'enqueue_failed' as a bare string,
    which _switch_failed() reads as success no matter what it says."""
    from aot.outputs.base_output import AbstractOutput

    out = _make_output(False)
    ret = out.output_switch('off')
    failed, msg = AbstractOutput._switch_failed(ret)

    assert failed, f"a refused enqueue was reported as success: {ret!r}"
    assert msg


def test_a_raising_transport_reads_as_failure():
    """The AttributeError path. output_switch() catches every exception, so
    without a failure-shaped return the crash is indistinguishable from a
    completed command -- and begin_command() never ran either."""
    from aot.outputs.base_output import AbstractOutput

    out = _make_output(None, enqueue_raises=AttributeError("_log_error"))
    ret = out.output_switch('off')
    failed, msg = AbstractOutput._switch_failed(ret)

    assert failed, f"a crashing dispatch was reported as success: {ret!r}"
    assert out.began == [], "begin_command must not run when dispatch crashed"


def test_no_pending_window_is_armed_for_a_refused_enqueue():
    """A command that never went out must not leave an optimistic 'on'."""
    out = _make_output(False)
    out.output_switch('on')

    assert out.began, "begin_command is still called so it can decline"
    _args, kwargs = out.began[-1]
    assert kwargs.get('dispatched_ok') is False


# --- 3. DaemonControl (code, msg) contract ------------------------------------

@pytest.mark.parametrize('ret', [
    (1, 'Output OFF timed out: receiving: timeout'),
    (1, 'Output OFF communication error'),
    (2, 'anything non-zero'),
])
def test_daemon_failure_tuples_are_detected(ret):
    from aot.aot_client import daemon_call_failed

    failed, msg = daemon_call_failed(ret)
    assert failed
    assert msg


@pytest.mark.parametrize('ret', [
    (0, 'success'),
    None,
    'legacy string',
    ('not', 'ints'),
])
def test_non_failures_are_not_flagged(ret):
    """Unknown/legacy shapes stay success so this is safe at every call site."""
    from aot.aot_client import daemon_call_failed

    failed, _ = daemon_call_failed(ret)
    assert not failed


# --- 4. the call sites that must consult it -----------------------------------

def test_control_routes_check_the_daemon_return_value():
    """Every control route must read the (code, msg) code.

    A try/except alone cannot see a timeout here, because the daemon client
    returns the failure instead of raising. This is a source-level guard: the
    routes need a Flask app and a live daemon to exercise directly, and the
    defect is precisely that they looked fine while doing nothing.
    """
    import inspect

    from aot.aot_flask import routes_geo, routes_geo_iec

    for module, funcs in (
            (routes_geo_iec, ('api_facility_estop', 'api_facility_control')),
            (routes_geo, ('api_geo_output_state',)),
    ):
        for func_name in funcs:
            func = getattr(module, func_name)
            src = inspect.getsource(func)
            assert 'daemon_call_failed' in src, (
                f"{module.__name__}.{func_name}() issues control commands "
                f"without checking the daemon's (code, msg) return value")
