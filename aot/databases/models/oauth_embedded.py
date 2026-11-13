# coding=utf-8
"""내장 OAuth 인가 서버의 표 셋(docs/design/mcp-embedded-oauth.md §6).

gunicorn 워커가 여럿이라 클라이언트·코드·연결 상태는 전부 DB 에 둔다(프로세스 메모리에 두지 않는다).
인가 코드와 갱신 토큰은 SHA-256 해시만 저장한다 — DB 가 새도 그대로 쓸 수 있는 토큰이 없다.
"""
from datetime import datetime

from aot.databases.sqla import db
from aot.databases import CRUDMixin


class OAuthClient(CRUDMixin, db.Model):
    """동적 등록(RFC 7591)으로 만들어진 공개 클라이언트(비밀 없음, PKCE 필수)."""
    __tablename__ = "oauth_client"
    __table_args__ = {'extend_existing': True}

    id = db.Column(db.Integer, primary_key=True)
    client_id = db.Column(db.String(64), nullable=False, unique=True)
    # 클라이언트가 스스로 적은 이름 — 동의 화면에 보이되 검증된 값이 아니다.
    client_name = db.Column(db.String(100), default='', nullable=False)
    # JSON 목록 문자열. 등록 때 허용 목록을 통과한 주소만 들어 있다.
    redirect_uris = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    last_used_at = db.Column(db.DateTime, nullable=True)


class OAuthCode(CRUDMixin, db.Model):
    """인가 코드 — 60초, 한 번만. 다시 쓰이면 그 코드로 만든 연결(gid)을 끊는다."""
    __tablename__ = "oauth_code"
    __table_args__ = {'extend_existing': True}

    id = db.Column(db.Integer, primary_key=True)
    code_hash = db.Column(db.String(64), nullable=False, unique=True)
    client_id = db.Column(db.String(64), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    resource = db.Column(db.String(512), nullable=False)
    scope = db.Column(db.String(255), nullable=False)
    code_challenge = db.Column(db.String(128), nullable=False)
    redirect_uri = db.Column(db.String(2048), nullable=False)
    expires_at = db.Column(db.DateTime, nullable=False)
    used = db.Column(db.Boolean, nullable=False, default=False)
    # 코드를 쓴 뒤 만들어진 연결. 같은 코드가 또 오면 이 연결을 끊는다(RFC 6749 §4.1.2).
    gid = db.Column(db.String(64), nullable=True)


class OAuthGrant(CRUDMixin, db.Model):
    """사용자가 한 클라이언트에 내준 연결. 접근 토큰의 `gid` 가 이 행을 가리킨다."""
    __tablename__ = "oauth_grant"
    __table_args__ = {'extend_existing': True}

    ACTIVE = 'active'
    REVOKED = 'revoked'

    id = db.Column(db.Integer, primary_key=True)
    gid = db.Column(db.String(64), nullable=False, unique=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True)
    client_id = db.Column(db.String(64), nullable=False, index=True)
    client_name = db.Column(db.String(100), default='', nullable=False)
    resource = db.Column(db.String(512), nullable=False)
    scope = db.Column(db.String(255), nullable=False)
    refresh_hash = db.Column(db.String(64), nullable=False, index=True)
    # 바로 앞 갱신 토큰의 해시 하나 — 이게 다시 오면 훔쳐 쓴 것으로 보고 연결 전체를 끊는다.
    prev_refresh_hash = db.Column(db.String(64), nullable=True, index=True)
    refresh_expires_at = db.Column(db.DateTime, nullable=False)
    status = db.Column(db.String(16), nullable=False, default=ACTIVE)
    revoked_reason = db.Column(db.String(32), nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    last_used_at = db.Column(db.DateTime, nullable=True)
