"""
Resource monitoring and diagnostic tools for the camera system.
"""
import os
import logging
import time
from typing import Dict, Any, Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class ResourceSnapshot:
    """Point-in-time snapshot of system resources."""
    timestamp: float
    memory_used_mb: float
    memory_available_mb: float
    disk_used_mb: float
    disk_available_mb: float


class ResourceMonitor:
    """Monitor system resources and enforce profile-defined limits.

    @phase active
    @stability stable
    """

    def __init__(self, memory_limit_mb: int = 500, disk_limit_mb: int = 1000):
        self.memory_limit_mb = memory_limit_mb
        self.disk_limit_mb = disk_limit_mb

    def get_snapshot(self) -> ResourceSnapshot:
        """Take a snapshot of current system resources."""
        try:
            import psutil
            mem = psutil.virtual_memory()
            disk = psutil.disk_usage('/')
            return ResourceSnapshot(
                timestamp=time.time(),
                memory_used_mb=mem.used / (1024 * 1024),
                memory_available_mb=mem.available / (1024 * 1024),
                disk_used_mb=disk.used / (1024 * 1024),
                disk_available_mb=disk.free / (1024 * 1024),
            )
        except ImportError:
            # Fallback without psutil
            return ResourceSnapshot(
                timestamp=time.time(),
                memory_used_mb=0,
                memory_available_mb=float('inf'),
                disk_used_mb=0,
                disk_available_mb=float('inf'),
            )

    def check_resources(self) -> Dict[str, Any]:
        """Check if resources are within acceptable limits."""
        snap = self.get_snapshot()
        memory_ok = snap.memory_available_mb > self.memory_limit_mb * 0.1
        disk_ok = snap.disk_available_mb > self.disk_limit_mb * 0.1
        return {
            'memory_ok': memory_ok,
            'disk_ok': disk_ok,
            'memory_available_mb': snap.memory_available_mb,
            'disk_available_mb': snap.disk_available_mb,
        }

    def can_proceed(self) -> bool:
        """Simple check: are resources sufficient to proceed?"""
        status = self.check_resources()
        return status['memory_ok'] and status['disk_ok']


class Diagnostics:
    """Provide diagnostic tools for camera system troubleshooting.

    @phase active
    @stability stable
    @dependency CameraService
    """

    @staticmethod
    def get_library_versions() -> Dict[str, str]:
        """Report versions of key libraries."""
        versions = {}
        try:
            import cv2
            versions['opencv'] = cv2.__version__
        except ImportError:
            versions['opencv'] = 'not installed'

        try:
            import numpy
            versions['numpy'] = numpy.__version__
        except ImportError:
            versions['numpy'] = 'not installed'

        try:
            import plantcv
            versions['plantcv'] = getattr(plantcv, '__version__', 'installed (version unknown)')
        except ImportError:
            versions['plantcv'] = 'not installed'

        return versions

    @staticmethod
    def get_camera_status_report(service) -> Dict[str, Any]:
        """Generate a status report for all cameras managed by CameraService."""
        report = {
            'active_cameras': service.active_cameras_count,
            'camera_ids': service.list_cameras(),
            'library_versions': Diagnostics.get_library_versions(),
            'timestamp': time.time(),
        }
        return report
