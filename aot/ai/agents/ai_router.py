# coding=utf-8
import logging
import json
from flask_babel import lazy_gettext as lg

from aot.ai.agents.base_ai import AbstractAI

logger = logging.getLogger(__name__)

AI_INFORMATION = {
    "engine_type": "ai_router",
    "ai_manufacturer": "AoT Core",
    "ai_name": "Intent Router",
    "ai_name_unique": "ai_router",
    "description": lg("Gatekeeper agent that classifies user intent into 5 categories (Control, Data Query, Schedule, Composite, Chat) for v6 pipeline routing."),
    "specialty": "intent classification, routing, disambiguation",
    "is_mcp": False,
    "default_endpoint": "",
    "auth_methods": ["no_auth"],
    "auth_link": "https://aot-inc.github.io/AoT/ai/overview/#agents",
    "system_prompt": (
        "You are the Router and Gatekeeper of the AoT (AI of Things) system.\n"
        "Your MISSION is to classify user intent into one of: CONTROL, DATA_QUERY, SCHEDULE, COMPOSITE, CHAT.\n\n"
        "RULES:\n"
        "1. Never answer the user command directly.\n"
        "2. Only output strict JSON with 'intent', 'confidence', 'insight', and 'actions'.\n"
        "3. If in doubt, default to DATA_QUERY to ensure tool usage."
    ),
    "models": [
        {"label": "Intent Router (Virtual)", "value": "intent_router"}
    ],
    "custom_options": [
        {"id": "reasoning_entry_id", "name": "Reasoning Brain (AI Service)", "type": "select", "choices": [], "default": ""},
        {"id": "llm_model", "name": "Specific Model (Optional)", "type": "text", "default": ""},
    ]
}

