# coding=utf-8
"""
mcp_auth.py — 외부 MCP 접속의 인바운드 인증.

지금까지 MCP HTTP 엔드포인트는 무인증이었고, 호출자 신원은 요청이 스스로
적어 보내는 `X-MCP-Agent-Id` 헤더에 의존했다. 그 헤더는 누구나 원하는 값으로
바꿔 보낼 수 있어서, 감사 로그와 의견 원장의 "누가 낸 것인가"가 사실상 자기
신고였다. 여기서 그것을 실제 크레덴셜 기반으로 바꾼다.

새 키 체계를 만들지 않고 AoT 가 이미 쓰는 인바운드 규약을 그대로 따른다:
  - 크레덴셜: User.api_key (BLOB) — 설정 UI의 API 키 생성 버튼이 만든다
    (utils_settings.generate_api_key → set_api_key(128) → secrets.token_bytes)
  - 전달 방식: `X-API-KEY: <base64(api_key)>` 헤더
    (aot_flask/app.py 의 request_loader 와 동일한 규약)
이 규약을 재사용하므로 사용자는 새로 배울 것도, 별도 키 저장소도 없다.

인증이 성공하면 그 키의 소유 사용자가 곧 호출자 신원이 된다. 즉 agent_id 가
크레덴셜에서 유도되어 사칭이 불가능해지고, 감사 로그·의견 원장의 귀속이
비로소 신뢰할 수 있게 된다.

트랜스포트별 취급:
  - HTTP : 네트워크로 열리므로 인증 필수(기본값).
  - stdio: 클라이언트가 프로세스를 직접 spawn 하는 구조라 이미 호스트 접근
           권한이 전제된다(Claude Desktop 방식). 그래도 동일 정책을 적용할 수
           있도록 AOT_MCP_API_KEY 환경변수를 읽는다.

끄는 방법: AOT_MCP_REQUIRE_AUTH=0 (로컬 단독 테스트용). 끄면 무인증이 되고
호출자 신원은 다시 자기 신고 값이 되므로, 그 상태를 감사 로그에서 구분할 수
있도록 agent_id 앞에 'unauthenticated:' 를 붙인다.
"""

import base64
import hmac
import logging
import os
import uuid
from collections import namedtuple

logger = logging.getLogger(__name__)

UNAUTH_PREFIX = 'unauthenticated:'

# 내부 AI 전용 서비스 계정. 사람 계정을 빌려 쓰지 않기 위한 것이다(아래
# ensure_service_account 참조). 식별은 이름이 아니라 auth_provider 로 한다 —
# 이름은 사람이 먼저 차지했을 수 있고, 그 계정을 서비스 계정으로 오인하면
# 남의 계정에 키를 발급하게 된다.
SERVICE_ACCOUNT_NAME = 'aot-system'
SERVICE_ACCOUNT_PROVIDER = 'system'

# 인증된 호출자 정보의 스냅샷 — SQLAlchemy ORM 인스턴스가 아니라 평범한 값만 담는다.
# authenticate_http/authenticate_stdio 가 반환한 뒤에는 원래의 app_context/session이
# 이미 끝나 있을 수 있어(stdio는 initialize에서 한 번 인증하고 이후 tools/list,
# tools/call 은 별도 호출), ORM 인스턴스를 그대로 들고 다니면 DetachedInstanceError
# 위험이 있다. namedtuple 스냅샷은 그 위험이 원천적으로 없다.
# user_id는 User.unique_id — routes_mcp_api.py의 웹 승인 엔드포인트가 이미
# flask_login.current_user.unique_id를 MCPConfirmation.user_id에 적어 넣는 것과
# 동일한 규약이라, MCP 쪽에서 승인할 때도 이 값을 그대로 쓰면 "누가 승인했는지"가
# 웹 승인과 동일한 방식으로 귀속된다.
RoleInfo = namedtuple('RoleInfo', ['name', 'can_write', 'user_id'])


def require_auth() -> bool:
    """인증 요구 여부. 기본 ON — 네트워크로 열리는 엔드포인트이기 때문이다."""
    return os.environ.get('AOT_MCP_REQUIRE_AUTH', '1') not in ('0', 'false', 'False')


def _clean_label(value) -> str:
    """클라이언트가 스스로 밝힌 이름을 감사 로그에 넣기 전에 정리한다.

    HTTP 헤더는 latin-1 로 디코딩되므로 비ASCII 이름(예: 한글)은 이미 깨진 채로
    도착한다. 깨진 문자열을 그대로 남기면 감사 로그가 읽을 수 없게 되므로
    출력 가능한 ASCII 만 남긴다. 신원이 아니라 주석이므로 버려도 안전하다.
    """
    if not value:
        return ''
    text = ''.join(ch for ch in str(value) if 32 <= ord(ch) < 127).strip()
    return text[:40]


def _decode(raw: str) -> bytes:
    """헤더 값(base64)을 원본 바이트로. 실패하면 빈 값."""
    if not raw:
        return b''
    try:
        return base64.b64decode(raw, validate=False)
    except Exception:
        return b''


