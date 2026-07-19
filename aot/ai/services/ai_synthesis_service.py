# coding=utf-8
"""
AISynthesisService — Extracted synthesis methods from AIAgentService.

@ANCHOR: AI_SYNTHESIS_SERVICE
"""
import logging
import json
import re
from aot.databases.models.ai import AIAgent

logger = logging.getLogger(__name__)

class AISynthesisService:
    """
    Extracted synthesis methods from AIAgentService.
    Transforms raw execution data into user-friendly responses with verification.

    @phase active
    @stability stable
    @dependency AIAgentService, AIAgent
    """

    @staticmethod
    def run_synthesizer(execution_results, intent, original_command, plan=None, chat_history=None, worker_insights=None, proposed_actions=None):
        """
        v6 Synthesizer: Transforms raw execution data into user-friendly responses.
        Includes verification (source match, time validity, logic consistency)
        and self-correction (max 1 retry).

        Args:
            execution_results: List of dicts with step results from Executor/RAG
            intent: Router classification (e.g. 'DATA_QUERY', 'CONTROL', 'COMPOSITE')
            original_command: The user's original text
            plan: Optional Planner output for context
            chat_history: Optional conversation history

        Returns:
            dict with 'insight', 'actions', 'verification'
        """
        from aot.ai.services.ai_agent_service import AIAgentService
        synth_agent = AIAgent.query.filter_by(pipeline_role='synthesizer', is_activated=True).first()
        if not synth_agent:
            # Fallback: no synthesizer configured, return raw insight
            logger.info("[Synthesizer] No active synthesizer agent. Skipping verification.")
            return None

        # @ANCHOR: SYNTHESIZER_ERROR_CLASSIFICATION (TASK_9-B — PC-097 pre-scan)
        # Intercept PC-097 errors before LLM synthesis to prevent 'Hardware Offline' misdiagnosis.
        if execution_results:
            for _res in execution_results:
                if isinstance(_res, dict) and _res.get('error_code') in ['PC-097', 'PC-099']:
                    _is_pc099 = _res.get('error_code') == 'PC-099'
                    logger.warning(f"[TASK_9-J][{_res.get('error_code')}] Error detected. Bypassing LLM synthesis.")
                    return {
                        "insight": (
                            "장치 연결 또는 제어 로직에 오류가 발생했습니다. "
                            "브릿지 연결 상태를 확인 중입니다. 잠시 후 다시 시도해 주세요."
                        ) if _is_pc099 else (
                            "장치 제어를 위해 최신 상태 확인이 필요합니다. "
                            "시스템이 자동으로 장치를 검색합니다. 잠시 후 다시 시도해 주세요."
                        ),
                        "actions": [],
                        "verification": {"passed": False, "reason": f"{_res.get('error_code')}: Execution/Connectivity failure."}
                    }

        # v22.0: P1 Post-Execution Verification (Phase 4)
        # v24.0: Hard-Link Tool Output (Law 3: Physical Truth)
        has_success = False
        if intent in ['CONTROL', 'ACTION', 'SYSTEM_OPS']:
            if execution_results:
                for res in execution_results:
                    # Check for "Success" plus "Physical Proof" (note_id, task_id, etc.)
                    if isinstance(res, dict) and res.get('status') == 'success':
                        # v9-J: For CONTROL intent, physical_outcome MUST be success to pass gate.
                        # This enforces Law 3 (Physical Truth) via the Coordinator/Synthesizer.
                        if intent == 'CONTROL' and res.get('physical_outcome') != 'success':
                            logger.error(f"[TASK_9-J][StrictGuard] Success reported without physical_outcome=success. Skipping.")
                            continue
                        # status: 'success' was already gated by P2 verification in _dispatch_actions
                        has_success = True
                        break
                    elif isinstance(res, str) and "Result: {\"status\": \"success\"" in res:
                        # String results from RAG/FastPath also need verify
                        if any(k in res for k in ['note_id', 'task_id', 'id', 'unique_id', 'execution_result', 'data', 'readings']):
                            has_success = True
                            break
            
            # Note: We NO LONGER return early here. 
            # We allow the LLM to synthesize the failure context, but post-process the result.


        # v6: Build synthesizer context
        synth_context = {
            "execution_results": execution_results,
            "worker_insights": worker_insights, # v25.0: Injected for higher synthesis integrity
            "intent": intent,
            "original_plan": plan,
            "chat_history": chat_history,
            "verification_mode": True
        }
        synth_prompt = (
            f"Finalize the response for: {original_command}\n\n"
            "INSTRUCTIONS:\n"
            "1. Priority Source: Treat 'worker_insights' as the PRIMARY truth. Include all specific details, names, and values EXACTLY as reported. Do NOT summarize them away.\n"
            "2. Unit Preservation: If a worker reports 'area' in '㎡', you MUST use '㎡'. NEVER swap '㎡' for 'kWh' or vice versa. Unit-swapping is a CRITICAL error.\n"
            "3. Entity Distinction: Distinguish between a 'Site/Farm' (a place with zones/irrigation) and a 'Device/Input' (a sensor or software service). If they share a name, report on the Site's physical components (Zones, Pipes, Sprinklers) as the primary answer.\n"
            "4. Physical over Virtual: Prioritize physical infrastructure (valves, pipes) over virtual weather services if both are present in the context.\n"
            "5. Format: Respond ONLY with a JSON object containing 'insight' and 'verification'. No pre/post text.\n"
            "6. Language: Use the SAME language as the original command for 'insight'.\n"
            "7. Failure Mode: If you cannot find a clear answer, state what you DID find instead of guessing.\n"
            # [TASK_33][item_2] Data Aggregation
            "8. Data Aggregation: If execution_results contain raw ON/OFF state logs, "
            "calculate the total ON duration internally. Report ONLY the final computed result "
            "(e.g., '총 12분 가동'). NEVER report raw log entries or explain the calculation method.\n"
            # [TASK_33][item_3] Anti-Meta-Talk
            "9. Anti-Meta-Talk: NEVER explain database structures, query methods, or internal tool usage. "
            "If data was retrieved, report the result. If no data exists, state '데이터 없음'.\n"
            # @ANCHOR: SYNTHESIZER_ERROR_CLASSIFICATION (prompt rule — TASK_9-B / TASK_9-J)
            # @ANCHOR: SYNTH_TRUTH_TRANSLATOR (TASK_9-J — exact error code natural language mapping)
            "10. Error Code Rule: If execution_results contain error codes, apply the AoT Error Code Truth Table:\n"
            "    - PC-097 = 'Device Discovery required' (장치 검색 필요): The system attempted to control a device "
            "before discovering it. DO NOT report 'Hardware Offline'. Report: '장치 제어를 위해 먼저 장치 검색이 필요합니다. 시스템이 자동으로 장치를 검색합니다.'\n"
            "    - PC-099 = 'MCP Bridge physical connectivity error' (MCP 브릿지 물리 연결 오류): The MCP bridge "
            "cannot reach the physical device. DO NOT report 'Hardware Offline'. Report: 'MCP 브릿지 물리 연결 오류가 발생했습니다. 브릿지 연결 상태를 확인하세요.'\n"
            "    STRICT: Never substitute these codes with generic 'Hardware Offline' messages.\n"
        )

        try:
            engine = AIAgentService.get_engine(synth_agent.unique_id)
            if not engine:
                logger.error("[Synthesizer] Failed to initialize engine.")
                return None

            result = engine.run_reasoning(synth_context, synth_prompt)
            
            # v6: Self-Correction (Verifier) logic
            verification = result.get('verification', {})
            if verification and verification.get('needs_correction'):
                logger.info(f"[Synthesizer] Verification failed. Requesting correction for step {verification.get('retry_step_id')}")
                synth_context['_correction_attempt'] = True
                synth_context['_previous_verification'] = verification
                result = engine.run_reasoning(synth_context, synth_prompt)
                if result.get('verification'):
                    result['verification']['corrections_made'] = 1

            # v24.0: Law 3 Post-Processing (Physical Truth Enforcement)
            # [PD-089][TASK_30] Universal Draft Detection: all hardware control paths
            # Prevents '[ALARM: Execution Failed]' prefix when approval is merely pending.
            _CTRL_ACTION_TYPES_DIRECT = {'output', 'valve', 'control_output'}
            _DRAFT_TOOL_NAMES = {
                'operate_device', 'output_on', 'output_off',
                'set_output', 'control_output'
            }
            has_pending_draft = any(
                a.get('action_type') in _CTRL_ACTION_TYPES_DIRECT
                or (
                    a.get('action_type') in {'virtual_tool_call', 'mcp_tool_call'}
                    and a.get('params', {}).get('tool_name') in _DRAFT_TOOL_NAMES
                )
                or a.get('tool_name') in _DRAFT_TOOL_NAMES  # OPTION_D: top-level tool_name
                for a in (proposed_actions or [])
            )
            # @ANCHOR: APPROVAL_PENDING_PREFIX_GUARD  [2026-03-27]
            if proposed_actions:
                has_pending_draft = True
            if not has_success and not has_pending_draft and intent in ['CONTROL', 'ACTION', 'SYSTEM_OPS']:
                insight = result.get('insight', '')
                if insight:
                    import re
                    # 1. Strip hallucinated success claims (En/Ko)
                    success_patterns = [
                        r"(?i)(I have |I've )?successfully (turned|opened|closed|started|stopped|saved|added|sent|executed)\s*",
                        r"(?i)I (have |'ve )?(turned|opened|closed|started|stopped|saved|added|sent|executed)\s*",
                        r"(?i)(성공적으로|완료했습니다|적용했습니다|켰습니다|껐습니다|열었습니다|닫았습니다|등록했습니다|전송했습니다|추가했습니다|저장했습니다)\s*"
                    ]

                    for pattern in success_patterns:
                        insight = re.sub(pattern, "", insight).strip()
                    
                    # 2. Prepend mandatory failure status
                    is_cjk = any(ord(c) > 0x7F for c in insight)
                    prefix = "[실패: 명령 수행 불가] " if is_cjk else "[ALARM: Execution Failed] "
                    
                    if insight:
                        # Ensure first char is uppercase after stripping
                        insight = insight[0].upper() + insight[1:]
                    result['insight'] = prefix + insight
                    
                    # 3. Mark verification as failed
                    if 'verification' not in result:
                        result['verification'] = {}
                    result['verification']['passed'] = False
                    result['verification']['reason'] = "Physical Verification Failed (Law 3)"

            # @ANCHOR: SYNTHESIZER_INSIGHT_EXTRACTION (TASK_9-A — JSON leak guard)
            # Ensure insight is always clean text before returning, regardless of caller path.
            _raw_insight = result.get('insight', '')
            _clean_insight = _extract_clean_insight(_raw_insight)
            if _clean_insight != _raw_insight:
                result['insight'] = _clean_insight
                logger.warning("[TASK_9-A][SYNTH_GUARD] Extracted clean insight from Synthesizer raw output.")

            return result

        except Exception as e:
            err_msg = str(e)
            logger.error(f"[Synthesizer] Error: {err_msg}")
            
            # v6.3.3: Dynamic Fallback for Synthesizer
            if any(kw in err_msg for kw in ["Resource exhausted", "429", "Quota", "timeout", "connection"]):
                failing_entry_id = synth_agent.entry_id
                logger.warning(f"[Synthesizer] Hit failure on provider {failing_entry_id}. Attempting fallback...")
                
                alt_agent = AIAgent.query.filter(
                    AIAgent.is_activated == True,
                    AIAgent.entry_id != failing_entry_id,
                    AIAgent.pipeline_role.in_(['synthesizer', 'planner', 'worker'])
                ).order_by(AIAgent.model_tier.desc()).first()
                
                if alt_agent:
                    try:
                        logger.info(f"[Synthesizer] Fallback using: {alt_agent.name}")
                        alt_engine = AIAgentService.get_engine(alt_agent.unique_id)
                        if alt_engine:
                            return alt_engine.run_reasoning(synth_context, synth_prompt)
                    except Exception as alt_e:
                        logger.error(f"[Synthesizer] Fallback to {alt_agent.name} failed: {alt_e}")
            
            return None
        except Exception as e:
            logger.error(f"[Synthesizer] Error: {e}")
            return None


    @staticmethod
    def _sanitize_final_response(insight: str) -> str:
        """
        @ANCHOR: FINAL_RESPONSE_SANITIZER
        [031_STEP_2] Intercept and block internal JSON structures or
        'Router Observation' strings that leak into the final user-facing insight.

        Rules (Law 3 — Physical Truth, UI Purity):
          1. Strip leading 'Router Observation: ...' lines.
          2. If insight is raw JSON (starts with '{'), extract the 'insight'
             field if present; otherwise replace with a generic NL message.
          3. If insight is empty after stripping, return a safe fallback.
        """
        if not insight:
            return insight

        # Rule 1: Strip 'Router Observation:' prefix lines
        lines = insight.split('\n')
        cleaned_lines = [l for l in lines if not l.strip().startswith('Router Observation:')]
        insight = '\n'.join(cleaned_lines).strip()

        # Rule 2: Detect raw JSON payload
        if insight.startswith('{'):
            try:
                parsed = json.loads(insight)
                # Extract the natural-language insight field if present
                inner = parsed.get('insight') or parsed.get('message') or parsed.get('text')
                if inner and isinstance(inner, str):
                    insight = inner.strip()
                    logger.info("[031_STEP_2][Sanitizer] Extracted 'insight' from leaked JSON.")
                else:
                    # No recoverable field — replace with generic NL
                    insight = "죄송합니다. 요청하신 내용을 처리했으나 응답 형식에 오류가 발생했습니다. 다시 시도해 주세요."
                    logger.warning("[031_STEP_2][Sanitizer] Raw JSON had no 'insight' field — replaced with generic NL.")
            except (json.JSONDecodeError, ValueError):
                # Not valid JSON — partial JSON leak; strip everything from '{' onward
                brace_idx = insight.find('{')
                if brace_idx > 0:
                    insight = insight[:brace_idx].strip()
                    logger.info("[031_STEP_2][Sanitizer] Stripped partial JSON suffix.")
                else:
                    # brace_idx == 0: entire string is a JSON-like structure but unparseable
                    insight = ""
                    logger.warning("[031_STEP_2][Sanitizer] Invalid JSON at start of insight — replacing with fallback.")
                # If the entire string is the brace (nothing before it), fallback
                if not insight:
                    insight = "요청 처리 결과를 반환하지 못했습니다. 다시 시도해 주세요."

        # Rule 3: Empty after cleaning
        if not insight.strip():
            insight = "답변을 생성하지 못했습니다. 잠시 후 다시 시도해 주세요."

        return insight


    @staticmethod
    def _generate_display_summary(action):
        """
        [TASK_5] Generate a human-friendly approval button label.
        e.g. '3구역 밸브 3분 가동', '조명 ON 예약 (09:00)'
        """
        try:
            params = action.get('params', {}) or {}
            tool_name = params.get('tool_name') or action.get('tool_name', '')
            action_type = action.get('action_type', '')
            args = params.get('arguments', {}) or params

            if tool_name == 'operate_device':
                device_id = args.get('device_id') or args.get('output_id') or args.get('unique_id')
                state = args.get('state', '')
                duration_sec = args.get('duration_seconds') or args.get('duration') or 0

                device_name = device_id
                if device_id:
                    from aot.databases.models import Output
                    dev = Output.query.filter_by(unique_id=device_id).first()
                    if dev:
                        device_name = dev.name

                duration_str = ''
                if duration_sec:
                    mins = int(duration_sec) // 60
                    secs = int(duration_sec) % 60
                    if mins > 0:
                        duration_str = f' {mins}분'
                        if secs > 0:
                            duration_str += f' {secs}초'
                    else:
                        duration_str = f' {secs}초'

                state_lower = str(state).lower()
                state_str = '가동' if state_lower in ('on', 'true', '1') else '중지' if state_lower in ('off', 'false', '0') else state

                return f"{device_name or '장치'} {state_str}{duration_str}".strip()

            if tool_name == 'schedule_device_control':
                device_id = args.get('device_id')
                scheduled_time = args.get('scheduled_time', '')
                state = args.get('state', '')
                device_name = device_id
                if device_id:
                    from aot.databases.models import Output
                    dev = Output.query.filter_by(unique_id=device_id).first()
                    if dev:
                        device_name = dev.name
                return f"{device_name or '장치'} {scheduled_time} 예약 ({state})".strip()

            if tool_name:
                return tool_name
            return action_type or '작업'
        except Exception:
            return (action.get('params', {}) or {}).get('tool_name') or action.get('action_type') or '작업'

def _extract_clean_insight(raw_text):
    """
    [TASK_9-A] Helper to extract clean natural language from potentially
    JSON-polluted or meta-talk-heavy LLM output.
    """
    if not raw_text:
        return ""
    
    # 1. If it's a JSON block, try to parse it
    if raw_text.strip().startswith('{'):
        try:
            data = json.loads(raw_text)
            return data.get('insight', data.get('message', raw_text))
        except:
            pass

    # 2. Strip common meta-prefixes
    prefixes = ["Router Observation:", "Plan:", "Insight:", "Response:"]
    clean_text = raw_text
    for p in prefixes:
        if clean_text.startswith(p):
            clean_text = clean_text[len(p):].strip()
    
    return clean_text
