# coding=utf-8
"""
mcp_server/tools/control.py — P4-1: 쓰기(제어) 도구 모음.

모든 도구는 safety_check() 통과 후 사용자 승인을 받아야 실행된다.

도구 목록:
  set_vpd_target        — VPD 목표값 변경 (Method 또는 CustomVariable)
  update_method_point   — DailyMultiPoint 곡선 제어점 수정
  request_manual_lock   — 수동 잠금 요청 (AI 자동제어 일시 정지)
  acknowledge_alert     — 경보 확인 처리
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
# set_vpd_target
# ─────────────────────────────────────────────────────────────────────────────

def set_vpd_target(
    function_id: str,
    value: float,
    reason: str = '',
    agent_id: str = 'ai_agent',
) -> dict:
    """env_coordinator 의 VPD 목표값을 변경한다.

    Args:
        function_id: CustomController.unique_id
        value:       새 VPD 목표 (kPa). 허용 범위 0.3 ~ 2.5, 1회 변화량 ≤ 0.5 kPa.
        reason:      변경 이유 (감사 로그 기록)
        agent_id:    AI 에이전트 식별자

    Returns:
        성공 시 {'ok': True, 'old_value': float, 'new_value': float}
        대기 시 {'pending': True, 'token_id': str, ...}
        오류 시 {'error': str, 'message': str}
    """
    params = {'function_id': function_id, 'value': value}

    # 현재값 조회 (delta 제한 검증용)
    current_value = _get_current_vpd_target(function_id)

    gate = _write_gate('set_vpd_target', params, agent_id, reason, current_value)
    if gate:
        return gate  # pending or error

    # ── 실제 쓰기 (승인 경로 — 여기에 오지 않음, 항상 pending 반환) ──
    # 아래 _apply_vpd_target 은 confirm_action 도구가 승인 후 직접 호출하도록 설계
    return {'error': 'unreachable', 'message': 'safety_check should have raised'}


def _get_current_vpd_target(function_id: str) -> float | None:
    try:
        from aot.databases.models import CustomController
        from aot.utils.database import db_retrieve_table_daemon
        ctrl = db_retrieve_table_daemon(CustomController, unique_id=function_id)
        custom_options = json.loads(ctrl.custom_options or '{}')
        return float(custom_options.get('target_vpd', 0))
    except Exception:
        return None


def _apply_vpd_target(function_id: str, value: float, agent_id: str,
                      audit_id: str = '') -> dict:
    """승인 후 실제 VPD setpoint 를 DB 에 기록."""
    try:
        from aot.databases.models import CustomController
        from aot.config import AOT_DB_PATH
        from aot.databases.utils import session_scope

        with session_scope(AOT_DB_PATH) as sess:
            ctrl = sess.query(CustomController).filter(
                CustomController.unique_id == function_id).first()
            if ctrl is None:
                return {'error': 'not_found', 'function_id': function_id}
            opts = json.loads(ctrl.custom_options or '{}')
            old = opts.get('target_vpd')
            opts['target_vpd'] = round(value, 3)
            ctrl.custom_options = json.dumps(opts, ensure_ascii=False)
            sess.commit()

        # 실행 중인 env_coordinator 인스턴스는 custom_options 를 최초 1회만 읽으므로,
        # cmd_reload 로 재기동 없이 다음 사이클에 반영되게 한다.
        try:
            from aot.aot_client import DaemonControl
            DaemonControl().module_function(
                'Function', function_id, 'cmd_reload', {}, thread=True)
        except Exception as reload_exc:
            logger.warning('set_vpd_target: cmd_reload failed for %s: %s',
                           function_id, reload_exc)

        audit.update_status(audit_id, 'completed',
                            result_summary=f'target_vpd {old} → {value}')
        logger.info('set_vpd_target: %s → %.3f kPa (agent=%s)', function_id, value, agent_id)
        return {'ok': True, 'function_id': function_id,
                'old_value': old, 'new_value': value}
    except Exception as exc:
        audit.update_status(audit_id, 'error', error=str(exc))
        logger.exception('set_vpd_target apply failed: %s', exc)
        return {'error': 'db_error', 'message': str(exc)}


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
    'set_vpd_target':    lambda p, aid, auid: _apply_vpd_target(
        p['function_id'], p['value'], aid, auid),
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
