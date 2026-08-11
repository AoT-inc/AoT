# coding=utf-8
"""사용자별 API 키 — 1인 다중 키.

예전에는 키가 `users.api_key_hash` 컬럼 하나였다. 사람마다 키를 딱 하나만 가질
수 있다는 뜻이고, 실제로 이런 일이 벌어졌다:

  - 같은 사람이 ChatGPT 와 Claude 에 각각 붙일 수 없다. 한쪽에 키를 넣고 다른
    쪽을 위해 새로 발급하면 **앞의 것이 조용히 죽는다** — 컬럼이 하나라
    재발급이 곧 덮어쓰기이기 때문이다.
  - 어느 클라이언트가 어느 키를 쓰는지 이름을 붙일 수 없어, 키 하나가 미심쩍어도
    무엇을 끊는 것인지 모른 채 끊어야 한다.
  - 유출이 의심될 때 그 키만 끊을 수 없다. 끊으면 그 사람의 모든 연동이 끊긴다.

이 테이블은 키를 사람에게서 떼어내 **1:N** 으로 만든다. 각 키는 이름을 갖고,
개별로 폐기할 수 있으며, 폐기해도 행은 남는다(감사 로그의 과거 기록이 가리키는
대상이 사라지면 안 된다 — geo_binding 의 unbind 가 행을 지우지 않는 것과 같은
이유다).

키 자체는 저장하지 않는다. `users.api_key_hash` 와 같은 규약으로 SHA-256 만
남기고, 평문은 발급 응답에서 한 번 보여준 뒤 서버에 남지 않는다. bcrypt 가
아닌 이유도 같다 — 키가 128바이트 난수라 무차별 대입이 불가능하고, 인증은 매
요청마다 일어나므로 bcrypt 의 의도적 지연이 그대로 응답 지연이 된다.

레거시 컬럼 `users.api_key_hash` 는 아직 남아 있다. 읽기는
`User.find_by_api_key` 가 이 테이블 → 레거시 컬럼 순으로 보고(폴백), 배포한
서버에서 백필이 끝나 폴백이 0 인 것을 확인한 뒤에 컬럼을 제거한다. 지금
지우면 백필 전인 서버의 모든 API 연동이 즉시 끊긴다.
"""
from datetime import datetime

from aot.aot_flask.extensions import db
from aot.databases import CRUDMixin
from aot.databases import set_uuid

#: 키 스코프. 값을 늘릴 수 있도록 문자열로 둔다(불리언이면 세 번째 값이 필요해질
#: 때 컬럼을 다시 바꿔야 한다).
SCOPE_FULL = 'full'
SCOPE_READONLY = 'readonly'
SCOPES = (SCOPE_FULL, SCOPE_READONLY)


class UserAPIKey(CRUDMixin, db.Model):
    """한 사용자가 가진 API 키 하나.

    @phase active
    @stability stable
    @dependency User
    """
    __tablename__ = "user_api_key"
    __table_args__ = {'extend_existing': True}

    id = db.Column(db.Integer, primary_key=True)
    unique_id = db.Column(db.String(36), nullable=False, unique=True,
                          default=set_uuid)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'),
                        nullable=False, index=True)

    # 사람이 붙이는 이름. "ChatGPT", "Claude Desktop" 처럼 **어디에 꽂았는지** 를
    # 적는 자리다. 이름이 없으면 키를 끊을 때 무엇이 끊기는지 알 수 없다.
    name = db.Column(db.String(64), default=None)

    # 키의 SHA-256(hex). 평문은 발급 시 1회만 노출되고 저장하지 않는다.
    key_hash = db.Column(db.String(64), nullable=False, unique=True, index=True)

    # 이 키로 무엇을 할 수 있는가. 'full' = 그 사용자의 권한 그대로,
    # 'readonly' = 읽기만.
    #
    # 키에 스코프가 없던 동안 API 키는 **그 사용자의 전 권한**이었다
    # (`load_user_from_request` 가 키로 User 를 찾아 그대로 로그인시킨다).
    # 그래서 다른 AoT 서버의 데이터를 받아오기만 하려 해도 상대에게 내 장치
    # 제어권까지 함께 넘겨야 했다 — 원격 AoT 수집 연결이 정확히 그 경우다.
    # 읽기 전용 계정을 따로 만들라는 안내로 때워 왔지만, 계정을 하나 더 만드는
    # 일과 키 하나를 좁히는 일은 부담이 다르다.
    #
    # 기본값은 'full' 이다. 이미 발급된 키의 동작이 업그레이드로 조용히 바뀌면
    # 돌던 연동이 끊긴다.
    scope = db.Column(db.String(16), nullable=False, default=SCOPE_FULL,
                      server_default=SCOPE_FULL)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # 폐기 시각. 행을 지우지 않고 여기에 시각을 적는다 — 지우면 "이 키는 언제
    # 끊겼나" 를 나중에 물을 수 없고, 같은 해시를 다시 발급받는 사고도 막지
    # 못한다(unique 제약이 사라지므로).
    revoked_at = db.Column(db.DateTime, default=None)

    def __repr__(self):
        state = 'revoked' if self.revoked_at else 'active'
        return "<UserAPIKey(id={s.id}, user_id={s.user_id}, name='{s.name}', {st})>".format(
            s=self, st=state)

    @property
    def is_active(self):
        return self.revoked_at is None

    @property
    def is_readonly(self):
        return self.scope == SCOPE_READONLY

    @classmethod
    def find_active(cls, raw_key):
        """제시된 평문 키에 해당하는 **살아 있는** 키 행. 없으면 None.

        `User.find_by_api_key` 가 사용자를 돌려주는 것과 달리 이쪽은 키 행을
        돌려준다 — 스코프를 알아야 하는 호출자(요청 가드)를 위해서다. 검증
        규칙은 같은 곳에 두 벌로 두지 않도록 여기서만 판단한다.
        """
        if not raw_key:
            return None
        import hmac

        from .user import User
        candidate = User.hash_api_key(raw_key)
        row = cls.query.filter_by(key_hash=candidate).first()
        if row is None or not hmac.compare_digest(row.key_hash or '', candidate):
            return None
        if row.revoked_at is not None:
            return None
        return row

    def revoke(self):
        """이 키를 폐기한다. 이미 폐기됐으면 시각을 덮어쓰지 않는다 —
        최초 폐기 시각이 감사상 의미 있는 값이다."""
        if self.revoked_at is None:
            self.revoked_at = datetime.utcnow()
        return self