def role_can_write(role) -> bool:
    """이 role(RoleInfo, 또는 None)로 인증된 MCP 호출자가 쓰기(mutating/physical)
    도구를 쓸 자격이 있는지. 새 권한 체계를 만드는 대신 웹 대시보드의 기존
    Role.edit_controllers 플래그를 그대로 재사용한다 — USER_ROLES 시딩
    (aot/config/__init__.py)상 Admin/Editor만 True, Monitor/Guest/Kiosk는 전부
    False로 이미 사용자가 원하는 "admin/editor=쓰기, 나머지=조회" 구분과 일치한다.
    role이 없으면(미인증/인증 끔) 안전한 기본값으로 조회 전용 취급한다."""
    return bool(role is not None and getattr(role, 'can_write', False))


def ensure_service_account():
    """내부 AI 가 자기 MCP 서버에 붙을 때 쓸 전용 계정을 찾거나 만든다.

    Flask 앱 컨텍스트 안에서 호출해야 한다. 역할이 하나도 시딩돼 있지 않으면
    None 을 돌려준다(그 경우 호출자가 경고를 남기고 넘어간다).

    예전에는 "API 키가 없는 첫 번째 Admin/Editor" 를 골라 **그 사람 명의로**
    키를 발급했다. 두 가지가 무너진다:
      - 감사 로그의 agent_id 가 'user:<그 사람>' 이 되어, 내부 AI 가 한 일과
        그 사람이 한 일을 구분할 수 없다. 이 파일이 애초에 없애려던 문제
        (신원 자기신고)가 형태만 바꿔 되살아난다.
      - User.api_key_hash 는 컬럼 하나뿐이라 1인 1키다. 그 사람이 나중에
        설정 화면에서 자기 키를 재발급하면 덮어써지고, 내부 AI 는 아무 에러
        없이 도구를 전부 잃는다.

    이 계정으로는 로그인할 수 없다:
      - 비밀번호 로그인은 routes_authentication.py 의 `elif not
        user.password_hash` 가 거부한다(password_hash 를 비워 둔다).
      - 키패드 로그인은 User.code 로 계정을 찾는데 code 가 None 이라 어떤
        코드와도 매칭되지 않는다.
      - Google 로그인은 email 로 대조하는데 그 값이 없다.
    """
    from aot.aot_flask.extensions import db
    from aot.databases.models import Role, User

    user = User.query.filter(
        User.auth_provider == SERVICE_ACCOUNT_PROVIDER).first()
    if user is not None:
        return user

    # 최소 권한: 쓰기 도구를 쓰려면 edit_controllers 가 필요하지만 사용자 관리
    # 권한까지 줄 이유는 없다 — USER_ROLES 시딩상 그 조합이 Editor 다. 역할을
    # 이름으로 찾지 않는 이유는 운영자가 이름을 바꿨을 수 있기 때문이다.
    role = (Role.query
            .filter(Role.edit_controllers.is_(True))
            .filter(Role.edit_users.is_(False))
            .order_by(Role.id).first()
            or Role.query
            .filter(Role.edit_controllers.is_(True))
            .order_by(Role.id).first())
    if role is None:
        return None

    name = SERVICE_ACCOUNT_NAME
    if User.query.filter(User.name == name).first() is not None:
        # User.name 은 unique 다. 사람이 이미 이 이름을 쓰고 있으면 비켜 간다.
        name = '{}-{}'.format(SERVICE_ACCOUNT_NAME, uuid.uuid4().hex[:8])

    user = User()
    user.name = name
    user.full_name = 'AoT System (internal AI)'
    user.role_id = role.id
    user.auth_provider = SERVICE_ACCOUNT_PROVIDER
    user.is_enabled = True
    user.is_approved = True
    user.password_hash = None
    user.email = None
    user.code = None
    db.session.add(user)
    db.session.commit()
    logger.info("[MCP] 내부 AI 전용 서비스 계정을 만들었습니다: '%s' (role=%s)",
                name, role.name)
    return user


def resolve_key(raw_key: str):
    """base64 API 키 → (소유 사용자, 키 행). 유효하지 않으면 (None, None).

    Flask 앱 컨텍스트 안에서 호출해야 한다.

    DB 에는 키의 SHA-256 만 저장되므로(p6_13) 제시된 키를 해시해 인덱스로
    조회한다. 이전 구현은 전 사용자를 순회하며 평문을 상수시간 비교했는데,
    해시 조회는 그 순회 자체가 없어 타이밍 노출면이 더 작다. 최종 확인의
    상수시간 비교는 User.resolve_api_key 안에 있다.

    **키 행까지 돌려주는 이유**: 스코프(readonly)가 여기서 버려지면 그 뒤로는
    복구할 방법이 없다. 실제로 그랬다 — 예전에는 사용자만 돌려주어 읽기 전용
    키로도 MCP 쓰기 도구를 전부 쓸 수 있었다. 메인 앱은 HTTP 메서드로 거르는
    가드(app.py)가 막아 주지만, MCP 는 도구 호출이 전부 `POST /mcp` 한 경로라
    메서드로는 구분되지 않는다.

    레거시 컬럼으로 찾은 키는 행이 없어 (user, None) 이며, 스코프는 'full'
    취급이다 — 스코프가 없던 시절 발급된 키는 실제로 전 권한이었다.
    """
    key_bytes = _decode(raw_key)
    if not key_bytes:
        return None, None

    from aot.databases.models import User

    return User.resolve_api_key(key_bytes)


