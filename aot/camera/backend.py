import numpy as np
from abc import ABC, abstractmethod
from typing import Generator, Any, Optional, Dict, List
from dataclasses import dataclass
from .models import CameraConfig, CameraCapabilities

@dataclass
class StreamHandle:
    """Handle for an active camera stream.

    @phase active
    @stability stable
    """
    id: str
    metadata: Optional[Dict[str, Any]] = None

class CameraBackend(ABC):
    """Abstract base class defining the standard interface for all camera backends.

    @phase active
    @stability stable
    """
    
    def __init__(self):
        self._is_initialized = False

    @abstractmethod
    def initialize(self, config: CameraConfig) -> bool:
        """
        Initialize the camera hardware or connection.
        """
        pass

    @abstractmethod
    def capture_image(self) -> np.ndarray:
        """
        Capture a single frame from the camera.
        """
        pass

    @abstractmethod
    def start_stream(self) -> StreamHandle:
        """
        Start the video stream.
        """
        pass

    @abstractmethod
    def stop_stream(self, handle: StreamHandle) -> None:
        """
        Stop the video stream.
        """
        pass

    @abstractmethod
    def get_capabilities(self) -> CameraCapabilities:
        """
        Query the camera for its supported features and resolutions.
        """
        pass

    @abstractmethod
    def release(self) -> None:
        """Release all camera resources (hardware, network connections)."""
        pass

    @property
    def is_initialized(self) -> bool:
        return self._is_initialized
