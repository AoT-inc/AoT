# coding=utf-8
import hashlib
import hmac
import logging

import bcrypt
from flask_login import UserMixin

from aot.databases import CRUDMixin
from aot.databases import set_uuid
from aot.aot_flask.extensions import db
from aot.aot_flask.extensions import ma

logger = logging.getLogger(__name__)

#: 레거시 폴백을 이미 보고한 사용자 id. 인증은 요청마다 일어나므로 그대로
#: 로그를 남기면 초당 수십 줄이 쌓여, 정작 읽어야 할 다른 로그를 밀어낸다.
#: 프로세스당 사용자당 한 번이면 "이 서버가 아직 레거시 컬럼에 기대고 있다" 는
#: 사실을 알기에 충분하다.
_LEGACY_FALLBACK_SEEN = set()


def _note_legacy_fallback(user):
    """`users.api_key_hash` 로 인증이 성사됐음을 알린다.

    이 로그가 **한 줄도 없어야** 레거시 컬럼을 제거할 수 있다. 계측이 없으면
    "폴백이 0 인가" 를 물어볼 방법 자체가 없어서(코드에는 폴백이 있고, 쓰이는지는
    데이터에 달렸다) 제거 판단을 영원히 미루게 된다.

    반대로 이 줄이 보이면 그 서버는 **백필이 안 돌았다.**
    `python3 -m aot.scripts.check_api_key_fallback` 로 확인할 것.
    """
    try:
        if user.id in _LEGACY_FALLBACK_SEEN:
            return
        _LEGACY_FALLBACK_SEEN.add(user.id)
        logger.warning(
            "[API키] 사용자 '%s' 가 레거시 컬럼(users.api_key_hash)으로 인증됐습니다 "
            "— user_api_key 백필이 돌지 않은 키입니다. 이 로그가 남아 있는 한 "
            "레거시 컬럼을 제거하면 안 됩니다.", user.name)
    except Exception:
        # 계측이 인증을 깨뜨리면 안 된다.
        pass