class AIRouterAI(AbstractAI):
    """
    AIRouterAI: The Gatekeeper.
    Classifies user intent before any orchestration happens.

    @phase active
    @stability stable
    @dependency Tier0Classifier, BrainResolver, AIAgentService
    """

    def __init__(self, agent_config):
        super().__init__(agent_config)

        try:
            options = json.loads(agent_config.custom_options_json) if agent_config.custom_options_json else {}
        except Exception:
            options = {}

        self.reasoning_entry_id = options.get('reasoning_entry_id', '')
        self.llm_model = options.get('llm_model', '')
        self._brain = self._init_brain(agent_config)

        if self._brain:
            # Dynamically override the brain's prompt builder to use OUR minimalist version.
            # This ensures that when self._brain.run_reasoning() is called, 
            # it uses our gatekeeper instructions instead of the system-wide action instructions.
            import types
            self._brain._build_prompt = types.MethodType(self.__class__._build_prompt, self._brain)

    def _init_brain(self, agent_config):
        from aot.ai.services.brain_resolver import BrainResolver
        brain_ctx = BrainResolver.resolve(
            skeleton_id=agent_config.unique_id,
            preferred_entry_id=self.reasoning_entry_id
        )
        if not brain_ctx:
            return None
        engine = brain_ctx.engine_instance
        if self.llm_model:
            engine.model_name = self.llm_model
        return engine

    def _build_gatekeeper_prompt(self):
        return (
            "### [Role: Intent Router v6.2 (Minimalist)] ###\n"
            "Classify user input into: [INTENT]:[COMPLEXITY]\n"
            "INTENT: CONTROL, DATA_QUERY, SCHEDULE, COMPOSITE, CHAT\n"
            "COMPLEXITY: SIMPLE, COMPLEX\n\n"
            "Decision Rules:\n"
            "- CONTROL: Physical device commands (valves, pumps).\n"
            "- DATA_QUERY: Sensor status/history, weather info, soil info, or status requests.\n"
            "- SCHEDULE: Task planning/human work.\n"
            "- COMPOSITE: Mixed (query + action).\n"
            "- CHAT: General knowledge without tools (e.g. 'hello', 'what is AoT').\n\n"
            "SPECIAL RULES:\n"
            "1. If a specific 'Plot' (포장/1포장/2포장 등), 'Zone', or 'Device' is mentioned with 'Weather' (기상/날씨) -> DATA_QUERY.\n"
            "2. If in doubt, default to DATA_QUERY.\n\n"
            "RULES:\n"
            "1. Response MUST be ONLY the code (e.g., DATA_QUERY:SIMPLE).\n"
            "2. NO JSON, NO explanation, NO chatter."
        )

    def _build_prompt(self, context, goal):
        """
        Override AbstractAI._build_prompt to provide a minimalist, 
        router-specific prompt without the base system's action noise.
        """
        router_instruction = self._build_gatekeeper_prompt()
        return (
            f"{router_instruction}\n"
            f"USER_COMMAND: {goal}\n\n"
            "Respond ONLY with the JSON defined above."
        )

    def run_reasoning(self, context, goal):
        if not self._brain:
            return {"intent": "DATA_QUERY", "confidence": 0.0, "requires_tools": True, "insight": "Router brain not initialized.", "actions": []}
        
        # Save original brain state
        original_builder = self._brain._build_prompt
        original_system = self._brain.system_prompt
        
        try:
            # 1. Force the brain to ONLY use our minimalist prompt for the human message
            self._brain._build_prompt = lambda ctx, g: g
            
            # 2. Clear the system instructions to avoid conflict with the assistant role
            self._brain.system_prompt = ""
            
            # 3. Construct the classification request containing EVERYTHING
            from aot.ai.services.ai_agent_service import _RATE_LIMITER
            _RATE_LIMITER.acquire()
            
            router_instruction = self._build_gatekeeper_prompt()
            full_prompt = (
                f"{router_instruction}\n\n"
                f"### [USER REQUEST TO CLASSIFY] ###\n"
                f"'{goal}'\n\n"
                f"CRITICAL: You are an Intent Classifier. Do NOT try to fulfill the request. "
                f"ONLY respond with the JSON object containing 'intent', 'insight', 'actions': [], and 'suggested_actions'."
            )
            
            logger.info(f"[AIRouter] Requesting classification...")
            raw_result = self._brain.run_reasoning({}, full_prompt)
        finally:
            # Always restore the original builder and system prompt
            self._brain._build_prompt = original_builder
            self._brain.system_prompt = original_system
        
        logger.info(f"[AIRouter] Raw result from brain: {raw_result}")

        # Priority 1: Direct JSON in the result dict
        if 'intent' in raw_result:
            logger.info(f"[AIRouter] Classified '{goal}' as {raw_result['intent']} (Direct)")
            return raw_result
            
        # Priority 2: Extracted from insight string
        insight = raw_result.get('insight', '')
        parsed = self._brain._extract_json_from_text(insight)
        if not parsed:
            # Priority 3: Extracted from raw text representation
            parsed = self._brain._extract_json_from_text(str(raw_result))
            
        if parsed and 'intent' in parsed:
            logger.info(f"[AIRouter] Classified '{goal}' as {parsed['intent']} (Extracted JSON)")
            return parsed
            
        # Priority 4: Direct Code Parsing (e.g. DATA_QUERY:SIMPLE)
        text_result = str(raw_result).strip().upper()
        if ':' in text_result:
            parts = text_result.split(':')
            intent = parts[0].strip()
            complexity = parts[1].strip() if len(parts) > 1 else 'SIMPLE'
            
            # Simple validation
            valid_intents = ['CONTROL', 'DATA_QUERY', 'SCHEDULE', 'COMPOSITE', 'CHAT']
            if intent in valid_intents:
                logger.info(f"[AIRouter] Classified '{goal}' as {intent}:{complexity} (Direct Code)")
                return {
                    "intent": intent,
                    "complexity": complexity,
                    "confidence": 1.0,
                    "requires_tools": intent != 'CHAT',
                    "insight": f"Classified as {intent} via minimalist router.",
                    "actions": []
                }
            
        # v6: Fallback to DATA_QUERY instead of C_AMBIGUOUS (Force Tool Policy)
        logger.warning(f"[AIRouter] Failed to parse classification for '{goal}'. Returning DATA_QUERY (Force Tool Policy).")
        return {
            "intent": "DATA_QUERY",
            "confidence": 0.0,
            "sub_intents": [],
            "requires_tools": True,
            "insight": insight if insight else "의도를 분류하지 못했습니다.",
            "actions": []
        }

    def parse_actions(self, raw_response):
        return []
