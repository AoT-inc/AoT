# coding=utf-8
"""사용자 지정 문자열의 번역 캐시.

gettext 카탈로그는 소스에 박힌 문구만 덮는다. 사용자가 직접 지은 이름
("1번 하우스", "동편 밸브")은 DB 원문 그대로 모든 언어에서 노출된다.
이 테이블은 그 원문 → 대상 언어 번역본의 캐시다.

원문이 정본이고 이 테이블은 표시 레이어의 캐시일 뿐이다. 어떤 경로로도
`translated_text` 가 `Input.name` 등 원본 컬럼에 되써져서는 안 된다.

설계: docs/design/user-string-live-translation.md
"""
from datetime import datetime

from aot.databases import CRUDMixin
from aot.aot_flask.extensions import db


# status 값
STATUS_PENDING = 'pending'   # 큐에 있음, 아직 번역 안 됨
STATUS_DONE = 'done'         # 번역 완료
STATUS_FAILED = 'failed'     # 엔진 실패 — 재시도 대상
STATUS_SKIPPED = 'skipped'   # 번역하지 않기로 판정 — 영구히 건너뜀


class UserStringTranslation(CRUDMixin, db.Model):
    """사용자 지정 문자열 하나의, 한 대상 언어에 대한 번역.

    @phase active
    @stability stable
    """
    __tablename__ = "user_string_translation"
    __table_args__ = (
        db.UniqueConstraint('source_hash', 'target_lang',
                            name='uq_user_string_translation_hash_lang'),
        db.Index('ix_user_string_translation_lang_status',
                 'target_lang', 'status'),
        {'extend_existing': True},
    )

    id = db.Column(db.Integer, unique=True, primary_key=True)

    # 정규화된 원문의 sha1 앞 16자. 원문 자체가 길 수 있어 조회는 해시로 한다.
    source_hash = db.Column(db.String(16), nullable=False, index=True)
    source_text = db.Column(db.Text, nullable=False)

    # 감지된 원어. 판정 불가는 'auto' — 엔진에 감지를 위임한다는 뜻.
    source_lang = db.Column(db.String(12), nullable=False, default='auto')
    target_lang = db.Column(db.String(12), nullable=False)

    # pending/skipped 상태에서는 NULL.
    translated_text = db.Column(db.Text, nullable=True)

    # 'device' | 'zone' | 'crop' | 'function' | ... — 프롬프트 힌트로 쓴다.
    domain = db.Column(db.String(32), nullable=False, default='misc')
    status = db.Column(db.String(16), nullable=False,
                       default=STATUS_PENDING, index=True)

    # 사용자가 손으로 고친 값. True 면 재번역이 덮지 않는다.
    is_locked = db.Column(db.Boolean, nullable=False, default=False)

    # 번역에 쓴 엔진/모델 — 감사용. 특정 모델을 가정하지 않는다.
    engine = db.Column(db.String(120), nullable=True)

    # 연속 실패 횟수. 상한을 넘기면 더 시도하지 않는다.
    fail_count = db.Column(db.Integer, nullable=False, default=0)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow,
                           onupdate=datetime.utcnow)

    def __repr__(self):
        return (f"<UserStringTranslation({self.source_text!r} → "
                f"{self.target_lang}: {self.translated_text!r}, "
                f"status={self.status})>")
