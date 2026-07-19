# coding=utf-8
import json
import logging
import requests
from aot.ai.agents.base_ai import AbstractAI
from flask_babel import lazy_gettext as lg

logger = logging.getLogger(__name__)

# Models that reject non-default temperature/top_p/top_k (400 invalid_request_error).
# @ANCHOR: NO_SAMPLING_PARAMS [2026-07-07]
_NO_SAMPLING_PARAM_PREFIXES = ('claude-opus-4-7', 'claude-opus-4-8', 'claude-sonnet-5', 'claude-fable-5', 'claude-mythos-5')

AI_INFORMATION = {
    'ai_name_unique': 'anthropic',
    'ai_manufacturer': 'Anthropic',
    'ai_name': 'Anthropic (Claude)',
    'ai_type': 'LLM',
    'auth_methods': ['api_key'],
    'auth_link': 'https://console.anthropic.com/settings/keys',
    'default_endpoint': 'https://api.anthropic.com/v1/messages',
    'endpoint_hint': 'Official Anthropic API',
    'models': [
        {'value': 'claude-opus-4-8', 'label': 'Claude Opus 4.8'},
        {'value': 'claude-sonnet-5', 'label': 'Claude Sonnet 5'},
        {'value': 'claude-sonnet-4-6', 'label': 'Claude Sonnet 4.6'},
        {'value': 'claude-haiku-4-5', 'label': 'Claude Haiku 4.5'},
    ],
    'description': lg("Anthropic's Claude engine, known for human-like reasoning, sophisticated analysis, and safe response generation."),
    'url_manufacturer': 'https://www.anthropic.com/',
    'custom_options': [
        {'id': 'temperature', 'type': 'float', 'default': 0.7, 'name': 'Temperature (0.0 - 1.0)'},
        {'id': 'max_tokens', 'type': 'int', 'default': 1024, 'name': 'Max Output Tokens'}
    ]
}

