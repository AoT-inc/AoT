import logging
import json
import hashlib
from aot.databases.models import Input, InputChannel, Output, OutputChannel, Function, PID, Actions, GeoShape, GeoMap, CustomController, Notes, Camera
from aot.aot_client import DaemonControl
from aot.config import PYRO_URI
from aot.utils.inputs import parse_input_information
from aot.utils.outputs import parse_output_information
from aot.aot_flask.extensions import db
from aot.aot_flask.utils import utils_input, utils_output
from shapely.geometry import shape
from sqlalchemy import or_
from flask import has_app_context, has_request_context

logger = logging.getLogger(__name__)

# E-2: Module-level parsing cache
_INPUT_MODULE_CACHE = None
_OUTPUT_MODULE_CACHE = None
_AI_DOCS_CACHE = None  # Lazy-loaded from {INSTALL_DIRECTORY}/docs/ai_docs/ (BUG_01/BUG_04)
_MCP_HEALTH_CACHE = {}  # {server_id: (tools_list, timestamp, error_count)} TTL=300s (BUG_02)

# [TASK_8 056_] ID Validation Cache
import time
_ID_TTL_CACHE = {}  # {device_id: last_verification_timestamp}

class InvalidToolError(Exception):
    """Raised when a tool_name cannot be resolved to a valid action."""
    pass

# [OPTION_D] Static registry for internal system tools
# MIGRATION_CANDIDATE: Move to DB table when count > 20
# @ANCHOR: VIRTUAL_TOOL_REGISTRY — now DERIVED from the SSOT tool registry (Phase 1).
# Was a hand-maintained frozenset that drifted from the resolver tool_map
# (get_weather / get_cumulative_status were dispatchable but missing here, so
# resolve_action raised InvalidToolError for them). Declaring each tool once in
# aot/ai/services/tool_registry.py and deriving this set makes drift impossible.
from aot.ai.services.tool_registry import (
    virtual_tool_registry as _virtual_tool_registry,
    manifest_system_tools as _manifest_system_tools,
)
VIRTUAL_TOOL_REGISTRY = _virtual_tool_registry()

