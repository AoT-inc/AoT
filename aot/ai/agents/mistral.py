# coding=utf-8
import logging
from aot.ai.agents.base_ai import AbstractAI
from flask_babel import lazy_gettext as lg

logger = logging.getLogger(__name__)

AI_INFORMATION = {
    'ai_name_unique': 'mistral',
    'ai_manufacturer': 'Mistral AI',
    'ai_name': 'Mistral AI (Large)',
    'ai_type': 'LLM',
    'auth_methods': ['api_key'],
    'auth_link': 'https://console.mistral.ai/api-keys/',
    'default_endpoint': 'https://api.mistral.ai/v1',
    'endpoint_hint': 'Official Mistral AI API',
    'models': [
        {'value': 'mistral-large-latest', 'label': 'Mistral Large'},
        {'value': 'mistral-medium-latest', 'label': 'Mistral Medium'},
        {'value': 'mistral-small-latest', 'label': 'Mistral Small'},
        {'value': 'codestral-latest', 'label': 'Codestral'},
        {'value': 'open-mistral-nemo', 'label': 'Mistral Nemo'},
    ],
    'description': lg("Mistral engine, a powerful open/closed-source model developed in Europe, boasting multilingual capabilities and exceptional efficiency."),
    'url_manufacturer': 'https://mistral.ai/',
    'custom_options': [
        {'id': 'temperature', 'type': 'float', 'default': 0.7, 'name': 'Temperature (0.0 - 1.0)'},
        {'id': 'max_tokens', 'type': 'int', 'default': 2048, 'name': 'Max Output Tokens'}
    ]
}

class Mistral_AI(AbstractAI):
    """
    Mistral AI Engine Implementation.
    Uses the Mistral OpenAI-compatible API for multilingual reasoning.

    @phase active
    @stability stable
    @dependency AbstractAI, BrainResolver
    """
    MCP_SPECIALTY = "General Purpose Assistant (Mistral Efficiency)"
    
    def __init__(self, agent_config):
        super().__init__(agent_config)
        if not self.api_endpoint:
            self.api_endpoint = "https://api.mistral.ai/v1"
        logger.info(f"Initializing Mistral_AI with endpoint: {self.api_endpoint}")

    def run_reasoning(self, context, goal):
        return self._call_openai_compatible_api(context, goal)

    def parse_actions(self, raw_response):
        return raw_response.get('actions', [])
