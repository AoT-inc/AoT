# coding=utf-8
"""FrameSource / FrameHub / LatestFrameFile (설계 §3.3, §7).

- FrameSource: open/read/close. 열 수 없으면 `SourceError`(fatal=True 면 재시도하지 않는다 — 인증 래치).
- FrameHub: 카메라당 **프로세스당** 하나. 소스 하나를 읽어 구독자 여럿에게 최신 프레임만 나눈다.
  구독자가 한동안 없으면 스스로 멈춘다. CV 는 gunicorn 워커 안이 아니라 데몬/작업 프로세스가 자기 허브를 열어 구독한다.
- LatestFrameFile: 허브 구독자. 1초에 한 번 이하로 임시 폴더에 JPEG 를 원자적으로 쓴다. 다른 워커·데몬의 스냅샷이
  새 연결·새 인증 없이 읽는다.
"""
import logging
import os
import tempfile
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class Frame:
    ts_utc: datetime
    seq: int
    jpeg: Optional[bytes] = None
    image: object = None  # ndarray (CV 용)


class SourceError(Exception):
    """소스를 열거나 읽을 수 없다. fatal 이면 같은 자격 증명으로 다시 시도하지 않는다."""

    def __init__(self, reason, fatal=False):
        super().__init__(reason)
        self.reason = reason
        self.fatal = fatal


class FrameSource:
    def open(self):
        raise NotImplementedError

    def read(self) -> Optional[Frame]:
        raise NotImplementedError

    def close(self):
        raise NotImplementedError


class FrameHub:
    """소스 하나 → 구독자 여럿. 시계·잠자기는 주입할 수 있다(시험)."""

    def __init__(self, source_factory, name='', idle_stop_s=30.0, retry_delays=(2, 5, 10, 30),
                 sleep=time.sleep, monotonic=time.monotonic):
        self._factory = source_factory
        self.name = name
        self.idle_stop_s = idle_stop_s
        self._retry = retry_delays
        self._sleep = sleep
        self._mono = monotonic
        self._lock = threading.Lock()
        self._subs = {}
        self._next = 1
        self._latest = None
        self._thread = None
        self._stop = threading.Event()
        self.dead_reason = None   # 치명 오류로 멈췄으면 이유(재시작은 사용자 조작 뒤)
        self._last_sub_seen = self._mono()

    # -- 구독 -------------------------------------------------------------
    def subscribe(self, callback, rate_hz=None, want='jpeg'):
        with self._lock:
            token = self._next
            self._next += 1
            self._subs[token] = [callback, rate_hz, 0.0]
            self._last_sub_seen = self._mono()
            self._ensure_started()
        return token

    def unsubscribe(self, token):
        with self._lock:
            self._subs.pop(token, None)
            self._last_sub_seen = self._mono()

    def latest(self) -> Optional[Frame]:
        return self._latest

    @property
    def running(self):
        return self._thread is not None and self._thread.is_alive()

    def stop(self):
        self._stop.set()

    def _ensure_started(self):
        if self.running:
            return
        if self.dead_reason:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name='framehub-' + self.name, daemon=True)
        self._thread.start()

    # -- 읽기 루프 ----------------------------------------------------------
    def _idle(self):
        with self._lock:
            return not self._subs and (self._mono() - self._last_sub_seen) >= self.idle_stop_s

    def _publish(self, frame):
        self._latest = frame
        now = self._mono()
        with self._lock:
            subs = list(self._subs.values())
        for sub in subs:
            cb, rate, last = sub
            if rate and now - last < 1.0 / rate:
                continue
            sub[2] = now
            try:
                cb(frame)
            except Exception:
                logger.exception('framehub subscriber failed')

    def _run(self):
        attempt = 0
        while not self._stop.is_set() and not self._idle():
            src = self._factory()
            try:
                src.open()
            except SourceError as exc:
                if exc.fatal:
                    self.dead_reason = exc.reason
                    return
                delay = self._retry[min(attempt, len(self._retry) - 1)]
                attempt += 1
                logger.warning('framehub %s open failed (%s); retry in %ss', self.name,
                               exc.reason, delay)
                self._sleep(delay)
                continue
            attempt = 0
            try:
                while not self._stop.is_set() and not self._idle():
                    frame = src.read()
                    if frame is None:
                        break
                    self._publish(frame)
            except SourceError as exc:
                if exc.fatal:
                    self.dead_reason = exc.reason
                    return
            finally:
                src.close()
            self._sleep(1)


_hubs = {}
_hubs_lock = threading.Lock()


def get_hub(camera_id, source_factory, **kw):
    """프로세스 안의 카메라별 허브. 치명 오류로 죽은 허브는 새로 만든다(사용자가 래치를 푼 뒤)."""
    with _hubs_lock:
        hub = _hubs.get(camera_id)
        if hub is None or hub.dead_reason:
            hub = _hubs[camera_id] = FrameHub(source_factory, name=camera_id[:8], **kw)
        return hub


class LatestFrameFile:
    """허브 구독자. `hub.subscribe(LatestFrameFile(uid))`."""

    def __init__(self, camera_id, directory=None, min_interval=1.0, monotonic=time.monotonic):
        self.path = self.path_for(camera_id, directory)
        self.min_interval = min_interval
        self._mono = monotonic
        self._last = -1e9

    @staticmethod
    def path_for(camera_id, directory=None):
        d = directory or os.path.join(tempfile.gettempdir(), 'aot-cam')
        return os.path.join(d, '%s.jpg' % camera_id)

    def __call__(self, frame):
        if not frame.jpeg:
            return
        now = self._mono()
        if now - self._last < self.min_interval:
            return
        self._last = now
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        tmp = self.path + '.%d.tmp' % os.getpid()
        with open(tmp, 'wb') as f:
            f.write(frame.jpeg)
        os.replace(tmp, self.path)          # 원자적

    @classmethod
    def read_fresh(cls, camera_id, max_age=3.0, directory=None, now=time.time):
        path = cls.path_for(camera_id, directory)
        try:
            if now() - os.path.getmtime(path) > max_age:
                return None
            with open(path, 'rb') as f:
                return f.read() or None
        except OSError:
            return None
