# coding=utf-8
"""Shared 'aot' logger setup — a SharedRotatingFileHandler on DAEMON_LOG_FILE plus
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
import contextlib
import logging
import os
import sys
import time
from logging.handlers import RotatingFileHandler

try:  # 윈도우에는 없다 — 그때는 프로세스 사이 잠금 없이 돈다.
    import fcntl
except ImportError:  # pragma: no cover
    fcntl = None


class SharedRotatingFileHandler(RotatingFileHandler):
    """여러 프로세스가 **같은 파일 하나**를 함께 써도 회전이 깨지지 않는 핸들러.

    `aot.log` 에는 데몬, gunicorn 워커 N 개, MCP 서버가 동시에 쓴다(도커에서는
    세 컨테이너가 `../logs:/var/log/aot` 로 같은 디렉터리를 본다). 표준
    `RotatingFileHandler` 는 자기 프로세스만 파일을 쓴다고 가정하므로:

    1. 한 프로세스가 `aot.log` → `aot.log.1` 로 옮겨도 다른 프로세스는 옮겨진
       파일을 계속 붙잡고 쓴다. 그 파일은 이미 상한을 넘었으니 **그 프로세스는
       줄마다 다시 회전한다** — 1~5번 백업이 몇 KB 짜리 조각으로 갈려 나가고
       이력이 사라진다.
    2. 그렇게 밀려난 파일은 결국 `.5` 를 넘어 지워지고, 컨테이너마다 보는
       디렉터리 상태도 잠깐씩 어긋난다(도커 데스크톱 virtiofs: 한 컨테이너가 만든
       파일을 다른 컨테이너의 `mv` 가 "No such file" 로 못 찾는 것을 실측).
       맥미니 8084 데몬은 이 상태에서 `seek(0, 2)`(handlers.py shouldRollover
       197행)가 **줄마다** `FileNotFoundError` 를 내 `--- Logging error ---` 만
       stderr 로 쏟고 파일에는 한 줄도 못 썼다(2026-11-05~07: 47 시간 16,401 회).
       표준 핸들러는 스트림을 다시 열 줄 모르므로 재시작 전까지 낫지 않는다.
    3. 두 프로세스가 동시에 회전하면 `exists()` 와 `rename()` 사이에 상대가
       파일을 옮겨 `FileNotFoundError` 가 난다(로컬 재현).

    고친 방식:
    - 쓰기 전에 경로의 (st_dev, st_ino) 가 지금 열린 파일과 같은지 본다
      (`WatchedFileHandler` 와 같은 검사). 다르면 남이 회전한 것이므로 다시 연다.
      바깥 logrotate(`install/logrotate_aot`)가 옮긴 경우도 같은 길로 따라간다.
    - 회전은 `<파일>.lock` 에 `flock` 을 잡고 한다. 잠금을 얻은 뒤 경로가 이미
      바뀌었으면(기다리는 동안 남이 회전) 다시 열기만 하고 회전하지 않는다.
    - 회전이 어떤 이유로든 실패해도 쓸 수 있는 스트림을 남긴다.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._lock_path = self.baseFilename + '.lock'
        self._dev, self._ino = -1, -1
        self._remember_stream()

    def _remember_stream(self):
        self._dev, self._ino = -1, -1
        if self.stream is None:
            return
        try:
            st = os.fstat(self.stream.fileno())
        except (OSError, ValueError):
            return
        self._dev, self._ino = st.st_dev, st.st_ino

    def _path_identity(self):
        try:
            st = os.stat(self.baseFilename)
        except OSError:
            return None
        return st.st_dev, st.st_ino

    def _reopen(self):
        if self.stream is not None:
            try:
                self.stream.flush()
                self.stream.close()
            except (OSError, ValueError):
                pass
        self.stream = None
        self.stream = self._open()
        self._remember_stream()

    @contextlib.contextmanager
    def _interprocess_lock(self):
        if fcntl is None:
            yield
            return
        try:
            fd = os.open(self._lock_path, os.O_RDWR | os.O_CREAT, 0o644)
        except OSError:
            # 잠금 파일을 못 만들면(읽기 전용 디렉터리 등) 잠금 없이라도 돈다.
            # 아래 경로 재확인이 경합 대부분을 막는다.
            yield
            return
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        finally:
            try:
                fcntl.flock(fd, fcntl.LOCK_UN)
            finally:
                os.close(fd)

    def shouldRollover(self, record):
        if self.stream is None or self._path_identity() != (self._dev, self._ino):
            self._reopen()
        try:
            return super().shouldRollover(record)
        except OSError:
            # 지금 스트림이 망가졌다(맥미니 데몬: seek(0, 2) 가 줄마다
            # FileNotFoundError). 버리고 다시 연다 — 표준 핸들러는 여기서
            # 영영 못 빠져나왔다.
            self._reopen()
            return super().shouldRollover(record)

    def doRollover(self):
        with self._interprocess_lock():
            if self._path_identity() != (self._dev, self._ino):
                # 잠금을 기다리는 사이 다른 프로세스가 이미 회전했다.
                self._reopen()
                return
            try:
                super().doRollover()
            except OSError:
                # 외부 logrotate 처럼 잠금 밖에서 옮기는 쪽과 겹친 경우.
                # 회전은 다음 기회로 넘기고 쓰기는 계속한다.
                pass
            if self.stream is None:
                self.stream = self._open()
            self._remember_stream()


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
    # 같은 파일을 데몬·웹 워커·MCP 가 함께 쓰므로 Shared 쪽이어야 한다.
    file_handler = SharedRotatingFileHandler(
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
