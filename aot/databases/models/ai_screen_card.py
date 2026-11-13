# coding=utf-8
"""AI 가 사용자에게 남기는 자막·수신함 카드 (2026-10-19, P0).

외부 AI(MCP)의 screen_action(action='post')이 만든다. 농장 기록(Notes)과 섞이면
검색·AI 컨텍스트·일지에 나타나고, 읽음·닫기·만료 칸이 없으며, 30일 정리가 노트
삭제가 되므로 전용 테이블을 쓴다.

수신자는 API 키 주인(user_id) 한 사람이다. 모든 질의는 user_id 로 거른다.
HTML 은 서버에서 바꾸지 않고 원문 그대로 저장한다 — 표시측이 textContent 로만 그린다.

@phase active
"""
from aot.utils.timekit import utc_now

from aot.databases.sqla import db
from aot.databases import CRUDMixin
from aot.databases import set_uuid


class AIScreenCard(CRUDMixin, db.Model):
    """AI 가 보낸 카드 한 장 (제목 + 마크다운 본문).

    @phase active
    """
    __tablename__ = "ai_screen_cards"
    __table_args__ = (
        db.Index('ix_ai_screen_cards_user_created', 'user_id', 'created_at'),
        db.Index('ix_ai_screen_cards_expires_at', 'expires_at'),
        db.Index('ix_ai_screen_cards_user_pinned', 'user_id', 'pinned_at'),
        {'extend_existing': True},
    )

    id = db.Column(db.Integer, unique=True, primary_key=True)
    unique_id = db.Column(db.String(36), nullable=False, unique=True, default=set_uuid)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=utc_now)
    expires_at = db.Column(db.DateTime, nullable=False)

    #: 'text' | 'image' | 'file' (P1) | 'artifact'(P2 — 정적 HTML)
    kind = db.Column(db.String(16), default='text')
    title = db.Column(db.String(80), default=None)
    body = db.Column(db.Text, default=None)
    #: 보낸 쪽 표시 이름(API 키 이름, 없으면 'AI')
    source_label = db.Column(db.String(64), default=None)
    source_key_id = db.Column(db.String(36), default=None)

    read_at = db.Column(db.DateTime, default=None)
    dismissed_at = db.Column(db.DateTime, default=None)

    #: 첨부 파일(P1) — file_path 는 PATH_AI_CARD_FILES 아래 상대경로('YYYY/MM/uuid.ext')
    #: 만 담는다. 입력으로 경로를 만들지 않는다(aot/utils/ai_card_files.py).
    file_path = db.Column(db.String(255), default=None)
    file_name = db.Column(db.String(120), default=None)
    file_mime = db.Column(db.String(64), default=None)
    file_size = db.Column(db.Integer, default=None)
    #: 고정한 시각 — 있으면 30일 만료·300건 정리에서 빠진다(사용자당 30장).
    pinned_at = db.Column(db.DateTime, default=None)
    #: 사용자가 [노트로 저장] 한 노트의 unique_id(이미 저장했는지 표시)
    note_id = db.Column(db.String(36), default=None)
    #: 사용자가 [공지로 게시] 한 공지(NoticePost)의 unique_id(P2). 게시 멱등은 이 칸에
    #: 조건부 UPDATE(notice_id IS :old)로 자리를 잡아 여러 워커에서도 한 번만 일어난다.
    notice_id = db.Column(db.String(36), default=None)
    #: 끌어올린 시각(P7-11) — 사람이 [맨 위로] 누르거나 AI 가 이 카드를 다시 띄우면 남긴다.
    #: 수신함 정렬은 이 값(없으면 created_at)의 최신순이다(ai_screen_cards.sort_key).
    raised_at = db.Column(db.DateTime, default=None)

    def __repr__(self):
        return "<{cls}(id={s.id})>".format(s=self, cls=self.__class__.__name__)
