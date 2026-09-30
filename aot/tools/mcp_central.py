# coding=utf-8
# @manual ai/overview#central-auth
"""mcp_central.py — 외부 MCP 의 중앙 인증(OAuth 인가 서버가 낸 접근 토큰).

API 키(`X-API-KEY`)는 그대로 두고, 켜면 `Authorization: Bearer <JWT>` 도 받는다. 이 서버는 **자원 서버**다 —
로그인·동의·토큰 발급은 인가 서버가 하고, 여기서는 토큰의 서명·발급자·대상(aud)·만료·폐지 목록만 확인한다
(`aot/tools/central_verify`, 저장소 aot-auth 의 공용 검증 코드 사본).

주소를 코드에 박지 않는다. 설치처마다 네트워크(VPN·사설망·공인망)와 도메인이 다르므로 인가 서버 주소와
이 서버의 MCP 공개 주소는 설정 > 일반 > AI 서비스의 "MCP 인증 설정" 에서 정한다. 여러 대에 같은 값을 넣을 때는
환경변수가 화면 값보다 앞선다(google_oauth.py 와 같은 규칙).

실제로 통하는 권한 = 토큰 범위 ∩ 연결된 사용자의 역할. 범위는 역할 위에 얹히는 상한이다(API 키 스코프와 같다).
"""
import base64
import hashlib
import logging
import os
import secrets
import threading
from collections import namedtuple
from urllib.parse import urlencode, urlsplit

logger = logging.getLogger(__name__)

SCOPE_READ = 'aot.read'
SCOPE_CONTROL = 'aot.control'
SCOPE_CONFIG = 'aot.config'
#: 인가 서버에 이 사이트를 등록할 때 적는 범위 — (이름, 필수 여부). 읽기는 언제나 허용한다.
SCOPES = ((SCOPE_READ, True), (SCOPE_CONTROL, False), (SCOPE_CONFIG, False))

CALLBACK_PATH = '/settings/mcp_auth/callback'

_ENV = {
    'enabled': 'AOT_MCP_CENTRAL',
    'issuer': 'AOT_MCP_CENTRAL_ISSUER',
    'public_url': 'AOT_MCP_PUBLIC_URL',
    'link_client_id': 'AOT_MCP_LINK_CLIENT_ID',
    'link_client_secret': 'AOT_MCP_LINK_CLIENT_SECRET',
}

CentralConfig = namedtuple('CentralConfig', [
    'enabled', 'issuer', 'public_url', 'link_client_id', 'link_client_secret', 'web_base_url', 'from_env'])

_verifiers = {}
_verifiers_lock = threading.Lock()


def _env(name):
    return (os.environ.get(_ENV[name]) or '').strip()


def normalize_issuer(value):
    """발급자 주소 → 끝 `/` 없는 https 주소. 틀리면 None.

    http 는 루프백만 받는다 — 서명 키(JWKS)를 평문으로 받으면 가운데서 키를 바꿔 토큰을 위조할 수 있다."""
    value = (value or '').strip().rstrip('/')
    if not value:
        return None
    try:
        parts = urlsplit(value)
    except ValueError:
        return None
    if not parts.hostname or parts.query or parts.fragment or parts.username or parts.password:
        return None
    if parts.scheme == 'https':
        return value
    if parts.scheme == 'http' and parts.hostname in ('localhost', '127.0.0.1', '::1'):
        return value
    return None


def normalize_public_url(value):
    """MCP 공개 주소 → 토큰 aud 와 비교할 정규형(소문자 호스트·기본 포트 없음·끝 `/` 없음). 틀리면 None."""
    from aot.tools.central_verify import normalize_resource
    normalized = normalize_resource((value or '').strip())
    if normalized is None or not urlsplit(normalized).path:
        return None
    return normalized


def normalize_web_base(value):
    value = (value or '').strip().rstrip('/')
    if not value:
        return None
    parts = urlsplit(value)
    if parts.scheme not in ('https', 'http') or not parts.hostname or parts.query or parts.fragment:
        return None
    return value


