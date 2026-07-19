from dataclasses import dataclass, field
from typing import Optional, Dict, List, Any, Tuple
from enum import Enum

class BackendType(Enum):
    """Enumeration of supported camera backend implementations.

    @phase active
    @stability stable
    """
    OPENCV = "opencv"
    LIBCAMERA = "libcamera"
    IP_CAMERA = "ip_camera"
    MOCK = "mock"

@dataclass(frozen=True)
class PerformanceProfile:
    """Define system resource limits and feature availability for a performance tier.

    @phase active
    @stability stable
    """
    name: str
    max_resolution: Tuple[int, int]
    max_fps: int
    enable_plantcv: bool
    enable_hdr: bool
    enable_noise_reduction: bool
    max_ip_cameras: int
    stream_quality: int  # 1-100

@dataclass
class CameraConfig:
    """Configure a single camera instance with device, capture, and processing settings.

    @phase active
    @stability stable
    """
    unique_id: str
    name: str
    backend_type: BackendType
    device_path: Optional[str] = None  # For USB/OpenCV/libcamera (/dev/video0)
    url: Optional[str] = None         # For IP Camera (RTSP/HTTP)
    username: Optional[str] = None    # For IP Camera authentication
    password: Optional[str] = None    # For IP Camera authentication
    
    # Capture Settings
    resolution: Tuple[int, int] = (1280, 720)
    fps: int = 15
    
    # Image Settings
    brightness: float = 0.5
    contrast: float = 0.5
    saturation: float = 0.5
    gain: float = 0.0
    exposure: float = 0.0
    
    # Processing Flags
    flip_h: bool = False
    flip_v: bool = False
    rotation: int = 0  # 0, 90, 180, 270
    
    # Custom Backend Options
    custom_options: Dict[str, Any] = field(default_factory=dict)

    def validate(self, profile: PerformanceProfile):
        """Validate configuration against a performance profile."""
        if self.resolution[0] > profile.max_resolution[0] or self.resolution[1] > profile.max_resolution[1]:
            raise ValueError(f"Resolution {self.resolution} exceeds profile limit {profile.max_resolution}")
        if self.fps > profile.max_fps:
            raise ValueError(f"FPS {self.fps} exceeds profile limit {profile.max_fps}")

@dataclass(frozen=True)
class CameraCapabilities:
    """Describe supported features for a specific camera hardware or backend.

    @phase active
    @stability stable
    """
    resolutions: List[Tuple[int, int]]
    max_fps: int
    supports_ptz: bool
    supports_hdr: bool
    supports_manual_exposure: bool
    backend_specific: Dict[str, Any] = field(default_factory=dict)

@dataclass
class ProcessedImage:
    """Container for processed image data with metadata and optional plant analysis metrics.

    @phase active
    @stability stable
    """
    raw_data: bytes
    format: str  # e.g., 'jpeg', 'png'
    timestamp: float
    metadata: Dict[str, Any]
    plant_metrics: Optional[Dict[str, Any]] = None

@dataclass
class StreamConfig:
    """Configuration for a video stream.

    @phase active
    @stability stable
    """
    port: int
    protocol: str  # 'hls', 'webrtc', 'mjpeg'
    quality: int
    use_auth: bool = True
