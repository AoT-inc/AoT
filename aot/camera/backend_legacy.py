import logging
import warnings
import numpy as np
import subprocess
import os
from typing import Optional, List, Any
from .backend import CameraBackend, StreamHandle
from .models import CameraConfig, CameraCapabilities
from .exceptions import CameraError, InitializationError, CaptureError

logger = logging.getLogger(__name__)

class LegacyBackend(CameraBackend):
    """Legacy backend wrapping deprecated CLI tools for backward compatibility.

    @phase deprecated
    @stability frozen
    @dependency CameraBackend
    @see OpenCVBackend, LibcameraBackend
    """
    
    def __init__(self):
        super().__init__()
        self._config: Optional[CameraConfig] = None
        warnings.warn(
            "LegacyBackend is deprecated and will be removed in a future version. "
            "Please upgrade to OpenCV or libcamera.",
            DeprecationWarning,
            stacklevel=2
        )
        
    def initialize(self, config: CameraConfig) -> bool:
        """Initialize legacy backend by detecting available CLI capture tools."""
        self._config = config
        try:
            if self._has_command("raspistill") or self._has_command("fswebcam"):
                self._is_initialized = True
                return True
        except Exception:
            pass
        return False
        
    def _has_command(self, cmd: str) -> bool:
        return subprocess.call(["which", cmd], stdout=subprocess.PIPE, stderr=subprocess.PIPE) == 0

    def capture_image(self) -> np.ndarray:
        """Capture image using raspistill or fswebcam CLI tools."""
        if not self._is_initialized:
            raise CameraError("Legacy backend not initialized")
            
        temp_file = "/tmp/legacy_capture.jpg"
        try:
            if self._has_command("raspistill"):
                subprocess.run(["raspistill", "-o", temp_file, "-t", "100", "-n"], check=True)
            elif self._has_command("fswebcam"):
                subprocess.run(["fswebcam", "-d", str(self._config.device_path or 0), temp_file], check=True)
            else:
                raise CaptureError("No legacy capture command available")
                
            import cv2
            image = cv2.imread(temp_file)
            if image is None:
                raise CaptureError("Failed to load image from temp file")
                
            return image
        except Exception as e:
            logger.error(f"Legacy capture failed: {e}")
            raise CaptureError(f"Legacy capture error: {e}") from e
        finally:
            if os.path.exists(temp_file):
                os.remove(temp_file)

    def start_stream(self) -> StreamHandle:
        raise CameraError("Streaming not supported on LegacyBackend")

    def stop_stream(self, handle: StreamHandle) -> None:
        """Stop stream (not supported on legacy backend)."""

    def get_capabilities(self) -> CameraCapabilities:
        return CameraCapabilities(
            resolutions=[],
            max_fps=1,
            supports_ptz=False,
            supports_hdr=False,
            supports_manual_exposure=False
        )

    def release(self) -> None:
        self._is_initialized = False
        self._config = None
