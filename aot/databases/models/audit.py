# coding=utf-8
"""audit.py — 사용자 행위 감사로그.

기존에 있던 것: 로그인 로그 파일(`LOGIN_LOG_FILE`)과 MCP 감사로그
(`mcp_audit_log`, AI 도구 호출 전용, 90일).
없던 것: 설정 변경·장치 제어·사용자/권한 변경·인증 실패·데이터 반출 이력.

공공조달 규격서(운영 현황·이력 관리)와 개인정보 안전성 확보조치 기준의
접속기록 요구를 충족하기 위한 범용 감사로그다. `MCPAuditLog`와는 통합하지
않는다 — 그쪽은 승인 큐(`confirmation_status`) 등 AI 경로 고유 필드가 있어
스키마가 다르고, 조회 화면에서만 합쳐 보여준다.
"""
from datetime import datetime

from aot.databases import CRUDMixin, set_uuid
from aot.aot_flask.extensions import db


class AuditLog(CRUDMixin, db.Model):
    """사용자 행위 감사로그 (기본 보존 1년).

    한 행 = 한 번의 감사 대상 행위. `before_json`/`after_json`은 설정 변경처럼
    "무엇이 어떻게 바뀌었는지"가 중요한 경우에만 채운다(제어 명령 등은 비워둔다).
    """

    __tablename__ = 'audit_log'
    __table_args__ = {'extend_existing': True}

    id = db.Column(db.Integer, primary_key=True)
    unique_id = db.Column(db.String(36), nullable=False, unique=True, default=set_uuid)
    timestamp = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)

    # 행위자. user_id는 로그인 실패처럼 사용자가 특정되지 않는 경우 None이 될 수
    # 있으므로 시도된 이름을 username에 따로 남긴다(사후 추적용).
    user_id = db.Column(db.Integer, default=None, index=True)
    username = db.Column(db.String(64), default=None)
    ip_address = db.Column(db.String(64), default=None)

    # 행위. action은 'login.success', 'output.control' 같은 점 구분 문자열.
    action = db.Column(db.String(64), nullable=False, index=True)
    target_type = db.Column(db.String(64), default=None)   # 'Output', 'Misc', 'User' ...
    target_id = db.Column(db.String(64), default=None)     # unique_id 또는 PK
    target_name = db.Column(db.String(128), default=None)  # 사람이 읽을 이름

    result = db.Column(db.String(16), nullable=False, default='success')  # success | failure
    detail = db.Column(db.Text, default=None)
    before_json = db.Column(db.Text, default=None)
    after_json = db.Column(db.Text, default=None)

    def __repr__(self):
        return "<AuditLog {ts} {act} {res} user={usr}>".format(
            ts=self.timestamp, act=self.action, res=self.result, usr=self.username)
