# coding=utf-8
"""Shared 'aot' logger setup — a RotatingFileHandler on DAEMON_LOG_FILE plus
a StreamHandler on stdout (for `docker logs`).

Only aot_daemon.py ever set this up, inline, at module import time. Every
`logger = logging.getLogger('aot.<something>')` call elsewhere in the
codebase (aot.aot_flask.app, aot.ai.services.*, ...) relies on propagating
up to the 'aot' logger to actually go anywhere -- but that only happens in
the daemon *process*. gunicorn importing aot.start_flask_ui:app never
imports aot_daemon.py, so under gunicorn the 'aot' logger has no handler
anywhere in its ancestry. Python's logging then falls back to its "handler
of last resort" (logging.lastResort), which only prints WARNING and above
to stderr -- every logger.info() call in the Flask app process was silently
dropped, not merely hard to find. Found 2026-08-16 chasing a widget-
regeneration confirmation log that never appeared anywhere.

aot_mcp_server.py is deliberately NOT wired to this: it already has its own
logging.basicConfig() to a separate mcp.log, and touching that is out of
scope for what this fixes.
"""
import logging
import sys
import time
from logging.handlers import RotatingFileHandler

_TZ_CACHE = {'tz': None, 'expires': 0.0, 'resolving': False}


def _user_tz_converter(secs):
    """Render log asctime in the user-configured timezone (Misc.timezone).
    Falls back to UTC when the DB is not yet reachable (early startup) or
    when called from a process with no DB access at all."""
    try:
        import pytz
        from datetime import datetime as _dt

        now = time.time()
        if _TZ_CACHE['tz'] is not None and now <= _TZ_CACHE['expires']:
            return _dt.fromtimestamp(secs, _TZ_CACHE['tz']).timetuple()

        if _TZ_CACHE['resolving']:
            # Re-entrancy guard. db_retrieve_table_daemon() logs its own
            # retry/failure lines via the 'aot' logger, which get formatted
            # through this same converter before the outer call below
            # returns. Without this guard, a missing `misc` table (e.g. a
            # brand new install, before db.create_all() has run) turns every
            # one of those retry log lines into a fresh 5-retry DB lookup of
            # its own, which logs more lines, which trigger more lookups -
            # a self-sustaining loop that stalled app startup indefinitely
            # (2026-08-17 aot-gw-001: fresh install's aotflask/aot_daemon
            # spun on "no such table: misc" continuously and never finished
            # booting). Just fall back to gmtime for this one line instead.
            return time.gmtime(secs)

        _TZ_CACHE['resolving'] = True
        try:
            from aot.databases.models import Misc
            from aot.utils.database import db_retrieve_table_daemon

            misc = db_retrieve_table_daemon(Misc, entry='first')
            tz_name = misc.timezone if misc and getattr(misc, 'timezone', None) else 'UTC'
            _TZ_CACHE['tz'] = pytz.timezone(tz_name)
            _TZ_CACHE['expires'] = now + 60
        finally:
            _TZ_CACHE['resolving'] = False
        return _dt.fromtimestamp(secs, _TZ_CACHE['tz']).timetuple()
    except Exception:
        return time.gmtime(secs)


def configure_aot_file_logging(level=logging.INFO):
    """Attach the daemon's file+stream handlers to the shared 'aot' logger.

    Idempotent: a second call in the same process (e.g. a re-entrant
    create_app()) is a no-op, so every caller can call this unconditionally
    on its own startup path without coordinating with the others.
    """
    logger = logging.getLogger('aot')
    if logger.handlers:
        return logger

    from aot.config import DAEMON_LOG_FILE

    formatter = logging.Formatter(
        '%(asctime)s - %(levelname)s - %(name)s - %(message)s')
    formatter.converter = _user_tz_converter

    # 50 MB x 5 파일 = 최대 250 MB 유지. aot_daemon.py 와 동일한 정책.
    file_handler = RotatingFileHandler(
        DAEMON_LOG_FILE, maxBytes=50 * 1024 * 1024, backupCount=5,
        encoding='utf-8')
    file_handler.setLevel(level)
    file_handler.setFormatter(formatter)

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setLevel(level)
    stream_handler.setFormatter(formatter)

    logger.setLevel(level)
    logger.addHandler(file_handler)
    logger.addHandler(stream_handler)
    logger.propagate = False
    return logger
