# coding=utf-8
"""
AIRoutingService — Extracted routing methods from AIAgentService.

@ANCHOR: AI_ROUTING_SERVICE
"""
import logging
from aot.databases.models.ai import AIAgent
from aot.utils.safe_eval import safe_eval

logger = logging.getLogger(__name__)


# @ANCHOR: TIER0_CLASSIFIER
class Tier0Classifier:
    """
    Zero-token pre-classifier for trivially resolvable queries.
    Guards against over-classification via dual-validation:
      1. Extracted user query length ≤ MAX_LEN (strips page/system context prefix)
      2. Data-dependency keywords absent (device/sensor/weather → TIER 1)
      3. Connector keywords absent (compound requests → TIER 1)
    Only handles: greetings, current time, identity, system description,
    language support, and pure math. All data queries route to TIER 1 AI.

    @phase active
    @stability stable
    @dependency AIDomainGlossary
    """

    _DATA_DEP_TERMS = frozenset([
        # Korean
        '밸브', '센서', '장치', '구역', '포장', '온도', '습도', '압력', '날씨', '기온',
        '기상', '강수', '풍속', '상태', '이력', '현황', '데이터', '조회', '측정',
        # English
        'valve', 'sensor', 'device', 'zone', 'temperature', 'humidity', 'pressure',
        'weather', 'status', 'history', 'data', 'reading',
        # Japanese
        'バルブ', 'センサー', '装置', 'ゾーン', '温度', '湿度', '天気',
    ])
    _CONNECTORS = frozenset([
        '그리고', '또한', '그런데', '하지만', '그리고서', '근데', '왜냐면',
        'and', 'also', 'but', 'however', 'moreover',
        'また', 'そして', 'でも', 'しかし',
        ',', '，',
    ])
    _MAX_LEN = 30
    _PATTERN_CACHE = {}
    _PATTERN_CACHE_TTL = 300  # 5 minutes

    @classmethod
    def extract_user_query(cls, command_text):
        """Strip [Page Context:...] and [System Context:...] prefix injected by frontend."""
        import re
        m = re.search(r'\[System Context:[^\]]*\]\s*(.*)', command_text, re.DOTALL)
        if m:
            return m.group(1).strip()
        stripped = re.sub(r'^(?:\s*\[[^\]]*\]\s*)+(?:IMPORTANT:[^\[]*)?', '', command_text).strip()
        return stripped if stripped else command_text.strip()

    @classmethod
    def _load_patterns(cls, category, fallback):
        from aot.utils.time_utils import get_local_now
        now = get_local_now().timestamp()

        # [PHASE 1.1] TTL Cache check to eliminate redundant DB calls
        if category in cls._PATTERN_CACHE:
            cached_data, expiry = cls._PATTERN_CACHE[category]
            if now < expiry:
                return cached_data

        try:
            from aot.databases.models.ai_domain_glossary import AIDomainGlossary
            terms = AIDomainGlossary.query.filter_by(category=category, is_active=True).all()
            if terms:
                patterns = [t.term for t in terms]
                cls._PATTERN_CACHE[category] = (patterns, now + cls._PATTERN_CACHE_TTL)
                return patterns
        except Exception:
            pass
        return fallback

    @classmethod
    def _has_data_dependency(cls, clean_text):
        return any(term in clean_text for term in cls._DATA_DEP_TERMS)

    @classmethod
    def _has_connector(cls, clean_text):
        return any(conn in clean_text for conn in cls._CONNECTORS)

    @classmethod
    def classify(cls, command_text):
        """
        Returns a router-compatible dict (static_response=True) for trivial queries,
        or None to proceed to TIER 1 LLM classification.
        """
        import re
        user_query = cls.extract_user_query(command_text)
        clean = re.sub(r'[!?.~]', '', user_query.strip().lower()).strip()

        # Guard 1: Too long → TIER 1
        if len(clean) > cls._MAX_LEN:
            return None

        # Guard 2: Data dependency keyword present → TIER 1
        if cls._has_data_dependency(clean):
            return None

        # Guard 3: Connector (compound request) → TIER 1
        if cls._has_connector(clean):
            return None

        # --- Pure math ---
        # The regex below is a fast pre-filter, not the security boundary:
        # safe_eval parses and whitelists the AST, so this stays safe even if
        # the character class is ever widened (it previously guarded a bare
        # eval() on raw chat input — one relaxed character from being RCE).
        if re.match(r'^[\d\s\+\-\*\/\(\)\.]+$', user_query.strip()):
            if any(c in user_query for c in '+-*/'):
                try:
                    math_result = safe_eval(user_query)
                    from flask_babel import gettext as _
                    return cls._make_response(_("The result is %(result)s.", result=math_result))
                except Exception:
                    pass

        # --- Current time ---
        TIME_PATTERNS = cls._load_patterns('router_bypass_time', [
            '몇시', '몇 시', '시간', '지금 시간', 'what time', 'current time',
            '今何時', '何時',
        ])
        if any(p in clean for p in TIME_PATTERNS):
            from aot.utils.time_utils import get_local_now
            from flask_babel import gettext as _
            now = get_local_now().strftime("%Y-%m-%d %H:%M:%S")
            return cls._make_response(_("The current time is %(time)s.", time=now))

        # --- Greeting (exact + fuzzy) ---
        GREETINGS = cls._load_patterns('router_bypass_greeting', [
            '안녕', '안뇽', '안냥', '안냐세요', '안녕하세요', '반가워', '하이', '반갑다',
            'hello', 'hi', 'hey', 'greetings', 'ciao', 'ola',
            'こんにちは', 'こんにちわ', 'おはよ', 'ばんわ',
        ])
        import difflib
        is_greeting = clean in GREETINGS
        if not is_greeting and len(clean) <= 10:
            matches = difflib.get_close_matches(clean, GREETINGS, n=1, cutoff=0.65)
            is_greeting = bool(matches)
        if is_greeting:
            from flask_babel import gettext as _
            return cls._make_response(_("Hello! I am the AoT AI Assistant. How can I help you today?"))

        # --- Identity ---
        IDENTITY_QS = cls._load_patterns('router_bypass_identity', [
            '누구', 'who are you', 'what are you', '너는', '당신은', 'だれ', '何者',
        ])
        if any(q in clean for q in IDENTITY_QS):
            from flask_babel import gettext as _
            return cls._make_response(_("I am the intelligent management assistant for the AoT system."))

        # --- System description ---
        SYSTEM_QS = cls._load_patterns('router_bypass_system', [
            'aot', 'ai of things', '이게뭐야', '뭐하는', 'what is aot', 'aotとは', '에이오티',
        ])
        if any(q in clean for q in SYSTEM_QS):
            from flask_babel import gettext as _
            return cls._make_response(
                _("AoT (AI of Things) is an AI-based spatial control and monitoring system.")
            )

        # --- Language support ---
        LANG_QS = cls._load_patterns('router_bypass_language', [
            '다국어', 'language', '언어', '多言語',
        ])
        if any(q in clean for q in LANG_QS):
            from flask_babel import gettext as _
            return cls._make_response(_("I currently support Korean, English, Japanese, and more."))

        return None

    @staticmethod
    def _make_response(insight):
        return {
            "intent": "CHAT",
            "complexity": "SIMPLE",
            "confidence": 1.0,
            "requires_tools": False,
            "insight": insight,
            "static_response": True,
            "actions": [],
        }


