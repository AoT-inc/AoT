# coding=utf-8
# @ANCHOR: PHYSICAL_CONTROL_RESOLVER
"""
PhysicalControlResolver — handles mcp_tool_call when tool_name IN PHYSICAL_TOOLS.

Enforces explicit approval gate before delegating to MCPBridgeService.
Separating this from MCPToolCallResolver makes the approval boundary explicit
and auditable (Law 3 — Physical Truth).

Ref: 008_TASK_3_STEP4_RESOLVER_DESIGN_SUPPLEMENT (physical_control_resolver)
"""
import logging
import re
from typing import Any, Dict, Optional

from aot.ai.services.resolvers.base_resolver import BaseActionResolver
from aot.ai.services.resolvers.constants import PHYSICAL_TOOLS  # retained as fallback per Law 1

logger = logging.getLogger(__name__)


class PhysicalControlResolver(BaseActionResolver):
    """
    Handles physical hardware MCP tool calls.
    Raises SafetyViolation if approved=False (defense-in-depth over PC-089-GATE).

    @phase active
    @stability stable
    @dependency MCPBridgeService, SafetyService, DeviceCapabilityRegistry, VirtualExecutionEngine
    """

    def execute(
        self,
        action_type: str,
        target_id: Optional[str],
        params: Dict[str, Any],
        context: Optional[Dict[str, Any]],
        approved: bool = False,
    ) -> Dict[str, Any]:
        # @ANCHOR: PHYSICAL_APPROVAL_GATE
        tool_name = params.get('tool_name') or params.get('arguments', {}).get('tool_name')
        # M4_4: metadata-driven physical check (DeviceCapabilityRegistry wraps PHYSICAL_TOOLS as fallback)
        try:
            from aot.ai.services.device_capability_registry import DeviceCapabilityRegistry
            _is_physical = DeviceCapabilityRegistry.is_physical(tool_name)
        except ImportError:
            _is_physical = tool_name in PHYSICAL_TOOLS
            logger.warning("[PhysicalControl] DeviceCapabilityRegistry unavailable — PHYSICAL_TOOLS fallback active.")
        if _is_physical:
            if not approved:
                from aot.ai.services.safety_service import SafetyViolation
                raise SafetyViolation(
                    f"[APPROVAL_REQUIRED] Physical tool '{tool_name}' requires "
                    "explicit approval. Set approved=True via human-confirmed path only."
                )
        # @ANCHOR: VEE_INJECTION (005_EDGE_OPTIMIZED_SPECIFICATION / Phase 5 B-2 + C-3)
        # VEE is ADVISORY ONLY (advisory_only=True immutable). It does NOT replace
        # SafetyService.validate() which runs unconditionally below (SEC-001).
        try:
            from aot.config.feature_flags import capability_manager as _cm
            _vee_enabled = _cm.is_enabled('VEE')
        except ImportError:
            _vee_enabled = False
            logger.warning("[VEE][GUARD] CapabilityManager unavailable — VEE disabled.")
        if _vee_enabled:
            try:
                from aot.ai.services.virtual_execution_engine import (
                    VirtualExecutionEngine,
                    SimulationRequest,
                )
                _urgency = (context or {}).get('urgency_level', 'NORMAL')
                # M4_4: attach DeviceCapabilityProfile metadata into action_payload for VEE context
                _device_id = (
                    params.get('arguments', {}).get('device_id')
                    or params.get('arguments', {}).get('output_id')
                    or params.get('device_id')
                )
                _enriched_payload = dict(params)
                try:
                    from aot.ai.services.device_capability_registry import DeviceCapabilityRegistry as _DCR
                    _profile = _DCR.get_profile(_device_id) if _device_id else None
                    if _profile:
                        _enriched_payload['_device_profile'] = {
                            'device_class': _profile.device_class.value,
                            'risk_level': _profile.risk_level.value,
                            'vee_simulation_required': _profile.vee_simulation_required,
                        }
                except Exception:
                    pass  # profile enrichment is best-effort; VEE remains advisory
                _sim_req = SimulationRequest(
                    action_payload=_enriched_payload,
                    spatial_snapshot=(context or {}).get('spatial_snapshot', {}),
                    weather_forecast=(context or {}).get('weather_forecast', {}),
                    simulation_horizon_minutes=(context or {}).get(
                        'simulation_horizon_minutes', 30
                    ),
                    urgency_level=_urgency,
                )
                _vee_result = VirtualExecutionEngine().simulate(_sim_req)
                logger.info(
                    "[VEE] advisory confidence=%.3f proceed=%s conflicts=%s",
                    _vee_result.confidence_score,
                    _vee_result.proceed_recommended,
                    _vee_result.conflict_flags,
                )
            except Exception as _vee_exc:
                logger.warning("[VEE][ERROR] Simulation failed — continuing: %s", _vee_exc)
        # SEC-001: SafetyService.validate() is MANDATORY regardless of VEE result.
        # Runs unconditionally for both VEE-enabled and VEE-disabled profiles.
        from aot.ai.services.safety_service import SafetyService
        SafetyService.validate(action_type, target_id, params)
        # @ANCHOR: PHYSICAL_EXECUTION
        result = self._delegate_to_mcp_bridge(target_id, params)
        # @ANCHOR: LAW_3_PHYSICAL_VERIFICATION
        return self._verify_physical_outcome(tool_name, result)

    def _delegate_to_mcp_bridge(
        self,
        target_id: Optional[str],
        params: Dict[str, Any],
    ) -> Dict[str, Any]:
        from aot.ai.services.mcp_bridge_service import MCPBridgeService
        tool_name = params.get('tool_name')
        arguments = params.get('arguments') or params.get('params') or {}
        agent_uid = params.get('agent_unique_id')

        # @ANCHOR: PHYSICAL_CHANNEL_RESOLUTION (TASK_7_8 Step 2 / TASK_17 Step 1 diagnostic upgrade)
        # Resolve the physical output channel (relay_index) from OutputChannel model
        # before delegating to MCPBridgeService. Eliminates 'output channel doesn't exist: None'.
        device_id = arguments.get('device_id') or arguments.get('output_id')
        if device_id and 'channel' not in arguments:
            try:
                from aot.databases.models.output import OutputChannel
                oc = OutputChannel.query.filter_by(output_id=device_id).first()
                if oc is not None and oc.channel is not None:
                    arguments = dict(arguments)
                    arguments['channel'] = oc.channel
                    logger.info(
                        f"[PhysicalControl][CHANNEL_RESOLVED] device_id='{device_id}' "
                        f"→ channel={oc.channel} (OutputChannel.unique_id={oc.unique_id})"
                    )
                else:
                    # [PC-099-ERROR] Full DB diagnostic as required by TASK_17 Step 1
                    _diag = (
                        f"oc_row={oc!r}, "
                        f"channel={oc.channel if oc else 'NO_ROW'}, "
                        f"device_id='{device_id}'"
                    )
                    logger.error(
                        f"[PC-099-ERROR][CHANNEL_NULL] No valid OutputChannel for "
                        f"device_id='{device_id}'. DB diagnostic: {_diag}. "
                        f"MCP payload will be sent without 'channel' key."
                    )
            except Exception as _ch_err:
                logger.error(
                    f"[PC-099-ERROR][CHANNEL_LOOKUP_FAILED] OutputChannel query failed "
                    f"for device_id='{device_id}': {_ch_err}"
                )

        return MCPBridgeService.call_tool(
            target_id, tool_name, arguments, agent_unique_id=agent_uid
        )

    def _verify_physical_outcome(
        self,
        tool_name: Optional[str],
        result: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        [023_STEP_4][LAW_3] Verify that the hardware returned a physical SUCCESS signal.
        Parses MCP protocol content payload for explicit failure keywords.
        'Fake Success' (bridge returned ok but hardware failed) is prohibited.

        키워드만으로는 못 잡는 미실행이 셋 있었다 (2026-08-13 감사):
          1. 승인 게이트 응답 — {"status":"pending_approval", ... "It was NOT
             executed ..."}. 실패 어휘가 한 글자도 없어 그대로 통과했다.
             이것이 지도 위젯 예약 6건이 장치를 못 켠 채 COMPLETED 로 기록된
             경로다.
          2. MCP 표준 오류 플래그 `isError: true` — 브리지가 읽지 않아
             {"status":"success"} 로 감싸여 온다.
          3. **내용이 아예 없는 응답** — content 가 비면 outcome_text 가 ''
             이라 키워드 검사가 통째로 건너뛰어지고 "hardware execution
             confirmed" 로 기록됐다. 실행 증거가 없는 것을 성공이라 부르는 것이
             정확히 PC-099 가 금지하는 것이다.
        """
        if result.get('status') == 'error':
            logger.error(
                f"[PC-099-ERROR][LAW_3][PHYSICAL_FAILED] MCP bridge returned error for tool='{tool_name}': "
                f"{result.get('message', '')}"
            )
            result['message'] = f"[PC-099-ERROR] Physical Execution Failed: {result.get('message', 'MCP bridge error')}"
            return result

        # MCP tool result format: {"status": "success", "result": {"content": [{"type": "text", "text": "..."}]}}
        mcp_result = result.get('result', {}) or {}
        content_list = mcp_result.get('content', []) or []

        # 텍스트 블록을 전부 모은다 — 첫 블록만 보고 break 하면 뒤 블록에 실린
        # 오류를 못 본다.
        outcome_text = '\n'.join(
            item.get('text', '') for item in content_list
            if isinstance(item, dict) and item.get('type') == 'text'
        ).strip()

        def _failed(reason: str) -> Dict[str, Any]:
            logger.error(
                f"[PC-099-ERROR][LAW_3][PHYSICAL_FAILED] tool='{tool_name}': {reason[:300]}"
            )
            return {
                'status': 'error',
                'message': f"[PC-099-ERROR] Physical Execution Failed: {reason[:300]}",
                'physical_outcome': 'failed',
            }

        # (2) MCP 표준 오류 플래그
        if mcp_result.get('isError'):
            return _failed(f"MCP tool reported isError=true: {outcome_text[:200]}")

        # (1) 실행되지 않았다고 응답이 스스로 말하는 경우. AoT MCP 서버는 모든
        # tools/call 에 call_state 를 찍으므로 그것이 정본이다
        # (mcp_safety_gate.CALL_STATES). 승인 대기·거부·만료는 전부 미실행이다.
        _not_run = self._response_says_not_executed(outcome_text)
        if _not_run:
            return _failed(f"tool responded but did NOT execute ({_not_run}): {outcome_text[:200]}")

        # (3) 실행 증거가 없는 응답
        if not outcome_text:
            return _failed(
                "MCP response carried no content — there is no evidence the hardware "
                "was actually operated (PC-099 forbids reporting this as success)")

        # Check for explicit hardware failure signals in the response
        _FAILURE_SIGNALS = ('error', 'fail', 'denied', 'exception', '오류', '실패', '거부')
        if any(sig in outcome_text.lower() for sig in _FAILURE_SIGNALS):
            return _failed(outcome_text)

        logger.info(
            f"[LAW_3][PHYSICAL_VERIFIED] tool='{tool_name}' hardware execution confirmed. "
            f"Response: {outcome_text[:200]}"
        )
        result['physical_outcome'] = 'success'
        return result

    # 승인 게이트/거부 어휘. call_state 가 정본이고, 그 키가 없는 (구버전이거나
    # 서드파티) 서버를 위해 reason_code·status 문자열도 함께 본다.
    _EXECUTED_CALL_STATES = frozenset({'executed', 'already_executed'})
    _CALL_STATE_RE = re.compile(r'["\']call_state["\']\s*:\s*["\']([a-z_]+)["\']')
    _NOT_RUN_MARKERS = (
        'pending_approval', 'awaiting_user', 'was NOT executed',
        'requires_approval', 'insufficient_role', 'write_disabled',
        'rate_limited', 'user_declined', 'confirmation_',
    )

    @classmethod
    def _response_says_not_executed(cls, outcome_text: str) -> Optional[str]:
        """응답이 '실행하지 않았다'고 말하면 그 근거를, 아니면 None."""
        if not outcome_text:
            return None
        for state in cls._CALL_STATE_RE.findall(outcome_text):
            if state not in cls._EXECUTED_CALL_STATES:
                return f"call_state={state}"
        low = outcome_text.lower()
        for mk in cls._NOT_RUN_MARKERS:
            if mk.lower() in low:
                return mk
        return None
