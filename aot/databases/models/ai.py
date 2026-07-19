# coding=utf-8
from sqlalchemy.dialects.mysql import LONGTEXT
from datetime import datetime

from aot.databases import CRUDMixin
from aot.databases import set_uuid
from aot.aot_flask.extensions import db

class AIEntry(CRUDMixin, db.Model):
    """
    Represents an AI Service Connection (Provider).
    Similar to 'Input' in AoT.

    @phase active
    @stability stable
    """
    __tablename__ = "ai_entry"
    __table_args__ = {'extend_existing': True}

    id = db.Column(db.Integer, primary_key=True)
    unique_id = db.Column(db.String(36), nullable=False, unique=True, default=set_uuid)
    name = db.Column(db.String(100), nullable=False)
    
    # Engine & Connection settings
    model_type = db.Column(db.String(50), default='gemini') # gemini, openai, ollama, etc.
    model_name = db.Column(db.String(100), default='gemini-2.5-flash')
    api_endpoint = db.Column(db.String(255), default='')
    
    # Authentication (Decoupled from persona)
    auth_type = db.Column(db.String(20), default='api_key') # api_key, account, oauth2, no_auth
    auth_id = db.Column(db.String(100), default='')
    api_key = db.Column(db.Text, default='')
    
    is_activated = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # GridStack layout positions
    position_x = db.Column(db.Integer, default=0)
    position_y = db.Column(db.Integer, default=0)
    width = db.Column(db.Integer, default=24)
    height = db.Column(db.Integer, default=1)

    # v3.1 Tier Architecture — model-agnostic registry (see .local/reports/ai_architecture_v3_tier_proposal.md §13)
    # protocol: which request driver to use ('anthropic_protocol', 'openai_compatible', ...).
    # NULL means "derive from model_type via ENGINE_REGISTRY" (legacy path, unchanged behavior).
    protocol = db.Column(db.String(50), nullable=True, default=None)
    # capabilities_json: conformance probe result (tool_use, structured_output, streaming, latency_ms).
    # Written by aot.ai.services.model_probe. Empty/'{}' means never probed.
    capabilities_json = db.Column(db.Text, default='{}')
    capabilities_probed_at = db.Column(db.DateTime, nullable=True)

    def __repr__(self):
        return f"<AIEntry(name={self.name}, type={self.model_type})>"

class AIAgent(CRUDMixin, db.Model):
    """
    Represents an AI Persona/Logic.
    Uses an AIEntry as its 'Brain'.

    @phase active
    @stability stable
    @dependency AIEntry
    """
    __tablename__ = "ai_agent"
    __table_args__ = {'extend_existing': True}

    id = db.Column(db.Integer, primary_key=True)
    unique_id = db.Column(db.String(36), nullable=False, unique=True, default=set_uuid)
    name = db.Column(db.String(100), nullable=False)
    
    # Link to Service Provider (Brain)
    entry_id = db.Column(db.String(36), db.ForeignKey('ai_entry.unique_id'), nullable=True)
    
    # Persona & Behavior
    role = db.Column(db.String(20), default='worker') # supervisor, worker (legacy)
    specialty = db.Column(db.String(100), default='general')
    system_prompt = db.Column(db.Text().with_variant(LONGTEXT, "mysql", "mariadb"), default='You are a helpful assistant.')
    temperature = db.Column(db.Float, default=0.7)
    max_tokens = db.Column(db.Integer, default=2048)

    # v6 Pipeline Role & Configuration
    pipeline_role = db.Column(db.String(20), default='worker')  # router, planner, executor, synthesizer, worker
    model_tier = db.Column(db.String(20), default='standard')   # lightweight, standard, heavy
    model_name = db.Column(db.String(128), default='')           # Override entry model_name if set (from role preset)
    tool_access = db.Column(db.String(20), default='auto')      # all, none, assigned, auto
    
    # Provider-specific configuration and auth tokens
    custom_options_json = db.Column(db.Text().with_variant(LONGTEXT, "mysql", "mariadb"), default='{}')
    
    is_activated = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # GridStack layout positions
    position_x = db.Column(db.Integer, default=0)
    position_y = db.Column(db.Integer, default=0)
    width = db.Column(db.Integer, default=24)
    height = db.Column(db.Integer, default=1)

    # Relationship to Entry
    entry = db.relationship('AIEntry', backref='agents')

    def __repr__(self):
        return f"<AIAgent(name={self.name}, role={self.role})>"


