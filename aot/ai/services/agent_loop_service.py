# coding=utf-8
"""
AgentLoopService — Phase 1 of the AI orchestration redesign.
See docs/design/ai-agent-loop.md for the full design and rationale.

Replaces the router-enum + per-intent pipeline fan-out (Router → Planner →
Executor → Worker → Synthesizer, or run_fast_path's intent-hardcoded prompt)
with ONE bounded, stateful tool-calling loop: the model sees the full tool
catalog every step and decides what to call, `ask_user` is a first-class
tool it can call whenever unsure, and read tools auto-execute within the
turn while write/physical tools always go through the existing approval
gate (`AIDispatchService._dispatch_actions` — unchanged, reused as-is).

Model-agnostic (G5): this loop calls `engine.run_reasoning(context, prompt)`
— the SAME abstract method every engine (anthropic/gemini/openai/ollama/…)
already implements — so it works with whichever model the user has active,
with no per-model branching here. Gemini's own native function-calling has
one required safety fix (see gemini.py @ANCHOR: GEMINI_NATIVE_APPROVAL_GATE)
so it can never self-execute a tool that needs approval; every other engine
already only ever returns {insight, actions} without executing anything
itself, so this loop's approval gate is what actually runs the tool either
way — no engine gets special-cased at the orchestration layer.

Scope boundary (Phase 1, intentional — see design doc §Phase1/§Phase2):
catalog = virtual + native tools (AIActionService.get_action_manifest).
MCP tools already surface through that manifest if a server is active/
healthy — untested here, not excluded, just not a Phase-1 target. Engine-
level native tool-calling beyond the gemini fix above is Phase 2.
"""
import logging

logger = logging.getLogger(__name__)

MAX_STEPS = 6


