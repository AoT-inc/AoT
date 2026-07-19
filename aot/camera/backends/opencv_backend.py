# coding=utf-8
import cv2
import numpy as np
import logging
from aot.camera.backends.base import CameraBackend, CameraConfig, CameraError

logger = logging.getLogger(__name__)

class OpenCVBackend(CameraBackend):
    """General-purpose OpenCV camera backend for USB, IP, and virtual cameras.

    @phase active
    @stability stable
    @dependency CameraBackend
    """

    def __init__(self):
        self.cap = None
        self.width = 1280
        self.height = 720

    def initialize(self, config: CameraConfig) -> bool:
        self.width = config.width
        self.height = config.height
        
        # device_id가 숫자면 USB/로컬 장치, 문자열이면 URL
        source = config.device_id if isinstance(config.device_id, int) else config.stream_url
        if not source and config.stream_url:
            source = config.stream_url
            
        self.cap = cv2.VideoCapture(source)
        if not self.cap.isOpened():
            logger.error(f"Failed to open OpenCV camera: {source}")
            return False
            
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
        return True

    def capture_image(self) -> np.ndarray:
        if not self.cap or not self.cap.isOpened():
            raise CameraError("OpenCV camera is not initialized")
            
        ret, frame = self.cap.read()
        if not ret:
            raise CameraError("Failed to capture frame from OpenCV camera")
        return frame

    def release(self) -> None:
        if self.cap:
            self.cap.release()
            self.cap = None