class AgentRolePreset(CRUDMixin, db.Model):
    """
    DB-managed pipeline role configurations for AI Agent setup UX.

    @phase active
    @stability stable
    """
    __tablename__ = 'agent_role_preset'
    __table_args__ = {'extend_existing': True}

    pipeline_role = db.Column(db.String(32), primary_key=True)
    ai_name_unique = db.Column(db.String(64), nullable=False)
    model_value = db.Column(db.String(128), nullable=False)
    temperature = db.Column(db.Float, default=0.7)
    max_tokens = db.Column(db.Integer, default=4096)
    role_description_en = db.Column(db.Text, nullable=True)
    role_description_ko = db.Column(db.Text, nullable=True)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f"<AgentRolePreset(pipeline_role={self.pipeline_role}, model={self.model_value})>"


class AIHistory(CRUDMixin, db.Model):
    """
    Logs every reasoning cycle.

    @phase active
    @stability stable
    @dependency AIAgent
    """
    __tablename__ = "ai_history"
    __table_args__ = {'extend_existing': True}

    id = db.Column(db.Integer, unique=True, primary_key=True)
    unique_id = db.Column(db.String(36), nullable=False, unique=True, default=set_uuid)
    agent_id = db.Column(db.String(36), db.ForeignKey('ai_agent.unique_id'), nullable=False)
    
    goal = db.Column(db.Text, nullable=False)
    insight = db.Column(db.Text().with_variant(LONGTEXT, "mysql", "mariadb"))
    
    actions_json = db.Column(db.Text().with_variant(LONGTEXT, "mysql", "mariadb"), default='[]')
    status = db.Column(db.String(20), default='proposed') 
    execution_result = db.Column(db.Text, default='')
    metadata_json = db.Column(db.Text().with_variant(LONGTEXT, "mysql", "mariadb"), default='{}')
    
    # v2.1: Conversation Threading
    thread_id = db.Column(db.String(36), nullable=True, index=True)
    message_type = db.Column(db.String(20), default='ai') # ai, user, system, assistant

    # v2.2: Per-user isolation (REQ-1) — nullable for backward compat with legacy records
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True, index=True)

    timestamp = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    def __repr__(self):
        return f"<AIHistory(goal={self.goal[:20]}..., status={self.status})>"


