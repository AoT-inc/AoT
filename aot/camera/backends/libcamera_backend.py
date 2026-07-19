# coding=utf-8
import subprocess
import os
import logging
import cv2
import numpy as np
from aot.camera.backends.base import CameraBackend, CameraConfig, CameraError

logger = logging.getLogger(__name__)

class LibcameraBackend(CameraBackend):
    """Raspberry Pi libcamera backend using Picamera2 with RGB-to-BGR conversion.

    @phase active
    @stability stable
    @dependency CameraBackend, Picamera2
    """

    def __init__(self):
        self.picam2 = None
        self.width = 1920
        self.height = 1080

    def initialize(self, config: CameraConfig) -> bool:
        self.width = config.width
        self.height = config.height
        
        try:
            from picamera2 import Picamera2
            self.picam2 = Picamera2()
            
            # Configure camera
            config_picam = self.picam2.create_still_configuration(
                main={"format": "RGB888", "size": (self.width, self.height)}
            )
            self.picam2.configure(config_picam)
            self.picam2.start()
            return True
        except ImportError:
            logger.error("picamera2 library not found. libcamera backend requires picamera2.")
            return False
        except Exception as e:
            logger.error(f"Failed to initialize Libcamera: {e}")
            return False

    def capture_image(self) -> np.ndarray:
        if not self.picam2:
            raise CameraError("Libcamera is not initialized")
            
        try:
            # Capture as numpy array
            frame = self.picam2.capture_array()
            # Convert RGB to BGR for OpenCV compatibility
            return cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
        except Exception as e:
            raise CameraError(f"Libcamera capture failed: {e}")

    def release(self) -> None:
        if self.picam2:
            self.picam2.stop()
            self.picam2 = None
