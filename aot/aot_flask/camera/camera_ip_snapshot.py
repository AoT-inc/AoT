# -*- coding: utf-8 -*-
"""가벼운 IP 카메라 중계: HTTP 스냅샷(JPEG)을 주기적으로 받아 그대로 내보낸다.

RTSP 상시 수신·H.264 디코딩·JPEG 재인코딩이 없다. 카메라가 준 JPEG 바이트를
검증만 하고 그대로 중계하므로 라즈베리 파이급 장비에 맞다. 시청자가 없으면
요청 자체를 보내지 않는다.
"""
import logging
import time

from aot.aot_flask.camera.base_camera import BaseCamera, load_camera_settings
from aot.aot_flask.camera.net_auth import (
    RetryBackoff, SnapshotAuthError, SnapshotError, credential_fingerprint,
    fetch_snapshot, is_auth_latched, latch_auth_failure, redact_url)

logger = logging.getLogger(__name__)

# 초당 요청 상한: 스냅샷마다 카메라가 JPEG 를 새로 인코딩한다
MAX_FPS = 2.0


def snapshot_verify(settings):
    """자체 서명 인증서를 허용하는 옵션(custom_options 의 JSON 안 'verify_tls': false)."""
    import json
    try:
        opts = json.loads(getattr(settings, 'custom_options', '') or '{}')
    except (TypeError, ValueError):
        opts = {}
    return opts.get('verify_tls', True) is not False


def snapshot_headers(settings):
    import json
    try:
        headers = json.loads(getattr(settings, 'json_headers', '') or '{}')
        return headers if isinstance(headers, dict) else {}
    except (TypeError, ValueError):
        return {}


class Camera(BaseCamera):
    camera_options = {}

    @staticmethod
    def set_camera_options(camera_options):
        Camera.camera_options[camera_options.unique_id] = camera_options

    @staticmethod
    def frames(unique_id):
        import requests
        backoff = RetryBackoff()
        session = requests.Session()
        try:
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
                url = settings.url_still
                if not url:
                    logger.error("[%s] No snapshot URL configured for this camera", unique_id)
                    return
                if settings.auth_username and not settings.auth_password:
                    logger.error("[%s] Username is set but password is empty; "
                                 "not connecting", unique_id)
                    return

                fp = credential_fingerprint(url, settings.auth_username, settings.auth_password)
                if is_auth_latched(unique_id, fp):
                    logger.error("[%s] Camera already rejected these credentials; not retrying. "
                                 "Change the credentials or save the camera settings to try again.",
                                 unique_id)
                    return

                interval = 1.0 / min(MAX_FPS, float(settings.stream_fps or 1))
                started = time.time()
                try:
                    data = fetch_snapshot(
                        url, settings.auth_username, settings.auth_password,
                        verify=snapshot_verify(settings),
                        headers=snapshot_headers(settings), session=session)
                except SnapshotAuthError:
                    latch_auth_failure(unique_id, fp)
                    logger.error("[%s] Camera rejected the credentials for %s; "
                                 "stopping to avoid locking the account. "
                                 "Check the settings and open the stream again.",
                                 unique_id, redact_url(url))
                    return
                except SnapshotError as err:
                    delay = backoff.next_delay()
                    logger.error("[%s] Snapshot failed for %s: %s (retry in %ds)",
                                 unique_id, redact_url(url), err, delay)
                    if Camera.sleep_unless_stopped(unique_id, delay):
                        return
                    yield None
                    continue

                backoff.reset()
                yield data
                rest = interval - (time.time() - started)
                if rest > 0 and Camera.sleep_unless_stopped(unique_id, rest):
                    return
        finally:
            session.close()
