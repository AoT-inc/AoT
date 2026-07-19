# coding=utf-8
import logging
from aot.ai.agents.base_ai import AbstractAI
from flask_babel import lazy_gettext as lg

logger = logging.getLogger(__name__)

AI_INFORMATION = {
    'ai_name_unique': 'openai',
    'ai_manufacturer': 'OpenAI',
    'ai_name': 'OpenAI (GPT)',
    'ai_type': 'LLM',
    'auth_methods': ['api_key'],
    'auth_link': 'https://platform.openai.com/api-keys',
    'default_endpoint': 'https://api.openai.com/v1',
    'endpoint_hint': 'Official OpenAI API',
    'models': [
        {'value': 'gpt-5.5', 'label': 'GPT-5.5 (Flagship)'},
        {'value': 'gpt-5.4', 'label': 'GPT-5.4'},
        {'value': 'gpt-5.4-mini', 'label': 'GPT-5.4 Mini'},
        {'value': 'gpt-5.4-nano', 'label': 'GPT-5.4 Nano (Fastest/Cheapest)'},
    ],
    'description': lg("OpenAI's widely recognized GPT engine, featuring powerful logical reasoning and creative writing capabilities."),
    'url_manufacturer': 'https://openai.com/',
    'custom_options': [
        {'id': 'temperature', 'type': 'float', 'default': 0.7, 'name': 'Temperature (0.0 - 2.0)'},
        {'id': 'max_tokens', 'type': 'int', 'default': 2048, 'name': 'Max Output Tokens'}
    ]
}

class OpenAI_AI(AbstractAI):
    """
    OpenAI (GPT) AI Engine Implementation.
    Uses the OpenAI Chat Completions API for GPT-based reasoning.

    @phase active
    @stability stable
    @dependency AbstractAI, BrainResolver
    """
    MCP_SPECIALTY = "General Purpose Assistant (GPT Reasoning)"
    
    def __init__(self, agent_config):
        super().__init__(agent_config)
        if not self.api_endpoint:
            self.api_endpoint = "https://api.openai.com/v1"
        logger.info(f"Initializing OpenAI_AI with endpoint: {self.api_endpoint}")

    def run_reasoning(self, context, goal):
        return self._call_openai_compatible_api(context, goal)

    def parse_actions(self, raw_response):
        return raw_response.get('actions', [])
