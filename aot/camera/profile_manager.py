"""
Dynamic profile application: allows changing performance profile at runtime
without restarting the camera system.
"""
import logging
from typing import Optional
from .models import PerformanceProfile
from .profiles import PROFILES
from .service import CameraService
from .processor import ImageProcessor

logger = logging.getLogger(__name__)


class ProfileManager:
    """Manage dynamic switching of performance profiles at runtime.

    @phase active
    @stability stable
    @dependency CameraService, ImageProcessor, PerformanceProfile
    """

    def __init__(self, camera_service: CameraService, image_processor: ImageProcessor):
        self._camera_service = camera_service
        self._image_processor = image_processor
        self._current_profile_name: Optional[str] = None

    @property
    def current_profile(self) -> Optional[str]:
        return self._current_profile_name

    def apply_profile(self, profile_name: str) -> bool:
        """
        Apply a new performance profile.
        Returns True if the profile was successfully applied.
        """
        profile_name = profile_name.lower()
        if profile_name not in PROFILES:
            logger.error(f"Unknown profile: {profile_name}")
            return False

        profile = PROFILES[profile_name]

        # Update ImageProcessor profile
        self._image_processor.profile = profile
        self._current_profile_name = profile_name

        logger.info(f"Applied performance profile: {profile_name}")
        return True

    def get_available_profiles(self) -> dict:
        """Return available profiles and their key settings."""
        return {
            name: {
                'max_resolution': p.max_resolution,
                'max_fps': p.max_fps,
                'enable_hdr': p.enable_hdr,
                'enable_plantcv': p.enable_plantcv,
            }
            for name, p in PROFILES.items()
        }
