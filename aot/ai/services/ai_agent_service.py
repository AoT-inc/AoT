# coding=utf-8
import logging
import json
import re
import time
import uuid as _uuid_module
from aot.databases.models import db
from datetime import datetime, timedelta
from aot.utils.time_utils import get_local_now, utc_now
import importlib
import os
import inspect
from aot.ai.services.ai_context_service import AIContextService
from aot.ai.services.ai_action_service import AIActionService
from aot.ai.services.ai_scheduler_service import AISchedulerService
from aot.ai.services.safety_service import SafetyService, SafetyViolation
from aot.ai.services.ai_learning_service import AILearningService
from flask_login import current_user
from collections import OrderedDict, deque
import threading
from aot.databases.models.ai import AIAgent
from aot.databases.models.ai_task import AITask

logger = logging.getLogger(__name__)


def _log_path_metrics(path, start_time, intercept=None, ok=True, approved=None):
    """Structured per-path log line for Phase 0b instrumentation (AI
    architecture improvement plan §0b). One line per top-level dispatch
    decision inside process_natural_language_command, so path/latency can be
    grepped and aggregated without a metrics backend. Purely additive
    logging — no behavior change."""
    latency_ms = int((time.monotonic() - start_time) * 1000)
    logger.info(f"[PathMetrics] path={path} intercept={intercept} ok={ok} "
                f"approved={approved} latency_ms={latency_ms}")

# Actions that can be executed immediately without human approval (Safe/Informational/Read-only)
IMMEDIATE_ACTIONS = ['read_manual', 'knowledge_search', 'get_detailed_manifest', 'mcp_tool_call', 'virtual_tool_call', 'mcp_resource_read', 'mcp_prompt_get']

# Engine registry: model_type -> (engine_class, module)
# Populated dynamically on first access
ENGINE_REGISTRY = {}
REGISTRY_INITIALIZED = False


class ThreadSafeLRUCache:
    """
    스레드 안전 LRU 캐시
    OrderedDict 사용으로 O(1) 성능 보장
    """
    def __init__(self, max_size=100):
        self.cache = OrderedDict()
        self.max_size = max_size
        self.lock = threading.Lock()
        self.hits = 0
        self.misses = 0

    def get(self, key, default=None):
        with self.lock:
            if key not in self.cache:
                self.misses += 1
                return default
            # LRU: 접근 시 맨 뒤로 이동
            self.cache.move_to_end(key)
            self.hits += 1
            return self.cache[key]

    def __setitem__(self, key, value):
        with self.lock:
            if key in self.cache:
                self.cache.move_to_end(key)
            self.cache[key] = value
            # 크기 초과 시 가장 오래된 것 제거
            if len(self.cache) > self.max_size:
                oldest = self.cache.popitem(last=False)
                logger.debug(f"[SemanticCache] Evicted oldest: {oldest[0][:50]}...")

    def __contains__(self, key):
        with self.lock:
            return key in self.cache

    def __len__(self):
        with self.lock:
            return len(self.cache)

    def delete(self, key):
        """Remove a specific entry from the cache."""
        with self.lock:
            return self.cache.pop(key, None) is not None

    def clear(self):
        """Flush all entries from the cache."""
        with self.lock:
            self.cache.clear()
            self.hits = 0
            self.misses = 0

    def stats(self):
        """캐시 통계"""
        with self.lock:
            total = self.hits + self.misses
            hit_rate = (self.hits / total * 100) if total > 0 else 0
            return {
                'size': len(self.cache),
                'max_size': self.max_size,
                'hits': self.hits,
                'misses': self.misses,
                'hit_rate': f"{hit_rate:.1f}%"
            }


def truncate_message_smart(content, max_length=3000):
    """
    스마트 truncation
    - 줄바꿈 단위로 자르기
    - JSON 보호
    - 멀티바이트 문자 안전
    """
    if len(content) <= max_length:
        return content

    # JSON 감지 및 보호
    stripped = content.strip()
    if stripped.startswith(('{', '[')):
        if len(content) > 5000:
            return content[:5000] + "\n... [JSON truncated]"
        return content

    # 줄바꿈 단위로 자르기
    cut_pos = content.rfind('\n', 0, max_length)

    # 너무 앞에서 잘리면 (70% 이하) 그냥 max_length 사용
    if cut_pos < max_length * 0.7:
        cut_pos = max_length

    return content[:cut_pos] + "\n... [truncated]"


# RAG 로그 제한 설정
MAX_RAG_LOGS = 20
TOOL_LOG_LIMITS = {
    'mcp_tool_call': 10000,
    'virtual_tool_call': 10000,
    'read_manual': 8000,
    'get_detailed_manifest': 8000,
    'mcp_resource_read': 5000,
    'mcp_prompt_get': 5000,
    'default': 5000
}


def _extract_clean_insight(raw: str) -> str:
    """
    [TASK_41] Robustly extracts the 'insight' text from raw LLM output.
    Handles three common leakage patterns:
      1. Pure JSON:    {"insight": "...", "actions": [...]}
      2. Markdown fence: ```json\n{...}\n```
      3. JSON embedded mid-text with key 'insight'
    Returns the original string unchanged if no JSON wrapper is detected.
    """
    import re as _re
    if not raw or not isinstance(raw, str):
        return raw
    s = raw.strip()

    # Pattern 1: starts with {
    if s.startswith('{'):
        try:
            import json as _j
            _inner = _j.loads(s)
            if isinstance(_inner, dict) and _inner.get('insight'):
                return str(_inner['insight'])
        except Exception:
            pass

    # Pattern 2: markdown code fence ```json ... ```
    _m = _re.search(r'```(?:json)?\s*(\{[\s\S]*?\})\s*```', s)
    if _m:
        try:
            import json as _j
            _inner = _j.loads(_m.group(1))
            if isinstance(_inner, dict) and _inner.get('insight'):
                return str(_inner['insight'])
        except Exception:
            pass

    # Pattern 3: JSON embedded in prose — find first "insight" value
    _m2 = _re.search(r'"insight"\s*:\s*"((?:[^"\\]|\\.)+)"', s)
    if _m2:
        return _m2.group(1).replace('\\"', '"')

    return raw


def add_limited_rag_log(log_deque, log_msg, action_type='default'):
    """
    RAG 로그 추가 (deque 사용)
    - O(1) 성능
    - 자동 크기 제한
    """
    max_size = TOOL_LOG_LIMITS.get(action_type, 5000)

    if len(log_msg) > max_size:
        log_msg = log_msg[:max_size] + f"... [truncated at {max_size}]"

    log_deque.append(log_msg)


class _TokenBucketRateLimiter:
    """
    Simple token-bucket rate limiter for LLM API calls.
    Avoids fixed sleep(4) by tracking actual request timing.
    """
    def __init__(self, max_rpm=12):
        self._interval = 60.0 / max_rpm  # seconds between requests
        self._last_request = 0.0

    def acquire(self):
        import time as _time
        import random as _random
        now = _time.monotonic()
        wait = self._interval - (now - self._last_request)
        if wait > 0:
            # v6.3: Add small jitter to prevent synchronized bursts
            jitter = _random.uniform(0.1, 0.5)
            logger.debug(f"[RateLimiter] Waiting {wait + jitter:.1f}s (with jitter) before next LLM call")
            _time.sleep(wait + jitter)
        self._last_request = _time.monotonic()


# Token-bucket rate limiter for LLM API calls.
# v6.2: Reduced max_rpm to 10 for better stability on free tiers.
# v6.3: Raised to 30 — prompt caching reduces token load; paid tier confirmed. [2026-03-25]
_RATE_LIMITER = _TokenBucketRateLimiter(max_rpm=30)

_SEMANTIC_CACHE = ThreadSafeLRUCache(max_size=100)  # LRU cache with automatic eviction

def bootstrap_ai_glossary():
    """
    v21.0: Bootstraps the AI Domain Glossary with critical control intent keywords.
    This replaces hardcoding in the runtime logic by externalizing data to the DB.
    """
    from flask import has_app_context
    if not has_app_context():
        # Called at module-import time (initialize_engine_registry) before any
        # request/app context exists. The startup path in app.py re-invokes this
        # within app.app_context(), so defer instead of raising "working outside
        # of application context" tracebacks on every worker boot.
        logger.debug("[Bootstrap] No app context; deferring AI glossary seed to startup.")
        return
    try:
        from aot.databases.models.ai_domain_glossary import AIDomainGlossary
        from aot.databases.models import db

        # --- Section 1: control_intent keywords (one-time seed) ---
        # Bare device NOUNS ('밸브', '전등', 'valve', ...) were removed from
        # this list (2026-07-19): the semantic guard treats any response
        # containing a control_intent term + empty actions as a hallucinated
        # action claim, so a noun here made EVERY legitimate data/knowledge
        # answer that merely mentions the device ("밸브는 ... 45초 걸림")
        # get discarded as hallucination and escalated — observed live; the
        # same false-positive class v26.10/BUG-06 already fixed for tool
        # names. A noun is zero evidence of control INTENT; only verb-like
        # command terms stay.
        if not AIDomainGlossary.query.filter_by(category='control_intent').first():
            logger.info("[Bootstrap] Seeding AI Domain Glossary with Control Intent keywords...")
            keywords = ['turn on', 'turn off', 'switch', 'operate', '켜줘', '꺼줘', '동작', '조절']
            for kw in keywords:
                db.session.add(AIDomainGlossary(
                    term=kw,
                    definition="Indicator of potential control intent for hallucination guarding",
                    category='control_intent',
                    source='system_bootstrap',
                    status='approved',
                ))

            # v22.0: Completion Indicators (for Semantic Guard P2)
            indicators = [
                '완료', '켰습니다', '꺼졌습니다', '완료되었습니다', '동작시켰습니다',
                'done', 'successfully', 'finished', 'completed', 'applied'
            ]
            for term in indicators:
                if not AIDomainGlossary.query.filter_by(term=term).first():
                    db.session.add(AIDomainGlossary(
                        term=term,
                        definition=f'Control completion indicator: {term}',
                        category='completion_indicator',
                        source='system_bootstrap',
                        status='approved',
                        is_active=True,
                    ))
            db.session.commit()

        # --- Retro-fix (idempotent, runs every startup): deactivate the bare
        # device nouns earlier bootstraps seeded into control_intent — the
        # one-time seed guard above means existing installs never re-seed, so
        # the corrected list alone can't reach them. Only system_bootstrap
        # rows are touched; an operator-added term is theirs to keep.
        _noun_terms = ['valve', '밸브', '전등', '에어컨', '티비']
        _stale = AIDomainGlossary.query.filter(
            AIDomainGlossary.category == 'control_intent',
            AIDomainGlossary.source == 'system_bootstrap',
            AIDomainGlossary.term.in_(_noun_terms),
            AIDomainGlossary.is_active.is_(True),
        ).all()
        if _stale:
            for row in _stale:
                row.is_active = False
            db.session.commit()
            logger.info(f"[Bootstrap] Deactivated {len(_stale)} device-noun control_intent term(s) "
                        f"(semantic-guard false-positive fix): {[r.term for r in _stale]}")
            logger.info("[Bootstrap] Control intent keywords and completion indicators seeded.")

        # --- Section 2: term_alias seeds (idempotent — safe to run on every boot) ---
        _term_aliases = [
            ('기상', 'OpenWeather'),
            ('날씨', 'OpenWeather'),
            ('weather', 'OpenWeather'),
            ('기온', 'OpenWeather'),
        ]
        _alias_added = 0
        for _term, _def in _term_aliases:
            if not AIDomainGlossary.query.filter_by(term=_term, category='term_alias').first():
                db.session.add(AIDomainGlossary(
                    term=_term, definition=_def,
                    category='term_alias', source='system_bootstrap',
                    status='approved', is_active=True,
                ))
                _alias_added += 1
        if _alias_added:
            db.session.commit()
            logger.info(f"[Bootstrap] {_alias_added} term alias(es) seeded.")
    except Exception as e:
        # Silence errors during migration/test phases where DB might be inaccessible
        logger.warning(f"Failed to bootstrap AI glossary: {e}")

# @ANCHOR: CACHE_WARMUP  [2026-03-25]
def _warm_semantic_cache(limit=50):
    """
    On startup, pre-load recent AI history into _SEMANTIC_CACHE
    so repeated queries hit cache immediately after server restart.
    """
    from flask import has_app_context
    if not has_app_context():
        # Deferred to the app-context warmup in app.py startup (see _warm_semantic_cache call).
        logger.debug("[CacheWarmup] No app context; deferring semantic cache warmup to startup.")
        return
    try:
        from aot.databases.models.ai import AIHistory
        records = (AIHistory.query
                   .filter_by(message_type='ai')
                   .order_by(AIHistory.timestamp.desc())
                   .limit(limit)
                   .all())
        loaded = 0
        for r in records:
            if r.goal and r.insight:
                meta = json.loads(r.metadata_json or '{}')
                _actions = json.loads(r.actions_json or '[]')
                # @ANCHOR: SEMANTIC_CACHE_WARMUP_GUARD [2026-03-25]
                # Only cache entries that had real execution: actions present OR synthesis verified.
                # Prevents failed/partial responses (insight = router text only) from poisoning cache.
                _synthesis_passed = meta.get('synthesis_passed', False)
                if not _actions and not _synthesis_passed:
                    logger.debug(f"[SemanticCache] Skipping warmup for '{r.goal[:40]}' — no actions and no synthesis.")
                    continue
                _SEMANTIC_CACHE[r.goal.strip().lower()] = {
                    "insight": r.insight,
                    "actions": _actions,
                    "intent": meta.get('intent'),
                    "agent_id": r.agent_id or 'auto'
                }
                loaded += 1
        if loaded:
            logger.info(f"[CacheWarmup] Loaded {loaded} entries into semantic cache.")
    except Exception as e:
        logger.warning(f"[CacheWarmup] Skipped: {e}")


def initialize_engine_registry():
    """
    Dynamically scans aot/ai/agents directory and registers all AI agents.
    Avoids hardcoding specific agents.
    """
    global ENGINE_REGISTRY, REGISTRY_INITIALIZED
    if REGISTRY_INITIALIZED:
        return
        
    # v21.0: Bootstrap domain knowledge in DB
    bootstrap_ai_glossary()
        
    agents_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'agents')
    if not os.path.exists(agents_dir):
        logger.error(f"Agents directory not found: {agents_dir}")
        return

    for filename in os.listdir(agents_dir):
        if filename.endswith('.py') and not filename.startswith('__') and filename != 'mcp_base.py':
            module_name = filename[:-3]
            try:
                # Import module
                module_path = f"aot.ai.agents.{module_name}"
                module = importlib.import_module(module_path)
                # v15.1: Force reload to pick up base class/interface changes (get_context_budget renaming)
                module = importlib.reload(module)
                
                # Check for AI_INFORMATION metadata
                if hasattr(module, 'AI_INFORMATION'):
                    info = module.AI_INFORMATION
                    engine_type = info.get('engine_type') or info.get('ai_name_unique')
                    if not engine_type:
                        continue
                        
                    # Find the class that inherits from BaseAI, AbstractAI or BaseMCP_AI
                    engine_class = None
                    for name, obj in inspect.getmembers(module, inspect.isclass):
                        if (name.endswith('_AI') or name.endswith('AI')) and obj.__module__ == module_path:
                            engine_class = obj
                            break
                    
                    if engine_class and engine_type:
                        ENGINE_REGISTRY[engine_type] = (engine_class, module)
                        logger.info(f"Dynamically registered AI engine: {engine_type} -> {engine_class.__name__}")
                        
                        # Special alias for ollama/local
                        if engine_type == 'ollama':
                            ENGINE_REGISTRY['local'] = (engine_class, module)
            except Exception as e:
                logger.error(f"Failed to load agent module {filename}: {e}")

    # v2.5: Symbolic Intent Router explicit registration
    try:
        from aot.ai.agents.intent_router import SymbolicIntentRouter, AI_INFORMATION as SIR_INFO
        from aot.ai.agents import intent_router as intent_router_module
        ENGINE_REGISTRY['symbolic_intent_router'] = (SymbolicIntentRouter, intent_router_module)
        logger.info("Explicitly registered SymbolicIntentRouter engine.")
    except ImportError as e:
        logger.debug(f"SymbolicIntentRouter not found during bootstrap: {e}")

    REGISTRY_INITIALIZED = True
    _warm_semantic_cache()

# Initial registration
initialize_engine_registry()