class AnthropicAI(AbstractAI):
    """
    Anthropic (Claude) AI Engine Implementation.
    Uses the Anthropic Messages API for general-purpose reasoning.

    @phase active
    @stability stable
    @dependency AbstractAI, BrainResolver
    """
    MCP_SPECIALTY = "General Purpose Assistant (Claude Analysis)"
    supports_vision = True  # Claude models accept base64 image content blocks

    def __init__(self, agent_config):
        super().__init__(agent_config)
        if not self.api_endpoint:
            self.api_endpoint = "https://api.anthropic.com/v1/messages"
        logger.info(f"Initializing AnthropicAI with endpoint: {self.api_endpoint}")

    def _build_tools_schema(self, context):
        """
        Builds Anthropic `tools` definitions from context.capabilities.

        Mirrors GeminiAI._build_tools_schema (Phase 2, docs/design/ai-agent-loop.md
        — native tool-calling for a non-gemini engine, same source data: system_tools
        + mcp_tools, same skip set, same dedupe-by-name so a tool declared both as a
        virtual system_tool and an AoT MCP tool doesn't get sent twice). Returns []
        when there are no capabilities (backward compat — no `tools` key sent, engine
        behaves exactly as before this change).
        """
        capabilities = context.get('capabilities', {})
        system_tools = capabilities.get('system_tools', [])
        mcp_tools = capabilities.get('mcp_tools', [])

        tools = []
        _skip = {'read_manual', 'get_detailed_manifest'}
        _seen = set()

        for tool in (system_tools + mcp_tools):
            name = tool.get('tool_name') or tool.get('action_type', '')
            if not name or name in _skip or name in _seen:
                continue
            _seen.add(name)
            tools.append({
                'name': name,
                'description': tool.get('description', ''),
                'input_schema': {
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

        return tools

    def run_reasoning(self, context, goal):
        """
        Executes reasoning via Anthropic Messages API, with native tool-calling
        (Phase 2, docs/design/ai-agent-loop.md) when `context.capabilities` carries
        a tool catalog — mirrors GeminiAI.run_reasoning's multi-turn tool-call loop.
        Falls back to plain text + JSON-in-text parsing when there are no tools
        (unchanged from before this change).
        """
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "anthropic-beta": "prompt-caching-2024-07-16",  # @ANCHOR: PROMPT_CACHE [2026-03-25]
            "content-type": "application/json"
        }

        prompt = self._build_prompt(context, goal)
        model = self.model_name or "claude-sonnet-5"

        # Multimodal: prepend any attached images as base64 content blocks, then
        # the text block. Falls back to a plain string when there are no images.
        user_content = prompt
        try:
            from aot.ai.ai_request_context import get_attachments
            _atts = get_attachments()
            if _atts:
                user_content = [
                    {"type": "image", "source": {"type": "base64",
                        "media_type": a["media_type"], "data": a["base64_data"]}}
                    for a in _atts
                ]
                user_content.append({"type": "text", "text": prompt})
                logger.info(f"[AnthropicAI] Attaching {len(_atts)} image(s) to request")
        except Exception as _att_err:
            logger.warning(f"[AnthropicAI] attachment build failed, sending text only: {_att_err}")
            user_content = prompt

        tools_schema = self._build_tools_schema(context)
        logger.info(f"[AnthropicAI] tools_schema count={len(tools_schema)}")

        messages = [{"role": "user", "content": user_content}]

        payload_base = {
            "model": model,
            "system": [
                {
                    "type": "text",
                    "text": self.system_prompt or "You are a helpful AI assistant.",
                    "cache_control": {"type": "ephemeral"}
                }
            ],
            "max_tokens": self.get_max_output_tokens(),
        }
        # Opus 4.7+/Sonnet 5+/Fable 5/Mythos 5 reject temperature/top_p/top_k with a 400.
        if not model.startswith(_NO_SAMPLING_PARAM_PREFIXES):
            payload_base["temperature"] = self.temperature or 0.7
        # Attach tools only when non-empty (backward compat: no tools key = plain text).
        if tools_schema:
            payload_base["tools"] = tools_schema

        max_fc_turns = 3
        fc_turn = 0
        while fc_turn < max_fc_turns:
            payload = dict(payload_base)
            payload["messages"] = messages

            logger.info(f"[AnthropicAI] POST {self.api_endpoint} model={payload['model']}")
            try:
                response = requests.post(
                    self.api_endpoint, json=payload, headers=headers, timeout=self.timeout
                )
                response.raise_for_status()
                data = response.json()
            except requests.exceptions.Timeout:
                logger.error(f"[AnthropicAI] API timeout ({self.timeout}s)")
                return {"insight": f"[AnthropicAI] API 호출 시간 초과 ({self.timeout}초)", "actions": []}
            except requests.exceptions.HTTPError as e:
                status_code = e.response.status_code if e.response is not None else "unknown"
                body = e.response.text[:300] if e.response is not None else ""
                logger.error(f"[AnthropicAI] HTTP {status_code}: {body}")
                return {"insight": f"[AnthropicAI] API 오류 (HTTP {status_code}): {body}", "actions": []}
            except requests.exceptions.ConnectionError:
                logger.error("[AnthropicAI] Connection failed")
                return {"insight": "[AnthropicAI] API 서버 연결 실패", "actions": []}
            except (KeyError, IndexError) as e:
                logger.error(f"[AnthropicAI] Unexpected response structure: {e}")
                return {"insight": "[AnthropicAI] 예상치 못한 응답 형식", "actions": []}

            content_blocks = data.get("content", []) or []
            tool_use_blocks = [b for b in content_blocks if b.get("type") == "tool_use"]

            if tool_use_blocks and fc_turn < max_fc_turns - 1:
                logger.info(f"[AnthropicAI] tool_use turn {fc_turn + 1}: "
                            f"{[b.get('name') for b in tool_use_blocks]}")

                def _to_action(block):
                    raw_args = block.get("input", {}) or {}
                    args_payload = raw_args.get('arguments') if isinstance(raw_args.get('arguments'), dict) else raw_args
                    return {'tool_name': block.get("name"), 'params': {'arguments': args_payload}}

                # @ANCHOR: ANTHROPIC_NATIVE_APPROVAL_GATE (agent-loop redesign,
                # docs/design/ai-agent-loop.md §5, same fix as GEMINI_NATIVE_APPROVAL_GATE
                # in gemini.py). Every OTHER engine only ever returns {insight, actions}
                # — it never executes anything itself, so the caller (AgentLoopService /
                # _dispatch_actions) always gets a chance to gate writes/physical actions
                # before they run. A native tool-calling loop here is the same kind of
                # exception gemini's was: left unchecked it would call execute_action()
                # directly for a mutating tool the moment the model picks it. Check ALL
                # tool_use blocks in this turn BEFORE executing any of them — if the model
                # asked for several tools in parallel and even one needs approval/is
                # ask_user, hand the whole batch back as proposed actions instead of
                # partially executing, so the approval gate is never bypassed by mixing a
                # gated tool alongside auto-executable ones in the same turn.
                from aot.ai.services.ai_action_service import AIActionService
                gated = [_to_action(b) for b in tool_use_blocks
                         if b.get("name") == 'ask_user' or AIActionService.requires_approval(b.get("name"))]
                if gated:
                    logger.info(f"[AnthropicAI] tool(s) {[g['tool_name'] for g in gated]} are "
                                f"control-flow/approval — returning as actions instead of auto-executing.")
                    return {"insight": "", "actions": gated}

                # All auto-executable — run each, feed every tool_use its own tool_result
                # (Anthropic requires one tool_result per tool_use in the same turn).
                from aot.ai.ai_routing_service import AIRoutingService
                messages.append({"role": "assistant", "content": content_blocks})
                tool_result_blocks = []
                for block in tool_use_blocks:
                    action = _to_action(block)
                    tool_name = action['tool_name']
                    logger.info(f"[AnthropicAI] executing tool={tool_name} "
                                f"args={str(action['params']['arguments'])[:200]}")
                    valid, _ = AIRoutingService._validate_and_normalize_action(action)
                    exec_result = None
                    if valid:
                        exec_result = AIActionService.execute_action(
                            action.get('action_type'), action.get('target_id'), action.get('params'))
                    tool_result_str = (json.dumps(exec_result, ensure_ascii=False, default=str)
                                        if exec_result else '{"error": "tool execution failed"}')
                    tool_result_blocks.append({
                        "type": "tool_result",
                        "tool_use_id": block.get("id"),
                        "content": tool_result_str
                    })
                messages.append({"role": "user", "content": tool_result_blocks})
                fc_turn += 1
                continue

            # No tool_use (or at the turn cap) → check for text.
            text = "".join(b.get("text", "") for b in content_blocks if b.get("type") == "text")
            if text:
                logger.debug(f"[AnthropicAI] Raw response: {text[:300]}")
                return self._safe_api_result(text, "AnthropicAI")

            if fc_turn >= max_fc_turns - 1:
                logger.info("[AnthropicAI] MAX_FC_TURNS reached, injecting final-answer prompt")
                messages.append({"role": "assistant", "content": content_blocks})
                messages.append({"role": "user", "content": [{
                    "type": "text",
                    "text": "You have reached the maximum number of tool-call turns. Provide "
                            "your final answer in a JSON object with 'insight' and 'actions' "
                            "fields based on the tool results above."
                }]})
                fc_turn += 1
                continue

        logger.warning("[AnthropicAI] No text response after all tool-call turns")
        return self._safe_api_result('{"insight": "No response from Anthropic after maximum tool-call turns.", "actions": []}', "AnthropicAI")

    def parse_actions(self, raw_response):
        return raw_response.get('actions', [])
