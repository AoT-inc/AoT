# coding=utf-8
import logging
from aot.ai.agents.base_ai import AbstractAI
from flask_babel import lazy_gettext as lg

logger = logging.getLogger(__name__)

AI_INFORMATION = {
    'ai_name_unique': 'groq',
    'ai_manufacturer': 'Groq',
    'ai_name': 'Groq (Fast LPU)',
    'ai_type': 'LLM',
    'auth_methods': ['api_key'],
    'auth_link': 'https://console.groq.com/keys',
    'default_endpoint': 'https://api.groq.com/openai/v1',
    'endpoint_hint': 'Ultra-fast Groq API',
    'models': [
        {'value': 'openai/gpt-oss-120b', 'label': 'GPT-OSS 120B (Best quality)'},
        {'value': 'llama-3.3-70b-versatile', 'label': 'Llama 3.3 70B'},
        {'value': 'openai/gpt-oss-20b', 'label': 'GPT-OSS 20B (Fast)'},
        {'value': 'llama-3.1-8b-instant', 'label': 'Llama 3.1 8B Instant'},
        {'value': 'groq/compound', 'label': 'Groq Compound (Agentic, built-in tools)'},
    ],
    # gemma2-9b-it (retired 2025-10-08) and mixtral-8x7b-32768 (retired
    # 2025-03-20) were removed — see console.groq.com/docs/deprecations.
    'description': lg("Provides extremely fast inference speeds using Groq's LPU (Language Processing Unit) technology, supporting models like Llama 3.3 and GPT-OSS."),
    'url_manufacturer': 'https://groq.com/',
    'custom_options': [
        {'id': 'temperature', 'type': 'float', 'default': 0.7, 'name': 'Temperature (0.0 - 2.0)'},
        {'id': 'max_tokens', 'type': 'int', 'default': 2048, 'name': 'Max Output Tokens'}
    ]
}

class Groq_AI(AbstractAI):
    """
    Groq AI Engine Implementation (High-speed Llama/GPT-OSS).
    Uses the Groq OpenAI-compatible API for fast inference.

    @phase active
    @stability stable
    @dependency AbstractAI, BrainResolver
    """
    MCP_SPECIALTY = "High-speed Inference (Llama 3.3 / GPT-OSS)"
    
    def __init__(self, agent_config):
        super().__init__(agent_config)
        if not self.api_endpoint:
            self.api_endpoint = "https://api.groq.com/openai/v1"
        logger.info(f"Initializing Groq_AI with endpoint: {self.api_endpoint}")

    def get_context_budget(self):
        """
        Groq specific character budgets.
        Free Tier (lightweight) has 6,000 TPM (~20-24k chars).
        """
        budgets = {
            'lightweight': 20000,    # Strictly within 6000 TPM
            'standard': 100000,      # ~25k tokens
            'heavy': 300000          # ~75k tokens
        }
        return budgets.get(self.model_tier, 100000)

    def get_max_output_tokens(self):
        """
        Groq specific output tokens.
        Keep it low for lightweight to avoid TPM issues.
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
