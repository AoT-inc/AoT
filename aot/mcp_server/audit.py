# coding=utf-8
"""
mcp_server/audit.py — P4-3: MCP 도구 호출 감사 로그 기록.

모든 MCP 도구 호출(읽기·쓰기)이 mcp_audit_log 에 기록된다.
쓰기 도구는 confirmation_id 로 MCPConfirmation 큐와 연결된다.

공개 API:
  log_call(tool_name, params, agent_id, permission, ...) -> str  (unique_id)
  update_status(unique_id, status, user_id, result, error)
  get_recent(limit, agent_id, tool_name) -> list[dict]
  purge_old(days) -> int
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


def log_call(
    tool_name: str,
    params: dict | None = None,
    agent_id: str = 'unknown',
    permission: str = 'read',
    reason: str = '',
    confirmation_id: str | None = None,
) -> str:
    """DB 에 감사 로그 1행을 삽입. unique_id 반환."""
    try:
        from aot.databases.models import MCPAuditLog
        from aot.config import AOT_DB_PATH
        from aot.databases.utils import session_scope
        import uuid

        uid = str(uuid.uuid4())
        with session_scope(AOT_DB_PATH) as sess:
            row = MCPAuditLog(
                unique_id=uid,
                timestamp=datetime.utcnow(),
                agent_id=agent_id,
                tool_name=tool_name,
                params_json=json.dumps(params or {}, ensure_ascii=False),
                reason=reason,
                permission=permission,
                confirmation_status='n/a' if permission == 'read' else 'pending',
                confirmation_id=confirmation_id,
            )
            sess.add(row)
            sess.commit()
        return uid
    except Exception:
        logger.exception('audit.log_call failed — tool=%s', tool_name)
        return ''


def update_status(
    unique_id: str,
    status: str,
    user_id: str | None = None,
    result_summary: str = '',
    error: str = '',
) -> None:
    """감사 로그 행의 상태를 갱신 (승인/거부/만료/완료)."""
    if not unique_id:
        return
    try:
        from aot.databases.models import MCPAuditLog
        from aot.config import AOT_DB_PATH
        from aot.databases.utils import session_scope

        with session_scope(AOT_DB_PATH) as sess:
            row = sess.query(MCPAuditLog).filter(
                MCPAuditLog.unique_id == unique_id).first()
            if row:
                row.confirmation_status = status
                if user_id:
                    row.user_id = user_id
                if result_summary:
                    row.result_summary = result_summary
                if error:
                    row.error = error
                sess.commit()
    except Exception:
        logger.exception('audit.update_status failed — uid=%s', unique_id)


def get_recent(
    limit: int = 50,
    agent_id: str | None = None,
    tool_name: str | None = None,
) -> list[dict]:
    """최근 감사 로그 조회."""
    try:
        from aot.databases.models import MCPAuditLog
        from aot.config import AOT_DB_PATH
        from aot.databases.utils import session_scope

        with session_scope(AOT_DB_PATH) as sess:
            q = sess.query(MCPAuditLog)
            if agent_id:
                q = q.filter(MCPAuditLog.agent_id == agent_id)
            if tool_name:
                q = q.filter(MCPAuditLog.tool_name == tool_name)
            rows = (q.order_by(MCPAuditLog.timestamp.desc())
                     .limit(limit).all())
            result = []
            for r in rows:
                result.append({
                    'unique_id':           r.unique_id,
                    'timestamp':           r.timestamp.isoformat() if r.timestamp else None,
                    'agent_id':            r.agent_id,
                    'tool_name':           r.tool_name,
                    'params':              json.loads(r.params_json or '{}'),
                    'reason':              r.reason,
                    'permission':          r.permission,
                    'confirmation_status': r.confirmation_status,
                    'user_id':             r.user_id,
                    'result_summary':      r.result_summary,
                    'error':               r.error,
                })
            sess.expunge_all()
        return result
    except Exception:
        logger.exception('audit.get_recent failed')
        return []


def purge_old(days: int = 90) -> int:
    """days 일 이전 로그 삭제. 삭제된 행 수 반환."""
    try:
        from aot.databases.models import MCPAuditLog
        from aot.config import AOT_DB_PATH
        from aot.databases.utils import session_scope

        cutoff = datetime.utcnow() - timedelta(days=days)
        with session_scope(AOT_DB_PATH) as sess:
            n = (sess.query(MCPAuditLog)
                      .filter(MCPAuditLog.timestamp < cutoff)
                      .delete())
            sess.commit()
        return n
    except Exception:
        logger.exception('audit.purge_old failed')
        return 0
