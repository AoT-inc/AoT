# coding=utf-8
# @ANCHOR: VIRTUAL_TOOL_RESOLVER
"""
VirtualToolResolver — routes virtual_tool_call to AoTDataToolService.
No subprocess — internal Python dispatch only.
Ref: SBS-002_V2_STRATEGY (pluggable_resolver.resolvers[VirtualToolResolver])
"""
import logging
from typing import Any, Dict, Optional

from aot.ai.services.resolvers.base_resolver import BaseActionResolver

logger = logging.getLogger(__name__)


class VirtualToolResolver(BaseActionResolver):
    """
    Routes virtual_tool_call to AoTDataToolService.

    @phase active
    @stability stable
    @dependency AoTDataToolService
    """

    def execute(
        self,
        action_type: str,
        target_id: Optional[str],
        params: Dict[str, Any],
        context: Optional[Dict[str, Any]],
        approved: bool = False,
    ) -> Dict[str, Any]:
        # [TASK_37] LLM sometimes puts tool_name in target_id — fallback
        tool_name = params.get('tool_name') or target_id
        arguments = params.get('arguments') or params.get('params') or {}

        # Flattened params fallback: LLM sometimes puts args directly in params
        if not arguments:
            # Exclude internal framework keys that are NOT tool arguments
            _meta_keys = {'tool_name', 'server_id', 'agent_unique_id', 'context'}
            _flat = {k: v for k, v in params.items() if k not in _meta_keys}
            if _flat:
                arguments = _flat
                logger.debug(
                    f"[VirtualToolResolver] Flattened params fallback for '{tool_name}': "
                    f"{list(arguments.keys())}"
                )

        if not tool_name:
            return {"status": "error", "message": "Missing tool_name for virtual_tool_call"}

        # @ANCHOR: TOOL_MAP — now DERIVED from the SSOT tool registry (Phase 1).
        # Was a hand-maintained dict duplicated across 5 places; build_tool_map()
        # resolves each declared tool's handler on AoTDataToolService. Add a tool
        # by declaring it once in aot/ai/services/tool_registry.py.
        from aot.ai.services.tool_registry import build_tool_map
        tool_map = build_tool_map()
        handler = tool_map.get(tool_name)
        if not handler:
            return {"status": "error", "message": f"Unknown virtual tool: {tool_name}"}

        # @ANCHOR: ARGUMENT_ALIAS_NORMALIZERS
        # LLM sometimes generates parameter names that differ from the actual
        # function signature.  Normalize them here before dispatch so the handler
        # never receives an unexpected keyword argument.
        # Pattern: { tool_name: { llm_key: real_key, ... } }
        _alias_maps: Dict[str, Dict[str, str]] = {
            'get_sensor_detail': {
                'device_id': 'loc_id',
                'unique_id': 'loc_id',
                'sensor_id': 'loc_id',
                'location_id': 'loc_id',
                'id':          'loc_id',
            },
        }
        if tool_name in _alias_maps:
            _am = _alias_maps[tool_name]
            _before = list(arguments.keys())
            arguments = {_am.get(k, k): v for k, v in arguments.items()}
            _after = list(arguments.keys())
            if _before != _after:
                logger.debug(
                    f"[VirtualToolResolver] alias-normalized '{tool_name}': "
                    f"{_before} → {_after}"
                )

        try:
            result = handler(**arguments)
            # @ANCHOR: VIRTUAL_TOOL_ERROR_PROPAGATION
            # If tool returns {"error": "..."} dict, propagate as error status
            # so execute_logged_action marks history as 'failed' and frontend shows ✗.
            if isinstance(result, dict) and result.get('error'):
                logger.warning(f"[VirtualToolResolver] {tool_name} returned error: {result['error']}")
                return {"status": "error", "message": result['error'], "result": result}
            return {"status": "success", "result": result}
        except Exception as e:
            logger.error(f"[VirtualToolResolver] {tool_name} failed: {e}")
            return {"status": "error", "message": str(e)}
