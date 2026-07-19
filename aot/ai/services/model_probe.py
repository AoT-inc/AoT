# coding=utf-8
"""
ModelProbe — conformance probe for AIEntry connections (v3.1 tier architecture).

Reuses the production run_reasoning()/actions contract instead of a parallel
probing protocol, so a passing probe reflects what real traffic will actually
get. See .local/reports/ai_architecture_v3_tier_proposal.md §13-2-C.

@phase active
@stability new
@dependency AIEntry, ENGINE_REGISTRY (ai_agent_service)
"""
import json
import logging
import time
from datetime import datetime

logger = logging.getLogger(__name__)

_KNOWN_ERROR_PREFIXES = (
    '[', '(', 'API', 'Error', 'error',
)

_PROBE_GOAL = (
    "This is a conformance probe, not a real task. "
    "Respond with exactly one action of action_type 'noop' and set insight to 'probe_ok'."
)
_PROBE_CONTEXT = "conformance probe — no real device or data context."


class _ProbeAgentShim:
    """Duck-typed stand-in for AIAgent — lets a bare AIEntry (connection,
    no persona yet) be probed through the same engine classes production
    agents use. Not persisted; exists only for the duration of one probe call.
    """
    def __init__(self, entry):
        self.unique_id = f"probe-{entry.unique_id}"
        self.name = f"probe:{entry.name}"
        self.entry = entry
        self.system_prompt = "You are a conformance probe target. Follow instructions exactly."
        self.temperature = 0.0
        self.model_tier = 'lightweight'
        self.max_tokens = 256
        self.pipeline_role = None
        # Some engines read these directly off agent_config as a fallback
        # before consulting .entry (see base_ai.AbstractAI.__init__).
        self.api_endpoint = None
        self.auth_type = None
        self.auth_id = None
        self.api_key = None
        self.model_type = None
        self.model_name = None


def probe_entry(entry_id):
    """Run a conformance probe against one AIEntry and persist the result.

    Never raises — probe failures are recorded in the result, not thrown,
    so this is safe to call from setup/onboarding flows.

    Returns the capabilities dict that was written to AIEntry.capabilities_json.
    """
    from aot.databases.models.ai import AIEntry
    from aot.aot_flask.extensions import db
    from aot.ai.services.ai_agent_service import ENGINE_REGISTRY, initialize_engine_registry

    initialize_engine_registry()

    entry = AIEntry.query.filter_by(unique_id=entry_id).first()
    if not entry:
        return {'ok': False, 'error': 'entry_not_found'}

    result = {
        'ok': False,
        'tool_use': False,        # AoT equivalent: engine returned a well-formed action
        'structured_output': False,  # parse succeeded (insight+actions present, no exception)
        'streaming': False,        # not probed yet — most AoT engines are non-streaming today
        'latency_ms': None,
        'error': None,
    }

    registry_entry = ENGINE_REGISTRY.get(entry.model_type)
    if not registry_entry:
        result['error'] = f'no_engine_for_model_type:{entry.model_type}'
        _save_probe_result(entry, result)
        return result

    engine_class, _module = registry_entry
    shim = _ProbeAgentShim(entry)

    start = time.monotonic()
    try:
        engine = engine_class(shim)
        response = engine.run_reasoning(context=_PROBE_CONTEXT, goal=_PROBE_GOAL)
        result['latency_ms'] = int((time.monotonic() - start) * 1000)

        insight = (response or {}).get('insight', '') or ''
        actions = (response or {}).get('actions', []) or []

        looks_like_error = insight.strip().startswith(_KNOWN_ERROR_PREFIXES)
        result['structured_output'] = isinstance(response, dict) and 'insight' in response and 'actions' in response
        result['tool_use'] = bool(actions) and not looks_like_error
        result['ok'] = result['structured_output'] and not looks_like_error
        if looks_like_error:
            result['error'] = insight[:200]
    except Exception as e:
        result['latency_ms'] = int((time.monotonic() - start) * 1000)
        result['error'] = f'{type(e).__name__}: {e}'[:200]
        logger.warning(f"[ModelProbe] Probe failed for entry {entry.name}: {e}")

    _save_probe_result(entry, result)
    return result


def _save_probe_result(entry, result):
    from aot.aot_flask.extensions import db
    entry.capabilities_json = json.dumps(result)
    entry.capabilities_probed_at = datetime.utcnow()
    db.session.add(entry)
    db.session.commit()


def get_capabilities(entry):
    """Read back the last-probed capabilities dict for an AIEntry (or {} if never probed)."""
    try:
        return json.loads(entry.capabilities_json or '{}')
    except (ValueError, TypeError):
        return {}
