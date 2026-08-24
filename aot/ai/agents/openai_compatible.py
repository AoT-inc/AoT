# coding=utf-8
"""
Generic OpenAI-compatible engine — v3.1 tier architecture protocol driver.

groq.py, mistral.py, minimax.py, openai.py, and ollama.py already share one
HTTP caller (AbstractAI._call_openai_compatible_api) — there is no duplicate
request logic to consolidate. What was still missing: adding any OTHER
OpenAI-wire-compatible provider (vLLM, LM Studio, Together AI, Perplexity, a
self-hosted endpoint, a brand-new provider that launches tomorrow) required
writing a new agents/*.py file first. This engine removes that requirement —
it takes endpoint/model/auth purely from the linked AIEntry, so a new
provider of this kind is just a new AIEntry row, no code.

See .local/reports/ai_architecture_v3_tier_proposal.md §13-2-B.

@phase active
@stability new
@dependency AbstractAI._call_openai_compatible_api
"""
import logging
from aot.ai.agents.base_ai import AbstractAI
from flask_babel import lazy_gettext as lg

logger = logging.getLogger(__name__)

AI_INFORMATION = {
    'ai_name_unique': 'openai_compatible',
    'ai_manufacturer': 'Generic',
    'ai_name': 'OpenAI-Compatible (Custom Endpoint)',
    'ai_type': 'LLM',
    'auth_methods': ['api_key', 'no_auth'],
    'auth_link': '',
    'default_endpoint': '',
    'endpoint_hint': (
        'Any OpenAI Chat Completions-compatible endpoint '
        '(vLLM, LM Studio, Together AI, Perplexity, self-hosted, etc.). '
        'Enter the endpoint and model name manually — there is no curated model list.'
    ),
    # Deliberately empty — this engine is provider-agnostic. The model name
    # is whatever the target endpoint expects, entered directly on the AIEntry.
    'models': [],
    'description': lg(
        "A generic driver for any provider that speaks the OpenAI Chat "
        "Completions wire format but does not have a dedicated engine here yet. "
        "Use this to connect a new provider without writing code."
    ),
    'url_manufacturer': '',
    'custom_options': [
        {'id': 'temperature', 'type': 'float', 'default': 0.7, 'name': 'Temperature (0.0 - 2.0)'},
        {'id': 'max_tokens', 'type': 'int', 'default': 2048, 'name': 'Max Output Tokens'},
    ],
}


class OpenAICompatibleAI(AbstractAI):
    """
    Provider-agnostic engine for any OpenAI Chat Completions-wire-compatible
    endpoint not covered by a dedicated agents/*.py file.

    Select it by setting AIEntry.model_type='openai_compatible' (or, once a
    given AIEntry already has an unrelated model_type, AIEntry.protocol=
    'openai_compatible' — get_engine() checks protocol before model_type).
    Both api_endpoint and model_name must be set explicitly on the AIEntry;
    there is no default endpoint or curated model list to fall back to.

    @phase active
    @stability new
    @dependency AbstractAI, BrainResolver
    """
    MCP_SPECIALTY = "Generic OpenAI-compatible endpoint"

    def __init__(self, agent_config):
        super().__init__(agent_config)
        if not self.api_endpoint:
            raise ValueError(
                f"AI Agent '{self.name}' uses the openai_compatible engine but its "
                "linked Entry has no api_endpoint set. This engine has no default "
                "endpoint — set one explicitly on the AIEntry."
            )
        logger.info(f"Initializing OpenAICompatibleAI with endpoint: {self.api_endpoint}, model: {self.model_name}")

    def get_context_budget(self):
        """이 드라이버는 **어느 엔드포인트를 가리키는지 알 수 없다.**

        vLLM·LM Studio·Together·Perplexity·자체 호스팅 — 창이 8k 토큰인 것도
        1M 인 것도 같은 이 클래스로 들어온다. 모델 이름조차 큐레이트하지 않는
        드라이버가 base_ai 의 낙관적 기본값(300,000자 ≈ 75k 토큰)을 쓰면,
        작은 엔드포인트에서 프롬프트 꼬리(시스템 지시·재진술 목표)가 조용히
        잘린다.

        그래서 **보수적으로 잡는다** — 100,000자 ≈ 25k 토큰은 요즘 거의 모든
        엔드포인트(32k 창 vLLM 포함)가 받는 값이다. 큰 엔드포인트를 붙인
        운영자는 등급을 heavy 로 올려 그 사실을 표현하면 된다. 모르는 쪽으로
        기울일 때는 **큰 값을 가정해 조용히 잘리는 것보다, 작은 값을 써서
        덜 싣는 쪽**이 낫다.
        """
        budgets = {
            'lightweight': 20000,
            'standard': 100000,
            'heavy': 400000,
        }
        return budgets.get(self.model_tier, 100000)

    def run_reasoning(self, context, goal):
        return self._call_openai_compatible_api(context, goal)

    def parse_actions(self, raw_response):
        return raw_response.get('actions', [])
