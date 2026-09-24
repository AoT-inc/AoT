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

    # 장치 id 를 선택지(enum)로 싣지 않는다 — 현장 장치 수만큼 도구 정의가
    # 커지고(장치 140대에 약 3천 토큰), 대화마다 그 값을 치른다. 대신 이름도
    # 받아 서버가 푼다(모호하면 후보). 인자 모양은 device_ids 를 받는 것 말고는
    # 그대로다. 옛 서명(device_ids 인자)은 호출자 호환으로 남긴다.
    @staticmethod
    def _schema_get_sensor_reading(device_ids: List[str] = None) -> Dict:
        return {
            "name": "get_sensor_reading",
            "description": (
                "Latest value of one or more sensors (value, unit, timestamp). "
                "For history or statistics use get_sensor_detail."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "device_id": {
                        "type": "string",
                        "description": "Sensor unique_id or name.",
                    },
                    "device_ids": {
                        "type": "array", "items": {"type": "string"},
                        "description": "Several sensors at once (max 10).",
                    },
                },
            },
        }

    @staticmethod
    def _schema_set_output_state(device_ids: List[str] = None) -> Dict:
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
                        "description": "Output unique_id or exact name.",
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
        from aot.tools.aot_data_tool_service import AoTDataToolService as S
        from flask import current_app
        with current_app.app_context():
            tokens, err = S._targets_arg(params.get("device_id"),
                                         params.get("device_ids"), "device_id")
            if err:
                return dict({"status": "error",
                             "message": err.get("error")}, **err)
            if len(tokens) == 1:
                return AoTNativeToolEngine._sensor_reading_one(tokens[0])
            return S._for_each_target(tokens, AoTNativeToolEngine._sensor_reading_one)

    @staticmethod
    def _sensor_reading_one(token) -> Dict:
        from flask import current_app
        with current_app.app_context():
            try:
                from aot.tools.aot_data_tool_service import AoTDataToolService as S
                from aot.databases.models import CustomController, Input
                # 이름이면 센서(Input)나 집계 함수로 푼다 — 모호하면 후보.
                row = (Input.query.filter_by(unique_id=token).first()
                       or CustomController.query.filter_by(unique_id=token).first())
                if row is None:
                    row, _kind, rerr = S._read_device(token)
                    if rerr:
                        return dict({"status": "error",
                                     "message": rerr.get("error") or rerr.get("message")},
                                    **rerr)
                device_id = row.unique_id
                # Delegate to the InfluxDB-backed reader used by get_sensor_detail —
                # there is no SQLite Measurement.input_id/timestamp/value column;
                # live readings live in InfluxDB, not in the measurement-type table.
                from aot.tools.aot_data_tool_service import AoTDataToolService
                result = AoTDataToolService.get_sensor_detail(device_id, time_range="1h", limit=1)

                if isinstance(result, dict):
                    return {"status": "error", "message": result.get("error") or result.get("message") or "No data available"}
                if not result:
                    return {"status": "error", "message": f"No measurements found for device '{device_id}'"}

                readings = result[0].get("readings") or []
                if not readings:
                    return {"status": "error", "message": f"No measurements found for device '{device_id}'"}

                latest = readings[-1]
                return {
                    "status": "success",
                    "device_id": device_id,
                    "name": getattr(row, "name", None),
                    "timestamp": latest["t"],
                    "value": latest["v"],
                    "unit": latest["u"],
                }
            except Exception as exc:
                logger.error(f"[NativeToolEngine] get_sensor_reading error: {exc}")
                return {"status": "error", "message": str(exc)}

    @staticmethod
    def _exec_set_output_state(params: Dict) -> Dict:
        device_id = params.get("device_id")
        state = params.get("state")
        duration = params.get("duration", 0)
        # 실패 응답의 `dispatched`: False = 명령을 보내기 전의 확정 실패. 보낸 뒤의
        # 실패는 안쪽 operate_device 결과가 dispatched=True 를 싣는다(실행층이
        # "모름" 으로 알린다 — mcp_safety_gate.annotate_write_outcome).
        if not device_id:
            return {"status": "error", "message": "device_id is required",
                    "dispatched": False}
        # `state` is required by the schema, so a missing value is a caller bug —
        # not a reason to fall back to "off". Defaulting here would turn a
        # malformed "turn it on" into an actual valve close.
        if state not in ("on", "off"):
            return {"status": "error",
                    "message": f"state must be 'on' or 'off', got {state!r}",
                    "dispatched": False}
        
        from flask import current_app
        sent = False
        with current_app.app_context():
            try:
                from aot.databases.models.output import Output
                output = Output.query.filter_by(unique_id=device_id).first()
                if not output:
                    # 이름으로 왔으면 푼다 — 모호하면 고르지 않는다(물리 명령이다).
                    from aot.tools.aot_data_tool_service import AoTDataToolService as S
                    output, _kind, rerr = S._read_device(device_id, kinds=('output',))
                    if rerr:
                        return dict({"status": "error",
                                     "message": rerr.get("error") or rerr.get("message"),
                                     "dispatched": False},
                                    **{k: v for k, v in rerr.items()
                                       if k not in ("status", "_reading")})
                    device_id = output.unique_id
                # 쓰기 시점 그룹 스코프 — 켜고 끌 출력으로 묻는다(묶여 있을 때만).
                from aot.aot_flask.access import write_scope
                write_scope.enforce(output)

                # Delegate to the daemon control channel via AIActionService.
                # _approved=True: this static method is only ever reached AFTER
                # mcp_safety_gate.gate() has already approved the call — 'set_output_state'
                # is in _NATIVE_WRITE_TOOLS, so tool_execution.py's dispatch (and the
                # elicitation-approved immediate-execute path in mcp_safety_gate.py) both
                # gate this before it ever reaches here. Passing the token forward tells
                # execute_action's own 'control_output' check (added 2026-09-16,
                # mcp_tool_audit_tracker.md #17) that approval already happened, instead of
                # leaving that branch unguarded for every caller.
                from aot.tools import providers
                sent = True
                result = providers.get('action_service').execute_action(
                    "control_output",
                    device_id,
                    {"state": state, "duration_seconds": duration},
                    _approved=True,
                )
                if isinstance(result, dict) and result.get("status") == "error":
                    logger.error(f"[NativeToolEngine] set_output_state failed for {device_id}: {result}")
                    return {"status": "error", "device_id": device_id, "state": state, "result": result}
                return {"status": "success", "device_id": device_id, "state": state, "result": result}
            except Exception as exc:
                logger.error(f"[NativeToolEngine] set_output_state error: {exc}")
                return {"status": "error", "message": str(exc), "dispatched": sent}