def config():
    """지금 설정. Flask 앱 컨텍스트 안에서 부른다. 환경변수가 있는 칸은 화면 값보다 앞선다."""
    from aot.databases.models import AIGlobalSettings, Misc
    from aot.utils.crypto import decrypt_secret

    row = AIGlobalSettings.query.first()
    misc = Misc.query.first()
    from_env = {name: bool(_env(name)) for name in _ENV}
    from_env['web_base_url'] = bool((os.environ.get('OAUTH_PUBLIC_BASE_URL') or '').strip())

    if from_env['enabled']:
        enabled = _env('enabled') not in ('0', 'false', 'False')
    else:
        enabled = bool(row is not None and row.mcp_central_enabled)
    issuer = _env('issuer') or (row.mcp_central_issuer if row is not None else '') or ''
    public_url = _env('public_url') or (row.mcp_public_url if row is not None else '') or ''
    client_id = _env('link_client_id') or (row.mcp_link_client_id if row is not None else '') or ''
    secret = _env('link_client_secret') or (
        decrypt_secret(row.mcp_link_client_secret) if row is not None else None) or ''
    web_base = (os.environ.get('OAUTH_PUBLIC_BASE_URL') or '').strip() or (
        (misc.oauth_public_base_url or '') if misc is not None else '')
    return CentralConfig(
        enabled=enabled,
        issuer=normalize_issuer(issuer) or '',
        public_url=normalize_public_url(public_url) or '',
        link_client_id=client_id.strip(),
        link_client_secret=secret.strip(),
        web_base_url=normalize_web_base(web_base) or '',
        from_env=from_env)


def is_active(cfg):
    """토큰을 받을 수 있는 상태인가 — 켜져 있고 발급자·공개 주소가 맞는 모양일 때."""
    return bool(cfg.enabled and cfg.issuer and cfg.public_url)


def can_link(cfg):
    return bool(is_active(cfg) and cfg.link_client_id and cfg.link_client_secret and cfg.web_base_url)


def verifier(cfg):
    """(발급자, 공개 주소)마다 하나 — JWKS·폐지 목록 캐시를 요청 사이에 나눠 쓴다."""
    from aot.tools.central_verify import CentralTokenVerifier
    key = (cfg.issuer, cfg.public_url)
    with _verifiers_lock:
        found = _verifiers.get(key)
        if found is None:
            found = _verifiers[key] = CentralTokenVerifier(cfg.issuer, cfg.public_url)
        return found


def looks_like_jwt(token):
    """JWS 압축형(점 두 개)인가. API 키(base64)는 점이 없다."""
    return bool(token) and token.count('.') == 2


def resource_metadata_url(cfg):
    """RFC 9728 — 공개 주소의 호스트 뒤, 경로 앞에 `/.well-known/oauth-protected-resource` 를 끼운다."""
    parts = urlsplit(cfg.public_url)
    return f"{parts.scheme}://{parts.netloc}/.well-known/oauth-protected-resource{parts.path}"


def protected_resource_metadata(cfg):
    return {
        'resource': cfg.public_url,
        'authorization_servers': [cfg.issuer],
        'scopes_supported': [name for name, _required in SCOPES],
        'bearer_methods_supported': ['header'],
        'resource_name': 'AoT',
    }


def www_authenticate(cfg, invalid=False):
    value = f'Bearer resource_metadata="{resource_metadata_url(cfg)}"'
    if invalid:
        value += ', error="invalid_token"'
    return value


# 결과 종류 — authenticate 의 kind
OK = 'ok'
INVALID = 'invalid'            # 토큰 자체가 틀림 → HTTP 401(클라이언트가 다시 인증)
NOT_LINKED = 'not_linked'      # 토큰은 맞지만 이 AoT 사용자와 이어지지 않음 → 도구 오류로 안내
NO_READ_SCOPE = 'no_read_scope'

CentralResult = namedtuple('CentralResult', ['kind', 'user', 'claims'])


