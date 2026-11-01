# coding=utf-8
"""AI 카드의 첨부 한 칸 (2026-10-21, P5) — 카드당 최대 8개(파일+영상).

카드(`ai_screen_cards`)의 file_* 칸은 한 릴리스 동안 **첫 파일형 첨부**를 이중으로 기록하는
호환용이다(옛 번들·되돌리기 안전판). 읽기는 이 테이블이 정본이다.

  - kind 'image'|'file'|'artifact': path 는 PATH_AI_CARD_FILES 아래 `YYYY/MM/uuid.ext`,
    image 의 thumb 는 `thumb_rel(path)`. 입력으로 경로를 만들지 않는다.
  - kind 'video': 파일이 없다(path NULL). url·provider·host 는 서버가 정규화해 다시 만든
    값이고, thumb 은 서버가 받아 다시 인코딩한 포스터(없을 수 있다)다.
  - position 은 카드 안 순서(0..7)이며 수신함 API 의 `?i=` 값이다.
SQLite 는 FK 강제가 꺼져 있다 — 카드를 지울 때 이 행들은 코드가 명시적으로 지운다.

@phase active
"""
from aot.utils.time_utils import utc_now

from aot.aot_flask.extensions import db


class AICardAttachment(db.Model):
    """AI 카드 첨부 한 칸.

    @phase active
    """
    __tablename__ = "ai_card_attachments"
    __table_args__ = (
        db.Index('ux_ai_card_attachments_card_pos', 'card_id', 'position', unique=True),
        db.Index('ix_ai_card_attachments_user_created', 'user_id', 'created_at'),
        {'extend_existing': True},
    )

    id = db.Column(db.Integer, unique=True, primary_key=True)
    card_id = db.Column(db.Integer, db.ForeignKey('ai_screen_cards.id'), nullable=False)
    #: 카드 주인 복사 — 일 한도·용량 합계를 조인 없이 센다.
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    position = db.Column(db.SmallInteger, nullable=False)
    #: 'image' | 'file' | 'artifact' | 'video'
    kind = db.Column(db.String(16), default=None)
    path = db.Column(db.String(255), default=None)
    thumb = db.Column(db.String(255), default=None)
    name = db.Column(db.String(120), default=None)
    mime = db.Column(db.String(64), default=None)
    #: 디스크 바이트(video 는 포스터 바이트) — 사용자 용량 합계에 들어간다.
    size = db.Column(db.Integer, default=0)
    url = db.Column(db.String(2048), default=None)
    #: video 만: 'youtube' | 'vimeo' | 'direct'
    provider = db.Column(db.String(16), default=None)
    host = db.Column(db.String(253), default=None)
    #: video(direct) 만: post 때 한 번 판정한 "뷰어 안 <video> 허용" — 목록은 DNS 를 하지 않고 이 값만 쓴다.
    #: 백필·옛 행은 false(새 탭 링크만).
    playable = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, nullable=False, default=utc_now)

    def __repr__(self):
        return "<{cls}(id={s.id}, card={s.card_id}, i={s.position})>".format(
            s=self, cls=self.__class__.__name__)
