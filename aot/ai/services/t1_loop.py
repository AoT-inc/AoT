# coding=utf-8
"""
T1UnifiedLoop — v3.1 tier architecture, Phase 1 (surgical scope).

Collapses the legacy CONTROL pipeline (router → planner → supervisor/workers
→ synthesizer, 4-5 single-shot LLM calls) into a single bounded agentic loop
(~2 calls: router + the loop). The loop is the SAME tested machinery that
already backs DATA_QUERY — run_fast_path — which does context-assembly once,
then run_reasoning() with read-only tool execution re-injected between
iterations, and produces the final user-facing answer directly. That removes
the separate synthesizer call (the "재생산" step) and the duplicate full-context
load that planner + supervisor each paid.

WHY THIS REUSES run_fast_path INSTEAD OF A NEW 300-LINE LOOP: run_fast_path
already contains the CONTROL-specific safety machinery this phase must NOT
regress — MCP physical-tool preflight (hard-lock escalation when offline),
device discovery enforcement, the [장치/시간/동작] approval-template guard, the
anti-hallucination "실행 완료 어투 금지" guard, and the P4 approval-gate split
that routes control tools to `proposed` rather than auto-executing. Rewriting
that from scratch would risk dropping a guard. This module's job is narrower:
own the ROUTING (which intents enter the loop) and the ESCALATION POLICY (when
to fall back to the legacy pipeline), so the loop becomes the front door and
the heavy pipeline becomes the exception — "escalation, not mandatory
pipeline" (see .local/reports/ai_architecture_v3_tier_proposal.md §2, §12-2).

Gated behind AIGlobalSettings.t1_unified_enabled (default False). With the
flag off, this module is never reached and behavior is identical to before.

Phase 1 scope is CONTROL only — the intent run_fast_path fully supports as a
primary path. SCHEDULE/COMPOSITE stay on the legacy pipeline until the loop
grows their intent-specific enforcement (follow-up). The enabled-intent set is
a module constant so widening it later is a one-line change.

@phase active
@stability new
@dependency AIAgentService.run_fast_path, AIAgentService.run_collaborative_reasoning
"""
import logging

logger = logging.getLogger(__name__)

# Intents that route through the unified loop when the flag is on. Kept
# deliberately narrow for Phase 1 (see module docstring). run_fast_path has
# first-class handling for CONTROL and DATA_QUERY; DATA_QUERY already routes
# to run_fast_path directly upstream, so only CONTROL needs to be added here.
T1_ENABLED_INTENTS = frozenset({'CONTROL'})


def is_enabled():
    """True if the T1 unified loop feature flag is on. Fails safe to False —
    any error reading settings leaves the legacy pipeline in charge."""
    try:
        from aot.databases.models import AIGlobalSettings
        settings = AIGlobalSettings.query.first()
        return bool(settings and getattr(settings, 't1_unified_enabled', False))
    except Exception as e:
        logger.debug(f"[T1Loop] flag read failed, defaulting off: {e}")
        return False


def handles(intent):
    """Whether the unified loop should handle this intent (flag on AND intent
    in the enabled set). Callers use this to decide whether to enter run()."""
    return intent in T1_ENABLED_INTENTS and is_enabled()


class T1UnifiedLoop:
    """Front door for intents the unified loop owns. Runs the bounded loop and
    falls back to the legacy pipeline on escalation — callers get the same
    result dict shape either way, so the branch is transparent to them."""

    @staticmethod
    def run(command_text, intent, thread_id=None, page_context=None,
            router_insight=None, complexity='SIMPLE', supervisor_id=None):
        """Route one command through the unified loop, falling back to the
        legacy collaborative pipeline if the loop escalates or errors.

        Returns the same dict shape as run_fast_path / run_collaborative_
        reasoning (status/insight/intent/proposed_actions/immediate_results/
        draft_job_ids/history_id), so the entry point can `return` it directly.
        """
        from aot.ai.services.ai_agent_service import AIAgentService

        # 1. Unified loop (run_fast_path is the tested loop engine).
        loop_result = AIAgentService.run_fast_path(
            command_text, intent=intent,
            thread_id=thread_id, page_context=page_context,
        )
        status = loop_result.get('status')
        if status not in ('escalate', 'error'):
            logger.info(
                f"[T1Loop] intent={intent} handled by unified loop "
                f"(rag_loops={loop_result.get('rag_loops', '?')}, "
                f"status={status}) — legacy planner/supervisor/synthesizer skipped."
            )
            loop_result['_t1_unified'] = True
            return loop_result

        # 2. Escalation → legacy pipeline (preserves all prior behavior for the
        #    hard cases run_fast_path deliberately refuses: MCP offline hard-lock,
        #    zero-tool responses, semantic-guard failures).
        logger.info(
            f"[T1Loop] intent={intent} escalated to legacy pipeline: "
            f"{loop_result.get('reason', '?')}"
        )
        return T1UnifiedLoop._legacy_fallback(
            command_text, intent=intent, thread_id=thread_id,
            page_context=page_context, router_insight=router_insight,
            complexity=complexity, supervisor_id=supervisor_id,
        )

    @staticmethod
    def _legacy_fallback(command_text, intent, thread_id, page_context,
                         router_insight, complexity, supervisor_id):
        """Invoke the legacy collaborative pipeline exactly as the entry point
        would have without the flag. Resolves a supervisor the same way the
        entry point does when one wasn't supplied."""
        from aot.ai.services.ai_agent_service import AIAgentService
        from aot.databases.models import AIAgent

        supervisor = None
        if supervisor_id:
            supervisor = AIAgent.query.filter_by(unique_id=supervisor_id).first()
        if not supervisor:
            supervisor = (
                AIAgent.query.filter_by(role='supervisor', is_activated=True).first()
                or AIAgent.query.filter_by(is_activated=True).first()
            )
        if not supervisor:
            return {"status": "error", "message": "No active AI agents available"}

        return AIAgentService.run_collaborative_reasoning(
            supervisor.unique_id, command_text,
            thread_id=thread_id, page_context=page_context,
            intent=intent, router_insight=router_insight, complexity=complexity,
        )
