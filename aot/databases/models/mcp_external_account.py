# coding=utf-8
"""중앙 계정 ↔ 이 AoT 사용자 — 외부 MCP 의 중앙 인증 토큰으로 들어온 사람을 누구로 볼지.

토큰의 `sub` 는 인가 서버 계정의 불투명 값이라 이 AoT 의 사용자가 아니다. 이메일이 같다고 잇지 않는다
(남의 주소로 가입해 남의 계정을 얻는 길을 막는다). 사용자가 이 AoT 에 **평소대로 로그인한 채** 계정 연결
(OpenID Connect 인가 코드 + PKCE)을 거쳐야만 행이 생긴다. 한 (발급자, sub) 는 한 사용자에만, 한 사용자는
발급자마다 하나에만 이어진다.
"""
from datetime import datetime

from aot.aot_flask.extensions import db
from aot.databases import CRUDMixin


class MCPExternalAccount(CRUDMixin, db.Model):
    __tablename__ = "mcp_external_account"
    __table_args__ = (
        db.UniqueConstraint('issuer', 'subject', name='uq_mcp_external_account_subject'),
        db.UniqueConstraint('user_id', 'issuer', name='uq_mcp_external_account_user'),
        {'extend_existing': True},
    )

    id = db.Column(db.Integer, primary_key=True)
    issuer = db.Column(db.String(255), nullable=False)
    subject = db.Column(db.String(255), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    # 연결할 때 인가 서버가 알려 준 이름·이메일 — 화면 표시용. 판정에 쓰지 않는다.
    label = db.Column(db.String(255), default='', nullable=True)
    linked_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    def __repr__(self):
        return "<MCPExternalAccount(user_id={}, issuer={})>".format(self.user_id, self.issuer)
