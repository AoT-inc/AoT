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
#
# can_edit_settings / can_use_ai_chat (2026-09-23): 기록 쓰기(노트·지식)와 조언
# 제출의 기준. 웹과 같은 역할 권한을 본다 — 노트·지식은 `edit_settings`,
# AI 사용은 `use_ai_chat`(제어 권한이 함의). None 이면 옛 방식으로 만든 스냅샷
# 이라는 뜻이다 — role_can_record 는 can_write 로, role_can_advise 는 허용으로
# 읽는다(아래 두 함수 참고). 운영 경로의 스냅샷은 전부 _role_for 가 채운다.
#
# can_edit_plots (2026-09-23): 작기 운영 쓰기(구획·단계·자원·작기 프로그램)의
# 기준 — 웹 구획 화면과 같은 `edit_plots`(설정 편집이 함의). None 이면 옛
# 스냅샷이라 can_write 로 읽는다(role_can_edit_plots).
#
# tool_profile (2026-09-24): 이 연결에 보여 줄 도구 묶음 — 'operations' 또는
# 'configuration'(tool_registry.TOOL_PROFILES). **None 은 "제한 없음"** 이다 —
# 인앱 AI 가 _role_for 로 만든 스냅샷이 그렇다. 외부 키로 들어온 연결은
# authenticate_http/authenticate_stdio 가 키에서 읽어 **반드시 채운다**(비어
# 있으면 운영). 내부 AI 서비스 계정의 키로 들어온 연결은
# 'unrestricted'(tool_registry.TOOL_PROFILE_UNRESTRICTED) — 인앱 물리 제어가
# 그 키로 stdio 하위 프로세스를 거치므로, 인앱과 같이 제한이 없다.
# 권한 판단에는 쓰지 않는다 — 표면(무엇을 보여 주는가)이다.
RoleInfo = namedtuple('RoleInfo', ['name', 'can_write', 'user_id',
                                   'can_edit_settings', 'can_use_ai_chat',
                                   'can_edit_plots', 'tool_profile'],
                      defaults=(None, None, None, None))


def role_row_allows(row, permission) -> bool:
    """DB `Role` 행이 이 권한을 갖는가 — 웹 `utils_general.user_has_permission`
    과 **같은 함의 규칙**이다(설정 편집 ⇒ 작기 운영, 제어 ⇒ AI 사용).

    요청 컨텍스트 없이(워커 스레드·MCP) 역할 행으로 판정할 때 쓴다. 규칙을
    자리마다 다시 적으면 한 곳만 함의를 빠뜨려 웹과 갈라진다."""
    if row is None:
        return False
    if permission == 'edit_plots':
        return bool(getattr(row, 'edit_plots', False)
                    or getattr(row, 'edit_settings', False))
    if permission == 'use_ai_chat':
        return bool(getattr(row, 'use_ai_chat', False)
                    or getattr(row, 'edit_controllers', False))
    return bool(getattr(row, permission, False))


def tool_profiles_enabled() -> bool:
    """키별 도구 묶음을 적용할지. 기본 켬 — `AOT_MCP_TOOL_PROFILES=0` 이면 모든
    키가 예전처럼 전체 표면을 본다(되돌리기용). 매 호출 읽는다. 환경변수인
    이유: 안전 스위치는 DB 가 이상해도 동작해야 한다."""
    return os.environ.get('AOT_MCP_TOOL_PROFILES', '1') not in ('0', 'false', 'False')


def default_tool_profile() -> str:
    """키 없이 들어온 연결(인증을 끈 서버)의 묶음. 기본 운영."""
    from aot.tools.tool_registry import normalize_tool_profile
    return normalize_tool_profile(
        os.environ.get('AOT_MCP_DEFAULT_TOOL_PROFILE', 'operations'))


def is_service_account(user) -> bool:
    return bool(user is not None and
                getattr(user, 'auth_provider', None) == SERVICE_ACCOUNT_PROVIDER)


