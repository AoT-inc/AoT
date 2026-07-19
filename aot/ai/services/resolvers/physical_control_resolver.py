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
        """
        if result.get('status') == 'error':
            logger.error(
                f"[PC-099-ERROR][LAW_3][PHYSICAL_FAILED] MCP bridge returned error for tool='{tool_name}': "
                f"{result.get('message', '')}"
            )
            result['message'] = f"[PC-099-ERROR] Physical Execution Failed: {result.get('message', 'MCP bridge error')}"
            return result

        # MCP tool result format: {"status": "success", "result": {"content": [{"type": "text", "text": "..."}]}}
        mcp_result = result.get('result', {})
        content_list = mcp_result.get('content', [])

        outcome_text = ''
        for item in content_list:
            if isinstance(item, dict) and item.get('type') == 'text':
                outcome_text = item.get('text', '')
                break

        # Check for explicit hardware failure signals in the response
        _FAILURE_SIGNALS = ('error', 'fail', 'denied', 'exception', '오류', '실패', '거부')
        if outcome_text and any(sig in outcome_text.lower() for sig in _FAILURE_SIGNALS):
            logger.error(
                f"[LAW_3][PHYSICAL_FAILED] Hardware signal indicates failure for tool='{tool_name}': "
                f"{outcome_text[:300]}"
            )
            return {
                'status': 'error',
                'message': f"[PC-099-ERROR] Physical Execution Failed: {outcome_text[:300]}",
                'physical_outcome': 'failed',
            }

        logger.info(
            f"[LAW_3][PHYSICAL_VERIFIED] tool='{tool_name}' hardware execution confirmed. "
            f"Response: {outcome_text[:200] if outcome_text else '(no content)'}"
        )
        result['physical_outcome'] = 'success'
        return result
