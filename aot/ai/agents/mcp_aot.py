# coding=utf-8
import logging
import json
from flask_babel import lazy_gettext as lg

from aot.ai.agents.base_ai import AbstractAI

logger = logging.getLogger(__name__)

AI_INFORMATION = {
    "engine_type": "mcp_aot",
    "ai_manufacturer": "AoT System Expert",
    "ai_name": "AoT System Expert",
    "ai_name_unique": "mcp_aot",
    "description": lg("AoT System Specialist. Queries sensor history, spatial hierarchy, device search, and energy reports via internal system tools."),
    "specialty": "AoT internal sensor history, device search, spatial hierarchy, energy analysis",
    "system_prompt": (
        "You are the AoT System Expert, a specialized AI for managing and monitoring the AoT (AI of Things) platform.\n\n"
        "Your Role:\n"
        "1. Bridge the gap between user questions and the physical infrastructure (Sites, Zones, Devices).\n"
        "2. Provide fact-based, precise information about sensor states, history, and spatial relationships.\n"
        "3. Help users analyze energy usage and facility performance.\n\n"
        "Key Capabilities & Tools:\n"
        "- **Manual Work vs System Control**: \n"
        "  - For human tasks like weeding (제초), cleaning, inspection (점검), use 'add_schedule'. These are NOT device operations.\n"
        "  - For device operations (valves, pumps), use 'operate_device' (immediate) or 'schedule_device_control' (future).\n"
        "- **Spatial Hierarchy**: Understand Sites and Zones. Use 'get_spatial_tree' for context.\n"
        "- **Sensor History**: Use 'get_sensor_detail' for historical analysis."
    ),
    "is_mcp": True,
    "default_endpoint": "",
    "auth_methods": ["no_auth"],
    "auth_link": "https://aot-inc.github.io/AoT/ai/overview/",
    "models": [
        {"label": "Virtual MCP (Internal)", "value": "virtual_mcp"}
    ],
    "custom_options": [
        {"id": "reasoning_entry_id", "name": "Reasoning Brain (AI Service)", "type": "select", "choices": [], "default": ""},
        {"id": "llm_model", "name": "Specific Model (Optional Brain Override)", "type": "text", "default": ""},
    ]
}

# Virtual tool definitions exposed to the LLM prompt.
# SSOT: this list is now DERIVED from the tool registry (aot/ai/services/
# tool_registry.py :: virtual_tools()) — it used to be hand-maintained here and
# drifted from the registry (advertising tools the stdio MCP server could not
# dispatch). Add/edit an MCP tool in tool_registry._MCP_TOOL_PAYLOADS, not here.
from aot.ai.services.tool_registry import virtual_tools as _virtual_tools

VIRTUAL_TOOLS = _virtual_tools()


def _get_request_locale() -> str:
    """[BUG_03] Safely extract browser locale from Accept-Language header.
    Returns empty string if no Flask request context is active
    (e.g. background threads, daemon startup).
    """
    try:
        from flask import has_request_context, request
        if has_request_context():
            best = request.accept_languages.best
            return best if best else ''
    except Exception:
        pass
    return ''