def key_tool_profile(user, key_row) -> str:
    """이 키로 들어온 연결의 묶음.

    - 내부 AI 서비스 계정의 키는 'unrestricted'(제한 없음). 인앱 물리 제어
      (PhysicalControlResolver → MCPBridgeService)가 이 키로 stdio 하위
      프로세스에 붙어 set_output_state 를 부른다 — 설정 묶음으로 두면 외부
      키에서 뺀(retired) 그 도구가 거절돼 인앱 제어가 끊긴다. 키 행의 값은
      보지 않는다(화면도 이 키의 묶음 선택을 숨긴다).
    - 키 행의 값이 있으면 그 값(모르는 값은 운영으로 좁힌다).
    - 행이 없는 레거시 키, 아직 배정 전(NULL)인 키는 운영.
    """
    from aot.tools.tool_registry import (TOOL_PROFILE_OPERATIONS,
                                         TOOL_PROFILE_UNRESTRICTED,
                                         normalize_tool_profile)
    if is_service_account(user):
        return TOOL_PROFILE_UNRESTRICTED
    value = getattr(key_row, 'tool_profile', None) if key_row is not None else None
    if not value:
        return TOOL_PROFILE_OPERATIONS
    return normalize_tool_profile(value)


def tool_profile_of(role):
    """외부 전송이 목록·실행·안내문에 넘길 묶음. None = 제한 없음.

    role 이 없으면(인증을 끈 서버, 역할 행이 없는 계정) 기본 묶음이다.
    서비스 계정 키의 'unrestricted' 는 None 이다(key_tool_profile).
    스위치(AOT_MCP_TOOL_PROFILES)가 꺼져 있으면 언제나 None 이다."""
    from aot.tools.tool_registry import TOOL_PROFILE_UNRESTRICTED
    if not tool_profiles_enabled():
        return None
    if role is None:
        return default_tool_profile()
    value = getattr(role, 'tool_profile', None)
    if value == TOOL_PROFILE_UNRESTRICTED:
        return None
    return value or default_tool_profile()


def _with_key_profile(role, user, key_row):
    """인증된 스냅샷에 키의 묶음을 싣는다. role 이 없으면 그대로 None."""
    if role is None:
        return None
    return role._replace(tool_profile=key_tool_profile(user, key_row))


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


def role_can_record(role) -> bool:
    """기록 쓰기(노트·지식 — tool_registry 의 record_write)를 할 자격.

    웹에서 같은 기록을 쓰는 화면(`routes_notes_api.api_notes_create`,
    `routes_ai_library` 의 지식 추가)이 `edit_settings` 를 요구하므로 같은 것을
    본다. 읽기 전용 키면 _role_for 가 이미 꺼 두었다. role 이 없으면(미인증·
    인증 끔) 조회 전용이다."""
    if role is None:
        return False
    flag = getattr(role, 'can_edit_settings', None)
    if flag is None:
        flag = getattr(role, 'can_write', False)
    return bool(flag)


def role_can_edit_plots(role) -> bool:
    """작기 운영 쓰기(tool_registry 의 plot_write_tools)를 할 자격.

    웹 구획 화면(`routes_geo_plot._require_edit`)·구획 일지·작기 프로그램이
    `edit_plots` 를 요구하므로 같은 것을 본다(설정 편집이 함의). 읽기 전용
    키면 _role_for 가 이미 꺼 두었다. role 이 없으면 조회 전용이다."""
    if role is None:
        return False
    flag = getattr(role, 'can_edit_plots', None)
    if flag is None:
        flag = getattr(role, 'can_write', False)
    return bool(flag)


def role_can_advise(role) -> bool:
    """조언 원장(submit_advice)에 의견을 낼 자격.

    읽기 전용 키도 낼 수 있다 — 쓰기를 거부할 때 "대신 조언으로 남겨라" 고
    안내하기 때문이다. 막는 것은 AI 자체를 쓸 수 없는 역할뿐이다(웹 채팅과
    같은 `use_ai_chat`, 기본 표에서 Guest·Kiosk). role 이 없으면(인증을 끈
    서버) 판단 근거가 없으므로 예전처럼 허용한다 — 그 서버는 운영자가 일부러
    연 것이다."""
    if role is None:
        return True
    flag = getattr(role, 'can_use_ai_chat', None)
    return True if flag is None else bool(flag)


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
    can_edit_settings = bool(getattr(row, 'edit_settings', False))
    # AI 사용 권한 — 웹의 user_has_permission('use_ai_chat') 과 같은 규칙
    # (제어 권한이 함의한다). 읽기 전용 키와는 무관하다(조언은 쓰기가 아니다).
    can_use_ai_chat = role_row_allows(row, 'use_ai_chat')
    # 작기 운영 — 웹과 같이 설정 편집이 함의한다.
    can_edit_plots = role_row_allows(row, 'edit_plots')
    if key_row is not None and getattr(key_row, 'is_readonly', False) \
            and (can_write or can_edit_settings or can_edit_plots):
        logger.info(
            "[MCP] 읽기 전용 키 '%s' — 역할 %s 의 쓰기 권한을 이 연결에서는 끕니다.",
            key_row.name or (key_row.unique_id or '')[:8], row.name)
        can_write = False
        can_edit_settings = False
        can_edit_plots = False
    return RoleInfo(name=row.name, can_write=can_write,
                     user_id=user.unique_id,
                     can_edit_settings=can_edit_settings,
                     can_use_ai_chat=can_use_ai_chat,
                     can_edit_plots=can_edit_plots)


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
    return True, agent_id, _with_key_profile(
        _role_for(user, key_row), user, key_row), None


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
    return True, agent_id, _with_key_profile(
        _role_for(user, key_row), user, key_row), None


