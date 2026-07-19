# coding=utf-8
"""
AIPlanningService — Extracted planning methods from AIAgentService.

@ANCHOR: AI_PLANNING_SERVICE
"""
import logging
from aot.databases.models.ai import AIAgent
import contextvars

logger = logging.getLogger(__name__)

sse_queue_var = contextvars.ContextVar('sse_queue_var', default=None)

class AIPlanningService:
    """
    Extracted planning methods from AIAgentService.
    Creates execution plans with atomic steps, dependencies, and tool selections.

    @phase active
    @stability stable
    @dependency AIAgentService, AIActionService, AiDocService
    """
    # @ANCHOR: PLANNER_RUN_PLANNER
    @staticmethod
    def run_planner(intent, command_text, context, manifest, chat_history=None, stream=False):
        """
        v6 Planner: Creates an execution plan with atomic steps, dependencies,
        and tool selections. Falls back to legacy worker selection if no planner configured.

        Returns:
            dict with 'steps', 'strategy', 'estimated_tools', etc. or None if no planner
            If stream=True, returns a generator yielding dict events.
        """
        from concurrent.futures import ThreadPoolExecutor
        from aot.ai.services.ai_action_service import AIActionService
        from aot.ai.services.ai_agent_service import AIAgentService
        from aot.ai.services.ai_doc_service import AiDocService as _ADS

        # [PHASE 2.3] Shared Agent Cache lookup
        planner_agent = AIAgentService.get_cached_agent('planner')
        if not planner_agent:
            if not stream:
                return None
            def no_planner_gen():
                yield {"status": "error", "message": "No planner configured"}
            return no_planner_gen()

        # [PHASE 2.3] Parallel fetching of Manifest and Doc Context (B3 Optimization)
        with ThreadPoolExecutor(max_workers=2) as executor:
            manifest_future = None
            if not manifest:
                manifest_future = executor.submit(
                    AIActionService.get_action_manifest,
                    agent_unique_id=planner_agent.unique_id,
                    is_slim=False
                )
            
            doc_future = executor.submit(
                _ADS.search,
                intent or command_text or '',
                doc_type='functions'
            )

            # Collect results
            full_manifest = manifest
            if not full_manifest and manifest_future:
                full_manifest = manifest_future.result()
            _doc_results = doc_future.result()

        planner_context = {
            "intent": intent or "DATA_QUERY",
            "user_command": command_text,
            "system_state": context,
            "tool_manifest": full_manifest,
            "chat_history": chat_history or []
        }
        planner_context['ai_doc_context'] = _doc_results[:3] if _doc_results else None

        # @ANCHOR: AI_FUNCTION_GENERATION_HANDLER (M5_2 — AiFunctionGenerationRequest per 035/036)
        # Validate ai_doc_refs in function generation requests before engine reasoning.
        if planner_context.get('intent_type') == 'function_generation':
            try:
                from aot.ai.services.ai_doc_service import AiDocService as _ADS
                gen_request = planner_context.get('function_generation_request', {})
                # Validate all ai_doc_refs — each must resolve to a known function doc
                for ref in gen_request.get('ai_doc_refs', []):
                    if _ADS.get_function_doc(ref) is None:
                        logger.warning("[Planner][FuncGen] Unknown ai_doc_ref: %s", ref)
                        gen_request['validation_errors'] = gen_request.get('validation_errors', [])
                        gen_request['validation_errors'].append(f"Unknown ai_doc_ref: {ref}")
                planner_context['function_generation_request'] = gen_request
            except Exception as _fgen_exc:
                logger.warning("[Planner][FuncGen] Generation context error: %s", _fgen_exc)

        # @ANCHOR: PLANNER_DISCOVERY_ENFORCEMENT (TASK_9-C — CONTROL intent guard)
        _discovery_rule = ""
        import re as _re
        _UUID_PATTERN = r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}'
        _has_explicit_uuid = bool(_re.search(_UUID_PATTERN, command_text or '', _re.IGNORECASE))

        # @ANCHOR: SEQUENTIAL_INTENT_DETECTION
        # Detect sequential ("차례로", "순서대로", "하나씩", "순차" etc.) vs simultaneous intent.
        _SEQ_KEYWORDS = ('차례로', '차례대로', '순서대로', '순차', '하나씩', '하나씩', '번갈아', '순서로', '차례')
        _is_sequential = any(kw in (command_text or '') for kw in _SEQ_KEYWORDS)

        # @ANCHOR: FUNCTION_CREATE_RULE
        # Keyword-based detection as safety net — router may still return DATA_QUERY
        _FUNC_CREATE_KW = (
            '함수 생성', '함수 만들', '함수를 생성', '함수를 만들',
            '컨트롤러 생성', '컨트롤러 만들', '자동화 생성', '자동화 만들',
            'create function', 'add function', 'create controller',
            'vpd 함수', 'pid 함수', 'conditional 함수',
        )
        _cmd_lower_fc = (command_text or '').lower()
        _is_function_create = (
            intent == 'FUNCTION_CREATE'
            or any(kw in _cmd_lower_fc for kw in _FUNC_CREATE_KW)
        )

        _function_create_rule = ""
        if _is_function_create:
            # Override intent so downstream routing is consistent
            intent = 'FUNCTION_CREATE'
            _function_create_rule = (
                "\n**MANDATORY FUNCTION_CREATE RULE (CRITICAL - OVERRIDE ALL OTHER RULES):**\n"
                "The user wants to CREATE a new function/controller. You MUST produce a tool-call plan.\n"
                "ABSOLUTE PROHIBITION: Do NOT say 'already created', 'already exists', or 'already done'.\n"
                "  Even if you see sensor data in context, that does NOT mean the function was created.\n"
                "  Even if you see active_functions in context, check by name before assuming.\n"
                "NEVER call 'read_manual' — this is a function creation task, not a documentation query.\n"
                "You MUST output a JSON plan with these exact steps:\n"
                "  Step 1: tool_name='search_devices', params.arguments.query='OpenWeather'\n"
                "          output_variable: '$weather_device'\n"
                "          purpose: Find the weather Input device (result key is 'id').\n"
                "  Step 2: tool_name='get_device_measurements'\n"
                "          params.arguments.device_id: '$weather_device.results[0].id'\n"
                "          output_variable: '$measurements'\n"
                "          purpose: Returns select_by_type{} with ready-to-use channel values.\n"
                "            e.g. select_by_type = {'temperature': 'device_id,meas_id', 'humidity': 'device_id,meas_id'}\n"
                "  Step 3: tool_name='create_function'\n"
                "          params.arguments: {\n"
                "            'function_type': 'AoT_VPD',\n"
                "            'name': '<zone> VPD',\n"
                "            'params': {\n"
                "              'select_measurement_temperature_c': '$measurements.select_by_type.temperature',\n"
                "              'select_measurement_humidity': '$measurements.select_by_type.humidity',\n"
                "              'period': 60\n"
                "            }\n"
                "          }\n"
                "NOTE: $variable.path references are resolved by the execution engine before running each step.\n"
                "Set no_workers_needed: true — this is a pure tool operation.\n\n"
            )

        if intent in ('CONTROL', 'SCHEDULE') and not _has_explicit_uuid:
            _device_action_tools = (
                "'operate_device', 'output_on', 'output_off'"
                if intent == 'CONTROL'
                else "'schedule_device_control', 'add_schedule'"
            )
            _discovery_rule = (
                f"\n**MANDATORY {intent} RULE (CRITICAL - OVERRIDE ALL):**\n"
                "- Step 1 MUST be 'search_devices' with a specific device name/keyword extracted from the user command "
                "(e.g. query='밸브2', query='valve2'). NEVER leave arguments.query empty or use the full sentence.\n"
                f"- In Step 2 ({_device_action_tools}), set device_id to the EXACT device name/keyword "
                "from the user command (e.g. device_id='밸브2'). "
                "DO NOT use variable references like '$device_info.results[0].id'. "
                "The system resolves device_id by name lookup — use the plain name directly.\n"
                "- search_devices Step 1 is for VERIFICATION only, not for providing device_id.\n\n"
            )

        # @ANCHOR: WEATHER_REQUEST_DIFFERENTIATION  [2026-03-24 — 001_WEATHER_LOGIC_UPGRADE patch_3]
        _WEATHER_KW = frozenset([
            '날씨', '기상', '기온', '강수', '풍속', '온도', '습도', '기압',
            'weather', 'temperature', 'humidity', 'wind', 'rain', 'forecast',
        ])
        _ANALYTICAL_KW = frozenset([
            '평균', '최대', '최소', '비교', '추이', '분석', '어제', '지난', '최고', '최저',
            'average', 'max', 'min', 'compare', 'trend', 'history', 'past', 'yesterday',
        ])
        _cmd_lower = (command_text or '').lower()
        _is_weather_query = any(kw in _cmd_lower for kw in _WEATHER_KW)
        _is_analytical = any(kw in _cmd_lower for kw in _ANALYTICAL_KW)

        _weather_query_rule = ""
        if _is_weather_query:
            # Extract the user-supplied zone/device name for the search query.
            # Strip [Page Context:] / [System Context:] prefix first, then remove weather
            # stop-words so only the zone/device name remains.
            # search_devices resolves term aliases (e.g. "1포장" → "1구역") automatically.
            import re as _re_wq
            from aot.ai.ai_routing_service import Tier0Classifier as _T0C
            _user_q_clean = _T0C.extract_user_query(command_text or '')
            _user_q_raw = _re_wq.sub(
                r'(?:기상|날씨|기온|습도|온도|강수|풍속|기압|정보|알려줘|조회|알려줘|주세요|현재|알려|줘|주|weather|temperature|humidity|wind|rain|forecast)',
                ' ', _user_q_clean.lower()
            ).strip()
            _user_q_raw = _re_wq.sub(r'\s+', ' ', _user_q_raw).strip()
            # @ANCHOR: KOREAN_PARTICLE_STRIP  [2026-03-27]
            # Strip Korean grammar particles from token-end positions to clean zone names.
            # e.g. "1포장의" -> "1포장", "온실에서" -> "온실"
            _user_q_raw = _re_wq.sub(
                r'(의|에서의?|으?로|부터|까지|이?라도|이?나|도|만|은|는|이|가|을|를|에|와|과)(?=\s|$)',
                ' ', _user_q_raw
            ).strip()
            _user_q_raw = _re_wq.sub(r'\s+', ' ', _user_q_raw).strip()
            _wq_search_term = _user_q_raw[:30] if _user_q_raw else _user_q_clean[:30]

            if _is_analytical:
                _weather_query_rule = (
                    "\n**WEATHER ANALYTICAL RULE (분석 요청 감지됨):**\n"
                    "MANDATORY 2-step pattern for analytical weather requests:\n"
                    f"  Step 1: tool_name='search_devices'\n"
                    f"          params.arguments.query='{_wq_search_term}'\n"
                    "          output_variable: '$sensor_device'\n"
                    "          purpose: Find the sensor/zone device ID. Uses term-alias mapping.\n"
                    "  Step 2: tool_name='get_sensor_detail'\n"
                    "          params.arguments.loc_id='$sensor_device.results[0].id'\n"
                    "          params.arguments.sensor_type='weather'\n"
                    "          params.arguments.time_range='24h'\n"
                    "          depends_on: [1]\n"
                    "          purpose: Fetch weather time-series for average/min/max/trend analysis.\n"
                    "CRITICAL: Always use 'loc_id' (NOT 'device_id', NOT 'unique_id') for get_sensor_detail.\n"
                    "Set no_workers_needed: true — data query is fully answered by tool results.\n\n"
                )
            else:
                _weather_query_rule = (
                    "\n**WEATHER CURRENT RULE (현재 날씨 요청):**\n"
                    "MANDATORY 2-step pattern:\n"
                    f"  Step 1: tool_name='search_devices'\n"
                    f"          params.arguments.query='{_wq_search_term}'\n"
                    "          output_variable: '$sensor_device'\n"
                    "          purpose: Find the sensor/zone device ID. Uses term-alias mapping (e.g. '1포장' → '1구역').\n"
                    "  Step 2: tool_name='get_sensor_detail'\n"
                    "          params.arguments.loc_id='$sensor_device.results[0].id'\n"
                    "          params.arguments.sensor_type='weather'\n"
                    "          params.arguments.limit=1\n"
                    "          depends_on: [1]\n"
                    "          purpose: Fetch latest weather reading for that device.\n"
                    "CRITICAL: Always use 'loc_id' (NOT 'device_id', NOT 'unique_id') for get_sensor_detail.\n"
                    "Set no_workers_needed: true — data query is fully answered by tool results.\n\n"
                )

        # @ANCHOR: ADVICE_REQUEST_RULE  [2026-03-24]
        # Detect advice/guidance requests about function types, input sensors, or output devices.
        # Routes to structured doc tools (get_function_doc / get_input_doc / get_output_doc).
        _ADVICE_REQUEST_KW = frozenset([
            '조언', '방법', '설명', '가이드', '안내', '어떻게', '알려', '도움',
            '분석', '설정 방법', '사용법', '사용 방법',
            'advice', 'guide', 'how to', 'explain', 'help', 'tips', 'configure',
        ])
        # Function-type keywords (use get_function_doc)
        _FUNC_TYPE_KW = frozenset(['pid', 'vpd', 'conditional'])
        # Input sensor keywords (use get_input_doc)
        _INPUT_TYPE_KW = frozenset([
            'input', '입력', '센서', 'sensor',
            'dht', 'bme', 'sht', 'ds18', 'atlas', 'anyleaf', 'mcp', 'ads',
        ])
        # Output device keywords (use get_output_doc)
        _OUTPUT_TYPE_KW = frozenset([
            'output', '출력', '릴레이', 'relay', 'pwm', 'pump', '펌프',
            'stepper', 'motor', '모터',
        ])

        _is_advice_request = (
            not _is_function_create
            and any(kw in _cmd_lower_fc for kw in _ADVICE_REQUEST_KW)
            and any(kw in _cmd_lower_fc for kw in (_FUNC_TYPE_KW | _INPUT_TYPE_KW | _OUTPUT_TYPE_KW))
        )

        _advice_rule = ""
        if _is_advice_request:
            # Determine domain: function / input / output
            _ft = next((ft for ft in _FUNC_TYPE_KW if ft in _cmd_lower_fc), None)
            _is_input_advice  = not _ft and any(kw in _cmd_lower_fc for kw in _INPUT_TYPE_KW)
            _is_output_advice = not _ft and not _is_input_advice and any(kw in _cmd_lower_fc for kw in _OUTPUT_TYPE_KW)

            if _ft:
                # Function-type advice (PID, VPD, Conditional)
                _advice_rule = (
                    f"\n**ADVICE/GUIDANCE RULE (설정 조언 요청 — {_ft.upper()}):**\n"
                    f"The user wants advice or guidance about '{_ft.upper()}', NOT to create a new function.\n"
                    f"Step 1: tool_name='get_function_doc', "
                    f"params={{\"arguments\": {{\"function_type\": \"{_ft}\"}}}} "
                    f"— Fetch structured '{_ft.upper()}' documentation (params, use_cases, tuning guide).\n"
                    f"Step 2 (optional): tool_name='get_function_detail', "
                    f"params={{\"arguments\": {{\"function_id\": \"<focused_id_from_page_context>\"}}}} "
                    f"— Get current instance settings if a specific device ID is available.\n"
                    f"Set no_workers_needed: false — specialist workers must analyze docs and synthesize advice.\n\n"
                )
            elif _is_input_advice:
                # Input sensor advice
                _advice_rule = (
                    "\n**ADVICE/GUIDANCE RULE (입력 센서 설정 조언 요청):**\n"
                    "The user wants advice about an input sensor device.\n"
                    "Step 1: tool_name='get_input_doc', "
                    "params={\"arguments\": {\"query\": \"<sensor type or keyword from user command>\"}} "
                    "— Fetch sensor catalog info (measurements, interfaces, dependencies).\n"
                    "Step 2: tool_name='search_devices', "
                    "params={\"arguments\": {\"query\": \"<device name or keyword>\"}} "
                    "— Find current configured device instance.\n"
                    "Set no_workers_needed: false — specialist workers must synthesize setup advice.\n\n"
                )
            elif _is_output_advice:
                # Output device advice
                _advice_rule = (
                    "\n**ADVICE/GUIDANCE RULE (출력 장치 설정 조언 요청):**\n"
                    "The user wants advice about an output device.\n"
                    "Step 1: tool_name='get_output_doc', "
                    "params={\"arguments\": {\"query\": \"<output type or keyword from user command>\"}} "
                    "— Fetch output catalog info (output_name, interfaces, dependencies).\n"
                    "Step 2: tool_name='search_devices', "
                    "params={\"arguments\": {\"query\": \"<device name or keyword>\"}} "
                    "— Find current configured output device instance.\n"
                    "Set no_workers_needed: false — specialist workers must synthesize setup advice.\n\n"
                )

        # @ANCHOR: SEQUENTIAL_CONTROL_RULE
        _sequential_rule = ""
        if intent == 'CONTROL' and _is_sequential:
            _sequential_rule = (
                "\n**SEQUENTIAL CONTROL RULE (차례로/순차 감지됨):**\n"
                "- 장치를 '차례로' 또는 '순서대로' 제어할 때는 'operate_device' 대신 "
                "'schedule_device_control'을 사용하여 각 장치에 시간 오프셋을 부여하세요.\n"
                "- 첫 번째 장치: scheduled_time = now (현재 시각, ISO 8601)\n"
                "- N번째 장치: scheduled_time = now + (N-1) × duration_minutes\n"
                "- 예시 (밸브 4개, 각 1분): device1=now+0min, device2=now+1min, device3=now+2min, device4=now+3min\n"
                "- 모든 schedule_device_control 스텝의 state='on'으로 설정하세요.\n\n"
            )

        planner_prompt = (
            "### [Role: Execution Planner] ###\n"
            "MISSION: You are the Routing Planner. Do not act as a chatbot.\n"
            "RULE: NEVER answer the user directly. ALWAYS output strict JSON matching the required schema.\n"
            "RULE: Provide NO conversational text, greetings, or formatting outside the JSON block.\n"
            "RULE: If factual data is missing, your ONLY action is to create a tool call step (e.g., mcp_tool_call) to retrieve it.\n\n"
            "You create execution plans. You do NOT execute anything.\n\n"
            "**Rules:**\n"
            "1. Break the user's goal into atomic steps. Each step = one tool call or one decision.\n"
            "2. Express dependencies with 'depends_on' (step_id references).\n"
            "3. For complex intents, use 'conditional' steps with $variable references.\n"
            "4. Select tools ONLY from the provided tool_manifest.\n"
            "5. Mark steps requiring safety validation with 'safety_check_required': true.\n"
            "6. Set 'no_workers_needed': true ONLY if the goal is fully answerable by tool calls alone "
            "(e.g., a simple data read, device scheduling). If expert analysis, cross-domain synthesis, or domain knowledge "
            "is needed, set 'no_workers_needed': false so specialist workers are consulted.\n"
            "   → SCHEDULE intent: ALWAYS set 'no_workers_needed': true (scheduling is a pure tool operation).\n"
            "   → FUNCTION_CREATE intent: ALWAYS set 'no_workers_needed': true (function creation is a pure tool operation).\n\n"
            "**Strategy Types:** 'sequential' (default), 'parallel', 'conditional'\n\n"
            f"{_discovery_rule}{_sequential_rule}{_weather_query_rule}{_advice_rule}{_function_create_rule}USER COMMAND: \"{command_text}\"\n"
            "Respond with ONLY a valid JSON object:\n"
            '{\n'
            '  "strategy": "sequential|parallel|conditional",\n'
            '  "steps": [\n'
            '    {\n'
            '      "step_id": 1,\n'
            '      "tool_name": "mcp_tool_name|virtual_tool_name",\n'  # [OPTION_D] LLM no longer provides action_type
            '      "params": { "tool_name": "...", "arguments": { ... } },\n'
            '      "purpose": "What this step does",\n'
            '      "depends_on": [],\n'
            '      "output_variable": "$var_name"\n'
            '    }\n'
            '  ],\n'
            '  "estimated_tools": ["tool1", "tool2"],\n'
            '  "safety_check_required": false,\n'
            '  "no_workers_needed": false,\n'
            '  "insight": "Brief plan summary in the user\'s language. '
            'Use future/progressive tense — describe what WILL be done, NOT what has been done. '
            'NEVER use past-tense completion phrases like \'예약했습니다\', \'완료했습니다\', \'등록했습니다\'. '
            'Use: \'예약하겠습니다\', \'검색 후 예약 요청을 드리겠습니다\' etc."\n'
            '}'
        )

        try:
            engine = AIAgentService.get_engine(planner_agent.unique_id)
            if not engine:
                logger.error("[Planner] Failed to initialize engine.")
                if not stream:
                    return None
                def no_engine_gen():
                    yield {"status": "error", "message": "Failed to initialize engine."}
                return no_engine_gen()

            if stream:
                def plan_generator():
                    yield {"status": "planning"}
                    result = engine.run_reasoning(planner_context, planner_prompt)
                    if result and result.get('steps'):
                        for i, step in enumerate(result['steps']):
                            if 'step_id' not in step: step['step_id'] = i + 1
                        yield {"status": "plan_ready", "insight": result.get('insight'), "plan": result}
                    else:
                        yield {"status": "plan_failed", "insight": result.get('insight')}
                return plan_generator()

            result = engine.run_reasoning(planner_context, planner_prompt)
            
            # TTFT Optimization: Push a neutral "planning" status — NOT the Planner insight.
            # Planner insight describes what WILL happen (plan intent), not execution result.
            # Showing it verbatim before execution gives users a false sense of completion.
            q = sse_queue_var.get()
            if q:
                q.put({"type": "planning_status", "content": "..."})

            if result.get('steps'):
                logger.info(f"[Planner] Generated plan with {len(result['steps'])} steps, strategy: {result.get('strategy')}")
                # Ensure every step has an ID
                for i, step in enumerate(result['steps']):
                    if 'step_id' not in step: step['step_id'] = i + 1
                return result
            # If LLM returned insight but no steps, treat as planning failure
            logger.info("[Planner] No execution steps generated. Falling back to legacy.")
            # @ANCHOR: SCHEDULE_CONTROL_FALLBACK_PLAN  [2026-03-24]
            # For SCHEDULE/CONTROL intent: build minimal search-only plan so the chain
            # runs and at least verifies the device exists, instead of falling silently
            # to legacy workers (which produces a no-op "예약하겠습니다" response).
            if intent in ('SCHEDULE', 'CONTROL'):
                import re as _re2
                _kw = _re2.findall(r'[가-힣a-zA-Z0-9]+', command_text or '')
                _q = ' '.join(_kw[:5]) if _kw else (command_text or '')[:40]
                logger.warning("[Planner][FALLBACK] SCHEDULE/CONTROL — injecting search-only fallback plan.")
                return {
                    "strategy": "sequential",
                    "steps": [
                        {
                            "step_id": 1,
                            "tool_name": "search_devices",
                            "params": {"arguments": {"query": _q}},
                            "purpose": "Fallback: confirm device exists before scheduling",
                            "depends_on": [],
                            "output_variable": "$device_info"
                        }
                    ],
                    "no_workers_needed": False,
                    "insight": result.get('insight', '장치를 확인합니다.')
                }
            # @ANCHOR: DATA_QUERY_FALLBACK_PLAN  [2026-03-27]
            # DATA_QUERY + weather intent: inject minimal 2-step plan so the chain always
            # runs and real sensor data is attempted, mirroring SCHEDULE/CONTROL fallback above.
            if intent == 'DATA_QUERY' and _is_weather_query:
                _fb_q = _wq_search_term or (command_text or '')[:30]
                logger.warning("[Planner][FALLBACK] DATA_QUERY weather — injecting 2-step fallback plan.")
                return {
                    "strategy": "sequential",
                    "steps": [
                        {"step_id": 1, "tool_name": "search_devices",
                         "params": {"arguments": {"query": _fb_q}},
                         "purpose": "Fallback: find sensor/zone device",
                         "depends_on": [], "output_variable": "$sensor_device"},
                        {"step_id": 2, "tool_name": "get_sensor_detail",
                         "params": {"arguments": {"loc_id": "$sensor_device.results[0].id",
                                                  "sensor_type": "weather", "limit": 1}},
                         "purpose": "Fallback: fetch latest weather reading",
                         "depends_on": [1], "output_variable": "$sensor_data"},
                    ],
                    "no_workers_needed": True,
                    "insight": result.get('insight', '날씨 데이터를 조회합니다.')
                }
            return None
        except Exception as e:
            err_msg = str(e)
            logger.error(f"[Planner] Error: {err_msg}")
            
            # v6.3.1: Dynamic Fallback (No Hardcoding)
            if any(kw in err_msg for kw in ["Resource exhausted", "429", "Quota"]):
                failing_entry_id = planner_agent.entry_id
                logger.warning(f"[v6] Provider {failing_entry_id} hit quota. Finding alternative from user-defined agents...")
                
                # Find an alternative agent using a DIFFERENT provider
                alt_agent = AIAgent.query.filter(
                    AIAgent.is_activated == True,
                    AIAgent.entry_id != failing_entry_id
                ).order_by(
                    # Prefer agents with higher tiers or specific pipeline roles
                    AIAgent.model_tier.desc(),
                    AIAgent.pipeline_role.desc()
                ).first()
                
                if alt_agent:
                    try:
                        logger.info(f"[v6] Dynamic fallback using: {alt_agent.name} (Provider: {alt_agent.entry_id})")
                        alt_engine = AIAgentService.get_engine(alt_agent.unique_id)
                        if alt_engine:
                            # Use the same context/prompt but on the alternative engine
                            result = alt_engine.run_reasoning(planner_context, planner_prompt)
                            if result.get('steps'):
                                logger.info(f"[v6] Fallback successful via {alt_agent.name}")
                                return result
                    except Exception as alt_e:
                        logger.error(f"[v6] Dynamic fallback to {alt_agent.name} failed: {alt_e}")
            
            return None


    # @ANCHOR: EXECUTOR_ACTION_CHAIN
    @staticmethod
    def _execute_action_chain(agent_id, plan, context, chat_history=None):
        """
        v6 Executor: Sequentially executes steps from a plan.
        Handles variable substitution between steps ($var_name).
        Returns (execution_logs, pending_actions) where pending_actions are
        physical control steps that require human approval and must NOT be executed.
        """
        from aot.ai.services.ai_action_service import AIActionService
        from aot.ai.services.ai_agent_service import AIAgentService
        from aot.ai.services.safety_service import SafetyService, SafetyViolation
        import json

        # [APPROVAL_GATE] Tools that require human approval — never auto-execute.
        # @ANCHOR: _APPROVAL_REQUIRED_TOOLS — now DERIVED from the SSOT tool registry
        # (Phase 1): every `mutating` tool PLUS the `physical`/scheduling tools
        # (operate_device, set_output_state, schedule_device_control, add_schedule).
        # Was hand-synced with _VIRTUAL_APPROVAL_TOOLS in ai_dispatch_service.py; both
        # now derive from the same registry so the two lists cannot drift.
        from aot.ai.services.tool_registry import approval_required_tools
        _APPROVAL_REQUIRED_TOOLS = approval_required_tools()

        executor_agent = AIAgent.query.filter_by(pipeline_role='executor', is_activated=True).first()
        # Fallback to current agent if no specific executor
        exec_id = executor_agent.unique_id if executor_agent else agent_id

        steps = plan.get('steps', [])
        variables = {}
        execution_logs = []
        pending_actions = []  # Control steps pending human approval

        logger.info(f"[Executor] Starting action chain with {len(steps)} steps using agent {exec_id}")

        import threading
        from concurrent.futures import ThreadPoolExecutor, as_completed

        state_lock = threading.Lock()
        completed_step_ids = set()
        pending_steps = steps.copy()

        def execute_single_step(step):
            try:
                # 1. Resolve variables in params
                with state_lock:
                    params = step.get('params', {}).copy()
                    
                    if 'arguments' in params and isinstance(params['arguments'], dict):
                        _inner_args = params.pop('arguments')
                        params = {**params, **_inner_args}

                    params = AIAgentService._resolve_variables(params, variables)

                # RC-2: APPROVAL_GATE runs BEFORE UNRESOLVED_VAR_GUARD for approval-required tools.
                # When search_devices returns 0, operate_device step has $device_id still unresolved.
                # UNRESOLVED_VAR_GUARD would fire first and skip the step silently — APPROVAL_GATE
                # never fires, chain_pending=[] and FIX-A/FIX-C never trigger in ai_agent_service.py.
                # Fix: for _APPROVAL_REQUIRED_TOOLS, check APPROVAL_GATE first so the step is
                # intercepted as pending_approval even when variables are still unresolved.
                _step_tool = step.get('tool_name') or step.get('params', {}).get('tool_name', '')

                # [APPROVAL_GATE] Intercept physical control tools — checked BEFORE UNRESOLVED_VAR_GUARD
                if _step_tool in _APPROVAL_REQUIRED_TOOLS:
                    # @ANCHOR: DISCOVERY_GUARD
                    # Advisory only: log when discovery returned 0 results, but do NOT block.
                    # The actual tool (operate_device / schedule_device_control) validates device
                    # existence by name at execution time. Blocking here on 0 search results
                    # causes regressions when search is imprecise but device name is valid.
                    with state_lock:
                        _disc = variables.get('$device_info')
                    if _disc is not None and isinstance(_disc, dict):
                        _disc_count = _disc.get('count', 0)
                        if _disc_count == 0 and not _disc.get('results'):
                            logger.warning(
                                f"[DISCOVERY_GUARD] Step {step.get('step_id')}: "
                                f"search_devices returned 0 results — proceeding anyway (tool validates by name)."
                            )

                    with state_lock:
                        if 'params' in step and isinstance(step['params'], dict):
                            step['params'] = AIAgentService._resolve_variables(step['params'], variables)
                    AIAgentService._validate_and_normalize_action(step)
                    # Inject display_summary for UI approval bubble
                    if not step.get('display_summary'):
                        _name = step.get('params', {}).get('name') or ''
                        _ftype = step.get('params', {}).get('function_type') or _step_tool
                        step['display_summary'] = f"{_step_tool}: {_name}" if _name else _ftype
                    # @ANCHOR: APPROVAL_PENDING_DESCRIPTION  [2026-03-27]
                    # Inject description from display_summary for JS _appendMessage compatibility
                    step.setdefault(
                        'description',
                        step.get('display_summary') or
                        f"{step.get('tool_name', 'operate_device')} on {step.get('target_id', 'device')}"
                    )
                    logger.info(f"[APPROVAL_GATE] Step {step.get('step_id')} tool='{_step_tool}' intercepted.")
                    with state_lock:
                        pending_actions.append(step)
                        # @ANCHOR: CHAIN_RESULTS_PENDING_APPROVAL_FORMAT  [2026-03-27]
                        # execution_logs (→ chain_results) MUST contain a plain string with 'pending_approval'
                        # so PhysicalGuard in ai_agent_service.py counts this step as non-failure.
                        # Format: "Step <id> (pending_approval) Intercepted: '<tool>' requires human approval."
                        execution_logs.append(f"Step {step.get('step_id')} (pending_approval) Intercepted: '{_step_tool}' requires human approval.")
                    return

                # @ANCHOR: UNRESOLVED_VAR_GUARD  [2026-03-27]
                # If any param still starts with '$' after resolution, the prior step's
                # output_variable was missing (e.g. search returned 0 results).
                # Skip this step cleanly to avoid passing literal '$...' strings to tool handlers.
                # NOTE: This guard runs AFTER APPROVAL_GATE so approval-required tools are
                # always intercepted as pending_approval even when variables are unresolved.
                _unresolved_keys = [k for k, v in params.items()
                                    if isinstance(v, str) and v.startswith('$') and k != 'context']
                if _unresolved_keys:
                    _uv_tool = step.get('tool_name', '')
                    with state_lock:
                        execution_logs.append(
                            f"Step {step.get('step_id')} tool={_uv_tool} Skipped: "
                            f"unresolved variable(s) {_unresolved_keys} — prior step returned no results."
                        )
                    logger.warning(f"[Executor][UNRESOLVED_VAR_GUARD] Step {step.get('step_id')} "
                                   f"skipped: unresolved {_unresolved_keys}")
                    return

                action_type = step.get('action_type')
                target_id = step.get('target_id')

                # 2. Safety Check
                if step.get('safety_check_required'):
                    try:
                        SafetyService.validate(action_type, target_id, params)
                    except SafetyViolation as sv:
                        with state_lock:
                            execution_logs.append(f"Step {step.get('step_id')} Blocked by Safety: {sv}")
                        return

                # 3. Handle Variable Substitution for target_id
                with state_lock:
                    if isinstance(target_id, str) and target_id.startswith('$'):
                        target_id = variables.get(target_id, target_id)

                    # [FIX-BUG09] @ANCHOR: RESOLVE_STEP_PARAMS
                    if 'params' in step and isinstance(step['params'], dict):
                        step['params'] = AIAgentService._resolve_variables(step['params'], variables)
                
                params['context'] = context
                valid, err = AIAgentService._validate_and_normalize_action(step)
                
                with state_lock:
                    if not valid:
                        variables[f"${step.get('id', 'err')}"] = f"Error: {err}"
                        # Log validation failure so PhysicalGuard can see it in chain_results
                        execution_logs.append(f"Step {step.get('step_id')} Validation Failed: {err}")
                        return

                action_type = step.get('action_type') or action_type
                target_id = step.get('target_id') or target_id
                params = step.get('params', params)
                params['context'] = context

                # [APPROVAL_GATE] Second check after normalization
                _norm_tool = params.get('tool_name', '')
                if _norm_tool in _APPROVAL_REQUIRED_TOOLS:
                    if not step.get('display_summary'):
                        _name = params.get('name') or ''
                        step['display_summary'] = f"{_norm_tool}: {_name}" if _name else _norm_tool
                    # Inject description from display_summary for JS _appendMessage compatibility
                    step.setdefault(
                        'description',
                        step.get('display_summary') or
                        f"{step.get('tool_name', 'operate_device')} on {step.get('target_id', 'device')}"
                    )
                    logger.info(f"[APPROVAL_GATE] Step {step.get('step_id')} normalized tool='{_norm_tool}' intercepted.")
                    with state_lock:
                        pending_actions.append(step)
                        # @ANCHOR: CHAIN_RESULTS_PENDING_APPROVAL_FORMAT  [2026-03-27]
                        # Second intercept site (post-normalization). Same format as first site.
                        execution_logs.append(f"Step {step.get('step_id')} (pending_approval) Intercepted: '{_norm_tool}' requires human approval.")
                    return

                # 4. Execute
                res = AIActionService.execute_action(action_type, target_id, params)

                # 5. Capture output variable
                with state_lock:
                    out_var = step.get('output_variable')
                    if out_var and out_var.startswith('$'):
                        variables[out_var] = res.get('result') or res.get('data') or res

                    log_entry = f"Step {step.get('step_id')} tool={_step_tool} ({action_type}) Success: {json.dumps(res, ensure_ascii=False)[:500]}"
                    execution_logs.append(log_entry)

            except Exception as e:
                with state_lock:
                    log_entry = f"Step {step.get('step_id')} ({action_type}) Failed: {str(e)}"
                    execution_logs.append(log_entry)
                    logger.error(f"[Executor] {log_entry}")

        with ThreadPoolExecutor(max_workers=5) as pool:
            while pending_steps:
                # Find ready steps (no dependencies, or all dependencies met)
                ready_steps = []
                for s in pending_steps:
                    deps = s.get('depends_on', [])
                    if isinstance(deps, str): deps = [deps]
                    # Convert completed_step_ids to strings for robust comparison
                    completed_strs = {str(cid) for cid in completed_step_ids}
                    if not deps or all(str(d) in completed_strs for d in deps):
                        ready_steps.append(s)

                if not ready_steps:
                    # Fallback for cyclic dependencies
                    ready_steps = [pending_steps[0]]

                # Execute ready steps concurrently
                futures = {pool.submit(execute_single_step, s): s for s in ready_steps}
                for f in as_completed(futures):
                    s = futures[f]
                    f.result() # Surface any fatal exceptions not caught in execute_single_step
                    with state_lock:
                        completed_step_ids.add(s.get('step_id'))
                        pending_steps.remove(s)

        return execution_logs, pending_actions


    @staticmethod
    def _resolve_variables(params, variables):
        """Helper to recursively replace $var and $var.path[idx].field with values in dict/list."""
        import re as _re
        from aot.ai.services.ai_agent_service import AIAgentService

        def _resolve_path(root, path_str):
            """Walk a.b[0].c style path on a nested dict/list."""
            parts = _re.split(r'\.|\[(\d+)\]', path_str)
            cur = root
            i = 0
            while i < len(parts):
                p = parts[i]
                if p is None:
                    i += 1
                    continue
                if p == '':
                    i += 1
                    continue
                if p.isdigit():
                    try:
                        cur = cur[int(p)]
                    except (IndexError, TypeError, KeyError):
                        return None
                elif isinstance(cur, dict):
                    cur = cur.get(p)
                    if cur is None:
                        return None
                else:
                    return None
                i += 1
            return cur

        if isinstance(params, dict):
            return {k: AIAgentService._resolve_variables(v, variables) for k, v in params.items()}
        elif isinstance(params, list):
            return [AIAgentService._resolve_variables(v, variables) for v in params]
        elif isinstance(params, str) and params.startswith('$'):
            # Exact match first
            if params in variables:
                return variables[params]
            # Path expression: $var_name.field[0].subfield
            dot_idx = params.find('.')
            bracket_idx = params.find('[')
            sep = -1
            if dot_idx > 0 and (bracket_idx < 0 or dot_idx < bracket_idx):
                sep = dot_idx
            elif bracket_idx > 0:
                sep = bracket_idx
            if sep > 0:
                base_var = params[:sep]
                rest = params[sep + 1:] if params[sep] == '.' else params[sep:]
                if base_var in variables:
                    resolved = _resolve_path(variables[base_var], rest)
                    if resolved is not None:
                        return resolved
        return params
