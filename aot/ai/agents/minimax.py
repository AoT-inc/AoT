# coding=utf-8
import logging
from aot.ai.agents.base_ai import AbstractAI
from flask_babel import lazy_gettext as lg

logger = logging.getLogger(__name__)

AI_INFORMATION = {
    'ai_name_unique': 'minimax',
    'ai_manufacturer': 'MiniMax',
    'ai_name': 'MiniMax (M2 Series)',
    'ai_type': 'LLM',
    'auth_methods': ['api_key'],
    'auth_link': 'https://platform.minimax.io/user-center/basic-information/interface-key',
    'default_endpoint': 'https://api.minimax.io/v1',
    'endpoint_hint': 'Official MiniMax API (OpenAI-compatible)',
    'models': [
        {'value': 'MiniMax-M2.7', 'label': 'MiniMax-M2.7 (Latest, Mar 2026)'},
        {'value': 'MiniMax-M2.7-highspeed', 'label': 'MiniMax-M2.7 High Speed'},
        {'value': 'MiniMax-M2.5', 'label': 'MiniMax-M2.5 (SOTA Coding/Agentic)'},
        {'value': 'MiniMax-M2.5-highspeed', 'label': 'MiniMax-M2.5 High Speed'},
        {'value': 'MiniMax-M2.1', 'label': 'MiniMax-M2.1 (Polyglot Coding)'},
        {'value': 'MiniMax-M2', 'label': 'MiniMax-M2 (Agentic, Oct 2025)'},
        {'value': 'MiniMax-Text-01', 'label': 'MiniMax-Text-01 (200K ctx, Legacy)'},
    ],
    'description': lg("MiniMax M2 series MoE models — optimized for coding, agentic workflows, and multilingual tasks. OpenAI-compatible API."),
    'url_manufacturer': 'https://www.minimax.io/',
    'custom_options': [
        {'id': 'temperature', 'type': 'float', 'default': 0.7, 'name': 'Temperature (0.0 - 2.0)'},
        {'id': 'max_tokens', 'type': 'int', 'default': 2048, 'name': 'Max Output Tokens'}
    ]
}


class MiniMax_AI(AbstractAI):
    """
    MiniMax AI Engine Implementation (MoE/GLM models).
    Uses the MiniMax Chat Completions API (OpenAI-compatible).

    @phase active
    @stability stable
    @dependency AbstractAI
    """
    MCP_SPECIALTY = "High-quality Conversational AI (MoE/GLM)"

    def __init__(self, agent_config):
        super().__init__(agent_config)
        self.api_endpoint = "https://api.minimax.io/v1"
        logger.info(f"Initializing MiniMax_AI with endpoint: {self.api_endpoint}")

    def get_context_budget(self):
        """
        MiniMax specific character budgets.
        MiniMax-Text-01 supports up to 200K context.
        """
        budgets = {
            'lightweight': 50000,     # ~12.5k tokens
            'standard': 200000,       # ~50k tokens
            'heavy': 500000           # ~125k tokens (within 200K ctx)
        }
        return budgets.get(self.model_tier, 200000)

    def get_max_output_tokens(self):
        """
        MiniMax specific output tokens.
        """
        budgets = {
            'lightweight': 512,
            'standard': 2048,
            'heavy': 4096
        }
        db_val = getattr(self.agent_config, 'max_tokens', 0)
        return db_val if db_val > 0 else budgets.get(self.model_tier, 2048)

    def run_reasoning(self, context, goal):
        return self._call_openai_compatible_api(context, goal)

    def parse_actions(self, raw_response):
        return raw_response.get('actions', [])