# coding=utf-8
"""
mcp_server/tools/control.py — P4-1: 쓰기(제어) 도구 모음.

모든 도구는 safety_check() 통과 후 사용자 승인을 받아야 실행된다.

도구 목록:
  update_method_point   — DailyMultiPoint 곡선 제어점 수정
  request_manual_lock   — 수동 잠금 요청 (AI 자동제어 일시 정지)
  acknowledge_alert     — 경보 확인 처리

⚠ `set_vpd_target` 은 2026-09-06 에 뺐다. `custom_options['target_vpd']` 에
쓰기만 하고 아무도 읽지 않는 죽은 경로였다 — VPD 목표의 정본은 구획/프로그램
이고, env_coordinator 는 매 사이클 `_plot_targets()` 로 그것을 직접 읽는다
(코디네이터 자체 옵션에 목표를 중복 저장하지 않는다, 설계문서 D19 및
`docs/design/coordinator-plot-targets.md`). Method 곡선을 쓰는 VPD 목표는
`update_method_point` 로 바꾸고, 고정값 목표는 프로그램/구획 화면에서 바꾼다.
"""

from __future__ import annotations

import json
import logging
from typing import Optional

from aot.mcp_server import audit
from aot.mcp_server.safety import (
    WRITE_TOOLS,
    ConfirmationRequired,
    SafetyViolation,
    WriteDisabled,
    RateLimitExceeded,
    safety_check,
    confirm as safety_confirm,
    get_pending_confirmations,
)

logger = logging.getLogger(__name__)


def _write_gate(tool_name: str, params: dict, agent_id: str,
                reason: str = '', current_value: float | None = None) -> dict:
    """safety_check → audit → ConfirmationRequired 전파.

    Returns:
        {'pending': True, 'token_id': ..., 'expires_in': ..., 'message': ...}
    """
    try:
        safety_check(tool_name, params, agent_id, current_value=current_value)
        # safety_check 가 write 도구에서 None 을 반환하는 경우는 없음
        return {}
    except WriteDisabled as e:
        audit.log_call(tool_name, params, agent_id, 'write', reason)
        return {'error': 'write_disabled', 'message': str(e)}
    except SafetyViolation as e:
        audit.log_call(tool_name, params, agent_id, 'write', reason)
        return {'error': 'safety_violation', 'message': str(e)}
    except RateLimitExceeded as e:
        audit.log_call(tool_name, params, agent_id, 'write', reason)
        return {'error': 'rate_limit', 'message': str(e)}
    except ConfirmationRequired as e:
        uid = audit.log_call(tool_name, params, agent_id, 'write', reason,
                             confirmation_id=e.token_id)
        pending = get_pending_confirmations()
        token_info = next((p for p in pending if p['token_id'] == e.token_id), {})
        return {
            'pending': True,
            'token_id': e.token_id,
            'expires_in': token_info.get('expires_in', 60),
            'audit_id': uid,
            'message': (
                f'사용자 승인 필요 — UI 또는 confirm_action 도구로 승인하세요. '
                f'token_id={e.token_id}'
            ),
        }


# ─────────────────────────────────────────────────────────────────────────────
# update_method_point
# ─────────────────────────────────────────────────────────────────────────────

def update_method_point(
    method_id: str,
    point_index: int,
    new_value: float,
    reason: str = '',
    agent_id: str = 'ai_agent',
) -> dict:
    """DailyMultiPoint 곡선의 특정 제어점 VPD 값을 변경한다.

    Args:
        method_id:    Method.unique_id
        point_index:  제어점 인덱스 (0-based)
        new_value:    새 VPD 값 (kPa). 범위 0.0 ~ 3.0.
        reason:       변경 이유
        agent_id:     AI 에이전트 식별자

    Returns:
        pending 응답 또는 오류. 승인 후 _apply_method_point 로 적용.
    """
    params = {'method_id': method_id, 'point_index': point_index, 'new_value': new_value}

    # 시드 프리셋 보호
    is_seed = _check_seed_protection(method_id)
    if is_seed:
        return {
            'error': 'seed_protected',
            'message': (
                f'Method {method_id} is a seed preset (read-only). '
                'Duplicate it before editing.'
            ),
        }

    current_value = _get_method_point_value(method_id, point_index)

    gate = _write_gate('update_method_point', params, agent_id, reason, current_value)
    if gate:
        return gate

    return {'error': 'unreachable'}