def authenticate(cfg, token):
    """접근 토큰 → CentralResult. Flask 앱 컨텍스트 안에서 부른다."""
    from aot.databases.models import MCPExternalAccount, User

    claims = verifier(cfg).verify(token)
    if claims is None:
        return CentralResult(INVALID, None, None)
    if SCOPE_READ not in claims.scopes:
        return CentralResult(NO_READ_SCOPE, None, claims)
    link = MCPExternalAccount.query.filter_by(issuer=claims.iss, subject=claims.sub).first()
    user = User.query.filter(User.id == link.user_id).first() if link is not None else None
    if user is None or not getattr(user, 'is_enabled', True) or not getattr(user, 'is_approved', True):
        return CentralResult(NOT_LINKED, None, claims)
    return CentralResult(OK, user, claims)


def restrict_role(role, scopes):
    """역할 스냅샷(mcp_auth.RoleInfo)을 토큰 범위로 좁힌다 — 둘 중 좁은 쪽이 이긴다.

    제어(쓰기 도구)는 aot.control, 설정·기록·작기 운영은 aot.config 가 있어야 한다. 도구 묶음도 범위를 따른다.

    중앙 토큰에는 키 행이 없어 설정 모듈(tool_registry.TOOL_MODULES)을 고를 자리가 없다 — aot.config 는
    'configuration'(모듈 전부), 없으면 'operations'(모듈 없음)다. 이 값이 API 키와 같은 묶음 값이라 목록·실행·
    안내문·거절은 전송과 무관하게 같은 규칙을 탄다."""
    from aot.tools.tool_registry import TOOL_PROFILE_CONFIGURATION, TOOL_PROFILE_OPERATIONS
    if role is None:
        return None
    scopes = set(scopes or ())
    config_ok = SCOPE_CONFIG in scopes
    return role._replace(
        can_write=bool(role.can_write and SCOPE_CONTROL in scopes),
        can_edit_settings=bool(role.can_edit_settings and config_ok),
        can_edit_plots=bool(role.can_edit_plots and config_ok),
        tool_profile=TOOL_PROFILE_CONFIGURATION if config_ok else TOOL_PROFILE_OPERATIONS)


def link_help(cfg):
    """연결이 없을 때 도구 결과로 돌려줄 안내."""
    where = (cfg.web_base_url + '/settings/general') if cfg.web_base_url else 'Settings > General > AI Service'
    return ("This AI connection is signed in to the authorization server, but it is not linked to a user of "
            "this AoT. Sign in to AoT as yourself, open %s, choose \"MCP Authentication Settings\" and press "
            "\"Link My Account\". Then try again." % where)


# ── 계정 연결(OpenID Connect 인가 코드 + PKCE) ──────────────────────────────

def redirect_uri(cfg):
    return cfg.web_base_url + CALLBACK_PATH if cfg.web_base_url else ''


def new_pkce():
    code_verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(code_verifier.encode()).digest()).decode().rstrip('=')
    return code_verifier, challenge


def authorize_url(cfg, *, state, code_challenge, nonce):
    params = {
        'response_type': 'code',
        'client_id': cfg.link_client_id,
        'redirect_uri': redirect_uri(cfg),
        'scope': 'openid',
        'state': state,
        'code_challenge': code_challenge,
        'code_challenge_method': 'S256',
        'nonce': nonce,
    }
    return f"{cfg.issuer}/link/authorize?{urlencode(params)}"


class LinkError(Exception):
    pass


def exchange_link_code(cfg, *, code, code_verifier, nonce):
    """코드 → ID 토큰 → 확인된 claims. 실패하면 LinkError."""
    import requests

    from aot.tools.central_verify import IdTokenError, verify_id_token
    try:
        response = requests.post(
            f"{cfg.issuer}/link/token",
            data={'grant_type': 'authorization_code', 'code': code,
                  'redirect_uri': redirect_uri(cfg), 'code_verifier': code_verifier},
            auth=(cfg.link_client_id, cfg.link_client_secret),
            timeout=10, allow_redirects=False)
    except requests.RequestException as exc:
        raise LinkError('token endpoint unreachable: %s' % type(exc).__name__) from exc
    if response.status_code != 200:
        raise LinkError('token endpoint %s' % response.status_code)
    try:
        id_token = response.json().get('id_token')
    except ValueError as exc:
        raise LinkError('token endpoint returned no JSON') from exc
    try:
        return verify_id_token(verifier(cfg), id_token or '', cfg.link_client_id, nonce=nonce)
    except IdTokenError as exc:
        raise LinkError(str(exc)) from exc


