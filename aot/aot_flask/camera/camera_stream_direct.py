# -*- coding: utf-8 -*-
import logging
from aot.aot_flask.camera.base_camera import BaseCamera

logger = logging.getLogger(__name__)

class Camera(BaseCamera):
    """
    서버에서 프레임을 직접 처리하지 않고 클라이언트에서 스트리밍 URL로 직접 접속하기 위한
    '가상' 카메라 클래스입니다. BaseCamera의 구조를 유지하면서 서버 측의 부하를 없앱니다.
    """
    camera_options = None

    @staticmethod
    def set_camera_options(camera_options):
        """가장 최근의 카메라 설정을 저장합니다."""
        Camera.camera_options = camera_options

    @staticmethod
    def frames():
        """
        서버 사이드 MJPEG 스트리밍을 제공하지 않습니다.
        클라이언트에서 직접 스트리밍 URL을 사용해야 합니다.
        """
        logger.info("Direct Stream Camera: Server-side frame generation is disabled.")
        return
        yield  # To make it a generator
