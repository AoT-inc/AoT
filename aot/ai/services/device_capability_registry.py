# coding=utf-8
# @ANCHOR: DEVICE_CAPABILITY_REGISTRY
"""
DeviceCapabilityRegistry — metadata-driven replacement for static PHYSICAL_TOOLS frozenset.

Design ref: 031_FUNCTION_CENTRIC_DESIGN_PROPOSAL.yaml (Section 1)
Law 1: New service file only — no modification to constants.py or physical_control_resolver.py.
Law 2: @ANCHOR: DEVICE_CAPABILITY_REGISTRY registered via incremental_update.py.

Migration contract:
  - PHYSICAL_TOOLS frozenset in constants.py is the DEFAULT fallback.
  - New devices register via DeviceCapabilityProfile.register().
  - is_physical() wraps PHYSICAL_TOOLS so all existing behaviour is preserved.
"""
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ── Enumerations ──────────────────────────────────────────────────────────────

class DeviceClass(str, Enum):
    SWITCH  = "SWITCH"
    PWM     = "PWM"
    VALVE   = "VALVE"
    MOTOR   = "MOTOR"
    PUMP    = "PUMP"
    HEATER  = "HEATER"
    LIGHT   = "LIGHT"
    CUSTOM  = "CUSTOM"


# @ANCHOR: WEATHER_TAG  [2026-03-24 — 001_WEATHER_LOGIC_UPGRADE patch_1]
class WeatherTag(str, Enum):
    """Semantic tag for environmental/weather input devices."""
    WEATHER     = "WEATHER"      # Primary weather station (외부 기상)
    ENVIRONMENT = "ENVIRONMENT"  # In-field environmental sensor (내부 환경)


class PhysicalClass(str, Enum):
    RELAY  = "RELAY"
    GPIO   = "GPIO"
    I2C    = "I2C"
    MQTT   = "MQTT"
    KASA   = "KASA"
    CUSTOM = "CUSTOM"


class RiskLevel(str, Enum):
    LOW      = "LOW"       # display backlight, LED color
    MEDIUM   = "MEDIUM"    # fan, heater, pump
    HIGH     = "HIGH"      # main valve, motor
    CRITICAL = "CRITICAL"  # system power, chemical dosing


class ControlModeType(str, Enum):
    ON_OFF = "ON_OFF"
    PWM    = "PWM"
    VOLUME = "VOLUME"
    RAMP   = "RAMP"
    VALUE  = "VALUE"


# ── Data schemas ──────────────────────────────────────────────────────────────

@dataclass
class ControlMode:
    """Supported control interface for a specific device."""
    mode: ControlModeType
    tool_name: str                          # MCP tool name for this mode
    param_schema: Dict[str, Any] = field(default_factory=dict)
    requires_approval: bool = True
    safety_constraints: Dict[str, Any] = field(default_factory=dict)


@dataclass
class DeviceCapabilityProfile:
    """Runtime metadata record for any physical output device."""
    output_id: str
    device_class: DeviceClass
    control_modes: List[ControlMode] = field(default_factory=list)
    physical_class: PhysicalClass = PhysicalClass.RELAY
    zone_id: Optional[str] = None
    risk_level: RiskLevel = RiskLevel.MEDIUM
    ai_doc_ref: Optional[str] = None

    @property
    def vee_simulation_required(self) -> bool:
        """Derived from risk_level: HIGH/CRITICAL always require VEE simulation."""
        return self.risk_level in (RiskLevel.HIGH, RiskLevel.CRITICAL)

    def get_tool_names(self) -> List[str]:
        """Return all MCP tool names associated with this device."""
        return [cm.tool_name for cm in self.control_modes]


# ── Registry ─────────────────────────────────────────────────────────────────

