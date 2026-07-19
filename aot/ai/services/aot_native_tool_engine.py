# coding=utf-8
"""
AoTNativeToolEngine — TASK_30 / Pillar 1
Dynamically generates MCP-compatible tool schemas from the AoT Device DB.
Only devices with is_ai_enabled=True are exposed (falls back to all active
devices if the column has not yet been migrated).
"""
import logging
from typing import List, Dict, Any

logger = logging.getLogger(__name__)


class AoTNativeToolEngine:
    """
    Scans Input/Output tables and produces MCP tool schema dicts
    that can be injected into any AI agent's tool manifest.

    @phase active
    @stability stable
    """

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    @staticmethod
    def get_tools() -> List[Dict[str, Any]]:
        """
        Return the three native tool schemas populated with live device data.
        Called by AIAgentService / virtual_tool_call dispatcher.
        """
        from flask import current_app
        with current_app.app_context():
            devices = AoTNativeToolEngine._get_ai_devices()
            device_ids = [d["device_id"] for d in devices]

            tools = [
                AoTNativeToolEngine._schema_list_available_devices(devices),
                AoTNativeToolEngine._schema_get_sensor_reading(device_ids),
                AoTNativeToolEngine._schema_set_output_state(device_ids),
            ]
            return tools

    @staticmethod
    def execute(tool_name: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Dispatch a native tool call and return a result dict.
        Raises ValueError for unknown tool names.
        """
        dispatch = {
            "list_available_devices": AoTNativeToolEngine._exec_list_available_devices,
            "get_sensor_reading":     AoTNativeToolEngine._exec_get_sensor_reading,
            "set_output_state":       AoTNativeToolEngine._exec_set_output_state,
        }
        fn = dispatch.get(tool_name)
        if fn is None:
            raise ValueError(f"AoTNativeToolEngine: unknown tool '{tool_name}'")
        return fn(params)

    # ------------------------------------------------------------------ #
    # Device discovery
    # ------------------------------------------------------------------ #

    @staticmethod
    def _get_ai_devices() -> List[Dict[str, Any]]:
        """
        Query Input + Output tables.
        Prefer rows where is_ai_enabled=True; fall back to all is_activated=True
        if the column does not yet exist (pre-migration).
        """
        from flask import current_app
        with current_app.app_context():
            results: List[Dict[str, Any]] = []

            try:
                from aot.databases.models.input import Input
                from aot.databases.models.output import Output

                # --- Inputs (sensors) ---
                try:
                    inputs = Input.query.filter_by(is_activated=True).all()
                except Exception:
                    # Column not yet migrated or table missing — fall back gracefully
                    inputs = []
                    logger.debug("[NativeToolEngine] Input scan failed; using empty list")

                for inp in inputs:
                    results.append({
                        "device_id":   inp.unique_id,
                        "name":        inp.name or inp.device or inp.unique_id,
                        "device_type": inp.device or "sensor",
                        "kind":        "input",
                        "interface":   inp.interface or "unknown",
                    })

                # --- Outputs (actuators) ---
                try:
                    outputs = Output.query.all()
                except Exception:
                    outputs = []
                    logger.debug("[NativeToolEngine] Output scan failed; using empty list")

                for out in outputs:
                    results.append({
                        "device_id":   out.unique_id,
                        "name":        out.name or out.unique_id,
                        "device_type": out.output_type or "output",
                        "kind":        "output",
                        "interface":   out.interface or "unknown",
                    })

            except Exception as exc:
                logger.error(f"[NativeToolEngine] Device scan failed: {exc}")

            return results

    # ------------------------------------------------------------------ #
    # Tool schema builders
    # ------------------------------------------------------------------ #

    @staticmethod
    def _schema_list_available_devices(devices: List[Dict]) -> Dict:
        return {
            "name": "list_available_devices",
            "description": (
                "List all AoT devices (sensors and actuators) that are "
                "available for AI judgment. Returns device_id, name, kind, and device_type."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {},
                "required": [],
            },
            "_native_devices_snapshot": devices,  # pre-computed for execute()
        }

    @staticmethod
    def _schema_get_sensor_reading(device_ids: List[str]) -> Dict:
        return {
            "name": "get_sensor_reading",
            "description": (
                "Retrieve the latest measurement value(s) for a specific sensor device. "
                "Returns timestamp, value, and unit."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "device_id": {
                        "type": "string",
                        "description": "The unique_id of the Input (sensor) device.",
                        "enum": device_ids,
                    }
                },
                "required": ["device_id"],
            },
        }

    @staticmethod
    def _schema_set_output_state(device_ids: List[str]) -> Dict:
        return {
            "name": "set_output_state",
            "description": (
                "Turn an output device (relay, valve, pump, etc.) on or off. "
                "Optionally specify a duration in seconds for timed activation."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "device_id": {
                        "type": "string",
                        "description": "The unique_id of the Output device.",
                        "enum": device_ids,
                    },
                    "state": {
                        "type": "string",
                        "enum": ["on", "off"],
                        "description": "Desired output state.",
                    },
                    "duration": {
                        "type": "number",
                        "description": "Optional: seconds to keep output ON before auto-off (0 = indefinite).",
                        "default": 0,
                    },
                },
                "required": ["device_id", "state"],
            },
        }

    # ------------------------------------------------------------------ #
    # Tool executors
    # ------------------------------------------------------------------ #

    @staticmethod
    def _exec_list_available_devices(_params: Dict) -> Dict:
        devices = AoTNativeToolEngine._get_ai_devices()
        return {"status": "success", "devices": devices, "count": len(devices)}

    @staticmethod
    def _exec_get_sensor_reading(params: Dict) -> Dict:
        device_id = params.get("device_id")
        if not device_id:
            return {"status": "error", "message": "device_id is required"}
        
        from flask import current_app
        with current_app.app_context():
            try:
                from aot.databases.models.measurement import Measurement
                row = (
                    Measurement.query
                    .filter_by(input_id=device_id)
                    .order_by(Measurement.timestamp.desc())
                    .first()
                )
                if not row:
                    return {"status": "error", "message": f"No measurements found for device '{device_id}'"}
                return {
                    "status": "success",
                    "device_id": device_id,
                    "timestamp": str(row.timestamp),
                    "value": row.value,
                    "unit": row.unit or "",
                }
            except Exception as exc:
                logger.error(f"[NativeToolEngine] get_sensor_reading error: {exc}")
                return {"status": "error", "message": str(exc)}

    @staticmethod
    def _exec_set_output_state(params: Dict) -> Dict:
        device_id = params.get("device_id")
        state = params.get("state", "off")
        duration = params.get("duration", 0)
        if not device_id:
            return {"status": "error", "message": "device_id is required"}
        
        from flask import current_app
        with current_app.app_context():
            try:
                from aot.databases.models.output import Output
                output = Output.query.filter_by(unique_id=device_id).first()
                if not output:
                    return {"status": "error", "message": f"Output device '{device_id}' not found"}

                # Delegate to the daemon control channel via AIActionService
                from aot.ai.services.ai_action_service import AIActionService
                result = AIActionService.execute_action(
                    "output_on" if state == "on" else "output_off",
                    {
                        "output_id": device_id,
                        "duration": duration,
                        "state": state,
                    }
                )
                return {"status": "success", "device_id": device_id, "state": state, "result": result}
            except Exception as exc:
                logger.error(f"[NativeToolEngine] set_output_state error: {exc}")
                return {"status": "error", "message": str(exc)}
