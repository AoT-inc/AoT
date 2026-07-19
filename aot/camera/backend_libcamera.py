import logging
import numpy as np
from typing import Optional, List, Any
from .backend import CameraBackend, StreamHandle
from .models import CameraConfig, CameraCapabilities
from .exceptions import CameraError, InitializationError, CaptureError

logger = logging.getLogger(__name__)

class LibcameraBackend(CameraBackend):
    """Libcamera backend for Raspberry Pi camera modules using Picamera2.

    @phase active
    @stability stable
    @dependency CameraBackend, Picamera2
    """
    
    def __init__(self):
        super().__init__()
        self.camera: Any = None
        self._config: Optional[CameraConfig] = None
        
    def initialize(self, config: CameraConfig) -> bool:
        """Initialize libcamera through Picamera2 with the given resolution."""
        try:
            from picamera2 import Picamera2
        except ImportError:
            logger.error("picamera2 library not found. libcamera backend unavailable.")
            return False
            
        try:
            self.camera = Picamera2()
            
            # Configure the camera
            camera_config = self.camera.create_still_configuration(
                main={"size": config.resolution}
            )
            self.camera.configure(camera_config)
            
            # Start the camera (required for libcamera)
            self.camera.start()
            
            self._config = config
            self._is_initialized = True
            logger.info(f"libcamera initialized: {config.resolution}")
            return True
        except Exception as e:
            logger.error(f"Failed to initialize libcamera: {e}")
            return False
            
    def capture_image(self) -> np.ndarray:
        """Capture a single frame using Picamera2."""
        if not self._is_initialized or self.camera is None:
            raise CameraError("libcamera not initialized")
            
        try:
            return self.camera.capture_array()
        except Exception as e:
            logger.error(f"libcamera capture failed: {e}")
            raise CaptureError(f"Failed to capture frame from libcamera: {e}") from e

    def start_stream(self) -> StreamHandle:
        """Start Picamera2 stream and return a handle."""
        if not self._is_initialized:
            raise CameraError("Cannot start stream: libcamera not initialized")
        return StreamHandle(id="libcamera_stream")

    def stop_stream(self, handle: StreamHandle) -> None:
        """Stop the Picamera2 stream."""
        pass

    def get_capabilities(self) -> CameraCapabilities:
        """Query camera capabilities for Picamera2-supported resolutions and features."""
        return CameraCapabilities(
            resolutions=[(3280, 2464), (1920, 1080), (1280, 720), (640, 480)],
            max_fps=30,
            supports_ptz=False,
            supports_hdr=True,
            supports_manual_exposure=True
        )

    def release(self) -> None:
        if self.camera:
            try:
                self.camera.stop()
                self.camera.close()
            except Exception as e:
                logger.warning(f"Error during libcamera release: {e}")
            self.camera = None
        self._is_initialized = False
        self._config = None