class User(UserMixin, CRUDMixin, db.Model):
    """
    Represents a human operator in the AoT system.

    Stores authentication credentials (password hash, optional API key), contact
    information, role binding, and UI preferences. Used by Flask-Login for session
    management and by role-based access control throughout the application.

    @phase active
    @stability stable
    @dependency Role
    """
    __tablename__ = "users"
    __table_args__ = {'extend_existing': True}

    id = db.Column(db.Integer, primary_key=True)
    unique_id = db.Column(db.String(36), nullable=False, unique=True, default=set_uuid)
    name = db.Column(db.VARCHAR(64), unique=True, index=True)
    # 사람이 알아보는 이름. name 은 로그인 계정(영숫자·유일)이라 "koat", "5739"
    # 처럼 누구인지 알 수 없는 값이 흔해, 표시용으로 따로 둔다. 비어 있으면
    # 화면은 name 으로 되돌아간다 — 유일성을 요구하지 않으므로 동명이인 가능.
    full_name = db.Column(db.VARCHAR(64), default=None)
    password_hash = db.Column(db.VARCHAR(255))
    code = db.Column(db.Integer, default=None)
    # DEPRECATED: 평문 API 키. p6_13 마이그레이션이 기존 값을 api_key_hash 로
    # 옮기고 이 컬럼을 비웠다. 새로 쓰지 말 것 — 남겨둔 이유는 SQLite 에서
    # 컬럼 삭제가 테이블 재생성을 요구해 위험 대비 이득이 없기 때문이다.
    api_key = db.Column(db.BLOB, unique=True)
    # API 키의 SHA-256(hex). 키 자체는 발급 시 1회만 노출되고 DB 에는 남지 않는다.
    # bcrypt 가 아니라 SHA-256 인 이유: 키가 128바이트 난수라 무차별 대입이
    # 불가능하고, bcrypt 의 의도적 지연은 저엔트로피 비밀번호용이다. API 인증은
    # 매 요청마다 일어나므로 그 지연이 그대로 응답 지연이 된다.
    api_key_hash = db.Column(db.String(64), unique=True, index=True, default=None)
    email = db.Column(db.VARCHAR(64), unique=True, index=True)
    role_id = db.Column(db.Integer, default=None)
    # Settings > Users 카드의 표시 순서. Input/Output 카드와 같은 GridStack 드래그로
    # 정렬하며, /settings/users/save_order 가 0..N-1 로 다시 매겨 동률을 없앤다.
    position_y = db.Column(db.Integer, default=0)
    theme = db.Column(db.VARCHAR(64))
    landing_page = db.Column(db.Text, default='live')
    index_page = db.Column(db.Text, default='landing')
    language = db.Column(db.Text, default=None)  # Force the web interface to use a specific language
    timezone = db.Column(db.String(64), default=None)  # IANA tz for personal display; None = use system default (docs/design/timezone-management.md §3·§7)
    password_reset_code = db.Column(db.Text, default=None)
    password_reset_code_expiration = db.Column(db.DateTime, default=None)
    password_reset_last_request = db.Column(db.DateTime, default=None)

    # Google sign-in (see aot/utils/google_oauth.py). auth_provider records how
    # the account was created ('google' or None for the normal admin/password
    # flow); is_approved gates login for accounts self-registered via Google
    # sign-in until an admin reviews them (default True so existing/admin-
    # created accounts are unaffected).
    auth_provider = db.Column(db.String(32), default=None)
    is_approved = db.Column(db.Boolean, nullable=False, default=True)

    # 관리자가 계정을 지우지 않고 잠시 막아두는 스위치.
    #
    # 이름을 is_active 로 하지 않은 이유: UserMixin 이 같은 이름의 프로퍼티를
    # 제공하고 flask_login.login_user() 가 그것을 본다. 로그인 경로들은 DB 행이
    # 아니라 id/name 만 채운 빈 User() 를 login_user() 에 넘기는데, 컬럼으로
    # 덮어쓰면 그 임시 객체의 값이 None(=falsy)이 되어 모든 로그인이 거부된다.
    #
    # 로그인 시도는 routes_authentication.py 의 명시적 검사가, 이미 열려 있는
    # 세션은 app.py 의 user_loader 가 막는다.
    is_enabled = db.Column(db.Boolean, nullable=False, default=True)

    # Brute-force protection. The failed-attempt counter used to live in the
    # Flask session, so clearing a cookie reset it — no protection at all
    # against a scripted attacker. Server-side and per-account instead.
    failed_login_count = db.Column(db.Integer, nullable=False, default=0)
    locked_until = db.Column(db.DateTime, default=None)

    # TOTP two-factor auth (opt-in, per user). totp_secret is only meaningful
    # once totp_enabled is set — enrollment stores the secret first, then flips
    # the flag after the user proves they can generate a valid code.
    totp_secret = db.Column(db.String(64), default=None)
    totp_enabled = db.Column(db.Boolean, nullable=False, default=False)

    def __repr__(self):
        output = "<User: <name='{name}', email='{email}' is_admin='{isadmin}'>"
        return output.format(name=self.name, email=self.email, isadmin=bool(self.role_id == 1))

    def session_auth_hash(self):
        """비밀번호에서 파생된 세션 인증 해시.

        이 값이 세션과 "90일간 유지" 쿠키에 함께 실리고, 요청마다
        `user_loader` 가 대조한다. 비밀번호가 바뀌면 값이 달라지므로 **다른
        기기에 남아 있던 세션과 90일 토큰이 전부 그 자리에서 무효가 된다.**

        왜 필요한가: remember 토큰은 90일을 산다. 기기를 잃어버리거나 토큰이
        유출됐을 때 예전에는 끊을 방법이 없었다 — 비밀번호를 바꿔도 그 토큰은
        멀쩡히 살아 있었다. 이제 비밀번호 변경이 곧 "다른 기기 전부 로그아웃"
        이다.

        토큰이 아니라 **HMAC** 인 이유: flask-login 의 remember 쿠키는 서명은
        돼 있지만 내용은 그대로 읽힌다. `password_hash` 를 그냥 해시해 넣으면
        그 값이 쿠키에 노출돼, 쥔 사람이 "비밀번호가 바뀌었는지" 를 관찰하는
        오라클이 된다. 앱 비밀키로 HMAC 을 걸면 밖에서는 의미 없는 값이다.

        `password_hash` 가 없는 계정(구글 가입 직후)은 빈 값으로 계산한다 —
        바꿀 비밀번호가 없으니 무효화할 것도 없다.
        """
        from flask import current_app
        secret = current_app.secret_key or ''
        if isinstance(secret, str):
            secret = secret.encode('utf-8')
        pw = self.password_hash or b''
        if isinstance(pw, str):
            pw = pw.encode('utf-8')
        return hmac.new(secret, pw, hashlib.sha256).hexdigest()[:32]

    def verify_session_auth_hash(self, token):
        """세션/쿠키에 실려 온 인증 해시가 지금 비밀번호와 맞는가."""
        try:
            return hmac.compare_digest(str(token or ''), self.session_auth_hash())
        except Exception:
            return False

    def get_id(self):
        """flask-login 이 세션·remember 쿠키에 저장하는 식별자.

        `<id>|<session_auth_hash>` 형식. UserMixin 의 기본 구현(=id 만)을
        덮어쓴다. 짝이 되는 해석은 `app.py` 의 `user_loader` 에 있다 —
        **한쪽만 고치면 전원이 로그아웃된다.**

        주의: 로그인 경로는 이 메서드를 부를 수 있도록 반드시 **DB 행**을
        `flask_login.login_user()` 에 넘겨야 한다. 예전처럼 id/name 만 채운 빈
        `User()` 를 넘기면 `password_hash` 가 None 이라 엉뚱한 해시가 실린다.
        """
        return '%s|%s' % (self.id, self.session_auth_hash())

    def set_password(self, new_password):
        """saves a password hash  """
        if isinstance(new_password, str):
            new_password = new_password.encode('utf-8')
        self.password_hash = bcrypt.hashpw(new_password, bcrypt.gensalt())

    @staticmethod
    def hash_api_key(raw_key):
        """API 키(bytes 또는 str) → SHA-256 hex."""
        if isinstance(raw_key, str):
            raw_key = raw_key.encode('utf-8')
        return hashlib.sha256(raw_key).hexdigest()

    @classmethod
    def resolve_api_key(cls, raw_key):
        """제시된 API 키 → (사용자, 키 행). 찾지 못하면 (None, None).

        키 행은 스코프를 판단하는 쪽(`load_user_from_request`, `mcp_auth`)이
        필요로 한다. 레거시 컬럼으로 찾은 키는 행이 없으므로 (user, None) 이며,
        스코프는 'full' 로 취급한다 — 스코프가 없던 시절에 발급된 키는 실제로
        전 권한이었고, 업그레이드로 조용히 좁히면 돌던 연동이 끊긴다.
        """
        if not raw_key:
            return None, None
        candidate = cls.hash_api_key(raw_key)

        from .user_api_key import UserAPIKey
        row = UserAPIKey.query.filter_by(key_hash=candidate).first()
        if row is not None and hmac.compare_digest(row.key_hash or '', candidate):
            if row.revoked_at is not None:
                return None, None
            user = cls.query.filter_by(id=row.user_id).first()
            if user is not None and user.is_enabled:
                return user, row
            return None, None

        user = cls.query.filter_by(api_key_hash=candidate).first()
        if user and hmac.compare_digest(user.api_key_hash or '', candidate):
            if not user.is_enabled:
                return None, None
            _note_legacy_fallback(user)
            return user, None
        return None, None

    @classmethod
    def find_by_api_key(cls, raw_key):
        """제시된 API 키로 사용자를 찾는다. 없으면 None.

        `resolve_api_key` 의 얇은 껍데기다 — 키 행이 필요 없는 호출자를 위한
        것. **판정 규칙을 여기에 다시 쓰지 말 것.** 예전에는 두 메서드가 같은
        규칙(폐기 검사·계정 활성 검사·레거시 폴백)을 각자 한 벌씩 들고 있어,
        한쪽만 고치면 조용히 갈라지는 구조였다.
        """
        return cls.resolve_api_key(raw_key)[0]

    def issue_api_key(self, name=None, scope=None):
        """이 사용자에게 새 API 키를 하나 **추가** 발급한다.

        기존 키는 건드리지 않는다 — 그것이 이 테이블이 생긴 이유다. 반환값은
        평문 키(bytes)이며 호출자가 사용자에게 한 번 보여주고 버려야 한다.
        서버에는 해시만 남는다.

        scope 는 'full'(그 사용자의 권한 그대로) 또는 'readonly'(읽기만).
        모르는 값이 오면 'full' 로 떨어뜨리지 않고 'readonly' 로 좁힌다 —
        오타 하나가 조용히 전 권한 키를 만드는 쪽이 훨씬 위험하다.

        커밋은 하지 않는다. 호출자가 자기 트랜잭션 경계에서 커밋한다.
        """
        from aot.databases import set_api_key
        from .user_api_key import SCOPE_FULL, SCOPE_READONLY, SCOPES, UserAPIKey

        raw_key = set_api_key(128)
        row = UserAPIKey()
        row.user_id = self.id
        row.name = (name or '').strip()[:64] or None
        row.key_hash = self.hash_api_key(raw_key)
        if scope is None:
            row.scope = SCOPE_FULL
        else:
            row.scope = scope if scope in SCOPES else SCOPE_READONLY
        db.session.add(row)
        return raw_key

    def active_api_keys(self):
        """폐기되지 않은 키 목록(최근 발급 순)."""
        from .user_api_key import UserAPIKey
        return (UserAPIKey.query
                .filter(UserAPIKey.user_id == self.id)
                .filter(UserAPIKey.revoked_at.is_(None))
                .order_by(UserAPIKey.id.desc())
                .all())

    @staticmethod
    def check_password(password, hashed_password):
        """validates a password."""
        # Check type of password hashed_password to determine if it is a str
        # and should be encoded
        if isinstance(password, str):
            password = password.encode('utf-8')
        if isinstance(hashed_password, str):
            hashed_password = hashed_password.encode('utf-8')

        hashes_match = bcrypt.hashpw(password, hashed_password)
        return hashes_match


class UserSchema(ma.SQLAlchemyAutoSchema):
    """
    Marshmallow schema for serializing and deserializing User instances.

    Excludes sensitive fields (api_key, password_hash, totp_secret) from all
    outputs — totp_secret is a shared secret, so leaking it would let anyone
    generate valid second-factor codes.

    @phase active
    """
    class Meta:
        model = User
        exclude = ('api_key', 'password_hash', 'totp_secret',)
