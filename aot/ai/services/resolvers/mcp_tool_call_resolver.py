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

            res = MCPBridgeService.call_tool(server_id, tool_name, arguments, agent_unique_id=agent_uid)
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