class AIAgentService:
    """
    Handles the lifecycle and execution of AI Agents.
    """
    _agent_cache = ThreadSafeLRUCache(max_size=32)

    @staticmethod
    def get_cached_agent(pipeline_role):
        """
        [PHASE 2.1] Returns the first active agent for the given role from cache.
        Reduces database load during router/planner phases.
        """
        from aot.databases.models.ai import AIAgent
        from aot.aot_flask.extensions import db
        from sqlalchemy.orm import joinedload
        
        cache_key = f"role_{pipeline_role}"
        cached = AIAgentService._agent_cache.get(cache_key)
        if cached:
            try:
                # v3.1: Re-attach the cached agent to the current session.
                # This prevents 'DetachedInstanceError' when accessing lazy-loaded attributes.
                return db.session.merge(cached, load=False)
            except Exception as _merge_err:
                logger.debug(f"[AIAgentService] Cache merge failed, re-fetching: {_merge_err}")
                # Fallback: keep going to re-fetch

        agent = AIAgent.query.options(joinedload(AIAgent.entry)).filter_by(pipeline_role=pipeline_role, is_activated=True).first()
        if agent:
            AIAgentService._agent_cache[cache_key] = agent
        return agent

    @staticmethod
    def get_engine(agent_id):
        """
        Instantiates the appropriate AI engine based on agent configuration.
        """
        from aot.databases.models import AIAgent
        agent_cfg = AIAgent.query.filter_by(unique_id=agent_id).first()
        if not agent_cfg:
            logger.error(f"AI Agent not found: {agent_id}")
            return None

        if not agent_cfg.entry:
            logger.error(f"AI Agent '{agent_cfg.name}' has no linked Entry (Service). Register an AI Service first.")
            return None

        model_type = agent_cfg.entry.model_type
        # v3.1: protocol (if set) takes precedence over model_type — lets an
        # AIEntry opt into a provider-agnostic driver (e.g. openai_compatible)
        # without needing a dedicated agents/*.py file for its provider.
        # NULL protocol (the default for every existing entry) falls straight
        # through to model_type — unchanged behavior for all current entries.
        registry_key = getattr(agent_cfg.entry, 'protocol', None) or model_type
        registry_entry = ENGINE_REGISTRY.get(registry_key)
        if registry_entry:
            engine_class, _ = registry_entry
            # Always instantiate with the USER-CONFIGURED model (from the agent's
            # AIEntry). Response-depth never swaps the model — it is applied as a
            # prompt directive at the route layer instead (see routes_ai_api).
            return engine_class(agent_cfg)

        logger.error(f"Unsupported model type: {model_type}")
        return None

    @staticmethod
    def get_engine_info(model_type):
        """
        Returns the metadata (AI_INFORMATION) for a specific engine type.
        Now also includes 'specialty' from the engine class if available.
        """
        entry = ENGINE_REGISTRY.get(model_type)
        if entry:
            engine_class, module = entry
            info = getattr(module, 'AI_INFORMATION', {}).copy()
            # v6: Inject class for internal use (e.g. MCP bridge listing)
            info['engine_class'] = engine_class
            # Inject specialty from class if not in info
            if 'specialty' not in info and hasattr(engine_class, 'MCP_SPECIALTY'):
                info['specialty'] = engine_class.MCP_SPECIALTY
            return info
        return {}

    # Code-based role presets (specialty, system_prompt, model_tier, tool_access)
    # These remain hardcoded as they are large multi-line texts not suitable for DB storage
    _CODE_ROLE_PRESETS = {
            'router': {
                'specialty': 'Intent Classification, Gatekeeping',
                'system_prompt': (
                    "You are the Router and Gatekeeper of the AoT (AI of Things) system.\n"
                    "Your MISSION is to classify user intent into one of: CONTROL, DATA_QUERY, SCHEDULE, COMPOSITE, CHAT.\n\n"
                    "INTENT DEFINITIONS:\n"
                    "- CONTROL: User wants to physically operate a device RIGHT NOW (immediately).\n"
                    "  Action verbs mean: operate, activate, turn on/off, open/close, run, start, stop, set\n"
                    "  Key: NO time-delay. Action happens NOW.\n"
                    "- SCHEDULE: User wants to execute a device action at a FUTURE point in time.\n"
                    "  Time-delay pattern: [number] + [time unit] + [delay word] + [action]\n"
                    "    e.g. 'after 30 seconds', 'in 5 minutes', '30초 뒤에', '5분 후에', 'dans 30 secondes'\n"
                    "  Recurring pattern: every/daily/weekly, 매일/반복, chaque jour\n"
                    "  Key rule: If a TIME DELAY (N sec/min/hour later/after/뒤/후) precedes an action, it is SCHEDULE.\n"
                    "  'duration only' (run for 1 min, 1분 동안) with NO delay = CONTROL.\n"
                    "  'delay + duration' (after 30s, run for 1 min) = SCHEDULE.\n"
                    "- DATA_QUERY: User wants to READ information — sensor data, status, OR how the\n"
                    "  system works: what it can do, how to do something, whether a feature exists,\n"
                    "  where a menu/option is (capability & how-to questions). No physical device action.\n"
                    "  e.g. 'can I change the colors?', 'how do I add a widget?', 'does it support X?',\n"
                    "       '색을 바꿀 수 있어?', '위젯 추가하는 법', '이 페이지에서 뭘 할 수 있어?'\n"
                    "- COMPOSITE: Requires both reading data AND controlling a device.\n"
                    "- CLARIFY: Intent is ambiguous — device unclear, or action cannot be determined.\n"
                    "- CHAT: ONLY greeting, identity question, or casual small-talk. A question about\n"
                    "  system features or how to do something is DATA_QUERY, never CHAT.\n\n"
                    "RULES:\n"
                    "1. Never answer the user command directly.\n"
                    "2. Only output strict JSON. NO CONVERSATIONAL TEXT.\n"
                    "3. SCHEDULE takes priority when a numeric time-delay (N sec/min/hour + delay word) is present.\n"
                    "4. CONTROL = right now. SCHEDULE = future time. Duration alone does NOT imply future.\n"
                    "5. If truly ambiguous with NO action verb, default to DATA_QUERY.\n"
                    "6. Capability / how-to / 'can I ...?' / 'how do I ...?' / feature-existence questions\n"
                    "   are DATA_QUERY (they need documentation), NOT CHAT.\n"
                    "FEW-SHOT EXAMPLES (multi-language):\n"
                    '  {"command":"Turn on valve2","intent":"CONTROL","confidence":0.98}\n'
                    '  {"command":"밸브2 켜줘","intent":"CONTROL","confidence":0.98}\n'
                    '  {"command":"Activate valve2 after 30 seconds for 1 minute","intent":"SCHEDULE","confidence":0.97}\n'
                    '  {"command":"30초 뒤에 밸브2 1분 작동시켜","intent":"SCHEDULE","confidence":0.97}\n'
                    '  {"command":"Turn on pump in 5 minutes","intent":"SCHEDULE","confidence":0.97}\n'
                    '  {"command":"What is the current temperature?","intent":"DATA_QUERY","confidence":0.98}\n'
                    '  {"command":"Can I change the dashboard colors?","intent":"DATA_QUERY","confidence":0.95}\n'
                    '  {"command":"색을 바꿀 수 있어?","intent":"DATA_QUERY","confidence":0.95}\n'
                    '  {"command":"이 페이지에서 뭘 할 수 있어?","intent":"DATA_QUERY","confidence":0.94}\n'
                    '  {"command":"How do I add a new widget?","intent":"DATA_QUERY","confidence":0.95}\n'
                    '  {"command":"안녕","intent":"CHAT","confidence":0.98}\n'
                    '  {"command":"Check temperature and turn on fan if high","intent":"COMPOSITE","confidence":0.9}'
                ),
                'model_tier': 'lightweight',
                'tool_access': 'none'
            },
            'planner': {
                'specialty': 'Strategic Planning, Task Decomposition',
                'system_prompt': (
                    "You are the Planner for the AoT system.\n"
                    "Your MISSION is to decompose complex user commands into a sequence of atomic, actionable steps.\n\n"
                    "RULES:\n"
                    "1. Use provided Tool Manifest to select appropriate tools.\n"
                    "2. Define dependencies between steps using $variable references.\n"
                    "3. Output an Execution Plan JSON with 'steps' and 'strategy'."
                ),
                'model_tier': 'heavy',
                'tool_access': 'none'
            },
            'executor': {
                'specialty': 'Tool Execution, Data Collection',
                'system_prompt': (
                    "You are a specialist Executor agent in the AoT (AI of Things) platform.\n"
                    "Your role is to execute tool calls precisely and return verified, raw data to the pipeline.\n"
                    "You are NOT the final decision-maker — your output feeds into a Supervisor or Synthesizer.\n\n"
                    "## Core Responsibilities\n\n"
                    "1. EXECUTE, then REPORT.\n"
                    "   Follow the parameters provided by the Planner exactly. If no plan is given,\n"
                    "   infer the required tool from the goal and available context.\n\n"
                    "2. TOOL CALL FORMAT.\n"
                    "   Respond ONLY as valid JSON:\n"
                    "   {\n"
                    "     \"insight\": \"<brief description of what was retrieved>\",\n"
                    "     \"actions\": [\n"
                    "       {\n"
                    "         \"action_type\": \"virtual_tool_call\",\n"
                    "         \"target_id\": \"virtual_mcp\",\n"
                    "         \"params\": { \"tool_name\": \"<tool>\", \"<arg>\": \"<value>\" }\n"
                    "       }\n"
                    "     ]\n"
                    "   }\n"
                    "   After tool results are returned to you, set \"actions\" to [] and report raw data in insight.\n\n"
                    "3. TOOL SELECTION RULES.\n"
                    "   - Sensor / weather / environmental data  → virtual_tool_call: get_sensor_detail\n"
                    "     Use zone unique_id (from spatial_hierarchy) as loc_id.\n"
                    "   - Device discovery / search              → virtual_tool_call: search_devices\n"
                    "   - Spatial hierarchy lookup               → virtual_tool_call: get_spatial_tree\n"
                    "   - Human task scheduling                  → virtual_tool_call: add_schedule\n"
                    "   - Device control                         → NEVER call operate_device.\n"
                    "     Control actions require human approval and must not be executed automatically.\n\n"
                    "4. DATA INTEGRITY.\n"
                    "   - Return exact values from tool results. Do NOT round, summarize, or omit data.\n"
                    "   - If a tool call returns no data, state that clearly. Do NOT fabricate values.\n"
                    "   - Never claim an action completed unless a tool result explicitly confirms it.\n\n"
                    "5. DYNAMIC RESOLUTION.\n"
                    "   All device IDs, zone IDs, and server IDs MUST be resolved from context\n"
                    "   (spatial_hierarchy, device_list, available_api_keys). Never hardcode IDs."
                ),
                'model_tier': 'standard',
                'tool_access': 'all'
            },
            'synthesizer': {
                'specialty': 'Result Synthesis, Fact Verification',
                'system_prompt': (
                    "You are the Synthesizer for the AoT system.\n"
                    "Your MISSION is to create a human-friendly response based on execution results.\n\n"
                    "RULES:\n"
                    "1. Verify every fact against the provided 'raw_data' and 'worker_insights'.\n"
                    "2. Unit Consistency: NEVER swap units. If a worker reports 'Area (㎡)', do NOT report it as 'Energy (kWh)'.\n"
                    "3. Cite tool sources for every claim.\n"
                    "4. Be EXTREMELY concise. Skip greetings (Hello, Sure, Okay) and filler sentences.\n"
                    "5. Focus only on actionable data and results. No decorative text.\n"
                    "6. If 'weeding' or manual work was recorded, confirm it by citing 'add_schedule' or 'note' result.\n"
                    "7. Advisory framing: Present findings as observations and considerations, not as commands.\n"
                    "   If an action is suggested, frame it as 'may be worth considering' or 'based on current data'.\n"
                    "8. Confidence signal: If any value used is a system default (not facility-confirmed), append:\n"
                    "   '(general baseline — not yet confirmed for this facility)'\n"
                    "9. When data is insufficient to form a reliable conclusion, say so explicitly rather than\n"
                    "   filling the gap with a confident-sounding statement."
                ),
                'model_tier': 'heavy',
                'tool_access': 'none'
            },
            'worker': {
                'specialty': 'General Purpose Assistant (Advanced Multimodal)',
                'system_prompt': (
                    "You are a specialist Worker agent in the AoT (AI of Things) platform.\n"
                    "AoT manages IoT environments: Inputs (sensors, weather APIs), Outputs (valves, pumps,\n"
                    "sprinklers), Functions (schedules, PID controllers), and GIS map layers.\n"
                    "Your role is to gather data, execute tool calls, and deliver a focused expert analysis\n"
                    "scoped to your assigned specialty. You are NOT the final decision-maker — your output\n"
                    "feeds into a Supervisor/Synthesizer that merges all worker perspectives.\n\n"

                    "## Core Responsibilities\n\n"

                    "1. RETRIEVE before you REASON.\n"
                    "   Never answer from memory alone. If the goal involves sensor readings, weather,\n"
                    "   device status, or any time-series value, call the appropriate tool FIRST and\n"
                    "   reason only from the returned data.\n\n"

                    "2. OUTPUT FORMAT — always strict JSON, nothing else:\n"
                    "   {\n"
                    "     \"insight\": \"<your expert analysis in the user's language>\",\n"
                    "     \"actions\": [ <tool call objects, or [] when reporting final results> ]\n"
                    "   }\n"
                    "   Tool call object shapes:\n"
                    "   • Virtual tool  → { \"action_type\": \"virtual_tool_call\", \"target_id\": \"virtual_mcp\",\n"
                    "                        \"params\": { \"tool_name\": \"<name>\", \"<arg>\": \"<value>\" } }\n"
                    "   • External MCP  → { \"action_type\": \"mcp_tool_call\", \"target_id\": \"<server_id>\",\n"
                    "                        \"params\": { \"tool_name\": \"<name>\", \"arguments\": {<per schema>} } }\n"
                    "   • Device output → { \"action_type\": \"output\", \"target_id\": \"<device_unique_id>\",\n"
                    "                        \"params\": { \"state\": true/false, \"duration\": <seconds> } }\n"
                    "   After tool results arrive, set \"actions\" to [] and report real data in insight.\n\n"

                    "3. TOOL SELECTION RULES (priority order).\n"
                    "   - Sensor / weather / environmental data  → virtual_tool_call: get_sensor_detail\n"
                    "     Use zone unique_id (from spatial_hierarchy) as loc_id.\n"
                    "   - Device discovery / search              → virtual_tool_call: search_devices\n"
                    "   - Spatial hierarchy lookup               → virtual_tool_call: get_spatial_tree\n"
                    "   - External integrations (if listed)      → mcp_tool_call (see capabilities.mcp_tools)\n"
                    "   - Technical specification lookup         → read_manual (LAST RESORT only)\n"
                    "   - Device control                         → NEVER call operate_device autonomously.\n"
                    "     Physical control requires human approval; return your intent and let the\n"
                    "     pipeline handle the approval gate.\n\n"

                    "4. STAY IN SCOPE.\n"
                    "   Analyse only what falls within your specialty. If the goal is outside your domain,\n"
                    "   return insight=\"Not applicable to my specialty\" and actions=[].\n\n"

                    "5. INSIGHT QUALITY.\n"
                    "   - Match the language the user used (Korean if Korean, English if English, etc.).\n"
                    "   - Plain conversational text. No Markdown (**, *, -, #).\n"
                    "   - No raw UUIDs, JSON structures, or internal field names in visible text.\n"
                    "   - Report exact measured values (numbers + units + timestamps) from tool results.\n"
                    "   - If a tool returns no data, say so explicitly. NEVER fabricate values.\n\n"

                    "6. MULTI-TURN AWARENESS.\n"
                    "   Tool results are injected into the conversation by the pipeline. After each\n"
                    "   tool result, re-evaluate your insight using the new data before responding.\n"
                    "   Do not repeat tool calls for data you already received.\n\n"

                    "7. PHYSICAL TRUTH.\n"
                    "   Never claim an action completed unless a tool execution result explicitly\n"
                    "   confirms it. State intent ('I will…'), not past completion ('I did…').\n\n"

                    "8. DYNAMIC RESOLUTION.\n"
                    "   All device IDs, zone IDs, server IDs, and API keys MUST be resolved from\n"
                    "   context (spatial_hierarchy, device_list, available_api_keys). Never hardcode.\n\n"

                    "9. ADVISORY FRAMING (law_8_philosophy_alignment).\n"
                    "   Insights are advisory — never directive. Frame conclusions as observations:\n"
                    "   'Current readings suggest…', 'Based on available data…', 'May be worth considering…'\n"
                    "   When context is unconfirmed (system default, not facility-calibrated), say so.\n"
                    "   When data is insufficient to conclude reliably, state the limitation explicitly."
                ),
                'model_tier': 'standard',
                'tool_access': 'all'
            }
        }

    @staticmethod
    def get_role_presets():
        """
        v6: Returns default configurations for each pipeline role.
        Merges DB-driven values (model, temperature, max_tokens, descriptions)
        with code-driven values (specialty, system_prompt, model_tier, tool_access).
        """
        from aot.databases.models.ai import AgentRolePreset

        # Read DB presets
        db_presets = {}
        try:
            rows = db.session.query(AgentRolePreset).filter_by(is_active=True).all()
            for row in rows:
                db_presets[row.pipeline_role] = {
                    'ai_name_unique': row.ai_name_unique,
                    'model_value': row.model_value,
                    'temperature': row.temperature,
                    'max_tokens': row.max_tokens,
                    'description_en': row.role_description_en,
                    'description_ko': row.role_description_ko,
                }
        except Exception as e:
            logger.warning(f"Failed to read AgentRolePreset from DB: {e}")
            db_presets = {}

        # Merge code-based and DB-based presets
        result = {}
        for role, code_data in AIAgentService._CODE_ROLE_PRESETS.items():
            merged = dict(code_data)  # Copy code-based values
            if role in db_presets:
                merged.update(db_presets[role])  # Override with DB values
            result[role] = merged
        return result

    @staticmethod
    def get_all_engine_presets():
        """
        Returns presets for all registered engines.
        Used by the UI to populate engine/model selection dropdowns.
        Each entry's AI_INFORMATION provides models, default_endpoint, etc.
        """
        presets = {}
        seen = set()
        for engine_key, (engine_class, module) in ENGINE_REGISTRY.items():
            info = getattr(module, 'AI_INFORMATION', {})
            unique = info.get('ai_name_unique', engine_key)
            if unique in seen:
                continue
            seen.add(unique)
            presets[engine_key] = {
                'ai_name': info.get('ai_name', engine_key),
                'ai_manufacturer': info.get('ai_manufacturer', 'AoT'),
                'default_endpoint': info.get('default_endpoint', ''),
                'endpoint_hint': info.get('endpoint_hint', ''),
                'models': info.get('models', []),
                'auth_methods': info.get('auth_methods', ['api_key']),
                'auth_link': info.get('auth_link', ''),
                'custom_options': info.get('custom_options', []),
                'description': str(info.get('description', '')),
                'message': str(info.get('message', '')), # Ensure string for JSON (could be lazy_gettext)
                'specialty': info.get('specialty', getattr(engine_class, 'MCP_SPECIALTY', 'general')),
                'system_prompt': info.get('system_prompt', "You are a specialized MCP tool expert." if info.get('is_mcp') else "You are a helpful assistant."),
                'is_mcp': info.get('is_mcp', False),
                'ai_category': info.get('ai_category', 'mcp' if info.get('is_mcp') else 'llm')
            }
        return presets

    # [OPTION_D] Helper function to strip action_type from chat history
    @staticmethod
    def _strip_action_type_from_history(message):
        """
        Removes action_type field references from message content.
        Prevents AI from reintroducing action_type field through imitation.
        """
        if isinstance(message, dict) and 'content' in message:
            import re
            # Replace action_type mentions with tool_name references
            content = message.get('content', '')
            if isinstance(content, str):
                # Pattern: "action_type": "something" → "tool_name": "..."
                content = re.sub(
                    r'"action_type"\s*:\s*"[^"]*"',
                    '"tool_name": "..."',
                    content
                )
                message['content'] = content
        return message

    @staticmethod
    def get_thread_history(thread_id, limit=10, months=3, user_id=None):
        """
        Retrieves recent conversation history for a given thread.
        Filters out messages older than 'months' and flags rejected proposals.
        Provides the AI with 'Short-term Thread Memory'.

        user_id: when provided, restricts results to that user's records (REQ-1/REQ-2).
                 Falls back to current Flask-Login user if available and user_id is None.
        """
        from aot.databases.models import AIHistory
        if not thread_id:
            return []

        # Resolve user_id for scoping. Resolve from Flask request context when not
        # supplied explicitly so background daemon calls (no request ctx) still work.
        _user_id = user_id
        if _user_id is None:
            try:
                import flask_login
                cu = flask_login.current_user
                if cu and cu.is_authenticated:
                    _user_id = cu.id
            except Exception:
                pass  # Outside request context — omit user filter (daemon/batch calls)

        try:
            from aot.utils.time_utils import utc_now
            cutoff = utc_now() - timedelta(days=months * 30)
            _q = AIHistory.query.filter(
                AIHistory.thread_id == thread_id,
                AIHistory.timestamp >= cutoff
            )
            if _user_id is not None:
                _q = _q.filter(AIHistory.user_id == _user_id)
            history = _q.order_by(AIHistory.timestamp.desc()).limit(limit).all()
            
            # Reverse to get chronological order
            history.reverse()
            
            formatted = []
            for h in history:
                # Disambiguate user goal and AI insight
                content = h.goal if h.message_type == 'user' else h.insight
                if h.message_type == 'user' and content.startswith("Smart Command: "):
                    content = content.replace("Smart Command: ", "", 1)

                # @ANCHOR: TOOL_RESULT_CONTEXT_RETENTION
                # [fix_tool_result_context_retention] Append prior tool execution results
                # to the AI turn content so follow-up queries can reference them.
                # Without this, avg/min/max from get_sensor_detail are lost between turns.
                if h.message_type != 'user' and h.execution_result:
                    _exec = h.execution_result.strip()
                    if _exec:
                        content = (content or '') + f"\n[Tool Results: {_exec}]"

                # v17.0: Apply smart truncation for memory optimization
                content = truncate_message_smart(content, max_length=3000)

                formatted.append({
                    "role": h.message_type, # user, ai, assistant
                    "content": content,
                    "status": h.status,
                    "is_rejected_proposal": h.status == 'rejected'
                })
            return formatted
        except Exception:
            logger.exception(f"Error fetching thread history: {thread_id}")
            return []

    @staticmethod
    def process_natural_language_command(agent_id, command_text, thread_id=None,
                                         page_context=None, attachments=None,
                                         depth=None, autonomy=None):
        """Public entry point for a chat turn.

        Thin wrapper that publishes the per-request AI context (image
        attachments + judgment-level controls) into a thread-local shared by
        the whole reasoning pipeline, then delegates to the implementation.
        The context is restored on exit so nested re-entry (goal loop) and
        thread-pool reuse never leak a previous turn's images/mode.
        """
        from aot.ai import ai_request_context as _ai_ctx
        _token = _ai_ctx.push(attachments=attachments, depth=depth, autonomy=autonomy)
        try:
            return AIAgentService._process_nl_command_impl(
                agent_id, command_text, thread_id=thread_id, page_context=page_context)
        finally:
            _ai_ctx.pop(_token)

    @staticmethod
    def _process_nl_command_impl(agent_id, command_text, thread_id=None, page_context=None):
        """
        Processes a natural language command from the user,
        translates it into potential actions, and registers them as DRAFT jobs.
        If agent_id is 'auto', it uses the supervisor to dispatch to correct workers.
        """
        _pnc_t0 = time.monotonic()
        # [v26.0] Check if AI features are enabled before processing any command
        from aot.databases.models import AIGlobalSettings, AIAgent
        ai_settings = AIGlobalSettings.query.first()
        if not ai_settings or not ai_settings.ai_enabled:
            logger.info("AI features are disabled. Blocking command execution.")
            return {"status": "error", "message": "AI features are currently disabled. Please enable them in AI Settings."}

        # v3.1 Phase 6: budget hard-stop gate (flag-gated → no work when off).
        # If the active worker's connection is at hard-stop for the month, block
        # new AI work with a clear message rather than incurring more cost.
        if getattr(ai_settings, 't3_budget_governance_enabled', False):
            try:
                from aot.ai.services.budget_service import is_hard_stopped
                worker = AIAgentService.get_cached_agent('worker') or AIAgentService.get_cached_agent('executor')
                _entry = getattr(worker, 'entry', None) if worker else None
                if _entry and is_hard_stopped(_entry.unique_id):
                    from flask_babel import gettext as _
                    return {"status": "error",
                            "message": _("This month's AI usage limit has been reached; AI features are paused. They resume automatically on the 1st of next month.")}
            except Exception:
                pass  # budget gate must never break the request path

        if agent_id == 'auto':
            # @ANCHOR: AGENT_LOOP_CANARY (Phase 1, docs/design/ai-agent-loop.md).
            # For canary users, replace the ENTIRE router→planner→synthesizer
            # fan-out below with the single agent loop. Flag/allowlist default
            # off — zero behavior change for everyone else. Checked before the
            # semantic cache so a canary user never gets a cached response from
            # the (different) legacy pipeline's phrasing.
            try:
                _uid = current_user.id if current_user and current_user.is_authenticated else None
            except Exception:
                _uid = None
            from aot.ai.services.agent_loop_service import AgentLoopService
            if AgentLoopService.is_canary_active(_uid):
                logger.info(f"[AgentLoop] canary active for user={_uid} — routing to AgentLoopService")
                _al_result = AgentLoopService.run(
                    command_text, thread_id=thread_id, page_context=page_context, agent_id=agent_id)
                _log_path_metrics('agent_loop', _pnc_t0, intercept='agent_loop',
                                   ok=isinstance(_al_result, dict) and _al_result.get('status') != 'error')
                return _al_result

            # v16.8: Semantic Cache Check (Phase 18 PoC)
            # v17.0: Using ThreadSafeLRUCache
            clean_cmd = command_text.strip().lower()
            cached = _SEMANTIC_CACHE.get(clean_cmd)
            if cached:
                logger.info(f"[SemanticCache] Hit for: '{clean_cmd}'")
                # Re-dispatch using cached data to create a new history entry
                dispatch_res = AIAgentService._dispatch_actions(
                    agent_id=cached.get('agent_id', 'auto'),
                    goal=command_text,
                    insight=cached.get('insight', ''),
                    actions=cached.get('actions', []),
                    thread_id=thread_id,
                    message_type='ai',
                    metadata={"intent": cached.get('intent'), "cache_hit": True}
                )
                return {
                    "status": "success", "insight": cached.get('insight', ''),
                    "intent": cached.get('intent'), "proposed_actions": cached.get('actions', []),
                    "immediate_results": [], "draft_job_ids": [],
                    "history_id": dispatch_res['history_id']
                }

            # 0. Check for Resolved Intent (Bypass Router if user clicked a suggestion button)
            intent_override = None
            router_res = {}  # Safe default — populated by run_router() if not bypassed
            if command_text.startswith("[RESOLVED_INTENT:"):
                try:
                    import re
                    match = re.search(r"\[RESOLVED_INTENT: (.*?)\]", command_text)
                    if match:
                        intent_override = match.group(1)
                        command_text = command_text.split("]", 1)[1].strip()
                        logger.info(f"Bypassing router due to resolved intent: {intent_override}")
                except Exception:
                    pass

            # 1. Run Router (Gatekeeper) if not bypassed
            if not intent_override:
                router_res = AIAgentService.run_router(command_text, thread_id=thread_id)
                intent_override = router_res.get('intent')
                complexity = router_res.get('complexity', 'SIMPLE')

                # v6: Legacy C_AMBIGUOUS handling (backward compat for old router configs)
                if intent_override == 'C_AMBIGUOUS':
                    suggested = router_res.get('suggested_actions', [])
                    if suggested:
                        router_agent = AIAgent.query.filter_by(role='router', is_activated=True).first()
                        router_id = router_agent.unique_id if router_agent else 'router'
                        dispatch_res = AIAgentService._dispatch_actions(
                            agent_id=router_id, goal=command_text,
                            insight=router_res.get('insight', ''), actions=[],
                            thread_id=thread_id, message_type='ai',
                            metadata={"intent": "C_AMBIGUOUS", "suggested_actions": suggested}
                        )
                        return {
                            "status": "success", "insight": router_res.get('insight', ''),
                            "intent": "C_AMBIGUOUS", "suggested_actions": suggested,
                            "history_id": dispatch_res['history_id']
                        }
                    # No suggestions → treat as DATA_QUERY (Force Tool Policy)
                    intent_override = 'DATA_QUERY'

                # P3: CLARIFY intent or low-confidence — return clarifying question immediately,
                # bypassing Planner, Executor, Worker, and Synthesizer phases.
                from flask import current_app
                _confidence_threshold = current_app.config.get('INTENT_CONFIDENCE_THRESHOLD', 0.7)
                _router_confidence = router_res.get('confidence', 1.0)
                if intent_override == 'CLARIFY' or _router_confidence < _confidence_threshold:
                    clarify_insight = router_res.get('insight', '')
                    if not clarify_insight:
                        from flask_babel import gettext as _
                        clarify_insight = _("I'm not sure I understood your request. Could you please clarify?")
                    router_agent_cfg = AIAgent.query.filter_by(pipeline_role='router', is_activated=True).first()
                    clarify_agent_id = router_agent_cfg.unique_id if router_agent_cfg else agent_id
                    dispatch_res = AIAgentService._dispatch_actions(
                        agent_id=clarify_agent_id, goal=command_text,
                        insight=clarify_insight, actions=[],
                        thread_id=thread_id, message_type='ai',
                        metadata={"intent": "CLARIFY", "confidence": _router_confidence}
                    )
                    logger.info(f"[P3] Clarification bypass triggered. intent={intent_override}, confidence={_router_confidence:.2f}")
                    return {
                        "status": "success", "insight": clarify_insight,
                        "intent": "CLARIFY", "proposed_actions": [],
                        "immediate_results": [], "draft_job_ids": [],
                        "history_id": dispatch_res['history_id']
                    }

                # v6: CHAT shortcut — skip Planner/Executor/Synthesizer pipeline
                if intent_override == 'CHAT':
                    logger.info(f"[v6] CHAT shortcut for: {command_text}")
                    
                    # v16.8: Ultra-Fast Path — Use static response from router if available
                    if router_res.get('static_response'):
                        static_insight = router_res.get('insight', 'Hello!')
                        dispatch_res = AIAgentService._dispatch_actions(
                            agent_id='router', goal=command_text,
                            insight=static_insight, actions=[],
                            thread_id=thread_id, message_type='ai',
                            metadata={"intent": "CHAT", "shortcut": "static"}
                        )
                        return {
                            "status": "success", "insight": static_insight,
                            "intent": "CHAT", "proposed_actions": [],
                            "immediate_results": [], "draft_job_ids": [],
                            "history_id": dispatch_res['history_id']
                        }

                    # Use synthesizer or first available agent for direct response
                    chat_agent = (
                        AIAgent.query.filter_by(pipeline_role='synthesizer', is_activated=True).first()
                        or AIAgent.query.filter_by(role='supervisor', is_activated=True).first()
                        or AIAgent.query.filter_by(is_activated=True).first()
                    )
                    if chat_agent:
                        chat_engine = AIAgentService.get_engine(chat_agent.unique_id)
                        if chat_engine:
                            full_history = AIAgentService.get_thread_history(thread_id)
                            # [OPTION_D] Strip legacy action_type field from history
                            chat_history = [AIAgentService._strip_action_type_from_history(m) for m in full_history]
                            from aot.utils.time_utils import get_local_now
                            current_time_str = get_local_now().strftime("%Y-%m-%d %A %H:%M:%S %Z (UTC%z)")
                            chat_result = chat_engine.run_reasoning(
                                {"chat_history": chat_history, "current_time": current_time_str},
                                command_text
                            )
                            learning = AILearningService.process_ai_response(chat_result.get('insight', ''))
                            dispatch_res = AIAgentService._dispatch_actions(
                                agent_id=chat_agent.unique_id, goal=command_text,
                                insight=learning.get('text', ''), actions=[],
                                thread_id=thread_id, message_type='ai',
                                metadata={"intent": "CHAT", "shortcut": True}
                            )
                            return {
                                "status": "success", "insight": learning.get('text', ''),
                                "intent": "CHAT", "proposed_actions": [],
                                "immediate_results": [], "draft_job_ids": [],
                                "history_id": dispatch_res['history_id']
                            }

            # [027_STEP_2] Force-sync MCP tools cache whenever CONTROL intent is detected.
            # Prevents stale tools cache from causing false HARDWARE_OFFLINE in pre-flight.
            # @ANCHOR: control_intent_force_sync
            if intent_override == 'CONTROL':
                try:
                    from aot.ai.services.mcp_bridge_service import MCPBridgeService as _MCPB_s2
                    _active_s2 = _MCPB_s2.get_active_servers()
                    for _srv in _active_s2:
                        _MCPB_s2.get_tools(_srv.unique_id, force_refresh=True)
                    logger.info(f"[027_STEP_2] Force-synced tools for {len(_active_s2)} active MCP server(s).")
                except Exception as _fs_err:
                    logger.warning(f"[027_STEP_2] MCP force-sync failed (non-fatal): {_fs_err}")

            # 2. Fast Path — DATA_QUERY (SIMPLE + COMPLEX) [2026-04-02 re-enabled]
            # Scope: ALL DATA_QUERY intents → single executor LLM + RAG loop (max 2).
            # Skips Planner / Supervisor / Synthesizer (3-4 LLM calls removed).
            # run_fast_path() already handles MCP tool calls via RAG loop — no need for Planner.
            # COMPLEX DATA_QUERY also handled here; Planner was hallucinating data anyway.
            # If run_fast_path() returns status=escalate|error → falls through to full pipeline.
            # CONTROL / SCHEDULE / COMPOSITE / FUNCTION_CREATE always use full MCP pipeline.
            # Goal-directed continuous loop (agentic T1) — flag-gated. When enabled,
            # an eligible request (CONTROL/COMPOSITE/DATA_QUERY) is pursued as a GOAL:
            # autonomous read-chaining within the turn (reads never need approval, no
            # per-step re-prompt), physical control batched to a single approval. It
            # owns its own escalation fallback, so hard cases behave like the legacy
            # path. Flag off (default) skips this entirely — behavior is unchanged.
            # [Deterministic intent interceptors] recent-control reference, location-
            # /map-scoped control, and function-create requests are resolved
            # DETERMINISTICALLY — never left to the LLM to freelance a device grab-bag
            # or stall on a missing function_type. Extracted to intent_resolver.py
            # (architecture Phase 2) — a single call tries each interceptor in
            # declaration order and returns None to fall through when nothing resolves.
            from aot.ai.services import intent_resolver
            _intercepted = intent_resolver.resolve(
                command_text, thread_id=thread_id, page_context=page_context,
                intent_override=intent_override)
            if _intercepted:
                _log_path_metrics(_intercepted.get('_intercept', 'deterministic'), _pnc_t0,
                                   intercept=_intercepted.get('_intercept'))
                return _intercepted

            from aot.ai.services import goal_loop_service as _goal_loop
            if _goal_loop.handles(intent_override):
                _gl_result = _goal_loop.run(
                    command_text, intent=intent_override,
                    thread_id=thread_id, page_context=page_context,
                    router_insight=router_res.get('insight') if intent_override != 'C_AMBIGUOUS' else None,
                    complexity=complexity,
                )
                if isinstance(_gl_result, dict):
                    _gl_result.setdefault('_intercept', 'goal_loop')
                _log_path_metrics('goal_loop', _pnc_t0, intercept='goal_loop',
                                   ok=isinstance(_gl_result, dict) and _gl_result.get('status') != 'error')
                return _gl_result

            if intent_override == 'DATA_QUERY':
                fp_result = AIAgentService.run_fast_path(
                    command_text, intent=intent_override,
                    thread_id=thread_id, page_context=page_context
                )
                if fp_result.get('status') not in ('escalate', 'error'):
                    fp_result.setdefault('_intercept', 'fast_path')
                    _log_path_metrics('fast_path', _pnc_t0, intercept='fast_path')
                    return fp_result
                logger.info(f"[FastPath] Escalated to full pipeline: {fp_result.get('reason', '?')}")

            # 2.5 v3.1 T1 Unified Loop (Phase 1) — flag-gated. When enabled, CONTROL
            # intents route through the single bounded loop (run_fast_path engine,
            # ~2 LLM calls) instead of the legacy planner→supervisor→synthesizer
            # pipeline (4-5 calls). T1UnifiedLoop.run owns its own escalation
            # fallback to run_collaborative_reasoning, so on the hard cases behavior
            # is identical to the legacy path. Flag off (default) skips this entirely.
            from aot.ai.services.t1_loop import T1UnifiedLoop, handles as _t1_handles
            if _t1_handles(intent_override):
                _t1_result = T1UnifiedLoop.run(
                    command_text, intent=intent_override,
                    thread_id=thread_id, page_context=page_context,
                    router_insight=router_res.get('insight') if intent_override != 'C_AMBIGUOUS' else None,
                    complexity=complexity,
                )
                if isinstance(_t1_result, dict):
                    _t1_result.setdefault('_intercept', 't1_loop')
                _log_path_metrics('t1_loop', _pnc_t0, intercept='t1_loop',
                                   ok=isinstance(_t1_result, dict) and _t1_result.get('status') != 'error')
                return _t1_result

            # 3. Find the primary supervisor
            supervisor = AIAgent.query.filter_by(role='supervisor', is_activated=True).first()
            if not supervisor:
                supervisor = AIAgent.query.filter_by(is_activated=True).first()

            if not supervisor:
                return {"status": "error", "message": "No active AI agents available"}

            # 4. Use collaborative reasoning (Supervisor analyzes and dispatches)
            logger.info(f"Auto-dispatching (Intent: {intent_override}) using {supervisor.name}: {command_text}")
            _collab_result = AIAgentService.run_collaborative_reasoning(
                supervisor.unique_id, command_text,
                thread_id=thread_id, page_context=page_context,
                intent=intent_override,
                router_insight=router_res.get('insight') if intent_override != 'C_AMBIGUOUS' else None,
                complexity=complexity
            )
            if isinstance(_collab_result, dict):
                _collab_result.setdefault('_intercept', 'collaborative')
            _log_path_metrics('collaborative', _pnc_t0, intercept='collaborative',
                               ok=isinstance(_collab_result, dict) and _collab_result.get('status') != 'error')
            return _collab_result

        agent_cfg = AIAgent.query.filter_by(unique_id=agent_id).first()
        if not agent_cfg:
            return {"status": "error", "message": "Invalid agent"}

        engine = AIAgentService.get_engine(agent_id)
        if not engine:
            return {"status": "error", "message": "Engine initialization failed"}

        try:
            # Analyze user proficiency based on current command
            if current_user and current_user.is_authenticated:
                AILearningService.analyze_user_proficiency(current_user.id, command_text)
                
            # 1. Provide context and command as the "goal"
            tier = agent_cfg.model_tier if agent_cfg else 'standard'
            context = AIContextService.get_master_context(focused_target=page_context, tier=tier)
            manifest = AIActionService.get_action_manifest(agent_unique_id=agent_id)
            full_history = AIAgentService.get_thread_history(thread_id)
            # [OPTION_D] Strip legacy action_type field from history
            history = [AIAgentService._strip_action_type_from_history(m) for m in full_history]
            
            full_context = {
                "system_state": context,
                "capabilities": manifest,
                "chat_history": history, # Memory of previous turns
                "user_command": command_text,
                "page_context": page_context, # Current page/device context
                "current_time": get_local_now().strftime("%Y-%m-%d %A %H:%M:%S %Z (UTC%z)")
            }

            # Instructions for the LLM to focus on the specific user command
            prompt = (
                f"USER COMMAND: \"{command_text}\".\n"
                "Interpret this command and fulfill it proactively.\n"
                "1. CRITICAL: Check 'chat_history' first. If the user says 'check again', 'tell me more', 'do it', or uses pronouns/short references, they are continuing the PREVIOUS conversation. You MUST resolve these references from chat_history before responding.\n"
                "2. If the goal requires data not present in 'system_state' (like historical data, detailed logs, or specific past events), "
                "you MUST use available 'mcp_tools' or 'get_detailed_manifest' to find it. Do not assume data doesn't exist just because it's not in the current view.\n"
                "3. If the user specifies a time or relative time (e.g. '12 hours ago'), use the database or MCP tools to query a relevant time RANGE (e.g. '11.5 to 12.5 hours ago').\n"
                "4. NOTE: The 'system_state' sensor readings usually show only the LATEST values (within ~1 hour). Historical data MUST be queried via tools.\n"
                "5. Detect the language of the USER COMMAND and strictly write your 'insight' in that SAME language.\n"
                "6. If you call a tool, return it in the 'actions' list. You will get the result for final synthesis.\n"
                "7. SCHEDULING CATEGORIZATION: \n"
                "   - For manual human work (weeding/제초, inspection/점검, cleaning, etc.), use 'add_schedule'. These are stored in SchedulerJobMeta (action_type=human) and are included in the upcoming schedule context under 'human_schedules'.\n"
                "   - For system/device control (valves, pumps, sprinklers), use 'schedule_device_control'. These go to the Scheduler (AITask).\n"
                "   - If the user mentions 'weeding' or 'work', do NOT call OpenWeather tools; prioritize the scheduling tools.\n"
                "8. [TASK_8 056_] LOOK BEFORE LEAP (LBL): NEVER call 'control_device' or 'operate_device' without a preceding 'search_devices' or 'get_detailed_manifest' call in the SAME plan, unless a physical UUID is already explicitly present in the raw User Request."
            )

            # v26.9: Inject Situation Baseline for better context awareness
            AIAgentService._inject_situation_baseline(full_context, page_context)

            # 2. Reason (engine should return JSON with 'insight' and 'actions')
            max_rag_loops = 3
            rag_loop_count = 0
            # v17.0: Using deque for O(1) performance and automatic size limiting
            all_rag_logs = deque(maxlen=MAX_RAG_LOGS)

            while rag_loop_count < max_rag_loops:
                result = engine.run_reasoning(full_context, prompt)

                actions = result.get('actions', [])
                # Extract actions that are safe for automatic context-gathering (RAG)
                # [P4] Block physical control tools in RAG phase — must pass Phase 4/5 approval gates.
                # [RAG-FIX] Check both params.tool_name AND top-level tool_name:
                # LLM may output tool_name at top level before _validate_and_normalize_action moves it.
                _RAG_TYPES = {'read_manual', 'knowledge_search', 'get_detailed_manifest', 'mcp_tool_call', 'virtual_tool_call', 'mcp_resource_read', 'mcp_prompt_get'}
                from aot.ai.services.resolvers.constants import PHYSICAL_TOOLS as _PHYS
                def _is_physical_action(a):
                    t = a.get('params', {}).get('tool_name') or a.get('tool_name', '')
                    return t in _PHYS
                rag_actions = [a for a in actions if
                               (a.get('action_type') in _RAG_TYPES
                                or (a.get('tool_name') and not _is_physical_action(a) and not a.get('action_type')))
                               and not _is_physical_action(a)]

                if not rag_actions:
                    break # No more RAG actions, proceed to final output

                rag_loop_count += 1
                logger.info(f"Auto-RAG loop {rag_loop_count} executing actions: {rag_actions}")

                # Execute RAG actions synchronously without user permission
                rag_results = []
                for a in rag_actions:
                    try:
                        # v21.0: P1 Metadata Validation
                        valid, err = AIAgentService._validate_and_normalize_action(a)
                        if not valid:
                            add_limited_rag_log(all_rag_logs, f"Validation Error: {err}", 'default')
                            continue

                        res = AIActionService.execute_action(a['action_type'], a.get('target_id'), a.get('params'))

                        # [001_WEATHER_LOGIC_UPGRADE] Weather-aware truth tagging via AIRoutingService
                        if a.get('action_type') == 'virtual_tool_call':
                            from aot.ai.services.ai_routing_service import AIRoutingService as _ARS
                            log_msg = _ARS.format_weather_tool_result(a, res)
                        else:
                            # [TASK_8 054_] Truth-Source Enforcement: Tag sensor/weather data from MCP
                            _t_name = (a.get('params', {}).get('tool_name') or '').lower()
                            _is_truth = any(k in _t_name for k in ('sensor', 'weather', 'measurement', 'current', 'read'))
                            _prefix = "[SRC:MCP] " if _is_truth else ""
                            log_msg = f"Auto-RAG Action '{a['action_type']}' Output:\n{_prefix}{json.dumps(res, ensure_ascii=False)}"

                        rag_results.append(log_msg)
                        add_limited_rag_log(all_rag_logs, log_msg, a['action_type'])
                    except Exception as e:
                        err_msg = f"Auto-RAG Action '{a['action_type']}' Failed:\n{str(e)}"
                        rag_results.append(err_msg)
                        add_limited_rag_log(all_rag_logs, err_msg, 'default')

                # Append to context history and re-prompt the engine
                if 'chat_history' not in full_context:
                    full_context['chat_history'] = []
                
                full_context['chat_history'].append({
                    "role": "assistant",
                    "content": "Executing search: " + json.dumps(rag_actions, ensure_ascii=False)
                })
                full_context['chat_history'].append({
                    "role": "user",
                    "content": (
                        "System Execution Result (TRUTH SOURCE):\n" + "\n".join(rag_results) + 
                        "\n\nBased on this TRUTH SOURCE, please fulfill my original request. "
                        "If these real-time values differ from the 'system_state' provided earlier, "
                        "you MUST trust these latest execution results."
                    )
                })
                
            # 2.4 Final cleanup: Remove RAG/info actions — keep control actions for approval
            # [TASK_37] operate_device must survive this filter
            _CTRL_KEEP = {'operate_device', 'output_on', 'output_off', 'set_output', 'control_output'}
            result['actions'] = [
                a for a in result.get('actions', [])
                if a.get('action_type') not in ['read_manual', 'knowledge_search', 'get_detailed_manifest', 'mcp_tool_call', 'virtual_tool_call', 'mcp_resource_read', 'mcp_prompt_get']
                or a.get('params', {}).get('tool_name') in _CTRL_KEEP
                or a.get('tool_name') in _CTRL_KEEP
            ]

            # 2.5 v6 Synthesizer: Verify and refine the response
            synth_result = AIAgentService.run_synthesizer(
                execution_results=all_rag_logs,
                intent=intent_override if agent_id == 'auto' else None,
                original_command=command_text,
                chat_history=history,
                worker_insights=None, # No collaborative workers in direct smart command
                proposed_actions=result.get('actions', [])  # [PD-089]
            )
            if synth_result and synth_result.get('insight'):
                result['insight'] = synth_result['insight']
                result['_verification'] = synth_result.get('verification', {})

            # 2.6 Intercept for Auto-Learning
            learning = AILearningService.process_ai_response(result.get('insight', ''))

            # 3. Dispatch actions and log history via unified helper
            metadata = {
                "phase2": [{
                    "thought": result.get('thought') or result.get('insight', '')[:200] + "...",
                    "model": agent_cfg.entry.model_name if agent_cfg.entry else "Unknown"
                }],
                "phase3": list(all_rag_logs) if all_rag_logs else [],
                "phase4": [{"summary": "Smart command direct execution."}],
                "final_response": learning.get('text', ''),
                "learning": learning,
                "verification": result.get('_verification', {})
            }

            dispatch_res = AIAgentService._dispatch_actions(
                agent_id=agent_id,
                goal=f"Smart Command: {command_text}",
                insight=learning.get('text', ''),
                actions=result.get('actions', []),
                thread_id=thread_id,
                message_type='ai',
                metadata=metadata
            )

            return {
                "status": "success",
                "insight": learning.get('text', ''),
                "proposed_actions": dispatch_res['proposed'],
                "immediate_results": list(all_rag_logs) + dispatch_res['immediate_results'],
                "draft_job_ids": dispatch_res['draft_ids'],
                "history_id": dispatch_res['history_id'],
                "verification": result.get('_verification', {}),
                "learning_action": learning.get('payload') if learning.get('requires_action') else None,
                "learning_action_type": learning.get('action_type') if learning.get('requires_action') else None
            }

        except Exception as e:
            logger.exception(f"Error processing smart command: {command_text}")
            return {"status": "error", "message": str(e)}

    @staticmethod
    def run_agent_reasoning(agent_id, goal, collaborative=True, thread_id=None):
        """
        Orchestrates a reasoning cycle. If collaborative is True,
        it involves other agents based on the supervisor's discretion.
        """
        # Check if AI features are enabled
        from aot.databases.models import AIGlobalSettings
        ai_settings = AIGlobalSettings.query.first()
        if not ai_settings or not ai_settings.ai_enabled:
            return {"status": "error", "message": "AI features are disabled"}
        
        from aot.databases.models import AIAgent
        agent_cfg = AIAgent.query.filter_by(unique_id=agent_id).first()
        if not agent_cfg:
            return {"status": "error", "message": "Invalid agent"}

        # If the agent is a supervisor and collaboration is requested, use the collab flow
        if collaborative and agent_cfg.role == 'supervisor':
            return AIAgentService.run_collaborative_reasoning(agent_id, goal, thread_id=thread_id)

        engine = AIAgentService.get_engine(agent_id)
        if not engine:
            return {"status": "error", "message": "Engine initialization failed"}

        try:
            # 1. Observe
            tier = agent_cfg.model_tier if agent_cfg else 'standard'
            context = AIContextService.get_master_context(tier=tier)
            manifest = AIActionService.get_action_manifest(agent_unique_id=agent_id)
            full_history = AIAgentService.get_thread_history(thread_id)
            # [OPTION_D] Strip legacy action_type field from history
            history = [AIAgentService._strip_action_type_from_history(m) for m in full_history]

            # Combine for the engine
            full_context = {
                "system_state": context,
                "capabilities": manifest,
                "chat_history": history
            }
            # v26.9: Inject Situation Baseline
            AIAgentService._inject_situation_baseline(full_context)

            # 2. Reason
            result = engine.run_reasoning(full_context, goal)

            # 2.5 [P8] Normalize operate_device parameter schema to match MCP server inputSchema.
            # Maps AI-generated legacy params (valve_id → device_id, duration → state=on)
            # to the standard schema defined in 031_AI_MCP_USAGE_GUIDE.
            for _act in result.get('actions', []):
                if _act.get('params', {}).get('tool_name') == 'operate_device':
                    _args = _act.get('params', {}).get('arguments', {})
                    if 'valve_id' in _args and 'device_id' not in _args:
                        _args['device_id'] = _args.pop('valve_id')
                        logger.info("[P8] Normalized operate_device: valve_id → device_id")
                    if 'duration' in _args and 'state' not in _args:
                        _args['state'] = 'on'
                        logger.info("[P8] Normalized operate_device: duration present, defaulting state=on")
                    _act.get('params', {})['arguments'] = _args

            # 2.6 Intercept for Auto-Learning
            learning = AILearningService.process_ai_response(result.get('insight', ''))

            # 3. Dispatch actions and log history via unified helper
            dispatch_res = AIAgentService._dispatch_actions(
                agent_id=agent_id,
                goal=goal,
                insight=learning.get('text', ''),
                actions=result.get('actions', []),
                thread_id=thread_id,
                message_type='ai'
            )

            return {
                "status": "success",
                "history_id": dispatch_res['history_id'],
                "insight": learning.get('text', ''),
                "proposed_actions": dispatch_res['proposed'],
                "immediate_results": dispatch_res['immediate_results'],
                "draft_job_ids": dispatch_res['draft_ids'],
                "agent_name": engine.name,
                "role": agent_cfg.role,
                "learning_action": learning.get('payload') if learning.get('requires_action') else None,
                "learning_action_type": learning.get('action_type') if learning.get('requires_action') else None
            }

        except Exception as e:
            logger.exception(f"Error during agent reasoning: {agent_id}")
            return {"status": "error", "message": str(e)}

    # ------------------------------------------------------------------
    # v6 Pipeline: Planner (Execution Plan Generator)
    # ------------------------------------------------------------------

    @staticmethod
    def run_planner(intent, command_text, context, manifest, chat_history=None, stream=False):
        from aot.ai.services.ai_planning_service import AIPlanningService
        return AIPlanningService.run_planner(intent=intent, command_text=command_text, context=context, manifest=manifest, chat_history=chat_history, stream=stream)

    @staticmethod
    def _execute_action_chain(agent_id, plan, context, chat_history=None):
        from aot.ai.services.ai_planning_service import AIPlanningService
        return AIPlanningService._execute_action_chain(agent_id=agent_id, plan=plan, context=context, chat_history=chat_history)

    @staticmethod
    def _resolve_variables(params, variables):
        from aot.ai.services.ai_planning_service import AIPlanningService
        return AIPlanningService._resolve_variables(params=params, variables=variables)

    @staticmethod
    def run_collaborative_reasoning(supervisor_id, goal, thread_id=None, page_context=None, intent=None, router_insight=None, complexity=None):
        """
        Supervisor-led collaborative reasoning flow.
        v6: Attempts Planner → Executor → Synthesizer pipeline first,
        falls back to legacy Supervisor flow if pipeline agents not configured.

        Args:
            intent: Router classification result (e.g. 'CONTROL', 'DATA_QUERY')
            router_insight: Router's observation text (may contain useful sensor data)
        """
        from flask_babel import gettext as _
        supervisor_engine = AIAgentService.get_engine(supervisor_id)
        if not supervisor_engine:
            return {"status": "error", "message": "Supervisor engine failed"}

        try:
            # v6.1: Intent-based context filtering — load only relevant sections
            INTENT_CONTEXT_MAP = {
                'DATA_QUERY': ['spatial_hierarchy', 'sensor_readings', 'dashboards'],
                'CONTROL': ['spatial_hierarchy', 'sensor_readings', 'scheduled_tasks'],
                'SCHEDULE': ['spatial_hierarchy', 'scheduled_tasks', 'global_plans'],
                'COMPOSITE': None,  # Full context
                'CHAT': [],
            }
            include_keys = INTENT_CONTEXT_MAP.get(intent, None)
            from aot.databases.models import AIAgent
            supervisor_cfg = AIAgent.query.filter_by(unique_id=supervisor_id).first()
            tier = supervisor_cfg.model_tier if supervisor_cfg else 'standard'
            context = AIContextService.get_master_context(include_keys=include_keys, focused_target=page_context, tier=tier)
            manifest = AIActionService.get_action_manifest(agent_unique_id=supervisor_id)
            full_history = AIAgentService.get_thread_history(thread_id)
            # [OPTION_D] Strip legacy action_type field from history
            history = [AIAgentService._strip_action_type_from_history(m) for m in full_history]
            intent_override = intent  # v6: Passed from process_natural_language_command
            # v17.0: Using deque for O(1) performance and automatic size limiting
            all_rag_logs = deque(maxlen=MAX_RAG_LOGS)

            # Metadata initialization for Phase-based logging
            metadata = {
                "phase2": [],
                "phase3": [],
                "phase4": []
            }

            # @ANCHOR: FINAL_RESULT_INIT (TASK_9-A — UnboundLocalError fix)
            # Must be initialized before Planner branch references final_result.get('actions').
            final_result = {"insight": "", "actions": []}

            # v6: Try Planner first
            _pc097_retry_done = False
            # Pre-initialize chain variables so FIX-A/FIX-C guards outside the plan block can
            # safely reference them even if the plan block is not entered.
            chain_results: list = []
            chain_pending: list = []
            chain_outcomes: list = []
            plan = AIAgentService.run_planner(
                intent=intent_override,
                command_text=goal,
                context=context,
                manifest=manifest,
                chat_history=history,
                stream=False
            )

            if plan and plan.get('steps'):
                # @ANCHOR: MANDATORY_DISCOVERY_INJECTION (TASK_9-I)
                # Hard-coded safety check: if CONTROL/SCHEDULE intent, ensure Step 1 is discovery
                # with a non-empty query derived from the user goal.
                if intent_override in ('CONTROL', 'SCHEDULE'):
                    import re as _re
                    steps = plan.get('steps', [])
                    first_tool = steps[0].get('tool_name') if steps else None

                    # @ANCHOR: DEVICE_QUERY_EXTRACTION
                    # Pass the full goal as the fallback search query.
                    # search_devices() splits by whitespace and runs LIKE '%token%' per token,
                    # so device names embedded in longer commands (any language) are found correctly.
                    # No language-specific filtering here — the search layer handles tokenization.
                    _query = goal[:80]

                    if first_tool not in ['search_devices', 'get_device_list']:
                        logger.warning("[TASK_9-I][LBL] Injecting mandatory 'search_devices' at Step 0.")
                        new_step = {
                            "step_id": 0,
                            "tool_name": "search_devices",
                            "params": {"arguments": {"query": _query}},
                            "output_variable": "$device_info",
                            "purpose": "Mandatory physical discovery (Task 9-I injection)",
                            "depends_on": []
                        }
                        plan['steps'].insert(0, new_step)
                        # Ensure all subsequent steps depend on Step 0 (device discovery)
                        for _s in plan['steps']:
                            if _s['step_id'] != 0:
                                _deps = _s.get('depends_on', [])
                                if isinstance(_deps, str):
                                    _deps = [_deps]
                                if 0 not in _deps and '0' not in [str(d) for d in _deps]:
                                    _s['depends_on'] = [0] + list(_deps)
                    else:
                        # @ANCHOR: LBL_REPAIR_QUERY — Planner already placed search_devices first.
                        # (a) Repair empty/variable query. (b) Ensure output_variable + depends_on are set.
                        _existing_args = steps[0].get('params', {}).get('arguments', {})
                        _existing_query = str(_existing_args.get('query', ''))
                        if not _existing_query or _existing_query.startswith('$'):
                            logger.warning("[TASK_9-I][LBL] Repairing bad query on existing 'search_devices' Step 0: %r", _existing_query or 'EMPTY')
                            if 'params' not in steps[0]:
                                steps[0]['params'] = {}
                            if 'arguments' not in steps[0]['params']:
                                steps[0]['params']['arguments'] = {}
                            steps[0]['params']['arguments']['query'] = _query
                        # Ensure output_variable is set so DISCOVERY_GUARD can read the result
                        if not steps[0].get('output_variable'):
                            steps[0]['output_variable'] = '$device_info'
                        # Ensure subsequent steps depend on Step 0 (sequential execution)
                        _step0_id = steps[0].get('step_id', 0)
                        for _s in steps[1:]:
                            _deps = _s.get('depends_on', [])
                            if isinstance(_deps, str):
                                _deps = [_deps]
                            if _step0_id not in _deps and str(_step0_id) not in [str(d) for d in _deps]:
                                _s['depends_on'] = [_step0_id] + list(_deps)

                logger.info(f"[v6] Using Planner pipeline ({len(plan['steps'])} steps)")
                metadata["phase2"].append({
                    "agent": "Planner",
                    "thought": plan.get('insight', 'Generated execution plan'),
                    "model": "Planner Agent"
                })
                # v6 Execution: Run the action chain
                chain_results, chain_pending, chain_outcomes = AIAgentService._execute_action_chain(
                    agent_id=supervisor_id,
                    plan=plan,
                    context=context,
                    chat_history=history
                )

                # @ANCHOR: PC097_FEEDBACK_LOOP (TASK_9-F — enhanced sensitivity)
                # Detect PC-097 in chain_results via code, flag, or message keywords.
                _pc097_in_chain = any(
                    isinstance(r, dict) and (
                        r.get('error_code') == 'PC-097' or
                        r.get('requires_search') is True or
                        "Discovery Required" in str(r.get('message', '')) or
                        "PC-097" in str(r.get('message', ''))
                    )
                    for r in chain_results
                )
                if _pc097_in_chain and not _pc097_retry_done:
                    logger.warning("[TASK_9-D][PC097] PC-097 detected in chain. Re-invoking Planner with feedback.")
                    _pc097_retry_done = True
                    _feedback_context = dict(context)
                    _feedback_context['_pc097_feedback'] = (
                        "Previous plan failed: operate_device was called before search_devices. "
                        "PC-097 error: device UUID not in cache. "
                        "You MUST place search_devices as Step 1 in the new plan."
                    )
                    _retry_plan = AIAgentService.run_planner(
                        intent=intent_override,
                        command_text=goal,
                        context=_feedback_context,
                        manifest=manifest,
                        chat_history=history,
                        stream=False
                    )
                    if _retry_plan and _retry_plan.get('steps'):
                        logger.info("[TASK_9-D][PC097] Replanning succeeded. Re-running action chain.")
                        chain_results, chain_pending, chain_outcomes = AIAgentService._execute_action_chain(
                            agent_id=supervisor_id,
                            plan=_retry_plan,
                            context=context,
                            chat_history=history
                        )
                        plan = _retry_plan  # Update plan reference for downstream use
                    else:
                        logger.error("[TASK_9-D][PC097] Replanning failed. Falling through to legacy collaboration.")

                # [v28.0 Physical Guard] Verify the chain before the Synthesizer pass-gate.
                # pending_approval steps count as successful intent (approval required).
                #
                # @ANCHOR: CHAIN_STEP_OUTCOMES — judge on the structured outcomes, not on
                # the prose in chain_results. The old test was `'Success' in r`, which also
                # matches "Successfully ..." appearing anywhere in a step's serialized
                # result (e.g. a daemon message quoted inside a FAILED step's payload) —
                # so a chain in which every step failed could still be declared successful
                # and its false claim passed to the user.
                from aot.ai.services.ai_planning_service import CHAIN_OUTCOMES_OK
                _successful_steps = [o for o in chain_outcomes
                                     if o.get('outcome') in CHAIN_OUTCOMES_OK]
                _guard_extended = False
                synth_result = None
                if not _successful_steps:
                    logger.warning(
                        "[v6][PhysicalGuard] Zero successful steps in chain_results. "
                        "Skipping Synthesizer pass-gate to prevent false success claim."
                    )
                    all_rag_logs.extend(chain_results)
                    _guard_extended = True
                else:
                    # [APPROVAL_GATE] Merge pending control actions into proposed_actions
                    _proposed = chain_pending or final_result.get('actions', [])
                    if chain_pending:
                        logger.info(f"[APPROVAL_GATE] {len(chain_pending)} control action(s) pending approval: {[s.get('tool_name') or s.get('params', {}).get('tool_name') for s in chain_pending]}")
                        # @ANCHOR: APPROVAL_SKIP_SYNTH [2026-03-24]
                        # chain_pending is non-empty → approval gate at L1469 handles the return.
                        # Synthesizer output is unused in that path, so skip it to save ~3-5s latency.
                        # synth_result stays None; APPROVAL_GATE uses a static insight string.
                    else:
                        # @ANCHOR: SYNTH_SIMPLE_SKIP [2026-03-25]
                        # CONTROL/SCHEDULE + SIMPLE complexity: Synthesizer adds no value.
                        # Execution result is deterministic — use a structured template response.
                        _skip_synth = (
                            complexity == 'SIMPLE'
                            and intent_override in ('CONTROL', 'SCHEDULE')
                        )
                        if _skip_synth:
                            logger.info(f"[SYNTH_SIMPLE_SKIP] Skipping Synthesizer (intent={intent_override}, complexity=SIMPLE)")
                        else:
                            synth_result = AIAgentService.run_synthesizer(
                                execution_results=list(all_rag_logs) + chain_results,
                                intent=intent_override,
                                original_command=goal,
                                plan=plan,
                                chat_history=history,
                                proposed_actions=_proposed
                            )

                # v27.0 (Option C): Early return only when Planner explicitly marks
                # no_workers_needed=True. This prevents bypassing specialist workers
                # for goals that require expert analysis or cross-domain synthesis.
                if (synth_result and synth_result.get('verification', {}).get('passed')
                        and plan.get('no_workers_needed')):
                    learning = AILearningService.process_ai_response(synth_result.get('insight', ''))
                    # [P5] Reconstruct phase3/phase4 metadata before early return
                    metadata["phase3"] = chain_results if chain_results else []
                    metadata["phase4"] = [{
                        "summary": synth_result.get('insight', 'Pipeline synthesis finalized.'),
                        "verification": synth_result.get('verification')
                    }]
                    metadata.update({"v6_pipeline": True, "verification": synth_result.get('verification')})

                    dispatch_res = AIAgentService._dispatch_actions(
                        agent_id=supervisor_id, goal=goal,
                        insight=learning.get('text', ''), actions=synth_result.get('actions', []),
                        thread_id=thread_id, message_type='ai',
                        metadata=metadata
                    )
                    # [APPROVAL_GATE] Merge chain_pending into proposed_actions so UI shows approval button
                    _v6_proposed = list(dispatch_res.get('proposed', []))
                    if chain_pending and not _v6_proposed:
                        _v6_proposed = chain_pending
                    return {
                        "status": "success", "insight": learning.get('text', ''),
                        "immediate_results": list(all_rag_logs) + chain_results,
                        "proposed_actions": _v6_proposed,
                        "history_id": dispatch_res['history_id'],
                        "v6_pipeline": True
                    }

                # @ANCHOR: SCHEDULE_FAST_EXIT  [2026-03-24]
                # SCHEDULE/CONTROL (scheduling path): if chain produced successful steps AND no
                # approval is pending, return immediately. Workers add no value for a scheduling
                # operation and only add latency.
                # CRITICAL: Do NOT fire when chain_pending is non-empty — schedule_device_control
                # intercepted logs contain 'schedule_device', which would set _chain_used_schedule=True
                # and skip APPROVAL_GATE, causing the approval button to never appear.
                # @ANCHOR: CHAIN_STEP_OUTCOMES — same reasoning as PhysicalGuard above:
                # match on the step's tool/action_type, not on the whole log line. The
                # old scan read the serialized payload too, so any step whose result
                # merely quoted "add_schedule" flipped this on.
                from aot.ai.services.ai_planning_service import STEP_OUTCOME_PENDING_APPROVAL
                _chain_used_schedule = any(
                    any(_s in (o.get('tool') or '') or _s in (o.get('action_type') or '')
                        for _s in ('schedule_device', 'add_schedule'))
                    and o.get('outcome') != STEP_OUTCOME_PENDING_APPROVAL
                    for o in chain_outcomes
                )
                if _successful_steps and (intent_override == 'SCHEDULE' or _chain_used_schedule) and not chain_pending:
                    _sched_insight = (synth_result.get('insight') if synth_result else None) or (
                        _("Scheduling completed.")
                    )
                    # @ANCHOR: SCHED_INSIGHT_SANITIZE — prevent raw JSON leak in Phase 4/5
                    _sched_insight = AIAgentService._sanitize_final_response(_sched_insight)
                    if not _sched_insight:
                        _sched_insight = _("Scheduling completed.")
                    learning = AILearningService.process_ai_response(_sched_insight)
                    metadata["phase3"] = chain_results if chain_results else []
                    metadata["phase4"] = [{"summary": _sched_insight}]
                    dispatch_res = AIAgentService._dispatch_actions(
                        agent_id=supervisor_id, goal=goal,
                        insight=learning.get('text', ''),
                        actions=synth_result.get('actions', []) if synth_result else [],
                        thread_id=thread_id, message_type='ai', metadata=metadata
                    )
                    logger.info("[SCHEDULE_FAST_EXIT] Returning early after successful schedule chain.")
                    return {
                        "status": "success", "insight": learning.get('text', ''),
                        "immediate_results": list(all_rag_logs) + chain_results,
                        "proposed_actions": dispatch_res.get('proposed', []),
                        "history_id": dispatch_res['history_id'],
                        "v6_pipeline": True
                    }

                # [APPROVAL_GATE] If physical control is pending approval, return early.
                # No need for legacy workers — the user needs to confirm the action.
                if chain_pending:
                    logger.info(f"[APPROVAL_GATE] Physical control pending approval — skipping legacy workers.")
                    _approval_insight = synth_result.get('insight') if synth_result else None
                    # @ANCHOR: APPROVAL_INSIGHT_SANITIZE — prevent raw JSON leak in Phase 4/5
                    if _approval_insight:
                        _approval_insight = AIAgentService._sanitize_final_response(_approval_insight)
                    if not _approval_insight:
                        _pending_tool = chain_pending[0].get('tool_name') or chain_pending[0].get('params', {}).get('tool_name', 'operate_device')
                        _approval_insight = _("Action requires your approval before execution.")
                    learning = AILearningService.process_ai_response(_approval_insight)
                    metadata["phase3"] = chain_results if chain_results else []
                    metadata["phase4"] = [{"summary": _approval_insight}]
                    dispatch_res = AIAgentService._dispatch_actions(
                        agent_id=supervisor_id, goal=goal,
                        insight=learning.get('text', ''), actions=chain_pending,
                        thread_id=thread_id, message_type='ai', metadata=metadata
                    )
                    return {
                        "status": "success", "insight": learning.get('text', ''),
                        "immediate_results": list(all_rag_logs) + chain_results,
                        "proposed_actions": dispatch_res.get('proposed', chain_pending),
                        "history_id": dispatch_res['history_id'],
                        "v6_pipeline": True
                    }

                # @ANCHOR: APPROVAL_PENDING_GUARD_BEFORE_FALLBACK  [2026-03-27]
                # If APPROVAL_GATE intercepted steps, chain_pending is non-empty.
                # Do NOT fall back to legacy Supervisor — set guard flag so FIX-C
                # (LEGACY_SUPERVISOR_CONTROL_BYPASS) returns the approval response directly.
                if chain_pending:
                    _guard_extended = True  # suppress legacy fallback

                # If pipeline verification failed or workers are needed, fall back to legacy collaboration flow
                logger.warning("[v6] Pipeline synthesis incomplete or workers required. Falling back to legacy collaboration.")
                # v17.0: deque extend works the same way
                if not _guard_extended:
                    all_rag_logs.extend(chain_results)


            # v6: Include Router's observation as baseline context
            if router_insight:
                add_limited_rag_log(all_rag_logs, f"Router Observation: {router_insight}", 'default')

            # 1. Dispatch: Select Relevant Workers (legacy flow, enhanced by plan if available)
            # v23.0: Skip worker collaboration for simple CHAT intent to save tokens
            if intent == 'CHAT':
                logger.info("[Collaboration] Skipping worker phase for CHAT intent.")
                worker_insights = []
            else:
                from aot.databases.models import AIAgent
                all_workers = AIAgent.query.filter_by(role='worker', is_activated=True).all()
                if not all_workers:
                    worker_insights = []
                else:
                    # Ask supervisor which workers are needed
                    planned_worker_ids = AIAgentService._select_relevant_workers(supervisor_engine, goal, all_workers)
                    logger.info(f"[Collaboration] Supervisor selected {len(planned_worker_ids)} relevant workers: {planned_worker_ids}")
                    
                    workers_to_call = [w for w in all_workers if w.unique_id in planned_worker_ids]
                    worker_insights = []

                    for i, w in enumerate(workers_to_call):
                        # Throttle to avoid 429 Resource Exhausted on free-tier APIs
                        if i > 0:
                            _RATE_LIMITER.acquire()

                        # Determine context needed for this worker based on specialty
                        spec = (w.specialty or '').lower()
                        include_keys = ['spatial_hierarchy', 'global_plans'] # Core minimum
                        
                        if 'aot' in spec and ('sensor' in spec or 'device' in spec or 'hierarchy' in spec):
                            include_keys += ['sensor_readings', 'input_energy_summary', 'scheduled_tasks']
                        elif 'energy' in spec or 'power' in spec:
                            include_keys += ['input_energy_summary', 'sensor_readings', 'scheduled_tasks']
                        elif 'geo' in spec or 'map' in spec or 'spatial' in spec or 'gis' in spec:
                            include_keys += ['geo_designs', 'semantics', 'dashboards']
                        elif 'camera' in spec or 'vision' in spec or 'image' in spec:
                            include_keys += ['cameras', 'semantics']
                        elif 'agronomy' in spec or 'plant' in spec or 'soil' in spec or 'environment' in spec or 'weather' in spec:
                            include_keys += ['sensor_readings', 'supply_resource_summary', 'scheduled_tasks', 'domain_glossary']
                        elif 'time-series' in spec or 'data' in spec or 'influx' in spec or 'grafana' in spec:
                            include_keys += ['sensor_readings', 'dashboards']
                        else:
                            # Default: Moderate context
                            include_keys += ['sensor_readings', 'scheduled_tasks', 'semantics']

                        w_engine = AIAgentService.get_engine(w.unique_id)
                        if w_engine:
                            # v12.5: Force strict contextual isolation for workers
                            # spatial_hierarchy is enough for identity. Only add specific data.
                            w_tier = w.model_tier if w else 'standard'
                            w_context = AIContextService.get_master_context(include_keys=include_keys, tier=w_tier)
                            
                            # Truncate internal worker-brain context if it grows too large
                            w_full_context = {
                                "system_state": w_context,
                                "chat_history": (history[-2:] if history else []) # Last 2 rounds of global memory only
                            }
                            w_goal = f"Analyze your specialty ({w.specialty}) perspective for goal: {goal}"

                            # Worker mini-RAG loop: execute tool calls and re-reason (max 2 rounds)
                            try:
                                w_result = w_engine.run_reasoning(w_full_context, w_goal)
                            except Exception as e:
                                logger.error(f"[Collaboration] Worker {w.name} failed: {e}")
                                w_result = {"insight": f"Error: {str(e)}", "actions": []}
                            for _rag_round in range(2):
                                w_actions = w_result.get('actions', [])
                                w_rag = [a for a in w_actions if a.get('action_type') in ['virtual_tool_call', 'mcp_tool_call', 'read_manual', 'knowledge_search', 'get_detailed_manifest', 'mcp_resource_read', 'mcp_prompt_get']]
                                if not w_rag:
                                    break
                                logger.info(f"[Collaboration] Worker {w.name} RAG round {_rag_round+1}: {[a.get('action_type') for a in w_rag]}")
                                rag_results = []
                                for a in w_rag:
                                    try:
                                        # v21.0: P1 Metadata Validation
                                        valid, err = AIAgentService._validate_and_normalize_action(a)
                                        if not valid:
                                            rag_results.append(f"Validation Error: {err}")
                                            # [P6] Unify worker logs into global all_rag_logs
                                            add_limited_rag_log(all_rag_logs, f"[Worker:{w.name}] Validation Error: {err}", 'default')
                                            continue

                                        res = AIActionService.execute_action(a['action_type'], a.get('target_id'), a.get('params'))
                                        # [001_WEATHER_LOGIC_UPGRADE] Weather-aware truth tagging
                                        if a.get('action_type') == 'virtual_tool_call':
                                            from aot.ai.services.ai_routing_service import AIRoutingService as _ARS
                                            _base = _ARS.format_weather_tool_result(a, res)
                                            log_msg = f"[Worker:{w.name}] {_base}"
                                        else:
                                            log_msg = f"[Worker:{w.name}] Tool '{a.get('params', {}).get('tool_name', a['action_type'])}' result: {json.dumps(res, ensure_ascii=False, default=str)[:2000]}"
                                        rag_results.append(log_msg)
                                        # [P6] Unify worker logs into global all_rag_logs
                                        add_limited_rag_log(all_rag_logs, log_msg, a['action_type'])
                                    except Exception as e:
                                        err_msg = f"[Worker:{w.name}] Tool failed: {str(e)}"
                                        rag_results.append(err_msg)
                                        # [P6] Unify worker logs into global all_rag_logs
                                        add_limited_rag_log(all_rag_logs, err_msg, 'default')
                                if 'chat_history' not in w_full_context:
                                    w_full_context['chat_history'] = []
                                w_full_context['chat_history'].append({"role": "assistant", "content": json.dumps(w_rag, ensure_ascii=False)})
                                w_full_context['chat_history'].append({"role": "user", "content": "Tool results:\n" + "\n".join(rag_results) + "\n\nNow provide your final analysis based on these results."})
                                try:
                                    w_result = w_engine.run_reasoning(w_full_context, w_goal)
                                except Exception as e:
                                    logger.error(f"[Collaboration] Worker {w.name} RAG re-reasoning failed: {e}")
                                    w_result = {"insight": f"Error: {str(e)}", "actions": []}
                                    break

                            insight = w_result.get('insight', '')
                            
                            # If any worker hits a rate limit, auth error, or API error, stop and move to synthesis
                            is_rate_limited = any(kw in insight for kw in ["Resource exhausted", "한도를 초과", "429"])
                            is_auth_error = any(kw in insight for kw in ["API key not valid", "API_KEY_INVALID", "INVALID_ARGUMENT", "401", "403"])

                            if is_auth_error:
                                logger.warning(f"Worker {w.name} failed with auth error (API key invalid/missing). Skipping this worker.")
                                worker_insights.append({
                                    "agent_name": w.name,
                                    "specialty": w.specialty,
                                    "insight": f"(API key configuration error - please check the agent's AI Service settings)"
                                })
                                continue  # Skip this worker but try others (auth issue is per-agent, not global)

                            if is_rate_limited:
                                logger.error(f"Worker {w.name} failed with persistent rate limit (429/Quota) after retries. Stopping further collaboration.")
                                worker_insights.append({
                                    "agent_name": w.name,
                                    "specialty": w.specialty,
                                    "insight": "(Quota exceeded - all retries failed. Please wait or upgrade your API tier.)"
                                })
                                break  # Hard break as quota is shared

                            worker_insight_entry = {
                                "agent_name": w.name,
                                "specialty": w.specialty,
                                "insight": insight
                            }
                            worker_insights.append(worker_insight_entry)
                            metadata["phase4"].append(worker_insight_entry)

            # 2. Synthesize: Supervisor evaluates all insights
            full_history = AIAgentService.get_thread_history(thread_id)
            # [OPTION_D] Strip legacy action_type field from history
            history = [AIAgentService._strip_action_type_from_history(m) for m in full_history]
            # [System knowledge] FIRST key so it survives base_ai's tail-truncation
            # (see fast_path note). Same authoritative registered-inventory block, so
            # escalated system questions answer from learned knowledge. Cached.
            _sk_text = ""
            try:
                from aot.ai.services import system_knowledge_service as _sk
                _sk_text = _sk.get_knowledge_text()
            except Exception as _sk_err:
                logger.debug(f"[Collab] system_knowledge injection skipped: {_sk_err}")
            collab_context = {}
            if _sk_text:
                collab_context["system_knowledge"] = _sk_text
            collab_context.update({
                "system_state": context,
                "capabilities": manifest,
                "chat_history": history, # Injected memory
                "worker_perspectives": worker_insights,
                "page_context": page_context,
                "current_time": get_local_now().strftime("%Y-%m-%d %A %H:%M:%S %Z (UTC%z)")
            })
            # [Conversation memory] Recently-controlled devices in this thread, so
            # "모두 꺼줘 / turn them off" targets what was just acted on.
            from aot.ai.services import intent_resolver as _ir
            _recent_dev = _ir.recent_controlled_devices(thread_id)
            if _recent_dev:
                collab_context["recently_controlled_devices"] = _recent_dev

            # v26.9: Inject Situation Baseline for Supervisor
            AIAgentService._inject_situation_baseline(collab_context, page_context)

            # [Capability grounding] Mirror the fast-path manual injection here: a
            # DATA_QUERY how-to answered with zero tool calls escalates to this full
            # path, so the supervisor also needs the manual to cite real menu paths
            # instead of inventing them. Flag-gated; '' when off / no match.
            #
            # intent None is included (2026-07-19): auto-dispatch reaches this
            # path with intent_override=None for unclassified requests, and a
            # knowledge question arriving that way was synthesized with NO
            # grounding at all — observed live: the model answered "no such
            # data is registered" about a user_confirmed library item. An
            # unclassified request may be exactly such a knowledge question;
            # the directive already self-gates ("use it ONLY when...") so
            # injecting for None risks nothing but a few grounded tokens.
            # CONTROL and other explicit non-DATA_QUERY intents stay excluded.
            _manual_directive = ""
            _collab_short_followup = len((goal or '').strip()) < 8 and len(history) > 0
            if intent_override in ('DATA_QUERY', None) and not _collab_short_followup:
                _mref = AIAgentService._manual_grounding(goal)
                if _mref:
                    # FRONT placement — same truncation-survival reason as the
                    # fast path; see _inject_context_front.
                    collab_context = AIAgentService._inject_context_front(
                        collab_context, 'manual_reference', _mref)
                    _manual_directive = AIAgentService._MANUAL_GROUNDING_DIRECTIVE

            max_rag_loops = 3
            rag_loop_count = 0
            # [P6] Worker RAG logs already accumulated in all_rag_logs; no reset here

            # @ANCHOR: LEGACY_SUPERVISOR_CONTROL_BYPASS  [2026-03-27]
            # Defense-in-depth: if intent is CONTROL and APPROVAL_GATE intercepted steps,
            # skip the legacy Supervisor entirely — it would generate its own search_devices plan
            # with no visibility into the Planner's pending_actions, overriding the correct output.
            # chain_pending is pre-initialized to [] so this guard is always safe to evaluate.
            if intent_override == 'CONTROL' and chain_pending:
                logger.info(f"[LEGACY_SUPERVISOR_CONTROL_BYPASS] Skipping legacy Supervisor: "
                            f"CONTROL intent with {len(chain_pending)} pending approval action(s).")
                _bypass_insight = _("Action requires your approval before execution.")
                _bypass_learning = AILearningService.process_ai_response(_bypass_insight)
                metadata["phase3"] = chain_results if chain_results else []
                metadata["phase4"] = [{"summary": _bypass_insight}]
                _bypass_dispatch = AIAgentService._dispatch_actions(
                    agent_id=supervisor_id, goal=goal,
                    insight=_bypass_learning.get('text', ''), actions=chain_pending,
                    thread_id=thread_id, message_type='ai', metadata=metadata
                )
                return {
                    "status": "success",
                    "insight": _bypass_learning.get('text', ''),
                    "immediate_results": list(all_rag_logs) + (chain_results if chain_results else []),
                    "proposed_actions": _bypass_dispatch.get('proposed', chain_pending),
                    "history_id": _bypass_dispatch['history_id'],
                    "v6_pipeline": True
                }

            while rag_loop_count < max_rag_loops:
                try:
                    final_result = supervisor_engine.run_reasoning(
                        collab_context,
                        f"GOAL: {goal}\n\n"
                        # @ANCHOR: COORDINATOR_GATEKEEPER (TASK_9-J — physical integrity audit)
                        "INSTRUCTIONS:\n"
                        "1. Analyze the user's goal considering the WORKER PERSPECTIVES provided.\n"
                        "2. CRITICAL: Check 'chat_history' first. If the user says something like 'check again', 'tell me more', or uses pronouns like 'it/that/this', they are referring to the PREVIOUS conversation. You MUST resolve these references using chat_history context.\n"
                        "2b. SHORT-IMPERATIVE CONTINUATION: If the user's message is a short imperative such as "
                        "'안내해줘', '알려줘', '계속', 'continue', 'go ahead', 'do it', they are asking you to DELIVER "
                        "what the immediately previous turn promised or was analyzing — continue THAT exact topic "
                        "(e.g. the valve operation analysis just discussed). Do NOT treat it as a new or general "
                        "request, and do NOT reply with a generic system introduction. If the previous turn "
                        "promised an analysis, actually perform it now (call the needed tool) instead of promising again.\n"
                        "3. If the goal requires historical data or information not in 'system_state', you MUST use 'mcp_tools' (e.g., Grafana query_series) to fetch it.\n"
                        "4. NOTE: 'system_state' sensor readings are only the LATEST (~1hr). For any 'X hours ago' or 'yesterday' queries, use tools with a fuzzy RANGE.\n"
                        "5. If a worker hit a rate limit (Quota exceeded), do not assume data is missing. Try to use a tool yourself if you have access.\n"
                        "6. After tool execution, you will be given the results. Do not say data is missing if tools are available to find it.\n"
                        "7. [OPTION_D] Respond with JSON containing 'insight' and 'actions'.\n"
                        "   SCHEMA: { \"insight\": \"...\", \"actions\": [ { \"tool_name\": \"...\", \"params\": {} } ] }\n"
                        "   STRICT: No 'action_type' or 'target_id' field. The system derives them from tool_name.\n"
                        "8. [COORDINATOR_GATEKEEPER] Physical Integrity Audit: Before claiming success for any CONTROL/ACTION goal, "
                        "reconcile the Planner's original intent against the Tool Execution Logs in 'worker_perspectives'. "
                        "If the logs do not confirm the intended physical action was executed, do NOT claim success.\n"
                        "9. [COORDINATOR_GATEKEEPER] Physical Evidence Requirement: A CONTROL response is only valid if "
                        "execution results contain a 'physical_outcome' field confirming the action. "
                        "If 'physical_outcome' is absent or not 'success', report failure — do NOT fabricate a success response.\n"
                        "10. [COORDINATOR_GATEKEEPER] No JSON Leaks: Your 'insight' field MUST be plain natural language. "
                        "NEVER include raw JSON objects, metadata keys, tool call structures, or system-internal fields in the insight text.\n"
                        "11. [STRICT_JSON] You MUST respond with a single, valid JSON object. Do NOT include any text before or after the JSON. "
                        "If you are unsure, provide a simple 'insight' and an empty 'actions' list."
                        + _manual_directive
                    )
                    
                    # v26.9: Robust JSON Parsing for Supervisor
                    if isinstance(final_result, dict) and (final_result.get('_parse_failed') or final_result.get('status') == 'error'):
                        _raw = final_result.get('raw_response', '')
                        if _raw:
                            try:
                                # Try to extract JSON from code blocks or loose text
                                import json as _json
                                _match = _re.search(r'(\{.*\})', _raw, _re.DOTALL)
                                if _match:
                                    _json_str = _match.group(1)
                                    _parsed = _json.loads(_json_str)
                                    if 'insight' in _parsed:
                                        logger.info("[v26.9] Recovered Supervisor JSON via regex.")
                                        final_result = _parsed
                                        final_result['_parse_failed'] = False
                                        final_result['status'] = 'success'
                            except Exception as _je:
                                logger.warning(f"[v26.9] JSON recovery failed: {str(_je)}")

                    # v20.0: Automatic Fallback for Supervisor Errors
                    if final_result.get('status') == 'error':
                        logger.warning(f"[SupervisorFallback] Primary supervisor ({supervisor_id}) failed: {final_result.get('error_code')}. Attempting fallback...")
                        
                        # Find another 'heavy' or 'standard' tier agent
                        alt_supervisor = AIAgent.query.filter(
                            AIAgent.is_activated == True,
                            AIAgent.unique_id != supervisor_id,
                            AIAgent.model_tier.in_(['heavy', 'standard'])
                        ).first()
                        
                        if alt_supervisor:
                            alt_engine = AIAgentService.get_engine(alt_supervisor.unique_id)
                            if alt_engine:
                                logger.info(f"[SupervisorFallback] Retrying with alternative: {alt_supervisor.unique_id}")
                                final_result = alt_engine.run_reasoning(collab_context, f"GOAL: {goal}\n(Fallback Mode)")
                                # If fallback still fails, return original error or try again? 
                                # Let's stop after one fallback to avoid loops.
                except Exception as e:
                    logger.error(f"[Collaboration] Supervisor reasoning failed: {e}")
                    # v12.5 Fallback: Try to synthesize with what we have
                    from flask_babel import gettext as _
                    final_result = {"status": "error", "insight": _("Sorry, the service is unstable and could not generate a response. Please try again shortly.") + f" (Error: {str(e)})", "actions": []}
                    break
                
                all_actions = final_result.get('actions', [])
                # Filter for RAG-safe actions (informational only) that are also considered immediate.
                # [P4] Block physical control tools in RAG phase — must pass Phase 4/5 approval gates.
                # [RAG-FIX] Check both params.tool_name AND top-level tool_name to catch un-normalized actions.
                from aot.ai.services.resolvers.constants import PHYSICAL_TOOLS as _PHYS2
                def _is_phys2(a):
                    t = a.get('params', {}).get('tool_name') or a.get('tool_name', '')
                    return t in _PHYS2
                rag_actions = [a for a in all_actions
                               if a.get('action_type', '').lower() in ['read_manual', 'knowledge_search', 'get_detailed_manifest', 'mcp_tool_call', 'virtual_tool_call', 'mcp_resource_read', 'mcp_prompt_get']
                               and not _is_phys2(a)]
                
                if not rag_actions:
                    break
                    
                rag_loop_count += 1
                logger.info(f"Auto-RAG loop {rag_loop_count} executing actions: {rag_actions}")
                
                rag_results = []
                for a in rag_actions:
                    try:
                        # v21.0: P1 Metadata Validation
                        valid, err = AIAgentService._validate_and_normalize_action(a)
                        if not valid:
                            add_limited_rag_log(all_rag_logs, f"Validation Error: {err}", 'default')
                            continue

                        res = AIActionService.execute_action(a['action_type'], a.get('target_id'), a.get('params'))
                        # [001_WEATHER_LOGIC_UPGRADE] Weather-aware truth tagging
                        if a.get('action_type') == 'virtual_tool_call':
                            from aot.ai.services.ai_routing_service import AIRoutingService as _ARS
                            log_msg = _ARS.format_weather_tool_result(a, res)
                        else:
                            log_msg = f"Auto-RAG Action '{a['action_type']}' Output:\n{json.dumps(res, ensure_ascii=False)}"
                        rag_results.append(log_msg)
                        add_limited_rag_log(all_rag_logs, log_msg, a['action_type'])
                    except Exception as e:
                        err_msg = f"Auto-RAG Action '{a['action_type']}' Failed:\n{str(e)}"
                        rag_results.append(err_msg)
                        add_limited_rag_log(all_rag_logs, err_msg, 'default')

                collab_context['chat_history'].append({
                    "role": "assistant",
                    "content": "Executing search: " + json.dumps(rag_actions, ensure_ascii=False)
                })
                collab_context['chat_history'].append({
                    "role": "user",
                    "content": "System Execution Result (TRUTH SOURCE):\n" + "\n".join(rag_results) + "\n\nBased on this TRUTH SOURCE, please fulfill my original request. If these real-time values differ from the 'system_state' provided earlier, you MUST trust these latest execution results."
                })
                
                # Cleanup handled actions — keep control actions for approval
                # [TASK_37] operate_device must survive this filter
                _CTRL_KEEP = {'operate_device', 'output_on', 'output_off', 'set_output', 'control_output'}
                final_result['actions'] = [
                    a for a in all_actions
                    if a.get('action_type') not in ['read_manual', 'knowledge_search', 'get_detailed_manifest', 'mcp_tool_call', 'virtual_tool_call', 'mcp_resource_read', 'mcp_prompt_get']
                    or a.get('params', {}).get('tool_name') in _CTRL_KEEP
                    or a.get('tool_name') in _CTRL_KEEP
                ]
            
            # 2.5 v6 Synthesizer: Verify and refine the response
            synth_result = AIAgentService.run_synthesizer(
                execution_results=all_rag_logs,
                intent=intent_override,
                original_command=goal,
                chat_history=history,
                worker_insights=worker_insights, # v25.0: Preserve detail
                proposed_actions=final_result.get('actions', [])  # [PD-089]
            )
            if synth_result and synth_result.get('insight'):
                # Synthesizer produced a verified response — use it
                final_result['insight'] = synth_result['insight']
                final_result['_verification'] = synth_result.get('verification', {})
                if not synth_result.get('_parse_failed'):
                    final_result.pop('_parse_failed', None)  # Clear only when Synthesizer itself succeeded
                logger.info(f"[v6] Synthesizer verified response. Passed: {synth_result.get('verification', {}).get('passed')}")

            # P2: Graceful fallback when Supervisor JSON parsing failed and Synthesizer did not recover
            if final_result.get('_parse_failed'):
                if worker_insights:
                    worker_summary = "\n".join(
                        f"- [{w.get('agent_name', 'Worker')}] {w.get('insight', '')}"
                        for w in worker_insights
                        if w.get('insight')
                    )
                    final_result['insight'] = _("Intent parsing failed. Providing worker insights:") + f"\n{worker_summary}"
                    logger.warning("[v6] Supervisor parse failed. Compiled response from worker insights.")
                else:
                    # @ANCHOR: SUPERVISOR_PARSE_CLARIFY — structured CLARIFY instead of hardcoded failure
                    final_result['intent'] = 'CLARIFY'
                    final_result['_routing_reason'] = 'ROUTING_FAILED'
                    final_result['insight'] = _("I couldn't process your request properly. Please try rephrasing your command.")
                    logger.warning("[v6] Supervisor parse failed and no worker insights available. Returning CLARIFY response.")

            # 2.6 Intercept for Auto-Learning
            # [TASK_41] Guard: extract inner insight — handles JSON wrapper, markdown fence, embedded JSON
            _raw_collab = final_result.get('insight', '')
            _collab_insight = _extract_clean_insight(_raw_collab)
            if _collab_insight != _raw_collab:
                final_result['insight'] = _collab_insight
                logger.warning("[TASK_41] Extracted clean insight from raw LLM output in collaboration path.")
            # [031_STEP_2] Final response sanitizer — strip JSON leaks and Router Observation strings
            _collab_sanitized = AIAgentService._sanitize_final_response(_collab_insight)
            if _collab_sanitized != _collab_insight:
                _collab_insight = _collab_sanitized
                final_result['insight'] = _collab_insight
                logger.warning("[031_STEP_2] Sanitizer applied to collaborative reasoning insight.")
            # [Citation trust] Server-side disclosure guard — same contract as the
            # fast path; see _enforce_unconfirmed_disclosure.
            _collab_disclosed = AIAgentService._enforce_unconfirmed_disclosure(
                _collab_insight, collab_context.get('manual_reference'))
            if _collab_disclosed != _collab_insight:
                _collab_insight = _collab_disclosed
                final_result['insight'] = _collab_insight
            learning = AILearningService.process_ai_response(_collab_insight)

            # 3. Dispatch actions and log history via unified helper
            metadata["phase2"].append({
                "thought": final_result.get('thought') or final_result.get('insight', '')[:200] + "...",
                "model": supervisor_engine.name if hasattr(supervisor_engine, 'name') else "Supervisor"
            })
            metadata["phase3"] = list(all_rag_logs) if all_rag_logs else []
            metadata.update({
                "final_response": learning.get('text', ''),
                "collaboration": worker_insights,
                "verification": final_result.get('_verification', {})
            })
            if not metadata["phase4"]:
                metadata["phase4"].append({
                    "summary": f"Coordinated {len(worker_insights)} workers." if worker_insights else "Direct supervision."
                })

            # [APPROVAL_GATE] Merge chain_pending (physical control) so legacy flow shows approval button
            _legacy_actions = list(final_result.get('actions', []))
            _chain_pending_ref = locals().get('chain_pending', []) or []
            if _chain_pending_ref:
                _existing_tool_names = {
                    a.get('params', {}).get('tool_name') or a.get('tool_name', '')
                    for a in _legacy_actions
                }
                for _cp in _chain_pending_ref:
                    _cp_tool = _cp.get('tool_name') or _cp.get('params', {}).get('tool_name', '')
                    if _cp_tool not in _existing_tool_names:
                        _legacy_actions.append(_cp)
                        logger.info(f"[APPROVAL_GATE] Merged chain_pending '{_cp_tool}' into legacy dispatch actions.")

            # [DATA_QUERY is read-only] Mirror the fast-path guard: an info / how-to
            # answer must never carry an approval action. DATA_QUERY has no physical
            # action by definition — if the supervisor attached one (e.g. a
            # register_device on "how do I add a sensor?"), drop it so no phantom
            # "Approve Action" button appears. Physical/registration actions belong
            # to CONTROL / SCHEDULE / FUNCTION_CREATE intents.
            if intent_override == 'DATA_QUERY' and _legacy_actions:
                logger.info(
                    f"[Collab][DATA_QUERY_READONLY] Dropping {len(_legacy_actions)} "
                    f"non-data action(s) from a read-only DATA_QUERY answer "
                    f"(types={[a.get('action_type') for a in _legacy_actions]})."
                )
                _legacy_actions = []

            dispatch_res = AIAgentService._dispatch_actions(
                agent_id=supervisor_id,
                goal=goal,
                insight=learning.get('text', ''),
                actions=_legacy_actions,
                thread_id=thread_id,
                message_type='ai',
                metadata=metadata
            )

            # v16.8: Store in Semantic Cache (Phase 18 PoC)
            # v17.0: Using ThreadSafeLRUCache with automatic eviction
            try:
                clean_goal = goal.strip().lower()
                # LRU cache now handles size management automatically
                _SEMANTIC_CACHE[clean_goal] = {
                    "insight": learning.get('text', ''),
                    "actions": final_result.get('actions', []),
                    "intent": intent_override,
                    "agent_id": supervisor_id
                }
                logger.debug(f"[SemanticCache] Stored result for: '{clean_goal}'")
            except Exception:
                pass

            return {
                "status": "success",
                "history_id": dispatch_res['history_id'],
                "insight": learning.get('text', ''),
                "proposed_actions": dispatch_res['proposed'],
                "immediate_results": list(all_rag_logs) + dispatch_res['immediate_results'],
                "draft_job_ids": dispatch_res['draft_ids'],
                "agent_name": supervisor_engine.name,
                "role": "supervisor",
                "collaboration": worker_insights,
                "verification": final_result.get('_verification', {}),
                "learning_action": learning.get('payload') if learning.get('requires_action') else None,
                "learning_action_type": learning.get('action_type') if learning.get('requires_action') else None
            }

        except Exception as e:
            logger.exception(f"Error during collaborative reasoning: {supervisor_id}")
            return {"status": "error", "message": str(e)}

    @staticmethod
    def _select_relevant_workers(supervisor_engine, goal, active_workers):
        """
        v23.0: Selects relevant workers using a hybrid approach:
        1. Fast keyword matching to prune the list.
        2. LLM-based selection from the pruned list.
        """
        if not active_workers:
            return []
            
        goal_lower = goal.lower()
        
        # 1. Fast Keyword Search (Pre-filter)
        # Mapping common goal keywords to specialty patterns
        KEYWORD_MAP = {
            'gis': ['gis', 'map', 'spatial', 'geo', 'location', '지도', '위치', 'gis'],
            'weather': ['weather', 'environment', 'agronomy', 'plant', 'soil', '날씨', '기상', '환경', '토양'],
            'energy': ['energy', 'power', 'consumption', 'electricity', '에너지', '전력'],
            'data': ['data', 'grafana', 'influx', 'time-series', 'history', '데이터', '이력', '시계열'],
            'aot': ['aot', 'sensor', 'device', 'hierarchy', 'system', 'expert', '전문가', '장치', '센서'],
            'excel': ['excel', 'report', 'sheet', 'csv', '엑셀', '보고서']
        }
        
        candidates = []
        for w in active_workers:
            spec = (w.specialty or '').lower()
            name = (w.name or '').lower()
            # If any keyword in goal matches any keyword in worker's specialty mapping
            is_potential = False
            for goal_kw, worker_patterns in KEYWORD_MAP.items():
                if goal_kw in goal_lower:
                    if any(p in spec or p in name for p in worker_patterns):
                        is_potential = True
                        break
            
            # Special case: 'aot' expert is a broad fallback for many AoT questions
            if not is_potential and ('sensor' in goal_lower or 'device' in goal_lower or 'status' in goal_lower):
                if 'aot' in spec:
                    is_potential = True
            
            if is_potential:
                candidates.append(w)
        
        # If pre-filter found too few or no candidates, use all workers as candidates for the LLM to decide
        # But if total workers > 10, let's keep it pruned to avoid token blast.
        if not candidates:
            # If no candidates found by keyword, maybe the query is complex.
            # Only use all workers if the list is reasonably small.
            if len(active_workers) <= 5:
                candidates = active_workers
            else:
                # Still try to prune or just use 5 random? 
                # Let's use a very small subset of 'General' or 'System' agents.
                candidates = [w for w in active_workers if 'aot' in (w.specialty or '').lower() or 'expert' in (w.specialty or '').lower()][:3]
        
        if not candidates:
            return []

        worker_list_str = "\n".join([f"- ID: {w.unique_id}, Name: {w.name}, Specialty: {w.specialty}" for w in candidates])
        
        prompt = (
            f"GOAL: \"{goal}\"\n\n"
            "Analyze the GOAL and select the unique_ids of AI workers needed to fulfill it.\n"
            "PRIORITY RULES:\n"
            "1. If it involves sensor data, device status, or AoT hierarchy: select the 'AoT System Expert'.\n"
            "   DATA_FIRST (TASK_7_8): For weather/environmental queries, ALWAYS try AoT System Expert (Local DB) FIRST.\n"
            "   Only escalate to GIS Expert (External API) if Local DB returns no data or is unavailable.\n"
            "2. If it involves external data (weather, maps, energy APIs): select the specific expert.\n"
            "3. If the goal is simple chat: select NONE.\n"
            "Return ONLY a JSON list of strings (IDs)."
            f"\n\nAVAILABLE WORKERS:\n{worker_list_str}"
        )
        
        try:
            result = supervisor_engine.run_reasoning({}, prompt)
            insight = result.get('insight', '')
            import re
            match = re.search(r'\[.*\]', insight, re.DOTALL)
            if match:
                ids = json.loads(match.group(0))
                valid_ids = [w.unique_id for w in candidates]
                return [wid for wid in ids if wid in valid_ids]
        except Exception as e:
            logger.error(f"[Collaboration] Worker selection failed: {e}")
            
        # Fallback v23.0: Empty instead of all to prevent token waste
        return []

    @staticmethod
    def execute_all_logged_actions(history_id):
        """Batch approval: execute EVERY action in a history record. Runs each via
        execute_logged_action (so per-action normalization + safety gates all apply),
        and returns {status, results:[...], executed, failed} for the UI to reflect.
        Lets the user approve many devices with one click instead of N."""
        from aot.databases.models import AIHistory
        history = AIHistory.query.filter_by(unique_id=history_id).first()
        if not history:
            return {"status": "error", "message": "History record not found"}
        try:
            actions = json.loads(history.actions_json or '[]')
        except Exception:
            actions = []
        if not actions:
            return {"status": "error", "message": "No actions to execute"}
        results, ok = [], 0
        for i in range(len(actions)):
            try:
                r = AIAgentService.execute_logged_action(history_id, i)
            except Exception as e:
                r = {"status": "error", "message": str(e)}
            results.append(r if isinstance(r, dict) else {"status": "error"})
            if isinstance(r, dict) and r.get('status') == 'success':
                ok += 1
        return {
            "status": "success" if ok > 0 else "error",
            "results": results,
            "executed": ok,
            "failed": len(actions) - ok,
            "message": f"{ok}/{len(actions)} executed",
        }

    @staticmethod
    def execute_logged_action(history_id, action_index):
        """
        Executes a specific action from a history entry.
        Validates through SafetyService before execution.

        [031_STEP_1] action_index may be:
          - int   → legacy positional index (fallback)
          - str   → _action_uuid for stable UUID-based lookup (preferred)
        """
        from aot.databases.models import AIHistory  # @ANCHOR: AIHISTORY_LOCAL_IMPORT
        history = AIHistory.query.filter_by(unique_id=history_id).first()
        if not history:
            return {"status": "error", "message": "History record not found"}

        try:
            actions = json.loads(history.actions_json)

            # @ANCHOR: UUID_BASED_ACTION_LOOKUP
            # Prefer UUID lookup (stable across re-indexing) over positional index.
            action = None
            if isinstance(action_index, str) and len(action_index) == 36 and '-' in action_index:
                # action_index is actually a UUID → find by _action_uuid field
                action = next((a for a in actions if a.get('_action_uuid') == action_index), None)
                if action is None:
                    return {"status": "error", "message": f"Action UUID '{action_index}' not found in history"}
            else:
                # Legacy integer index path
                idx = int(action_index)
                # @ANCHOR: CHAIN_RESULTS_SAFETY_GUARD (TASK_9-H — negative index crash fix)
                # Guard against both out-of-range (positive) and negative indices.
                # Negative indices bypass the '>= len' check but still cause IndexError on empty lists,
                # or silently return the wrong action on non-empty lists.
                if idx < 0 or idx >= len(actions):
                    return {"status": "error", "message": "Action index out of bounds"}
                action = actions[idx]
            action_type = action.get('action_type')
            target_id = action.get('target_id')
            params = action.get('params', {})

            # [Option D] action_type 누락 시 tool_name으로 재파생 (LLM이 스키마 따른 경우).
            # Also re-run when action_type IS already 'mcp_tool_call': a stored action can
            # have a WRONG-but-present target_id (e.g. the model invented 'virtual_mcp' for
            # a tool that is actually virtual_tool_call) — the TASK_38 fallback below only
            # catches a MISSING target_id, not a wrong one, so this must run first to give
            # _validate_and_normalize_action's VIRTUAL_TOOL_MISCLASSIFY_FIX a chance (same
            # gap fixed in AIDispatchService._dispatch_actions, 2026-07-19).
            if not action_type or action_type == 'mcp_tool_call':
                AIAgentService._validate_and_normalize_action(action)
                action_type = action.get('action_type')
                target_id = action.get('target_id')
                params = action.get('params', {})

            if not action_type:
                return {"status": "error", "message": "Missing action_type in history"}

            # [TASK_38] Fallback: mcp_tool_call stored without target_id → re-resolve via _resolve_action_route
            if action_type == 'mcp_tool_call' and not target_id:
                tool_name = params.get('tool_name') or action.get('tool_name')
                if tool_name:
                    _rerouted = AIAgentService._resolve_action_route(action, None)
                    if _rerouted and _rerouted.get('target_id'):
                        action_type = _rerouted['action_type']
                        target_id = _rerouted['target_id']
                        params = _rerouted['params']
                        logger.info(f"[TASK_38] execute_logged_action: re-resolved target_id='{target_id}' for '{tool_name}'")
                    else:
                        logger.error(f"[TASK_38] execute_logged_action: could not resolve target_id for '{tool_name}'")

            # Safety validation before execution
            try:
                SafetyService.validate(action_type, target_id, params)
            except SafetyViolation as sv:
                logger.warning(f"Safety violation blocked action: {sv}")
                return {"status": "error", "message": f"Safety violation: {sv}"}

            # [TASK_5][PC-089-GATE] This path is the human-confirmed execution path.
            # _approved=True unlocks PhysicalControlResolver for physical tools.
            result = AIActionService.execute_action(action_type, target_id, params, _approved=True)

            # [PB-086] Honest Execution Recording (Law 3 + Law 6)
            _exec_success = result.get('status') == 'success'
            if _exec_success:
                history.status = 'executed'
                _evidence = result.get('result', result)
                history.execution_result = json.dumps(_evidence, ensure_ascii=False)[:1000]
                logger.info(f"[PB-086] Action {action_index} executed. Evidence: {history.execution_result[:200]}")
            else:
                history.status = 'failed'
                _err = result.get('message', str(result))
                history.execution_result = f"[EXECUTION FAILED] {_err}"
                logger.error(f"[PB-086] Action {action_index} FAILED: {_err}")
            history.save()

            # [023_STEP_5][AUDIT_TRAIL] Update corresponding AITask with physical execution outcome.
            # Matches by action_type + target_id on proposed/in_progress tasks.
            try:
                _task = AITask.query.filter(
                    AITask.action_type == action_type,
                    AITask.target_id == target_id,
                    AITask.status.in_(['proposed', 'in_progress'])
                ).order_by(AITask.created_at.desc()).first()
                if _task:
                    _task.status = 'completed' if _exec_success else 'failed'
                    _phys = result.get('physical_outcome', 'success' if _exec_success else 'failed')
                    _outcome_str = json.dumps(result.get('result', result), ensure_ascii=False)[:800] if _exec_success \
                        else result.get('message', str(result))[:800]
                    _task.execution_result = f"[physical_outcome={_phys}] {_outcome_str}"
                    _task.save()
                    logger.info(
                        f"[023_STEP_5][AUDIT_TRAIL] AITask {_task.unique_id} "
                        f"updated: status={_task.status}, physical_outcome={_phys}"
                    )
                else:
                    logger.debug(
                        f"[023_STEP_5][AUDIT_TRAIL] No proposed AITask found for "
                        f"{action_type}/{target_id} — skipping audit update."
                    )
            except Exception as _audit_err:
                logger.warning(f"[023_STEP_5][AUDIT_TRAIL] Non-fatal: could not update AITask: {_audit_err}")

            # [TASK_B] Surface execution evidence for frontend and AI pipeline awareness
            _is_physical = action_type in ('mcp_tool_call', 'virtual_tool_call', 'output_on', 'output_off')
            result['_execution_evidence'] = {
                'execution_confirmed': _exec_success,
                'mcp_used': _is_physical,
                'physical_outcome': result.get('physical_outcome', 'success' if _exec_success else 'failed'),
                'history_id': history_id,
                'executed_at': datetime.utcnow().isoformat() + 'Z',
            }

            # NOTE: A synchronous goal-continuation call used to run here (Phase B-2),
            # but it made the approve request hang ("Executing…") on a heavy re-reasoning
            # call and was redundant when the model already BATCHES the goal's actions
            # into one proposal (the common "밸브1 켜고 밸브4도 켜줘" case). Multi-action
            # goals are handled by batching + a message that names ALL actions
            # (_control_proposal_message). True sequential continuation, if needed, must
            # run ASYNC — not inline in the approve path.

            return result
        except Exception as e:
            logger.exception(f"Error executing logged action: {history_id}")
            return {"status": "error", "message": str(e)}

    # Future-action "I'll do it" promises the model emits instead of answering
    # (the recurring meta-stall). Multilingual, high-precision. Used to detect a
    # non-answer so we can force a direct synthesis.
    _STALL_MARKERS = (
        '불러오겠', '확인하겠', '조회하겠', '분석하겠', '정리하겠', '안내해 드리겠',
        '안내하겠', '파악하겠', '검색하겠', '잠시만', '기다려',
        # note/memo creation promises — "노트를 생성하겠습니다" without a tool call
        '생성하겠', '작성하겠', '기록하겠', '남기겠', '남겨두겠', '저장하겠',
        "i'll ", 'i will ', 'let me ', 'please wait', 'one moment', 'fetching', 'loading',
        'をします', 'いたします', 'お待ち',
    )
    # Inventory / "what do I have" questions answerable straight from system_knowledge
    # (no tool needed). High-precision multilingual pre-filter so we only short-circuit
    # these — NOT sensor-data queries like "current temperature".
    _INVENTORY_MARKERS = (
        '장치 목록', '장치목록', '등록된 장치', '등록 장치', '조회 가능한 장치', '조회할 수 있는 장치',
        '어떤 장치', '무슨 장치', '함수 목록', '구역 목록', '뭐가 있', '무엇이 있', '뭐 있',
        '내 장치', '가진 장치',
        'list my device', 'list device', 'what device', 'my devices', 'registered device',
        'what do i have', 'inventory', 'list function', 'list zone', 'show device',
    )
    @staticmethod
    def _looks_like_stall(text):
        """True if `text` is a short future-action promise rather than an answer."""
        if not text:
            return True
        low = text.strip().lower()
        if len(low) < 12:
            return True
        return any(m in text or m.lower() in low for m in AIAgentService._STALL_MARKERS)

    # ---- Phase B-2: goal continuation (post-approval) --------------------------
    # Markers that a request is a MULTI-STEP goal — sequence/conjunction words or
    # "all/every". Single-device single-action commands lack these and are NOT
    # continued, so the common case keeps its exact current behavior (no friction).
    _MULTISTEP_MARKERS = (
        '그리고', '그다음', '그 다음', '다음에', '이어서', '그런 다음', '한 뒤', '한 후', '후에',
        '모두', '전부', '다 켜', '다 꺼', '순차', '차례',
        ' then ', 'and then', 'after that', 'one by one', 'sequentially', 'all of',
    )
    _GOAL_CONT_MAX_DEPTH = 4

    @staticmethod
    def _goal_continuation_enabled():
        """Reuses the goal-loop flag. Fails safe to False."""
        try:
            from aot.databases.models import AIGlobalSettings
            s = AIGlobalSettings.query.first()
            return bool(s and getattr(s, 't1_goal_loop_enabled', False))
        except Exception:
            return False

    @staticmethod
    def _is_multistep_goal(command):
        """True only for genuinely multi-step goals (see markers). Keeps the common
        single-action control OUT of the continuation loop entirely."""
        if not command:
            return False
        low = command.lower()
        if any(m in command or m.lower() in low for m in AIAgentService._MULTISTEP_MARKERS):
            return True
        # Two or more distinct registered Output names named in one command
        # (e.g. "밸브1과 밸브2 켜줘") is also multi-step.
        try:
            from aot.databases.models import Output
            hits = 0
            for o in Output.query.all():
                nm = (o.name or '').strip()
                if nm and nm in command:
                    hits += 1
                    if hits >= 2:
                        return True
        except Exception:
            pass
        return False

    @staticmethod
    def _continue_goal(history, executed_action, depth):
        """After a physical step of a multi-step goal executes, ask the PROVEN
        pipeline for the next step toward the goal. Returns a continuation dict
        {message, actions, history_id} if a next proposal was produced, else None
        (goal complete / nothing to do). Reuses process_natural_language_command so
        continuation control is exactly as stable as a normal control request."""
        goal = history.goal
        desc = (executed_action.get('description') or executed_action.get('display_summary')
                or (executed_action.get('params', {}) or {}).get('tool_name')
                or executed_action.get('tool_name') or 'the action')
        cont_cmd = (
            f"[CONTINUE_GOAL] Original goal: {goal}\n"
            f"You have just completed: {desc} (result: success).\n"
            "If the goal is now FULLY achieved, reply that it is complete and propose NO action. "
            "If more steps remain to achieve the goal, perform ONLY the single next step now "
            "(propose the next control action). Do not repeat a step already completed."
        )
        res = AIAgentService.process_natural_language_command(
            agent_id='auto', command_text=cont_cmd, thread_id=history.thread_id)
        pa = res.get('proposed_actions') or []
        if not pa:
            return None  # goal complete / no further action
        # Stamp continuation depth on the new proposal's history so the NEXT
        # continuation is bounded (prevents runaway if the model never says done).
        try:
            from aot.databases.models import AIHistory
            nh = AIHistory.query.filter_by(unique_id=res.get('history_id')).first()
            if nh:
                _m = json.loads(nh.metadata_json or '{}') or {}
                _m['goal_step'] = depth + 1
                nh.metadata_json = json.dumps(_m)
                nh.save()
        except Exception:
            pass
        return {"message": res.get('insight'), "actions": pa, "history_id": res.get('history_id')}

    # @ANCHOR: intent interceptors — MOVED to aot/ai/services/intent_resolver.py
    # (architecture Phase 2). Was ~400 lines here (_recent_controlled_devices,
    # _is_recent_control_reference, _is_vague_device_control, _command_has_location,
    # _is_function_create_request, _infer_function_type, the proposal builders, and
    # their keyword-table data). Entry point now calls intent_resolver.resolve().

    @staticmethod
    def _resolve_control_device_id(action, command_text):
        """Return a valid Output UUID for a control action, resolving it
        DETERMINISTICALLY from the device NAME (in the action's own hints first,
        then the user command) when the model's device_id is missing, invalid, or a
        planner-style placeholder ($x.results[0].id).

        This is the Phase-B foundation: rather than trusting the LLM's multi-step
        reasoning to carry a concrete UUID (unstable — it emitted unresolved
        variables in Phase A), the system resolves 'name → UUID' itself, so control
        is robust regardless of what the model produces. Returns None if no
        registered Output name matches — the caller then escalates."""
        from aot.databases.models import Output
        p = action.get('params', {}) or {}
        _args = p.get('arguments', {}) if isinstance(p.get('arguments'), dict) else {}
        did = p.get('device_id') or _args.get('device_id') or action.get('target_id')
        # Already a concrete, existing UUID? keep it.
        if (isinstance(did, str) and len(did) == 36 and '-' in did
                and '$' not in did and '.results[' not in did):
            try:
                if Output.query.filter_by(unique_id=did).first():
                    return did
            except Exception:
                pass
        # Resolve by longest registered-Output-name substring match. Action-specific
        # hints first (so a multi-device request resolves each action to its own
        # valve), then the command text.
        try:
            outputs = Output.query.all()
        except Exception:
            return None

        def _match(text):
            tl = (text or '').lower()
            if not tl:
                return None
            best, best_len = None, 0
            for o in outputs:
                nm = (o.name or '').strip()
                if nm and nm.lower() in tl and len(nm) > best_len:
                    best, best_len = o, len(nm)
            return best

        for src in (action.get('display_summary'), action.get('name'),
                    p.get('device_name'), p.get('name'),
                    _args.get('device_name'), _args.get('name'), command_text):
            o = _match(src)
            if o:
                return o.unique_id
        return None

    @staticmethod
    def _is_inventory_question(text):
        """True if the command is a 'what do I have / list my devices' inventory
        question (answerable from system_knowledge alone). Multilingual heuristic."""
        if not text:
            return False
        low = text.lower()
        return any(m in text or m.lower() in low for m in AIAgentService._INVENTORY_MARKERS)

    @staticmethod
    def _manual_grounding(command_text):
        """Authoritative manual/knowledge sections for a capability, how-to, or
        domain (crop/pest/environment) query, or ''.

        Measurement showed that leaving doc-consultation to the model is
        unreliable: for "센서 추가 방법" the agent variably guessed a wrong
        read_manual filename, only announced "I'll search", or answered from
        imagination ("기기 관리" — a menu that does not exist; the real path is
        "설정 -> 입력"). So we retrieve the relevant sections SERVER-SIDE
        (deterministic, no LLM/tokens) and inject them as ground truth, instead
        of depending on which tool the model picks. Flag-gated
        (t3_knowledge_search_enabled); '' when off or nothing matches.

        Since Phase 6 (knowledge digest), knowledge_search's index also
        includes registered AI Library knowledge (documents/web sources,
        pre-digested at sync time) when knowledge_digest_enabled is on — so
        this same server-side retrieval covers both "how do I use this menu"
        and "what's the recommended humidity for this crop" without any
        further changes here. Library knowledge is farm-wide (the AI Library
        is a flat catalog — the former per-source facility_id gate was
        removed along with the library's site picker); relevance is decided
        by knowledge_search's keyword scoring alone (optionally narrowed by
        tags — not yet wired in here, see docs/design/ai-library-redesign.md
        §11.3 — entity/tag scoping is deferred past this call site for now).

        search_as_text() tags each library hit by provenance ('[권위]' /
        '[Library]' / '[관측]' / '[AI 정리 — 미확인]') so
        _MANUAL_GROUNDING_DIRECTIVE can tell the model to cite an
        authoritative source differently from its own unreviewed note.
        """
        try:
            from aot.databases.models import AIGlobalSettings
            s = AIGlobalSettings.query.first()
            if not (s and getattr(s, 't3_knowledge_search_enabled', False)):
                return ''
            from aot.ai.services import knowledge_search as _ks
            _ref = _ks.search_as_text(command_text, top_k=3) or ''
            if _ref:
                # INFO on purpose (not debug): during live verification the
                # grounding's fate was undiagnosable from logs — retrieval ran
                # silently, then the model answered "no data" and there was no
                # way to tell whether injection happened, was truncated away,
                # or was never called on that path. One line per grounded
                # request makes the injection observable end-to-end.
                logger.info(f"[ManualGrounding] injected {_ref.count('###')} section(s), {len(_ref)} chars")
            return _ref
        except Exception as e:
            logger.debug(f"[ManualGrounding] skipped: {e}")
            return ''

    @staticmethod
    def _inject_context_front(ctx, key, value):
        """Insert `key` at the FRONT of a context dict (right after
        system_knowledge if present) and return the rebuilt dict.

        base_ai serializes the context in dict-insertion order and
        HARD-TRUNCATES the prompt tail at the tier budget (100k chars) — so a
        key appended at the end can be silently cut on a large install.
        Verified live (2026-07-19): a 195k fast-path prompt was truncated to
        100k and the tail-appended manual_reference (plus every instruction
        after it) never reached the model, which then answered "no data
        exists" about knowledge the library demonstrably held — the exact
        '동작하는 척' failure the AI-library redesign was built to close.
        system_knowledge already solved this for itself with FIRST-key
        placement; this helper generalizes that pattern instead of each
        injection re-discovering the trap. system_knowledge deliberately
        stays ahead of `key`: it is the device-inventory ground truth and
        the longest-standing front-load contract."""
        out = {}
        if 'system_knowledge' in ctx:
            out['system_knowledge'] = ctx['system_knowledge']
        out[key] = value
        for k, v in ctx.items():
            if k not in ('system_knowledge', key):
                out[k] = v
        return out

    # Appended server-side by _enforce_unconfirmed_disclosure — module constant
    # so the "already disclosed?" check and the tests reference one string.
    _UNCONFIRMED_DISCLOSURE = (
        "\n\n※ 위 답변의 일부는 AI가 자체 기록해 둔 미확인 메모를 근거로 합니다. "
        "아직 사람이 확인하지 않은 정보이니 참고용으로 활용해 주세요."
    )

    # Korean glues grammar onto the END of a content word ('압력이'/'압력은',
    # '안정되기까지'/'안정되는'), so whole-word comparison misses an answer that
    # states the same fact in different clothes. Particles and the everyday
    # endings are a CLOSED class, which is why stripping a recognized one is
    # safe in a way that cutting every word to a fixed length is not: truncation
    # would also collapse '관리기' and '관리자' onto '관리' and disclose an
    # answer that never touched the note. A morphological analyzer would do this
    # properly and isn't available — AoT ships in 22 languages and can't take a
    # Korean-only runtime dependency for a presentation guard. Anything this
    # list doesn't know simply stays whole, i.e. degrades to the old behaviour.
    _KO_SUFFIXES = tuple(sorted({
        # 조사 (nouns)
        '은', '는', '이', '가', '을', '를', '에', '의', '도', '만', '와', '과',
        '로', '나', '랑', '께', '에서', '에게', '한테', '으로', '로써', '로서',
        '보다', '처럼', '까지', '부터', '마다', '조차', '밖에', '라도', '든지',
        '만큼', '대로', '와의', '과의', '에는', '에도', '에서는', '에서도',
        '으로는', '으로도', '에게서', '이라고', '라고는', '까지는', '부터는',
        # 용언 어미 (verbs/adjectives)
        '된', '된다', '되는', '되어', '되며', '되고', '되기', '됩니다', '되었다',
        '되기까지', '되었습니다', '한다', '하는', '하고', '하며', '하면', '하여',
        '하지', '해서', '해야', '했다', '합니다', '했습니다', '하기까지',
        '임', '함', '이다', '이며', '이고', '이나', '이란', '이라', '이라는',
        '입니다', '있다', '있는', '없다', '없는', '있습니다', '없습니다',
    }, key=len, reverse=True))

    # A suffix that would leave less than this isn't a suffix here — it's part
    # of the word. This is what keeps '관로', '온도', '결로' (which merely END
    # in the particles 로/도) from being filed away as '관', '온', '결'.
    _KO_MIN_STEM = 2

    # Words that are pure grammar even after stripping. A hit on them says
    # nothing about WHICH section an answer came from, and they are the words
    # most likely to sit in the unconfirmed block alone by accident — which is
    # all "distinctive" means here. Two wordy texts overlap on these no matter
    # what they are about, which is enough to clear the word-only threshold.
    _DISCLOSURE_STOP_WORDS = frozenset({
        '있습니다', '없습니다', '합니다', '입니다', '됩니다', '같습니다', '것으로',
        '되어', '하기', '때문', '때문에', '경우', '따라', '따라서', '또는',
        '그리고', '그러나', '그래서', '하지만', '통해', '위해', '대한', '대해',
        '정도', '다시', '다만', '이런', '그런', '저런', '이렇게', '그렇게',
    })

    @staticmethod
    def _grounding_block_text(block):
        """One grounding block with the provenance parenthetical dropped from
        its '### ' header ('… 관로 압력 안정 시간  (AI 자율 비치 — 대화
        2026-08-24)'). The title stays — an answer really can quote it — but
        the parenthetical is shelving bookkeeping, and its date digits are
        unique to the unconfirmed block, so they would count as a distinctive
        number match against any answer that happens to mention 24."""
        return '\n'.join(
            re.sub(r'\s*\([^)]*\)\s*$', '', line) if line.startswith('### ') else line
            for line in block.split('\n'))

    @staticmethod
    def _enforce_unconfirmed_disclosure(insight, manual_ref):
        """Deterministic post-guard for the citation-trust contract
        (docs/design/ai-library-redesign.md §6): when the final answer
        demonstrably draws on an '[AI 정리 — 미확인]' grounding section but
        doesn't disclose that, append the disclosure server-side.

        The prompt directive already ORDERS the model to disclose ("you MUST
        tell the user this is your own prior unconfirmed note"), but
        compliance proved model-dependent — verified live (2026-07-19):
        flash-lite answered from an unconfirmed shelved note with
        "...확인되었습니다", presenting the AI's own unreviewed memo as
        established fact. Trust presentation is a §3 contract, so it gets the
        same treatment retrieval got in P2: enforced server-side, not left to
        whichever model is configured.

        "Draws on" is decided by DISTINCTIVE-token overlap: tokens that
        appear in the unconfirmed section(s) but in NO other grounding
        section, matched against the answer. A same-topic answer sourced
        from an authoritative section therefore doesn't trigger (its tokens
        are not distinctive to the unconfirmed block). Conservative
        threshold — a number match (the typical payload of a shelved
        observation: '45초', '30%') plus corroborating words, or a strong
        word-overlap alone. Never raises; on any error returns the insight
        unchanged (this is a presentation guard, not allowed to break the
        response path).

        Tokens are compared as STEMS — particle/ending stripped — rather
        than as whole words (measured 2026-08-24).
        Whole-word containment let Korean inflection walk straight through
        the guard: a note saying '관로 압력이 안정되기까지 약 45초' and an
        answer saying '관로 압력은 약 45초 뒤 안정되는 것으로 확인되었습니다'
        state the same fact, yet only '관로' matched — '압력이'/'압력은' and
        '안정되기까지'/'안정되는' both missed, the answer landed one word
        short of the threshold, and it shipped with no disclosure at all.
        That is the exact failure this guard exists to stop. Stemming cuts
        both ways on purpose: the same reduction is applied when subtracting
        the other sections, so a word the authoritative section also uses
        cancels out however either side inflected it — which is what keeps
        the looser match from turning into looser triggering. The threshold
        is therefore unchanged."""
        try:
            if not insight or not manual_ref or '[AI 정리 — 미확인]' not in manual_ref:
                return insight
            low = insight.lower()
            if '미확인' in insight or 'unconfirmed' in low:
                return insight  # model already disclosed on its own

            import re as _re
            unconf_parts, other_parts = [], []
            for block in manual_ref.split('\n\n---\n\n'):
                # The tag lives on the block's '### ' section-header line — which
                # is NOT the block's first line for the first section, because
                # search_as_text glues its "[Knowledge search: ...]" preamble
                # onto that block.
                header = next((l for l in block.split('\n') if l.startswith('### ')), '')
                (unconf_parts if '[AI 정리 — 미확인]' in header else other_parts).append(
                    AIAgentService._grounding_block_text(block))
            unconf_text = ' '.join(unconf_parts)
            other_text = ' '.join(other_parts)

            def _tokens(text):
                # Bracketed spans are the injector's own furniture — the trust
                # tag itself and search_as_text's "[Knowledge search: ...]"
                # preamble. They sit only in the retrieved text, so left in they
                # read as evidence distinctive to the unconfirmed block ('정리'
                # would match any answer that says '정리하면').
                text = _re.sub(r'\[[^\]]*\]', ' ', text)
                # A number is evidence only together with what it counts: '90%'
                # in the note and '90일' in the answer are not the same fact,
                # and a bare number is the one thing loose enough to clear the
                # threshold on its own. Captured as (value, first unit char).
                nums = set(_re.findall(r'(\d+(?:\.\d+)?)\s*([%℃가-힣A-Za-z]?)', text))
                # Split hangul and latin runs apart so a particle glued to a
                # latin term ('VPD가', 'EC는') doesn't hide the term.
                words = set(_re.findall(r'[가-힣]{2,}|[A-Za-z]{2,}', text))
                return nums, words

            def _stem(word):
                if not ('가' <= word[0] <= '힣'):
                    return word.lower()
                for suf in AIAgentService._KO_SUFFIXES:
                    if word.endswith(suf):
                        stem = word[:-len(suf)]
                        return stem if len(stem) >= AIAgentService._KO_MIN_STEM else word
                return word

            def _stems(words):
                out = set()
                for w in words:
                    if w in AIAgentService._DISCLOSURE_STOP_WORDS:
                        continue
                    st = _stem(w)
                    if st not in AIAgentService._DISCLOSURE_STOP_WORDS:
                        out.add(st)
                return out

            u_nums, u_words = _tokens(unconf_text)
            o_nums, o_words = _tokens(other_text)
            a_nums, a_words = _tokens(insight)
            a_stems = _stems(a_words)
            # Cancel by value alone — if any other section states this number,
            # it isn't the unconfirmed block's to give away, whatever unit
            # either of them attached to it.
            _o_values = set(n for n, _ in o_nums)
            distinct_nums = set((n, u) for n, u in u_nums if n not in _o_values)
            distinct_words = _stems(u_words) - _stems(o_words)

            # Numbers match as whole tokens: '45' must not be read out of the
            # answer's '450'. Stems match either way round INSIDE a word, which
            # is what absorbs Korean compounding — '밸브' is written into
            # '급수밸브' with no space — and any ending this module doesn't know,
            # where one side ends up stripped further than the other.
            num_hits = sorted(
                n for n, unit in distinct_nums
                if any(n == a_n and (not unit or not a_unit or unit == a_unit)
                       for a_n, a_unit in a_nums))
            word_hits = sorted(
                w for w in distinct_words
                if any(w in a or a in w for a in a_stems))
            drew_on_it = (num_hits and len(word_hits) >= 2) or len(word_hits) >= 5
            if not drew_on_it:
                return insight

            logger.info(
                f"[UnconfirmedDisclosure] appended (num_hits={num_hits[:3]}, "
                f"word_hits={len(word_hits)}) — model cited an unconfirmed note without disclosure."
            )
            return insight + AIAgentService._UNCONFIRMED_DISCLOSURE
        except Exception as e:
            logger.debug(f"[UnconfirmedDisclosure] skipped: {e}")
            return insight

    # Prompt directive paired with an injected 'manual_reference' block. Tells the
    # model the docs/knowledge are ALREADY provided (so it stops announcing "I'll
    # search") and to answer from them, citing the source — the fix for the
    # invented-menu-path hallucination, generalized to non-manual knowledge too.
    #
    # Each library entry is tagged by provenance+trust_state
    # (knowledge_search._PROVENANCE_TAG / _AI_CURATED_TRUST_TAG,
    # docs/design/ai-library-redesign.md §6) — the tags carry different trust
    # and must be cited differently, otherwise an AI's own unreviewed note
    # reads to the user with the same authority as RDA's official setpoints.
    # ai_curated has THREE tag variants (P5) because its trust changes after
    # write — a human confirming it (or it auto-corroborating via reuse)
    # moves it off "미확인" without changing what it's cited as forever.
    _MANUAL_GROUNDING_DIRECTIVE = (
        "\nKNOWLEDGE GROUNDING [authoritative — already retrieved for you]: 'manual_reference' in the "
        "context holds documentation sections and/or registered domain-knowledge excerpts that MAY be "
        "relevant. Use it ONLY when the user is genuinely asking what the system can do, how to do "
        "something, or a domain question (crop/livestock/structure/environment) that registered "
        "knowledge covers; if their message is a continuation of the prior conversation, follow "
        "CONVERSATION CONTINUITY instead. When you do use it: for a system how-to entry, ANSWER "
        "DIRECTLY and cite the exact page / menu path it states (e.g. '설정 -> 입력'); for a "
        "'[권위]'-tagged entry, state it as an authoritative fact and cite the source shown after "
        "the dash; for a '[Library]'-tagged entry, cite the source name in parentheses; for a "
        "'[관측]'-tagged entry, present it as an observation from this operation's own data, not a "
        "general rule; for an '[AI 정리 — 출처 …, 미확인]'-tagged entry, you transcribed it from a "
        "source this system actually has (the source is named in the tag): cite that "
        "source by name, and say it has not been reviewed yet — but do NOT call it your "
        "own guess, because it is checkable; "
        "for an '[AI 정리 — 미확인]'-tagged entry, you MUST tell the user this is your "
        "own prior unconfirmed note (not a verified source) before using it, and prefer a "
        "'[권위]'/'[Library]' entry over it if both cover the same point; for '[AI 정리 — 확인됨]', a "
        "person has reviewed and confirmed it — you may state it with the same confidence as "
        "'[Library]', but still note it originated from your own prior note if relevant; for "
        "'[AI 정리 — 교차검증됨]', it has held up over repeated use without dispute but no person has "
        "reviewed it — treat it as moderately trustworthy, between '[AI 정리 — 미확인]' and confirmed. "
        "Do NOT say you will search — this is already provided. Do NOT invent menu paths or figures "
        "not present in the provided text, and do NOT claim a feature or fact is unsupported if the "
        "provided text shows otherwise. "
        # Verified live (2026-07-19): without this clause, DATA_QUERY ENFORCEMENT
        # ("data retrieval REQUIRES a tool call") overrode this grounding for a
        # question whose answer sat verbatim in manual_reference — the model
        # hunted with read_manual/get_sensor_detail, failed, and finally
        # answered "no such data is registered". The two rules must have an
        # explicit precedence for the case where the knowledge is already here.
        "PRECEDENCE over DATA_QUERY ENFORCEMENT: if 'manual_reference' ALREADY CONTAINS the specific "
        "fact/value/duration the user is asking about, that IS the retrieved data — answer from it "
        "directly (with its citation tag) and do NOT call a retrieval tool for it; registered "
        "knowledge is not a live sensor reading. Only fall back to tools when manual_reference does "
        "not actually contain the asked-for answer."
    )

    @staticmethod
    def run_fast_path(command_text, intent='DATA_QUERY', thread_id=None, page_context=None,
                      max_rag_override=None, goal_directive=None):
        """
        v6.1 Fast Path: For SIMPLE queries, skip Planner/Worker/Synthesizer.

        Goal-loop hooks (backward-compatible; both default to current behavior):
          - max_rag_override: raise the autonomous read/RAG-loop budget so a
            goal that needs several discovery/read steps completes in one turn
            instead of stalling at the 2-loop cap.
          - goal_directive: extra prompt text framing the request as a GOAL to
            pursue autonomously (appended to the fast-path prompt).
        Uses mini context (no InfluxDB calls) + single LLM + RAG loop (max 2).
        Returns escalate status if AI cannot answer with available data.
        Hard timeout: 60 seconds.
        """
        import time as _time
        _fast_path_start = _time.monotonic()
        _FAST_PATH_TIMEOUT = 60  # seconds

        try:
            # [025_STEP_1] Pre-flight: verify physical tool availability for CONTROL intent.
            # Tool availability MUST be confirmed via MCPBridgeService before AI generates a response.
            # @ANCHOR: fast_path_mcp_preflight
            # @ANCHOR: APPROVAL_BYPASS_GUARD (TASK_7_8 Step 3)
            # TASK_7_8: Do NOT block the approval proposal stage when MCP health is unstable.
            # The HARDWARE_OFFLINE check is now a warning flag only — the LLM still generates
            # the proposal + display_summary. Physical execution is gated at PhysicalControlResolver
            # (PHYSICAL_APPROVAL_GATE), which is the correct enforcement point.
            _mcp_hardware_offline = False
            # @ANCHOR: EMERGENCY_FALLBACK (TASK_8 048 — Step 2)
            # MCP First Protocol: Fast Path is ONLY allowed as Emergency Fallback
            # when mcp_tool_call returns Timeout or ConnectionError.
            _emergency_fallback = False
            if intent == 'CONTROL':
                try:
                    from aot.ai.services.mcp_bridge_service import MCPBridgeService
                    from aot.ai.services.resolvers.constants import PHYSICAL_TOOLS as _PTOOLS
                    _active = MCPBridgeService.get_active_servers()
                    _physical_available = any(
                        t in _PTOOLS for s in _active for t in (s.tool_names or [])
                    )
                    if _physical_available:
                        logger.info(
                            "[MCP_PRIORITY_ACTIVE] CONTROL intent: MCP server with physical tools "
                            f"confirmed. MCP-first routing active (servers={[s.name for s in _active]})."
                        )
                    else:
                        # [TASK_8 052_] Hard Lock: CONTROL intents MUST escalate if MCP is offline.
                        # No text-only emergency fallback allowed for physical control.
                        logger.warning(
                            "[HARD_LOCK_ESCALATE] CONTROL intent: no active MCP server with physical "
                            "tools. Escalating to Full Path to prevent text-only bypass."
                        )
                        return {"status": "escalate", "reason": "MCP physical tools offline (Hard Lock)"}
                except Exception as _pf_err:
                    logger.error(f"[HARD_LOCK_ESCALATE] CONTROL pre-flight exception: {_pf_err}")
                    return {"status": "escalate", "reason": f"MCP pre-flight error: {_pf_err}"}

            # [PHASE 2.1] Optimized Agent Lookup (Shared Cache)
            # Prefer 'worker' pipeline_role; fall back to 'executor' (newer agent naming)
            worker = AIAgentService.get_cached_agent('worker') or AIAgentService.get_cached_agent('executor')
            if not worker:
                return {"status": "escalate", "reason": "No active worker/executor agent"}

            engine = AIAgentService.get_engine(worker.unique_id)
            if not engine:
                return {"status": "escalate", "reason": "Engine init failed"}

            # 2. Lightweight context — NO InfluxDB calls
            context = AIContextService.get_mini_context(intent=intent)
            manifest = AIActionService.get_action_manifest(agent_unique_id=worker.unique_id, is_slim=True, intent=intent)
            
            # v6.2: History Trimming for Fast Path (last 3 messages)
            full_history = AIAgentService.get_thread_history(thread_id)
            # [OPTION_D] Strip legacy action_type field from history
            history = [AIAgentService._strip_action_type_from_history(m) for m in full_history]
            # Keep enough turns that a short follow-up ('안내해줘', 'tell me more')
            # can be resolved against what was just discussed. 3 was too shallow —
            # a 2-question exchange plus the follow-up already exceeds it.
            history = history[-6:] if history else []

            # [System knowledge] Standing, authoritative inventory of the user's
            # registered devices/functions/zones — cached, rebuilt ≤daily and on any
            # system change. Lets the AI answer "what do I have" from LEARNED
            # knowledge instead of re-investigating or reciting the creatable_* catalog.
            # MUST be the FIRST context key: base_ai serializes the whole context to
            # JSON and HARD-TRUNCATES the tail at the tier budget (100k). The manifest
            # (capabilities) is huge, so anything appended AFTER it is cut off — the
            # reason an end-of-context injection was silently dropped and the AI
            # stalled. Front placement survives truncation.
            _sk_text = ""
            try:
                from aot.ai.services import system_knowledge_service as _sk
                _sk_text = _sk.get_knowledge_text()
            except Exception as _sk_err:
                logger.debug(f"[FastPath] system_knowledge injection skipped: {_sk_err}")
            full_context = {}
            if _sk_text:
                full_context["system_knowledge"] = _sk_text
            full_context.update({
                "system_state": context,
                "capabilities": manifest,
                "chat_history": history,
                "user_command": command_text,
                "page_context": page_context,
                "current_time": get_local_now().strftime("%Y-%m-%d %A %H:%M:%S %Z (UTC%z)")
            })
            # [Conversation memory] Devices controlled in this thread's recent turns, so
            # a follow-up like "모두 꺼줘 / 그거 꺼 / turn them off" targets what was JUST
            # acted on rather than a generic 'all outputs' set.
            from aot.ai.services import intent_resolver as _ir
            _recent_dev = _ir.recent_controlled_devices(thread_id)
            if _recent_dev:
                full_context["recently_controlled_devices"] = _recent_dev

            prompt = (
                f"User Command: {command_text}\n\n"
                # [Conversation Continuity] Resolve short/ambiguous follow-ups against
                # the immediately preceding turns instead of restarting. Without this,
                # '안내해줘' after a valve-analysis turn was answered as a generic system
                # intro — the conversation thread was dropped.
                "CONVERSATION CONTINUITY [check FIRST]: Read 'chat_history' before answering. "
                "If the user's message is short or a continuation ('안내해줘', 'tell me more', "
                "'계속', 'again', or a pronoun like '그거/that/it'), it refers to the PREVIOUS turn "
                "— continue THAT topic and deliver what was promised there. Do NOT restart, and do "
                "NOT reply with a generic system introduction or unrelated dashboard readings.\n"
                "RECENT-CONTROL REFERENCE: If the user says '모두 꺼줘 / 모두 켜줘 / 다 꺼 / turn them off "
                "/ turn everything off / 그것들 / those' right after controlling devices, they mean the "
                "devices in the context key 'recently_controlled_devices' (what was JUST acted on) — "
                "propose control for THOSE, using their device_id from that list. Do NOT substitute a "
                "generic set of other outputs (e.g. 밸브1~51) that were never mentioned.\n"
                "FAST PATH MODE: You have a device list but NO live sensor data.\n"
                # [Device inventory] The context does NOT contain the user's registered
                # devices — only 'creatable_*' (the CATALOG of installable TYPES). Asked
                # "list my devices", the model wrongly recited that catalog (스테퍼 모터,
                # Kasa, BME280 …) instead of the actual registered devices.
                "DEVICE INVENTORY RULE: The context key 'system_knowledge' is the AUTHORITATIVE, "
                "current inventory of the user's registered devices, functions, and zones. To answer "
                "'what devices/functions/zones do I have / list my devices / 장치·함수·구역 목록 / "
                "등록된 장치', answer DIRECTLY from 'system_knowledge' — no tool call needed. Only call "
                "tool_name='get_device_list' if 'system_knowledge' is absent, or "
                "tool_name='search_devices' (params={\"arguments\": {\"query\": \"<keyword>\"}}) for a "
                "specific device's live detail. The 'creatable_*' entries are ONLY the catalog of device "
                "TYPES that CAN be added — they are NOT the user's registered devices. NEVER answer a "
                "'my devices' question from 'creatable_*' or from memory.\n"
                "If you need sensor readings (temperature, humidity, weather, 날씨, 기온, 강수, soil, CO2, etc.), "
                "use tool_name='get_sensor_detail' with params={\"loc_id\": \"<zone_unique_id_or_device_id>\"}. "
                "You can find zone unique_ids in the spatial_hierarchy (field: 'unique_id'). "
                "Weather data (KMA, 기상청, OpenWeatherMap) is also stored as sensor data — always call get_sensor_detail to get it.\n"
                "Respond with JSON containing 'insight' (answer in user's language) and 'actions' (list of tools to call).\n"
                "SCHEMA: { \"insight\": \"...\", \"actions\": [ { \"tool_name\": \"...\", \"params\": {}, \"display_summary\": \"...\" } ] }\n"
                "CRITICAL: Do NOT include 'action_type' or 'target_id' in the JSON. The system resolves them automatically.\n"
                "Detect the language of the USER COMMAND and write 'insight' in that SAME language.\n"
                # [PA-086] Anti-Hallucination: operate_device requires user approval before physical execution.
                "DEVICE CONTROL RULE: If any action involves device control (e.g. operate_device), "
                "write 'insight' as a PROPOSAL in the user's language "
                "(e.g. 'Requested control of [device]. Please approve below.'). "
                "NEVER write as if execution is complete ('켰습니다', 'turned on', 'activated') — "
                "physical execution only occurs after explicit user approval.\n"
                # [TASK_5] Ambiguity prevention: approval button must show Target + Action + Duration
                "APPROVAL CLARITY RULE: For every control action, you MUST set 'display_summary' "
                "to a concise Korean label stating the Target Device, Action, and Duration. "
                "Example: '3구역 밸브 3분 가동', '조명 OFF', '펌프 10초 가동'. "
                "NEVER leave display_summary empty or use vague labels like 'operate_device'.\n"
                # [TASK_33][item_3] Anti-Meta-Talk Guard
                "STRICT RULE: Do not explain internal tool-use, database structures, or query methods. "
                "Provide the answer directly based on retrieved data. "
                "If data is missing after execution, state 'No logs found' (or '데이터 없음' in Korean)."
            )
            # [TASK_33][item_1] DATA_QUERY Execution Enforcement
            # AI MUST call a retrieval tool before answering historical duration/state queries.
            if intent == 'DATA_QUERY':
                prompt += (
                    "\nDATA_QUERY ENFORCEMENT [OVERRIDES Rule 5.1]: "
                    "Weather (날씨/기상/KMA/OpenWeatherMap), temperature (온도/기온), humidity, soil, CO2, and any sensor measurement "
                    "are DATA RETRIEVAL — they REQUIRE a tool call. They are NOT 'Information Requests'. "
                    "TOOL SELECTION for data retrieval:\n"
                    "  • For weather/temperature/climate queries (날씨, 기상, 온도, 기온, 습도, 풍속 etc.) with a zone name: "
                    "use tool_name='get_weather' with params={\"zone_name\": \"<zone name>\"}. "
                    "get_weather accepts zone names directly (e.g. '1포장') — do NOT require a UUID.\n"
                    "  • For other sensor data or historical analysis: "
                    "use tool_name='get_sensor_detail' with params={\"loc_id\": \"<zone_unique_id from spatial_hierarchy>\"}.\n"
                    "Answering without a tool call when data retrieval is needed is a VIOLATION of Law 3 (Physical Truth). "
                    "When multiple measurements (e.g., weather metrics) are returned, you MUST summarize ALL of them "
                    "in your final answer. Do NOT omit any measurements if they are present in the results. "
                    "If the tool returns raw ON/OFF state logs, calculate the total ON duration internally "
                    "and report ONLY the final result (e.g., '총 12분 가동'). Never report raw log entries."
                )
                # [Capability grounding] DATA_QUERY now also covers capability / how-to
                # questions. Pre-inject the relevant manual sections so the answer is
                # documentation-grounded regardless of whether/which doc tool the model
                # picks (see _manual_grounding). Flag-gated; no-op when off / no match.
                # BUT NOT for a short conversational follow-up: injecting capability docs
                # for '안내해줘' hijacked the reply into a generic system intro. When the
                # message is short and a conversation is already in progress, treat it as
                # a continuation (handled by CONVERSATION CONTINUITY above), not a how-to.
                _is_short_followup = len((command_text or '').strip()) < 8 and len(history) > 0
                if not _is_short_followup:
                    _manual_ref = AIAgentService._manual_grounding(command_text)
                    if _manual_ref:
                        # FRONT placement (not append) — a tail-appended key was
                        # verified to be cut by base_ai's 100k hard-truncation on
                        # large installs; see _inject_context_front.
                        full_context = AIAgentService._inject_context_front(
                            full_context, 'manual_reference', _manual_ref)
                        prompt += AIAgentService._MANUAL_GROUNDING_DIRECTIVE
            # [001_WEATHER_LOGIC_UPGRADE FIX_2] Inject limit=1 for current weather queries
            # [WEATHER_TOOL_UNIFICATION] get_weather preferred over get_sensor_detail for current weather
            # @ANCHOR: FAST_PATH_WEATHER_LIMIT  [2026-03-24]
            _WEATHER_KW_FP = frozenset([
                '날씨', '기상', '기온', '강수', '풍속', '온도', '습도', '기압',
                'weather', 'temperature', 'humidity', 'wind', 'rain',
            ])
            _ANALYTICAL_KW_FP = frozenset([
                '평균', '최대', '최소', '비교', '추이', '어제', '지난', 'average', 'max', 'min', 'trend',
            ])
            _cmd_fp = (command_text or '').lower()
            if any(kw in _cmd_fp for kw in _WEATHER_KW_FP) and not any(kw in _cmd_fp for kw in _ANALYTICAL_KW_FP):
                prompt += (
                    "\nWEATHER_CURRENT_RULE: This is a current-state weather query. "
                    "Use tool_name='get_weather' with params={\"zone_name\": \"<zone name as stated by user>\"}. "
                    "get_weather resolves zone names automatically — do NOT look up a UUID first. "
                    "Example: {\"tool_name\": \"get_weather\", \"params\": {\"zone_name\": \"1포장\"}}"
                )
            # [TASK_34][item_1] CONTROL Discovery Rule
            # AI MUST perform device discovery before proposing any operate_device action.
            if intent == 'CONTROL':
                prompt += (
                    "\nCONTROL DISCOVERY RULE: Before proposing any device control action, "
                    "you MUST first call a discovery tool (e.g., search_devices, get_device_info) "
                    "to confirm the target device's exact UUID and ServerID. "
                    "Do NOT submit operate_device as your first action without prior discovery.\n"
                    # [TASK_37] Tool selection rules for CONTROL
                    "TOOL SELECTION RULES:\n"
                    "- Immediate control ('켜줘', '꺼줘', 'turn on', 'turn off', + optional duration): "
                    "use tool_name='operate_device' with arguments={device_id, state, duration_seconds}\n"
                    "- Future/scheduled control ('내일', '오전 9시에', 'tomorrow', 'at 9am'): "
                    "use tool_name='schedule_device_control' with arguments={device_id, scheduled_time (ISO8601), state}\n"
                    "- Duration like '1분동안', 'for 5 minutes' = IMMEDIATE operate_device, NOT schedule_device_control.\n"
                    "- NEVER call schedule_device_control for immediate requests.\n"
                    # [025_STEP_2] Strict template: all 3 parameters required before approval gate
                    "STRICT TEMPLATE RULE: When proposing device control, your 'insight' MUST follow "
                    "this exact template: '[장치명]을(를) [시간]동안 [동작]하겠습니다. 승인하시겠습니까?' "
                    "ALL THREE of [장치명], [시간], [동작] MUST be explicitly stated. "
                    "If ANY parameter is unknown or cannot be confirmed from discovery context, "
                    "you are STRICTLY FORBIDDEN from presenting an approval action. "
                    "Set 'actions': [] and ask for the missing parameter in 'insight' instead."
                )

            # [Goal loop] Frame the request as a goal to pursue autonomously — appended
            # LAST so it is the final instruction the model reads before acting.
            if goal_directive:
                prompt += goal_directive

            # 3. Single LLM call + RAG loop (max 2 iterations by default; a goal loop
            #    raises this so multi-step goals finish autonomously in one turn).
            max_rag = int(max_rag_override) if max_rag_override else 2
            rag_count = 0
            # v17.0: Using deque for O(1) performance and automatic size limiting
            all_rag_logs = deque(maxlen=MAX_RAG_LOGS)

            while rag_count < max_rag:
                # Timeout guard
                if _time.monotonic() - _fast_path_start > _FAST_PATH_TIMEOUT:
                    logger.warning(f"[Fast Path] Timeout ({_FAST_PATH_TIMEOUT}s) reached.")
                    return {"status": "escalate", "reason": f"Fast path timeout ({_FAST_PATH_TIMEOUT}s)"}

                result = engine.run_reasoning(full_context, prompt)
                actions = result.get('actions', [])
                # [PC-089][TASK_30][TASK_32] Universal Anti-Hallucination Guard (PA-086 / Law 3)
                # Intercepts ANY hardware control intent regardless of action_type,
                # including custom top-level types (e.g. 'operate_device') and
                # any action carrying a 'device_id' parameter.
                # [PC-089] PC-089 simplified: tool_name check only (action_type field gone from LLM)
                _CTRL_TOOL_NAMES = {'operate_device', 'output_on', 'output_off', 'set_output', 'control_output'}
                _device_ctrl = any(
                    # [TASK_37] Check both params.tool_name AND top-level tool_name
                    a.get('params', {}).get('tool_name') in _CTRL_TOOL_NAMES
                    or a.get('tool_name') in _CTRL_TOOL_NAMES
                    or bool(a.get('params', {}).get('device_id') or a.get('params', {}).get('arguments', {}).get('device_id'))
                    for a in actions
                )
                if _device_ctrl and result.get('insight'):
                    # [TASK_34][item_2] Dynamic insight: resolve device name from manifest outputs
                    _confirmed_name = None
                    _duration_hint = None
                    for _a in actions:
                        _p = _a.get('params', {})
                        _args = _p.get('arguments', _p)
                        _dev_id = (
                            _args.get('device_id') or _p.get('device_id') or _a.get('target_id')
                        )
                        _duration_hint = _duration_hint or _args.get('duration') or _args.get('duration_minutes')
                        if _dev_id and not _confirmed_name:
                            _manifest_outputs = full_context.get('capabilities', {}).get('outputs', [])
                            for _o in _manifest_outputs:
                                if _o.get('unique_id') == _dev_id or _o.get('name') == _dev_id:
                                    _confirmed_name = _o.get('name')
                                    break
                    # i18n: English source + gettext → localized to the user's
                    # locale (never hardcode one language on a user-facing string).
                    from flask_babel import gettext as _
                    if _confirmed_name:
                        if _duration_hint:
                            result['insight'] = _(
                                "Prepared a draft to run [%(device)s] for %(minutes)s minutes. Approve?"
                            ) % {'device': _confirmed_name, 'minutes': _duration_hint}
                        else:
                            result['insight'] = _(
                                "Prepared a control draft for [%(device)s]. Tap the button below to approve; "
                                "the device is controlled only after you approve."
                            ) % {'device': _confirmed_name}
                    else:
                        result['insight'] = _(
                            "[Device control request] Tap the button below to approve; "
                            "the device is controlled only after you approve."
                        )
                    logger.info("[PC-089][TASK_34] Device control — insight overridden to contextual proposal.")

                # @ANCHOR: CONTROL_TEMPLATE_GUARD (TASK_8 CM_2 — Hard-Block)
                # Unconditional guard for ALL CONTROL intents with device actions.
                # Expanded regex covers Korean + English duration/action tokens.
                # On first failure: re-synthesize once. On second failure: SYSTEM_ERROR hard-block.
                if intent == 'CONTROL' and _device_ctrl and result.get('insight'):
                    import re as _re_tpl
                    _insight_val = result.get('insight', '')
                    # CM_2 Step 1: Expanded duration pattern (Korean + English)
                    _has_duration = bool(_re_tpl.search(
                        r'\d+\s*(분|초|시간|hours?|minutes?|seconds?|min|sec|hrs?)',
                        _insight_val, _re_tpl.IGNORECASE
                    ))
                    # CM_2 Step 1: Expanded action pattern (Korean + English)
                    _has_action = bool(_re_tpl.search(
                        r'(켜|끄|열|닫|작동|가동|on|off|open|close|turn|activate)',
                        _insight_val, _re_tpl.IGNORECASE
                    ))
                    if not (_has_duration and _has_action):
                        if rag_count < max_rag:
                            # First failure: re-synthesize once
                            logger.warning(
                                f"[CM_2][TEMPLATE_GUARD] insight missing duration or action token. "
                                f"Re-synthesizing (attempt {rag_count+1}). insight='{_insight_val[:100]}'"
                            )
                            full_context.setdefault('chat_history', []).append({
                                "role": "user",
                                "content": (
                                    "[TEMPLATE ENFORCEMENT] Your previous insight did not follow the required format. "
                                    "You MUST rewrite 'insight' using this EXACT template: "
                                    "'[장치명]을(를) [N분/N초]동안 [동작]하겠습니다. 승인하시겠습니까?' "
                                    "ALL THREE of [장치명], [시간], [동작] are mandatory. Do not omit any."
                                )
                            })
                            rag_count += 1
                            continue
                        else:
                            # CM_2 Step 2: Hard-block — SYSTEM_ERROR, do NOT send invalid insight to UI
                            logger.error(
                                f"[CM_2][TEMPLATE_GUARD][HARD_BLOCK] Re-synthesis also failed template. "
                                f"Returning SYSTEM_ERROR. insight='{_insight_val[:100]}'"
                            )
                            return {
                                "status": "error",
                                "message": (
                                    "[TEMPLATE_GUARD] Control proposal failed validation after re-synthesis. "
                                    "Please rephrase your command with device name, duration, and action."
                                )
                            }
                # [TASK_35][item_2] Intent-gated semantic guard (safe: DATA_QUERY exempt)
                elif intent == 'CONTROL' and not _device_ctrl:
                    _CTRL_KEYWORDS = {'valve', 'pump', 'output', 'device_id'}
                    _kw_hit = any(
                        kw in json.dumps(a, ensure_ascii=False).lower()
                        for a in actions for kw in _CTRL_KEYWORDS
                    )
                    if _kw_hit and result.get('insight'):
                        from flask_babel import gettext as _
                        result['insight'] = _(
                            "[Device control request] Tap the button below to approve; "
                            "the device is controlled only after you approve."
                        )
                        logger.info("[TASK_35] Keyword-based CONTROL guard triggered — insight overridden.")
                # [P4] Block operate_device in RAG (context-gathering) phase — must pass Phase 4/5 gates
                _RAG_TYPES_FP = {'virtual_tool_call', 'mcp_tool_call', 'read_manual', 'knowledge_search', 'get_detailed_manifest'}
                _CTRL_TOOLS_FP = {'operate_device'}
                rag_actions = [a for a in actions if
                               (a.get('action_type') in _RAG_TYPES_FP
                                or (a.get('tool_name') and a.get('tool_name') not in _CTRL_TOOLS_FP and not a.get('action_type')))
                               and not (a.get('action_type') == 'virtual_tool_call'
                                        and a.get('params', {}).get('tool_name') == 'operate_device')]

                if not rag_actions:
                    # [TASK_34][item_3] Mandatory discovery for CONTROL with no prior RAG
                    if intent == 'CONTROL' and rag_count == 0 and _device_ctrl:
                        logger.info("[TASK_34] CONTROL intent with 0 RAG loops — forcing discovery loop.")
                        full_context.setdefault('chat_history', []).append({
                            "role": "user",
                            "content": (
                                "[DISCOVERY REQUIRED] Before proceeding with device control, "
                                "call a discovery tool (search_devices or get_device_info) "
                                "to confirm the target device UUID and ServerID. "
                                "Do NOT call operate_device yet."
                            )
                        })
                        rag_count += 1
                        continue
                    # [DATA_AUTORUN REVERT] — DATA_AUTORUN was a text-mode workaround.
                    # Gemini Function Calling now handles tool execution natively.
                    # Only provide a simple fallback hint; do not auto-execute tools.
                    if intent == 'DATA_QUERY' and rag_count == 0:
                        logger.info("[DATA_AUTORUN] DATA_QUERY with no tool call — providing fallback hint.")
                        _data_hint = (
                            "[SYSTEM: DATA RETRIEVAL REQUIRED] No tool call detected. "
                            "Call get_sensor_detail with loc_id from system_state.device_list. "
                            "Return JSON with actions array."
                        )
                        full_context.setdefault('chat_history', []).append({"role": "user", "content": _data_hint})
                        rag_count += 1
                        continue
                    break

                rag_count += 1
                logger.info(f"[Fast Path] RAG loop {rag_count}: {[a.get('action_type') for a in rag_actions]}")

                rag_results = []
                for a in rag_actions:
                    try:
                        # v21.0: P1 Metadata Validation
                        valid, err = AIAgentService._validate_and_normalize_action(a)
                        if not valid:
                            add_limited_rag_log(all_rag_logs, f"Validation Error: {err}", 'default')
                            continue

                        res = AIActionService.execute_action(a['action_type'], a.get('target_id'), a.get('params'))

                        # @ANCHOR: EMERGENCY_FALLBACK detector (TASK_8 048 — Step 2)
                        # Detect mcp_tool_call connection/timeout failures → activate emergency fallback.
                        if (a.get('action_type') == 'mcp_tool_call'
                                and isinstance(res, dict)
                                and res.get('status') == 'error'
                                and '[PC-099-ERROR]' not in res.get('message', '')
                                and isinstance(res, dict)
                                and res.get('status') == 'error'
                                and any(kw in res.get('message', '').lower()
                                        for kw in ('not available', 'not initialized',
                                                   'timeout', 'connection'))):
                            _emergency_fallback = True
                            logger.warning(
                                f"[FALLBACK_TRIGGERED] mcp_tool_call returned connection/timeout error "
                                f"(tool='{a.get('params', {}).get('tool_name', '')}', "
                                f"msg='{res.get('message', '')}'). Emergency Fallback activated."
                            )

                        # [027_STEP_3] Data-First Priority: if MCP call failed with server-offline error
                        # and intent is DATA_QUERY, inject a DB fallback suggestion.
                        # Truth (DB data, last 15m) must take precedence over Admin (server status flag).
                        if (intent == 'DATA_QUERY'
                                and isinstance(res, dict)
                                and res.get('status') == 'error'
                                and 'not available' in res.get('message', '').lower()):
                            _tool = a.get('params', {}).get('tool_name', '')
                            logger.warning(
                                f"[027_STEP_3][DATA_FIRST] MCP tool '{_tool}' server offline — "
                                "injecting DB fallback hint for DATA_QUERY."
                            )
                            res['_db_fallback_hint'] = (
                                "SERVER_OFFLINE_FALLBACK: The MCP server is unavailable, but fresh data "
                                "may exist in the local database. Use 'get_sensor_detail' virtual tool "
                                "to retrieve the last known reading from the DB (last 15 minutes)."
                            )

                        # v6.2: Tool Result Slimming (Truncate bulky lists/responses)
                        # v30.1: Increased limit from 5 to 30 to support multi-sensor weather data.
                        if isinstance(res, list) and len(res) > 30:
                            res = res[-30:] # Take last 30 readings/items
                            res.append("... [TRUNCATED for token saving]")

                        # [001_WEATHER_LOGIC_UPGRADE] Weather-aware truth tagging
                        if a.get('action_type') == 'virtual_tool_call':
                            from aot.ai.services.ai_routing_service import AIRoutingService as _ARS
                            log_msg = _ARS.format_weather_tool_result(a, res)
                        else:
                            log_msg = f"Tool '{a['action_type']}' result:\n{json.dumps(res, ensure_ascii=False)}"
                        rag_results.append(log_msg)
                        add_limited_rag_log(all_rag_logs, log_msg, a['action_type'])
                    except Exception as e:
                        err_msg = f"Tool '{a['action_type']}' failed: {str(e)}"
                        rag_results.append(err_msg)
                        add_limited_rag_log(all_rag_logs, err_msg, 'default')

                if 'chat_history' not in full_context:
                    full_context['chat_history'] = []
                full_context['chat_history'].append({
                    "role": "assistant",
                    "content": "Executing: " + json.dumps(rag_actions, ensure_ascii=False)
                })
                full_context['chat_history'].append({
                    "role": "user",
                    "content": "Result:\n" + "\n".join(rag_results) + "\n\nNow answer my original question."
                })

            # @ANCHOR: FAST_PATH_FINAL_SYNTHESIS  [001_WEATHER_LOGIC_UPGRADE BUG_A — 2026-03-24]
            # [BUG_A2/CONTEXT_OVERFLOW fix 2026-03-24]
            # When the while loop exits at max_rag, `result` predates the last RAG execution.
            # Problem: full_context['capabilities'] (manifest) can exceed 50k chars, pushing
            #   chat_history RAG results past the 100k budget → hard-truncated → LLM never sees data.
            # Fix: use a lean synthesis context (no capabilities manifest) + explicit retrieved_data key.
            if rag_count >= max_rag and all_rag_logs:
                logger.info(
                    "[FastPath][FINAL_SYNTHESIS] max_rag=%d reached with %d log entries — "
                    "forcing lean synthesis call.", max_rag, len(all_rag_logs)
                )
                _lean_ctx = {
                    "user_command": command_text,
                    "current_time": full_context.get("current_time", ""),
                    "page_context": full_context.get("page_context", ""),
                    # Keep only the last 6 chat turns (pre-RAG history) to preserve conversational context
                    "prior_chat": (full_context.get("chat_history") or [])[-6:],
                    # Inject RAG results as a dedicated top-level key — not buried in chat_history
                    "retrieved_data": list(all_rag_logs),
                }
                _synth_suffix = (
                    "\n\nSYNTHESIS_MODE: Data retrieval is COMPLETE — the results are already in "
                    "'retrieved_data' above. Write the FINAL user-facing answer in 'insight' NOW, "
                    "using that data directly and completely, in the user's language. Present whatever "
                    "was retrieved: if it is a DEVICE LIST, list the actual devices by name; if it is "
                    "measurements, summarize ALL of them. Return 'actions': [] and call NO more tools. "
                    "CRITICAL: Do NOT say you will load / fetch / check / 불러오겠습니다 / 확인하겠습니다, "
                    "and do NOT ask the user to wait — the data is right here; answer it immediately."
                )
                result = engine.run_reasoning(_lean_ctx, prompt + _synth_suffix)

            # [Inventory from system_knowledge] For a "what do I have / list my devices"
            # question, NO tool is needed — the answer is already in system_knowledge.
            # But the model often stalls ("장치 정보를 불러오겠습니다") or the zero-RAG
            # escalation below would wrongly treat rag_count==0 as a placeholder. So:
            # if this is an inventory question and the model didn't answer it cleanly,
            # force ONE synthesis from system_knowledge ALONE — a tiny context with no
            # manifest/tool bloat, so it can't be truncated and there's nothing to
            # "fetch". Scoped to inventory questions so sensor queries still escalate.
            if (intent == 'DATA_QUERY' and _sk_text
                    and AIAgentService._is_inventory_question(command_text)):
                _prelim = result.get('insight', '') or ''
                if not AIAgentService._looks_like_stall(_prelim):
                    # The model already produced a real inventory answer. It lists device
                    # names (밸브1, …) which trip the control-intent semantic guard below
                    # (그 밸브 == a control keyword), falsely flagging a DATA answer as a
                    # control hallucination → escalation to a path that then stalls. Clear
                    # the false flags and keep the good answer.
                    result['_parse_failed'] = False
                    result['_semantic_guard_hit'] = False
                    rag_count = max(rag_count, 1)
                    logger.info("[FastPath][KNOWLEDGE_ANSWER] Kept inventory answer; cleared false control-guard flag.")
                else:
                    # The model meta-stalled ("장치 정보를 불러오겠습니다"). run_reasoning always
                    # wraps the goal in the heavy tool-oriented agent prompt, so re-prompting
                    # rarely helps — go straight to the DETERMINISTIC inventory so the user
                    # always gets the real, complete list. No LLM, no stall, no truncation.
                    try:
                        from aot.ai.services import system_knowledge_service as _sk2
                        _det = _sk2.get_inventory_answer()
                        if _det:
                            result = {"insight": _det, "actions": [], "_parse_failed": False, "_semantic_guard_hit": False}
                            rag_count = max(rag_count, 1)
                            logger.info("[FastPath][KNOWLEDGE_ANSWER] Answered inventory question from system_knowledge (deterministic).")
                    except Exception as _kn_e:
                        logger.debug(f"[FastPath] knowledge-answer fallback failed: {_kn_e}")

            # [025_STEP_1] Enforce minimum 1 RAG loop for CONTROL/DATA_QUERY intents.
            # Zero RAG loops = AI answered without any tool call = potential placeholder response.
            if rag_count == 0 and intent in ('CONTROL', 'DATA_QUERY'):
                logger.warning(
                    f"[025_STEP_1][ZERO_RAG] {intent} intent completed with 0 RAG loops — "
                    "no tool was called. Escalating to full path to prevent placeholder response."
                )
                return {"status": "escalate", "reason": f"Zero RAG loops for {intent} intent"}

            # 4. Check if AI actually answered (escalate if empty or semantic fail)
            insight = result.get('insight', '')
            # [TASK_41] Guard: extract clean insight — handles JSON wrapper, markdown fence, embedded JSON
            _clean = _extract_clean_insight(insight)
            if _clean != insight:
                insight = _clean
                result['insight'] = insight
                logger.warning("[TASK_41] Extracted clean insight from raw LLM output in fast path.")
            # [031_STEP_2] Final response sanitizer — strip JSON leaks and Router Observation strings
            _sanitized = AIAgentService._sanitize_final_response(insight)
            if _sanitized != insight:
                insight = _sanitized
                result['insight'] = insight
                logger.warning("[031_STEP_2] Sanitizer applied to fast path insight.")
            # [Citation trust] Server-side disclosure guard — if the answer drew
            # on an unconfirmed AI-shelved note without saying so, say so for it.
            _disclosed = AIAgentService._enforce_unconfirmed_disclosure(
                insight, full_context.get('manual_reference'))
            if _disclosed != insight:
                insight = _disclosed
                result['insight'] = insight
            # @ANCHOR: EMERGENCY_FALLBACK prefix injection (TASK_8 048 — Step 2)
            # TEMPLATE_GUARD already validated [Device/Action/Duration] inside the RAG loop.
            # This prefix is added post-validation so it does not affect regex checks.
            if _emergency_fallback and insight:
                _EMERGENCY_PREFIX = "[긴급: MCP 통신 불가로 인한 대체 제어] "
                if not insight.startswith(_EMERGENCY_PREFIX):
                    insight = _EMERGENCY_PREFIX + insight
                    result['insight'] = insight
                    logger.warning("[EMERGENCY_FALLBACK] Emergency prefix prepended to insight.")

            if result.get('_parse_failed') or result.get('_semantic_guard_hit') or not insight or len(insight.strip()) < 5:
                # v23.0: If semantic guard triggered or response is empty, escalate to full collaboration.
                reason = "Semantic guard failure (hallucination)" if result.get('_parse_failed') else "Empty response from fast path"
                logger.info(f"[Fast Path] Escalating due to: {reason}")
                return {"status": "escalate", "reason": reason}


            # 5. Strip RAG/info actions from final result — keep control actions for approval
            # [TASK_37] operate_device must survive this filter to appear in approval button
            # [BUG_C fix 2026-03-24] OPTION_D: LLM does not set action_type (None).
            # None not in [...] = True caused RAG actions to bypass this filter and trigger
            # the approval gate. Fix: treat action_type=None as a RAG action unless the
            # tool_name is explicitly in _CTRL_APPROVAL_TOOLS.
            _CTRL_APPROVAL_TOOLS = {'operate_device', 'output_on', 'output_off', 'set_output', 'control_output'}
            _RAG_ACTION_TYPES = {'virtual_tool_call', 'mcp_tool_call', 'read_manual', 'knowledge_search', 'get_detailed_manifest'}
            result['actions'] = [
                a for a in result.get('actions', [])
                if (
                    # Always keep explicit control tool names (approval gate target)
                    a.get('params', {}).get('tool_name') in _CTRL_APPROVAL_TOOLS
                    or a.get('tool_name') in _CTRL_APPROVAL_TOOLS  # [TASK_38]
                    or a.get('params', {}).get('arguments', {}).get('tool_name') in _CTRL_APPROVAL_TOOLS
                ) or (
                    # Keep only when action_type is explicitly set AND not a RAG type
                    # action_type=None (OPTION_D pre-normalization) is treated as RAG → removed
                    a.get('action_type') is not None
                    and a.get('action_type') not in _RAG_ACTION_TYPES
                )
            ]

            # [Unresolved placeholder guard] The goal loop's deeper reasoning can lead
            # the model to emit a planner-style variable reference as a control target
            # ("$valve_device.results[0].unique_id"). The fast path executes read tools
            # and re-injects CONCRETE results — it does NOT resolve such placeholders —
            # so operate_device would fail with "찾을 수 없습니다: $valve_device…". If a
            # control action still carries an unresolved placeholder, escalate to the
            # legacy pipeline (which replans and resolves device ids), restoring the
            # previously-smooth behavior instead of proposing a broken action.
            def _bad_ctrl_target(v):
                # Unresolved placeholder, or a missing/too-short id — either way the
                # control action cannot execute and must not be proposed as-is.
                if not v or not isinstance(v, str) or len(v) < 8:
                    return True
                return ('$' in v or '.results[' in v or '{{' in v or '{%' in v)
            for _a in (result.get('actions') or []):
                _pp = _a.get('params', {}) or {}
                _pa = _pp.get('arguments', {}) if isinstance(_pp.get('arguments'), dict) else {}
                # operate_device can appear at top-level, under params, or nested in
                # params.arguments (mcp_tool_call shape) — check all.
                _tn = (_pp.get('tool_name') or _pa.get('tool_name')
                       or _a.get('tool_name') or _a.get('action_type'))
                if _tn in _CTRL_APPROVAL_TOOLS:
                    _did = _pp.get('device_id') or _pa.get('device_id') or _a.get('target_id')
                    if _bad_ctrl_target(_did):
                        # Phase B: resolve name → UUID deterministically before giving up.
                        _fixed = AIAgentService._resolve_control_device_id(_a, command_text)
                        if _fixed:
                            _pp['device_id'] = _fixed
                            if _pa:
                                _pa['device_id'] = _fixed
                            _a['params'] = _pp
                            _a['target_id'] = _fixed
                            logger.info(f"[FastPath] Resolved control target {_did!r} → {_fixed} deterministically.")
                            continue
                        logger.info(
                            f"[FastPath] Control target unresolved/invalid ({_did!r}) and no name match — "
                            "escalating to legacy pipeline for device resolution.")
                        return {"status": "escalate", "reason": "unresolved/invalid control target"}

            # [DATA_QUERY is read-only] An information / how-to answer must NEVER
            # surface an approval button. DATA_QUERY has no physical action by
            # definition — physical/registration actions belong to CONTROL /
            # SCHEDULE / FUNCTION_CREATE. Observed bug: a "how do I add a sensor?"
            # answer carried a register_device action the model attached out of
            # over-eagerness → a phantom "Approve Action" button (no description).
            # Drop any surviving action so info answers show no approval UI.
            if intent == 'DATA_QUERY' and result.get('actions'):
                logger.info(
                    f"[FastPath][DATA_QUERY_READONLY] Dropping {len(result['actions'])} "
                    f"non-data action(s) from a read-only DATA_QUERY answer "
                    f"(types={[a.get('action_type') for a in result['actions']]})."
                )
                result['actions'] = []

            # NOTE: the user-facing message for a physical-control PROPOSAL is set at
            # the route boundary (_control_proposal_message), which is the single
            # choke point every path (fast/collab/bypass) flows through — so the
            # message is correct regardless of which path produced it, and the model's
            # internal narration (auto-discovery, etc.) never leaks to the user.

            # 6. Learning + Dispatch
            learning = AILearningService.process_ai_response(insight)
            metadata = {
                "phase2": [{
                    "thought": insight[:200] + "..." if insight else "Fast Path Execution",
                    "model": worker.entry.model_name if worker.entry else "FastWorker"
                }],
                "phase3": list(all_rag_logs) if all_rag_logs else [],
                "phase4": [{"summary": f"Fast path. Intent: {intent}. RAG loops: {rag_count}."}],
                "final_response": learning.get('text', ''),
                "intent": intent,
                "fast_path": True,
                "rag_loops": rag_count
            }

            dispatch_res = AIAgentService._dispatch_actions(
                agent_id=worker.unique_id,
                goal=command_text,
                insight=learning.get('text', ''),
                actions=result.get('actions', []),
                thread_id=thread_id,
                message_type='ai',
                metadata=metadata
            )

            logger.info(f"[Fast Path] Complete. RAG loops: {rag_count}, insight length: {len(insight)}")
            return {
                "status": "success",
                "insight": learning.get('text', ''),
                "intent": intent,
                "proposed_actions": result.get('actions', []),
                "immediate_results": dispatch_res.get('immediate_results', []),
                "draft_job_ids": dispatch_res.get('draft_ids', []),
                "history_id": dispatch_res['history_id'],
                "_fast_path": True
            }

        except Exception as e:
            logger.error(f"[Fast Path] Error: {e}", exc_info=True)
            return {"status": "escalate", "reason": str(e)}

    @staticmethod
    def _validate_and_normalize_action(action):
        from aot.ai.services.ai_routing_service import AIRoutingService
        return AIRoutingService._validate_and_normalize_action(action=action)

    @staticmethod
    def _resolve_action_route(action, agent_id):
        from aot.ai.services.ai_routing_service import AIRoutingService
        return AIRoutingService._resolve_action_route(action=action, agent_id=agent_id)

    @staticmethod
    def _dispatch_actions(agent_id, goal, insight, actions, thread_id=None, message_type='ai', metadata=None):
        from aot.ai.services.ai_dispatch_service import AIDispatchService
        return AIDispatchService._dispatch_actions(agent_id=agent_id, goal=goal, insight=insight, actions=actions, thread_id=thread_id, message_type=message_type, metadata=metadata)

    @staticmethod
    def _register_drafts(actions, reasoning, agent_name='AI'):
        from aot.ai.services.ai_dispatch_service import AIDispatchService
        return AIDispatchService._register_drafts(actions=actions, reasoning=reasoning, agent_name=agent_name)

    @staticmethod
    def _register_drafts_no_commit(actions, reasoning, agent_name='AI'):
        from aot.ai.services.ai_dispatch_service import AIDispatchService
        return AIDispatchService._register_drafts_no_commit(actions=actions, reasoning=reasoning, agent_name=agent_name)

    @staticmethod
    def _inject_situation_baseline(full_context, page_context=None):
        """
        v26.9: Explicitly injects the latest natural language snapshots
        into the context as a 'situation_baseline'.
        """
        try:
            from aot.ai.services.cache_manager import CacheManager
            baseline = []
            
            # 1. System wide
            sys_summary = CacheManager.get_latest_summary('system', None)
            if not sys_summary:
                from aot.ai.services.ai_summary_service import AISummaryService
                model = AISummaryService.get_latest_summary('system', None)
                if model:
                    sys_summary = {'version': model.version, 'summary_text': model.summary_text}
            
            if sys_summary:
                baseline.append(f"[SYSTEM-WIDE SNAPSHOT (v{sys_summary.get('version', 1)})]: {sys_summary.get('summary_text')}")
            
            # 2. Scope specific
            if page_context and page_context.get('targetType') == 'farm':
                target_id = page_context.get('targetId')
                farm_summary = CacheManager.get_latest_summary('farm', target_id)
                if not farm_summary:
                    from aot.ai.services.ai_summary_service import AISummaryService
                    model = AISummaryService.get_latest_summary('farm', target_id)
                    if model:
                        farm_summary = {'version': model.version, 'summary_text': model.summary_text}
                
                if farm_summary:
                    baseline.append(f"[FARM SNAPSHOT (v{farm_summary.get('version', 1)})]: {farm_summary.get('summary_text')}")
            
            if baseline:
                full_context['situation_baseline'] = "\n\n".join(baseline)
        except Exception as e:
            logger.warning(f"Failed to inject situation baseline: {e}")

    @staticmethod
    def _check_approval_required(action_type, target_id, params):
        from aot.ai.services.ai_dispatch_service import AIDispatchService
        return AIDispatchService._check_approval_required(action_type=action_type, target_id=target_id, params=params)

    @staticmethod
    def _sanitize_final_response(insight: str):
        from aot.ai.services.ai_synthesis_service import AISynthesisService
        return AISynthesisService._sanitize_final_response(insight=insight)

    @staticmethod
    def _generate_display_summary(action):
        from aot.ai.services.ai_synthesis_service import AISynthesisService
        return AISynthesisService._generate_display_summary(action=action)

    # ------------------------------------------------------------------
    # v6 Pipeline: Synthesizer (Verifier + Response Generator)
    # ------------------------------------------------------------------

    @staticmethod
    def run_synthesizer(execution_results, intent, original_command, plan=None, chat_history=None, worker_insights=None, proposed_actions=None):
        from aot.ai.services.ai_synthesis_service import AISynthesisService
        return AISynthesisService.run_synthesizer(execution_results=execution_results, intent=intent, original_command=original_command, plan=plan, chat_history=chat_history, worker_insights=worker_insights, proposed_actions=proposed_actions)

    @staticmethod
    def run_router(command_text, thread_id=None):
        from aot.ai.services.ai_routing_service import AIRoutingService
        return AIRoutingService.run_router(command_text=command_text, thread_id=thread_id)

