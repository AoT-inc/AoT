# -*- coding: utf-8 -*-
"""VIGI 카메라의 레거시 규약 어댑터 (library='vigi'). 설계 §2·§3.3.

`/video_feed/<id>` 가 `camera_<library>` 모듈을 import 해 BaseCamera 스레드로 프레임을 받는다.
프레임은 `aot.camera_drivers` 의 FrameHub 가 읽는다 — 인증은 AuthGuard 가 지키므로 여기엔 인증 재시도가 없다.
허브가 치명 오류(인증 래치·미설정)로 멈추면 이 스트림은 끝난다. 사용자가 래치를 풀고 다시 열 때 새로 시작한다.
"""
import logging
import threading

from aot.aot_flask.camera.base_camera import BaseCamera
from aot.camera_drivers import frames as F
from aot.camera_drivers import runtime

logger = logging.getLogger(__name__)


class Camera(BaseCamera):
    camera_options = {}

    @staticmethod
    def set_camera_options(camera_options):
        Camera.camera_options[camera_options.unique_id] = camera_options

    @staticmethod
    def frames(unique_id):
        hub = runtime.live_hub(unique_id)
        wake = threading.Event()
        holder = {}

        def on_frame(frame):
            holder['jpeg'] = frame.jpeg
            wake.set()

        token = hub.subscribe(on_frame)
        latest_file = F.LatestFrameFile(unique_id)
        file_token = hub.subscribe(latest_file)     # 다른 워커·데몬의 스냅샷이 읽는 최신 프레임 파일
        try:
            while True:
                if Camera.should_stop(unique_id):
                    return
                if hub.dead_reason:
                    logger.error("[%s] VIGI stream stopped: %s", unique_id, hub.dead_reason)
                    return
                if not wake.wait(timeout=1.0):
                    yield None       # 살아 있음 신호 — BaseCamera 가 종료 조건을 검사한다
                    continue
                wake.clear()
                jpeg = holder.get('jpeg')
                if jpeg:
                    yield jpeg
        finally:
            hub.unsubscribe(token)
            hub.unsubscribe(file_token)
