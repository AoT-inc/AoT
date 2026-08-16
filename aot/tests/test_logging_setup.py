# coding=utf-8
"""Regression guard for the Flask/gunicorn logging gap.

Background: only aot_daemon.py ever attached handlers to the shared 'aot'
logger (inline, at its own module import time). Every logger.info()/
warning() call anywhere under the aot.* namespace -- including
aot.aot_flask.app -- relies on propagating up to that logger to go
anywhere, but gunicorn importing aot.start_flask_ui:app never imports
aot_daemon.py. Under gunicorn the 'aot' logger had no handler anywhere in
its ancestry, so Python fell back to logging.lastResort (WARNING+ to
stderr only) -- every INFO call from the Flask app process was silently
dropped, not merely hard to find (2026-08-16, found while chasing a log
line that never appeared).
"""
import logging
import os
import sys

import pytest

sys.path.insert(
    0,
    os.path.abspath(os.path.join(os.path.dirname(__file__), os.path.pardir, os.path.pardir))
)
os.environ.setdefault("ALEMBIC_RUNNING", "1")


@pytest.fixture
def clean_aot_logger():
    """The real 'aot' logger, stripped of whatever this test process (or an
    earlier test) already attached, and restored afterward."""
    logger = logging.getLogger('aot')
    saved_handlers = list(logger.handlers)
    saved_propagate = logger.propagate
    logger.handlers = []
    yield logger
    logger.handlers = saved_handlers
    logger.propagate = saved_propagate


def test_configure_aot_file_logging_attaches_handlers(clean_aot_logger, tmp_path, monkeypatch):
    import aot.config as config
    monkeypatch.setattr(config, 'DAEMON_LOG_FILE', str(tmp_path / 'aot.log'))

    from aot.utils.logging_setup import configure_aot_file_logging
    logger = configure_aot_file_logging()

    assert logger is clean_aot_logger
    assert len(logger.handlers) == 2
    assert logger.propagate is False, (
        "must not propagate -- a caller with its own root handler "
        "(aot_mcp_server.py's basicConfig) would otherwise get every "
        "aot.* line twice")


def test_configure_aot_file_logging_is_idempotent(clean_aot_logger, tmp_path, monkeypatch):
    """A re-entrant create_app() call (aot_mcp_server.py calls create_app()
    too) must not pile up duplicate handlers -- that would duplicate every
    log line once per call."""
    import aot.config as config
    monkeypatch.setattr(config, 'DAEMON_LOG_FILE', str(tmp_path / 'aot.log'))

    from aot.utils.logging_setup import configure_aot_file_logging
    configure_aot_file_logging()
    configure_aot_file_logging()
    configure_aot_file_logging()

    assert len(clean_aot_logger.handlers) == 2


def test_create_app_wires_up_file_logging():
    """The actual bug: create_app() (the gunicorn entry point) must call
    this, or the Flask process's loggers go straight back to invisible."""
    import inspect

    from aot.aot_flask.app import create_app
    source = inspect.getsource(create_app)
    assert "configure_aot_file_logging" in source


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
