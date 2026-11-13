# coding=utf-8
"""VIGI RTSP FrameSource (OpenCV/FFmpeg). 설계 §3.3. 열기 전에 반드시 `rtsp_access.authorize` 를 거친다.

OpenCV 는 열기 실패의 이유(401 인지 네트워크인지)를 알려 주지 않는다. 그래서 검증된 자격 증명으로 연 스트림이
실패하면 `rtsp_access.diagnose` 가 이유를 한 번 본다 — 401 이면 래치하고 hub 는 멈춘다. 이 클래스에는 인증
재시도 루프가 없다.
"""
import logging
import os
import threading

from aot.camera_drivers import frames as F
from aot.camera_drivers.vigi import rtsp_access, streams
from aot.utils.timekit import utc_now

logger = logging.getLogger(__name__)

_ENV = 'OPENCV_FFMPEG_CAPTURE_OPTIONS'
_OPTS = 'rtsp_transport;tcp|fflags;nobuffer|flags;low_delay|probesize;500000|analyzeduration;1000000'
_lock = threading.Lock()


def open_capture(url, cv2):
    with _lock:
        prev = os.environ.get(_ENV)
        if prev is None:
            os.environ[_ENV] = _OPTS
        try:
            try:
                return cv2.VideoCapture(url, cv2.CAP_FFMPEG,
                                        [cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 10000,
                                         cv2.CAP_PROP_READ_TIMEOUT_MSEC, 8000])
            except (TypeError, cv2.error):
                return cv2.VideoCapture(url)
        finally:
            if prev is None:
                os.environ.pop(_ENV, None)


class RtspCv2Source(F.FrameSource):
    def __init__(self, guard, camera_id, credential, host, port, fp_key, profile='sub',
                 cv2_module=None, capture_opener=None):
        self.guard, self.camera_id, self.cred = guard, camera_id, credential
        self.host, self.port, self.fp_key, self.profile = host, port, fp_key, profile
        self._cv2 = cv2_module
        self._opener = capture_opener
        self._cap = None
        self._seq = 0

    def open(self):
        try:
            rtsp_access.authorize(self.guard, self.camera_id, self.cred, self.host, self.port,
                                  self.fp_key, self.profile)
        except rtsp_access.RtspDenied as exc:
            raise F.SourceError('auth:' + exc.reason, fatal=exc.fatal)
        cv2 = self._cv2 or __import__('cv2')
        url = streams.with_credentials(streams.rtsp_url(self.host, self.port, self.profile),
                                       self.cred.username, self.cred.password)
        cap = (self._opener or open_capture)(url, cv2)
        if not cap.isOpened():
            cap.release()
            try:
                rtsp_access.diagnose(self.guard, self.camera_id, self.cred, self.host, self.port,
                                     self.fp_key, self.profile)
            except rtsp_access.RtspDenied as exc:
                raise F.SourceError('auth:' + exc.reason, fatal=exc.fatal)
            raise F.SourceError('open_failed')
        self._cap = cap

    def read(self):
        ok, img = self._cap.read()
        if not ok or img is None:
            return None
        cv2 = self._cv2 or __import__('cv2')
        okj, buf = cv2.imencode('.jpg', img)
        if not okj:
            return None
        self._seq += 1
        return F.Frame(utc_now(), self._seq, buf.tobytes(), None)

    def close(self):
        if self._cap is not None:
            self._cap.release()
            self._cap = None
