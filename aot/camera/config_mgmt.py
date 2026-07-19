import json
import os
import logging
from typing import Dict, Any, Optional
import dataclasses
from .models import CameraConfig, BackendType

logger = logging.getLogger(__name__)

class ConfigManager:
    """Manage persistence, retrieval, and preset application for camera configurations.

    @phase active
    @stability stable
    @dependency CameraConfig, BackendType
    """
    
    def __init__(self, config_path: str = "configs/cameras.json"):
        self.config_path = config_path
        self._configs: Dict[str, CameraConfig] = {}
        self._presets: Dict[str, Dict[str, Any]] = self._init_presets()
        
        self.load_configs()

    def get_config(self, camera_id: str) -> Optional[CameraConfig]:
        """Get configuration for a specific camera."""
        return self._configs.get(camera_id)

    def save_config(self, camera_id: str, config: CameraConfig) -> None:
        """Store and persist a camera configuration."""
        self._configs[camera_id] = config
        self.persist()
        logger.info(f"Configuration saved for {camera_id}")

    def load_configs(self) -> None:
        """Load configurations from disk."""
        if not os.path.exists(self.config_path):
            logger.debug("No camera configuration file found.")
            return

        try:
            with open(self.config_path, 'r') as f:
                data = json.load(f)
                for cid, cdata in data.items():
                    if 'backend_type' in cdata and isinstance(cdata['backend_type'], str):
                        cdata['backend_type'] = BackendType(cdata['backend_type'])
                    self._configs[cid] = CameraConfig(**cdata)
        except Exception as e:
            logger.error(f"Error loading camera configurations: {e}")

    def persist(self) -> None:
        """Write all current configurations to disk."""
        os.makedirs(os.path.dirname(self.config_path), exist_ok=True)
        try:
            # Convert configs to dicts for JSON
            data = {cid: self._serialize_config(config) for cid, config in self._configs.items()}
            with open(self.config_path, 'w') as f:
                json.dump(data, f, indent=4)
        except Exception as e:
            logger.error(f"Error persisting camera configurations: {e}")

    def get_preset(self, name: str) -> Optional[Dict[str, Any]]:
        """Retrieve a predefined setting preset."""
        return self._presets.get(name.lower())

    def list_configs(self) -> Dict[str, CameraConfig]:
        """Return all stored configurations."""
        return dict(self._configs)

    def delete_config(self, camera_id: str) -> bool:
        """Delete a camera configuration."""
        if camera_id in self._configs:
            del self._configs[camera_id]
            self.persist()
            logger.info(f"Configuration deleted for {camera_id}")
            return True
        return False

    def apply_preset(self, camera_id: str, preset_name: str) -> Optional[CameraConfig]:
        """Apply a preset to an existing or new camera configuration."""
        preset = self.get_preset(preset_name)
        if not preset:
            return None

        current_config = self.get_config(camera_id)
        if current_config:
            config_dict = dataclasses.asdict(current_config)
            config_dict.update(preset)
            if isinstance(config_dict.get('backend_type'), str):
                config_dict['backend_type'] = BackendType(config_dict['backend_type'])
            new_config = CameraConfig(**config_dict)
        else:
            new_config = CameraConfig(
                unique_id=camera_id,
                name=preset_name,
                backend_type=BackendType.OPENCV,
                **preset
            )

        self.save_config(camera_id, new_config)
        return new_config

    def _init_presets(self) -> Dict[str, Dict[str, Any]]:
        return {
            "indoor": {"resolution": (1280, 720), "fps": 15, "brightness": 0.5},
            "outdoor": {"resolution": (1920, 1080), "fps": 30, "brightness": 0.6},
            "security": {"resolution": (1280, 720), "fps": 5, "enable_noise_reduction": True}
        }

    def _serialize_config(self, config: CameraConfig) -> Dict[str, Any]:
        """Helper to convert CameraConfig to JSON-serializable dict."""
        # Simple implementation, handles basic types
        d = vars(config).copy()
        if isinstance(d.get('backend_type'), BackendType):
            d['backend_type'] = d['backend_type'].value
        return d
