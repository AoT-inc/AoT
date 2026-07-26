# coding=utf-8
import json
import logging
import requests
from aot.ai.agents.base_ai import AbstractAI
from flask_babel import lazy_gettext as lg

logger = logging.getLogger(__name__)

AI_INFORMATION = {
    'ai_name_unique': 'gemini',
    'ai_manufacturer': 'Google',
    'ai_category': 'llm',
    'ai_name': 'Google Gemini',
    'ai_type': 'LLM',
    'auth_methods': ['api_key'],
    'auth_link': 'https://aistudio.google.com/app/apikey',
    'default_endpoint': '',
    'endpoint_hint': 'Default Google API',
    'models': [
        {'value': 'gemini-3.5-flash', 'label': 'Gemini 3.5 Flash (Flagship — best agentic/coding)'},
        {'value': 'gemini-3.1-pro-preview', 'label': 'Gemini 3.1 Pro (Highest capability, preview)'},
        {'value': 'gemini-3-flash-preview', 'label': 'Gemini 3 Flash (Pro-level + Flash speed, preview)'},
        {'value': 'gemini-3.1-flash-lite', 'label': 'Gemini 3.1 Flash Lite (Fastest)'},
        {'value': 'gemini-2.5-pro', 'label': 'Gemini 2.5 Pro (Stable, deep reasoning)'},
        {'value': 'gemini-2.5-flash', 'label': 'Gemini 2.5 Flash (Stable, Recommended)'},
        {'value': 'gemini-2.5-flash-lite', 'label': 'Gemini 2.5 Flash Lite (Economy)'},
    ],
    'description': lg("Google's state-of-the-art multimodal AI engine, capable of understanding and generating text, code, and images with a massive context window."),
    'url_manufacturer': 'https://ai.google.dev/',
    'custom_options': [
        {'id': 'temperature', 'type': 'float', 'default': 0.7, 'name': 'Temperature (0.0 - 2.0)'},
        {'id': 'max_tokens', 'type': 'int', 'default': 2048, 'name': 'Max Output Tokens'},
        {'id': 'top_p', 'type': 'float', 'default': 0.95, 'name': 'Top P'},
        {'id': 'top_k', 'type': 'int', 'default': 40, 'name': 'Top K'}
    ]
}

