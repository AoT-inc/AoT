# coding=utf-8
"""
mcp_server/audit.py — P4-3: MCP 도구 호출 감사 로그 기록.

모든 MCP 도구 호출(읽기·쓰기)이 mcp_audit_log 에 기록된다.
쓰기 도구는 confirmation_id 로 MCPConfirmation 큐와 연결된다.

공개 API:
  record_call(tool_name, params, ..., **quality) -> str  (unique_id)
      실행 경로(tool_execution._execute_tool)가 쓰는 유일한 기록 함수. INSERT 1회.
  log_call(tool_name, params, agent_id, permission, ...) -> str  (unique_id)
  update_status(unique_id, status, user_id, result, error)
      위 둘은 예전 2단계 기록 방식이다. 호환을 위해 남긴다(현재 호출처 없음).
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


#: record_call 이 받는 호출 품질 칸(p6_74). 이 밖의 키는 조용히 버리지 않고
#: 오류로 남긴다 — 칸 이름 오타가 "NULL 로 쌓이는" 조용한 실패가 되지 않게.
QUALITY_FIELDS = ('duration_ms', 'session_key', 'transport', 'via_drawer',
                  'response_tokens', 'response_bytes', 'truncated',
                  'call_state', 'result_items')


def record_call(
    tool_name: str,
    params: dict | None = None,
    agent_id: str = 'unknown',
    permission: str = 'read',
    reason: str = '',
    confirmation_id: str | None = None,
    confirmation_status: str = 'n/a',
    result_summary: str = '',
    error: str = '',
    **quality,
) -> str:
    """호출 결과가 모두 정해진 뒤 감사 행 1개를 **INSERT 한 번**으로 쓴다.

    예전에는 `log_call`(INSERT) 뒤 `update_status`(SELECT+UPDATE)로 두 번
    커밋했다. 둘 다 실행이 끝난 뒤에 불렸으므로 한 번에 써도 남는 내용은
    같다(tests/test_mcp_quality_ledger.py 가 행 단위로 대조한다).

    quality: QUALITY_FIELDS 중 일부. 없으면 NULL.
    실패해도 예외를 올리지 않는다 — 감사 실패가 도구 호출을 깨면 안 된다.
    """
    try:
        unknown = set(quality) - set(QUALITY_FIELDS)
        if unknown:
            raise ValueError('unknown quality fields: %s' % sorted(unknown))
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
                confirmation_status=confirmation_status,
                confirmation_id=confirmation_id,
                result_summary=result_summary or '',
                error=error or '',
                **{k: v for k, v in quality.items() if v is not None},
            )
            sess.add(row)
            sess.commit()
        return uid
    except Exception:
        logger.exception('audit.record_call failed — tool=%s', tool_name)
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


def purge_old(days: int | None = None) -> int:
    """days 일 이전 로그 삭제. 삭제된 행 수 반환.

    days 를 생략하면 config.MCP_AUDIT_RETENTION_DAYS 를 쓴다 — 하루 1회 도는
    정리 잡(`aot.utils.audit.purge_old_mcp_logs`)과 같은 기준이어야 하는데,
    여기에 90 을 따로 박아두면 config 만 바꿨을 때 조용히 어긋난다.
    이 함수는 Flask 앱 컨텍스트 밖(MCP 서버 프로세스)에서 쓰는 경로다.
    """
    try:
        from aot.databases.models import MCPAuditLog
        from aot.config import AOT_DB_PATH, MCP_AUDIT_RETENTION_DAYS
        from aot.databases.utils import session_scope

        if days is None:
            days = MCP_AUDIT_RETENTION_DAYS
        if days is None or days <= 0:
            return 0

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
