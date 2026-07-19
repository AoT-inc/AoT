# coding=utf-8
from abc import ABC, abstractmethod
import numpy as np

class CameraConfig:
    """Simplified camera configuration for backend initialization.

    @phase active
    @stability stable
    """
    def __init__(self, **kwargs):
        self.camera_type = kwargs.get('camera_type', 'usb_webcam')
        self.device_id = kwargs.get('device_id', 0)
        self.ip_address = kwargs.get('ip_address', '')
        self.stream_url = kwargs.get('stream_url', '')
        self.width = kwargs.get('width', 1280)
        self.height = kwargs.get('height', 720)
        self.fps = kwargs.get('fps', 30)
        self.unique_id = kwargs.get('unique_id', '')

class CameraError(Exception):
    """Base exception for all camera-related errors."""
    pass

class CameraBackend(ABC):
    """Abstract interface for camera backend implementations.

    @phase active
    @stability stable
    """

    @abstractmethod
    def initialize(self, config: CameraConfig) -> bool:
        pass

    @abstractmethod
    def capture_image(self) -> np.ndarray:
        pass

    def release(self) -> None:
        pass
