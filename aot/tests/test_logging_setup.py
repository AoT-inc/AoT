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


# ── 여러 프로세스가 같은 aot.log 를 회전 ─────────────────────────────────────
# 데몬·gunicorn 워커·MCP 가 같은 파일을 쓴다. 한 프로세스 안의 핸들러 두 개는
# 각자 자기 fd 와 회전 판단을 가지므로 두 프로세스를 그대로 흉내 낸다.

def _record(msg='x' * 60):
    return logging.LogRecord('aot.t', logging.WARNING, __file__, 1, msg, None, None)


def _shared(path, max_bytes=2000):
    from aot.utils.logging_setup import SharedRotatingFileHandler
    h = SharedRotatingFileHandler(str(path), maxBytes=max_bytes, backupCount=3,
                                  encoding='utf-8')
    h.setFormatter(logging.Formatter('%(message)s'))
    errors = []
    h.handleError = lambda record: errors.append(sys.exc_info()[1])
    return h, errors


def test_follows_rotation_done_by_another_process(tmp_path):
    log = tmp_path / 'aot.log'
    a, a_err = _shared(log)
    b, b_err = _shared(log)
    try:
        while not (tmp_path / 'aot.log.1').exists():
            a.emit(_record())
        size_1 = (tmp_path / 'aot.log.1').stat().st_size

        b.emit(_record('from-b'))

        assert 'from-b' in log.read_text(), "b kept writing into the moved file"
        assert 'from-b' not in (tmp_path / 'aot.log.1').read_text()
        assert (tmp_path / 'aot.log.1').stat().st_size == size_1
        assert not (tmp_path / 'aot.log.2').exists(), (
            "b rotated again on top of a's rotation")
        assert a_err == [] and b_err == []
    finally:
        a.close()
        b.close()


def test_stale_process_does_not_rotate_storm(tmp_path):
    """The old failure: a handler still holding the moved, over-limit file
    saw "too big" on every line and rotated on every line, grinding the
    backups into fragments a few lines long."""
    log = tmp_path / 'aot.log'
    a, _ = _shared(log)
    b, b_err = _shared(log)
    try:
        while not (tmp_path / 'aot.log.1').exists():
            a.emit(_record())
        size_1 = (tmp_path / 'aot.log.1').stat().st_size
        for _ in range(5):
            b.emit(_record())
        assert not (tmp_path / 'aot.log.2').exists()
        assert (tmp_path / 'aot.log.1').stat().st_size == size_1
        assert b_err == []
    finally:
        a.close()
        b.close()


def test_rollover_skipped_when_another_process_got_there_first(tmp_path):
    """Two processes decide to rotate at once; the one that gets the lock
    second must just reopen, not rotate the fresh file away."""
    log = tmp_path / 'aot.log'
    a, _ = _shared(log)
    b, _ = _shared(log)
    try:
        a.emit(_record('first'))
        a.doRollover()
        b.doRollover()  # b still holds the old identity
        assert (tmp_path / 'aot.log.1').exists()
        assert not (tmp_path / 'aot.log.2').exists()
        assert 'first' in (tmp_path / 'aot.log.1').read_text()
    finally:
        a.close()
        b.close()


def test_follows_external_logrotate_and_deleted_file(tmp_path):
    """install/logrotate_aot moves the file under everyone; and the file a
    handler holds can be deleted outright (on Docker Desktop's virtiofs a
    seek on that fd then raised FileNotFoundError on every line)."""
    log = tmp_path / 'aot.log'
    h, err = _shared(log)
    try:
        h.emit(_record('before'))
        os.rename(log, tmp_path / 'aot.log.1')
        os.remove(tmp_path / 'aot.log.1')
        h.emit(_record('after'))
        assert log.read_text().strip() == 'after'
        assert err == []
    finally:
        h.close()


def test_failed_rollover_leaves_handler_usable(tmp_path, monkeypatch):
    log = tmp_path / 'aot.log'
    h, err = _shared(log)
    try:
        h.emit(_record('one'))

        def boom(*a, **k):
            raise FileNotFoundError(2, 'No such file or directory')
        monkeypatch.setattr(h, 'rotate', boom)
        h.doRollover()
        monkeypatch.undo()

        h.emit(_record('two'))
        assert 'two' in log.read_text()
        assert err == []
    finally:
        h.close()


def test_recovers_from_a_stream_that_keeps_failing(tmp_path):
    """맥미니 8084 데몬: shouldRollover 의 seek(0, 2) 가 줄마다
    FileNotFoundError 를 내 47 시간 동안 한 줄도 못 썼다. 경로가 그대로여도
    망가진 스트림은 버리고 다시 열어야 한다."""
    log = tmp_path / 'aot.log'
    h, err = _shared(log)

    class Broken:
        def __init__(self, inner):
            self._inner = inner

        def seek(self, *a):
            raise FileNotFoundError(2, 'No such file or directory')

        def __getattr__(self, name):
            return getattr(self._inner, name)

    try:
        h.emit(_record('before'))
        h.stream = Broken(h.stream)
        h.emit(_record('after'))
        h.emit(_record('again'))
        text = log.read_text()
        assert 'after' in text and 'again' in text
        assert err == []
    finally:
        h.close()


_STRESS = r"""
import logging, sys
sys.path.insert(0, sys.argv[1])
from aot.utils.logging_setup import SharedRotatingFileHandler
h = SharedRotatingFileHandler(sys.argv[2], maxBytes=8000, backupCount=4)
lg = logging.getLogger('p'); lg.addHandler(h); lg.propagate = False
for n in range(1500):
    lg.warning('%s %05d %s', sys.argv[3], n, 'x' * 40)
"""


def test_real_processes_share_one_file(tmp_path):
    import subprocess
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir, os.pardir))
    log = tmp_path / 'aot.log'
    procs = [subprocess.Popen([sys.executable, '-c', _STRESS, root, str(log), 'p%d' % i],
                              stderr=subprocess.PIPE, text=True)
             for i in range(4)]
    stderr = [p.communicate(timeout=120)[1] for p in procs]
    assert all(p.returncode == 0 for p in procs), stderr
    assert not any('Logging error' in e for e in stderr), stderr
    # Every backup is a full-size file, not a fragment from a rotation storm.
    for i in range(1, 5):
        assert (tmp_path / ('aot.log.%d' % i)).stat().st_size >= 8000 * 0.9


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