def link_account(cfg, user, claims):
    """확인된 ID 토큰의 sub 를 이 사용자와 잇는다. 그 sub 가 다른 사용자에게 이어져 있으면 LinkError."""
    from aot.aot_flask.extensions import db
    from aot.databases.models import MCPExternalAccount

    issuer, subject = claims.get('iss') or cfg.issuer, claims.get('sub')
    if not subject:
        raise LinkError('no subject')
    taken = MCPExternalAccount.query.filter_by(issuer=issuer, subject=subject).first()
    if taken is not None and taken.user_id != user.id:
        raise LinkError('already linked to another user')
    mine = MCPExternalAccount.query.filter_by(issuer=issuer, user_id=user.id).first()
    if mine is None:
        mine = MCPExternalAccount(issuer=issuer, user_id=user.id)
        db.session.add(mine)
    mine.subject = subject
    mine.label = (claims.get('email') or claims.get('name') or '')[:255]
    from datetime import datetime
    mine.linked_at = datetime.utcnow()
    db.session.commit()
    return mine


def linked_account(cfg, user):
    from aot.databases.models import MCPExternalAccount
    if user is None or not cfg.issuer:
        return None
    return MCPExternalAccount.query.filter_by(issuer=cfg.issuer, user_id=user.id).first()


# ── 연결 점검 ───────────────────────────────────────────────────────────────

def _plain(text, **values):
    return text % values if values else text


def check(cfg, _=_plain):
    """설정 화면의 "연결 점검" — [(항목, 통과 여부, 설명)]. 인가 서버에 실제로 닿아 본다.

    `_` 는 번역 함수(flask_babel.gettext 처럼 이름 붙은 자리표시를 받는다)."""
    import requests

    results = []
    if not cfg.issuer:
        results.append(('issuer', False, _('The authorization server address is empty or not https.')))
        return results
    if not cfg.public_url:
        results.append(('public_url', False, _('The public MCP address is empty or malformed (it needs a path such as /mcp).')))

    meta = None
    for path in ('/.well-known/oauth-authorization-server', '/.well-known/openid-configuration'):
        try:
            response = requests.get(cfg.issuer + path, timeout=5, allow_redirects=False)
        except requests.RequestException as exc:
            results.append(('metadata', False, _('Cannot reach %(address)s (%(error)s).',
                                                  address=cfg.issuer, error=type(exc).__name__)))
            return results
        if response.status_code == 200:
            try:
                meta = response.json()
            except ValueError:
                meta = None
            break
    if not isinstance(meta, dict):
        results.append(('metadata', False, _('The server did not publish authorization server metadata.')))
        return results
    if (meta.get('issuer') or '').rstrip('/') != cfg.issuer:
        results.append(('metadata', False, _('The server says its issuer is "%(issuer)s", not the address entered.',
                                              issuer=meta.get('issuer'))))
        return results
    results.append(('metadata', True, _('Authorization server metadata found.')))

    try:
        response = requests.get(cfg.issuer + '/.well-known/jwks.json', timeout=5, allow_redirects=False)
        keys = [k for k in (response.json().get('keys') or []) if k.get('kty') == 'EC'] if response.status_code == 200 else []
    except (requests.RequestException, ValueError):
        keys = []
    results.append(('jwks', bool(keys), _('%(count)s signing key(s) published.', count=len(keys)) if keys
                    else _('No ES256 signing keys at /.well-known/jwks.json.')))

    if cfg.link_client_id or cfg.link_client_secret or cfg.web_base_url:
        missing = [label for label, value in ((_('client ID'), cfg.link_client_id),
                                              (_('client secret'), cfg.link_client_secret),
                                              (_('public web address'), cfg.web_base_url)) if not value]
        results.append(('link', not missing, _('Account linking is ready.') if not missing
                        else _('Account linking needs: %(missing)s.', missing=', '.join(missing))))
    return results
