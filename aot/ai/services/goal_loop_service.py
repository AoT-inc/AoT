# coding=utf-8
"""
GoalLoopService — goal-directed continuous loop (agentic T1).

Requirement: "T1 must set the user's request as a GOAL and keep processing tasks
until the goal is achieved. Completing in a single one-shot action forces the
user to re-approve/re-prompt repeatedly." And: reads (device discovery/lookup)
must NOT require approval — only create/control does.

What this adds over the one-shot fast path:
  - The request is recorded as an AITask GOAL (is_goal=True) so progress is
    tracked and (Phase B) a physical step can pause for approval and RESUME the
    same goal instead of starting over.
  - The reasoning runs with a RAISED read/RAG budget and a GOAL directive, so a
    request needing several discovery/read steps completes autonomously within
    one turn (read tools auto-run, no approval) instead of stalling at the 2-loop
    cap or asking the user to re-prompt.
  - Physical-control actions are still gated — but batched into a single approval
    for the whole goal, so the user approves once, not once per internal step.

Flag-gated (AIGlobalSettings.t1_goal_loop_enabled, default False). With the flag
off this module is never entered and behaviour is identical to before.

Phase A (here): autonomous within-turn goal completion + goal record + batched
approval. Phase B (follow-up): resume the goal after an approved physical step
executes, to chain multiple approval-gated actions to completion.

@phase active
@stability new
@dependency AIAgentService.run_fast_path, AITask
"""
import logging

logger = logging.getLogger(__name__)

# Intents the goal loop owns. DATA_QUERY only — deliberately.
#
# Phase B learning (measured): routing CONTROL through the goal-loop fast path is
# the WRONG vehicle. The fast path's deeper reasoning produced a different, less
# stable action shape each run — first unresolved planner-style placeholders
# ("$valve_device.results[0].id"), and after the deterministic device resolver
# fixed that, a legacy 'output' action_type that the LegacyGuardResolver blocks.
# The PROVEN control path (collaborative → operate_device → Executed) is stable
# and already gives single-approval control. So CONTROL stays on that path; the
# real "continuous CONTROL goal" is Phase B-2 — a post-approval continuation hook
# on the proven path (execute the approved step, then re-reason toward the goal
# for the next step), NOT forcing CONTROL through this fast-path loop.
GOAL_LOOP_INTENTS = frozenset({'DATA_QUERY'})

# Autonomous read/RAG budget for a goal (vs. the one-shot default of 2). Bounded
# so a goal can't loop forever; enough for discovery → resolve → act → verify.
_GOAL_MAX_RAG = 5

_GOAL_DIRECTIVE = (
    "\n[GOAL — pursue autonomously in THIS turn]: Treat the user's request as a goal to "
    "fully accomplish now. Use read/discovery tools (search_devices, get_device_list, "
    "get_sensor_detail, etc.) freely — they run automatically and NEVER need the user's "
    "approval. Call ONE tool, WAIT for its ACTUAL result, then use the concrete values you "
    "received (the real device UUIDs, readings) in your next step. "
    "CRITICAL: NEVER reference a tool's output with a placeholder/variable such as "
    "'$valve_device.results[0].unique_id' or '{{...}}' — the system does NOT resolve "
    "placeholders and will fail; only ever use a REAL value you have already received from a "
    "tool result. When you have the concrete device id you need, finish the goal: give the "
    "final answer, or propose the physical control action(s) with the RESOLVED device_id. Do "
    "NOT stop early, do NOT ask the user to re-prompt or wait, and do NOT merely say you WILL "
    "act — act now. Only physical control needs approval; reading/searching does not."
)


def is_enabled():
    """True if the goal loop flag is on. Fails safe to False."""
    try:
        from aot.databases.models import AIGlobalSettings
        s = AIGlobalSettings.query.first()
        return bool(s and getattr(s, 't1_goal_loop_enabled', False))
    except Exception as e:
        logger.debug(f"[GoalLoop] flag read failed, defaulting off: {e}")
        return False


def handles(intent):
    """Whether the goal loop should own this intent (flag on AND eligible intent)."""
    return intent in GOAL_LOOP_INTENTS and is_enabled()


def _open_goal(command_text, intent, thread_id):
    """Record the request as an AITask goal (in_progress). Returns the goal or
    None — goal tracking must never block the actual work."""
    try:
        from aot.databases.models import AITask
        goal = AITask(
            title=(command_text or 'AI goal')[:255],
            description=command_text or '',
            task_type='goal',
            is_goal=True,
            status='in_progress',
        )
        goal.save()
        return goal
    except Exception as e:
        logger.debug(f"[GoalLoop] could not open goal record: {e}")
        return None


def _close_goal(goal, result):
    """Mark the goal done / awaiting-approval based on the loop result."""
    if goal is None:
        return
    try:
        proposed = result.get('proposed_actions') if isinstance(result, dict) else None
        goal.status = 'awaiting_approval' if proposed else 'done'
        try:
            from aot.utils.time_utils import utc_now
            goal.end_date = utc_now() if goal.status == 'done' else None
        except Exception:
            pass
        goal.save()
    except Exception as e:
        logger.debug(f"[GoalLoop] could not close goal: {e}")


def run(command_text, intent, thread_id=None, page_context=None,
        router_insight=None, complexity='SIMPLE', supervisor_id=None):
    """Run one request as an autonomous goal. Returns the same result dict shape
    as run_fast_path / run_collaborative_reasoning so the entry point can return
    it directly. Falls back to the legacy collaborative pipeline on escalation,
    exactly like the one-shot path, so hard cases keep their existing handling."""
    from aot.ai.services.ai_agent_service import AIAgentService

    goal = _open_goal(command_text, intent, thread_id)

    loop_result = AIAgentService.run_fast_path(
        command_text, intent=intent, thread_id=thread_id, page_context=page_context,
        max_rag_override=_GOAL_MAX_RAG, goal_directive=_GOAL_DIRECTIVE,
    )

    status = loop_result.get('status')
    if status not in ('escalate', 'error'):
        loop_result['_goal_loop'] = True
        if goal is not None:
            loop_result['goal_id'] = goal.unique_id
        _close_goal(goal, loop_result)
        logger.info(
            f"[GoalLoop] intent={intent} completed autonomously "
            f"(rag_loops={loop_result.get('rag_loops', '?')}, status={status})."
        )
        return loop_result

    # Escalation → legacy pipeline (same fallback the one-shot path uses).
    logger.info(f"[GoalLoop] intent={intent} escalated to legacy pipeline: {loop_result.get('reason', '?')}")
    from aot.databases.models import AIAgent
    supervisor = None
    if supervisor_id:
        supervisor = AIAgent.query.filter_by(unique_id=supervisor_id).first()
    if not supervisor:
        supervisor = (AIAgent.query.filter_by(role='supervisor', is_activated=True).first()
                      or AIAgent.query.filter_by(is_activated=True).first())
    if not supervisor:
        return {"status": "error", "message": "No active AI agents available"}
    result = AIAgentService.run_collaborative_reasoning(
        supervisor.unique_id, command_text, thread_id=thread_id, page_context=page_context,
        intent=intent, router_insight=router_insight, complexity=complexity,
    )
    _close_goal(goal, result)
    return result
