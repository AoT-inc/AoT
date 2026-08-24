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

    def get_context_budget(self):
        """Ollama 는 **모델의 창이 아니라 `num_ctx` 가 실제 상한**이다.

        base_ai 기본값(standard 300,000자 ≈ 75k 토큰)을 그대로 쓰면 안 되는
        유일한 부류다. 서버 기본 `num_ctx` 는 모델이 128k 창을 광고하더라도
        보통 4k~8k 토큰이고, 그 값은 Modelfile 이나 요청 옵션으로만 올라간다.
        게다가 AoT 는 라즈베리 파이 같은 저사양에서도 도는데(HARDWARE_PROFILE),
        로컬 모델의 컨텍스트는 VRAM/RAM 을 그대로 먹는다.

        **넘기면 조용히 더 나빠진다**: Ollama 는 창을 넘는 입력을 서버에서
        **앞에서부터** 잘라낸다. 우리 쪽 절단은 꼬리를 자르지만(목표·지시가
        앞에 있으므로 최소한 요청은 남는다), 서버 절단은 그 앞부분을 먼저
        버린다 — 즉 우리가 안 자르고 넘기는 쪽이 더 나쁘다.

        그래서 여기서는 **일부러 낮게 잡는다.** 다만 아무 값이나 낮출 수는 없다:
        실측(2026-08-24) AoT 의 고정 프롬프트 **바닥이 17,645자**다(컨텍스트를
        완전히 비워도 남는 머리말·지시·목표 2회·응답형식 꼬리). 그보다 작은
        예산은 컨텍스트가 아니라 **지시부터** 자르게 되므로 의미가 없다.

        값은 흔한 num_ctx 설정에 맞춘다(문자수 ≈ 토큰 × 4):
          lightweight  20,000 — 바닥 바로 위. 지시는 지키고 컨텍스트는 거의 없다
          standard     32,000 ≈  8k 토큰 — num_ctx 8192 를 쓰는 보통 설정
          heavy       120,000 ≈ 30k 토큰 — num_ctx 32768 로 올린 장비

        **num_ctx 가 기본값(4096)인 채로는 이 프롬프트가 들어가지 않는다.**
        그 경우 Ollama 가 앞에서부터 잘라 목표까지 버리므로, 운영자는 Modelfile
        이나 요청 옵션으로 num_ctx 를 올려야 한다. 등급을 올리는 것이 "내 장비는
        더 받는다" 를 표현하는 자리다 — 여기 숫자를 올리는 것이 아니라.
        """
        budgets = {
            'lightweight': 20000,
            'standard': 32000,
            'heavy': 120000,
        }
        return budgets.get(self.model_tier, 32000)

    def run_reasoning(self, context, goal):
        return self._call_openai_compatible_api(context, goal)

    def parse_actions(self, raw_response):
        return raw_response.get('actions', [])
