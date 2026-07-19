# coding=utf-8
# @ANCHOR: ACTION_RESOLVER_REGISTRY
"""
ActionResolverRegistry — routes action_type to the correct resolver.

Routing rules for mcp_tool_call (008_TASK_3_STEP4_RESOLVER_DESIGN_SUPPLEMENT):
  tool_name IN PHYSICAL_TOOLS  → PhysicalControlResolver (approval gate)
  tool_name NOT IN PHYSICAL_TOOLS → MCPToolCallResolver  (no gate)

resolve() returns None for unregistered action_types so that execute_action()
can fall through to its legacy if/elif chain for non-registered types.

Ref: SBS-002_V2_STRATEGY (pluggable_resolver.registry_class)
     008_TASK_3_STEP4_RESOLVER_DESIGN_SUPPLEMENT (registry_signature_update)
"""
import logging
from typing import Any, Dict, Optional

from aot.ai.services.resolvers.base_resolver import BaseActionResolver
from aot.ai.services.resolvers.constants import PHYSICAL_TOOLS
from aot.ai.services.resolvers.legacy_guard_resolver import LegacyGuardResolver
from aot.ai.services.resolvers.mcp_tool_call_resolver import MCPToolCallResolver
from aot.ai.services.resolvers.physical_control_resolver import PhysicalControlResolver
from aot.ai.services.resolvers.virtual_tool_resolver import VirtualToolResolver
from aot.ai.services.resolvers.schedule_resolver import ScheduleResolver
from aot.ai.services.resolvers.note_resolver import NoteResolver

logger = logging.getLogger(__name__)

# ── Singleton resolver instances ───────────────────────────────────────────
_LEGACY_GUARD = LegacyGuardResolver()
_MCP_TOOL_CALL = MCPToolCallResolver()
_PHYSICAL_CONTROL = PhysicalControlResolver()
_VIRTUAL_TOOL = VirtualToolResolver()
_SCHEDULE = ScheduleResolver()
_NOTE = NoteResolver()

class ActionResolverRegistry:
    """
    Static registry for routing action_type to the correct resolver.

    @phase active
    @stability stable
    @dependency PhysicalControlResolver, MCPToolCallResolver, VirtualToolResolver, ScheduleResolver, NoteResolver
    """

    _DISPATCH: Dict[str, BaseActionResolver] = {
        'output':                   _LEGACY_GUARD,
        'valve':                    _LEGACY_GUARD,
        'mcp_resource_read':        _MCP_TOOL_CALL,
        'mcp_prompt_get':           _MCP_TOOL_CALL,
        'virtual_tool_call':        _VIRTUAL_TOOL,
        'add_schedule':             _SCHEDULE,
        'schedule_device_control':  _SCHEDULE,
        'note':                     _NOTE,
        'abstract_plan':            _NOTE,
    }

    @classmethod
    def register(cls, action_type: str, resolver: BaseActionResolver) -> None:
        """Dynamically register a resolver for an action_type."""
        cls._DISPATCH[action_type] = resolver

    @classmethod
    def resolve(
        cls,
        action_type: str,
        target_id: Optional[str],
        params: Dict[str, Any],
        context: Optional[Dict[str, Any]],
        approved: bool = False,
    ) -> Optional[Dict[str, Any]]:
        """
        Route action_type to the appropriate resolver and return its result.
        Returns None if no resolver is registered for this action_type,
        allowing execute_action() to fall through to its legacy if/elif chain.

        Every call with approved=True for physical tools produces a log entry
        (audit_requirement from 008_TASK_3_STEP4_RESOLVER_DESIGN_SUPPLEMENT).
        """
        params = params or {}

        # ── Special routing: mcp_tool_call ─────────────────────────────────
        if action_type == 'mcp_tool_call':
            tool_name = (
                params.get('tool_name')
                or params.get('arguments', {}).get('tool_name')
                or (target_id if isinstance(target_id, str) else None)
            )
            if tool_name in PHYSICAL_TOOLS:
                if approved:
                    logger.info(
                        f"[ActionResolverRegistry][AUDIT] approved=True physical call: "
                        f"tool={tool_name}, target={target_id}"
                    )
                
                # --- P2-T2: VEE simulate() gate (advisory) ---
                try:
                    from aot.config.feature_flags import capability_manager
                    if capability_manager.is_enabled('VEE'):
                        from aot.ai.services.virtual_execution_engine import VirtualExecutionEngine, SimulationRequest
                        vee_req = SimulationRequest(
                            action_payload={'action_type': action_type, 'tool_name': tool_name, 'target_id': target_id, 'arguments': params},
                            spatial_snapshot=context.get('spatial_snapshot', {}) if context else {},
                            weather_forecast=context.get('weather_forecast', {}) if context else {}
                        )
                        vee_res = VirtualExecutionEngine().simulate(vee_req)
                        if not vee_res.proceed_recommended:
                            logger.warning(f"[ActionResolverRegistry] VEE advisory rejection for {tool_name}")
                        if context is None:
                            context = {}
                        context['vee_result'] = vee_res
                except ImportError:
                    pass

                resolver = _PHYSICAL_CONTROL
            else:
                resolver = _MCP_TOOL_CALL

            return resolver.execute(action_type, target_id, params, context, approved)

        # ── Static dispatch table ──────────────────────────────────────────
        resolver = cls._DISPATCH.get(action_type)
        if resolver is None:
            return None  # Not registered — caller falls through to legacy chain

        return resolver.execute(action_type, target_id, params, context, approved)
