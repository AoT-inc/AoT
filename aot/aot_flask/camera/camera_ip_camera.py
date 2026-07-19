# -*- coding: utf-8 -*-
"""MJPEG relay for network (RTSP/ONVIF/HTTP) IP cameras, e.g. VIGI/TP-Link cameras."""
import logging
import time

import cv2

from aot.aot_flask.camera.base_camera import BaseCamera

logger = logging.getLogger(__name__)


def _url_with_auth(url, username, password):
    """Inject username/password into a stream URL's netloc, if not already present."""
    if not username or not url or '://' not in url:
        return url

    from urllib.parse import urlparse, urlunparse

    parsed = urlparse(url)
    if parsed.username:
        return url

    netloc = f"{username}:{password or ''}@{parsed.hostname}"
    if parsed.port:
        netloc += f":{parsed.port}"
    return urlunparse(parsed._replace(netloc=netloc))


class Camera(BaseCamera):
    camera_options = None

    @staticmethod
    def set_camera_options(camera_options):
        logger.info("Setting camera options")
        Camera.camera_options = camera_options

    @staticmethod
    def frames():
        settings = Camera.camera_options
        stream_url = _url_with_auth(
            settings.url_stream, settings.auth_username, settings.auth_password)

        if not stream_url:
            raise RuntimeError('No stream URL configured for this camera.')

        wait_period = 1.0 / (settings.stream_fps or 5)

        # Network streams drop and reconnect; keep retrying instead of
        # letting one dropped connection kill the stream permanently.
        while True:
            capture = cv2.VideoCapture(stream_url)
            if not capture.isOpened():
                logger.error("Could not open IP camera stream: %s", stream_url)
                capture.release()
                time.sleep(5)
                continue

            while True:
                ret, img = capture.read()
                if not ret or img is None:
                    logger.warning("Lost frame from IP camera stream, reconnecting: %s", stream_url)
                    break
                time.sleep(wait_period)
                yield cv2.imencode('.jpg', img)[1].tobytes()

            capture.release()
            time.sleep(2)