def _role_for(user, key_row=None):
    """User.role_id → RoleInfo 스냅샷. User.role_id has no ORM relationship (raw
    FK-less integer column, per aot/databases/models/user.py), so every caller
    that needs the role looks it up this way — same query pattern as
    routes_authentication.py, but returns a plain namedtuple (see RoleInfo)
    instead of the ORM row so it stays valid after this app_context ends.

    key_row 가 읽기 전용 키면 역할이 무엇이든 can_write 를 끈다. 스코프는 역할
    **위에** 얹히는 제한이라, 둘 중 좁은 쪽이 이겨야 한다 — 그러지 않으면
    "읽기 전용으로 줬다" 가 거짓말이 된다.
    """
    if user is None or user.role_id is None:
        return None
    from aot.databases.models import Role
    row = Role.query.filter(Role.id == user.role_id).first()
    if row is None:
        return None
    can_write = bool(row.edit_controllers)
    if can_write and key_row is not None and getattr(key_row, 'is_readonly', False):
        logger.info(
            "[MCP] 읽기 전용 키 '%s' — 역할 %s 의 쓰기 권한을 이 연결에서는 끕니다.",
            key_row.name or (key_row.unique_id or '')[:8], row.name)
        can_write = False
    return RoleInfo(name=row.name, can_write=can_write,
                     user_id=user.unique_id)


def authenticate_http(headers, declared_agent_id=None):
    """HTTP 요청 헤더로 인증한다.

    Returns:
        (ok: bool, agent_id: str, role: Role|None, error: dict|None)
        ok=False 이면 error 를 그대로 401 본문으로 반환하면 된다. role 은 이 호출자가
        쓰기 도구를 쓸 수 있는지 판단할 때 role_can_write(role) 로 넘기면 된다 —
        인증을 껐거나 실패한 경우 role=None(= 안전하게 조회 전용 취급).
    """
    raw = headers.get('X-API-KEY')
    if not raw:
        # Authorization: Basic <base64> 도 같은 규약으로 받아준다(app.py 와 동일).
        auth = headers.get('Authorization') or ''
        if auth.startswith('Basic '):
            raw = auth[6:]
        elif auth.startswith('Bearer '):
            raw = auth[7:]

    if not require_auth():
        # 인증을 끈 상태 — 신원은 자기 신고이므로 감사 로그에서 구분되게 표시한다.
        # role 은 알 수 없으니 None(= role_can_write 는 False, 조회 전용) 취급한다.
        return True, f"{UNAUTH_PREFIX}{declared_agent_id or 'anonymous'}", None, None

    if not raw:
        return False, '', None, {
            "error": "unauthorized",
            "message": ("An API key is required. Send the user's API key "
                        "base64-encoded in the 'X-API-KEY' header. "
                        "Generate one under Settings > Users."),
        }

    user, key_row = resolve_key(raw)
    if user is None:
        return False, '', None, {
            "error": "unauthorized",
            "message": "The API key is not valid.",
        }

    # 신원은 키에서 유도한다 — 요청이 declared_agent_id 로 무엇을 주장하든 무시한다.
    agent_id = f"user:{user.name}"
    label = _clean_label(declared_agent_id)
    if label and label != agent_id:
        # 클라이언트 이름은 참고 정보로만 남긴다(같은 사용자 키로 여러 AI가 붙을 수 있다).
        agent_id = f"user:{user.name}/{label}"
    return True, agent_id, _role_for(user, key_row), None


def authenticate_stdio(declared_agent_id=None):
    """stdio 트랜스포트 인증 — 키는 AOT_MCP_API_KEY 환경변수로 받는다.

    Returns: (ok, agent_id, role, error) — authenticate_http과 동일 규약.
    """
    if not require_auth():
        return True, f"{UNAUTH_PREFIX}{declared_agent_id or 'stdio'}", None, None

    raw = os.environ.get('AOT_MCP_API_KEY', '')
    if not raw:
        return False, '', None, {
            "error": "unauthorized",
            "message": ("Set the base64 API key in the AOT_MCP_API_KEY environment "
                        "variable (the 'env' entry of your MCP client config). "
                        "To disable authentication, set AOT_MCP_REQUIRE_AUTH=0."),
        }

    user, key_row = resolve_key(raw)
    if user is None:
        return False, '', None, {"error": "unauthorized",
                                  "message": "AOT_MCP_API_KEY is not a valid key."}

    agent_id = f"user:{user.name}"
    label = _clean_label(declared_agent_id)
    if label:
        agent_id = f"user:{user.name}/{label}"
    return True, agent_id, _role_for(user, key_row), None