class GeminiAI(AbstractAI):
    """
    Google Gemini AI Engine Implementation.
    Uses the Gemini REST API (generativelanguage.googleapis.com) for multimodal reasoning.

    @phase active
    @stability stable
    @dependency AbstractAI, BrainResolver
    """
    MCP_SPECIALTY = "General Purpose Assistant (Advanced Multimodal)"
    supports_vision = True  # Gemini models accept inline_data image parts

    def __init__(self, agent_config):
        super().__init__(agent_config)
        self.base_url = self.api_endpoint or "https://generativelanguage.googleapis.com"
        
        # v6.2: Load cached content ID from custom options if available
        try:
            options = json.loads(agent_config.custom_options_json) if agent_config.custom_options_json else {}
            self.cached_content_id = options.get('cached_content_id')
        except:
            self.cached_content_id = None
            
        logger.info(f"Initializing GeminiAI with endpoint: {self.base_url}, cached_content: {self.cached_content_id}")

    def get_max_output_tokens(self):
        """
        Gemini specific output tokens.
        Can handle much larger output than Groq.
        """
        budgets = {
            'lightweight': 1024,
            'standard': 4096,
            'heavy': 32768
        }
        db_val = getattr(self.agent_config, 'max_tokens', 0)
        return db_val if db_val > 0 else budgets.get(self.model_tier, 4096)

    def get_context_budget(self):
        """
        Gemini-specific input character budget. AbstractAI's generic 'standard'
        cap (100k chars) was sized for engines without Gemini's context window
        and left almost no room once get_master_context() + the tool schema
        (spatial hierarchy, manual_index, note digests, ~50 tool declarations)
        filled it — every real turn hit "Near budget limit" from message one
        and got hard-truncated, discarding conversation history and tool
        results before the model ever saw them. Gemini 2.5/3.x models support
        ~1M-token context regardless of tier, so scale the budget to that
        instead of reusing the shared cross-engine table.
        """
        budgets = {
            'lightweight': 100000,   # ~25k tokens
            'standard': 600000,      # ~150k tokens
            'heavy': 3000000         # ~750k tokens
        }
        return budgets.get(self.model_tier, 600000)

    def _build_tools_schema(self, context):
        """
        Builds Gemini function_declarations from context.capabilities.

        Reads system_tools and mcp_tools from capabilities.
        Skips read_manual and get_detailed_manifest.
        Returns [] when no capabilities (backward compat).
        """
        capabilities = context.get('capabilities', {})
        system_tools = capabilities.get('system_tools', [])
        mcp_tools = capabilities.get('mcp_tools', [])

        declarations = []
        _skip = {'read_manual', 'get_detailed_manifest'}
        # Dedupe by name ACROSS both lists. Several tools (search_devices,
        # get_sensor_detail, operate_device, get_device_list, add_schedule …) exist
        # BOTH as a virtual system_tool AND as an AoT MCP tool. Declaring the same
        # name twice makes Gemini reject the WHOLE request with 400 "Duplicate
        # function declaration found: <name>" — so once the MCP server is warm, every
        # tool-bearing query crashed and the AI could never look up a device.
        _seen = set()

        for tool in system_tools:
            name = tool.get('tool_name') or tool.get('action_type', '')
            if not name or name in _skip or name in _seen:
                continue
            _seen.add(name)
            declarations.append({
                'name': name,
                'description': tool.get('description', ''),
                'parameters': {
                    'type': 'object',
                    'properties': {
                        'arguments': {
                            'type': 'object',
                            'description': tool.get('usage_hint', '')
                        }
                    },
                    'required': []
                }
            })

        for tool in mcp_tools:
            name = tool.get('tool_name', '')
            if not name or name in _skip or name in _seen:
                continue
            _seen.add(name)
            declarations.append({
                'name': name,
                'description': tool.get('description', ''),
                'parameters': {
                    'type': 'object',
                    'properties': {
                        'arguments': {
                            'type': 'object',
                            'description': tool.get('usage_hint', '')
                        }
                    },
                    'required': []
                }
            })

        return declarations

    def run_reasoning(self, context, goal):
        """
        Executes reasoning via Gemini REST API with native Function Calling support.

        Multi-turn loop (up to 3 function-call turns):
        1. Build payload with tools[] schema if capabilities exist
        2. POST to generateContent
        3. If response has functionCall parts → execute tool, append functionResponse, loop
        4. If response has text → return _safe_api_result(text)
        5. If MAX_FC_TURNS reached with no text → inject final-answer prompt, loop once
        """
        import time

        # Fallback deliberately a stable (non-preview) model — preview models can be
        # shut down abruptly (e.g. gemini-3.1-flash-lite-preview, retired 2026-06).
        model = self.model_name or "gemini-2.5-flash"
        if model.startswith("models/"):
            model = model.replace("models/", "")

        # v14.1: Default to v1beta for all models.
        api_version = "v1beta"
        url = f"{self.base_url.rstrip('/')}/{api_version}/models/{model}:generateContent?key={self.api_key}"

        key_status = f"PRESENT(len={len(self.api_key)})" if self.api_key else "MISSING"
        logger.info(f"[GeminiAI] POST generateContent model={model} (Version: {api_version}, Key: {key_status})")

        headers = {"Content-Type": "application/json"}

        # Build tools schema from context.capabilities (empty list = plain text mode)
        tools_schema = self._build_tools_schema(context)
        logger.info(f"[GeminiAI] tools_schema count={len(tools_schema)}")

        # Multi-turn conversation payload
        contents = []
        prompt = self._build_prompt(context, goal)
        # Multimodal: prepend attached images as inline_data parts (raw base64,
        # no data: prefix), then the text part. Plain text when no images.
        _parts = []
        try:
            from aot.ai.ai_request_context import get_attachments
            _atts = get_attachments()
            for a in _atts:
                _parts.append({"inline_data": {"mime_type": a["media_type"], "data": a["base64_data"]}})
            if _atts:
                logger.info(f"[GeminiAI] Attaching {len(_atts)} image(s) to request")
        except Exception as _att_err:
            logger.warning(f"[GeminiAI] attachment build failed, sending text only: {_att_err}")
            _parts = []
        _parts.append({"text": prompt})
        contents.append({"parts": _parts})

        payload = {
            "contents": contents,
            "generationConfig": {
                "temperature": self.temperature or 0.7,
                "maxOutputTokens": self.get_max_output_tokens()
            }
        }

        # Attach tools[] only when non-empty (backward compat: no tools key = plain text)
        if tools_schema:
            payload["tools"] = [{"function_declarations": tools_schema}]

        # v6.2: Gemini Context Caching Support
        cached_content = getattr(self, 'cached_content_id', None)
        if cached_content:
            payload["cachedContent"] = cached_content

        # v14.1: system_instruction only on v1beta
        if self.system_prompt:
            payload["system_instruction"] = {
                "parts": [{"text": self.system_prompt}]
            }

        max_retries = 5
        retry_delay = 5
        max_total_wait = 60
        max_fc_turns = 3

        total_waited = 0
        for attempt in range(max_retries):
            fc_turn = 0
            while fc_turn < max_fc_turns:
                try:
                    response = requests.post(url, json=payload, headers=headers, timeout=self.timeout)
                    response.raise_for_status()
                    data = response.json()

                    # Extract parts from candidate
                    parts = data.get("candidates", [{}])[0].get("content", {}).get("parts", [])

                    # Check for function-call parts
                    has_fc = any('functionCall' in p for p in parts)
                    if has_fc and fc_turn < max_fc_turns - 1:
                        logger.info(f"[GeminiAI] FunctionCall turn {fc_turn + 1}")
                        for part in parts:
                            fc = part.get('functionCall')
                            if not fc:
                                continue
                            tool_name = fc.get('name', '')
                            raw_args = fc.get('args', {})

                            # @ANCHOR: GEMINI_NATIVE_APPROVAL_GATE (agent-loop redesign,
                            # docs/design/ai-agent-loop.md §5). Every OTHER engine only
                            # returns {insight, actions} — it never executes anything
                            # itself, so the caller (AgentLoopService / _dispatch_actions)
                            # always gets a chance to gate writes/physical actions before
                            # they run. Gemini's native function-calling loop is the one
                            # exception: left unchecked it would call execute_action()
                            # directly for a mutating tool (create_function, modify_output,
                            # delete_input, …) the moment the model picks it — execute_action
                            # only hard-blocks PHYSICAL_TOOLS, not general mutations — so a
                            # gemini-backed agent could self-approve a mutation no other
                            # engine can. Stop the internal loop and hand the call back as a
                            # normal proposed action instead, so gemini behaves exactly like
                            # every other engine and the same single approval gate applies
                            # regardless of which model the user has active (G5).
                            action = {
                                'tool_name': tool_name,
                                'params': {'arguments': raw_args}
                            }
                            from aot.ai.services.ai_action_service import AIActionService
                            # ask_user is a control-flow tool, not an executable one:
                            # it has no handler, so executing it here would error and get
                            # swallowed (the model then falls back to a prose question and
                            # the caller never sees the structured question/options). Hand
                            # it back so the orchestrator (AgentLoopService) can turn it
                            # into the actual clarification turn — same as an approval tool.
                            if tool_name == 'ask_user' or AIActionService.requires_approval(tool_name):
                                logger.info(f"[GeminiAI] tool={tool_name} is control-flow/approval — "
                                            f"returning as an action instead of auto-executing.")
                                return {"insight": "", "actions": [action]}

                            logger.info(f"[GeminiAI] executing tool={tool_name} args={str(raw_args)[:200]}")

                            # Execute tool via AIActionService
                            from aot.ai.ai_routing_service import AIRoutingService
                            valid, _ = AIRoutingService._validate_and_normalize_action(action)
                            exec_result = None
                            if valid:
                                action_type = action.get('action_type')
                                target_id = action.get('target_id')
                                params = action.get('params')
                                exec_result = AIActionService.execute_action(
                                    action_type, target_id, params
                                )
                            tool_result_str = json.dumps(exec_result, ensure_ascii=False, default=str) if exec_result else '{"error": "tool execution failed"}'

                            # Append model's functionCall turn
                            contents.append({"parts": [part]})
                            # Append functionResponse
                            contents.append({
                                "parts": [{
                                    "functionResponse": {
                                        "name": tool_name,
                                        "response": {"result": tool_result_str}
                                    }
                                }]
                            })
                            fc_turn += 1
                            break  # Process one functionCall per turn

                    # No functionCall → check for text
                    for part in parts:
                        if 'text' in part:
                            raw_text = part['text']
                            logger.debug(f"[GeminiAI] Raw response: {raw_text[:300]}")
                            return self._safe_api_result(raw_text, "GeminiAI")

                    # No text at MAX_FC_TURNS → inject final answer prompt
                    if fc_turn >= max_fc_turns:
                        logger.info("[GeminiAI] MAX_FC_TURNS reached, injecting final-answer prompt")
                        contents.append({
                            "parts": [{"text": "You have reached the maximum number of tool-call turns. Provide your final answer in a JSON object with 'insight' and 'actions' fields based on the tool results above."}]
                        })
                        fc_turn += 1
                        continue  # One more turn to get text

                except requests.exceptions.HTTPError as e:
                    status_code = e.response.status_code if e.response is not None else "unknown"
                    if status_code == 429:
                        if attempt < max_retries - 1 and total_waited + retry_delay <= max_total_wait:
                            logger.warning(f"[GeminiAI] 429 Resource exhausted. Attempt {attempt + 1}/{max_retries}. Retrying in {retry_delay}s...")
                            time.sleep(retry_delay)
                            total_waited += retry_delay
                            retry_delay = min(retry_delay * 2, 20)
                            continue
                    body = e.response.text if e.response is not None else ""
                    error_msg = body
                    try:
                        parsed_err = json.loads(body)
                        if 'error' in parsed_err:
                            logger.error(f"[GeminiAI] API Error Details: {json.dumps(parsed_err['error'], indent=2)}")
                            error_msg = parsed_err['error'].get('message', body)
                    except Exception:
                        pass
                    msg = f"Gemini API Error ({status_code}) after {attempt + 1} retries: {error_msg}"
                    logger.error(f"[GeminiAI] {msg}")
                    raise RuntimeError(msg)

                except requests.exceptions.Timeout:
                    msg = f"Gemini API timeout after {self.timeout}s"
                    logger.error(f"[GeminiAI] {msg}")
                    raise RuntimeError(msg)
                except requests.exceptions.ConnectionError:
                    msg = "Gemini API connection failed"
                    logger.error(f"[GeminiAI] {msg}")
                    raise RuntimeError(msg)
                except Exception as e:
                    msg = f"Gemini API Critical Error: {str(e)}"
                    logger.error(f"[GeminiAI] {msg}")
                    raise RuntimeError(msg)

            # If we exited the fc loop due to retry (429), restart outer retry loop
            # Otherwise fall through to return a parse-failed result
            break

        # Fallback: no text response obtained
        logger.warning("[GeminiAI] No text response after all function-call turns")
        return self._safe_api_result('{"insight": "No response from Gemini after maximum tool-call turns.", "actions": []}', "GeminiAI")

    def parse_actions(self, raw_response):
        return raw_response.get('actions', [])
