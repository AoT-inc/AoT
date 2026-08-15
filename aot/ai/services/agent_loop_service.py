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
import json
import logging
import re

logger = logging.getLogger(__name__)

MAX_STEPS = 6

# @ANCHOR: DEVICE_CONTROL_BOUNDARY_SIGNALS
# Conservative, high-confidence wording that a device-control request is RECURRING
# or CONDITION-based — in which case it belongs to a Function (create_function),
# not a one-off scheduler reservation. Deliberately narrow so a genuine one-off
# ('이번 토요일 3시', 'this Saturday') is NEVER intercepted. Used only to decide
# whether to ASK the user which they meant (never to silently redirect).
_RECUR_SIGNAL = re.compile(
    r'매일|매주|매달|매월|날마다|아침마다|저녁마다|주기적|정기적|반복|격일|이틀에|'
    r'every\s*day|everyday|\bdaily\b|\bweekly\b|each\s+(?:morning|day|evening|night)',
    re.IGNORECASE)
# Conditional = a threshold comparison. Requires BOTH a comparison word AND a
# sensor/measurement context — so a DURATION like '20분 이상 열어' (이상 = "or more",
# not a sensor threshold) is NOT mistaken for a condition. Both must match.
_COND_CMP = re.compile(
    r'이상|이하|미만|초과|넘으면|넘어가면|떨어지면|낮아지면|높아지면|낮으면|높으면',
    re.IGNORECASE)
