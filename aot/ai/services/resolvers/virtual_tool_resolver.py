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
            #
            # 실패를 알리는 관행이 **둘**이다 — {"error": "..."} 와
            # {"status": "error"}. 여기서는 앞의 것만 봤다. 뒤의 모양으로
            # 실패한 도구는 {"status":"success","result":{"status":"error"}} 로
            # 감싸여 바깥 status 만 읽는 호출자에게 성공으로 보인다(예약 실행
            # 상태 기록이 그렇다). mcp_safety_gate.call_state() 는 같은 자리에서
            # 이미 두 관행을 함께 본다 — 판정 기준을 그쪽에 맞춘다.
            # 'needs_disambiguation' 은 여기서 실패로 보지 않는다 — resolve_target
            # 같은 읽기 도구의 **정상 결과**이고, 프롬프트가 그 status 를 보고
            # 사용자에게 되묻도록 안내한다. 그것이 "일정이 안 만들어졌다"는 뜻이
            # 되는 것은 ScheduleResolver 자리뿐이라, 판정도 거기서만 한다.
            if isinstance(result, dict):
                _inner = str(result.get('status', '')).lower()
                if result.get('error') or _inner in ('error', 'failed', 'refused',
                                                     'pending_approval'):
                    _msg = result.get('error') or result.get('message') or _inner
                    logger.warning(f"[VirtualToolResolver] {tool_name} returned error: {_msg}")
                    return {"status": "error", "message": str(_msg), "result": result}
            return {"status": "success", "result": result}
        except Exception as e:
            logger.error(f"[VirtualToolResolver] {tool_name} failed: {e}")
            return {"status": "error", "message": str(e)}