def _check_seed_protection(method_id: str) -> bool:
    try:
        from aot.databases.models import Method
        from aot.utils.database import db_retrieve_table_daemon
        m = db_retrieve_table_daemon(Method, unique_id=method_id)
        return bool(m and m.name and m.name.startswith('SEED:'))
    except Exception:
        return False


def _get_method_point_value(method_id: str, point_index: int) -> float | None:
    try:
        from aot.databases.models import Method
        from aot.utils.database import db_retrieve_table_daemon
        m = db_retrieve_table_daemon(Method, unique_id=method_id)
        if m is None or not m.points_json:
            return None
        points = json.loads(m.points_json)
        if not isinstance(points, list) or point_index >= len(points):
            return None
        pt = points[point_index]
        return float(pt.get('value', pt.get('vpd', 0)))
    except Exception:
        return None


def _apply_method_point(method_id: str, point_index: int, new_value: float,
                        agent_id: str, audit_id: str = '') -> dict:
    """승인 후 Method.points_json 의 특정 점 값을 갱신."""
    try:
        from aot.databases.models import Method
        from aot.config import AOT_DB_PATH
        from aot.databases.utils import session_scope

        with session_scope(AOT_DB_PATH) as sess:
            m = sess.query(Method).filter(Method.unique_id == method_id).first()
            if m is None:
                return {'error': 'not_found', 'method_id': method_id}
            points = json.loads(m.points_json or '[]')
            if point_index >= len(points):
                return {'error': 'index_out_of_range',
                        'point_index': point_index, 'n_points': len(points)}
            old = points[point_index].get('value', points[point_index].get('vpd'))
            points[point_index]['value'] = round(new_value, 4)
            m.points_json = json.dumps(points, ensure_ascii=False)
            sess.commit()

        audit.update_status(audit_id, 'completed',
                            result_summary=f'point[{point_index}] {old} → {new_value}')
        logger.info('update_method_point: %s[%d] → %.4f (agent=%s)',
                    method_id, point_index, new_value, agent_id)
        return {'ok': True, 'method_id': method_id,
                'point_index': point_index, 'old_value': old, 'new_value': new_value}
    except Exception as exc:
        audit.update_status(audit_id, 'error', error=str(exc))
        logger.exception('update_method_point apply failed: %s', exc)
        return {'error': 'db_error', 'message': str(exc)}


# ─────────────────────────────────────────────────────────────────────────────
# request_manual_lock
# ─────────────────────────────────────────────────────────────────────────────

def request_manual_lock(
    function_id: str,
    duration_minutes: int = 30,
    reason: str = '',
    agent_id: str = 'ai_agent',
) -> dict:
    """env_coordinator 의 AI 자동제어를 일시 정지 요청한다.

    Args:
        function_id:       CustomController.unique_id
        duration_minutes:  잠금 기간 (1 ~ 120분)
        reason:            정지 이유
        agent_id:          AI 에이전트 식별자

    Returns:
        pending 응답 또는 오류.
    """
    if not (1 <= duration_minutes <= 120):
        return {
            'error': 'safety_violation',
            'message': f'duration_minutes={duration_minutes} out of range [1, 120]',
        }

    params = {'function_id': function_id, 'duration_minutes': duration_minutes}
    gate = _write_gate('request_manual_lock', params, agent_id, reason)
    if gate:
        return gate
    return {'error': 'unreachable'}


def _apply_manual_lock(function_id: str, duration_minutes: int,
                       agent_id: str, audit_id: str = '') -> dict:
    """manual_lock 플래그를 CustomController custom_options 에 기록."""
    import time
    try:
        from aot.databases.models import CustomController
        from aot.config import AOT_DB_PATH
        from aot.databases.utils import session_scope

        lock_until = time.time() + duration_minutes * 60
        with session_scope(AOT_DB_PATH) as sess:
            ctrl = sess.query(CustomController).filter(
                CustomController.unique_id == function_id).first()
            if ctrl is None:
                return {'error': 'not_found', 'function_id': function_id}
            opts = json.loads(ctrl.custom_options or '{}')
            opts['manual_lock_until'] = lock_until
            opts['manual_lock_reason'] = f'AI lock by {agent_id}'
            ctrl.custom_options = json.dumps(opts, ensure_ascii=False)
            sess.commit()

        audit.update_status(audit_id, 'completed',
                            result_summary=f'manual_lock {duration_minutes}min')
        logger.info('request_manual_lock: %s locked %dmin (agent=%s)',
                    function_id, duration_minutes, agent_id)
        return {'ok': True, 'function_id': function_id,
                'locked_until_ts': lock_until, 'duration_minutes': duration_minutes}
    except Exception as exc:
        audit.update_status(audit_id, 'error', error=str(exc))
        return {'error': 'db_error', 'message': str(exc)}