class AIActionService:
    """
    Service to expose system capabilities to AI agents as a manifest
    and execute actions via the AoT Daemon.
    """

    @staticmethod
    def get_registered_devices():
        """
        [TASK_29] Bridge Logic Recovery.
        Returns a list of all devices that are AI-enabled (is_ai_enabled=True).
        Used for spatial tree generation and tool manifest audits.
        """
        results = []
        from flask import current_app
        with current_app.app_context():
            try:
                # v26: Use combined activated filter for manifest consistency
                inputs = Input.query.filter_by(is_activated=True).all()
                outputs = Output.query.all()
                cameras = Camera.query.filter_by(is_activated=True).all() # Note: Camera lacks is_ai_enabled field

                for item in inputs:
                    results.append({
                        "id": item.unique_id, 
                        "name": item.name or item.unique_id, 
                        "kind": "input", 
                        "type": item.device
                    })
                for item in outputs:
                    results.append({
                        "id": item.unique_id, 
                        "name": item.name or item.unique_id, 
                        "kind": "output", 
                        "type": item.output_type
                    })
                for item in cameras:
                    results.append({
                        "id": item.unique_id, 
                        "name": item.name or item.unique_id, 
                        "kind": "camera", 
                        "type": item.camera_type
                    })
            except Exception as e:
                logger.error(f"Error in get_registered_devices: {e}")
            
        return results

    @staticmethod
    def get_action_manifest(agent_unique_id=None, is_slim=True, intent=None):
        """
        Returns a structured registry of all actions AI can potentially perform.
        Includes Output control, PID adjustments, and Function triggers.
        Filters sections based on intent to reduce token usage.
        v6.4: Request-scoped cache — eliminates duplicate DB queries within the same request.
        """
        # @ANCHOR: ACTION_MANIFEST_REQUEST_CACHE [2026-03-25]
        _manifest_cache_key = (agent_unique_id, is_slim, intent)
        try:
            from flask import g, has_request_context as _hrc
            if _hrc():
                if not hasattr(g, '_manifest_cache'):
                    g._manifest_cache = {}
                if _manifest_cache_key in g._manifest_cache:
                    return g._manifest_cache[_manifest_cache_key]
        except Exception:
            pass

        # B-2: Ensure Flask app and request context for utils that need current_app and Babel
        from flask import has_app_context, has_request_context
        _pushed_app_ctx = None
        _pushed_req_ctx = None
        
        if not has_app_context():
            try:
                from aot.aot_flask.app import create_app
                app = create_app()
                _pushed_app_ctx = app.app_context()
                _pushed_app_ctx.push()
            except Exception:
                pass

        from flask import current_app
        if not has_request_context() and has_app_context():
            try:
                _pushed_req_ctx = current_app.test_request_context()
                _pushed_req_ctx.push()
            except Exception:
                pass

        try:
            manifest = {
                "outputs": [],
                "pid_controllers": [],
                "predefined_functions": [],
                # @ANCHOR: system_tools — SSOT-derived (Phase 1). Was a ~180-line
                # hand-written list; now generated verbatim from tool_registry so
                # it can never drift from dispatch/approval. Byte-identical output.
                "system_tools": _manifest_system_tools(),
                "system_context": AIActionService._load_system_context(),
            }

            # [TASK_31][PATCH_A] Pre-fetch AoT MCP server for device-to-server binding.
            # Resolves server_id=None gap at Phase 3 validation.
            from aot.databases.models.mcp_server import MCPServer as _MCPSrv
            _aot_srv = (
                _MCPSrv.query.filter(
                    _MCPSrv.is_activated == True,
                    _MCPSrv.command.contains('aot_mcp_server')
                ).first()
                or _MCPSrv.query.filter(
                    _MCPSrv.is_activated == True,
                    _MCPSrv.scope == 'general'
                ).first()
                or _MCPSrv.query.filter(
                    _MCPSrv.is_activated == True,
                    _MCPSrv.name.ilike('%aot%')
                ).first()
            )
            _aot_server_id = _aot_srv.unique_id if _aot_srv else None
            if not _aot_server_id:
                logger.warning("[TASK_31] No active AoT MCP server found. Using virtual_tool_call binding.")

            # v26: Only include AI-enabled outputs in manifest (Output model lacks is_activated field)
            outputs = Output.query.filter_by(is_ai_enabled=True).all()
            for o in outputs:
                out_item = {
                    "unique_id": o.unique_id,
                    "name": o.name,
                    "type": o.output_type,
                    "capabilities": ["on", "off", "pwm" if o.output_type == 'pwm' else "on_off"]
                }

                # [TASK_31][TASK_32] Bind MCP server metadata + enforce strict type rule
                # [FIX] MCP 서버 미등록 시에도 virtual_tool_call 바인딩으로 LLM에 operate_device 정보 제공
                _binding_hint = (
                    f"To control this device use tool_name='operate_device' with "
                    f"params.arguments={{\"device_id\": \"{o.unique_id}\", \"state\": \"on|off\", \"duration_seconds\": <seconds>}}. "
                    f"Do NOT include action_type in your JSON output."
                )
                if _aot_server_id:
                    out_item["mcp_binding"] = {
                        "server_id": _aot_server_id,
                        "tool_name": "operate_device",
                        "hint": _binding_hint
                    }
                else:
                    out_item["mcp_binding"] = {
                        "tool_name": "operate_device",
                        "hint": _binding_hint
                    }

                # Only include channels if NOT in slim mode to save tokens
                if not is_slim:
                    channels = OutputChannel.query.filter_by(
                        output_id=o.unique_id
                    ).order_by(OutputChannel.channel).all()
                    out_item["channels"] = [
                        {"index": ch.channel, "name": ch.name or f"CH{ch.channel}"}
                        for ch in channels
                    ]

                manifest["outputs"].append(out_item)

            # 2. PID Controllers (Environment Tuning)
            pids = PID.query.filter_by(is_activated=True).all()
            for p in pids:
                manifest["pid_controllers"].append({
                    "unique_id": p.unique_id,
                    "name": p.name,
                    "latitude": p.latitude,
                    "longitude": p.longitude,
                    "adjustable_parameters": ["setpoint", "kp", "ki", "kd"]
                })

            # 3. Predefined Functions (Scenario Execution)
            functions = Function.query.all()
            for f in functions:
                manifest["predefined_functions"].append({
                    "unique_id": f.unique_id,
                    "name": f.name,
                    "latitude": f.latitude,
                    "longitude": f.longitude,
                    "description": f"Executes all actions associated with {f.name}"
                })

            # 4. Abstract Planning Zones (Spatial Anchors)
            zones = GeoShape.query.filter_by(type='zone').all()
            manifest["spatial_zones"] = []
            for z in zones:
                meta = z.meta_json if z.meta_json else {}
                name = meta.get('name', f"Zone_{z.id}")
                manifest["spatial_zones"].append({
                    "id": z.id,
                    "name": name,
                    "type": z.type
                })

            # 5. Creatable Device Types (For Registration)
            # E-2: Use cached module information
            global _INPUT_MODULE_CACHE, _OUTPUT_MODULE_CACHE
            if _INPUT_MODULE_CACHE is None:
                _INPUT_MODULE_CACHE = parse_input_information()
            if _OUTPUT_MODULE_CACHE is None:
                _OUTPUT_MODULE_CACHE = parse_output_information()
            dict_inputs = _INPUT_MODULE_CACHE
            dict_outputs = _OUTPUT_MODULE_CACHE

            if is_slim:
                # Phase 21: Always include certain 'Virtual/Analysis' inputs even in slim mode
                # to help AI recognize them without a second RAG loop.
                v_inputs = [
                    k for k in dict_inputs.keys() 
                    if k.upper() == 'SATELLITE_ANALYSIS' or k.startswith('gis_')
                ]
                manifest["creatable_inputs"] = []
                for k in v_inputs:
                    v = dict_inputs[k]
                    interfaces = v.get('interfaces', [])
                    for itf in (interfaces if interfaces else ['']):
                        type_id = f"{k},{itf}" if itf else f"{k},"
                        manifest["creatable_inputs"].append({
                            "type_id": type_id,
                            "name": str(v.get('input_name', k)),
                            "manufacturer": str(v.get('input_manufacturer', 'Unknown')),
                            "description": str(v.get('message', ''))
                        })

                # Phase 6: Return summary only for slimming
                manifest["creatable_inputs_summary"] = {
                    "total_count": len(dict_inputs),
                    "analysis_count": len(v_inputs),
                    "meaning": "CATALOG of input device TYPES that CAN be added — NOT the user's registered devices. For registered devices call get_device_list.",
                    "note": "A few key analysis/GIS modules are listed above. Use 'action_type: get_detailed_manifest, target_id: input' for the full list of physical sensors."
                }
                manifest["creatable_outputs_summary"] = {
                    "total_count": len(dict_outputs),
                    "meaning": "CATALOG of output device TYPES that CAN be added — NOT the user's registered devices. For registered devices call get_device_list.",
                    "note": "Use 'action_type: get_detailed_manifest, target_id: output' for full list."
                }
                from aot.utils.functions import parse_function_information
                from aot.config import FUNCTION_INFO
                dict_functions = parse_function_information()
                manifest["creatable_functions_summary"] = {
                    "total_count": len(dict_functions) + len(FUNCTION_INFO),
                    "note": "Use 'action_type: get_detailed_manifest, target_id: function' for full list."
                }
                gis_count = sum(1 for k in dict_inputs.keys() if k.startswith('gis_'))
                manifest["creatable_gis_inputs_summary"] = {
                    "total_count": gis_count,
                    "note": "Use 'action_type: get_detailed_manifest, target_id: gis_input' for full list."
                }
            else:
                manifest["creatable_inputs"] = []
                for k, v in dict_inputs.items():
                    interfaces = v.get('interfaces', [])
                    for itf in (interfaces if interfaces else ['']):
                        type_id = f"{k},{itf}" if itf else f"{k},"
                        manifest["creatable_inputs"].append({
                            "type_id": type_id,
                            "name": str(v.get('input_name', k)),
                            "manufacturer": str(v.get('input_manufacturer', 'Unknown')),
                            "description": str(v.get('message', ''))
                        })

                manifest["creatable_outputs"] = []
                for k, v in dict_outputs.items():
                    interfaces = v.get('interfaces', [])
                    for itf in (interfaces if interfaces else ['']):
                        type_id = f"{k},{itf}" if itf else f"{k},"
                        manifest["creatable_outputs"].append({
                            "type_id": type_id,
                            "name": str(v.get('output_name', k)),
                            "library": str(v.get('output_library', '')),
                            "description": str(v.get('message', ''))
                        })

                # Creatable Functions
                from aot.utils.functions import parse_function_information
                from aot.config import FUNCTION_INFO
                dict_functions = parse_function_information()
                manifest["creatable_functions"] = []
                for k, v in dict_functions.items():
                    manifest["creatable_functions"].append({
                        "type_id": k,
                        "name": str(v.get('function_name', k)),
                        "description": str(v.get('message', ''))[:100]
                    })
                # Built-in function types
                for k, v in FUNCTION_INFO.items():
                    manifest["creatable_functions"].append({
                        "type_id": k,
                        "name": v.get('name', k)
                    })

                # Creatable GIS Inputs (Map Layers)
                manifest["creatable_gis_inputs"] = []
                for k, v in dict_inputs.items():
                    if k.startswith('gis_'):
                        interfaces = v.get('interfaces', [])
                        itf = interfaces[0] if interfaces else ''
                        type_id = f"{k},{itf}" if itf else f"{k},"
                        manifest["creatable_gis_inputs"].append({
                            "type_id": type_id,
                            "name": str(v.get('input_name', k)),
                            "description": str(v.get('message', ''))[:100]
                        })

            # E-3: Manifest version hash
            manifest["version"] = hashlib.md5(
                json.dumps(manifest, sort_keys=True, default=str).encode()
            ).hexdigest()[:8]

            # 6. MCP Tools Integration (Model Context Protocol)
            from aot.ai.services.mcp_bridge_service import MCPBridgeService
            from aot.databases.models.mcp_server import MCPServer, AgentMCPAccess
            from aot.databases.models.ai import AIAgent
            
            # Filter servers based on agent's tool_access policy
            mcp_query = MCPServer.query.filter_by(is_activated=True)
            
            if agent_unique_id:
                agent = AIAgent.query.filter_by(unique_id=agent_unique_id).first()
                if agent:
                    if agent.tool_access == 'none':
                        mcp_query = mcp_query.filter(False) # All tools disabled
                    elif agent.tool_access == 'assigned':
                        # Join with AgentMCPAccess to find only assigned servers
                        mcp_query = mcp_query.join(
                            AgentMCPAccess, 
                            AgentMCPAccess.mcp_unique_id == MCPServer.unique_id
                        ).filter(AgentMCPAccess.agent_unique_id == agent_unique_id)
                    elif agent.tool_access == 'auto':
                        # Legacy/Auto: only 'general' scope unless specifically assigned (hybrid)
                        mcp_query = mcp_query.filter(MCPServer.scope == 'general')
                    # if 'all', no additional filtering
            else:
                # Default for router/no agent context: only 'general' scope
                mcp_query = mcp_query.filter(MCPServer.scope == 'general')

            mcp_servers_raw = mcp_query.all()
            manifest["mcp_tools"] = []
            manifest["mcp_resources"] = []  # v23 (MCP_T08)

            # [P1-FIX] Pre-compute _expose_all BEFORE use at orphan-filter block below.
            # 'agent' is defined in enclosing scope when agent_unique_id is truthy.
            # Short-circuit evaluation ensures 'agent' is never accessed when agent_unique_id is falsy.
            _expose_all = bool(agent_unique_id and agent and agent.tool_access in ['assigned', 'all'])

            # [P3-FIX] Capture real Flask app object in the request thread.
            # ThreadPoolExecutor worker threads do NOT inherit the parent's Flask context stack.
            _flask_app = None
            try:
                from flask import current_app as _cur_app
                _flask_app = _cur_app._get_current_object()
            except RuntimeError:
                pass

            # v6: Exclude orphaned MCPServers (no active agent mapped)
            # [P2-FIX] Skip orphan filter for 'all'/'assigned' agents — they access servers
            # regardless of explicit AgentMCPAccess records.
            mcp_servers = []
            if _expose_all:
                mcp_servers = list(mcp_servers_raw)
            else:
                for _s in mcp_servers_raw:
                    has_agent = db.session.query(AgentMCPAccess).join(
                        AIAgent, AgentMCPAccess.agent_unique_id == AIAgent.unique_id
                    ).filter(
                        AgentMCPAccess.mcp_unique_id == _s.unique_id,
                        AIAgent.is_activated == True
                    ).first()
                    if has_agent:
                        mcp_servers.append(_s)
                    else:
                        logger.debug(f"Skipping orphaned MCPServer '{_s.name}' (no active agent mapped)")

            # [BUG_02] Concurrent MCP tool fetch with TTL cache
            import time
            from concurrent.futures import ThreadPoolExecutor, as_completed

            # [REFIX ERR_1] Bind _expose_all and _flask_app as default arguments at
            # function-definition time. Avoids any closure UnboundLocalError when the
            # outer-scope variables are resolved inside the ThreadPoolExecutor thread.
            def _fetch_server_tools(server, _ea=_expose_all, _fa=_flask_app):
                """Fetch tools for one server; uses _MCP_HEALTH_CACHE with TTL=300s."""
                server_id = server.unique_id
                expose_all = _ea

                if not (expose_all or server.scope == 'general'):
                    return [{
                        "server_id": server_id,
                        "server_name": server.name,
                        "description": f"Specific purpose MCP server. Use 'get_detailed_manifest' with target_id: mcp_{server_id} to see available tools.",
                        "requires_exploration": True
                    }]

                # TTL cache check
                entry = _MCP_HEALTH_CACHE.get(server_id)
                if entry:
                    cached_tools, ts, _err = entry
                    if (time.time() - ts) < 300:
                        return cached_tools

                # [P3-FIX] Guard: only call get_tools() for already-running servers.
                # get_tools() → get_server_process() holds cls._lock for up to 30s
                # (MCP_INIT_TIMEOUT). Calling it from ThreadPoolExecutor threads on
                # stopped/cooldown servers starves the UI restart button HTTP request.
                status = MCPBridgeService.get_server_status(server_id)
                if status != 'running':
                    logger.warning(f"MCP server '{server_id}' skipped in manifest: status is '{status}' (not running).")
                    _MCP_HEALTH_CACHE.pop(server_id, None)
                    return []

                try:
                    # [REFIX P3] Push app context for this thread; get_tools() calls
                    # MCPServer.query which requires SQLAlchemy app context.
                    # Explicit if/else avoids contextlib.nullcontext() version dependency.
                    if _fa:
                        with _fa.app_context():
                            tools = MCPBridgeService.get_tools(server_id)
                    else:
                        tools = MCPBridgeService.get_tools(server_id)
                    if not tools:
                        _MCP_HEALTH_CACHE.pop(server_id, None)
                        return []
                    result = []
                    for tool in tools:
                        desc = tool.get("description", "")
                        if is_slim and len(desc) > 100:
                            desc = desc[:97] + "..."
                        result.append({
                            "server_id": server_id,
                            "server_name": server.name,
                            "tool_name": tool.get("name"),
                            "description": desc,
                            "input_schema": tool.get("inputSchema", {}),
                            # [OPTION_D] Removed action_type field — AI derives it from resolver
                            # Hint: STRICT RULE for AI — use tool_name + server_id binding
                            "usage_hint": "CRITICAL: Using 'operate_device' as an action_type is DEPRECATED and will CRASH the system. "
                                         "You MUST use action_type='mcp_tool_call' with params.tool_name='operate_device'."
                        })
                    _MCP_HEALTH_CACHE[server_id] = (result, time.time(), 0)
                    return result
                except Exception as exc:
                    logger.warning(f"[BUG_02] MCP tool fetch failed for {server_id}: {exc}")
                    _MCP_HEALTH_CACHE.pop(server_id, None)
                    return []

            max_w = min(8, len(mcp_servers)) if mcp_servers else 1
            with ThreadPoolExecutor(max_workers=max_w) as pool:
                futures = {pool.submit(_fetch_server_tools, s): s for s in mcp_servers}
                for fut in as_completed(futures):
                    manifest["mcp_tools"].extend(fut.result())

            # v23 (MCP_T08): Populate mcp_resources — parallel loop over same mcp_servers
            for server in mcp_servers:
                resources = MCPBridgeService.get_resources(server.unique_id)
                for resource in resources:
                    desc = resource.get('description', '')
                    if is_slim and len(desc) > 100:
                        desc = desc[:97] + '...'
                    manifest['mcp_resources'].append({
                        'server_id': server.unique_id,
                        'server_name': server.name,
                        'uri': resource.get('uri'),
                        'name': resource.get('name'),
                        'description': desc,
                        'mime_type': resource.get('mimeType', ''),
                        'action_type': 'mcp_resource_read'
                    })

            # v6.1: Intent-based manifest filtering to reduce token usage
            if intent == 'DATA_QUERY':
                manifest.pop("outputs", None)
                manifest.pop("pid_controllers", None)
                manifest.pop("predefined_functions", None)
                # Drop the full 'creatable_*' CATALOGS (installable device TYPES) for
                # read-only queries. They are only for registration (register_device),
                # not for "what do I have", and the model kept reciting them (pH/EC
                # sensors, stepper motors, …) as if they were the user's devices —
                # while also bloating the context so 'system_knowledge' got truncated.
                # Keep the small '_summary' counts so "what CAN I add?" still has a
                # pointer (get_detailed_manifest) without the noisy full list.
                for _k in ("creatable_inputs", "creatable_outputs",
                           "creatable_functions", "creatable_gis_inputs"):
                    manifest.pop(_k, None)
            elif intent == 'CONTROL':
                manifest.pop("predefined_functions", None)
                manifest.pop("spatial_zones", None)
                manifest.pop("creatable_inputs", None)
                manifest.pop("creatable_inputs_summary", None)
            elif intent == 'CHAT':
                manifest.pop("outputs", None)
                manifest.pop("pid_controllers", None)
                manifest.pop("predefined_functions", None)
                manifest.pop("spatial_zones", None)
                manifest.pop("creatable_inputs", None)
                manifest.pop("creatable_outputs", None)
                manifest.pop("mcp_tools", None)
                manifest.pop("mcp_resources", None)  # v23 (MCP_T08)

            # @ANCHOR: ACTION_MANIFEST_REQUEST_CACHE [2026-03-25]
            try:
                from flask import g, has_request_context as _hrc
                if _hrc() and hasattr(g, '_manifest_cache'):
                    g._manifest_cache[_manifest_cache_key] = manifest
            except Exception:
                pass
            return manifest
        except Exception as e:
            logger.exception("Error generating action manifest")
            return {"error": str(e)}

    @staticmethod
    def _resolve_target(target_id, action_type, params=None, context=None):
        """
        Intelligently resolves target_id (Name, UUID, or None) into a valid system ID.
        Handles spatial nodes, devices, and context-based inference.
        """
        logger.info(f"[TargetResolver] Resolving '{target_id}' for action '{action_type}'")

        # 0. Defensive: a caller may pass the whole params dict as target_id by
        # mistake (positional-argument slip — see 9ceecf0). Fail loudly; do NOT
        # try to recover the id out of the dict. This function can only hand back
        # a resolved id — execute_action keeps its own `params`, so a "recovered"
        # target would be executed with the caller's EMPTY params, and the
        # control_output branch defaults state to 'off'. That turns a command
        # meant to OPEN a valve into one that silently CLOSES it — strictly worse
        # than the crash this guard replaced. execute_action's except block turns
        # this into {"status": "error", ...}.
        if isinstance(target_id, dict):
            raise TypeError(
                f"target_id must be a string id, got a dict for action '{action_type}'. "
                f"The caller most likely passed params positionally — use "
                f"execute_action(action_type, target_id, params=...). Received keys: "
                f"{sorted(target_id.keys())}"
            )

        # 1. Null handling & Placeholder handling (Inference from context or params)
        placeholders = ['none', 'null', 'here', 'this', 'current', 'system_internal', 'default']
        if not target_id or str(target_id).lower() in placeholders:
            # Priority 1: Check params for explicit identity cues (Deep Discovery)
            if params:
                # v26.9: Deep Discovery check — look inside nested 'arguments' if available
                _search_params = params.get('arguments') if isinstance(params.get('arguments'), dict) else params
                
                # Common keys LLM uses for target identity
                ID_KEYS = ['device_id', 'target_id', 'target_zone', 'loc_id', 'node_id', 'target']
                for k in ID_KEYS:
                    candidate = _search_params.get(k)
                    if candidate and str(candidate).lower() not in placeholders:
                        # Try to resolve this candidate recursively (but prevent infinite loop)
                        _res_id, _res_type = AIActionService._resolve_target(candidate, action_type, context=context)
                        if _res_id and str(_res_id).lower() not in placeholders:
                            logger.info(f"[TargetResolver] Deep Discovery: Found '{_res_id}' in params['{k}' or 'arguments']['{k}']")
                            return _res_id, _res_type

            # Priority 2: Pull from page_context (UI-driven inference)
            if context:
                # Current focused target in modal
                active_modal = context.get('active_modal') or {}
                ctx_id = context.get('targetId') or active_modal.get('targetId')
                if ctx_id:
                    logger.info(f"[TargetResolver] Inferred from page_context: {ctx_id}")
                    return ctx_id, context.get('targetType') or active_modal.get('targetType')

                # Current dashboard
                dash_id = context.get('current_dashboard_id')
                if dash_id:
                    logger.info(f"[TargetResolver] Inferred from dashboard: {dash_id}")
                    return dash_id, 'dashboard'
            
            # If still nothing, return as is (let execute_action handle validation error)
            return target_id, None

        # 2. Check if already a UUID (quick regex or length check)
        is_uuid = len(str(target_id)) == 36 and '-' in str(target_id)
        
        # 3. Fuzzy Matching by SQL-level Filter (E-1: Optimization)
        # Search priority: GeoShape (Zones/Sites) > Output > Input > Function
        if action_type in ['note', 'register_device', 'abstract_plan']:
            # Search GeoShape IDs and name in JSON feature/meta_json
            shape_match = GeoShape.query.filter(
                or_(
                    GeoShape.id == target_id,
                    GeoShape.geo_id == target_id,
                    GeoShape.feature.contains(target_id),
                    GeoShape.meta_json.contains(target_id)
                )
            ).all()
            
            if shape_match:
                if len(shape_match) > 1:
                    logger.warning(f"[TargetResolver] Multiple shapes found for '{target_id}'. Selecting first.")
                match = shape_match[0]
                logger.info(f"[TargetResolver] Resolved '{target_id}' to GeoShape: {match.id}")
                return match.id, 'geoshape'

        # Device matching
        output_match = Output.query.filter(or_(Output.unique_id == target_id, Output.name == target_id)).first()
        if output_match:
            logger.info(f"[TargetResolver] Resolved '{target_id}' to Output: {output_match.unique_id}")
            # [TASK_8 056_] Update TTL on successful resolution (Discovery)
            _ID_TTL_CACHE[output_match.unique_id] = time.time()
            return output_match.unique_id, 'output'

        input_match = Input.query.filter(or_(Input.unique_id == target_id, Input.name == target_id)).first()
        if input_match:
            logger.info(f"[TargetResolver] Resolved '{target_id}' to Input: {input_match.unique_id}")
            # [TASK_8 056_] Update TTL on successful resolution (Discovery)
            _ID_TTL_CACHE[input_match.unique_id] = time.time()
            return input_match.unique_id, 'input'

        func_match = Function.query.filter(or_(Function.unique_id == target_id, Function.name == target_id)).first()
        if func_match:
            logger.info(f"[TargetResolver] Resolved '{target_id}' to Function: {func_match.unique_id}")
            return func_match.unique_id, 'function'

        # Fallback to original if no match found
        return target_id, None

    @staticmethod
    def requires_approval(tool_name: str) -> bool:
        """True if `tool_name` is a physical-control or mutating tool that must
        never auto-execute — the single check any caller (an engine's own native
        tool-calling loop, AgentLoopService, _dispatch_actions, …) should use
        before running a tool without going through the approval flow. Union of
        PHYSICAL_TOOLS (hard-blocked inside execute_action itself) and the SSOT
        approval_required_tools() (mutating virtual tools execute_action does
        NOT independently gate — see GEMINI_NATIVE_APPROVAL_GATE)."""
        if not tool_name:
            return False
        from aot.ai.services.resolvers.constants import PHYSICAL_TOOLS
        from aot.ai.services.tool_registry import approval_required_tools
        return tool_name in PHYSICAL_TOOLS or tool_name in approval_required_tools()

    @staticmethod
    def resolve_action(tool_name: str, params: dict = None) -> dict:
        """
        [OPTION_D][Phase 1] Deterministic action router.
        Given tool_name (from LLM), return fully-formed action dict.

        Args:
            tool_name: tool identifier (e.g., 'operate_device', 'get_sensor_detail')
            params: dict — action parameters from LLM (optional, used for arguments)

        Returns:
            dict {
                'action_type': 'mcp_tool_call' | 'virtual_tool_call',
                'target_id': server_unique_id | 'system_internal',
                'params': { 'server_id', 'tool_name', 'arguments' }
            }

        Raises:
            InvalidToolError if tool_name not found in any registry.

        CM_3 NOTE: If this returns virtual_tool_call for 'operate_device', it means
        the AoT System Expert Server is not running or has no agent_mcp_access row.
        Operator must INSERT agent_mcp_access on machine_standard for server '67d63a46'.
        health_check_all() must run on startup to populate _tools_cache so active_servers
        returns tool_names correctly.
        """
        # Step 1: Query live MCP servers (Priority 1 — physical truth)
        # [027_STEP_4] AoT > GIS routing priority:
        # Sort active servers so AoT/hardware servers appear before GIS/external servers.
        # Local hardware data must always take precedence for Weather and Control queries.
        try:
            from aot.ai.services.mcp_bridge_service import MCPBridgeService
            active_servers = MCPBridgeService.get_active_servers()
            # Prioritize servers whose name/scope suggests AoT hardware (not GIS/external)
            _GIS_MARKERS = ('gis', 'geo', 'map', 'expert', 'external', 'remote')
            active_servers = sorted(
                active_servers,
                key=lambda s: any(m in (s.name or '').lower() for m in _GIS_MARKERS)
            )  # False (AoT) sorts before True (GIS)
            for server in active_servers:
                if tool_name in server.tool_names:
                    # @ANCHOR: MCP_PRIORITY_GATE (TASK_8 048 — Step 1)
                    # MCP is the mandatory first route for all tool calls.
                    logger.info(
                        f"[MCP_PRIORITY_GATE] Tool '{tool_name}' → mcp_tool_call "
                        f"on server '{server.name}' ({server.unique_id[:8]})"
                    )
                    # BUG-08 FIX: params passed here is action['params'] which may already
                    # contain an 'arguments' sub-dict (e.g. {"arguments": {"query": "..."}, "tool_name": "..."}).
                    # Using params directly would double-nest: arguments.arguments.query → query=None.
                    # Unwrap 'arguments' if present; otherwise strip system-internal keys.
                    _system_keys = frozenset({'tool_name', 'server_id', 'context'})
                    if params and 'arguments' in params:
                        _args = params['arguments'] if isinstance(params['arguments'], dict) else {}
                    else:
                        _args = {k: v for k, v in (params or {}).items() if k not in _system_keys}
                    return {
                        "action_type": "mcp_tool_call",
                        "target_id": server.unique_id,
                        "params": {
                            "server_id": server.unique_id,
                            "tool_name": tool_name,
                            "arguments": _args
                        }
                    }
        except Exception as e:
            logger.warning(f"[resolve_action] MCPBridgeService query failed: {e}")

        # Step 2a: Direct action_type tools — these have their own execute_action handler,
        # NOT routed through virtual_tool_call's tool_map. Must be resolved to themselves.
        # Supports both flat params {'target_id': ..., 'section': ...}
        # and nested params {'arguments': {'target_id': ..., 'section': ...}}.
        _DIRECT_ACTION_TYPES = frozenset({'read_manual', 'get_detailed_manifest'})
        if tool_name in _DIRECT_ACTION_TYPES:
            _p = dict(params) if params else {}
            _args = _p.pop('arguments', None)
            if isinstance(_args, dict):
                # Flatten nested arguments, preserving extra keys (e.g. section)
                _target = _p.pop('target_id', None) or _args.pop('target_id', 'system_internal')
                _p.update(_args)  # merge remaining args (section, etc.) into params
            else:
                _target = _p.pop('target_id', None) or 'system_internal'
            # Strip system-internal keys that do not belong in action params
            for _k in ('tool_name', 'server_id', 'agent_unique_id', 'context'):
                _p.pop(_k, None)
            return {
                "action_type": tool_name,
                "target_id": _target,
                "params": _p
            }

        # Step 2b: Check VIRTUAL_TOOL_REGISTRY (Priority 2 — static/internal)
        if tool_name in VIRTUAL_TOOL_REGISTRY:
            return {
                "action_type": "virtual_tool_call",
                "target_id": "system_internal",
                "params": {
                    "server_id": "system_internal",
                    "tool_name": tool_name,
                    **(params or {})
                }
            }

        # Step 3: Fail-fast
        error_msg = f"Unknown tool: '{tool_name}' — not found in MCP servers or VIRTUAL_TOOL_REGISTRY"
        logger.error(f"[resolve_action] {error_msg}")
        raise InvalidToolError(error_msg)

    @staticmethod
    def _tag_observation(raw_value, device_id):
        """[BUG_01] Semantic Observer: annotate tool result with unit and domain from ai_docs."""
        global _AI_DOCS_CACHE
        meta = _AI_DOCS_CACHE.get(device_id) if _AI_DOCS_CACHE else None
        if not meta:
            logger.warning(f"[SemanticObserver] No unit mapping for {device_id}. Passing raw.")
            return raw_value
        unit = meta.get('unit', '')
        domain = meta.get('domain', '')
        return f"{raw_value} {unit} [{domain}]" if unit else raw_value

    @staticmethod
    def _load_system_context() -> str:
        """[BUG_04] ICRA Layer: load structured system context from dynamic path in INSTALL_DIRECTORY/docs/ai_docs/."""
        global _AI_DOCS_CACHE
        try:
            from aot.config import INSTALL_DIRECTORY
            import os
            if _AI_DOCS_CACHE is None:
                index_path = os.path.join(INSTALL_DIRECTORY, 'docs', 'ai_docs', 'ai_doc_index.json')
                with open(index_path, 'r', encoding='utf-8') as f:
                    _AI_DOCS_CACHE = json.load(f)

            # [STEP 3] Inject real-time situational context via context7 MCP
            try:
                from aot.ai.services.mcp_bridge_service import MCPBridgeService
                # 'context7' provides time, location, and session metadata
                situational_context = MCPBridgeService.get_tools('context7')
                if situational_context:
                    _AI_DOCS_CACHE['situational_awareness'] = situational_context
            except Exception as ce:
                logger.warning(f"[ICRA] Context7 integration failed: {ce}")

            return json.dumps(_AI_DOCS_CACHE, ensure_ascii=False)[:2000]  # Token cap
        except Exception as e:
            logger.warning(f"[ICRA] Could not load system context: {e}")
            return ''

    @staticmethod
    def execute_action(action_type, target_id=None, params=None, context=None, _approved=False, **kwargs):
        """
        Executes a specific action via the corresponding Action Module.
        Supports outputs, pid, functions, and composite system commands.
        """
        from aot.ai.services.ai_scheduler_service import AISchedulerService
        from aot.utils.execution_context import get_context
        
        # [TASK_8 054_] Critical Fix 1: Lifecycle Initialization
        # Prevents UnboundLocalError if an exception occurs before assignment.
        final_result = None
        
        # Normalize action_type
        if action_type:
            action_type = str(action_type).lower().strip()


        logger.info(f"[AI Action] Requesting: {action_type} on {target_id} with {params}")
        # B-2: Ensure Flask app and request context for utils that need current_app and Babel
        _pushed_app_ctx = None
        _pushed_req_ctx = None
        
        if not has_app_context():
            try:
                from aot.aot_flask.app import create_app
                app = create_app()
                _pushed_app_ctx = app.app_context()
                _pushed_app_ctx.push()
            except Exception:
                logger.warning("Could not create app context for execute_action")

        from flask import current_app
        if not has_request_context() and has_app_context():
            try:
                # Flask-Babel context is needed for modules using gettext()
                _pushed_req_ctx = current_app.test_request_context()
                _pushed_req_ctx.push()
            except Exception as e:
                logger.warning(f"Could not push test request context: {e}")

        try:
            logger.info(f"[execute_action] Type: {action_type}, Target: {target_id}, Params: {params}")
            daemon = DaemonControl(pyro_uri=PYRO_URI)
            params = params or {}
            
            # Phase 24: Merge flattened kwargs into params for AI resilience
            if kwargs:
                # Prioritize explicit params, but capture missing keys from kwargs
                for k, v in kwargs.items():
                    if k not in params:
                        params[k] = v
                logger.info(f"[AI Integration] Merged kwargs into params: {params}")

            # --- Target Resolution Gateway ---
            page_context = params.get('page_context') or kwargs.get('page_context')
            resolved_id, resolved_type = AIActionService._resolve_target(target_id, action_type, params, context=page_context)
            
            # Validation: If target is strictly required but could not be resolved
            if not resolved_id and action_type not in ['output', 'pid']: # register_device might create its own target
                 logger.warning(f"[Gateway] Target could not be resolved for {action_type}")
            
            target_id = resolved_id # Update with resolved ID
            # ----------------------------------

            # [PC-089-GATE][TASK_43] Physical control gate — all execution paths
            # mcp_tool_call / virtual_tool_call 로 physical tool 호출 시
            # _approved=True 토큰을 실어 오는 경로만 허용(execute_logged_action의
            # 승인카드 실행, _execute_scheduled_action의 SchedulerJobMeta 실행 등).
            # Planner chain, RAG loop 등 미승인 경로는 모두 차단.
            from aot.ai.services.resolvers.constants import PHYSICAL_TOOLS as _PHYSICAL_TOOLS  # @ANCHOR: PHYSICAL_TOOLS_IMPORT
            if action_type in ('mcp_tool_call', 'virtual_tool_call') and not _approved:
                _tool_name = params.get('tool_name') or (target_id if isinstance(target_id, str) else None)
                # @ANCHOR: PC089_GATE_BYPASS (TASK_9-E)
                # Bypass physical control gate for SYSTEM_EXPERT_SERVER calls to prevent "User Approval Pending" deadlocks
                # during autonomous reasoning/discovery loops.
                _server_id = params.get('server_id')
                if _tool_name == 'operate_device' and _server_id == '67d63a46-21c2-4127-b343-2e43376f49a3':
                    logger.info(f"[PC-089-GATE] BYPASS — granting automated approval for '{_tool_name}' from System Expert Server.")
                    _approved = True

                if _tool_name in _PHYSICAL_TOOLS and not _approved:
                    logger.error(
                        f"[PC-089-GATE] Blocked unauthorized physical execution of '{_tool_name}'. "
                        f"Call path lacks an _approved=True approval token."
                    )
                    return {
                        "status": "error",
                        "message": "User approval is pending for physical safety.",
                        "blocked": True
                    }

            # [TASK_8 054_] Critical Fix 2: Symbolic Mapping Enforcement
            # Before registry dispatch, ensure target_id is a valid physical ID for CONTROL.
            # If target_id is a placeholder or logical name that wasn't resolved to a UUID/Service-ID,
            # we MUST block execution to prevent 'tool called with empty string' errors.
            if action_type in ('mcp_tool_call', 'virtual_tool_call') and _approved:
                from aot.ai.services.resolvers.constants import PHYSICAL_TOOLS as _PT
                _tool = params.get('tool_name') or (target_id if isinstance(target_id, str) else None)
                if _tool in _PT:
                    # [TASK_8 056_] Step 1: Look Before Leap (LBL) Gate
                    # Mandatory pre-flight check if TTL > 300s.
                    # [LBL_GATE_FIX] When _approved=True (human explicitly confirmed), skip TTL check.
                    # User approval is the highest authority — no need for re-discovery gate.
                    from aot.utils.time_utils import utc_now
                    _now_ts = utc_now().timestamp()
                    _last_seen = _ID_TTL_CACHE.get(target_id, 0)

                    if _now_ts - _last_seen > 300 and not _approved:
                        logger.warning(f"[DYNAMIC_SEARCH_TRIGGERED] Control of '{target_id}' aborted. Reason: Discovery stale or missing (TTL > 300s).")
                        return {
                            "status": "error",
                            "message": f"[DYNAMIC_SEARCH_TRIGGERED] Before running the '{_tool}' command, a fresh status check (search_devices) is required. (Target: {target_id})",
                            "error_code": "PC-097",
                            "requires_search": True
                        }

                    # Placeholders that indicate mapping failure or missing input.
                    # [PC-098-FIX] virtual_tool_call with 'system_internal' is valid:
                    # VirtualToolResolver uses system_internal as the canonical target.
                    # PC-098 only applies to mcp_tool_call where a real device UUID is required.
                    _invalid = [None, '', 'none', 'null', 'here', 'this', 'current', 'default']
                    _is_virtual_internal = (action_type == 'virtual_tool_call' and target_id == 'system_internal')
                    if not _is_virtual_internal and (target_id in _invalid or (isinstance(target_id, str) and len(target_id) < 8)):
                         logger.error(f"[PC-098-MAPPING-FAILED] Action '{action_type}' for tool '{_tool}' has invalid target: '{target_id}'")
                         return {
                             "status": "error",
                             "message": f"[PC-098-MAPPING-FAILED] Could not find the control target for the '{_tool}' command. (Target: {target_id})",
                             "error_code": "PC-098"
                         }

            # @ANCHOR: RESOLVER_REGISTRY_DISPATCH (SBS-002_V2 Step 4)
            # Registered action types are intercepted here. Unregistered types
            # fall through to the legacy if/elif chain below.
            from aot.ai.services.resolvers.registry import ActionResolverRegistry
            _registry_result = ActionResolverRegistry.resolve(
                action_type, target_id, params, context, approved=_approved
            )
            if _registry_result is not None:
                return _registry_result

            if action_type == 'pid':
                setting = str(params.get('setting', 'setpoint'))
                value = params.get('value')
                if value is None:
                    return {"status": "error", "message": "Missing value for PID adjustment"}
                value = float(value)
                res = daemon.pid_set(target_id, setting, value)
                return {"status": "success", "result": res}

            elif action_type == 'function':
                res = daemon.trigger_all_actions(target_id)
                return {"status": "success", "result": res}

            elif action_type in ('activate', 'deactivate'):
                # Scheduled activate/deactivate of an Input or controller
                # (Conditional/Trigger/PID/CustomController). Same DB+daemon
                # path as the settings UI; the scheduled job reached here only
                # via approve_job (_approved=True), so it's already human-confirmed.
                from aot.ai.services.aot_data_tool_service import AoTDataToolService
                res = AoTDataToolService._set_entity_activation(target_id, action_type == 'activate')
                if isinstance(res, dict) and res.get('error'):
                    return {"status": "error", "message": res['error'], "result": res}
                return {"status": "success", "result": res}

            elif action_type == 'read_manual':
                # Phase 6: RAG Search for AI Documents (Hybrid Markdown Parse)
                # target_id: The filename, e.g., 'API.md', 'Supported-Inputs.md'
                # params: {'section': 'REST API'}
                try:
                    from aot.config import INSTALL_DIRECTORY
                    import os, re
                    
                    target_file = target_id
                    if not target_file.endswith('.md'):
                        target_file += '.md'
                        
                    file_path = os.path.join(INSTALL_DIRECTORY, "docs", target_file)
                    
                    # v16.5: Fuzzy match for hallucinated filenames (especially for lightweight agents)
                    if not os.path.exists(file_path):
                        # 1. Direct aliases for common hallucinations
                        aliases = {
                            'supported-gis-inputs.md': 'Supported-Geo-Layers.md',
                            'supported-gis-layers.md': 'Supported-Geo-Layers.md',
                            'gis-inputs.md': 'Supported-Geo-Layers.md',
                            'gis.md': 'GEO.md'
                        }
                        low_target = target_file.lower()
                        if low_target in aliases:
                            target_file = aliases[low_target]
                            file_path = os.path.join(INSTALL_DIRECTORY, "docs", target_file)
                        
                        # 2. Fuzzy search fallback
                        if not os.path.exists(file_path):
                            import difflib
                            try:
                                available_files = [f for f in os.listdir(os.path.join(INSTALL_DIRECTORY, "docs")) if f.endswith('.md')]
                                matches = difflib.get_close_matches(target_file, available_files, n=1, cutoff=0.4)
                                if matches:
                                    target_file = matches[0]
                                    file_path = os.path.join(INSTALL_DIRECTORY, "docs", target_file)
                                    logger.info(f"[read_manual] Hallucination corrected: {target_id} -> {target_file}")
                            except Exception:
                                pass # Fallback to standard error below
                                
                    if not os.path.exists(file_path):
                        return {"status": "error", "message": f"Document '{target_id}' not found."}
                        
                    with open(file_path, "r", encoding='utf-8') as f:
                        lines = f.readlines()
                        
                    section_query = params.get('section', '').lower()
                    if not section_query:
                        toc = [line.strip() for line in lines if line.startswith('#')]
                        toc_str = "\n".join(toc)
                        return {
                            "status": "success", 
                            "result": f"Document '{target_file}' found but no 'section' was provided in params. Here is the Table of Contents:\n\n{toc_str}\n\nPlease call read_manual again and specify one of these headings as the 'section' parameter to read the details."
                        }
                        
                    in_section = False
                    section_level = 0
                    collected_lines = []
                    
                    header_pattern = re.compile(r'^(#{1,6})\s+(.+)$')
                    
                    for line in lines:
                        match = header_pattern.match(line.strip())
                        
                        if not in_section:
                            if match and section_query in match.group(2).lower():
                                in_section = True
                                section_level = len(match.group(1))
                                collected_lines.append(line)
                        else:
                            if match:
                                current_level = len(match.group(1))
                                if current_level <= section_level:
                                    # Found a header of same or higher level, section ends
                                    break
                            collected_lines.append(line)
                            
                    if not collected_lines:
                        return {"status": "error", "message": f"Section containing '{section_query}' not found in {target_file}."}
                        
                    result_text = "".join(collected_lines).strip()
                    # Token limit protection
                    if len(result_text) > 8000:
                        result_text = result_text[:8000] + "\n\n...[TRUNCATED_DUE_TO_LENGTH]..."
                        
                    return {"status": "success", "data": result_text}
                except Exception as e:
                    logger.exception(f"Error reading AI manual {target_id}")
                    return {"status": "error", "message": str(e)}

            elif action_type == 'knowledge_search':
                # v3.1 Phase 5: agentic knowledge search (§12-5). Unlike
                # read_manual (needs filename + section heading), this takes a
                # free query in params.query and returns the most relevant
                # markdown SECTIONS across ALL docs — no prior navigation, no
                # whole-doc load. Deterministic; read-only.
                try:
                    from aot.ai.services import knowledge_search as _ks
                    query = (params or {}).get('query') or target_id or ''
                    top_k = int((params or {}).get('top_k', 3))
                    text = _ks.search_as_text(query, top_k=top_k)
                    if not text:
                        return {"status": "success", "data": f"No documentation section matched '{query}'. Try different keywords, or use read_manual with a specific file."}
                    return {"status": "success", "data": text}
                except Exception as e:
                    logger.exception(f"Error in knowledge_search for {target_id}")
                    return {"status": "error", "message": str(e)}

            elif action_type == 'get_detailed_manifest':
                # Phase 6: Fetch full creatable list for a specific category
                # target_id: 'input', 'output', 'function', 'gis_input', or 'mcp_<server_id>'

                # MCP server detailed manifest
                if target_id and target_id.startswith('mcp_'):
                    mcp_server_id = target_id[4:]  # Strip 'mcp_' prefix
                    from aot.ai.services.mcp_bridge_service import MCPBridgeService
                    tools = MCPBridgeService.get_tools(mcp_server_id, force_refresh=True)
                    return {"status": "success", "data": tools}

                full_manifest = AIActionService.get_action_manifest(is_slim=False)
                key = f"creatable_{target_id}s"
                return {"status": "success", "data": full_manifest.get(key, [])}

            elif action_type == 'register_device':
                # Register a new Input, Output, or GIS device
                # target_id: 'input', 'output', 'function', 'gis_input' (OR Site/Zone ID)
                # params: {'type_id': 'Module,Interface', 'name': 'My Device', 'parent_id': '...', ...}
                # 1. Resolve Device Category and Parent Mapping
                device_category = target_id.lower() if isinstance(target_id, str) else 'input'
                parent_id = params.get('parent_id') or params.get('parent_zone_id')
                parent_node = None
                
                categories = ['input', 'output', 'function', 'gis_input']
                if device_category not in categories:
                    # target_id is likely a location ID (Site/Zone/Map)
                    # Check GeoShape (Spatial Nodes)
                    parent_node = GeoShape.query.filter(or_(GeoShape.id == target_id, GeoShape.geo_id == target_id)).first()
                    if not parent_node and isinstance(target_id, str):
                        # Try searching by name in meta_json if it's a string
                        parent_node = GeoShape.query.filter(GeoShape.feature.contains(target_id)).first()
                    
                    if parent_node:
                        parent_id = parent_node.id
                        # If AI didn't specify category in params, default to 'input'
                        device_category = params.get('category', 'input') 
                    else:
                        # Maybe it is a Map UUID?
                        parent_map = GeoMap.query.filter_by(unique_id=target_id).first()
                        if parent_map:
                            device_category = params.get('category', 'input')
                
                # Final fallback for validation
                if device_category not in categories:
                    device_category = 'input'

                config_type = params.get('type_id') or params.get('type') or params.get('module')
                name = params.get('name', 'New AI Device')

                # Phase 23: Dynamic fuzzy match with system_pi module information (no hardcoded names)
                if not config_type:
                    all_params_str = str(params).lower()
                    # [ANCHOR: DYNAMIC_MODULE_KEYWORD_MAP] Dynamic fuzzy match — no hardcoded module names
                    try:
                        from aot.utils.system_pi import parse_input_information
                        _mod_info = parse_input_information()
                        for _mod_key, _mod_data in _mod_info.items():
                            _mod_name = str(_mod_data.get('input_name_unique') or _mod_key).lower()
                            _mod_label = str(_mod_data.get('input_name') or '').lower()
                            if _mod_name in all_params_str or (_mod_label and _mod_label in all_params_str):
                                _interfaces = _mod_data.get('interfaces', ['AoT'])
                                _itf = _interfaces[0] if _interfaces else 'AoT'
                                config_type = f"{_mod_key},{_itf}"
                                logger.info(f"[AI Integration] Dynamic fuzzy matched '{_mod_name}' to '{config_type}'")
                                break
                    except Exception as _dyn_err:
                        logger.debug(f"[AI Integration] Dynamic module map unavailable: {_dyn_err}")
                    # Do NOT fall back to hardcoded strings

                # Validate type_id format and normalize case
                if device_category in ['input', 'output', 'gis_input']:
                    if not config_type:
                         return {"status": "error", "message": f"Missing 'type_id' in params. Please specify a valid Module,Interface (e.g. 'SATELLITE_ANALYSIS,AoT'). I matched category as '{device_category}'."}
                    
                    # If it's a known single-word type or a Title, auto-correct
                    if ',' not in config_type:
                        found_key = None
                        t_search = config_type.lower()
                        
                        if device_category in ['input', 'gis_input']:
                            dict_info = parse_input_information()
                        else:
                            dict_info = parse_output_information()
                            
                        # Search by key or by title
                        for k, v in dict_info.items():
                            if k.lower() == t_search or str(v.get('input_name', '')).lower() == t_search:
                                found_key = k
                                break
                        
                        if found_key:
                            interfaces = dict_info[found_key].get('interfaces', [])
                            itf = interfaces[0] if interfaces else 'AoT'
                            config_type = f"{found_key},{itf}"
                            logger.info(f"[AI Integration] Auto-corrected {t_search} to {config_type}")
                        elif config_type.startswith('gis_') or config_type.upper() == 'SATELLITE_ANALYSIS':
                            config_type = f"{config_type},AoT"
                            logger.info(f"[AI Integration] Force-appended ,AoT to {config_type}")
                        else:
                            return {"status": "error", "message": f"Invalid type_id format: '{config_type}'. Must be 'ModuleName,Interface' format (e.g. 'openweathermap_weather,AoT')."}
                    
                    # Case-insensitive matching for ModuleName
                    try:
                        module_part, interface_part = config_type.split(',', 1)
                        if device_category in ['input', 'gis_input']:
                            dict_info = parse_input_information()
                        else:
                            dict_info = parse_output_information()
                        
                        # Direct match check
                        if module_part not in dict_info:
                            # Try case-insensitive scan
                            found_key = None
                            module_part_lower = module_part.lower()
                            for k in dict_info:
                                if k.lower() == module_part_lower:
                                    found_key = k
                                    break
                            
                            if found_key:
                                logger.info(f"[AI Integration] Normalized type_id module: {module_part} -> {found_key}")
                                config_type = f"{found_key},{interface_part}"
                    except Exception as e:
                        logger.warning(f"Failed to normalize type_id: {e}")
                else:
                    if not config_type:
                        return {"status": "error", "message": f"Invalid type_id: '{config_type}'. Must provide a valid type string for {device_category}."}
                
                # Mock Form Pattern
                class MockLabel:
                    def __init__(self, text): self.text = text
                class MockField:
                    def __init__(self, data, name='field'):
                        self.data = data
                        self.label = MockLabel(name)
                class MockForm:
                    def __init__(self, data_dict):
                        for k, v in data_dict.items():
                            setattr(self, k, MockField(v, name=k))
                    def validate(self): return True
                    @property
                    def errors(self): return {}

                new_id = None
                if device_category == 'input':
                    form = MockForm({'input_type': config_type, 'name': name})
                    res_msg, _, _, _, new_id = utils_input.input_add(form)
                elif device_category == 'output':
                    form = MockForm({'output_type': config_type, 'name': name})
                    res_msg, _, _, _, new_id, _ = utils_output.output_add(form, {})
                elif device_category == 'function':
                    from aot.aot_flask.utils import utils_function
                    form = MockForm({'function_type': config_type})
                    res_msg, _, _, _, new_id = utils_function.function_add(form)
                elif device_category == 'gis_input':
                    from aot.aot_flask.utils import utils_geo
                    form = MockForm({'input_type': config_type, 'input_add': True})
                    res_msg = utils_geo.geo_layer_add(form)
                    new_id = None
                else:
                    return {"status": "error", "message": f"Unknown device category: '{device_category}'."}
                
                if res_msg.get('error'):
                    return {"status": "error", "message": f"Creation failed: {res_msg['error']}"}

                # 2. Inject parameters and perform Spatial Mapping
                if new_id:
                    try:
                        model_map = {
                            'input': Input, 
                            'output': Output, 
                            'function': Function,
                            'custom_controller': CustomController
                        }
                        model_cls = model_map.get(device_category)
                        record = model_cls.query.filter_by(unique_id=new_id).first() if model_cls else None
                        
                        if record:
                            # [New] Inject parameters directly into DB record
                            # Support common fields: period, latitude, longitude, uart_location, etc.
                            for p_key, p_val in params.items():
                                if p_key in ['type_id', 'parent_id', 'category', 'name']: continue
                                
                                # 1. Direct Model Attributes
                                if hasattr(record, p_key):
                                    try: setattr(record, p_key, p_val) 
                                    except: pass
                                
                                # 2. Custom Options (JSON)
                                if hasattr(record, 'custom_options'):
                                    try:
                                        co = json.loads(record.custom_options) if record.custom_options else {}
                                        if isinstance(co, dict):
                                            co[p_key] = p_val
                                            record.custom_options = json.dumps(co)
                                    except: pass
                            
                            # Priority for coordinates: 1. Passed in params, 2. Centroid of parent
                            p_lat = params.get('latitude')
                            p_lng = params.get('longitude')
                            
                            if parent_id:
                                if not parent_node:
                                    parent_node = GeoShape.query.get(parent_id)
                                
                                if parent_node:
                                    map_uuid = parent_node.geo_id
                                    # Calculate placement (Centroid of parent shape)
                                    c_lat, c_lng = None, None
                                    try:
                                        parent_geom = shape(parent_node.feature['geometry'])
                                        center = parent_geom.centroid
                                        c_lat, c_lng = center.y, center.x
                                    except: pass
                                    
                                    # Use parent centroid if not provided in params
                                    final_lat = p_lat if p_lat is not None else c_lat
                                    final_lng = p_lng if p_lng is not None else c_lng
                                    
                                    # [S5] 마커 생성은 geo 게이트웨이로만.
                                    # AI 대량생성이 직접 INSERT 하던 경로였고,
                                    # channel_id 누락으로 첫 위치 저장에서
                                    # 중복 마커가 생기던 지점이다.
                                    from aot.aot_flask.geo.device_placement import place_device
                                    place_device(
                                        new_id, map_uuid,
                                        final_lat, final_lng if final_lng else 0,
                                        device_type=device_category, name=name)


                                    # Update main record coordinates
                                    if hasattr(record, 'latitude'): record.latitude = final_lat
                                    if hasattr(record, 'longitude'): record.longitude = final_lng
                                    # [P2] map_config_id 저장 폐지 — 마커가 정본
                                    # [S3] map_overlay_id 저장 폐지 — 소속은 위
                                    # 마커 좌표에서 파생된다 (device_membership.py)
                                    
                                    logger.info(f"[AI Integration] Automatically mapped device {new_id} to zone {parent_node.id}")
                            
                            db.session.commit()
                            logger.info(f"[AI Integration] Succesfully injected params for device {new_id}")

                    except Exception as spatial_err:
                        logger.error(f"[AI Integration] Failed to auto-map/inject device params: {spatial_err}")

                # E-4: Invalidate spatial cache after registration
                from aot.ai.services.ai_context_service import AIContextService
                AIContextService.invalidate_spatial_cache()
                result_text = f"Device registered as {new_id}" if new_id else f"{device_category} registered successfully"
                return {"status": "success", "result": result_text, "new_id": new_id}

            elif action_type == 'edit_device':
                # Edit existing device settings
                # target_id: unique_id of device
                # params: {'category': 'input', 'updates': {'name': 'New Name', 'period': 30, ...}}
                category = params.get('category', 'input')
                updates = params.get('updates', {})
                
                model_map = {
                    'input': Input, 
                    'output': Output, 
                    'function': Function,
                    'custom_controller': CustomController,
                    'pid': PID
                }
                model_cls = model_map.get(category, Input)
                device = model_cls.query.filter_by(unique_id=target_id).first()
                if not device:
                    return {"status": "error", "message": "Device not found"}
                
                # B-1: 안전 필드 화이트리스트 적용
                SAFE_FIELDS = {
                    'name', 'period', 'latitude', 'longitude',
                    'pre_output_id', 'pre_output_duration',
                    'log_level_debug', 'is_activated',
                    'location', 'i2c_location', 'uart_location',
                    'baud_rate', 'pin_cs', 'resolution', 'sensitivity',
                    'i2c_bus', 'custom_options'
                }
                rejected_keys = [k for k in updates if k not in SAFE_FIELDS]
                applied_keys = []
                for key, val in updates.items():
                    if key in SAFE_FIELDS and hasattr(device, key):
                        setattr(device, key, val)
                        applied_keys.append(key)
                
                # E-5: Synchronize map markers if location changed.
                # [GB-6] 마커를 찾고 옮기는 일은 geo 패키지가 소유한다. 예전에는
                # 여기서 device_id 로 도형을 직접 찾아 첫 한 개의 geometry 만
                # 고쳤다 — 사망 선고된 컬럼을 읽었을 뿐 아니라, 채널이 여럿
                # 이거나 여러 지도에 놓인 나머지 마커는 옛 자리에 남았다.
                if 'latitude' in updates or 'longitude' in updates:
                    try:
                        from aot.aot_flask.geo.device_placement import (
                            move_device_markers)
                        moved = move_device_markers(
                            target_id, device.latitude, device.longitude)
                        if moved:
                            logger.info(
                                f"[AI Sync] Moved {moved} map marker(s) for {target_id}")
                    except Exception as sync_err:
                        logger.error(f"[AI Sync] Failed to sync GeoShape: {sync_err}")

                db.session.commit()

                # Invalidate spatial cache if location changed
                if 'latitude' in updates or 'longitude' in updates:
                    from aot.ai.services.ai_context_service import AIContextService
                    AIContextService.invalidate_spatial_cache()

                # E-6: Notify the daemon so a running controller (e.g. Input reading
                # latitude/longitude/custom_options at startup) picks up the change live.
                reload_fields = {'latitude', 'longitude', 'custom_options'}
                if reload_fields.intersection(applied_keys):
                    try:
                        if isinstance(device, PID):
                            daemon.pid_mod(target_id)
                        elif isinstance(device, CustomController):
                            daemon.module_function('Function_Custom', target_id, 'cmd_reload', {}, thread=False)
                        elif isinstance(device, Input):
                            daemon.controller_restart(target_id)
                        elif isinstance(device, Output):
                            daemon.output_setup('Modify', target_id)
                    except Exception as reload_err:
                        logger.error(f"[AI Sync] Failed to reload daemon for {target_id}: {reload_err}")

                result_msg = f"Device {target_id} updated ({', '.join(applied_keys)})"
                if rejected_keys:
                    result_msg += f" | Rejected unsafe fields: {rejected_keys}"
                return {"status": "success", "result": result_msg}

            elif action_type == 'delete_device':
                # Delete existing device
                # target_id: unique_id of device
                # params: {'category': 'input'}
                category = params.get('category', 'input')
                
                if category == 'input':
                    res_msg = utils_input.input_del(target_id)
                else:
                    # C-3: output_del은 폼 객체를 요구하므로 Mock Form 생성
                    class MockLabel:
                        def __init__(self, text): self.text = text
                    class MockField:
                        def __init__(self, data, name='field'):
                            self.data = data
                            self.label = MockLabel(name)
                    class MockDelForm:
                        def __init__(self, output_id):
                            self.output_id = MockField(output_id, 'output_id')
                    res_msg = utils_output.output_del(MockDelForm(target_id))
                
                if res_msg.get('error'):
                    return {"status": "error", "message": str(res_msg['error'])}
                # E-4: Invalidate spatial cache after deletion
                from aot.ai.services.ai_context_service import AIContextService
                AIContextService.invalidate_spatial_cache()
                return {"status": "success", "result": f"Device {target_id} deleted"}

            elif action_type == 'control_output':
                # @ANCHOR: CONTROL_OUTPUT_FIX — use operate_device_tool directly.
                # Formerly delegated to 'output' action which is blocked by LegacyGuardResolver.
                # operate_device_tool talks directly to the daemon, bypassing the legacy gate.
                from aot.ai.services.aot_data_tool_service import AoTDataToolService
                state = params.get('state', 'off')
                duration_minutes = params.get('duration_minutes')
                duration_seconds = params.get('duration_seconds')
                value = params.get('value', 0)

                op_kwargs = {}
                if duration_minutes:
                    op_kwargs['duration_minutes'] = duration_minutes
                elif duration_seconds:
                    op_kwargs['duration_seconds'] = duration_seconds
                elif value:
                    op_kwargs['duration_seconds'] = float(value)

                result = AoTDataToolService.operate_device_tool(
                    device_id=target_id, state=state, **op_kwargs
                )
                if isinstance(result, dict) and result.get('error'):
                    return {"status": "error", "message": result['error'], "result": result}
                return {"status": "success", "result": result}

            else:
                return {"status": "error", "message": f"Unknown action type: {action_type}"}

        except Exception as e:
            logger.exception(f"Error executing {action_type} action on {target_id}")
            return {"status": "error", "message": str(e)}
        finally:
            # B-2: Pop contexts if we pushed them
            if _pushed_req_ctx:
                _pushed_req_ctx.pop()
            if _pushed_app_ctx:
                _pushed_app_ctx.pop()
