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


def _log_tz():
    """로그 시각의 시계 — 시스템 시간대(Misc.timezone). 60초 캐시.
    DB 에 닿지 못하면(기동 초기) UTC."""
    import pytz

    now = time.time()
    if _TZ_CACHE['tz'] is not None and now <= _TZ_CACHE['expires']:
        return _TZ_CACHE['tz']

    if _TZ_CACHE['resolving']:
        # Re-entrancy guard. db_retrieve_table_daemon() logs its own
        # retry/failure lines via the 'aot' logger, which get formatted
        # through this same path before the outer call below
        # returns. Without this guard, a missing `misc` table (e.g. a
        # brand new install, before db.create_all() has run) turns every
        # one of those retry log lines into a fresh 5-retry DB lookup of
        # its own, which logs more lines, which trigger more lookups -
        # a self-sustaining loop that stalled app startup indefinitely
        # (2026-08-17 aot-gw-001: fresh install's aotflask/aot_daemon
        # spun on "no such table: misc" continuously and never finished
        # booting). Just fall back to UTC for this one line instead.
        return pytz.utc

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
    return _TZ_CACHE['tz']


class TzLogFormatter(logging.Formatter):
    """asctime 을 시스템 시계로 적고 **오프셋을 붙인다**:
    `2026-09-21 06:00:00,123+06:00`.

    오프셋이 없으면 시스템 시간대를 바꾼 전후의 로그가 구분되지 않고, 다른
    시간대에 있는 사람이 로그 시각을 자기 시각으로 읽는다. 로그 화면 파서
    (utils/log_reader._RE_AOT)는 이 꼴과 옛 꼴을 모두 읽는다.
    """
    def formatTime(self, record, datefmt=None):
        from datetime import datetime
        try:
            dt = datetime.fromtimestamp(record.created, _log_tz())
        except Exception:
            from datetime import timezone
            dt = datetime.fromtimestamp(record.created, timezone.utc)
        if datefmt:
            return dt.strftime(datefmt)
        off = dt.strftime('%z') or '+0000'
        return '%s,%03d%s:%s' % (dt.strftime('%Y-%m-%d %H:%M:%S'),
                                 record.msecs, off[:3], off[3:])


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

    formatter = TzLogFormatter(
        '%(asctime)s - %(levelname)s - %(name)s - %(message)s')

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
