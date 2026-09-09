# coding=utf-8
"""
mcp_audit.py — P4-3: MCP 감사 로그 + 승인 확인 큐 모델.

mcp_audit_log  : AI 도구 호출 이력 (읽기·쓰기 모두 기록)
mcp_confirmation: 쓰기 도구 사용자 승인 큐 (pending/approved/rejected/expired)
"""

from datetime import datetime

from aot.databases import CRUDMixin, set_uuid
from aot.aot_flask.extensions import db


class MCPAuditLog(CRUDMixin, db.Model):
    """AI 에이전트의 MCP 도구 호출 감사 로그 (90일 보존)."""

    __tablename__ = 'mcp_audit_log'
    __table_args__ = {'extend_existing': True}

    id                  = db.Column(db.Integer, primary_key=True)
    unique_id           = db.Column(db.String(36), nullable=False,
                                    unique=True, default=set_uuid)
    timestamp           = db.Column(db.DateTime, nullable=False,
                                    default=datetime.utcnow)
    agent_id            = db.Column(db.String(100), default='unknown')
    tool_name           = db.Column(db.String(100), nullable=False)
    params_json         = db.Column(db.Text, default='{}')
    reason              = db.Column(db.Text, default='')
    permission          = db.Column(db.String(20), default='read')  # read | write
    # n/a | not_required | pending | approved | rejected | expired
    # not_required: 쓰기지만 승인이 면제된 설정 편집(tool_registry 의 config_only).
    # 'approved' 로 뭉뚱그리면 아무도 보지 않은 동작이 사람이 승인한 것으로 남는다.
    confirmation_status = db.Column(db.String(20), default='n/a')
    confirmation_id     = db.Column(db.String(36), default=None)
    user_id             = db.Column(db.String(36), default=None)
    result_summary      = db.Column(db.Text, default='')
    error               = db.Column(db.Text, default='')

    def __repr__(self):
        return (f'<MCPAuditLog tool={self.tool_name} '
                f'status={self.confirmation_status}>')


class MCPConfirmation(CRUDMixin, db.Model):
    """사용자 승인 대기 큐 — 쓰기 도구는 실행 전 사람 승인이 필요하다.

    `expires_at` 은 상태에 따라 뜻이 다르다: pending 이면 "언제까지 승인할 수
    있는가", approved 면 "언제까지 실행할 수 있는가"(승인 시점부터 다시 셈).
    유효시간은 mcp_safety_gate 의 `_CONFIRM_TTL_SEC` / `_APPROVED_TTL_SEC`.
    """

    __tablename__ = 'mcp_confirmation'
    __table_args__ = {'extend_existing': True}

    id          = db.Column(db.Integer, primary_key=True)
    unique_id   = db.Column(db.String(36), nullable=False,
                            unique=True, default=set_uuid)
    created_at  = db.Column(db.DateTime, nullable=False,
                            default=datetime.utcnow)
    expires_at  = db.Column(db.DateTime, nullable=False)
    tool_name   = db.Column(db.String(100), nullable=False)
    # 승인 화면에 보이는 유일한 헤드라인 — tool_name 원문(내부 식별자)은 절대
    # 화면에 안 나간다. LLM 이 _title 메타 인자로 보내거나, 없으면
    # mcp_safety_gate.synthesize_title() 이 만들어 채운다(항상 값이 있어야
    # 한다는 뜻은 아니다 — 마이그레이션 이전 행은 비어 있을 수 있어 조회
    # 시점에도 폴백한다, list_pending() 참고).
    title       = db.Column(db.String(200), default=None)
    params_json = db.Column(db.Text, default='{}')
    reason      = db.Column(db.Text, default='')
    agent_id    = db.Column(db.String(100), default='unknown')
    status      = db.Column(db.String(20), default='pending')
    # pending | approved | rejected | expired | consumed | executed | failed
    #   executed/failed = 승인 시점에 서버가 직접 실행을 끝낸 상태(p6_26). 이후
    #   AI 가 _confirmation_id 로 재호출하면 재실행하지 않고 result_json 을 돌려준다.
    result_json = db.Column(db.Text, default=None)
    user_id     = db.Column(db.String(36), default=None)
    # 승인자가 값을 고쳐서 승인했을 때만 채워진다 (mcp_review 위젯의 "수정" 기능).
    # params_json(원본)은 감사 근거로 절대 덮어쓰지 않는다 — execute_approved() 가
    # 이 값이 있으면 이걸, 없으면 params_json 을 실행에 쓴다.
    modified_params_json = db.Column(db.Text, default=None)

    def is_expired(self) -> bool:
        return datetime.utcnow() > self.expires_at

    def __repr__(self):
        return (f'<MCPConfirmation tool={self.tool_name} '
                f'status={self.status}>')
