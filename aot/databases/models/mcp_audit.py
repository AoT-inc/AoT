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
    confirmation_status = db.Column(db.String(20), default='n/a')   # n/a | pending | approved | rejected | expired
    confirmation_id     = db.Column(db.String(36), default=None)
    user_id             = db.Column(db.String(36), default=None)
    result_summary      = db.Column(db.Text, default='')
    error               = db.Column(db.Text, default='')

    def __repr__(self):
        return (f'<MCPAuditLog tool={self.tool_name} '
                f'status={self.confirmation_status}>')


class MCPConfirmation(CRUDMixin, db.Model):
    """사용자 승인 대기 큐 — 쓰기 도구 실행 전 60초 내 승인 필요."""

    __tablename__ = 'mcp_confirmation'
    __table_args__ = {'extend_existing': True}

    id          = db.Column(db.Integer, primary_key=True)
    unique_id   = db.Column(db.String(36), nullable=False,
                            unique=True, default=set_uuid)
    created_at  = db.Column(db.DateTime, nullable=False,
                            default=datetime.utcnow)
    expires_at  = db.Column(db.DateTime, nullable=False)
    tool_name   = db.Column(db.String(100), nullable=False)
    params_json = db.Column(db.Text, default='{}')
    reason      = db.Column(db.Text, default='')
    agent_id    = db.Column(db.String(100), default='unknown')
    status      = db.Column(db.String(20), default='pending')  # pending | approved | rejected | expired
    user_id     = db.Column(db.String(36), default=None)

    def is_expired(self) -> bool:
        return datetime.utcnow() > self.expires_at

    def __repr__(self):
        return (f'<MCPConfirmation tool={self.tool_name} '
                f'status={self.status}>')
