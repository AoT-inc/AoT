# coding=utf-8
"""
ai_advice.py — 다자 AI 의견 원장.

메인 AoT의 AI, 외부에서 MCP로 접속한 AI, 그리고 AI를 가진 하위 노드가
각자 낸 의견(조언·제안)을 한 원장에 모은다. 제어 실행이 아니라 "의견"이므로
mcp_confirmation(실행 승인 큐)과 목적이 다르다 — 여기에 쌓인 의견은 사람이
읽고 채택/기각하며, 채택된 의견이 실제 제어로 이어질 때 비로소 승인 큐를 탄다.

왜 별도 테이블인가:
  - AISystemSummary 는 스코프당 최신 1건만 조회되므로(get_latest_summary,
    지도 조언 칩이 이 방식으로 읽는다) 여러 주체의 의견을 넣으면 서로를
    덮어써 둘 다 잃는다. 상충하는 의견을 나란히 보관하는 것이 이 원장의 목적이다.
  - Notes 는 사람이 쓰는 기록 표면이라 AI 의견을 섞으면 오염되고,
    채택/기각 상태를 표현할 수 없다.
"""

from datetime import datetime

from aot.databases import CRUDMixin, set_uuid
from aot.aot_flask.extensions import db


class AIAdvice(CRUDMixin, db.Model):
    """AI가 제출한 의견 1건 (읽기 전용 조언 — 실행 권한 없음)."""

    __tablename__ = 'ai_advice'
    __table_args__ = {'extend_existing': True}

    id         = db.Column(db.Integer, primary_key=True)
    unique_id  = db.Column(db.String(36), nullable=False, unique=True, default=set_uuid)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)

    # 제출 주체 — 어느 AI가 낸 의견인지 구분하는 것이 이 원장의 핵심.
    agent_id   = db.Column(db.String(100), nullable=False, default='unknown')
    # main | external | subordinate — 메인/외부/하위 중 어디서 왔는지
    agent_kind = db.Column(db.String(20), default='external')

    # 대상 범위 (system | farm | zone | facility | device)
    scope_type = db.Column(db.String(20), default='system')
    scope_id   = db.Column(db.String(64), default=None, index=True)
    scope_name = db.Column(db.String(128), default=None)

    title      = db.Column(db.String(200), nullable=False, default='')
    advice     = db.Column(db.Text, nullable=False, default='')
    # 근거 — 어떤 관측/도구 결과에 기반했는지. 상충 의견을 사람이 비교할 때 판단 재료.
    rationale  = db.Column(db.Text, default='')
    # 제안한 조치(자연어). 실행되지 않으며, 채택 시 사람이 승인 절차로 옮긴다.
    proposed_action = db.Column(db.Text, default='')
    severity   = db.Column(db.String(20), default='info')  # info | advice | warning | urgent
    confidence = db.Column(db.Float, default=None)         # 0.0~1.0, 제출자 자기평가

    # 처리 상태 — pending | accepted | rejected | superseded
    status       = db.Column(db.String(20), default='pending', index=True)
    reviewed_by  = db.Column(db.String(36), default=None)
    reviewed_at  = db.Column(db.DateTime, default=None)
    review_note  = db.Column(db.Text, default='')

    def __repr__(self):
        return (f'<AIAdvice {self.agent_kind}:{self.agent_id} '
                f'scope={self.scope_type} status={self.status}>')