class AgentLoopService:

    @staticmethod
    def is_canary_active(user_id=None):
        """True if THIS request should use the agent loop instead of the
        legacy pipeline. Master switch (agent_loop_enabled) + optional
        per-user allowlist (agent_loop_canary_user_ids, comma-separated
        User.id). Empty/unset allowlist while the switch is on means every
        user gets the new loop (fine for a local single-tenant install);
        a staged rollout populates the allowlist first. Fails safe to False
        on any error — a broken flag read must never silently change routing."""
        try:
            from aot.databases.models import AIGlobalSettings
            s = AIGlobalSettings.query.first()
            if not s or not getattr(s, 'agent_loop_enabled', False):
                return False
            allowlist = (getattr(s, 'agent_loop_canary_user_ids', '') or '').strip()
            if not allowlist:
                return True
            ids = {x.strip() for x in allowlist.split(',') if x.strip()}
            return str(user_id) in ids
        except Exception as e:
            logger.debug(f"[AgentLoop] is_canary_active check failed, defaulting off: {e}")
            return False

    @staticmethod
    def _resolve_agent(agent_id):
        from aot.databases.models import AIAgent
        from aot.ai.services.ai_agent_service import AIAgentService
        if agent_id and agent_id != 'auto':
            agent = AIAgent.query.filter_by(unique_id=agent_id, is_activated=True).first()
            if agent:
                return agent
        return (AIAgentService.get_cached_agent('worker')
                or AIAgentService.get_cached_agent('executor')
                or AIAgent.query.filter_by(is_activated=True).first())

    @staticmethod
    def _tool_name(action):
        """Extract a tool name from whatever shape the engine emitted it in —
        top-level tool_name, params.tool_name, params.arguments.tool_name, or
        (legacy) action_type. Mirrors the extraction used across the existing
        dispatch/approval code so classification never diverges from it."""
        if not isinstance(action, dict):
            return None
        p = action.get('params') or {}
        args = p.get('arguments') if isinstance(p.get('arguments'), dict) else {}
        return (action.get('tool_name') or p.get('tool_name')
                or args.get('tool_name') or action.get('action_type'))

    @staticmethod
    def _looks_like_question(text):
        """Heuristic: is this final answer actually a clarifying question the model
        wrote in prose (rather than calling ask_user)? Used only to tag the turn's
        intent metadata consistently — never changes the visible text. A trailing
        '?' / '？' is the language-neutral signal; kept deliberately conservative."""
        if not text:
            return False
        return text.rstrip().endswith(('?', '？'))

    @staticmethod
    def _extract_ask_user(actions):
        """Return (question, options) if any action is an ask_user call, else
        None. ask_user is intercepted here directly — never normalized/
        dispatched through execute_action — it has no real handler."""
        for a in (actions or []):
            if AgentLoopService._tool_name(a) != 'ask_user':
                continue
            p = a.get('params') or {}
            args = p.get('arguments') if isinstance(p.get('arguments'), dict) else p
            question = (args or {}).get('question') or a.get('insight') or ''
            options = (args or {}).get('options') or []
            return question, options
        return None

    @staticmethod
    def _execute_read_action(action):
        """Normalize + execute a single READ tool now (no approval needed —
        the caller already verified via AIActionService.requires_approval).
        Returns a compact {tool_name, arguments, result} record for the
        step-prompt's tool-result log."""
        from aot.ai.ai_routing_service import AIRoutingService
        from aot.ai.services.ai_action_service import AIActionService

        tool_name = AgentLoopService._tool_name(action)
        try:
            valid, err = AIRoutingService._validate_and_normalize_action(action)
            if not valid:
                return {"tool_name": tool_name, "error": err}
            result = AIActionService.execute_action(
                action.get('action_type'), action.get('target_id'), action.get('params'))
        except Exception as e:
            logger.exception(f"[AgentLoop] read-tool execution failed: {tool_name}")
            result = {"error": str(e)}
        p = action.get('params') or {}
        args = p.get('arguments') if isinstance(p.get('arguments'), dict) else {}
        return {"tool_name": tool_name, "arguments": args, "result": result}

    @staticmethod
    def _build_step_prompt(command_text, tool_log, step, history=None):
        """General instruction — no per-function/per-intent hardcoding. The
        model picks tools from the catalog in `context['capabilities']` on
        its own judgment; this prompt only states the RULES of the loop.

        `history` is rendered here as an EXPLICIT, readable transcript at the
        top of the prompt — NOT left to whatever attention the model gives
        chat_history buried inside the large Current-Context JSON blob that
        base_ai._build_prompt() dumps everything into. Same lesson already
        applied to the router's history injection (ai_routing_service.py
        ROUTER_CONVERSATION_CONTEXT): a JSON field is easy to skim past: a
        clearly labeled 'CONVERSATION SO FAR' block is not."""
        parts = []
        if history:
            lines = []
            for m in history[-6:]:
                role = 'You (assistant)' if m.get('role') in ('ai', 'assistant') else 'User'
                c = (m.get('content') or '').strip().replace('\n', ' ')
                if c:
                    lines.append(f"{role}: {c[:300]}")
            if lines:
                parts.append(
                    "CONVERSATION SO FAR (most recent last):\n" + "\n".join(lines) + "\n\n"
                    "If YOUR last message above asked a clarifying question, the CURRENT "
                    "user message below is almost certainly the answer to it, not a new "
                    "topic — resolve the current message against that earlier exchange "
                    "before deciding what to do.\n")
        parts += [
            f'USER REQUEST: "{command_text}"\n',
            "You have the full tool catalog in this context's 'capabilities'. Decide, "
            "using your own judgment, what — if anything — to call:\n"
            "1. If you need information to answer or act, call a READ tool. Its result "
            "will be given back to you and you can call more tools or finish.\n"
            "2. If the request is AMBIGUOUS (unclear which zone/device/entity, unclear "
            "what exactly to do, or a verification question you cannot resolve from "
            "context) — CALL THE 'ask_user' TOOL. Do NOT just write the question as your "
            "answer; actually call the tool so the user gets a proper prompt. When there "
            "is a short list of likely answers (candidate zone names, a yes/no), pass them "
            "in 'options' so the user can pick. Example call: ask_user with arguments "
            '{\"question\": \"Which zone did you mean?\", \"options\": [\"3-1\", \"3-2\", \"1-1\"]}. '
            "This is not a fallback — it is the correct move whenever you are not "
            "confident. Do NOT guess and do NOT invent data to fill the gap.\n"
            "3. If the request needs a write/control/creation action, call that tool — "
            "it will be proposed for the user's approval, not executed immediately.\n"
            "4. When you have enough to answer, return your final answer as 'insight' "
            "with an empty 'actions' list.\n"
            "CRITICAL — RESUMING AFTER YOUR OWN QUESTION: check 'chat_history'. If your "
            "OWN last turn there asked the user a clarifying question (e.g. you called "
            "ask_user), the CURRENT user message is very likely their ANSWER to that "
            "question, not a brand-new unrelated request — even if it is short and "
            "names only a location/device/value with no verb. In that case, COMBINE it "
            "with the ORIGINAL request from earlier in chat_history and complete THAT "
            "original request now (e.g. you asked which zone to save a note in, they "
            "replied with a zone name → now actually call create_note for that zone — "
            "do NOT treat the zone name as a new query about that zone).\n"
            "CRITICAL: Never state a sensor reading, status, or fact you have not just "
            "retrieved via a tool THIS turn or already have in conversation history. If "
            "you don't know, call a tool or call ask_user — do not invent an answer.\n"
            "CRITICAL — VERIFY, DON'T ASSUME, WHEN CONFIRMING SOMETHING EXISTS: a tool call "
            "succeeding is NOT the same as the specific thing you're being asked about being "
            "present in its result. If the user asks whether something specific was recorded/"
            "saved/exists (a note, a device, a setting, anything), and a tool above returned a "
            "LIST, you must actually find that specific item BY ITS ACTUAL CONTENT in that "
            "list before saying yes — do not answer 'yes, confirmed' just because the list is "
            "non-empty, because a similar item is in it, or because you (or an earlier turn) "
            "said it was created. If it is not clearly there, say plainly that it is not — "
            "never affirm something you have not actually matched against real tool output.\n"
            "Respond in the SAME language as the user's request."
        ]
        if tool_log:
            import json
            parts.append("\nTOOL RESULTS SO FAR THIS TURN (read every list here carefully "
                          "before confirming whether a specific item is present):\n" +
                          json.dumps(tool_log, ensure_ascii=False, indent=2, default=str)[:6000])
        if step >= MAX_STEPS - 2:
            parts.append("\nYou are near the step limit — wrap up with your best answer "
                          "or a single most-useful tool call now.")
        return "\n".join(parts)

    @staticmethod
    def _finish(agent_id, command_text, insight, thread_id, actions=None, extra_meta=None):
        """Shared terminal path — reuses the SAME dispatch/approval mechanism
        every other pipeline uses, so AgentLoopService's return shape is
        identical to process_natural_language_command's (drop-in for the
        chat route)."""
        from aot.ai.ai_dispatch_service import AIDispatchService
        meta = {'intent': 'AGENT_LOOP'}
        if extra_meta:
            meta.update(extra_meta)
        dispatch_res = AIDispatchService._dispatch_actions(
            agent_id=agent_id, goal=command_text, insight=insight or '',
            actions=actions or [], thread_id=thread_id, message_type='ai', metadata=meta)
        return {
            "status": "success",
            "insight": insight or '',
            "proposed_actions": dispatch_res.get('proposed', []),
            "immediate_results": dispatch_res.get('immediate_results', []),
            "draft_job_ids": dispatch_res.get('draft_ids', []),
            "history_id": dispatch_res.get('history_id'),
            # Surface the clarification options so the chat route/frontend can
            # render them as clickable buttons (ask_user with options). Empty
            # list when this turn isn't an ask_user.
            "ask_user_options": (meta.get('ask_user_options') or []),
            "_intercept": "agent_loop",
        }

    @staticmethod
    def run(command_text, thread_id=None, page_context=None, agent_id='auto'):
        """Entry point. Bounded loop over engine.run_reasoning — see module
        docstring. Returns the same result shape as
        AIAgentService.process_natural_language_command."""
        from aot.ai.services.ai_agent_service import AIAgentService
        from aot.ai.services.ai_action_service import AIActionService
        from aot.ai.services.ai_context_service import AIContextService

        agent = AgentLoopService._resolve_agent(agent_id)
        if not agent:
            return {"status": "error", "message": "No active AI agent available"}
        engine = AIAgentService.get_engine(agent.unique_id)
        if not engine:
            return {"status": "error", "message": "Engine initialization failed"}

        history = AIAgentService.get_thread_history(thread_id, limit=10) if thread_id else []
        manifest = AIActionService.get_action_manifest(agent_unique_id=agent.unique_id, is_slim=True)
        tier = getattr(agent, 'model_tier', 'standard')
        try:
            system_state = AIContextService.get_master_context(focused_target=page_context, tier=tier)
        except Exception as e:
            logger.warning(f"[AgentLoop] system_state build failed, continuing without it: {e}")
            system_state = {}

        tool_log = []
        last_insight = ''
        for step in range(MAX_STEPS):
            context = {
                "system_state": system_state,
                "capabilities": manifest,
                "chat_history": history,
                "user_command": command_text,
                "page_context": page_context,
            }
            prompt = AgentLoopService._build_step_prompt(command_text, tool_log, step, history=history)
            try:
                result = engine.run_reasoning(context, prompt) or {}
            except Exception as e:
                logger.exception("[AgentLoop] engine.run_reasoning failed")
                return {"status": "error", "message": str(e)}

            actions = result.get('actions') or []
            # Normalize every action's action_type up front (SSOT-authoritative
            # resolver, idempotent — the read path re-runs it in
            # _execute_read_action). Doing it here too means a WRITE action the
            # LLM mislabeled — e.g. action_type='mcp_tool_call' guessed from a
            # tool-name prefix like 'smartfarmkorea_lookup' → server
            # 'smartfarmkorea' — is corrected to virtual_tool_call BEFORE it is
            # proposed for approval, so it doesn't fail on post-approval dispatch.
            from aot.ai.ai_routing_service import AIRoutingService as _ARS
            for _a in actions:
                if isinstance(_a, dict):
                    try:
                        _ARS._validate_and_normalize_action(_a)
                    except Exception:
                        pass
            insight = (result.get('insight') or '').strip()
            if insight:
                last_insight = insight

            ask = AgentLoopService._extract_ask_user(actions)
            if ask:
                question, options = ask
                logger.info(f"[AgentLoop] ask_user: {question[:80]!r} options={options}")
                return AgentLoopService._finish(
                    agent.unique_id, command_text, question or last_insight, thread_id,
                    extra_meta={'intent': 'CLARIFY', 'ask_user_options': options})

            if not actions:
                # Final answer — nothing left to do. If the model asked a question
                # in prose (instead of calling ask_user), still classify the turn
                # as a clarification so metadata is consistent — the visible text is
                # unchanged; only the intent tag differs.
                _meta = None
                if AgentLoopService._looks_like_question(last_insight):
                    _meta = {'intent': 'CLARIFY'}
                return AgentLoopService._finish(agent.unique_id, command_text, last_insight,
                                                thread_id, extra_meta=_meta)

            write_actions = [a for a in actions if AIActionService.requires_approval(AgentLoopService._tool_name(a))]
            if write_actions:
                # Stop the loop and propose. _dispatch_actions already splits any
                # remaining read actions in the same batch to immediate execution —
                # reused unchanged, so this loop never re-implements that logic.
                logger.info(f"[AgentLoop] step {step}: proposing "
                            f"{[AgentLoopService._tool_name(a) for a in write_actions]} for approval")
                return AgentLoopService._finish(agent.unique_id, command_text, last_insight, thread_id, actions=actions)

            # All actions are read tools — execute now, feed results back, keep looping.
            logger.info(f"[AgentLoop] step {step}: auto-executing read tools "
                        f"{[AgentLoopService._tool_name(a) for a in actions]}")
            for a in actions:
                tool_log.append(AgentLoopService._execute_read_action(a))

        # Bounded exit — never spin past MAX_STEPS. Instead of returning whatever
        # mid-progress narration `last_insight` happened to hold ("…를 확인하겠습니다"),
        # do ONE final synthesis pass that turns the tool results gathered so far
        # into an honest partial answer. Only runs on the (rare) cap-hit path.
        logger.warning(f"[AgentLoop] step cap ({MAX_STEPS}) reached for thread={thread_id}")
        closing = AgentLoopService._final_synthesis(engine, command_text, history, tool_log)
        if not closing:
            closing = last_insight
        if not closing:
            # i18n: gettext msgid in English; NEVER hardcode the reply language here.
            from flask_babel import gettext as _
            closing = _(
                "I went through several steps but couldn't reach a conclusion. "
                "Could you break the request down and try again?")
        return AgentLoopService._finish(agent.unique_id, command_text, closing, thread_id,
                                        extra_meta={'bounded_exit': True})

    @staticmethod
    def _final_synthesis(engine, command_text, history, tool_log):
        """One tool-LESS LLM call for the bounded-exit path: give the model the
        results it already gathered and ask for the best HONEST partial answer.
        No 'capabilities' in the context → the engine attaches no tools → the
        model must produce text, not another tool call (so this can't itself
        loop). Returns '' on any failure so the caller falls back."""
        import json
        try:
            hist_block = ""
            if history:
                lines = [f"{'Assistant' if m.get('role') in ('ai','assistant') else 'User'}: "
                         f"{(m.get('content') or '').strip().replace(chr(10),' ')[:200]}"
                         for m in history[-4:] if (m.get('content') or '').strip()]
                if lines:
                    hist_block = "CONVERSATION SO FAR:\n" + "\n".join(lines) + "\n\n"
            prompt = (
                hist_block +
                f'USER REQUEST: "{command_text}"\n\n'
                "You have reached the step limit for this turn. Using ONLY the tool "
                "results below and the conversation, give the user your best answer NOW. "
                "A PARTIAL answer is fine and expected — report what you DID find, and "
                "state plainly what you could not finish (do NOT promise to keep working, "
                "do NOT say you 'will' check something — this turn is ending). Do not "
                "invent anything not in the results. Respond in the user's language.\n\n"
                "TOOL RESULTS GATHERED THIS TURN:\n" +
                (json.dumps(tool_log, ensure_ascii=False, indent=2, default=str)[:6000] if tool_log
                 else "(no tools returned usable data)"))
            # Tool-less context: omit 'capabilities' so engines build no tool schema.
            result = engine.run_reasoning({"user_command": command_text}, prompt) or {}
            return (result.get('insight') or '').strip()
        except Exception as e:
            logger.debug(f"[AgentLoop] final synthesis failed: {e}")
            return ''
