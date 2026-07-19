"""
AI Context Assembler for Devices

Aggregates device context data from multiple sources for display in the AI Context Panel.
Provides device-type-specific context assembly methods.
"""

from sqlalchemy.orm import Session
from typing import Dict, Any, Optional


class DeviceAIContextAssembler:
    """
    Assembles AI context data for different device types.

    @phase active
    @stability stable
    @dependency Input, Output, CustomController, GeoShape, AIAgent
    """

    def __init__(self, db: Session):
        """Initialize assembler with database session."""
        self.db = db

    def get_device_context(self, device_id: str) -> Optional[Dict[str, Any]]:
        """
        Get AI context for a device by its ID.
        Routes to type-specific assembler based on device type.

        Args:
            device_id: Unique device identifier

        Returns:
            Dictionary containing device identity and type-specific context sections.
            Returns None if device not found.
        """
        # Import device models
        from aot.databases.models import (
            Input, Output, CustomController, GeoShape, AIAgent
        )

        # Try each device type
        input_device = self.db.query(Input).filter(Input.unique_id == device_id).first()
        if input_device:
            return self._assemble_input_context(input_device)

        output_device = self.db.query(Output).filter(Output.unique_id == device_id).first()
        if output_device:
            return self._assemble_output_context(output_device)

        function_device = self.db.query(CustomController).filter(
            CustomController.unique_id == device_id
        ).first()
        if function_device:
            return self._assemble_function_context(function_device)

        geo_device = self.db.query(GeoShape).filter(
            GeoShape.unique_id == device_id
        ).first()
        if geo_device:
            return self._assemble_geo_context(geo_device)

        ai_device = self.db.query(AIAgent).filter(
            AIAgent.unique_id == device_id
        ).first()
        if ai_device:
            return self._assemble_ai_agent_context(ai_device)

        return None

    def _assemble_input_context(self, input_device) -> Dict[str, Any]:
        """Assemble context for Input (sensor) devices."""
        return {
            "device_type": "input_sensor",
            "device_identity": {
                "id": input_device.unique_id,
                "name": input_device.name,
                "type": input_device.device,
                "location": {
                    "latitude": input_device.latitude,
                    "longitude": input_device.longitude,
                    "location_source": input_device.location_source
                }
            },
            "device_metadata": {
                "interface": getattr(input_device, 'interface', None),
                "measurement_type": getattr(input_device, 'measurement', None),
                "period": getattr(input_device, 'period', None),
            },
            "ai_perception": {
                "description": f"Input sensor '{input_device.name}' of type {input_device.device}",
                "enabled_for_ai": True
            }
        }

    def _assemble_output_context(self, output_device) -> Dict[str, Any]:
        """Assemble context for Output (actuator/controller) devices."""
        return {
            "device_type": "output_actuator",
            "device_identity": {
                "id": output_device.unique_id,
                "name": output_device.name,
                "type": output_device.output_type,
                "location": {
                    "latitude": output_device.latitude,
                    "longitude": output_device.longitude,
                    "location_source": output_device.location_source
                }
            },
            "device_metadata": {
                "interface": getattr(output_device, 'interface', None),
                "period": getattr(output_device, 'period', None),
                "pin": getattr(output_device, 'pin', None),
            },
            "ai_perception": {
                "description": f"Output actuator '{output_device.name}' of type {output_device.output_type}",
                "enabled_for_ai": True
            }
        }

    def _assemble_function_context(self, function_device) -> Dict[str, Any]:
        """Assemble context for Function (logic controller) devices."""
        return {
            "device_type": "function_controller",
            "device_identity": {
                "id": function_device.unique_id,
                "name": function_device.name,
                "type": function_device.device,
                "location": {
                    "latitude": getattr(function_device, 'latitude', None),
                    "longitude": getattr(function_device, 'longitude', None),
                    "location_source": getattr(function_device, 'location_source', None)
                }
            },
            "device_metadata": {
                "function_type": function_device.function_type,
                "is_activated": getattr(function_device, 'is_activated', False),
            },
            "ai_perception": {
                "description": f"Function controller '{function_device.name}' of type {function_device.device}",
                "enabled_for_ai": True
            }
        }

    def _assemble_geo_context(self, geo_device) -> Dict[str, Any]:
        """Assemble context for GIS/Geo Input devices."""
        return {
            "device_type": "gis_input",
            "device_identity": {
                "id": geo_device.unique_id,
                "name": geo_device.name,
                "type": "gis_shape",
                "location": {
                    "type": getattr(geo_device, 'type', None),
                }
            },
            "device_metadata": {
                "shape_type": getattr(geo_device, 'type', None),
                "options": getattr(geo_device, 'options', None),
            },
            "ai_perception": {
                "description": f"GIS spatial input '{geo_device.name}'",
                "enabled_for_ai": True
            }
        }

    def _assemble_ai_agent_context(self, ai_agent) -> Dict[str, Any]:
        """Assemble context for AI Agent devices."""
        return {
            "device_type": "ai_agent",
            "device_identity": {
                "id": ai_agent.unique_id,
                "name": ai_agent.name,
                "type": "ai_agent",
            },
            "device_metadata": {
                "agent_type": getattr(ai_agent, 'agent_type', None),
                "endpoint": getattr(ai_agent, 'endpoint', None),
                "is_active": getattr(ai_agent, 'is_active', False),
            },
            "ai_perception": {
                "description": f"AI Agent '{ai_agent.name}'",
                "enabled_for_ai": True
            }
        }
