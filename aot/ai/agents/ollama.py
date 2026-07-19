# coding=utf-8
import logging
from aot.ai.agents.base_ai import AbstractAI
from flask_babel import lazy_gettext as lg

logger = logging.getLogger(__name__)

AI_INFORMATION = {
    'ai_name_unique': 'ollama',
    'ai_manufacturer': 'Ollama',
    'ai_name': 'Ollama (Local)',
    'ai_type': 'LLM',
    'auth_methods': ['no_auth', 'api_key'],
    'default_endpoint': 'http://localhost:11434/v1',
    'endpoint_hint': 'Local Ollama (OpenAI mode)',
    'models': [
        {'value': 'llama3.3', 'label': 'Llama 3.3 70B'},
        {'value': 'llama4', 'label': 'Llama 4'},
        {'value': 'qwen3', 'label': 'Qwen 3'},
        {'value': 'gemma3', 'label': 'Gemma 3'},
        {'value': 'deepseek-r1', 'label': 'DeepSeek R1 (Reasoning)'},
        {'value': 'phi4', 'label': 'Phi-4'},
        {'value': 'mistral', 'label': 'Mistral 7B'},
    ],
    'description': lg("An open-source LLM engine that runs on the user's local PC, ensuring privacy and functioning without an internet connection."),
    'auth_link': 'https://ollama.com/',
    'url_manufacturer': 'https://ollama.com/',
    'custom_options': [
        {'id': 'temperature', 'type': 'float', 'default': 0.7, 'name': 'Temperature (0.0 - 1.0)'},
        {'id': 'max_tokens', 'type': 'int', 'default': 2048, 'name': 'Max Output Tokens'}
    ]
}

class Ollama_AI(AbstractAI):
    """
    Ollama AI Engine Implementation (Local).
    Uses the Ollama OpenAI-compatible API for private/offline reasoning.

    @phase active
    @stability unstable
    @dependency AbstractAI, BrainResolver
    """
    MCP_SPECIALTY = "Local PC Assistant (Private/Offline)"
    
    def __init__(self, agent_config):
        super().__init__(agent_config)
        if not self.api_endpoint:
            self.api_endpoint = "http://localhost:11434/v1"
        logger.info(f"Initializing Ollama_AI with endpoint: {self.api_endpoint}")

    def run_reasoning(self, context, goal):
        return self._call_openai_compatible_api(context, goal)

    def parse_actions(self, raw_response):
        return raw_response.get('actions', [])
