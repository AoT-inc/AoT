# coding=utf-8
"""Define hardware-profile-based feature flags and capability gating.

@phase active
@stability stable
@dependency mcp_config
"""
import os
from enum import Enum

class HardwareProfile(str, Enum):
    """Enumerate supported hardware tiers for capability gating.

    @phase active
    @stability stable
    """
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"

PROFILE_DEFINITIONS = {
    HardwareProfile.LOW: {
        "INTENT_ROUTER": True,
        "VEE": False,
        "EKG": False,
        "NOTE_PROMOTION": True,
        "vee_cache_ttl_minutes": None,
        "ekg_window_size": None,
    },
    HardwareProfile.MEDIUM: {
        "INTENT_ROUTER": True,
        "VEE": True,
        "EKG": True,
        "NOTE_PROMOTION": True,
        "vee_cache_ttl_minutes": 30,
        "ekg_window_size": 500,
    },
    HardwareProfile.HIGH: {
        "INTENT_ROUTER": True,
        "VEE": True,
        "EKG": True,
        "NOTE_PROMOTION": True,
        "vee_cache_ttl_minutes": 30,
        "ekg_window_size": 5000,
    },
}

# @ANCHOR: CAPABILITY_MANAGER
class CapabilityManager:
    """Manage feature flags and capability gating based on hardware profile.

    Provide thread-safe read-only access after initialization.

    @phase active
    @stability stable
    @dependency HardwareProfile, mcp_config
    """
    def __init__(self):
        try:
            # Import here to avoid circular dependency if mcp_config imports this (unlikely but safe)
            from aot.config.mcp_config import HARDWARE_PROFILE
            raw_profile = HARDWARE_PROFILE
        except (ImportError, AttributeError):
            raw_profile = os.getenv('HARDWARE_PROFILE', 'LOW')
        
        try:
            self._profile = HardwareProfile(raw_profile.upper())
        except ValueError:
            self._profile = HardwareProfile.LOW
            
        self._flags = PROFILE_DEFINITIONS.get(self._profile, PROFILE_DEFINITIONS[HardwareProfile.LOW])

    def get_profile(self) -> HardwareProfile:
        """Return the active hardware profile."""
        return self._profile

    def is_enabled(self, feature: str) -> bool:
        """Return True if the feature is enabled for the current profile."""
        return bool(self._flags.get(feature, False))

    def get_param(self, key: str):
        """Return a profile-specific parameter value."""
        return self._flags.get(key)

# Singleton instance
capability_manager = CapabilityManager()
