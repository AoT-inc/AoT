# coding=utf-8
import logging
import json
import os
import re
from abc import ABC, abstractmethod

import requests


logger = logging.getLogger(__name__)


class AbstractAI(ABC):
    """
    Standard interface for all AI engines (Gemini, OpenAI, LocalLLM, etc.)
    integrated into the AoT framework. Defines the contract for run_reasoning,
    parse_actions, and common utilities (context budget, prompt building, JSON extraction).

    @phase active
    @stability stable
    @dependency AIAgentService, AIGlobalSettings, AIDomainGlossary
    """
    # Whether this engine accepts image inputs (multimodal). Vision-capable
    # providers override this to True and consume ai_request_context.get_attachments().
    supports_vision = False
    # 이 엔진이 도구를 tools[] 로 따로 보내는가(function_declarations / tool_use).
    # False 면 프롬프트의 capabilities 가 유일한 채널이므로 절대 빼면 안 된다.
    supports_native_tools = False

    def __init__(self, agent_config):
        self.agent_config = agent_config
        self.agent_id = agent_config.unique_id
        self.name = agent_config.name

        # Connection & Auth (Favor scalars from config if present, fallback to entry)
        self.api_endpoint = getattr(agent_config, 'api_endpoint', None)
        self.auth_type = getattr(agent_config, 'auth_type', None)
        self.auth_id = getattr(agent_config, 'auth_id', None)
        self.api_key = getattr(agent_config, 'api_key', None)
        self.model_type = getattr(agent_config, 'model_type', None)
        self.model_name = getattr(agent_config, 'model_name', None)

        entry = getattr(agent_config, 'entry', None)
        if entry:
            self.api_endpoint = self.api_endpoint or entry.api_endpoint
            self.auth_type = self.auth_type or entry.auth_type
            self.auth_id = self.auth_id or entry.auth_id
            self.api_key = self.api_key or entry.api_key
            self.model_type = self.model_type or entry.model_type
            self.model_name = self.model_name or entry.model_name
        
        if not self.model_type:
            raise ValueError(f"AI Agent '{self.name}' has no linked Entry (Service). Register an AI Service first.")
        
        # v20.0: Intelligent prompt fallback from engine presets
        self.system_prompt = agent_config.system_prompt
        _GENERIC_PROMPTS = {
            'You are a helpful assistant.',
            'You are a helpful AI assistant.',
        }
        if not self.system_prompt or self.system_prompt.strip() in _GENERIC_PROMPTS:
            try:
                from aot.ai.services.ai_agent_service import AIAgentService
                # v20.1: Try role-based preset first (pipeline_role → worker/executor/router/…)
                pipeline_role = getattr(agent_config, 'pipeline_role', None)
                if pipeline_role:
                    role_presets = AIAgentService.get_role_presets()
                    role_prompt = role_presets.get(pipeline_role, {}).get('system_prompt')
                    if role_prompt:
                        self.system_prompt = role_prompt
                        logger.info(f"[{self.name}] Using role preset system prompt for pipeline_role={pipeline_role}")

                # Fallback to engine-level preset when role preset is unavailable
                if not self.system_prompt or self.system_prompt.strip() in _GENERIC_PROMPTS:
                    preset_info = AIAgentService.get_engine_info(self.model_type)
                    if preset_info and preset_info.get('system_prompt'):
                        self.system_prompt = preset_info.get('system_prompt')
                        logger.info(f"[{self.name}] Using engine preset system prompt for {self.model_type}")
            except Exception as e:
                logger.warning(f"Failed to fetch preset info for {self.model_type}: {e}")

        # Final fallback
        if not self.system_prompt:
            self.system_prompt = "You are a helpful AI assistant for the AoT (AI of Things) platform."

        self.temperature = agent_config.temperature
        self.model_tier = getattr(agent_config, 'model_tier', 'standard')
        # @ANCHOR: TIER_TIMEOUT [2026-03-25] — dynamic timeout per model tier
        _TIER_TIMEOUT = {'lightweight': 20, 'standard': 45, 'heavy': 90}
        self.timeout = _TIER_TIMEOUT.get(self.model_tier, 45)

    def get_context_budget(self):
        """
        v12.6: Tier-based input character limits (guardrail).
        Returns max allowed characters for the prompt.
        """
        budgets = {
            'lightweight': 20000,    # ~5k tokens
            'standard': 100000,      # ~25k tokens
            'heavy': 2000000         # ~500k tokens (Gemini)
        }
        return budgets.get(self.model_tier, 300000)
    def get_max_output_tokens(self):
        """
        Returns the maximum output tokens (max_tokens) for the API call.
        Subclasses should override this to stay within TPM/RPM limits.
        """
        budgets = {
            'lightweight': 512,
            'standard': 2048,
            'heavy': 4096
        }
        tier_limit = budgets.get(self.model_tier, 2048)
        db_val = getattr(self.agent_config, 'max_tokens', 0)
        
        if self.model_tier == 'lightweight':
            # Strictly limit for lightweight to avoid TPM issues
            return min(db_val, tier_limit) if db_val > 0 else tier_limit
            
        return db_val if db_val > 0 else tier_limit

    # Native tool-calling loops (Anthropic's fc_turn while-loop, Gemini's
    # equivalent) append each tool's raw result to the running message/contents
    # list with NO length guard — unlike the initial prompt, which _build_prompt()
    # truncates via get_context_budget(), that guard never runs again once the
    # loop starts. A single unfiltered tool call (e.g. list_plots with no
    # map_id, or get_zone_sensor_summary with no measurement_type) can return
    # tens of thousands of characters, and because these APIs are stateless each
    # subsequent fc_turn resends the WHOLE accumulated history — 2-3 such turns
    # can burn a request's entire token budget on data the model only needed to
    # summarize, not quote in full. truncate_tool_result_json() caps each
    # individual tool result before it enters that loop.
    TOOL_RESULT_MAX_CHARS = {
        'lightweight': 4000,
        'standard': 12000,
        'heavy': 40000,
    }

    def truncate_tool_result_json(self, exec_result):
        """Serialize a tool's exec_result to JSON, capped to this engine's tier budget.

        Fits as-is → returned unchanged. Too large → top-level list fields (the
        usual source of bloat: rows/plots/zones/sensors arrays) are shrunk first,
        with a note telling the model how many items were dropped and how to
        narrow its next call, so it doesn't mistake the truncated slice for the
        complete answer. Only if that still doesn't fit does it fall back to a
        hard string cut.
        """
        max_chars = self.TOOL_RESULT_MAX_CHARS.get(self.model_tier, 12000)
        raw = json.dumps(exec_result, ensure_ascii=False, default=str)
        if len(raw) <= max_chars:
            return raw

        if isinstance(exec_result, dict):
            shrunk = dict(exec_result)
            list_keys = [k for k, v in shrunk.items() if isinstance(v, list) and v]
            # Largest offenders first so one shrink pass is usually enough.
            list_keys.sort(key=lambda k: -len(json.dumps(shrunk[k], ensure_ascii=False, default=str)))
            for key in list_keys:
                original = shrunk[key]
                keep = max(1, len(original) // 4)
                if keep >= len(original):
                    continue
                shrunk[key] = original[:keep]
                shrunk[f"_{key}_truncated"] = (
                    f"showing {keep} of {len(original)} items - response was too large for this "
                    "request's token budget. Narrow your filters (map_id, zone_ids, measurement_type, "
                    "on date, etc.) and call the tool again for the rest instead of assuming this is everything."
                )
                raw = json.dumps(shrunk, ensure_ascii=False, default=str)
                if len(raw) <= max_chars:
                    return raw

        logger.warning(
            f"[{self.__class__.__name__}] tool result still {len(raw)} chars after list-shrink, "
            f"hard-truncating to {max_chars}"
        )
        return raw[:max_chars] + "\n...[TRUNCATED: response cut off to control token usage; narrow your filters and call again for the rest]"

    @abstractmethod
    def run_reasoning(self, context, goal):
        """Execute a reasoning cycle using the provided context and goal.

        Should return a dictionary containing:
        - insight: Natural language explanation
        - actions: List of proposed action dictionaries

        @phase active
        """
        pass

    @abstractmethod
    def parse_actions(self, raw_response):
        """Parse the raw AI response into structured AoT actions.

        @phase active
        """
        pass

    def summarize_context(self, context):
        """Prepare context for the AI engine (passthrough in base class).

        @phase active
        """
        return context

    # ------------------------------------------------------------------
    # Common utilities for real API calls
    # ------------------------------------------------------------------

    def _build_prompt(self, context, goal):
        """
        Constructs a prompt that explicitly requests JSON output.
        Loads system instructions from AIGlobalSettings, falling back to default.
        """
        from aot.databases.models import AIGlobalSettings
        
        system_overview = (
            "### [System Overview: AoT (AI of Things)] ###\n"
            "You are the AI assistant for 'AoT 시스템'. Your role is to monitor, manage, and configure the IoT environment.\n"
            "- **Inputs**: Data sources (Sensors, Weather APIs).\n"
            "- **Outputs**: Actuators (Valves, Sprinklers).\n"
            "- **Functions**: Logic (Schedules, Conditionals, PID).\n"
            "- **GIS**: Map data (Satellite, Radar).\n"
            "- **Notes**: Digital logbook.\n"
            "**Tool Rule:** Use `read_manual` (see `manual_index`) for technical specs (e.g., target_id='API.md', 'Supported-Inputs.md'). DO NOT GUESS.\n\n"
        )
        
        default_instructions = (
            "1. [MISSION: Final Answer Only] You have the full 'Current Context' below. DO NOT explain that you are searching. You MUST provide the final processed answer (summary, status, or confirmation) directly in the `insight` field.\n"
            "2. [Insight Formatting] Use natural, conversational plain text in the user's language. NO Markdown (**, -, #). NO technical IDs or raw JSON in the text.\n"
            "3. [Comprehensive Summary] When asked about a Site or Zone, summarize ALL its children (devices, status) proactively in one response.\n"
            "4. [Viewport Awareness] Refer to `dashboards` -> `widgets` to understand what the user sees on 'this screen'.\n"
            "5. [Tool Selection PRIORITY]:\n"
            "   - **Information Requests** (summary, status, list about system config): Use context directly. NO ACTION TOOLS.\n"
            "   - **Sensor/Weather Data** (날씨, 기상, 온도, 습도, 토양, 강수, any measured value): ALWAYS use `get_sensor_detail` virtual_tool_call. This is DATA RETRIEVAL, NOT an information request. Use zone unique_id as loc_id.\n"
            "   - **Work Scheduling** (제초작업, 점검, 청소): Use `add_schedule` (Virtual MCP).\n"
            "   - **Control Scheduling** (밸브, 펌프, 스프링클러): Use `schedule_device_control` (Virtual MCP).\n"
            "   - **Immediate Control** (지금, 즉시): Use `operate_device` or `action_type='output'`.\n"
            "   - **Registration** (추가, 등록, 설치): Use `action_type='register_device'`.\n"
            "   - **Documentation** (LAST RESORT): Use `read_manual` ONLY for technical specs.\n"
            "   - **NEVER** use `read_manual` for operational tasks (scheduling, control, registration).\n"
            "6. [No Phantom Promises] The `actions` array MUST contain the specific action you describe in `insight`. ALWAYS include actions in the SAME response as the explanation.\n"
            "7. [Contextual Resolution] Infer coordinates/API keys from `spatial_hierarchy` or `available_api_keys` automatically.\n"
            "8. [Hallucination Guard] ONLY suggest devices listed in `creatable_..._summary`. Use `get_detailed_manifest` if exact type_ids are needed.\n"
        )
        
        # Load from DB or use default
        settings = None
        try:
            settings = AIGlobalSettings.query.first()
            instructions = settings.system_prompt_template if (settings and settings.system_prompt_template) else default_instructions
        except Exception:
            instructions = default_instructions

        # Capability humility / anti-over-confident-denial. Always appended (even
        # when a custom system_prompt_template is set), because answering system-
        # capability questions from imagination — especially wrongly claiming a
        # feature is unsupported — is the most damaging failure mode. English: an
        # instruction to the AI; it still answers in the user's language.
        instructions += (
            "\n- [Capability Humility] For questions about what the system can do or how to do "
            "something ('can I ...?', 'how do I ...?', 'where is ...?'), do NOT answer from "
            "assumption. NEVER state that a feature is unsupported, unavailable, or impossible "
            "unless the documentation or current context confirms it. If you are not certain, "
            "consult the documentation (read_manual, and knowledge_search when available) before "
            "answering, or tell the user you will verify — never deny a capability from imagination."
        )

        # v3.1 Phase 5: agentic knowledge-search tool discovery hint (flag-gated).
        # Reuses the already-loaded settings row — no extra query. Off by default.
        # English (instruction to the AI; it answers in the user's language).
        if settings is not None and getattr(settings, 't3_knowledge_search_enabled', False):
            instructions += (
                "\n- [Knowledge Search] When you need to find system usage, features, or "
                "terminology in the documentation, use action_type='knowledge_search', "
                "params={\"query\": \"<what to find>\"}. It searches ALL docs by a free query and "
                "returns the relevant sections without needing a filename or section heading. It "
                "also covers registered domain knowledge (crops, pests, environment guides) when "
                "the AI Library has synced sources. Prefer this for capability / how-to / domain "
                "questions instead of denying or guessing; use read_manual only when you need a "
                "specific full file."
            )

        # Tool selection guide is now integrated into instructions for brevity
        tool_selection_guide = ""

        # MCP Tool Integration: Always inject if mcp_tools exist in context (not overridable by DB template)
        mcp_addon = ""
        mcp_tools = context.get("capabilities", {}).get("mcp_tools", [])
        if mcp_tools:
            active_tools = [t for t in mcp_tools if not t.get("requires_exploration")]
            exploreable = [t for t in mcp_tools if t.get("requires_exploration")]

            mcp_addon = (
                "\n### [MCP External Tools - MANDATORY REFERENCE] ###\n"
                f"You have {len(mcp_tools)} external MCP tool(s) available in `capabilities.mcp_tools`.\n"
            )
            if active_tools:
                tool_summary = ", ".join([f"'{t.get('tool_name')}' (server: {t.get('server_name')})" for t in active_tools[:10]])
                mcp_addon += (
                    f"READY-TO-USE tools: {tool_summary}\n"
                    "To call these tools, use: action_type='mcp_tool_call', target_id='<server_id>', "
                    "params={\"tool_name\": \"<name>\", \"arguments\": {<args per input_schema>}}\n"
                    "These are auto-executed immediately and results are fed back to you.\n"
                )
            if exploreable:
                mcp_addon += (
                    f"EXPLORABLE servers ({len(exploreable)}): Use 'get_detailed_manifest' with target_id='mcp_<server_id>' to see their tools.\n"
                )
            mcp_addon += "When the user's request can be fulfilled by an MCP tool, you MUST use it.\n"

        # 도구 정의를 어느 채널로 보낼지 — 기본은 종전대로 **양쪽**이다.
        #
        # 지금 도구 정의가 한 요청에 두 번 실린다: 이 프롬프트의
        # `capabilities` 와, gemini·anthropic 이 따로 보내는 `tools[]`
        # (function_declarations / tool_use). 실측(2026-08-15) 왕복당
        # 199,057자 = 프롬프트의 37.6%.
        #
        # 그런데 **한쪽을 그냥 지울 수 없다.**
        # - openai·groq·mistral·ollama·minimax 는 tools[] 를 아예 안 보낸다.
        #   프롬프트 사본이 유일한 채널이라 지우면 도구를 통째로 잃는다.
        # - gemini·anthropic 의 네이티브 경로는 승인 게이트까지 갖춘 정식
        #   경로다(GEMINI/ANTHROPIC_NATIVE_APPROVAL_GATE). tools[] 를 지우면
        #   그 경로가 죽는다.
        # - 실측은 gemini 한 모델에서 "텍스트 JSON 을 쓴다" 만 보여준다.
        #   그 관측을 anthropic 으로 옮길 근거가 없다.
        #
        # 그래서 자르지 않고 **고를 수 있게** 한다. 어느 쪽이 나은지는 A/B 로
        # 재고 정한다(aot/tests/ai_eval/drawer_ab.py).
        #   both   (기본) 종전과 동일 — 프롬프트 + tools[]
        #   prompt 프롬프트만 — 네이티브 지원 엔진에서 tools[] 를 뺀다
        #   native tools[] 만 — 네이티브 지원 엔진에서 프롬프트 사본을 뺀다
        channel = os.environ.get('AOT_AI_TOOL_CHANNEL', 'both')
        if channel == 'native' and self.supports_native_tools:
            context = {k: v for k, v in context.items() if k != 'capabilities'}

        # 컨텍스트 JSON 은 **항상 compact** 로 보낸다.
        #
        # 예전에는 lightweight 티어만 compact 였고 나머지(기본값 'standard' 포함)
        # 는 indent=2 였다. 들여쓰기는 사람이 읽을 때 쓸모가 있지 컨텍스트를
        # 읽는 모델에게는 아니다 — 실측(2026-08-15): capabilities 만으로도
        # 151,228자 → 121,917자, **29,311자(19%)가 공백**이었다. 이 프롬프트는
        # 왕복당 수십만 자라 요청 한두 개로 분당 토큰 쿼터에 걸리는 상황이고,
        # 그 비용의 5분의 1이 들여쓰기였다.
        #
        # 답변 품질이 나빠지면 되돌리기는 한 줄이다(A/B 하네스:
        # aot/tests/ai_eval/drawer_ab.py).
        ctx_str = json.dumps(context, separators=(',', ':'), default=str)

        full_prompt = (
            f"{system_overview}"
            f"**CRITICAL GOAL:** {goal}\n"
            f"RULE 1: You MUST provide the final processed answer (summary, status, or confirmation) directly in the `insight` field based on the Current Context below. DO NOT describe your role.\n\n"
            f"Current Context:\n{ctx_str}\n\n"
            "SYSTEM INSTRUCTIONS:\n"
            f"{instructions}\n"
            f"{mcp_addon}\n\n"
            f"**RE-STATED GOAL:** {goal}\n"
            "Final answer required now. Do not delay."
        )
        
        # v12.6: Enforce Tiered Character Budgets (Engine-specific Guardrail)
        max_chars = self.get_context_budget()
        
        # v16.2: Final Hard-Limit Guardrail with Truncation instead of simple Abortion
        if len(full_prompt) > max_chars:
            logger.warning(f"[{self.__class__.__name__}] Hard-truncating prompt for {self.model_tier} tier: {len(full_prompt)} -> {max_chars}")
            full_prompt = full_prompt[:max_chars-500] + "\n... [PROMPT TRUNCATED DUE TO BUDGET LIMIT] ..."
            
        if len(full_prompt) > (max_chars * 0.8):
            logger.warning(f"[{self.__class__.__name__}] Near budget limit ({self.model_tier}): {len(full_prompt)}/{max_chars}")

        # Graceful degradation: if the user attached images but this engine is
        # not vision-capable, tell the model so it answers from text instead of
        # ignoring the request silently. (Vision engines consume the images
        # directly in run_reasoning and skip this note.)
        try:
            from aot.ai.ai_request_context import get_attachments
            _atts = get_attachments()
            if _atts and not getattr(self, 'supports_vision', False):
                full_prompt += (
                    f"\n[NOTE: The user attached {len(_atts)} image(s), but this model cannot view images. "
                    "Answer from the text only, or ask the user to describe the image(s).]\n"
                )
        except Exception:
            pass

        return (
            f"{full_prompt}"
            "CRITICAL INSTRUCTION: You MUST detect the language used in the 'Goal' user command "
            "and strictly write your reasoning ('insight') in that EXACT SAME language. "
            "(e.g., If the user asks in Korean, you must reply in Korean.)\n"
            "CRITICAL INSTRUCTION 2: NEVER use unicode escape sequences (like \\u0000) for non-English characters in the JSON. Output raw UTF-8 characters directly.\n"
            "CRITICAL INSTRUCTION 3: Respond with ONLY THE JSON OBJECT. No preamble, no postscript. Ensure the `insight` field does NOT contain any raw technical IDs or JSON structures unless explicitly asked for debugging.\n"
            "CRITICAL INSTRUCTION 4: Your `insight` MUST be plain, conversational text. DO NOT use ANY Markdown formatting (e.g., **, *, -, #) inside the `insight` string.\n"
            "CRITICAL INSTRUCTION 5: Your response MUST be 100% strictly valid JSON. Properly escape all internal double quotes (\\\") and newlines (\\\\n). Never leave trailing commas.\n"
            "CRITICAL INSTRUCTION 6: Physical Truth (Law 3). Your 'insight' will be DISCARDED by the system "
            "if your 'actions' JSON fails to execute successfully. Do NOT claim you have already performed "
            "an action; state your intent and wait for the tool output in the next turn.\n\n"

            "You MUST respond with ONLY a valid JSON object (no markdown, no explanation outside JSON) "
            "in the following format:\n"
            '{\n'
            '  "insight": "Your natural language analysis of the situation IN THE USER\'S LANGUAGE",\n'
            '  "actions": [\n'
            '    {\n'
            '      "action_type": "output|pid|function|note|register_device|edit_device|delete_device|get_detailed_manifest|read_manual|mcp_tool_call|virtual_tool_call",\n'
            '      "target_id": "device_unique_id",\n'
            '      "description": "What this action does",\n'
            '      "params": {}\n'
            '    }\n'
            '  ]\n'
            '}'
        )

    def _extract_json_from_text(self, text):
        """
        Extracts a JSON object from LLM text output using json_repair.
        Handles markdown code blocks, bare JSON, unescaped quotes, and broken structures.
        """
        try:
            import json_repair
            
            # Clean up obvious markdown blocks before sending to repair
            clean_text = text.strip()
            if clean_text.startswith('```'):
                clean_text = re.sub(r'^```(json)?\n?', '', clean_text)
            if clean_text.endswith('```'):
                clean_text = re.sub(r'\n?```$', '', clean_text)
                
            # json_repair works magic on broken JSON (returns dict if return_objects=True)
            repaired = json_repair.repair_json(clean_text, return_objects=True)
            
            # If it returns a list of objects, or single object, handle it
            if isinstance(repaired, dict):
                return repaired
            elif isinstance(repaired, list) and len(repaired) > 0 and isinstance(repaired[0], dict):
                return repaired[0]
                
        except Exception as e:
            logger.warning(f"json-repair failed or not available: {e}. Falling back to regex.")

        # Fallback naive extraction
        try:
            # 1. Look for markdown code blocks
            match = re.search(r'```(?:json)?\s*\n?(.*?)\n?\s*```', text, re.DOTALL)
            if match:
                return json.loads(match.group(1).strip(), strict=False)
            
            # 2. Look for any curly brace start/end
            match = re.search(r'(\{.*\}|\[.*\])', text, re.DOTALL)
            if match:
                return json.loads(match.group(1).strip(), strict=False)
                
            # 3. Direct parse
            return json.loads(text.strip(), strict=False)
        except Exception:
            pass

        return None

    def _get_control_keywords(self):
        """
        v21.0: Fetches keywords from the Glossary (No Hardcoding).
        Categorized as 'control_intent'.
        """
        try:
            from aot.databases.models.ai_domain_glossary import AIDomainGlossary
            terms = AIDomainGlossary.query.filter_by(category='control_intent', is_active=True).all()
            if terms:
                return [t.term for t in terms]
        except Exception as e:
            pass
        return []

    def _get_completion_indicators(self):
        """
        v22.0: Fetches completion indicators from the Glossary (Zero-Hardcoding).
        Categorized as 'completion_indicator'.
        """
        try:
            from aot.databases.models.ai_domain_glossary import AIDomainGlossary
            terms = AIDomainGlossary.query.filter_by(category='completion_indicator', is_active=True).all()
            if terms:
                return [t.term for t in terms]
        except Exception as e:
            pass
        return []

    def _get_available_tool_names(self):
        """
        v23.0: Dynamically fetches all available tool names (outputs, functions, MCP tools)
        from the AIActionService manifest. Used for the global semantic guard.
        """
        try:
            from aot.ai.services.ai_action_service import AIActionService
            # agent_id is available in self.agent_id initialized in __init__
            manifest = AIActionService.get_action_manifest(agent_unique_id=self.agent_id, is_slim=True)
            tool_names = []
            
            # Outputs
            for o in manifest.get('outputs', []):
                tool_names.append(o.get('name', '').lower())
            
            # PID Controllers
            for p in manifest.get('pid_controllers', []):
                tool_names.append(p.get('name', '').lower())
                
            # Predefined Functions
            for f in manifest.get('predefined_functions', []):
                tool_names.append(f.get('name', '').lower())
                
            # MCP Tools
            for t in manifest.get('mcp_tools', []):
                tool_names.append(t.get('tool_name', '').lower())
                
            # Filter empty names and return unique set
            return list(set(name for name in tool_names if name))
        except Exception as e:
            logger.warning(f"[{self.name}] Failed to fetch tool names for semantic guard: {e}")
        return []

    def _safe_api_result(self, raw_text, engine_name):
        """
        Parses LLM raw text into {"insight": str, "actions": list}.
        Falls back gracefully when parsing fails.
        """
        parsed = self._extract_json_from_text(raw_text)

        if parsed and isinstance(parsed, dict):
            result = {**parsed}
            result["insight"] = parsed.get("insight", raw_text[:3000])
            result["actions"] = parsed.get("actions", [])
            
            # v21.0/v22.0/v23.0: P3 Control Intent Guard & P2 Semantic Guard (Global)
            # If text describes a control action or claims completion but actions array is empty, force _parse_failed
            # v26.10 FIX (BUG-06): has_tool_mention alone must NOT trigger _parse_failed.
            # DATA_QUERY responses naturally mention device names (e.g. "1구역 밸브 ON") — this is
            # correct behaviour, not hallucination.  Tool-name presence is only suspicious when
            # paired with an explicit control-intent verb OR a past-tense completion claim.
            if not result["actions"]:
                control_keywords = self._get_control_keywords()
                completion_indicators = self._get_completion_indicators()

                raw_lower = raw_text.lower()

                # Check for control intent keywords (P3) — e.g. "켜줘", "꺼줘", "작동시켜"
                has_control_intent = any(kw.lower() in raw_lower for kw in control_keywords)
                # Check for past-tense completion claims (P2) — e.g. "켰습니다", "작동 완료"
                has_completion_claim = any(ci.lower() in raw_lower for ci in completion_indicators)

                # v26.10: tool_names check removed from solo trigger.
                # has_tool_mention alone is insufficient: every DATA_QUERY response about
                # a device will contain the device name, which would also appear in the
                # manifest tool list, causing false-positive _parse_failed for all device queries.
                # Guard only fires on semantic evidence of a falsely claimed action.
                if has_control_intent or has_completion_claim:
                    logger.warning(f"[{engine_name}] Action claim detected in text but 'actions' is empty (Hallucination suspected). Forcing recovery.")
                    result["_parse_failed"] = True
                    result["_semantic_guard_hit"] = True # Explicit flag for Fast Path escalation
                    
            return result

        logger.warning(f"[{engine_name}] JSON parsing failed. Falling back to raw text as insight.")
        
        # Clean up obvious markdown blocks before using as insight
        clean_text = raw_text.strip()
        if clean_text.startswith('```'):
            clean_text = re.sub(r'^```(json)?\n?', '', clean_text)
        if clean_text.endswith('```'):
            clean_text = re.sub(r'\n?```$', '', clean_text)
            
        return {
            "insight": clean_text,
            "actions": [],
            "_parse_failed": True
        }

    def _call_openai_compatible_api(self, context, goal):
        """
        Shared API caller for OpenAI-compatible endpoints
        (OpenAI, Groq, Mistral, Ollama).
        """
        url = f"{self.api_endpoint.rstrip('/')}/chat/completions"
        engine_name = self.__class__.__name__

        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        prompt = self._build_prompt(context, goal)

        payload = {
            "model": self.model_name,
            "messages": [
                {"role": "system", "content": self.system_prompt or "You are a helpful AI assistant."},
                {"role": "user", "content": prompt}
            ],
            "temperature": self.temperature or 0.7,
            "max_tokens": self.get_max_output_tokens()
        }

        logger.info(f"[{engine_name}] POST {url} model={self.model_name}")

        try:
            response = requests.post(url, json=payload, headers=headers, timeout=self.timeout)
            response.raise_for_status()

            data = response.json()
            raw_text = data["choices"][0]["message"]["content"]

            logger.debug(f"[{engine_name}] Raw response: {raw_text[:300]}")
            return self._safe_api_result(raw_text, engine_name)

        except requests.exceptions.Timeout:
            logger.error(f"[{engine_name}] API timeout ({self.timeout}s)")
            return {"insight": f"[{engine_name}] API 호출 시간 초과 ({self.timeout}초)", "actions": []}
        except requests.exceptions.HTTPError as e:
            status_code = e.response.status_code if e.response is not None else "unknown"
            body = e.response.text if e.response is not None else ""
            logger.error(f"[{engine_name}] HTTP {status_code}: {body}")
            
            friendly_msg = self._translate_http_error(status_code, body, engine_name, goal)
            return {"status": "error", "error_code": status_code, "insight": friendly_msg, "actions": []}
        except requests.exceptions.ConnectionError:
            logger.error(f"[{engine_name}] Connection failed to {url}")
            return {"status": "error", "error_code": "conn_error", "insight": f"[{engine_name}] API 서버 연결 실패. 네트워크 상태를 확인해 주세요.", "actions": []}
        except (KeyError, IndexError) as e:
            logger.error(f"[{engine_name}] Unexpected response structure: {e}")
            return {"status": "error", "error_code": "parse_error", "insight": f"[{engine_name}] 서비스 응답 처리 중 오류가 발생했습니다.", "actions": []}

    def _translate_http_error(self, status_code, body, engine_name, goal):
        """
        v20.0: Translates raw HTTP errors into user-friendly messages.
        Prevents JSON body leakage to the UI.
        """
        # Multi-language detection (simple heuristic)
        is_ko = any(0xAC00 <= ord(c) <= 0xD7A3 for c in (goal or ""))
        
        if status_code == 429:
            if is_ko:
                return f"죄송합니다. 서비스 이용량이 일시적으로 초과되었습니다(할당량 부족). 약 1~10분 후 다시 시도해 주세요. ({engine_name} 429)"
            return f"Sorry, the service quota has been exceeded (Rate Limit). Please try again in a few minutes. ({engine_name} 429)"
        
        if status_code == 401 or status_code == 403:
            if is_ko:
                return f"AI 서비스 인증(API Key)에 문제가 발생했습니다. 관리자 설정을 확인해 주세요. ({engine_name} {status_code})"
            return f"AI authentication error. Please check your API key in settings. ({engine_name} {status_code})"
            
        if status_code >= 500:
            if is_ko:
                return f"AI 서버가 일시적으로 응답하지 않습니다. 잠시 후 다시 시도해 주세요. ({engine_name} {status_code})"
            return f"The AI server is temporarily unavailable. Please try again later. ({engine_name} {status_code})"

        # Default fallback
        if is_ko:
            return f"AI 서비스 통신 중 오류가 발생했습니다. (HTTP {status_code})"
        return f"An error occurred while communicating with the AI service. (HTTP {status_code})"
