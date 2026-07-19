# coding=utf-8
# @ANCHOR: LEGACY_GUARD_RESOLVER
"""
LegacyGuardResolver — blocks deprecated 'output' and 'valve' action types.
Preserves LEGACY_BLOCKED error behaviour for backward compatibility.
Ref: SBS-002_V2_STRATEGY (pluggable_resolver.resolvers[LegacyGuardResolver])
"""
import logging
from typing import Any, Dict, Optional

from aot.ai.services.resolvers.base_resolver import BaseActionResolver

logger = logging.getLogger(__name__)


class LegacyGuardResolver(BaseActionResolver):
    """
    Returns LEGACY_BLOCKED error immediately.
    All hardware control must flow through 'mcp_tool_call' (Law 3).

    @phase active
    @stability stable
    """

    def execute(
        self,
        action_type: str,
        target_id: Optional[str],
        params: Dict[str, Any],
        context: Optional[Dict[str, Any]],
        approved: bool = False,
    ) -> Dict[str, Any]:
        logger.warning(
            f"[LEGACY_GUARD][TASK_30] Blocked legacy '{action_type}' action on "
            f"'{target_id}'. Use mcp_tool_call with operate_device."
        )
        return {
            "status": "error",
            "message": (
                f"[LEGACY_BLOCKED] '{action_type}' action type is deprecated. "
                "Use 'mcp_tool_call' with tool_name='operate_device' to control hardware."
            ),
        }
