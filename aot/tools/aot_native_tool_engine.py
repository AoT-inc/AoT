# coding=utf-8
"""
AoTNativeToolEngine — TASK_30 / Pillar 1
Dynamically generates MCP-compatible tool schemas from the AoT Device DB.
Devices whose 'Include in AI judgment' toggle is off (is_ai_enabled=False) are
not exposed (`device_resolver.ai_excluded` — the one test every AI tool uses).
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

    #: 도구 스키마에 싣지 않는 처리기 인자 — 도메인 표면(find.controllable)만 쓴다. 스키마에 싣지 않는 것은
    #: 카탈로그 토큰을 늘리지 않으려는 것이고, 명부 계약 검사가 이 이름을 맞는 인자로 인정한다.
    HANDLER_PARAMS = {
        # control.output_timed — 켜는 시간은 control.device_set 과 같은 이름(duration_seconds)으로 받는다.
        'set_output_state': frozenset({'duration_seconds'}),
        'list_available_devices': frozenset(
            {'brief', 'detail', 'query', 'kind', 'place_id', 'limit', 'offset'}),
        # measure.latest(장치 대상)가 항목·기간을 넘긴다 — 스키마에는 안 싣는다(토큰).
        'get_sensor_reading': frozenset({'measurement_type', 'time_range'}),
    }

    #: find.controllable 한 쪽의 건수.
    CONTROLLABLE_PAGE = 40

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
        Query Input + Output tables — active inputs and all outputs, minus the
        ones switched out of AI judgment (`device_resolver.ai_excluded`).
        """
        from flask import current_app
        with current_app.app_context():
            results: List[Dict[str, Any]] = []

            try:
                from aot.databases.models.input import Input
                from aot.databases.models.output import Output
                from aot.services.resolvers.device_resolver import ai_excluded

                # --- Inputs (sensors) ---
                try:
                    inputs = Input.query.filter_by(is_activated=True).all()
                except Exception:
                    # Column not yet migrated or table missing — fall back gracefully
                    inputs = []
                    logger.debug("[NativeToolEngine] Input scan failed; using empty list")

                for inp in inputs:
                    if ai_excluded(inp):
                        continue
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
                    if ai_excluded(out):
                        continue
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
    def _exec_list_available_devices(params: Dict) -> Dict:
        """전체 목록(인앱 AI·예전 소비자) — `brief` 를 주면 도메인 표면의 쪽 나눈 요약(`_controllable_brief`)."""
        devices = AoTNativeToolEngine._get_ai_devices()
        if not (params or {}).get("brief"):
            return {"status": "success", "devices": devices, "count": len(devices)}
        return AoTNativeToolEngine._controllable_brief(devices, params)

    #: 종류 낱말 → 목록의 kind. 모델이 쓰는 말을 몇 가지 받는다.
    _KIND_WORDS = {"input": "input", "inputs": "input", "sensor": "input", "sensors": "input",
                   "output": "output", "outputs": "output", "actuator": "output",
                   "actuators": "output"}

    @staticmethod
    def _norm_name(text) -> str:
        import re
        return re.sub(r"[\s_\-]+", "", str(text or "").lower())

    @staticmethod
    def _controllable_brief(devices: List[Dict[str, Any]], params: Dict) -> Dict:
        """find.controllable — 이름·종류 표를 40건씩. 출력(켜고 끄는 것)을 먼저, 켜진 입력(센서)은 뒤에.

        id·인터페이스는 기본에서 뺀다: 쓰기 흐름은 이름으로 대상을 풀고(`targets.resolve`) 이 응답의 id 를 읽지
        않는다. 이름이 겹치는 장치만 구별할 id 를 달고, `detail` 이면 예전 칸(device_id·device_type·kind·interface)
        그대로 쪽만 나눠 준다. 좁히는 길: `query`(이름·종류 낱말, 모두 들어야 함) · `kind` · 장소 대상(`place_id`)."""
        N = AoTNativeToolEngine
        wanted_kind = params.get("kind")
        if wanted_kind not in (None, ""):
            wanted_kind = N._KIND_WORDS.get(str(wanted_kind).strip().lower())
            if wanted_kind is None:
                return {"status": "error",
                        "message": "kind is 'output' (things that switch) or 'input' (live sensors)."}
        rows = list(devices)
        place_id = params.get("place_id")
        if place_id:
            members = N._place_members(place_id)
            if members is None:
                return {"status": "not_found",
                        "message": "No place with that id, so no devices were listed."}
            rows = [d for d in rows if d["device_id"] in members]
        if wanted_kind:
            rows = [d for d in rows if d["kind"] == wanted_kind]
        tokens = [N._norm_name(t) for t in str(params.get("query") or "").split() if t.strip()]
        if tokens:
            rows = [d for d in rows
                    if all(t in N._norm_name(d["name"]) or t in N._norm_name(d["device_type"])
                           for t in tokens)]
        rows.sort(key=lambda d: d["kind"] != "output")        # 안정 정렬: 출력 먼저, 안은 예전 차례 그대로
        counts: Dict[str, int] = {}
        for d in rows:
            counts[d["kind"]] = counts.get(d["kind"], 0) + 1
        total = len(rows)
        try:
            limit = int(params.get("limit")) if params.get("limit") not in (None, "") else N.CONTROLLABLE_PAGE
        except (TypeError, ValueError):
            limit = N.CONTROLLABLE_PAGE
        try:
            offset = max(0, int(params.get("offset") or 0))
        except (TypeError, ValueError):
            offset = 0
        limit = max(1, limit)
        page = rows[offset:offset + limit]
        nxt: Dict[str, Any] = {}
        more = offset + len(page) < total
        if more:
            parts = ["offset=%d" % (offset + len(page))]
            parts += ["%s=%r" % (k, params[k]) for k in ("query", "kind") if params.get(k)]
            if place_id:
                parts.append("same target")
            nxt["call"] = "find(op='controllable', %s)" % ", ".join(parts)
            nxt["why"] = "showing %d-%d of %d" % (offset + 1, offset + len(page), total)
        nxt["more"] = "detail=true: one entry per device with device_id and interface"
        out: Dict[str, Any] = {"status": "success", "next": nxt, "total": total, "counts": counts}
        if offset or more:
            out["page"] = {"offset": offset, "shown": len(page)}
        if not (place_id or wanted_kind or tokens):
            # find.devices 의 합과 다른 까닭 — 켜고 끄는 출력과 켜진 센서만 센다.
            out["scope"] = ("outputs and switched-on sensors only; switched-off sensors, cameras and complex "
                            "devices are not counted here - search_devices lists every device")
        if params.get("detail"):
            out["devices"] = page
            return out
        names: Dict[str, int] = {}
        for d in rows:
            key = str(d["name"]).strip().lower()
            names[key] = names.get(key, 0) + 1
        out["columns"] = ["name", "kind", "type", "id (only when the name repeats)"]
        out["rows"] = [[d["name"], d["kind"], d["device_type"]]
                       + ([d["device_id"]] if names[str(d["name"]).strip().lower()] > 1 else [])
                       for d in page]
        return out

    @staticmethod
    def _place_members(place_id):
        """장소(대지·구역·시설) id → 그 안 장치 id 집합. 모르는 id 면 None. 시설 행 id 도 받는다."""
        try:
            from aot.space import device_membership as dm
            from aot.databases.models import GeoFacility, GeoShape
            uid = str(place_id)
            fac = GeoFacility.query.filter_by(unique_id=uid).first()
            if fac is not None and getattr(fac, "shape_uuid", None):
                uid = fac.shape_uuid
            if GeoShape.query.filter_by(unique_id=uid).first() is None:
                return None
            members = dm.place_members(uid)
            return set(members) if members is not None else None
        except Exception as exc:                            # noqa: BLE001
            logger.debug("[NativeToolEngine] place members failed: %s", exc)
            return None

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
            one = lambda t: AoTNativeToolEngine._sensor_reading_one(          # noqa: E731
                t, params.get("measurement_type"), params.get("time_range"))
            if len(tokens) == 1:
                return one(tokens[0])
            return S._for_each_target(tokens, one)

    #: 측정 항목을 말하지 않았을 때 대표값으로 먼저 고르는 주 채널(이름에 들어 있는 낱말, 앞이 우선).
    _PRIMARY_CHANNELS = ("temperature", "humidity", "moisture", "co2", "illuminance", "ph")

    @staticmethod
    def _representative_channel(channels, measurement=None):
        """채널들 → 대표값 하나. 항목을 말했으면 첫 채널(이미 그 항목만 읽었다), 아니면 주 채널 먼저
        (배터리·신호 세기가 대표값이 되지 않게) — 주 채널이 없으면 첫 채널."""
        if not measurement:
            for word in AoTNativeToolEngine._PRIMARY_CHANNELS:
                for c in channels:
                    if word in str(c.get("measurement") or "").lower():
                        return c
        return channels[0]

    @staticmethod
    def _sensor_reading_one(token, measurement=None, time_range=None) -> Dict:
        from flask import current_app
        with current_app.app_context():
            try:
                from aot.tools.aot_data_tool_service import AoTDataToolService as S
                # id·이름 모두 공용 해석(_read_device)으로 푼다 — 모호하면 후보,
                # 'AI 판단에 포함' 을 끈 장치면 그 이유(예전에는 id 로 오면 해석을
                # 건너뛰어 그 판정도 건너뛰었다).
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
                result = AoTDataToolService.get_sensor_detail(
                    device_id, sensor_type=measurement or None,
                    time_range=time_range or "1h", limit=1)

                if isinstance(result, dict):
                    # 값이 없는 이유와 다음 걸음 — 그냥 "No data" 면 같은 호출을 되풀이한다(2026-11-03).
                    msg = result.get("error") or result.get("message") or "No data available"
                    out = dict({k: result[k] for k in ("reason_code",) if k in result},
                               status="error", message=msg)
                    if str(msg).startswith("No data"):
                        out.setdefault("reason_code", "no_recent_data")
                        out["next"] = {"call": "get_sensor_detail with time_range='7d' shows its last readings; "
                                               "get_device_freshness lists sensors that went silent"}
                    return out
                if not result:
                    return {"status": "error", "message": f"No measurements found for device '{device_id}'"}

                # 채널마다 최근 값 하나 — 채널 이름 없이 첫 채널 값만 주면 다채널 장치에서
                # "토양수분" 질문이 온도 값으로 답해진다(2026-11-03).
                channels = []
                for series in result:
                    readings = (series or {}).get("readings") or []
                    if readings:
                        channels.append({"measurement": series.get("measurement"),
                                         "timestamp": readings[-1]["t"],
                                         "value": readings[-1]["v"],
                                         "unit": readings[-1]["u"]})
                if not channels:
                    return {"status": "error", "message": f"No measurements found for device '{device_id}'"}

                latest = AoTNativeToolEngine._representative_channel(channels, measurement)
                out = {
                    "status": "success",
                    "device_id": device_id,
                    "name": getattr(row, "name", None),
                    "measurement": latest["measurement"],
                    "timestamp": latest["timestamp"],
                    "value": latest["value"],
                    "unit": latest["unit"],
                }
                if len(channels) > 1:
                    out["channels"] = channels
                if not measurement:
                    # 값이 있는 채널만 보면 온도·습도가 끊긴 센서가 배터리 값으로 답해진다 — 끊긴 채널을 말한다.
                    try:
                        seen = {c["measurement"] for c in channels}
                        quiet = [n for n in S.channel_names(device_id) if n not in seen]
                    except Exception:                                  # noqa: BLE001
                        quiet = []
                    if quiet:
                        out["silent_channels"] = quiet
                        out["note"] = ("No value in the last %s for: %s. The value above is from "
                                       "another channel of this device."
                                       % (time_range or "1h", ", ".join(quiet)))
                return out
            except Exception as exc:
                logger.error(f"[NativeToolEngine] get_sensor_reading error: {exc}")
                return {"status": "error", "message": str(exc)}

    @staticmethod
    def _exec_set_output_state(params: Dict) -> Dict:
        device_id = params.get("device_id")
        state = params.get("state")
        duration = params.get("duration", 0)
        if not duration and params.get("duration_seconds") not in (None, ""):
            # 도메인 틀의 이름. 숫자가 아니거나 0 이하면 승인 앞(validate_ai_control_target)에서 이미 거절됐다.
            from aot.outputs.command_forms import parse_run_seconds
            duration, _err = parse_run_seconds(params.get("duration_seconds"))
            if _err:
                return {"status": "error", "message": _err, "dispatched": False}
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
                # id·이름 모두 공용 해석으로 푼다 — 모호하면 고르지 않고(물리
                # 명령이다), 'AI 판단에 포함' 을 끈 출력이면 이유를 돌려준다.
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
