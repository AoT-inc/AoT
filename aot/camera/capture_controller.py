# coding=utf-8
import os
import time
import threading
from datetime import datetime
import cv2
import logging
from aot.camera.service import CameraService
from aot.camera.backends.base import CameraError

logger = logging.getLogger(__name__)

CAMERA_STORAGE_PATH = os.getenv('AOT_CAMERA_STORAGE_PATH',
    os.path.join(os.path.dirname(os.path.abspath(__file__)), '../../storage/camera'))
os.makedirs(CAMERA_STORAGE_PATH, exist_ok=True)

class CaptureController:
    """Control capture modes and manage capture threads for snapshot, timelapse, and video.

    @phase active
    @stability stable
    @dependency CameraService, TimelapseThread, VideoRecordThread
    """

    def __init__(self, camera_service: CameraService):
        self.camera_service = camera_service
        self.active_captures = {}  # camera_id -> capture_thread

    def start_capture(self, camera_id: str, mode: str, settings: dict) -> bool:
        """Start a capture operation in the specified mode."""
        if mode == 'snapshot':
            return self._capture_snapshot(camera_id, settings)
        elif mode == 'timelapse':
            return self._start_timelapse(camera_id, settings)
        elif mode == 'video':
            return self._start_video(camera_id, settings)
        elif mode == 'stream':
            return self._start_stream(camera_id, settings)
        else:
            raise ValueError(f"Unknown capture mode: {mode}")

    def stop_capture(self, camera_id: str) -> bool:
        """Stop an active capture operation."""
        if camera_id in self.active_captures:
            thread = self.active_captures[camera_id]
            if hasattr(thread, 'stop'):
                thread.stop()
            del self.active_captures[camera_id]
            return True
        return False

    def _capture_snapshot(self, camera_id: str, settings: dict) -> bool:
        """Capture a single snapshot image."""
        try:
            # Note: This requires the camera to be initialized in CameraService
            # In a real scenario, we'd look up the camera config first
            backend = self.camera_service.active_cameras.get(camera_id)
            if not backend:
                logger.error(f"Camera {camera_id} not initialized")
                return False

            image = backend.capture_image()
            quality = settings.get('quality', 95)
            img_format = settings.get('format', 'jpeg')

            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            filename = f'snapshot_{camera_id}_{timestamp}.{img_format}'
            filepath = os.path.join(CAMERA_STORAGE_PATH, filename)

            if img_format == 'jpeg':
                cv2.imwrite(filepath, image, [cv2.IMWRITE_JPEG_QUALITY, quality])
            elif img_format == 'png':
                cv2.imwrite(filepath, image, [cv2.IMWRITE_PNG_COMPRESSION, 9])
            else:
                cv2.imwrite(filepath, image)

            logger.info(f"Snapshot saved: {filepath}")
            return True
        except Exception as e:
            logger.exception(f"Snapshot capture failed: {e}")
            return False

    def _start_timelapse(self, camera_id: str, settings: dict) -> bool:
        """Start a TimelapseThread for periodic frame capture."""
        from aot.camera.capture_threads import TimelapseThread
        thread = TimelapseThread(
            camera_id=camera_id,
            camera_service=self.camera_service,
            interval=settings.get('interval', 60),
            duration=settings.get('duration', 0),
            auto_video=settings.get('auto_video', False),
            settings=settings
        )
        thread.start()
        self.active_captures[camera_id] = thread
        logger.info(f"Timelapse started: {camera_id}")
        return True

    def _start_video(self, camera_id: str, settings: dict) -> bool:
        """Start a VideoRecordThread for continuous video recording."""
        from aot.camera.capture_threads import VideoRecordThread
        thread = VideoRecordThread(
            camera_id=camera_id,
            camera_service=self.camera_service,
            fps=settings.get('fps', 30),
            duration=settings.get('duration', 0),
            codec=settings.get('codec', 'h264'),
            settings=settings
        )
        thread.start()
        self.active_captures[camera_id] = thread
        logger.info(f"Video recording started: {camera_id}")
        return True

    def _start_stream(self, camera_id: str, settings: dict) -> bool:
        """Placeholder for stream mode (delegates to StreamHandler layer)."""
        logger.info(f"Stream requested for {camera_id} (Not implemented in this layer)")
        return True
