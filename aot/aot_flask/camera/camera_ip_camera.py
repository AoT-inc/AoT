# -*- coding: utf-8 -*-
"""MJPEG relay for network (RTSP/ONVIF/HTTP) IP cameras, e.g. VIGI/TP-Link cameras."""
import logging
import os
import time

import cv2

from aot.aot_flask.camera.base_camera import BaseCamera, load_camera_settings
from aot.aot_flask.camera.net_auth import (
    RetryBackoff, build_stream_url, credential_fingerprint, http_auth_rejected,
    is_auth_latched, latch_auth_failure, redact_url)
from aot.aot_flask.camera.rtsp_open import open_capture

# 마지막 시청자가 떠난 뒤 연결을 유지하는 시간(초). 다시 열 때 RTSP 재접속(수 초)을
# 기다리지 않게 한다. 연결이 살아 있는 동안에만 적용된다. 0 이면 기본 유예(10초).
KEEP_ALIVE_SECONDS = int(os.environ.get('AOT_CAMERA_KEEPALIVE_SEC', '60'))

logger = logging.getLogger(__name__)

# 하위 호환: 예전 이름. 새 코드는 net_auth.build_stream_url 을 쓴다.
_url_with_auth = build_stream_url


class Camera(BaseCamera):
    # 카메라(unique_id)마다 따로 둔다 — 같은 클래스를 쓰는 카메라끼리 설정이
    # 섞이지 않게. 값은 요청 때 받은 설정이고, 재접속 때마다 DB 에서 다시 읽는다.
    camera_options = {}

    @staticmethod
    def set_camera_options(camera_options):
        logger.info("Setting camera options")
        Camera.camera_options[camera_options.unique_id] = camera_options

    @staticmethod
    def frames(unique_id):
        # 접속 실패·재시도 대기 중에도 종료 조건을 검사하므로 이 생성기는 접속이
        # 한 번도 안 되어도 비활성화·무시청 시 스스로 끝난다. 대기 중에는
        # None(살아 있음 신호)을 내보내 BaseCamera 가 검사하게 한다.
        backoff = RetryBackoff()
        while True:
            if Camera.should_stop(unique_id):
                return

            settings = load_camera_settings(
                unique_id, fallback=Camera.camera_options.get(unique_id))
            if settings is None:
                logger.error("[%s] Camera settings not found", unique_id)
                return
            if getattr(settings, 'is_activated', True) is False:
                logger.info("[%s] Camera is deactivated; stopping stream", unique_id)
                return

            raw_url = settings.url_stream
            if not raw_url:
                logger.error("[%s] No stream URL configured for this camera", unique_id)
                return
            if settings.auth_username and not settings.auth_password:
                # 비밀번호 없이 두드리면 카메라 로그인 잠금만 키운다
                logger.error("[%s] Username is set but password is empty; "
                             "not connecting", unique_id)
                return

            fp = credential_fingerprint(raw_url, settings.auth_username, settings.auth_password)
            if is_auth_latched(unique_id, fp):
                logger.error("[%s] Camera already rejected these credentials; not retrying. "
                             "Change the credentials or save the camera settings to try again.",
                             unique_id)
                return

            stream_url = build_stream_url(
                raw_url, settings.auth_username, settings.auth_password)
            wait_period = 1.0 / (settings.stream_fps or 5)

            capture = open_capture(stream_url, cv2)
            if not capture.isOpened():
                capture.release()
                if settings.auth_username and http_auth_rejected(
                        raw_url, settings.auth_username, settings.auth_password):
                    latch_auth_failure(unique_id, fp)
                    logger.error("[%s] Camera rejected the credentials for %s; stopping to avoid "
                                 "locking the account. Check the settings and open the stream again.",
                                 unique_id, redact_url(raw_url))
                    return
                # rtsp:// 는 열기 실패의 이유를 알 수 없다. 자격 증명이 있으면 로그인 잠금을
                # 피하도록 인증 실패용(60→900초) 간격으로 둔다.
                delay = backoff.next_delay(auth=bool(settings.auth_username))
                logger.error("Could not open IP camera stream: %s (retry in %ds)",
                             redact_url(stream_url), delay)
                if Camera.sleep_unless_stopped(unique_id, delay):
                    return
                yield None
                continue

            backoff.reset()
            if KEEP_ALIVE_SECONDS > Camera.IDLE_TIMEOUT:
                BaseCamera.idle_grace[unique_id] = KEEP_ALIVE_SECONDS
            try:
                last_sent = 0.0
                while True:
                    if Camera.should_stop(unique_id):
                        return
                    # 매 프레임을 읽어 버퍼가 쌓이지 않게 하되(지연 방지),
                    # JPEG 인코딩은 stream_fps 간격으로만 한다
                    if not capture.grab():
                        logger.warning("Lost frame from IP camera stream, "
                                       "reconnecting: %s", redact_url(stream_url))
                        break
                    now = time.time()
                    if now - last_sent < wait_period:
                        continue
                    ret, img = capture.retrieve()
                    if not ret or img is None:
                        break
                    last_sent = now
                    yield cv2.imencode('.jpg', img)[1].tobytes()
            finally:
                capture.release()
                BaseCamera.idle_grace.pop(unique_id, None)  # 끊기면 기본 유예로 복귀
            if Camera.sleep_unless_stopped(unique_id, 2):
                return
            yield None
