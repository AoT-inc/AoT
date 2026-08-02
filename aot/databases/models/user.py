# coding=utf-8
import hashlib
import hmac

import bcrypt
from flask_login import UserMixin

from aot.databases import CRUDMixin
from aot.databases import set_uuid
from aot.aot_flask.extensions import db
from aot.aot_flask.extensions import ma


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
    def find_by_api_key(cls, raw_key):
        """제시된 API 키로 사용자를 찾는다. 없으면 None.

        해시 컬럼으로 인덱스 조회한 뒤 상수시간 비교로 한 번 더 확인한다
        (인덱스 조회만으로도 값 비교는 일어나지만, 비교 자체를 상수시간으로
        고정해 두면 이후 구현이 바뀌어도 타이밍 측면이 유지된다).
        """
        if not raw_key:
            return None
        candidate = cls.hash_api_key(raw_key)
        user = cls.query.filter_by(api_key_hash=candidate).first()
        if user and hmac.compare_digest(user.api_key_hash or '', candidate):
            # 꺼진 계정의 키는 통하지 않는다. 세 API 경로(url arg / Basic /
            # X-API-KEY)가 모두 여기를 거치므로 검사는 이 한 곳이면 된다.
            if not user.is_enabled:
                return None
            return user
        return None

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