class AoTSystemMCP_AI(AbstractAI):
    """
    AoT System Data Expert Worker.
    Uses a virtual MCP pattern: no subprocess, calls AoTDataToolService directly.
    Inherits AbstractAI directly (not BaseMCP_AI) to avoid subprocess overhead.

    @phase active
    @stability stable
    @dependency BrainResolver, AoTDataToolService, AoTNativeToolEngine
    """

    def __init__(self, agent_config):
        super().__init__(agent_config)

        try:
            options = json.loads(agent_config.custom_options_json) if agent_config.custom_options_json else {}
        except Exception:
            options = {}

        self.reasoning_entry_id = options.get('reasoning_entry_id', '')
        self.llm_model = options.get('llm_model', '')

        # Initialize the internal LLM brain (reuses BaseMCP_AI pattern)
        self._brain = self._init_brain(agent_config)

        # Inject virtual tool instructions into the brain's system prompt
        if self._brain:
            tool_instruction = self._build_tool_instruction(agent_config.unique_id)
            orig_system = self._brain.system_prompt or ""
            if tool_instruction not in orig_system:
                self._brain.system_prompt = orig_system + tool_instruction

    def _init_brain(self, agent_config):
        """Initialize the LLM reasoning engine via BrainResolver."""
        from aot.ai.services.brain_resolver import BrainResolver
        brain_ctx = BrainResolver.resolve(
            skeleton_id=agent_config.unique_id,
            preferred_entry_id=self.reasoning_entry_id
        )
        if not brain_ctx:
            logger.error("[AoTSystemMCP] No reasoning brain available. Set 'Reasoning Brain' in agent options.")
            return None

        try:
            engine = brain_ctx.engine_instance

            if not self.llm_model:
                # Inherit model name from LLM entry if agent has MCP default
                if engine.model_name in ['virtual_mcp', 'default']:
                    engine.model_name = brain_ctx.model_name
            else:
                engine.model_name = self.llm_model
                
            # [BUG_03] Locale injection — ABSOLUTE TOP of system_prompt
            locale = _get_request_locale()
            if locale:
                locale_directive = f"SYSTEM LOCALE: {locale}. Respond ONLY in this language. Use UTF-8 encoding.\n\n"
                engine.system_prompt = locale_directive + (engine.system_prompt or "")

            return engine
        except Exception as e:
            logger.error(f"[AoTSystemMCP] Failed to init brain: {e}")
            return None

    @staticmethod
    def _build_tool_instruction(agent_id):
        """Build the virtual tool instruction block for the system prompt.
        [TASK_30/Pillar1] Includes both static VIRTUAL_TOOLS and dynamic AoTNativeToolEngine tools.
        """
        all_tools = list(VIRTUAL_TOOLS)
        try:
            from aot.ai.services.aot_native_tool_engine import AoTNativeToolEngine
            native_tools = AoTNativeToolEngine.get_tools()
            existing_names = {t["tool_name"] for t in all_tools}
            for nt in native_tools:
                if nt.get("name") not in existing_names:
                    all_tools.append({
                        "tool_name": nt["name"],
                        "description": nt.get("description", ""),
                        "input_schema": nt.get("inputSchema", {}),
                    })
        except Exception:
            pass  # Native engine not yet available (pre-migration)

        tool_descriptions = []
        for tool in all_tools:
            schema_str = json.dumps(tool["input_schema"], ensure_ascii=False)
            tool_descriptions.append(
                f"  - **{tool['tool_name']}**: {tool['description']}\n"
                f"    Parameters: {schema_str}"
            )
        tools_block = "\n".join(tool_descriptions)

        return (
            f"\n\n### [Specialist Context: AoT System Data Expert] ###\n"
            f"You are a specialized expert for querying AoT internal system data.\n"
            f"You have access to the following Virtual MCP tools:\n"
            f"{tools_block}\n\n"
            f"To call a tool, include it in your `actions` array with:\n"
            f"  action_type: 'virtual_tool_call'\n"
            f"  target_id: '{agent_id}'\n"
            f"  params: {{\"tool_name\": \"<name>\", \"arguments\": {{<args>}}}}\n"
            f"These tools are auto-executed and results are fed back to you immediately.\n"
            f"When the user's question requires historical sensor data, device search, "
            f"spatial hierarchy details, or energy analysis, you MUST use these tools "
            f"instead of guessing from context.\n\n"
            f"### [SCHEMA OVERRIDE — READ LAST, HIGHEST PRIORITY] ###\n"
            f"The user prompt may contain a generic JSON schema listing action_type options such as\n"
            f"'output', 'read_manual', 'mcp_tool_call', 'pid', 'function', etc.\n"
            f"IGNORE those action_type options entirely in this specialist context.\n"
            f"The ONLY valid action_type you may use is 'virtual_tool_call'.\n"
            f"The ONLY valid tool_names for data retrieval are: "
            f"{', '.join(t['tool_name'] for t in VIRTUAL_TOOLS)}.\n"
            f"Do NOT use 'read_manual', 'get_sensor_reading', or 'list_available_devices' as a tool_name.\n"
            f"Tool selection rules:\n"
            f"  - For current weather/temperature/climate queries (기상, 온도, 기온, 날씨, 습도, 풍속 etc.): use 'get_weather' with zone_name=<name>.\n"
            f"  - For historical sensor data or time-series analysis: use 'get_sensor_detail' with loc_id=<zone_unique_id>.\n"
            f"  - 'get_weather' accepts zone_name (e.g. '1포장') directly — do NOT require a UUID for weather queries.\n"
        )

    @classmethod
    def get_tools(cls):
        """
        Expose virtual tools for the AI Planner/Router discovery.
        [TASK_30/Pillar1] Merges static VIRTUAL_TOOLS with dynamic AoTNativeToolEngine tools.
        """
        tools = list(VIRTUAL_TOOLS)
        try:
            from aot.ai.services.aot_native_tool_engine import AoTNativeToolEngine
            native_tools = AoTNativeToolEngine.get_tools()
            # Avoid duplicates by name
            existing_names = {t["tool_name"] for t in tools}
            for nt in native_tools:
                if nt.get("name") not in existing_names:
                    # Normalize schema key: NativeToolEngine uses 'name', VIRTUAL_TOOLS uses 'tool_name'
                    tools.append({
                        "tool_name": nt["name"],
                        "description": nt.get("description", ""),
                        "input_schema": nt.get("inputSchema", {}),
                    })
            logger.debug(f"[AoTSystemMCP] get_tools: {len(tools)} total ({len(native_tools)} native)")
        except Exception as exc:
            logger.warning(f"[AoTSystemMCP] AoTNativeToolEngine unavailable: {exc}")
        return tools

    def run_reasoning(self, context, goal):
        if not self._brain:
            return {"insight": "Reasoning brain not initialized for AoT System Expert.", "actions": []}
        # [IMP_03] Re-apply locale on every request to handle agent instance reuse
        locale = _get_request_locale()
        if locale:
            current_prompt = self._brain.system_prompt or ""
            if not current_prompt.startswith("SYSTEM LOCALE:"):
                directive = f"SYSTEM LOCALE: {locale}. Respond ONLY in this language. Use UTF-8 encoding.\n\n"
                self._brain.system_prompt = directive + current_prompt
        logger.info("[AoTSystemMCP] Delegating reasoning to brain...")
        return self._brain.run_reasoning(context, goal)

    def parse_actions(self, raw_response):
        if not self._brain:
            return []
        return self._brain.parse_actions(raw_response)

    @staticmethod
    def execute_virtual_tool(tool_name: str, arguments: dict) -> dict:
        """
        [TASK_30/Pillar1] Dispatch virtual_tool_call to the correct handler.
        Static VIRTUAL_TOOLS are handled by AoTDataToolService.
        Native tools (list_available_devices, get_sensor_reading, set_output_state)
        are delegated to AoTNativeToolEngine.
        """
        NATIVE_TOOL_NAMES = {"list_available_devices", "get_sensor_reading", "set_output_state"}

        if tool_name in NATIVE_TOOL_NAMES:
            try:
                from aot.ai.services.aot_native_tool_engine import AoTNativeToolEngine
                result = AoTNativeToolEngine.execute(tool_name, arguments)
                # [IMP_01] Semantic tagging: annotate raw sensor value before returning to LLM
                if tool_name == 'get_sensor_reading' and isinstance(result, dict) and 'value' in result:
                    device_id = arguments.get('device_id', '')
                    if device_id:
                        from aot.ai.services.ai_action_service import AIActionService
                        result['value'] = AIActionService._tag_observation(result['value'], device_id)
                return result
            except Exception as exc:
                logger.error(f"[AoTSystemMCP] NativeToolEngine dispatch error: {exc}")
                return {"status": "error", "message": str(exc)}

        # Static virtual tools → dispatch via the SSOT tool registry. (The old
        # code called AoTDataToolService.execute(), which does not exist, so this
        # branch always errored; build_tool_map resolves each tool's real handler.)
        try:
            from aot.ai.services.tool_registry import build_tool_map
            handler = build_tool_map().get(tool_name)
            if handler is None:
                return {"status": "error", "message": f"Unknown virtual tool: {tool_name}"}
            _meta = {"tool_name", "server_id", "agent_unique_id", "context"}
            kwargs = {k: v for k, v in (arguments or {}).items() if k not in _meta}
            return handler(**kwargs)
        except Exception as exc:
            logger.error(f"[AoTSystemMCP] DataToolService dispatch error for '{tool_name}': {exc}")
            return {"status": "error", "message": str(exc)}
