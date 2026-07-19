# coding=utf-8
import logging
from typing import Dict, Optional
from aot.camera.backends.base import CameraBackend, CameraConfig

logger = logging.getLogger(__name__)

class CameraService:
    """Unified camera service for managing and routing to all backend implementations.

    @phase active
    @stability stable
    @dependency CameraBackend, CameraConfig
    """

    def __init__(self):
        self.active_cameras: Dict[str, CameraBackend] = {}

    def get_backend(self, config: CameraConfig) -> Optional[CameraBackend]:
        """Return active backend for a camera ID or create a new one."""
        if config.unique_id in self.active_cameras:
            return self.active_cameras[config.unique_id]
        
        backend = self._select_backend(config)
        if backend and backend.initialize(config):
            self.active_cameras[config.unique_id] = backend
            return backend
        return None

    def _select_backend(self, config: CameraConfig) -> Optional[CameraBackend]:
        """Select the appropriate backend for the given camera type."""
        camera_type = config.camera_type

        # --- 레거시 백엔드 ---
        if camera_type == 'fswebcam':
            from aot.camera.backends.legacy_backends import FswebcamBackend
            return FswebcamBackend()

        elif camera_type == 'raspistill':
            from aot.camera.backends.legacy_backends import RaspistillBackend
            return RaspistillBackend()

        elif camera_type == 'picamera':
            from aot.camera.backends.legacy_backends import PicameraBackend
            return PicameraBackend()

        elif camera_type == 'url_urllib':
            from aot.camera.backends.legacy_backends import UrllibStreamBackend
            return UrllibStreamBackend()

        elif camera_type == 'url_requests':
            from aot.camera.backends.legacy_backends import RequestsStreamBackend
            return RequestsStreamBackend()

        # --- 현대적 통합 백엔드 ---
        elif camera_type == 'rpi_csi':
            # Note: LibcameraBackend implementation will follow in next steps
            try:
                from aot.camera.backends.libcamera_backend import LibcameraBackend
                return LibcameraBackend()
            except ImportError:
                logger.error("LibcameraBackend not implemented yet")
                return None

        elif camera_type in ('usb_webcam', 'builtin_webcam', 'virtual_camera',
                             'stream_url', 'usb_passthrough'):
            # Note: OpenCVBackend implementation will follow in next steps
            try:
                from aot.camera.backends.opencv_backend import OpenCVBackend
                return OpenCVBackend()
            except ImportError:
                logger.error("OpenCVBackend not implemented yet")
                return None

        elif camera_type == 'ip_camera':
            # Note: IPCameraBackend implementation will follow in next steps
            try:
                from aot.camera.backends.ip_camera_backend import IPCameraBackend
                return IPCameraBackend()
            except ImportError:
                logger.error("IPCameraBackend not implemented yet")
                return None

        else:
            logger.error(f"Unknown camera type: {camera_type}")
            return None

    def release_camera(self, camera_id: str):
        """Release resources for a specific camera."""
        if camera_id in self.active_cameras:
            self.active_cameras[camera_id].release()
            del self.active_cameras[camera_id]

    def release_all(self):
        """Release resources for all active cameras."""
        for camera_id in list(self.active_cameras.keys()):
            self.release_camera(camera_id)
