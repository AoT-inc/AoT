# coding=utf-8
import uuid
from aot.aot_flask.extensions import db
from aot.databases import CRUDMixin

class AIGlobalSettings(CRUDMixin, db.Model):
    """
    Singleton configuration for Global AI Behavior.
    Controls autonomy levels, model routing, constraints, and limits.

    @phase active
    @stability stable
    """
    id = db.Column(db.Integer, primary_key=True, default=1)
    unique_id = db.Column(db.String(36), unique=True, nullable=False, default=lambda: str(uuid.uuid4()))
    
    # Core Persona & Behavior
    from sqlalchemy.dialects.mysql import LONGTEXT
    system_prompt_template = db.Column(db.Text().with_variant(LONGTEXT, "mysql", "mariadb"), nullable=True)
    
    # Approval & Safety
    auto_approve_routine = db.Column(db.Boolean, default=False)
    max_impact_auto_approve = db.Column(db.Integer, default=30)
    blackout_start = db.Column(db.String(10), default="23:00")
    blackout_end = db.Column(db.String(10), default="06:00")
    require_feedback = db.Column(db.Boolean, default=True)
    
    # Engine Routing
    default_supervisor = db.Column(db.String(50), default="gemini-2.5-pro")
    default_worker = db.Column(db.String(50), default="gemini-2.5-flash")
    
    # Scheduling & Context
    context_hours = db.Column(db.Integer, default=24)
    max_history = db.Column(db.Integer, default=5)
    
    # Cost Management
    budget_limit_usd = db.Column(db.Float, default=10.0)
    
    # Feature Toggle — "AI 를 쓸 수 있게 한다". Settings > General 에서 켠다.
    # 메뉴 노출, AI 페이지 접근, 채팅/조언 요청이 여기에 달려 있다.
    ai_enabled = db.Column(db.Boolean, default=False, nullable=False)

    # Operation Toggle — "AI 가 스스로 돈다". AI 페이지에서 켠다.
    # 사람이 부르지 않아도 도는 백그라운드 잡(주기 요약, 컨텍스트 브로드캐스트,
    # 날씨 요약, MCP 헬스체크, 실시간 알림)만 이 스위치에 달려 있다. 사용자가
    # 직접 보내는 채팅/조언 요청은 ai_enabled 만 보고 동작한다 — 모델을 막
    # 등록한 사람이 켜기 전에 시험해 볼 수 있어야 하기 때문.
    # 판정은 반드시 aot/ai/services/ai_runtime_state.py 를 거칠 것.
    ai_running = db.Column(db.Boolean, default=False, nullable=True)

    # External MCP HTTP server master switch. Checked per-request by
    # aot_mcp_server.py's _run_http_server() routes — when False, the server
    # refuses every request with 503 regardless of API key validity. This
    # only gates whether the already-listening process answers; it cannot
    # change the bind address/port (those are fixed by docker-compose.yml's
    # `ports:` mapping or the aotmcp.service systemd unit, set at container/
    # process start and outside the running process's control).
    mcp_http_enabled = db.Column(db.Boolean, default=True, nullable=True)

    # Context Layer Toggle
    context_broadcast_enabled = db.Column(db.Boolean, default=True, nullable=True)

    # v3.1 T1 Unified Loop (Phase 1) — feature flag.
    # When False (default), CONTROL intents use the legacy planner→supervisor→
    # synthesizer pipeline (4-5 LLM calls). When True, they route through the
    # T1 unified loop (run_fast_path as loop engine, ~2 calls) with automatic
    # fallback to the legacy pipeline on escalation. See
    # .local/plans/phase1_t1_loop_design.md.
    t1_unified_enabled = db.Column(db.Boolean, default=False, nullable=True)

    # Goal-directed continuous loop (agentic T1). When True, a user request is
    # set as a GOAL and processed autonomously until achieved: read/discovery
    # tools run without approval and results feed the next step within the turn,
    # so the AI does not stall or make the user re-prompt between steps; only
    # physical-control actions still gate on approval (batched). See
    # .local/plans/ai_goal_loop_design.md. Default False.
    t1_goal_loop_enabled = db.Column(db.Boolean, default=False, nullable=True)

    # v3.1 T3 async advisory audit (Phase 2) — feature flag.
    # When True, every finalized AI response is audited AFTER it is returned
    # (non-blocking background worker) for advisory-language violations, and
    # the result is recorded on the AIHistory record for the Phase 3 rule loop
    # / Phase 4 memory loop to consume. Never blocks or alters the response.
    # See .local/plans/phase2_gate_dualization_design.md.
    t3_async_audit_enabled = db.Column(db.Boolean, default=False, nullable=True)

    # v3.1 3-tier rule layer (Phase 3) — feature flag.
    # When True, active enforcement/learned AIRule prompt fragments are injected
    # into user-facing agent prompts (after the philosophy preamble), and the
    # proposal generator may turn accumulated advisory-audit evidence into
    # auto-approved style rules. When False (default), no rules are injected and
    # no proposals are auto-applied. See .local/plans/phase3_rule_layer_design.md.
    t3_rule_layer_enabled = db.Column(db.Boolean, default=False, nullable=True)

    # v3.1 memory loop (Phase 4) — feature flag.
    # When True, the async worker records tiered experience memory (error/
    # emotion/usage) and repeated error patterns (≥ threshold) become pending
    # behavior AIRuleProposals for user confirmation. When False (default), no
    # experience memory is recorded. See .local/plans/phase4_memory_loop_design.md.
    t3_memory_loop_enabled = db.Column(db.Boolean, default=False, nullable=True)

    # v3.1 agentic knowledge search (Phase 5) — feature flag.
    # When True, the AI is told (in its prompt) about the `knowledge_search`
    # tool — free-query section-level search across the markdown docs — so it
    # can pull the relevant doc slice without navigating a file/heading index.
    # The tool executes regardless; this flag only controls its discovery hint.
    #
    # Also gates `_manual_grounding()` (ai_agent_service.py) — the SERVER-SIDE
    # deterministic retrieval that injects manual_reference before the model
    # even decides to call a tool. This is the primary reason knowledge_search
    # results (including P1-P5's library/ext-authority/ai_curated items)
    # reach the AI at all in the common case; defaulted True since P6 for the
    # same reason as knowledge_digest_enabled below — no UI has ever exposed
    # this flag, so False here never reflected a deliberate choice.
    # See .local/plans/phase5_knowledge_search_design.md.
    t3_knowledge_search_enabled = db.Column(db.Boolean, default=True, nullable=True)

    # v3.1 budget governance (Phase 6) — feature flag.
    # When True, per-connection usage is metered (estimated) and enforced
    # against budget_limit_usd: 80% alert, 100% soft-downgrade role bindings to
    # the cheapest conformant model, optional hard-stop. When False (default),
    # no metering or enforcement. See .local/plans/phase6_onboarding_budget_design.md.
    t3_budget_governance_enabled = db.Column(db.Boolean, default=False, nullable=True)
    # Optional hard ceiling: when True, AI is fully stopped at 100% of budget
    # (cache/degraded only) until the next month. When False, only soft-downgrade.
    budget_hard_stop = db.Column(db.Boolean, default=False, nullable=True)

    # v3.1 server-side page context — feature flag.
    # When True, the chat endpoint assembles the current dashboard's widget
    # values SERVER-SIDE (reading each widget's data binding + get_sensor_detail)
    # and injects them into the prompt, instead of relying on fragile frontend
    # DOM scraping. Works for every widget type. See
    # .local/plans/server_side_page_context_design.md.
    t3_server_page_context_enabled = db.Column(db.Boolean, default=False, nullable=True)

    # Knowledge digest pipeline — feature flag.
    # When True (default since P6), AI Library document/web_url sources are
    # chunked and digested (LLM summarize + keyword extraction, cached to
    # AIKnowledgeChunk) on sync, and knowledge_search's unified index includes
    # those chunks alongside the markdown manual. When False, sync writes
    # AIContextRecord only and knowledge_search stays manual-only.
    #
    # Defaulted OFF through P1-P5 development, which reproduced exactly the
    # "동작하는 척" (works in the UI, never reaches the AI) bug the whole
    # redesign (docs/design/ai-library-redesign.md) set out to fix: an
    # operator could register/sync a source and it would sit in
    # AIKnowledgeChunk forever, invisible to knowledge_search, with no UI
    # anywhere exposing this flag to explain why. No template/route has ever
    # read or written this column (grepped before flipping it — see design
    # doc P6 notes), so False here never reflected anyone's deliberate
    # choice; it only ever meant "nobody's toggled this, because they
    # couldn't." Flipping the default (and backfilling existing installs'
    # stored value, migration p5_50) is what actually closes that gap.
    # See .local/plans/phase6_knowledge_digest_design.md.
    knowledge_digest_enabled = db.Column(db.Boolean, default=True, nullable=True)

    # When True, ai_curated items still at context_state='system_generated'
    # (i.e. never confirmed, corroborated, or otherwise reviewed) are excluded
    # from search — every OTHER provenance/state (external_authority,
    # user_provided, data_derived, and ai_curated items that ARE
    # user_confirmed/corroborated) stays searchable regardless. Redefined in
    # P6 (docs/design/ai-library-redesign.md §9) from the original "only
    # user_confirmed rows searchable at all" semantics, which — combined with
    # no review UI existing until P5 — meant turning this on made ALL library
    # knowledge vanish with no way to ever confirm anything back in. Default
    # stays False: an unconfirmed ai_curated note IS meant to be usable
    # immediately at low trust (§3.2 — review is not a precondition for
    # injection, only for promotion), so this is an opt-in stricter mode, not
    # something P6 turns on by default.
    knowledge_chunk_confirmed_only = db.Column(db.Boolean, default=False, nullable=True)

    # Agent loop redesign — see docs/design/ai-agent-loop.md.
    # Master switch for AgentLoopService: a single stateful tool-calling loop
    # (model-agnostic; the full tool catalog is always visible; ask_user is a
    # first-class tool) that replaces the router-enum + per-intent pipeline
    # fan-out (run_fast_path/planner/synthesizer). Default flipped to True in
    # Phase 3 (p5_52 migration) — the agent loop is now the primary path for
    # new installs; existing rows are backfilled by that same migration. The
    # legacy pipeline stays in the codebase and is reachable by setting this
    # False (a request-time rollback lever that needs no deploy/code revert) —
    # it is NOT yet deleted, only no longer the default (staged retirement,
    # see docs/design/ai-agent-loop.md §15 Phase 3 decision).
    agent_loop_enabled = db.Column(db.Boolean, default=True, nullable=True)

    # Comma-separated User.id allowlist for the agent-loop canary. Empty/NULL
    # while agent_loop_enabled=True means every user gets the new loop —
    # intentional for local single-tenant test environments; a real staged
    # rollout sets specific ids here first.
    agent_loop_canary_user_ids = db.Column(db.Text, default='', nullable=True)
