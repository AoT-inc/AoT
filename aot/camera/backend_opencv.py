import cv2
import numpy as np
import logging
from typing import Optional, Dict, Any, List
from .backend import CameraBackend, StreamHandle
from .models import CameraConfig, CameraCapabilities
from .exceptions import CameraError, InitializationError, CaptureError

logger = logging.getLogger(__name__)

class OpenCVBackend(CameraBackend):
    """OpenCV camera backend for USB and system cameras on Linux and macOS.

    @phase active
    @stability stable
    @dependency CameraBackend
    """
    
    def __init__(self):
        super().__init__()
        self.cap: Optional[cv2.VideoCapture] = None
        self._config: Optional[CameraConfig] = None
        
    def initialize(self, config: CameraConfig) -> bool:
        """Initialize OpenCV VideoCapture with the given configuration."""
        try:
            # Use device_path if provided, otherwise try converting to int (for default cameras)
            source: Any = config.device_path
            if source is None:
                source = 0 # Default to 0 if nothing specified
            elif source.isdigit():
                source = int(source)
            
            self.cap = cv2.VideoCapture(source)
            if not self.cap.isOpened():
                logger.error(f"Failed to open OpenCV camera with source: {source}")
                return False
            
            # Apply configuration
            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, config.resolution[0])
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, config.resolution[1])
            self.cap.set(cv2.CAP_PROP_FPS, config.fps)
            
            self._config = config
            self._is_initialized = True
            return True
            
        except Exception as e:
            logger.error(f"Error during OpenCV initialization: {e}")
            return False
            
    def capture_image(self) -> np.ndarray:
        """Capture a single frame from the camera."""
        if not self._is_initialized or self.cap is None:
            raise CameraError("OpenCV camera not initialized")
            
        try:
            ret, frame = self.cap.read()
            if not ret or frame is None:
                raise CaptureError("Failed to read frame from OpenCV camera")
            return frame
        except Exception as e:
            if not isinstance(e, (CameraError, CaptureError)):
                logger.error(f"Unexpected error during capture: {e}")
                raise CaptureError(f"OpenCV capture failed: {e}") from e
            raise

    def start_stream(self) -> StreamHandle:
        """Start the OpenCV video stream and return a handle."""
        if not self._is_initialized:
            raise CameraError("Cannot start stream: Camera not initialized")
        return StreamHandle(id="opencv_default_stream")

    def stop_stream(self, handle: StreamHandle) -> None:
        """Stop the OpenCV video stream."""

    def get_capabilities(self) -> CameraCapabilities:
        """Query camera capabilities from OpenCV VideoCapture properties."""
        if not self.cap:
            return CameraCapabilities(resolutions=[], max_fps=0, supports_ptz=False, supports_hdr=False, supports_manual_exposure=False)

        return CameraCapabilities(
            resolutions=[(int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH)), 
                          int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT)))],
            max_fps=int(self.cap.get(cv2.CAP_PROP_FPS)),
            supports_ptz=False,
            supports_hdr=False,
            supports_manual_exposure=True
        )

    def release(self) -> None:
        if self.cap:
            self.cap.release()
            self.cap = None
        self._is_initialized = False
        self._config = None
