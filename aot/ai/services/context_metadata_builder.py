# coding=utf-8
"""
ContextMetadataBuilder — Phase 2 Philosophy Alignment: Metadata Injection

Responsible for constructing enriched context metadata that surfaces the trust state,
source, and confidence of every parameter value in the master context. Enables the
philosophy principles of Honesty (P1) and Transparency (P3) at the architectural level.

This builder transforms raw context values into a structured metadata format where
each parameter carries:
  - value: The actual parameter value
  - source: Where it came from (domain_kr module, user_note_id, sensor_id, etc.)
  - state: Trust state (system_generated | pending | user_confirmed)
  - confidence: Trust level (HIGH | MEDIUM | LOW)
  - confirmed_by: User ID who confirmed it (or None)
  - confirmed_at: ISO timestamp when confirmed (or None)
"""

import logging
from datetime import datetime
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)


class ContextMetadataBuilder:
    """
    Builds enriched metadata for context values, mapping trust states and sources
    to enable transparent, philosophy-aligned context assembly.

    @phase active
    @stability stable
    """

    @staticmethod
    def build(
        facility_id: str,
        raw_context_dict: Dict[str, Any],
        domain_module_data: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Transform raw context into metadata-enriched format.

        Args:
            facility_id: The facility this context is for
            raw_context_dict: The raw aggregated context (spatial_hierarchy, sensor_readings, etc.)
            domain_module_data: The domain KR module data (operational_state, thresholds, etc.)
                                from DomainContextLoader.load_active_module()

        Returns:
            dict with structure:
            {
              "per_parameter": {
                "<parameter_name>": {
                  "value": <value>,
                  "source": "<source_identifier>",
                  "state": "system_generated" | "pending" | "user_confirmed",
                  "confidence": "HIGH" | "MEDIUM" | "LOW",
                  "confirmed_by": <user_id or None>,
                  "confirmed_at": <ISO timestamp or None>
                }
              },
              "metadata_version": "1.0",
              "generated_at": <ISO timestamp>
            }

        Philosophy Alignment:
            - P1_Honesty: Each parameter explicitly declares its trust state and confidence.
                         system_generated values are flagged as LOW confidence (domain baseline).
                         user_confirmed values are flagged as HIGH confidence (facility-specific).
            - P3_Transparency: source field traces every value back to its origin.
                             Users can follow the chain from AI output back to raw source.
        """
        metadata = {
            "per_parameter": {},
            "metadata_version": "1.0",
            "generated_at": datetime.utcnow().isoformat() + "Z",
        }

        # Extract and enrich context values from domain module
        if domain_module_data:
            operational_state = domain_module_data.get("operational_state", {})
            if operational_state:
                _extract_operational_state_metadata(
                    operational_state,
                    metadata["per_parameter"],
                )

        # Extract metadata from raw sensor readings
        if raw_context_dict:
            if "sensor_readings" in raw_context_dict:
                _extract_sensor_metadata(
                    raw_context_dict["sensor_readings"],
                    metadata["per_parameter"],
                )

            if "spatial_hierarchy" in raw_context_dict:
                _extract_spatial_metadata(
                    raw_context_dict["spatial_hierarchy"],
                    metadata["per_parameter"],
                )

        # Extract metadata from Notes with context_state field (Phase 1 schema)
        try:
            from aot.databases.models import Notes
            from aot.utils.time_utils import utc_now
            from flask_login import current_user

            notes = Notes.query.filter_by(
                facility_id=facility_id, is_archived=False
            ).all()

            for note in notes:
                context_state = getattr(note, "context_state", "system_generated")
                parameter_name = note.parameter or f"note_{note.unique_id}"

                confidence = "HIGH" if context_state == "user_confirmed" else "LOW"
                confirmed_by = None
                confirmed_at = None

                if context_state == "user_confirmed":
                    confirmed_by = current_user.id if current_user else None
                    confirmed_at = (
                        note.created_at.isoformat() + "Z"
                        if note.created_at
                        else None
                    )

                metadata["per_parameter"][parameter_name] = {
                    "value": note.value,
                    "source": f"note_id:{note.unique_id}",
                    "state": context_state,
                    "confidence": confidence,
                    "confirmed_by": confirmed_by,
                    "confirmed_at": confirmed_at,
                }

        except Exception as exc:
            logger.warning(
                "ContextMetadataBuilder: Failed to extract Notes metadata: %s", exc
            )

        # Extract metadata from AIContextRecord (Phase 1 schema)
        try:
            from aot.databases.models import AIContextRecord

            records = AIContextRecord.query.filter_by(
                facility_id=facility_id
            ).all()

            for record in records:
                parameter_name = record.parameter_name
                context_state = record.context_state or "system_generated"

                confidence_map = {
                    "system_generated": "LOW",
                    "pending": "LOW",
                    "user_confirmed": "HIGH",
                }
                confidence = confidence_map.get(context_state, "LOW")

                metadata["per_parameter"][parameter_name] = {
                    "value": record.value,
                    "source": record.source or "ai_context_record",
                    "state": context_state,
                    "confidence": confidence,
                    "confirmed_by": record.confirmed_by,
                    "confirmed_at": (
                        record.confirmed_at.isoformat() + "Z"
                        if record.confirmed_at
                        else None
                    ),
                }

        except Exception as exc:
            logger.warning(
                "ContextMetadataBuilder: Failed to extract AIContextRecord metadata: %s",
                exc,
            )

        return metadata


def _extract_operational_state_metadata(
    operational_state: Dict[str, Any],
    per_parameter: Dict[str, Any],
) -> None:
    """
    Extract metadata from domain module's operational_state section.

    All values from domain_kr modules are tagged as:
      - source: "domain_kr"
      - state: "system_generated"
      - confidence: "LOW"

    This reflects P1_Honesty: domain defaults are unconfirmed baselines.
    """
    if not operational_state:
        return

    # Top-level state value
    if "value" in operational_state:
        per_parameter["operational_state"] = {
            "value": operational_state["value"],
            "source": "domain_kr",
            "state": "system_generated",
            "confidence": "LOW",
            "confirmed_by": None,
            "confirmed_at": None,
        }

    # Growth stage (if present)
    if "growth_stage" in operational_state:
        per_parameter["growth_stage"] = {
            "value": operational_state["growth_stage"],
            "source": "domain_kr:growth_stage_resolver",
            "state": "system_generated",
            "confidence": "MEDIUM",  # Slightly higher: based on crop type + time
            "confirmed_by": None,
            "confirmed_at": None,
        }

    # Days after planting
    if "days_after_planting" in operational_state:
        per_parameter["days_after_planting"] = {
            "value": operational_state["days_after_planting"],
            "source": "domain_kr:growth_stage_resolver",
            "state": "system_generated",
            "confidence": "HIGH",  # High: based on planting_date (potentially user-confirmed)
            "confirmed_by": None,
            "confirmed_at": None,
        }

    # Optimal ranges
    if "optimal_ranges" in operational_state:
        for param_name, param_range in operational_state[
            "optimal_ranges"
        ].items():
            per_parameter[f"optimal_range_{param_name}"] = {
                "value": param_range,
                "source": "domain_kr:optimal_ranges",
                "state": "system_generated",
                "confidence": "LOW",  # Domain default, not facility-specific
                "confirmed_by": None,
                "confirmed_at": None,
            }

    # Cultivation context
    if "cultivation_context" in operational_state:
        per_parameter["cultivation_context"] = {
            "value": operational_state["cultivation_context"],
            "source": "domain_kr:EXT-KR-02:nongsaro",
            "state": "system_generated",
            "confidence": "LOW",
            "confirmed_by": None,
            "confirmed_at": None,
        }

    # Pest alerts context
    if "pest_alerts_context" in operational_state:
        per_parameter["pest_alerts_context"] = {
            "value": operational_state["pest_alerts_context"],
            "source": "domain_kr:EXT-KR-03:pest_management",
            "state": "system_generated",
            "confidence": "MEDIUM",  # Alert system is curated, not fully facility-specific
            "confirmed_by": None,
            "confirmed_at": None,
        }


def _extract_sensor_metadata(
    sensor_readings: Any,
    per_parameter: Dict[str, Any],
) -> None:
    """
    Extract metadata from live sensor readings.

    Sensor values are tagged as:
      - source: "sensor_<device_id>"
      - state: "system_generated"
      - confidence: "HIGH" (if recent and calibrated)

    This reflects P3_Transparency: users can trace live data back to sensors.
    """
    if not sensor_readings:
        return

    if not isinstance(sensor_readings, list):
        return

    for sensor in sensor_readings:
        if not isinstance(sensor, dict):
            continue

        device_name = sensor.get("name") or sensor.get("device") or "unknown"
        device_id = sensor.get("device_id") or "unknown"
        readings = sensor.get("readings", [])

        if readings:
            # Summarize live readings
            if isinstance(readings, dict):
                # Already summarized
                for key, value in readings.items():
                    param_name = f"sensor_{device_name}_{key}"
                    per_parameter[param_name] = {
                        "value": value,
                        "source": f"sensor:{device_id}",
                        "state": "system_generated",
                        "confidence": "HIGH",  # Live sensor data is high confidence
                        "confirmed_by": None,
                        "confirmed_at": None,
                    }
            elif isinstance(readings, list) and readings:
                # List of raw readings: extract latest
                latest = readings[-1] if readings else None
                if latest:
                    value = (
                        latest.get("value")
                        or latest.get("_value")
                        or latest.get("reading")
                    )
                    param_name = f"sensor_{device_name}"
                    per_parameter[param_name] = {
                        "value": value,
                        "source": f"sensor:{device_id}",
                        "state": "system_generated",
                        "confidence": "HIGH",
                        "confirmed_by": None,
                        "confirmed_at": None,
                    }


def _extract_spatial_metadata(
    spatial_hierarchy: Any,
    per_parameter: Dict[str, Any],
) -> None:
    """
    Extract metadata from spatial hierarchy nodes.

    Hierarchy structure and relationships are tagged as:
      - source: "spatial_hierarchy"
      - state: "system_generated"
      - confidence: "HIGH" (structural information, user-defined in setup)

    This reflects P3_Transparency: spatial context is traceable.
    """
    if not spatial_hierarchy:
        return

    if not isinstance(spatial_hierarchy, list):
        spatial_hierarchy = [spatial_hierarchy]

    def extract_from_node(node, path=""):
        if not isinstance(node, dict):
            return

        node_type = node.get("type") or "unknown"
        node_id = node.get("id") or "unknown"
        current_path = f"{path}/{node_type}:{node_id}" if path else f"{node_type}:{node_id}"

        # Extract structural metadata
        if "name" in node:
            per_parameter[f"spatial_name_{node_id}"] = {
                "value": node["name"],
                "source": "spatial_hierarchy",
                "state": "system_generated",
                "confidence": "HIGH",  # User-defined during setup
                "confirmed_by": None,
                "confirmed_at": None,
            }

        if "geometry" in node:
            per_parameter[f"spatial_geometry_{node_id}"] = {
                "value": (
                    {"type": node["geometry"].get("type", "unknown")}
                    if isinstance(node["geometry"], dict)
                    else "unknown"
                ),
                "source": "spatial_hierarchy",
                "state": "system_generated",
                "confidence": "HIGH",
                "confirmed_by": None,
                "confirmed_at": None,
            }

        # Recurse into children
        children = node.get("children")
        if children and isinstance(children, list):
            for child in children:
                extract_from_node(child, current_path)

    for node in spatial_hierarchy:
        extract_from_node(node)
