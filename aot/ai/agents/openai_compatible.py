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

    def run_reasoning(self, context, goal):
        return self._call_openai_compatible_api(context, goal)

    def parse_actions(self, raw_response):
        return raw_response.get('actions', [])
