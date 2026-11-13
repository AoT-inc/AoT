# -*- coding: utf-8 -*-
"""RTSP 스트림을 빠르게 여는 도우미 (OpenCV/FFmpeg).

OpenCV 의 FFmpeg 백엔드는 열 때마다 환경변수 OPENCV_FFMPEG_CAPTURE_OPTIONS 를
읽는다(OpenCV 4.9 에서 import 이후·재설정 후에도 열 때마다 반영됨을 확인).
그래서 cv2 import 순서와 무관하지만 환경변수는 프로세스 전역이므로, 이 모듈은
열리는 동안에만 값을 넣고 바로 되돌린다 — USB 웹캠·다른 카메라 방식의 열기에
영향을 주지 않는다. 운영자가 이미 이 환경변수를 지정했다면 그 값을 존중한다.
"""
import logging
import os
import threading

logger = logging.getLogger(__name__)

ENV_NAME = 'OPENCV_FFMPEG_CAPTURE_OPTIONS'
# 이 앱에서 값을 바꾸고 싶으면 AOT_CAMERA_FFMPEG_OPTIONS 로 덮어쓴다(빈 문자열 = 끔).
OPTIONS_ENV = 'AOT_CAMERA_FFMPEG_OPTIONS'
# 전송은 TCP(Wi-Fi 에서 UDP 패킷 손실로 인한 깨진 프레임·재시도 방지), 스트림 분석
# 시간을 기본 5초에서 1초로, 입력 버퍼링 끔. 실측으로 조정할 값이다(보고서 참조).
DEFAULT_OPTIONS = ('rtsp_transport;tcp|fflags;nobuffer|flags;low_delay'
                   '|probesize;500000|analyzeduration;1000000')
OPEN_TIMEOUT_MS = 10000   # 열기에서 멈추지 않게
READ_TIMEOUT_MS = 8000    # 읽기에서 멈추지 않게(끊기면 재접속 경로로)

_lock = threading.Lock()


def capture_options():
    """적용할 FFmpeg 옵션 문자열. 빈 문자열이면 적용하지 않는다."""
    value = os.environ.get(OPTIONS_ENV)
    return DEFAULT_OPTIONS if value is None else value


def is_rtsp(url):
    return isinstance(url, str) and url.lower().startswith('rtsp')


def open_capture(url, cv2_module=None):
    """url 에 대한 cv2.VideoCapture 를 연다. RTSP 에만 빠른 열기 옵션을 쓴다."""
    cv2 = cv2_module
    if cv2 is None:
        import cv2
    if not is_rtsp(url):
        return cv2.VideoCapture(url)

    options = capture_options()
    params = [cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, OPEN_TIMEOUT_MS,
              cv2.CAP_PROP_READ_TIMEOUT_MSEC, READ_TIMEOUT_MS]
    with _lock:
        previous = os.environ.get(ENV_NAME)
        apply_env = bool(options) and previous is None
        if apply_env:
            os.environ[ENV_NAME] = options
        try:
            try:
                return cv2.VideoCapture(url, cv2.CAP_FFMPEG, params)
            except (TypeError, cv2.error):
                # 타임아웃 인자를 모르는 오래된 OpenCV
                return cv2.VideoCapture(url)
        finally:
            if apply_env:
                os.environ.pop(ENV_NAME, None)