# @ANCHOR: AI_ROLE_CONFIG_MODEL
class AIRoleConfig(CRUDMixin, db.Model):
    """
    Layer 2 (Global Dynamic) — Runtime overrides for AI role system_prompt and specialty.
    Only rows that differ from YAML seed defaults (aot/config/ai_role_config.yaml) need to exist.
    Ref: SBS-002_V2_STRATEGY (layer_2_global_dynamic.tables[AIRoleConfig])

    @phase active
    @stability stable
    """
    __tablename__ = "ai_role_config"
    __table_args__ = {'extend_existing': True}

    id = db.Column(db.Integer, primary_key=True)
    role_key = db.Column(db.String(50), nullable=False, unique=True)
    system_prompt = db.Column(db.Text().with_variant(LONGTEXT, "mysql", "mariadb"), nullable=True)
    specialty = db.Column(db.Text, nullable=True)
    is_active = db.Column(db.Boolean, default=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f"<AIRoleConfig(role_key={self.role_key}, is_active={self.is_active})>"


# @ANCHOR: AI_ACTION_REGISTRY_MODEL
class AIActionRegistry(CRUDMixin, db.Model):
    """
    Layer 2 (Global Dynamic) — Runtime overrides for action routing and eligibility flags.
    Only rows that differ from YAML seed defaults (aot/config/ai_action_registry.yaml) need to exist.
    synced_from_mcp: set by REF-004 Auto-Sync Trigger (MCPBridgeService post-connect).
    Ref: SBS-002_V2_STRATEGY (layer_2_global_dynamic.tables[AIActionRegistry])

    @phase active
    @stability stable
    """
    __tablename__ = "ai_action_registry"
    __table_args__ = {'extend_existing': True}

    id = db.Column(db.Integer, primary_key=True)
    action_type = db.Column(db.String(80), nullable=False, unique=True)
    is_rag_eligible = db.Column(db.Boolean, default=False)
    is_immediate = db.Column(db.Boolean, default=False)
    resolver_module = db.Column(db.String(200), default='')
    is_active = db.Column(db.Boolean, default=True)
    synced_from_mcp = db.Column(db.Boolean, default=False)
    last_synced_at = db.Column(db.DateTime, nullable=True)

    def __repr__(self):
        return f"<AIActionRegistry(action_type={self.action_type}, is_immediate={self.is_immediate})>"


# @ANCHOR: AI_RULE_MODEL
class AIRule(CRUDMixin, db.Model):
    """
    v3.1 Phase 3 — 3-tier evolving rule structure (enforcement layer).

    Language-style rules (advisory framing, citation, hedging) are enforced by
    PROMPT INJECTION, not sync regex — an active rule's `content` is a prompt
    fragment appended to the system prompt of matching roles at resolve time
    (brain_resolver, right after the philosophy preamble). See
    .local/reports/ai_architecture_v3_tier_proposal.md §4, §12-4.

    Layers:
      - constitution: immutable top principles (the philosophy preamble is the
        canonical constitution; DB constitution rows are rare, human-only).
      - enforcement: operator-approved concrete rules, injected into prompts.
      - learned: promoted from an approved AIRuleProposal (same injection
        behavior as enforcement; distinguished by `source`).

    Structural rules (tool permission / value range / P4) are NOT stored here —
    they live in the synchronous deterministic gate (safety_service / P4).

    @phase active
    @stability new
    """
    __tablename__ = "ai_rule"
    __table_args__ = {'extend_existing': True}

    id = db.Column(db.Integer, primary_key=True)
    unique_id = db.Column(db.String(36), nullable=False, unique=True, default=set_uuid)
    name = db.Column(db.String(120), nullable=False)
    layer = db.Column(db.String(20), default='enforcement')  # constitution | enforcement | learned
    # Which pipeline roles this rule's prompt fragment is injected for.
    # 'all' or a specific role (worker/synthesizer/chat/...). Mirrors PHILOSOPHY_ROLES scoping.
    role_scope = db.Column(db.String(30), default='all')
    inject_at = db.Column(db.String(30), default='system_prompt')  # Phase 3: system_prompt only
    content = db.Column(db.Text().with_variant(LONGTEXT, "mysql", "mariadb"), nullable=False)
    severity = db.Column(db.String(10), default='warn')  # info | warn (advisory prompt strength; block lives in the sync gate)
    is_active = db.Column(db.Boolean, default=True)
    source = db.Column(db.String(60), default='human')  # human | proposal:<proposal_unique_id>
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f"<AIRule(name={self.name}, layer={self.layer}, active={self.is_active})>"


# @ANCHOR: AI_RULE_PROPOSAL_MODEL
class AIRuleProposal(CRUDMixin, db.Model):
    """
    v3.1 Phase 3 — learned-rule layer. A proposed enforcement rule generated
    from accumulated evidence (advisory_audit violations recorded on AIHistory
    by Phase 2). category drives the approval path:
      - style  → auto-approved when evidence_count ≥ threshold and no conflict
                 (advisory-language framing is style) → becomes an active AIRule.
      - behavior / scope → pending (user-confirm) — never auto-applied.

    proposed_rule_text is a PROMPT FRAGMENT (not a regex) per §12-4.

    @phase active
    @stability new
    """
    __tablename__ = "ai_rule_proposal"
    __table_args__ = {'extend_existing': True}

    id = db.Column(db.Integer, primary_key=True)
    unique_id = db.Column(db.String(36), nullable=False, unique=True, default=set_uuid)
    proposed_rule_text = db.Column(db.Text().with_variant(LONGTEXT, "mysql", "mariadb"), nullable=False)
    category = db.Column(db.String(20), default='style')  # style | behavior | scope
    role_scope = db.Column(db.String(30), default='all')
    evidence_ids = db.Column(db.Text, default='[]')  # JSON list of AIHistory unique_ids
    evidence_count = db.Column(db.Integer, default=0)
    # Stable key that dedupes proposals for the same observed pattern across scan runs.
    pattern_key = db.Column(db.String(120), nullable=True, index=True)
    status = db.Column(db.String(20), default='pending')  # pending | auto_approved | approved | rejected
    created_by = db.Column(db.String(60), default='advisory_audit_generator')
    resulting_rule_id = db.Column(db.String(36), nullable=True)  # AIRule.unique_id once approved
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    reviewed_at = db.Column(db.DateTime, nullable=True)

    def __repr__(self):
        return f"<AIRuleProposal(pattern={self.pattern_key}, category={self.category}, status={self.status})>"


# @ANCHOR: AI_EXPERIENCE_MEMORY_MODEL
class AIExperienceMemory(CRUDMixin, db.Model):
    """
    v3.1 Phase 4 — tiered experience memory (proposal §7).

    The system's memory of HOW it's being used and where it goes wrong — the
    three memory types from the architecture proposal:
      - error   : the AI failed / was reworked (degraded response, CLARIFY
                  loop, user rejection). Feeds the rule loop as behavior
                  evidence (≥ threshold → pending AIRuleProposal for user
                  confirmation — never auto-applied, per §4).
      - emotion : user dissatisfaction / friction signals (re-question,
                  frustration markers). Tracked for satisfaction trend +
                  operator alert on drop.
      - usage   : recurring user goals / preferences (direction).

    Tiered by occurrence: hot (recent + frequent, injection-eligible) / warm /
    cold. `pattern_key` dedupes a recurring pattern into one row whose
    occurrence_count grows — that count is the "증거" the promotion + rule loop
    read. This is a fresh, working store; the older AIUserSemanticMemory path
    is dormant (its module is absent), so this does not build on it.

    @phase active
    @stability new
    """
    __tablename__ = "ai_experience_memory"
    __table_args__ = {'extend_existing': True}

    id = db.Column(db.Integer, primary_key=True)
    unique_id = db.Column(db.String(36), nullable=False, unique=True, default=set_uuid)
    signal_type = db.Column(db.String(20), default='error')  # error | emotion | usage
    pattern_key = db.Column(db.String(120), nullable=False, index=True)
    summary = db.Column(db.Text, nullable=True)
    occurrence_count = db.Column(db.Integer, default=1)
    importance = db.Column(db.Integer, default=1)
    tier = db.Column(db.String(10), default='cold')  # hot | warm | cold
    evidence_ids = db.Column(db.Text, default='[]')  # JSON list of AIHistory unique_ids
    facility_id = db.Column(db.String(36), nullable=True, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_seen_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f"<AIExperienceMemory(type={self.signal_type}, pattern={self.pattern_key}, count={self.occurrence_count}, tier={self.tier})>"


# @ANCHOR: AI_USAGE_METER_MODEL
class AIUsageMeter(CRUDMixin, db.Model):
    """
    v3.1 Phase 6 — per-connection monthly usage tally for budget governance
    (proposal §13-2-F). One row per (AIEntry, YYYY-MM). Cost is ESTIMATED
    (chars/4 ≈ tokens × pricing table) because the engines don't surface real
    API usage here — approximate, not billing-accurate, and stated as such.

    @phase active
    @stability new
    """
    __tablename__ = "ai_usage_meter"
    __table_args__ = {'extend_existing': True}

    id = db.Column(db.Integer, primary_key=True)
    entry_unique_id = db.Column(db.String(36), nullable=False, index=True)
    period = db.Column(db.String(7), nullable=False, index=True)  # 'YYYY-MM'
    estimated_cost_usd = db.Column(db.Float, default=0.0)
    request_count = db.Column(db.Integer, default=0)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f"<AIUsageMeter(entry={self.entry_unique_id}, period={self.period}, cost=${self.estimated_cost_usd:.4f})>"