class DeviceCapabilityRegistry:
    """
    Runtime registry replacing the static PHYSICAL_TOOLS frozenset.
    Keeps an in-process profile store keyed by output_id.
    is_physical() wraps PHYSICAL_TOOLS as the authoritative fallback so
    existing hardware entries remain valid without re-registration.

    @phase active
    @stability stable
    """

    _profiles: Dict[str, DeviceCapabilityProfile] = {}
    # tool_name → set of output_ids that use it (reverse index)
    _tool_index: Dict[str, set] = {}
    # output_id → (WeatherTag value, cache_key) — cache_key = hash(name+notes)
    _weather_cache: Dict[str, tuple] = {}

    _WEATHER_NAME_KEYWORDS = frozenset([
        'weather', '날씨', '기상', '기온', '강수', '풍속',
        '온도', '습도', '기압', 'temperature', 'humidity', 'pressure',
        'wind', 'rain', 'precipitation', 'climate',
    ])
    _ENVIRONMENT_NOTE_KEYWORDS = frozenset([
        'indoor', 'greenhouse', '온실', '내부', '재배', 'cultivation', 'environment',
    ])

    @classmethod
    def register(cls, profile: DeviceCapabilityProfile) -> None:
        """Register or update a DeviceCapabilityProfile."""
        cls._profiles[profile.output_id] = profile
        for tool_name in profile.get_tool_names():
            cls._tool_index.setdefault(tool_name, set()).add(profile.output_id)
        logger.debug(
            "[DeviceCapabilityRegistry] Registered profile output_id=%s class=%s risk=%s",
            profile.output_id, profile.device_class, profile.risk_level,
        )

    @classmethod
    def get_profile(cls, output_id: str) -> Optional[DeviceCapabilityProfile]:
        """Return the profile for output_id, or None if not registered."""
        return cls._profiles.get(output_id)

    @classmethod
    def is_physical(cls, tool_name: Optional[str]) -> bool:
        """
        Return True if tool_name maps to a physical device.

        Evaluation order:
          1. Registered profiles (tool_index) — dynamic, metadata-driven.
          2. PHYSICAL_TOOLS frozenset fallback — preserves legacy behaviour.
        """
        if not tool_name:
            return False
        # 1. Dynamic registry check
        if tool_name in cls._tool_index:
            return True
        # 2. PHYSICAL_TOOLS frozenset fallback (Law 1 — no removal of existing guard)
        try:
            from aot.ai.services.resolvers.constants import PHYSICAL_TOOLS
            return tool_name in PHYSICAL_TOOLS
        except ImportError:
            logger.warning(
                "[DeviceCapabilityRegistry] PHYSICAL_TOOLS unavailable — defaulting to False."
            )
            return False

    @classmethod
    def get_control_mode(
        cls, output_id: str, mode: str
    ) -> Optional[ControlMode]:
        """Return the ControlMode for output_id+mode, or None."""
        profile = cls._profiles.get(output_id)
        if profile is None:
            return None
        for cm in profile.control_modes:
            if cm.mode.value == mode.upper():
                return cm
        return None

    @classmethod
    def get_risk_level(cls, output_id: str) -> str:
        """Return risk level string for output_id, default MEDIUM if not registered."""
        profile = cls._profiles.get(output_id)
        if profile is None:
            return RiskLevel.MEDIUM.value
        return profile.risk_level.value

    @classmethod
    def all_profiles(cls) -> Dict[str, DeviceCapabilityProfile]:
        """Return a snapshot of all registered profiles."""
        return dict(cls._profiles)

    # @ANCHOR: WEATHER_DEVICE_CLASSIFIER  [2026-03-24 — 001_WEATHER_LOGIC_UPGRADE patch_1]
    @classmethod
    def tag_weather_device(
        cls, output_id: str, device_name: str = '', notes: str = ''
    ) -> Optional["WeatherTag"]:
        """
        Classify output_id as WEATHER or ENVIRONMENT using semantic keyword scan.
        Result is cached keyed by hash(device_name + notes); re-evaluated only on change.

        Returns WeatherTag if this is a weather/environmental device, else None.
        """
        cache_key = str(hash(device_name + (notes or '')))
        cached = cls._weather_cache.get(output_id)
        if cached and cached[1] == cache_key:
            tag_val = cached[0]
            return WeatherTag(tag_val) if tag_val else None

        name_lower = device_name.lower()
        notes_lower = (notes or '').lower()
        combined = name_lower + ' ' + notes_lower

        tag: Optional[WeatherTag] = None
        if any(kw in combined for kw in cls._WEATHER_NAME_KEYWORDS):
            # Distinguish: notes hint at indoor/environment → ENVIRONMENT, else WEATHER
            if any(kw in notes_lower for kw in cls._ENVIRONMENT_NOTE_KEYWORDS):
                tag = WeatherTag.ENVIRONMENT
            else:
                tag = WeatherTag.WEATHER

        cls._weather_cache[output_id] = (tag.value if tag else '', cache_key)
        if tag:
            logger.debug(
                "[DeviceCapabilityRegistry] Tagged output_id=%s as %s", output_id, tag
            )
        return tag

    @classmethod
    def is_weather_device(
        cls, output_id: str, device_name: str = '', notes: str = ''
    ) -> bool:
        """Return True if output_id is a weather or environmental measurement device."""
        return cls.tag_weather_device(output_id, device_name, notes) is not None