#: 기존 키에 묶음을 한 번 배정할 때 보는 사용 기록의 기간(일).
PROFILE_BACKFILL_DAYS = 90


def agent_id_belongs_to(agent_id, user_name) -> bool:
    """감사 기록의 agent_id 가 이 사용자 키로 들어온 호출인가.

    authenticate_http/authenticate_stdio 가 적는 형식은 `user:<이름>` 또는
    `user:<이름>/<클라이언트 표지>` 다. 인증을 끈 서버의 `unauthenticated:` 는
    자기 신고라 누구의 것으로도 치지 않는다."""
    if not agent_id or not user_name:
        return False
    head = 'user:%s' % user_name
    return agent_id == head or agent_id.startswith(head + '/')


def backfill_key_tool_profiles(now=None):
    """묶음이 비어 있는(NULL) 키에 한 번 값을 채운다 — 기동 때 부른다.

    발급된 키의 동작을 업그레이드로 조용히 바꾸지 않는다는 원칙(user_api_key)
    을 따라, 근거로 정한다: 키 소유자가 최근 90일에 설정 묶음에만 있는 도구를
    부른 적이 있으면 'configuration', 아니면 'operations'. 감사 기록에는 어느
    키였는지가 없으므로 **사람 단위**로 본다 — 그 사람의 키는 모두 같은 값이다.
    내부 AI 서비스 계정의 키는 언제나 'configuration' 이다.

    이미 값이 있는 키는 건드리지 않으므로 몇 번 불러도 같다. Flask 앱
    컨텍스트 안에서 불러야 한다. 반환: {'operations': n, 'configuration': m}.

    서비스 계정 키에 적는 값은 표시용일 뿐이다 — 연결은 키 행을 보지 않고
    제한 없음으로 들어온다(key_tool_profile).
    """
    from datetime import datetime, timedelta

    from aot.aot_flask.extensions import db
    from aot.databases.models import MCPAuditLog, User, UserAPIKey
    from aot.tools.tool_registry import (TOOL_PROFILE_CONFIGURATION,
                                         TOOL_PROFILE_OPERATIONS,
                                         profile_tools)

    counts = {TOOL_PROFILE_OPERATIONS: 0, TOOL_PROFILE_CONFIGURATION: 0}
    rows = UserAPIKey.query.filter(UserAPIKey.tool_profile.is_(None)).all()
    if not rows:
        return counts

    config_only = sorted(profile_tools(TOOL_PROFILE_CONFIGURATION)
                         - profile_tools(TOOL_PROFILE_OPERATIONS))
    since = (now or datetime.utcnow()) - timedelta(days=PROFILE_BACKFILL_DAYS)
    agent_ids = {
        aid for (aid,) in db.session.query(MCPAuditLog.agent_id)
        .filter(MCPAuditLog.timestamp >= since)
        .filter(MCPAuditLog.tool_name.in_(config_only))
        .filter(MCPAuditLog.agent_id.like('user:%'))
        .distinct()
        if aid}
    users = {u.id: u for u in
             User.query.filter(User.id.in_({r.user_id for r in rows})).all()}

    for row in rows:
        user = users.get(row.user_id)
        used_config = user is not None and any(
            agent_id_belongs_to(aid, user.name) for aid in agent_ids)
        if is_service_account(user) or used_config:
            row.tool_profile = TOOL_PROFILE_CONFIGURATION
        else:
            row.tool_profile = TOOL_PROFILE_OPERATIONS
        counts[row.tool_profile] += 1
    db.session.commit()
    logger.info(
        "[MCP] API 키 도구 묶음을 배정했습니다: 운영 %d개, 설정 %d개 "
        "(최근 %d일 사용 기록 기준)",
        counts[TOOL_PROFILE_OPERATIONS], counts[TOOL_PROFILE_CONFIGURATION],
        PROFILE_BACKFILL_DAYS)
    return counts
