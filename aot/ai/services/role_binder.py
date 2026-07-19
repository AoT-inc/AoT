# coding=utf-8
"""
RoleBinder — v1 auto-binder for the v3.1 tier architecture (Phase 0).

v1 is intentionally a no-op wrapper: it resolves the same agent that
AIAgentService.get_cached_agent() already resolves today, and additionally
surfaces the linked AIEntry's probed capabilities so callers (and future
Phase 1 T1 loop code) can make capability-aware decisions later without any
change to current routing behavior.

Do not add capability-based fallback/rejection logic here yet — that is
explicitly deferred until a phase that needs it (see
.local/reports/ai_architecture_v3_tier_proposal.md §13-2-A, "무변화 출발점").

@phase active
@stability new
@dependency AIAgentService.get_cached_agent, model_probe
"""
import logging

logger = logging.getLogger(__name__)


def resolve_agent_for_role(pipeline_role):
    """Resolve the active agent for a pipeline role — same result as
    AIAgentService.get_cached_agent(pipeline_role) today, plus a capability
    read for observability.

    Returns (agent, capabilities_dict). agent is None if no active agent is
    configured for the role (unchanged from current behavior — callers must
    keep handling that case as before).
    """
    from aot.ai.services.ai_agent_service import AIAgentService
    from aot.ai.services.model_probe import get_capabilities

    agent = AIAgentService.get_cached_agent(pipeline_role)
    if not agent:
        return None, {}

    entry = getattr(agent, 'entry', None)
    capabilities = get_capabilities(entry) if entry else {}

    if entry and not capabilities:
        logger.debug(
            f"[RoleBinder] role={pipeline_role} agent={agent.name} "
            f"entry={entry.name} has never been conformance-probed."
        )

    return agent, capabilities


def _role_has_working_agent(role):
    """True if `role` already has an active agent whose connection carries a
    key — i.e. that role already works and shouldn't be clobbered by gap-fill."""
    from aot.databases.models.ai import AIAgent
    for a in AIAgent.query.filter_by(pipeline_role=role, is_activated=True).all():
        entry = getattr(a, 'entry', None)
        if entry and entry.api_key:
            return True
    return False


def autobind_all_roles(entry_unique_id, cheapest_model=None, fill_missing_only=False):
    """v3.1 Phase 6 — the "one key → all roles" auto-binder (§13-2-A).

    Given ONE registered connection (AIEntry with a key), ensure every pipeline
    role has an active AIAgent bound to it, using each role's preset config.
    This is what lets a user register a single provider and have the whole tier
    stack work without hand-binding each role (the 3-box onboarding's system
    step). Idempotent: an existing role agent is re-pointed at this entry and
    re-activated rather than duplicated.

    fill_missing_only: when True (the ON-REGISTRATION mode), only bind roles
    that DON'T already have an active keyed agent — fill gaps without clobbering
    a role a user already set up (e.g. keep a custom executor). This is what the
    "register one key and it just works" flow uses.

    cheapest_model: optional model_name to force on every role (used by budget
    downgrade — bind all roles to the cheapest conformant model on this entry).

    Returns {role: agent_unique_id} for roles it (re)bound. Never raises.
    """
    try:
        from aot.databases.models.ai import AIEntry, AIAgent
        from aot.aot_flask.extensions import db
        from aot.ai.services.ai_agent_service import AIAgentService

        entry = AIEntry.query.filter_by(unique_id=entry_unique_id).first()
        if not entry:
            logger.warning(f"[RoleBinder] autobind: entry {entry_unique_id} not found.")
            return {}

        presets = AIAgentService.get_role_presets()
        bound = {}
        for role, preset in presets.items():
            # Gap-fill mode: skip roles that already have a working keyed agent.
            if fill_missing_only and _role_has_working_agent(role):
                continue
            model_name = cheapest_model or preset.get('model_value') or preset.get('model_name') or ''
            # Update ALL agents of this role (robust against duplicates — a stale
            # duplicate must not keep serving an expensive model after a
            # downgrade). Create one if none exists.
            existing = AIAgent.query.filter_by(pipeline_role=role).all()
            if fill_missing_only:
                existing = []  # role has no working agent → create a fresh one
            if not existing:
                agent = AIAgent(
                    name=f"{role.capitalize()} ({entry.name})",
                    pipeline_role=role,
                    role='supervisor' if role in ('synthesizer', 'worker') else 'worker',
                    specialty=preset.get('specialty', 'general'),
                    system_prompt=preset.get('system_prompt', 'You are a helpful assistant.'),
                    temperature=preset.get('temperature', 0.7),
                    max_tokens=preset.get('max_tokens', 2048),
                    model_tier=preset.get('model_tier', 'standard'),
                    tool_access=preset.get('tool_access', 'auto'),
                )
                db.session.add(agent)
                existing = [agent]
            for agent in existing:
                agent.entry_id = entry.unique_id
                agent.model_name = model_name
                agent.is_activated = True
            db.session.flush()
            bound[role] = existing[0].unique_id

        db.session.commit()
        # Invalidate the role→agent cache so new bindings take effect immediately.
        try:
            AIAgentService._agent_cache.clear()
        except Exception:
            pass
        logger.info(f"[RoleBinder] autobind: bound {len(bound)} roles to entry '{entry.name}'"
                    + (f" (forced model={cheapest_model})" if cheapest_model else ""))
        return bound
    except Exception as e:
        logger.error(f"[RoleBinder] autobind failed: {e}")
        return {}
