# coding=utf-8
# @ANCHOR: MCP_TOOL_CALL_RESOLVER
"""
MCPToolCallResolver — handles non-physical MCP actions:
  mcp_tool_call (tool_name NOT IN PHYSICAL_TOOLS)
  mcp_resource_read
  mcp_prompt_get

Ref: SBS-002_V2_STRATEGY (pluggable_resolver.resolvers[MCPToolCallResolver])
     008_TASK_3_STEP4_RESOLVER_DESIGN_SUPPLEMENT (updated_resolver_table)
"""
import logging
from typing import Any, Dict, Optional

from aot.ai.services.resolvers.base_resolver import BaseActionResolver

logger = logging.getLogger(__name__)


def _is_builtin_server(server_id):
    """이 서버가 AoT 자기 자신인가.

    판별은 `command` 로 한다 — `aot_mcp_server.py` 를 띄우는 행이 곧 내장
    서버다(이름은 사람이 바꿀 수 있고, unique_id 는 설치마다 다르다).
    `ai_action_service` 가 매니페스트에서 같은 기준을 쓴다.
    """
    try:
        from aot.databases.models.mcp_server import MCPServer
        row = MCPServer.query.filter_by(unique_id=server_id).first()
        return bool(row and 'aot_mcp_server' in (row.command or ''))
    except Exception:
        return False


class MCPToolCallResolver(BaseActionResolver):
    """
    Generic (non-physical) MCP dispatcher. No approval gate.

    @phase active
    @stability stable
    @dependency MCPBridgeService
    """

    def execute(
        self,
        action_type: str,
        target_id: Optional[str],
        params: Dict[str, Any],
        context: Optional[Dict[str, Any]],
        approved: bool = False,
    ) -> Dict[str, Any]:
        from aot.ai.services.mcp_bridge_service import MCPBridgeService

        if action_type == 'mcp_tool_call':
            server_id = target_id
            tool_name = params.get('tool_name')
            arguments = params.get('arguments') or params.get('params') or {}
            agent_uid = params.get('agent_unique_id')

            if not server_id or not tool_name:
                return {"status": "error", "message": "Missing server_id or tool_name for MCP call"}

            # AoT 자기 서버는 **프로토콜을 거치지 않는다.** 도구 구현이 이미
            # 이 프로세스 안에 있는데 subprocess 를 띄워 자기 자신에게
            # JSON-RPC 를 보내던 구조였다 — 앱을 한 벌 더 로드해 약 400MB 를
            # 쓰고, 두 프로세스의 코드 버전이 갈리고, MCP 쪽이 죽어도 내부
            # AI 는 system_tools 로 우회해 **아무도 모르는** 상태가 됐다.
            # 승인·감사·응답 캡은 tool_execution 이 그대로 건다(같은 게이트다).
            if _is_builtin_server(server_id):
                from aot.ai.services import tool_execution
                from flask import current_app
                res = tool_execution.execute_for_agent(
                    current_app._get_current_object(), tool_name, arguments,
                    agent_unique_id=agent_uid, server_id=server_id)
            else:
                res = MCPBridgeService.call_tool(server_id, tool_name, arguments,
                                                 agent_unique_id=agent_uid)
            if res.get('status') == 'success' and res.get('result', {}).get('_schema_warn'):
                logger.warning(
                    f"[MCPBridge][schema_warn] Tool '{tool_name}' schema validation failed "
                    f"from server {server_id}"
                )
            return res

        if action_type == 'mcp_resource_read':
            server_id = target_id
            uri = params.get('uri')
            if not server_id or not uri:
                return {"status": "error", "message": "Missing server_id or uri for MCP resource read"}
            return MCPBridgeService.read_resource(server_id, uri)

        if action_type == 'mcp_prompt_get':
            server_id = target_id
            prompt_name = params.get('prompt_name')
            arguments = params.get('arguments')
            if not server_id or not prompt_name:
                return {"status": "error", "message": "Missing server_id or prompt_name for MCP prompt get"}
            return MCPBridgeService.get_prompt_template(server_id, prompt_name, arguments)

        return {"status": "error", "message": f"MCPToolCallResolver: unhandled action_type '{action_type}'"}
