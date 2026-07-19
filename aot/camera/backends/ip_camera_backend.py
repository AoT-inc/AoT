# coding=utf-8
import logging
import cv2
import numpy as np
from aot.camera.backends.base import CameraBackend, CameraConfig, CameraError

logger = logging.getLogger(__name__)

class IPCameraBackend(CameraBackend):
    """Simplified ONVIF/RTSP IP camera backend using OpenCV VideoCapture.

    @phase active
    @stability stable
    @dependency CameraBackend
    """

    def __init__(self):
        self.cap = None
        self.onvif_cam = None

    def initialize(self, config: CameraConfig) -> bool:
        # ONVIF discovery and PTZ would go here
        # For basic capture, we use RTSP URL via OpenCV
        rtsp_url = config.stream_url
        if not rtsp_url:
            logger.error("IP Camera requires a stream URL")
            return False
            
        self.cap = cv2.VideoCapture(rtsp_url)
        if not self.cap.isOpened():
            logger.error(f"Failed to open IP camera stream: {rtsp_url}")
            return False
        return True

    def capture_image(self) -> np.ndarray:
        if not self.cap or not self.cap.isOpened():
            raise CameraError("IP camera stream is not active")
            
        ret, frame = self.cap.read()
        if not ret:
            raise CameraError("Failed to capture frame from IP camera")
        return frame

    def release(self) -> None:
        if self.cap:
            self.cap.release()
            self.cap = None