# @ANCHOR: WEATHER_TOOL_RESULT_MAPPER  [2026-03-24 — 001_WEATHER_LOGIC_UPGRADE patch_5]
_WEATHER_TOOL_KEYWORDS = frozenset([
    'weather', 'sensor', 'get_sensor', 'measurement', 'environmental',
    'temperature', 'humidity', 'wind', 'rain', 'climate',
])


class AIRoutingService:
    """
    Service for intent routing, action validation, and result formatting.

    @phase active
    @stability stable
    @dependency AIAgentService, AIActionService, BrainResolver
    """

    _READINGS_KEEP_LAST = 3  # Max readings to retain per measurement block (token budget)

    @staticmethod
    def _condense_weather_result(result_dict: dict) -> dict:
        """
        Condense weather/sensor result for LLM context injection.

        For each measurement block in result_dict['result']:
        - Keep only the last _READINGS_KEEP_LAST readings (most recent values).
        - Retain total_readings and stats (min/max/avg/count).
        - Propagate 'measurement' label to unlabeled aggregate stat blocks.

        Reduces token usage ~95% for multi-reading sensor queries (e.g. 115 → 3 readings).
        Returns a shallow copy; does not mutate the original.
        """
        import copy as _copy
        rd = _copy.copy(result_dict)
        items = rd.get('result')
        if not isinstance(items, list):
            return rd

        condensed = []
        last_measurement = ''
        last_device = ''
        keep = AIRoutingService._READINGS_KEEP_LAST

        for item in items:
            if not isinstance(item, dict):
                condensed.append(item)
                continue

            if item.get('measurement'):
                last_measurement = item['measurement']
                last_device = item.get('device_name', last_device)
                # Slim readings: keep only last `keep` entries
                readings = item.get('readings', [])
                slim = dict(item)
                slim['readings'] = readings[-keep:] if len(readings) > keep else readings
                if len(readings) > keep:
                    slim['_readings_truncated'] = f"Showing last {keep} of {len(readings)} readings"
                condensed.append(slim)

            elif set(item.keys()) <= {'min', 'max', 'avg', 'count', 'unit'} and last_measurement:
                # Unlabeled aggregate stat block — inherit parent measurement label
                enriched = dict(item)
                enriched['_measurement'] = last_measurement
                enriched['_device'] = last_device
                condensed.append(enriched)
            else:
                condensed.append(item)

        rd['result'] = condensed
        return rd

    @staticmethod
    def format_weather_tool_result(action: dict, result_dict: dict) -> str:
        """
        Format a virtual_tool_call result for injection into chat_history / all_rag_logs.

        If the tool_name signals weather/sensor data, the result is tagged with
        [WEATHER_DATA] and a mandatory USE directive so the Synthesizer treats it
        as the primary truth source for weather queries — preventing the rule-4
        'Physical over Virtual' suppression from discarding it.

        Aggregate stat blocks ({min, max, avg, count}) without a 'measurement' key are
        annotated with '_measurement' / '_device' inherited from the preceding named block.

        Returns a formatted string ready for append to all_rag_logs.
        """
        import json as _json
        tool_name = (
            action.get('params', {}).get('tool_name') or
            action.get('tool_name', '')
        ).lower()
        action_type = action.get('action_type', 'virtual_tool_call')

        is_weather = any(kw in tool_name for kw in _WEATHER_TOOL_KEYWORDS)

        # Condense readings (last 3 per measurement) + annotate measurement labels
        annotated = AIRoutingService._condense_weather_result(result_dict)
        result_str = _json.dumps(annotated, ensure_ascii=False)

        if is_weather:
            return (
                f"[WEATHER_DATA][TRUTH_SOURCE] "
                f"Auto-RAG Action '{action_type}' Output:\n"
                f"{result_str}\n"
                "SYNTHESIZER DIRECTIVE: The above is real-time weather/sensor data. "
                "Each '_measurement' field identifies the sensor type for the adjacent "
                "min/max/avg statistics. Use this as the PRIMARY source for any "
                "weather/environmental answer. Do NOT suppress or deprioritize this result."
            )
        return f"Auto-RAG Action '{action_type}' Output:\n{result_str}"

    @staticmethod
    def run_router(command_text, thread_id=None):
        """
        Runs the Intent Router to classify the user's intent.
        v28.0+: TIER 0 pre-classifier handles trivial queries (0 tokens).
        v30.0 [052]: Removed DATA_Q_SIGNALS bypass; data queries always route
                     through AI. All user-facing strings use Flask-Babel gettext.
                     Fixed _user_query NameError (BUG-01). Fixed _extract_clean_insight
                     NameError (BUG-02). Added page context prefix extraction (BUG-05).
        v6.4: Request-scoped cache — avoids duplicate LLM calls for identical commands.
        """
        # TIER 0: Zero-token pre-classification
        tier0_result = Tier0Classifier.classify(command_text)
        if tier0_result is not None:
            logger.info("[AIRouter] TIER 0 bypass triggered.")
            return tier0_result

        # @ANCHOR: ROUTER_REQUEST_CACHE [2026-03-25]
        try:
            from flask import g, has_request_context
            if has_request_context():
                if not hasattr(g, '_router_cache'):
                    g._router_cache = {}
                if command_text in g._router_cache:
                    logger.info("[AIRouter] Request cache hit — skipping LLM call.")
                    return g._router_cache[command_text]
        except Exception:
            pass

        # TIER 1: LLM Router
        from aot.ai.services.ai_agent_service import AIAgentService

        from aot.ai.services.ai_agent_service import AIAgentService
        router_agent = AIAgentService.get_cached_agent('router')
        if not router_agent:
            # Legacy fallback
            router_agent = AIAgent.query.filter_by(role='router', is_activated=True).first()
        if not router_agent:
            logger.warning("[AIRouter] No active router agent found.")
            from flask_babel import gettext as _
            intent = "CHAT" if len(command_text) < 20 else "DATA_QUERY"
            return {
                "intent": intent, "complexity": "SIMPLE", "confidence": 0.0,
                "requires_tools": intent != "CHAT",
                "insight": _("Service is temporarily unavailable. Please try again."),
                "actions": [],
            }

        engine = AIAgentService.get_engine(router_agent.unique_id)
        if not engine:
            logger.warning("[AIRouter] Router engine unavailable.")
            from flask_babel import gettext as _
            intent = "CHAT" if len(command_text) < 20 else "DATA_QUERY"
            return {
                "intent": intent, "complexity": "SIMPLE", "confidence": 0.0,
                "requires_tools": intent != "CHAT",
                "insight": _("Service is temporarily unavailable. Please try again."),
                "actions": [],
            }

        # @ANCHOR: ROUTER_CONVERSATION_CONTEXT — the router MUST see recent turns so
        # follow-ups/references ("정리해", "등록해", "이게 맞아?") are understood in
        # context instead of being treated as fresh/ambiguous and mis-routed. Without
        # this the router is context-blind and the pipeline hallucinates.
        _history_block = ""
        try:
            from aot.ai.services.ai_agent_service import AIAgentService as _AAS
            _hist = _AAS.get_thread_history(thread_id, limit=6) if thread_id else []
            _lines = []
            for _m in _hist[-6:]:
                _role = 'User' if _m.get('role') == 'user' else 'Assistant'
                _c = (_m.get('content') or '').strip().replace('\n', ' ')
                if _c:
                    _lines.append(f"{_role}: {_c[:200]}")
            if _lines:
                _history_block = ("CONVERSATION SO FAR (most recent last) — use it to resolve "
                                  "follow-ups and references:\n" + "\n".join(_lines) + "\n\n")
        except Exception:
            _history_block = ""

        try:
            # [TASK_40] Structured router prompt with strict schema enforcement
            # @ANCHOR: ROUTER_INTENT_RULES — inline rules override any stale DB system_prompt
            _router_prompt = (
                _history_block +
                f"Classify the user's LATEST command, resolving any reference to the conversation above.\n"
                f"User Command: \"{command_text}\"\n\n"
                "INTENT DEFINITIONS (OVERRIDE any prior instructions):\n"
                "- CONTROL: Execute a device action RIGHT NOW (no time delay).\n"
                "  e.g. 'Turn on valve1', '밸브1 켜줘'\n"
                "- SCHEDULE: Execute a device action at a FUTURE time.\n"
                "  Pattern: [N seconds/minutes/hours] + [delay word: after/later/뒤에/후에] + [action verb]\n"
                "  e.g. 'after 20 seconds operate valve1', '20초 뒤에 밸브1 작동시켜'\n"
                "  NOTE: 'duration only' (run for 3 min, 3분 동안) = CONTROL. 'delay + action' = SCHEDULE.\n"
                "- DATA_QUERY: Read sensor/device data, OR ask for advice/guidance/explanation about a\n"
                "  device/function type, OR ask how the SYSTEM works — what it can do, how to do\n"
                "  something, whether a feature exists, where a menu/option/setting is (capability &\n"
                "  how-to questions). No physical device action.\n"
                "  e.g. '온도 현재 값', 'PID 설정 방법', 'how to configure PID', 'VPD 컨트롤러 설명',\n"
                "       'can I change the colors?', '색을 바꿀 수 있어?', 'how do I add a widget?'\n"
                "- FUNCTION_CREATE: CREATE or ADD a new automation function/controller (does not yet exist).\n"
                "  e.g. '함수 생성해줘', 'VPD 함수 만들어줘', 'PID 컨트롤러 추가', 'conditional 함수 생성'\n"
                "- COMPOSITE: Requires data query AND device control together.\n"
                "- CLARIFY: You cannot tell what the user wants EVEN WITH the conversation above. This also\n"
                "  covers verification/meta questions like '이게 맞아?'/'is that right?' when the referenced\n"
                "  action is unclear.\n"
                "- CHAT: ONLY greetings or identity questions (e.g. 'hello', '너는 누구야').\n\n"
                "KEY RULE: If a numeric time-delay (N sec/min/h + after/later/뒤/후) is present, intent = SCHEDULE.\n"
                "KEY RULE: If the user asks to CREATE or ADD a function/controller/자동화, intent = FUNCTION_CREATE.\n"
                "KEY RULE: If the user asks how the system works / whether a feature exists ('할 수 있어?','하는 법'), intent = DATA_QUERY.\n"
                "ANTI-HALLUCINATION (CRITICAL): When you are NOT confident what the user wants, choose CLARIFY.\n"
                "  NEVER invent an unrelated intent, and the downstream MUST NOT reply with sensor/weather/\n"
                "  dashboard data the user did not ask for. A confused answer is worse than asking.\n\n"
                "Respond with ONLY this JSON (no explanation, no extra fields):\n"
                "{\n"
                '  "intent": "CONTROL|DATA_QUERY|SCHEDULE|COMPOSITE|FUNCTION_CREATE|CLARIFY|CHAT",\n'
                '  "complexity": "SIMPLE|COMPLEX",\n'
                '  "confidence": 0.0~1.0,\n'
                '  "requires_tools": true|false,\n'
                '  "insight": "Brief description of what you understood"\n'
                "}\n"
                "CRITICAL: Do NOT add 'actions', 'tool_name', 'target_id', or any other field."
            )
            result = engine.run_reasoning({}, _router_prompt)

            # v20.0: Automatic Fallback for Router Errors (429/Quota/Technical)
            if result.get('status') == 'error':
                failed_id = router_agent.unique_id
                logger.warning(
                    f"[RouterFallback] Primary router ({failed_id}) failed: "
                    f"{result.get('error_code')}. Attempting fallback..."
                )
                alt_router = AIAgent.query.filter(
                    AIAgent.pipeline_role == 'router',
                    AIAgent.is_activated == True,
                    AIAgent.unique_id != failed_id
                ).first()
                if alt_router:
                    alt_engine = AIAgentService.get_engine(alt_router.unique_id)
                    if alt_engine:
                        logger.info(f"[RouterFallback] Retrying with alternative: {alt_router.unique_id}")
                        result = alt_engine.run_reasoning({}, command_text)

            # [TASK_46] Confidence Threshold: low confidence → CLARIFY
            _conf = float(result.get('confidence', 1.0))
            if _conf < 0.1 and result.get('intent') != 'CLARIFY':
                logger.warning(f"[AIRouter] Low confidence ({_conf}). Escalating to CLARIFY.")
                from flask_babel import gettext as _
                result['intent'] = 'CLARIFY'
                result['confidence'] = 0.0
                result['insight'] = _("I'm not sure I understood your request. Could you please clarify?")

            # v6: Normalize legacy intent codes to new format
            intent = result.get('intent', '')
            legacy_map = {'A_CONTROL': 'CONTROL', 'B_SCHEDULE': 'SCHEDULE'}
            if intent in legacy_map:
                result['intent'] = legacy_map[intent]

            # [TASK_40] Router Contamination Guard: remove hallucinated fields
            prohibited_fields = ['actions', 'tool_name', 'target_id', 'params', 'arguments']
            for field in prohibited_fields:
                if field in result:
                    logger.warning(f"[AIRouter] Stripping prohibited '{field}' field from Router output.")
                    result.pop(field, None)

            # [TASK_40] Handle insight as dict or raw JSON string
            _ri = result.get('insight', '')
            if isinstance(_ri, dict):
                logger.warning("[AIRouter] Router 'insight' is a dict. Extracting text.")
                _ri = _ri.get('insight') or str(_ri)
                result['insight'] = _ri

            # [TASK_41] Clean router insight — handles JSON wrapper, markdown fence, embedded JSON
            from aot.ai.services.ai_agent_service import _extract_clean_insight
            _clean_ri = _extract_clean_insight(_ri)
            if _clean_ri != _ri:
                result['insight'] = _clean_ri
                logger.debug("[TASK_41] Cleaned router insight from raw JSON format.")

            # v6.1: Backward-compatible complexity defaults
            if 'complexity' not in result:
                default_complexity = {'CHAT': 'SIMPLE', 'COMPOSITE': 'COMPLEX'}
                result['complexity'] = default_complexity.get(result.get('intent', ''), 'SIMPLE')

            # [TASK_42] CONTROL intent → always Fast path
            if result.get('intent') == 'CONTROL':
                if result.get('complexity') != 'SIMPLE':
                    logger.info(f"[AIRouter] CONTROL intent forced to SIMPLE (was {result.get('complexity')})")
                result['complexity'] = 'SIMPLE'

            # @ANCHOR: ROUTER_REQUEST_CACHE [2026-03-25]
            try:
                from flask import g, has_request_context
                if has_request_context() and hasattr(g, '_router_cache'):
                    g._router_cache[command_text] = result
            except Exception:
                pass

            return result

        except Exception as e:
            logger.error(f"[AIRouter] Router reasoning failed: {e}")
            from flask_babel import gettext as _
            _uq = Tier0Classifier.extract_user_query(command_text).lower()
            _DATA_SIGNALS = [
                '날씨', 'weather', '온도', '습도', '기온', '현황', '상태',
                '센서', '포장', '데이터', '조회',
            ]
            _fb_intent = (
                "DATA_QUERY"
                if any(s in _uq for s in _DATA_SIGNALS) or len(_uq) >= 20
                else "CHAT"
            )
            return {
                "status": "error",
                "intent": _fb_intent,
                "complexity": "SIMPLE",
                "confidence": 0.8,
                "requires_tools": _fb_intent != "CHAT",
                "insight": _("Service is temporarily unavailable. Please try again."),
                "actions": [],
            }

    @staticmethod
    def _resolve_action_route(action, agent_id):
        """
        [TASK_40] Unified Action Mediator: Refactored to use centralized AIActionService.resolve_action.
        Eliminates greedy scope search and ensures tool name validation.
        """
        a_type = (action.get('action_type') or '').lower()
        # Check both params.tool_name and top-level tool_name (normalized during dispatch)
        tool_name = action.get('params', {}).get('tool_name') or action.get('tool_name', '')

        # [P7] MCP_ONLY_TOOLS: must go through MCP path
        MCP_ONLY_TOOLS = {'operate_device'}

        from aot.ai.services.ai_action_service import AIActionService as _AAS

        def _extract_orig_args(action):
            params = action.get('params', {})
            args = params.get('arguments') or params.get('params') or {}
            if not args:
                _meta = {'tool_name', 'server_id', 'agent_unique_id'}
                args = {k: v for k, v in params.items() if k not in _meta}
            return args

        # Trigger resolution if:
        # 1. Virtual call to an MCP-only tool (mcp_binding redirection)
        # 2. MCP tool call missing its target_id (LLM hallucination or omission)
        if (a_type == 'virtual_tool_call' and tool_name in MCP_ONLY_TOOLS) or \
           (a_type == 'mcp_tool_call' and not action.get('target_id') and tool_name in MCP_ONLY_TOOLS):

            orig_args = _extract_orig_args(action)
            try:
                resolved = _AAS.resolve_action(tool_name, orig_args)
                # Inject agent_id for backward compatibility
                if 'params' in resolved:
                    resolved['params']['agent_unique_id'] = agent_id

                # [025_STEP_3] Eliminate silent fallback for MCP-only physical tools.
                if tool_name in MCP_ONLY_TOOLS and resolved.get('action_type') == 'virtual_tool_call':
                    logger.error(
                        f"[025_STEP_3][HARDWARE_OFFLINE] '{tool_name}' cannot be routed to "
                        f"MCPBridgeService — no active server with this tool found. "
                        f"Blocking action (HARDWARE_OFFLINE). "
                        f"Activate the MCP server to restore physical control."
                    )
                    return None  # Signals HARDWARE_OFFLINE to _dispatch_actions()

                logger.info(f"[TASK_40] '{tool_name}' resolved via resolve_action: "
                            f"{resolved['action_type']} → {resolved.get('target_id')}")
                return resolved
            except Exception as _e:
                if tool_name in MCP_ONLY_TOOLS:
                    logger.error(
                        f"[025_STEP_3][HARDWARE_OFFLINE] resolve_action failed for physical "
                        f"tool '{tool_name}': {_e}. Blocking action (no virtual fallback allowed)."
                    )
                    return None  # No silent fallback for physical tools
                logger.warning(f"[TASK_40] resolve_action failed for '{tool_name}': {_e}. "
                               f"Falling back to virtual_tool_call.")
                return {
                    'action_type': 'virtual_tool_call',
                    'target_id': 'system_internal',
                    'params': {'server_id': 'system_internal', 'tool_name': tool_name, 'arguments': orig_args}
                }

        return action

    @staticmethod
    def _validate_and_normalize_action(action):
        """
        P1/P2: Validates mandatory metadata and normalizes internal tools.
        [OPTION_D] Derives action_type from tool_name via deterministic resolver.
        Ensures 'tool_name' and 'server_id' (or 'plugin_id') exist for MCP/Virtual calls.
        """
        if not action:
            return False, "Action is None"

        # [OPTION_D] Normalize: LLM sometimes puts tool_name at top level instead of params
        if action.get('tool_name') and not action.get('params', {}).get('tool_name'):
            if 'params' not in action:
                action['params'] = {}
            action['params']['tool_name'] = action.pop('tool_name')
            logger.debug(f"[Normalize] Moved top-level tool_name into params.tool_name")

        # Accept tool_name from params.tool_name or target_id
        tool_name = action.get('params', {}).get('tool_name') or action.get('target_id')
        if not tool_name:
            return False, "Missing mandatory metadata: tool_name"

        # @ANCHOR: ACTION_ENVELOPE_AS_TOOL
        # 모델이 **액션 봉투를 도구 이름 자리에** 넣는 일이 있다. 도구 카탈로그가
        # 액션 종류(mcp_tool_call / virtual_tool_call)와 도구 이름을 둘 다 보여
        # 주므로 앞엣것을 도구로 착각하는 것이다. 실측(2026-08-26):
        #
        #   tool=mcp_tool_call
        #   args={'tool_name': 'get_plot', 'arguments': {'plot_id': …}, 'target_id': …}
        #   → [resolve_action] Unknown tool: 'mcp_tool_call'
        #
        # 진짜 호출은 그 안에 **온전히** 들어 있다 — 버릴 이유가 없다. 봉투를
        # 벗겨 정상 액션으로 되돌린다. 사용자에게는 "도구 실행에 문제가 발생
        # 했습니다" 로만 보이던 실패다.
        _ENVELOPE_NAMES = {'mcp_tool_call', 'virtual_tool_call'}
        _inner = (action.get('params') or {}).get('arguments')
        if (tool_name in _ENVELOPE_NAMES and isinstance(_inner, dict)
                and _inner.get('tool_name')):
            action['action_type'] = tool_name
            if _inner.get('target_id'):
                action['target_id'] = _inner['target_id']
            action['params'] = {k: v for k, v in _inner.items() if k != 'target_id'}
            tool_name = action['params']['tool_name']
            logger.info(f"[Normalize] Unwrapped action envelope used as a tool name "
                        f"→ '{tool_name}'")

        # [VIRTUAL_TOOL_MISCLASSIFY_FIX] The SSOT virtual registry is authoritative
        # about what is an internal tool. The LLM sometimes emits
        # action_type='mcp_tool_call' with a target guessed from the tool-name
        # prefix (e.g. 'smartfarmkorea_lookup' → nonexistent MCP server
        # 'smartfarmkorea') for a tool that is actually an internal virtual tool
        # — which then fails as "MCP Server not found". If the tool name is a
        # known virtual tool, force virtual_tool_call regardless of the LLM's
        # guess. EXCEPT MCP_ONLY_TOOLS (operate_device), which are virtual-
        # registry members deliberately routed to MCP via mcp_binding.
        if action.get('action_type') == 'mcp_tool_call' and action.get('params', {}).get('arguments') is not None:
            try:
                from aot.ai.services.tool_registry import virtual_tool_registry
                if tool_name in virtual_tool_registry() and tool_name not in {'operate_device'}:
                    action['action_type'] = 'virtual_tool_call'
                    action['target_id'] = 'system_internal'
                    action['params']['server_id'] = 'system_internal'
                    logger.info(f"[Normalize] Corrected LLM mcp_tool_call→virtual_tool_call "
                                f"for known virtual tool '{tool_name}'")
                    return True, "OK"
            except Exception as _e:
                logger.debug(f"[Normalize] virtual-tool misclassify check skipped: {_e}")

        # [OPTION_D] If action already has action_type, ensure server_id is populated for backward compat
        if action.get('action_type'):
            if action.get('action_type') == 'virtual_tool_call' and 'server_id' not in action.get('params', {}):
                if 'params' not in action:
                    action['params'] = {}
                action['params']['server_id'] = 'system_internal'
            return True, "OK"

        # [OPTION_D] Resolve action_type deterministically from tool_name
        try:
            from aot.ai.services.ai_action_service import AIActionService
            # v29.0: Always use resolve_action to benefit from tool_name validation across servers
            resolved = AIActionService.resolve_action(tool_name, action.get('params'))
            # v30.0: Strict cast to str to prevent AttributeError: 'bool' has no attribute 'lower' (TASK_8)
            action['action_type'] = str(resolved['action_type'])

            action['target_id'] = resolved['target_id']
            # Only update params if it's an MCP call (keep existing params for virtual tools)
            if resolved['action_type'] == 'mcp_tool_call':
                action['params'] = resolved['params']

            logger.info(f"[resolve_action] Derived action_type='{resolved['action_type']}' from tool_name='{tool_name}'")
            return True, "OK"
        except Exception as e:
            error_msg = f"Missing mandatory metadata: {str(e)}"
            logger.error(f"[Validation Failed][OPTION_D] {error_msg}")
            return False, error_msg
