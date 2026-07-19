# coding=utf-8
# @ANCHOR: SCHEDULE_RESOLVER
"""
ScheduleResolver — handles add_schedule and schedule_device_control.
Delegates to AoTDataToolService (no direct DB writes here).
Ref: SBS-002_V2_STRATEGY (pluggable_resolver.resolvers[ScheduleResolver])
"""
import logging
from typing import Any, Dict, Optional

from aot.ai.services.resolvers.base_resolver import BaseActionResolver

logger = logging.getLogger(__name__)


class ScheduleResolver(BaseActionResolver):
    """
    Handles add_schedule and schedule_device_control actions.

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
        from aot.ai.services.aot_data_tool_service import AoTDataToolService

        try:
            if action_type == 'add_schedule':
                res = AoTDataToolService.add_schedule_tool(**params)
                return {"status": "success", "result": res}

            if action_type == 'schedule_device_control':
                res = AoTDataToolService.schedule_device_control_tool(**params)
                return {"status": "success", "result": res}

            return {"status": "error", "message": f"ScheduleResolver: unhandled action_type '{action_type}'"}

        except Exception as e:
            logger.error(f"[ScheduleResolver] {action_type} failed: {e}")
            return {"status": "error", "message": f"일정 등록 실패: {str(e)}"}
