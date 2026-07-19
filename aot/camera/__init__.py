from .backend import CameraBackend, StreamHandle
from .models import CameraConfig, PerformanceProfile, BackendType, CameraCapabilities, ProcessedImage
from .profiles import LOW, MEDIUM, HIGH, PROFILES
from .exceptions import CameraError, InitializationError, CaptureError, ConfigurationError
from .platform_utils import recommend_profile, detect_platform

# Backends
from .backend_opencv import OpenCVBackend
from .backend_libcamera import LibcameraBackend
from .backend_ipcamera import IPCameraBackend
from .backend_legacy import LegacyBackend

# Discovery
from .discovery import IPCameraDiscovery

# Service & Processor
from .service import CameraService
from .processor import ImageProcessor

# Phase 4: Streaming, Timelapse & Config
from .streaming import StreamHandler
from .timelapse import TimelapseService
from .config_mgmt import ConfigManager

# Phase 5: Security & Diagnostics
from .security import SecurityManager, Permission, Role
from .diagnostics import ResourceMonitor, Diagnostics

# Phase 6 & 7: API, Profile Manager
from .api import camera_api, init_camera_api
from .profile_manager import ProfileManager

__all__ = [
    'CameraBackend',
    'StreamHandle',
    'CameraConfig',
    'PerformanceProfile',
    'BackendType',
    'CameraCapabilities',
    'ProcessedImage',
    'LOW',
    'MEDIUM',
    'HIGH',
    'PROFILES',
    'CameraError',
    'InitializationError',
    'CaptureError',
    'ConfigurationError',
    'recommend_profile',
    'detect_platform',
    'OpenCVBackend',
    'LibcameraBackend',
    'IPCameraBackend',
    'LegacyBackend',
    'IPCameraDiscovery',
    'CameraService',
    'ImageProcessor',
    'StreamHandler',
    'TimelapseService',
    'ConfigManager',
    'SecurityManager',
    'Permission',
    'Role',
    'ResourceMonitor',
    'Diagnostics',
    'camera_api',
    'init_camera_api',
    'ProfileManager',
]