# ─────────────────────────────────────────────────────────────────────────────
# acknowledge_alert
# ─────────────────────────────────────────────────────────────────────────────

def acknowledge_alert(
    alert_id: str,
    note: str = '',
    agent_id: str = 'ai_agent',
) -> dict:
    """시스템 경보를 확인 처리한다.

    Args:
        alert_id: NotificationLog.unique_id 또는 경보 ID
        note:     확인 메모
        agent_id: AI 에이전트 식별자

    Returns:
        pending 응답 또는 오류.
    """
    params = {'alert_id': alert_id, 'note': note}
    gate = _write_gate('acknowledge_alert', params, agent_id, note)
    if gate:
        return gate
    return {'error': 'unreachable'}


def _apply_acknowledge_alert(alert_id: str, note: str,
                             agent_id: str, audit_id: str = '') -> dict:
    """NotificationLog 에 acknowledged 플래그 기록."""
    try:
        from aot.databases.models import NotificationLog
        from aot.config import AOT_DB_PATH
        from aot.databases.utils import session_scope

        with session_scope(AOT_DB_PATH) as sess:
            row = sess.query(NotificationLog).filter(
                NotificationLog.unique_id == alert_id).first()
            if row is None:
                return {'error': 'not_found', 'alert_id': alert_id}
            row.acknowledged = True
            row.ack_note = note
            sess.commit()

        audit.update_status(audit_id, 'completed', result_summary=f'ack alert {alert_id}')
        return {'ok': True, 'alert_id': alert_id}
    except Exception as exc:
        audit.update_status(audit_id, 'error', error=str(exc))
        return {'error': 'db_error', 'message': str(exc)}


# ─────────────────────────────────────────────────────────────────────────────
# confirm_action — 대기 중인 토큰을 승인하고 실제 적용
# ─────────────────────────────────────────────────────────────────────────────

_APPLY_DISPATCH: dict[str, callable] = {
    'update_method_point': lambda p, aid, auid: _apply_method_point(
        p['method_id'], p['point_index'], p['new_value'], aid, auid),
    'request_manual_lock': lambda p, aid, auid: _apply_manual_lock(
        p['function_id'], p['duration_minutes'], aid, auid),
    'acknowledge_alert':   lambda p, aid, auid: _apply_acknowledge_alert(
        p['alert_id'], p.get('note', ''), aid, auid),
}


def confirm_action(
    token_id: str,
    user_id: str = 'user',
) -> dict:
    """대기 중인 쓰기 작업을 사용자가 승인한다.

    Args:
        token_id: safety_check 가 발행한 ConfirmationToken.token_id
        user_id:  승인한 사용자 ID

    Returns:
        Dict with ok, tool_name, result.
    """
    try:
        token = safety_confirm(token_id, user_id)
    except KeyError as e:
        return {'error': 'unknown_token', 'message': str(e)}
    except TimeoutError as e:
        return {'error': 'expired', 'message': str(e)}

    # 감사 로그 업데이트
    audit.update_status(token_id, 'approved', user_id=user_id)

    apply_fn = _APPLY_DISPATCH.get(token.tool_name)
    if apply_fn is None:
        return {'error': 'no_apply_fn', 'tool_name': token.tool_name}

    result = apply_fn(token.params, token.agent_id, token_id)
    return {'ok': True, 'tool_name': token.tool_name, 'result': result}


def reject_action(
    token_id: str,
    user_id: str = 'user',
) -> dict:
    """대기 중인 쓰기 작업을 사용자가 거부한다."""
    from aot.mcp_server.safety import reject as safety_reject
    try:
        token = safety_reject(token_id, user_id)
        audit.update_status(token_id, 'rejected', user_id=user_id)
        return {'ok': True, 'token_id': token_id, 'status': 'rejected'}
    except KeyError as e:
        return {'error': 'unknown_token', 'message': str(e)}
