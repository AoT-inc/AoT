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
from collections import namedtuple

logger = logging.getLogger(__name__)

UNAUTH_PREFIX = 'unauthenticated:'

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


def resolve_key(raw_key: str):
    """base64 API 키 → 소유 사용자. 유효하지 않으면 None.

    Flask 앱 컨텍스트 안에서 호출해야 한다.

    사용자 수만큼 순회하며 hmac.compare_digest 로 비교한다. DB에 원본 키를
    조건으로 거는 대신 상수시간 비교를 쓰는 이유는 타이밍으로 키를 한 바이트씩
    좁혀 들어가는 공격을 막기 위한 것이다(키가 128바이트라 비교 비용은 무시할
    수준이고, 사용자 수도 수십 명 규모다).
    """
    key_bytes = _decode(raw_key)
    if not key_bytes:
        return None

    from aot.databases.models import User

    for user in User.query.filter(User.api_key.isnot(None)).all():
        stored = user.api_key
        if not stored:
            continue
        if isinstance(stored, str):
            stored = stored.encode('utf-8')
        if hmac.compare_digest(bytes(stored), key_bytes):
            return user
    return None


def _role_for(user):
    """User.role_id → RoleInfo 스냅샷. User.role_id has no ORM relationship (raw
    FK-less integer column, per aot/databases/models/user.py), so every caller
    that needs the role looks it up this way — same query pattern as
    routes_authentication.py, but returns a plain namedtuple (see RoleInfo)
    instead of the ORM row so it stays valid after this app_context ends."""
    if user is None or user.role_id is None:
        return None
    from aot.databases.models import Role
    row = Role.query.filter(Role.id == user.role_id).first()
    if row is None:
        return None
    return RoleInfo(name=row.name, can_write=bool(row.edit_controllers),
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

    user = resolve_key(raw)
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
    return True, agent_id, _role_for(user), None


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

    user = resolve_key(raw)
    if user is None:
        return False, '', None, {"error": "unauthorized",
                                  "message": "AOT_MCP_API_KEY is not a valid key."}

    agent_id = f"user:{user.name}"
    label = _clean_label(declared_agent_id)
    if label:
        agent_id = f"user:{user.name}/{label}"
    return True, agent_id, _role_for(user), None
