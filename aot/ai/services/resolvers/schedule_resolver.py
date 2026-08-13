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
                return self._wrap('add_schedule',
                                  AoTDataToolService.add_schedule_tool(**params))

            if action_type == 'schedule_device_control':
                return self._wrap('schedule_device_control',
                                  AoTDataToolService.schedule_device_control_tool(**params))

            return {"status": "error", "message": f"ScheduleResolver: unhandled action_type '{action_type}'"}

        except Exception as e:
            logger.error(f"[ScheduleResolver] {action_type} failed: {e}")
            return {"status": "error", "message": f"일정 등록 실패: {str(e)}"}

    # 두 도구 모두 예외를 던지지 않고 실패를 **반환값**으로 알린다:
    #   add_schedule_tool           → {"status":"needs_disambiguation","error":"target_not_found", ...}
    #   schedule_device_control_tool→ {"error":"..."}  (장치 없음/시간 파싱 실패/예외)
    # 예전에는 그걸 그대로 {"status":"success","result": <실패 페이로드>} 로 감쌌다.
    # 바깥 status 만 읽는 호출자(_execute_scheduled_action, execute_logged_action,
    # 스케줄러 상태 기록)에게는 전부 성공으로 보이므로, **아무 일정도 만들어지지
    # 않았는데 "등록 완료"가 기록된다.** VirtualToolResolver 는 같은 자리에서
    # 이미 result.get('error') 를 검사하고 있었다 — 이쪽만 빠져 있었다.
    _FAILED_INNER_STATUSES = frozenset({
        'error', 'failed', 'refused', 'needs_disambiguation', 'pending_approval',
    })

    @classmethod
    def _wrap(cls, label: str, res: Any) -> Dict[str, Any]:
        if isinstance(res, dict):
            inner = str(res.get('status', '')).lower()
            if res.get('error') or inner in cls._FAILED_INNER_STATUSES:
                msg = res.get('message') or res.get('error') or f"{label} did not create a schedule"
                logger.warning("[ScheduleResolver] %s returned a failure payload: %s", label, msg)
                return {"status": "error", "message": str(msg), "result": res}
        return {"status": "success", "result": res}
