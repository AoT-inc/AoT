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

# Virtual tool definitions exposed to the LLM prompt
VIRTUAL_TOOLS = [
    {
        "tool_name": "get_sensor_detail",
        "description": "Query detailed sensor history for a specific location/device. Returns time-series readings with min/max/avg statistics.",
        "input_schema": {
            "type": "object",
            "properties": {
                "loc_id": {"type": "string", "description": "unique_id of the Input device or GeoShape zone"},
                "sensor_type": {"type": "string", "description": "Filter by measurement type (e.g. temperature, humidity). Optional."},
                "time_range": {"type": "string", "description": "Duration string: '1h', '24h', '7d'. Default: '24h'"}
            },
            "required": ["loc_id"]
        }
    },
    {
        "tool_name": "get_spatial_tree",
        "description": "Retrieve the spatial hierarchy (Site > Zone > Device) tree structure with optional depth and type filtering.",
        "input_schema": {
            "type": "object",
            "properties": {
                "depth": {"type": "integer", "description": "Maximum tree depth to return. Default: 2"},
                "filter_type": {"type": "string", "description": "Filter nodes by type (e.g. 'zone', 'device'). Optional."}
            }
        }
    },
    {
        "tool_name": "search_devices",
        "description": "Search for devices (inputs, outputs, cameras) by name or type keyword.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search keyword for device name or type"}
            },
            "required": ["query"]
        }
    },
    {
        "tool_name": "get_device_list",
        "description": "List all registered devices (inputs, outputs, cameras) in the AoT system. Use this when the user asks for a full device listing without a specific keyword.",
        "input_schema": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "tool_name": "get_energy_report",
        "description": "Generate an energy usage analysis report for a specific period and/or zone.",
        "input_schema": {
            "type": "object",
            "properties": {
                "period": {"type": "string", "description": "Analysis period: 'daily', 'weekly', 'monthly'. Default: 'daily'"},
                "zone_id": {"type": "string", "description": "Filter by zone unique_id. Optional (omit for all zones)."}
            }
        }
    },
    {
        "tool_name": "operate_device",
        "description": "[INTENT A] Direct physical control of devices. Use this for immediate operations like opening valves or turning on lights.",
        "input_schema": {
            "type": "object",
            "properties": {
                "device_id": {"type": "string", "description": "unique_id of the output device"},
                "state": {"type": "string", "enum": ["on", "off", "set_value"], "description": "Target state"},
                "value": {"type": "number", "description": "Numeric value for PWM/Setpoints (optional)"}
            },
            "required": ["device_id", "state"]
        }
    },
    {
        "tool_name": "add_schedule",
        "description": "[일반 작업/메모 기록용] 사람이 수행할 작업 일정이나 메모를 기록합니다. 제초작업, 점검, 청소 등 수동 작업에 사용하세요. 시스템 제어(밸브, 펌프 등)는 schedule_device_control을 사용하세요.",
        "input_schema": {
            "type": "object",
            "properties": {
                "date": {"type": "string", "description": "Target date (YYYY-MM-DD)"},
                "time": {"type": "string", "description": "Target time (HH:MM). Default '09:00'"},
                "content": {"type": "string", "description": "Description of the work or schedule"},
                "worker": {"type": "string", "description": "Name of the person assigned (optional)"},
                "tags": {"type": "string", "description": "Comma-separated tags (optional). If not provided, spatial tags are automatically extracted from content."}
            },
            "required": ["date", "content"]
        }
    },
    {
        "tool_name": "search_notes",
        "description": "[노트 읽기] 노트·메모·작업기록을 조회합니다. 읽기 전용이라 승인 불필요(요약은 데이터 가공). 특정 구역·장치에 붙은 노트를 읽거나 요약하려면(예: '3-1 구역 노트 요약') 반드시 target_name에 그 위치/장치 이름을 넣으세요 — 노트는 target_id로 엔티티에 붙어 있고 본문에 구역명이 없을 수 있어 키워드 검색으로는 못 찾습니다. query는 자유 키워드 검색용.",
        "input_schema": {
            "type": "object",
            "properties": {
                "target_name": {"type": "string", "description": "노트가 붙은 위치/장치 이름(예: '3-1', '1포장 1-1', '밸브1'). 구역·장치 노트 조회/요약 시 사용."},
                "query": {"type": "string", "description": "자유 키워드 검색(예: '콩밭', '제초'). target_name과 함께 주면 그 엔티티 내 추가 필터."},
                "category": {"type": "string", "description": "카테고리 필터: 'schedule'(일정), 'general'(일반) 등. 생략 시 전체."},
                "limit": {"type": "integer", "description": "최대 반환 건수 (기본 10)"}
            }
        }
    },
    {
        "tool_name": "schedule_device_control",
        "description": "[시스템 제어 예약 전용] 밸브, 펌프, 스프링클러 등 시스템 장치의 제어를 특정 시간에 예약합니다. 사용자 승인 후 스케줄러에 등록됩니다.",
        "input_schema": {
            "type": "object",
            "properties": {
                "device_id": {"type": "string", "description": "unique_id of the output device to control"},
                "scheduled_time": {"type": "string", "description": "ISO 8601 format datetime (e.g., '2026-02-27T09:00:00+09:00')"},
                "state": {"type": "string", "enum": ["on", "off"], "description": "Target state"},
                "duration_minutes": {"type": "number", "description": "Duration in minutes (optional, default: 5)"}
            },
            "required": ["device_id", "scheduled_time", "state"]
        }
    },
    {
        "tool_name": "get_weather",
        "description": "포장 또는 구역의 현재 기상 정보를 조회합니다. 기온, 습도, 풍속, 강수량, 날씨 상태를 반환합니다.",
        "input_schema": {
            "type": "object",
            "properties": {
                "zone_name": {
                    "type": "string",
                    "description": "조회할 포장 또는 구역 이름 (예: '1포장', '2포장'). zone_id 대신 사용 가능."
                },
                "zone_id": {
                    "type": "string",
                    "description": "GeoShape의 unique_id. zone_name 대신 사용 가능."
                }
            }
        }
    },
    {
        "tool_name": "get_cumulative_status",
        "description": "EnvCoordinator 함수의 DLI(일적산광량)·GDD(누적온도) 일별 누적 상태와 부채 현황을 조회합니다. 광량·온도 목표 달성 여부와 보상 제안을 확인할 때 사용하세요.",
        "input_schema": {
            "type": "object",
            "properties": {
                "function_id": {
                    "type": "string",
                    "description": "EnvCoordinator 함수의 unique_id"
                },
                "days": {
                    "type": "integer",
                    "description": "조회할 최근 일수 (기본값: 7)"
                }
            },
            "required": ["function_id"]
        }
    },
    {
        "tool_name": "get_system_update_status",
        "description": "AoT 소프트웨어(시스템)의 업데이트 가용 여부를 확인합니다. 현재 설치 버전을 GitHub 최신 릴리스와 비교하여 반환합니다. 사용자가 '시스템 업데이트', '새 버전', '현재 버전'을 물으면 사용하세요. 읽기 전용.",
        "input_schema": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "tool_name": "create_note",
        "description": "메모/노트를 즉시 생성·저장합니다(날짜 없는 메모 — 날짜 있는 작업은 add_schedule 사용). 승인 불필요. AoT에는 '노트 위젯' 같은 건 없고, 모든 장치·대지·구역 도형마다 각자의 노트가 있어 엔티티별로 조회됩니다. 노트는 대상에 부착되어야만 그 엔티티에서 보입니다. 따라서 사용자가 '1포장 1-1에', '밸브1에' 기록해달라고 하면 반드시 target_name에 그 위치/장치 이름을 넣으세요(도구가 실제 대상으로 해석해 부착). '생성하겠습니다'라고 말만 하지 말고 이 도구를 실제로 호출하세요.",
        "input_schema": {
            "type": "object",
            "properties": {
                "note": {"type": "string", "description": "노트 본문 내용"},
                "name": {"type": "string", "description": "노트 제목(짧게). 선택."},
                "target_name": {"type": "string", "description": "노트를 붙일 위치/장치 이름(예: '1포장 1-1', '밸브1'). 도구가 unique_id로 해석해 부착. 노트가 보이려면 강력 권장."},
                "tags": {"type": "string", "description": "태그(쉼표 구분). 선택."},
                "category": {"type": "string", "description": "분류(기본 'general'). 선택."},
                "target_id": {"type": "string", "description": "이미 아는 경우 대상 unique_id 직접 지정(target_name 대신). 선택."},
                "target_type": {"type": "string", "description": "연결 대상 유형(예: 'zone','input','output'). 선택."}
            },
            "required": ["note"]
        }
    },
    {
        "tool_name": "list_notices",
        "description": "공지사항 게시글 목록(제목·고정·날짜)을 조회합니다. 읽기 전용.",
        "input_schema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "description": "최대 반환 건수(기본 10)"}
            }
        }
    }
]


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

        # Fallback to existing AoTDataToolService for static virtual tools
        try:
            from aot.ai.services.aot_data_tool_service import AoTDataToolService
            return AoTDataToolService.execute(tool_name, arguments)
        except Exception as exc:
            logger.error(f"[AoTSystemMCP] DataToolService dispatch error for '{tool_name}': {exc}")
            return {"status": "error", "message": str(exc)}