_SENSOR_CTX = re.compile(
    r'온도|기온|지온|습도|수분|토양|조도|일사|이산화탄소|co2|\bec\b|이씨|\bph\b|산도|'
    r'풍속|풍향|수위|양액|humidity|temperature|moisture|sensor|센서',
    re.IGNORECASE)


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
    def _schedule_ambiguity_gate(actions):
        """@ANCHOR: SCHEDULE_ASK_USER_NUDGE
        If a schedule create/edit action names a LOCATION that does not resolve to
        a known entity, return (question, options) so the caller raises an ask_user
        turn INSTEAD of proposing a doomed action that would only fail post-approval.

        This is the deterministic half of '모호하면 ask_user로 확인' — the step prompt
        already ASKS the model to call ask_user when unsure, but a model that thinks
        a bare word like '온실' is a valid place proposes add_schedule anyway and the
        tool's own target-not-found guard then surfaces as a bare 'Failed'. Catching
        it here, before the approval card, turns that dead end into a real question
        with candidate places to pick from. Returns None when every schedule action's
        location resolves (or none was given — a farm-wide schedule needs no place).
        """
        from aot.ai.services.aot_data_tool_service import AoTDataToolService
        _SCHED_TOOLS = {'add_schedule', 'edit_schedule'}
        for a in (actions or []):
            if AgentLoopService._tool_name(a) not in _SCHED_TOOLS:
                continue
            p = a.get('params') or {}
            args = p.get('arguments') if isinstance(p.get('arguments'), dict) else p
            args = args or {}
            tname = (args.get('target_name') or args.get('location')
                     or args.get('zone_name') or args.get('place'))
            if not tname:
                continue  # farm-wide schedule — nothing to disambiguate
            try:
                tid, _tt, _rn, _lat, _lng = AoTDataToolService._resolve_note_target(tname)
            except Exception:
                tid = None
            if not tid:
                try:
                    cands = AoTDataToolService._geoshape_name_candidates(limit=12)
                except Exception:
                    cands = []
                try:
                    from flask_babel import gettext as _
                    q = _("'%(name)s' doesn't match a single known place in the system. "
                          "Which location did you mean?", name=tname)
                except Exception:
                    q = (f"'{tname}' doesn't match a single known place in the system. "
                         f"Which location did you mean?")
                return q, cands
        return None

    @staticmethod
    def _device_control_boundary_gate(command_text, actions):
        """@ANCHOR: DEVICE_CONTROL_BOUNDARY_NUDGE
        schedule_device_control is ONLY for one-off reservations. If the user's
        request implies RECURRENCE ('every day', '매일') or a CONDITION ('when
        humidity < 40%', '습도 이하') yet the model chose a one-off device schedule,
        that regular automation belongs to a Function (create_function). We do NOT
        silently redirect — building the right function needs details we can't
        assume — nor do we let a wrong one-off through; instead we ask the user
        which they meant, offering the Function vs one-off choice as options.
        On their reply the model builds create_function or the reservation.

        Returns (question, options) or None. Conservative: fires only on explicit
        recurrence/threshold wording (see _RECUR_SIGNAL/_COND_SIGNAL) so a genuine
        one-off request is never intercepted. Boundary is '매우 판단하기 어려운' →
        when a clear recurrence/condition signal is present, ASK rather than guess.
        """
        if not command_text:
            return None
        for a in (actions or []):
            if AgentLoopService._tool_name(a) != 'schedule_device_control':
                continue
            recur = bool(_RECUR_SIGNAL.search(command_text))
            cond = bool(_COND_CMP.search(command_text) and _SENSOR_CTX.search(command_text))
            if not (recur or cond):
                continue

            def _t(msgid, fallback):
                try:
                    from flask_babel import gettext as _g
                    return _g(msgid)
                except Exception:
                    return fallback
            if recur:
                q = _t("This looks like a recurring operation. Should I set it up as a "
                       "repeating automation (a Function), or reserve it just this once?",
                       "This looks like a recurring operation. Set it up as a repeating "
                       "automation (a Function), or reserve it just this once?")
                opts = [_t("Repeating automation (Function)", "Repeating automation (Function)"),
                        _t("Just this once", "Just this once")]
            else:
                q = _t("This looks like a condition-based operation. Should I set it up as a "
                       "conditional automation (a Function), or reserve it at a fixed time?",
                       "This looks like a condition-based operation. Set it up as a conditional "
                       "automation (a Function), or reserve it at a fixed time?")
                opts = [_t("Conditional automation (Function)", "Conditional automation (Function)"),
                        _t("Fixed-time reservation", "Fixed-time reservation")]
            return q, opts
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
            "NOTES vs KNOWLEDGE vs MEASUREMENTS — recorded notes/memos on a device or zone "
            "(specs someone wrote down, work logs, observations) live in this context under "
            "system_state.note_digests (each entity's FIRST + RECENT notes). When the user "
            "asks what is NOTED / recorded / written / 메모·노트·기록 about a specific entity, "
            "answer from note_digests, or call search_notes with target_name=<that device/zone "
            "name> to read the full/older notes. Do NOT use knowledge_search (that is the "
            "manual/domain library, not per-entity notes) or get_device_measurements (that is "
            "live sensor channels, not written notes) for this. NEVER say an entity has no note "
            "without first checking note_digests for it AND, if not found there, calling "
            "search_notes(target_name=...) — a wrong tool returning nothing is not evidence the "
            "note is absent.\n"
            "EQUIPMENT / 설비 DRAWN IN geo/design vs CONTROL DEVICES — the equipment placed on "
            "the map in geo/design (irrigation valves, sprinklers/drip emitters, pipes, fans, "
            "heaters/coolers, window/curtain motors) is a SEPARATE thing from control devices "
            "(Outputs/Inputs that appear in the spatial tree). When the user asks what "
            "equipment / 설비 / 관수장치 is installed / placed / drawn in an area, call "
            "get_map_equipment(area_name=<that site/zone>) FIRST — that is the design-info "
            "OVERVIEW (per area). ALWAYS distinguish the two irrigation methods precisely and "
            "report them separately — 스프링클러(sprinklers, spray heads) vs 점적(drip_emitters, "
            "along drip pipes); never collapse them into one generic 'emitter' number. Only "
            "escalate to get_map_equipment_detail(area_name=...) "
            "when the user asks something the summary can't give — an individual emitter's "
            "POSITION, the SPACING/간격, a radius, or a specific pipe's geometry. Do NOT answer "
            "from the spatial tree's control devices — a control Output valve (e.g. 'v111') is "
            "NOT the drawn irrigation equipment and must not be reported as the answer to a "
            "'관수장치/설비' question unless the user is clearly asking about that control device "
            "itself. For a facility's COMPUTED heating/cooling/ventilation design capacity, call "
            "get_facility_capacity(facility_name=...).\n"
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
    def _finish(agent_id, command_text, insight, thread_id, actions=None,
                extra_meta=None, steps=None, tool_log=None):
        """Shared terminal path — reuses the SAME dispatch/approval mechanism
        every other pipeline uses, so AgentLoopService's return shape is
        identical to process_natural_language_command's (drop-in for the
        chat route)."""
        from aot.ai.ai_dispatch_service import AIDispatchService
        meta = {'intent': 'AGENT_LOOP'}
        if extra_meta:
            meta.update(extra_meta)
        # 이 턴이 **몇 번 만에 끝났는지와 어떤 순서로 도구를 불렀는지**를 남긴다.
        #
        # 예전에는 최종 결과만 남아서, 루프가 12번 헤매다 답한 것과 한 번에
        # 맞힌 것이 기록상 똑같이 "1행" 이었다(2026-08-15 실측: 요청 311건 중
        # 대부분이 1턴으로 보였다). 그래서 "헤맸는가" 를 물을 근거가 아예
        # 없었고, 선례 학습의 성공 판정도 세울 수 없었다.
        #
        # metadata_json 에 넣으므로 마이그레이션이 필요 없다. 계측을 위해
        # 몽키패치를 운영에 올리지 않는다 — 루프가 자기 걸음 수를 아는 것이
        # 자연스럽고, 여기가 그 유일한 종료 지점이다.
        if steps is not None:
            meta['loop_steps'] = steps
        if tool_log is not None:
            meta['tool_sequence'] = [
                t.get('tool') or t.get('tool_name')
                for t in tool_log if isinstance(t, dict)][:40]
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
        seen_calls = {}  # (tool_name, json-args) -> tool_log record already produced this run
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
                                                thread_id, extra_meta=_meta,
                                                steps=step + 1, tool_log=tool_log)

            write_actions = [a for a in actions if AIActionService.requires_approval(AgentLoopService._tool_name(a))]
            if write_actions:
                # Ask-user nudge: a schedule action naming an unresolvable location
                # becomes a clarifying question (with candidate places) BEFORE the
                # approval card, instead of a post-approval 'Failed'. See
                # _schedule_ambiguity_gate.
                _amb = AgentLoopService._schedule_ambiguity_gate(write_actions)
                if _amb:
                    _q, _opts = _amb
                    logger.info(f"[AgentLoop] step {step}: schedule location ambiguous "
                                f"→ ask_user: {_q[:80]!r} options={_opts}")
                    return AgentLoopService._finish(
                        agent.unique_id, command_text, _q, thread_id,
                        extra_meta={'intent': 'CLARIFY', 'ask_user_options': _opts})

                # Boundary nudge: a recurring/conditional request that chose a one-off
                # schedule_device_control → ask whether it should be a Function instead.
                _bnd = AgentLoopService._device_control_boundary_gate(command_text, write_actions)
                if _bnd:
                    _q, _opts = _bnd
                    logger.info(f"[AgentLoop] step {step}: device-control boundary "
                                f"→ ask_user: {_q[:80]!r} options={_opts}")
                    return AgentLoopService._finish(
                        agent.unique_id, command_text, _q, thread_id,
                        extra_meta={'intent': 'CLARIFY', 'ask_user_options': _opts})

                # Stop the loop and propose. _dispatch_actions already splits any
                # remaining read actions in the same batch to immediate execution —
                # reused unchanged, so this loop never re-implements that logic.
                logger.info(f"[AgentLoop] step {step}: proposing "
                            f"{[AgentLoopService._tool_name(a) for a in write_actions]} for approval")
                return AgentLoopService._finish(agent.unique_id, command_text, last_insight,
                                                thread_id, actions=actions,
                                                steps=step + 1, tool_log=tool_log)

            # All actions are read tools — execute now, feed results back, keep looping.
            # Dedup by (tool_name, params) within this run: the model sometimes
            # re-requests a read tool it already called (e.g. because a prior
            # step's result was truncated out of the prompt) — re-running it
            # wastes a step's worth of latency/budget for an identical answer,
            # so reuse the cached record instead of calling it again.
            logger.info(f"[AgentLoop] step {step}: auto-executing read tools "
                        f"{[AgentLoopService._tool_name(a) for a in actions]}")
            for a in actions:
                key = (AgentLoopService._tool_name(a),
                       json.dumps(a.get('params') or {}, sort_keys=True, default=str))
                if key in seen_calls:
                    logger.info(f"[AgentLoop] step {step}: skipping duplicate call "
                                f"to {key[0]!r} — reusing this run's earlier result")
                    tool_log.append(seen_calls[key])
                    continue
                record = AgentLoopService._execute_read_action(a)
                seen_calls[key] = record
                tool_log.append(record)

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
