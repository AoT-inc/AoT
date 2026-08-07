# coding=utf-8
"""A daemon that is down must cost the web UI one RPC per TTL, not one per request.

From the 2026-08-07 audit. Three TTL caches all wrote their entry only on the
success path, so a daemon outage -- the one situation the cache exists for --
disabled every one of them:

  * DaemonControl.output_states_all() / input_status_all(): the cache write sat
    inside the try, so a timeout cached nothing and the next poll blocked for
    the full RPC timeout again.
  * routes_static.inject_variables(): the timestamp was stamped AFTER the RPC,
    so an exception skipped it and 'ts' stayed at its initial 0.0 forever.
    That function is an app_context_processor -- it runs on EVERY page render.
    With gunicorn workers=1 the thread pool saturates and pages that never
    touch the daemon stop loading too. This was the whole-site paralysis.

The invariant under test: after one failed call, the next call inside the TTL
must not reach the daemon again.
"""
import time

import pytest


@pytest.fixture
def clean_caches():
    """The caches are class-level; start and finish each test from empty."""
    from aot.aot_client import DaemonControl

    DaemonControl._states_all_cache = (None, 0.0)
    DaemonControl._input_status_all_cache = (None, 0.0)
    yield DaemonControl
    DaemonControl._states_all_cache = (None, 0.0)
    DaemonControl._input_status_all_cache = (None, 0.0)


def _client_that_always_fails(DaemonControl, calls):
    """A DaemonControl whose every RPC raises, counting attempts."""
    import Pyro5.errors

    ctrl = DaemonControl.__new__(DaemonControl)
    ctrl.pyro_timeout = 8
    ctrl.uri = 'PYRO:unreachable@127.0.0.1:1'

    class _Proxy:
        def output_states_all(self):
            calls.append('output')
            raise Pyro5.errors.TimeoutError("receiving: timeout")

        def input_status_all(self):
            calls.append('input')
            raise Pyro5.errors.TimeoutError("receiving: timeout")

    ctrl.proxy = lambda *a, **kw: _Proxy()
    return ctrl


def test_output_states_all_caches_the_failure(clean_caches):
    """The regression: an unreachable daemon was re-dialled on every request."""
    calls = []
    ctrl = _client_that_always_fails(clean_caches, calls)

    assert ctrl.output_states_all() == {}
    assert ctrl.output_states_all() == {}
    assert ctrl.output_states_all() == {}

    assert len(calls) == 1, (
        f"a failing daemon was contacted {len(calls)} times inside one TTL; "
        f"the failure is not being cached")


def test_input_status_all_caches_the_failure(clean_caches):
    calls = []
    ctrl = _client_that_always_fails(clean_caches, calls)

    assert ctrl.input_status_all() == {}
    assert ctrl.input_status_all() == {}

    assert len(calls) == 1


def test_the_cached_failure_expires(clean_caches):
    """Caching a failure must not make the outage permanent."""
    calls = []
    ctrl = _client_that_always_fails(clean_caches, calls)

    ctrl.output_states_all()
    # Expire the entry the way the passage of time would.
    cached, _expires = clean_caches._states_all_cache
    clean_caches._states_all_cache = (cached, time.monotonic() - 1.0)
    ctrl.output_states_all()

    assert len(calls) == 2


def test_a_recovered_daemon_is_served_fresh(clean_caches):
    """After the TTL, a working daemon's real answer replaces the cached {}."""
    import Pyro5.errors

    DaemonControl = clean_caches
    state = {'up': False}

    ctrl = DaemonControl.__new__(DaemonControl)
    ctrl.pyro_timeout = 8
    ctrl.uri = 'PYRO:flaky@127.0.0.1:1'

    class _Proxy:
        def output_states_all(self):
            if not state['up']:
                raise Pyro5.errors.TimeoutError("receiving: timeout")
            return {'out-1': 'on'}

    ctrl.proxy = lambda *a, **kw: _Proxy()

    assert ctrl.output_states_all() == {}

    state['up'] = True
    cached, _ = DaemonControl._states_all_cache
    DaemonControl._states_all_cache = (cached, time.monotonic() - 1.0)

    assert ctrl.output_states_all() == {'out-1': 'on'}


# --- the page-render path -----------------------------------------------------

def test_page_render_stamps_the_cache_before_calling_the_daemon():
    """inject_variables() must advance 'ts' before the RPC, not after.

    Structural check: this function needs a Flask app, a database and a form
    to call directly, and the defect is an ordering one -- the code read fine
    and still re-dialled a dead daemon on every page render. Asserting the
    order is what actually pins the fix.
    """
    import inspect

    from aot.aot_flask import routes_static

    src = inspect.getsource(routes_static.inject_variables)
    stamp_at = src.find("_daemon_status_cache['ts'] = now")
    rpc_at = src.find("daemon_status()")

    assert stamp_at != -1, "the TTL timestamp write disappeared"
    assert rpc_at != -1, "the daemon_status() call disappeared"
    assert stamp_at < rpc_at, (
        "inject_variables() stamps the TTL timestamp after the daemon RPC; a "
        "failing RPC then skips the stamp and every page render blocks again")


def test_page_render_uses_a_short_daemon_timeout():
    """Rendering a page must not wait as long as a control command may."""
    import inspect

    from aot.aot_flask import routes_static

    src = inspect.getsource(routes_static.inject_variables)
    assert 'pyro_timeout=' in src, (
        "inject_variables() uses the default 8 s RPC budget; a page render "
        "should give up on the daemon far sooner than a control command does")
