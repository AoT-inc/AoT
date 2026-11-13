# coding=utf-8
# @manual ai/overview#embedded-auth
"""mcp_embedded.py — 이 AoT 가 직접 OAuth 인가 서버가 되는 방식(docs/design/mcp-embedded-oauth.md).

중앙 인가 서버(aot-auth) 없이 claude.ai 커넥터가 붙도록, 로그인한 AoT 사용자를 토큰 주인으로 삼아 접근 토큰(JWT, ES256)을
이 서버가 직접 낸다. 흐름 규칙(PKCE S256 만, `resource` 필수, 갱신 토큰은 쓸 때마다 교체)은 aot-auth 의 DESIGN §2~§4 를 따른다.

- HTTP 껍데기(`/register` `/authorize` `/token` `/revoke` 메타데이터 JWKS)는 `aot_flask/routes_oauth_embedded.py`,
  여기에는 상태를 바꾸는 규칙과 키·토큰·검증만 둔다. 웹(8084)과 MCP(5700)가 같은 DB·키 파일을 쓴다.
- 코드·갱신 토큰·클라이언트·연결 상태는 전부 DB(gunicorn 워커가 여럿). 코드와 갱신 토큰은 SHA-256 해시만 저장한다.
- 서명 키(ES256 개인 키)는 `databases/` 의 파일(권한 600) — DB·로그·백업에 넣지 않는다(백업은 DB 파일과 업로드 폴더만 복사한다).
"""
import hashlib
import json
import logging
import os
import re
import secrets
import time
from datetime import datetime, timedelta
from urllib.parse import urlsplit
from aot.utils.timekit import naive_utc, utc_now

logger = logging.getLogger(__name__)

ACCESS_SECONDS = 3600
REFRESH_DAYS = 30
CODE_SECONDS = 60
ACCESS_TYP = 'at+jwt'
ALG = 'ES256'

KEY_FILE = 'mcp_oauth_es256.pem'
KEY_FILE_ENV = 'AOT_MCP_OAUTH_KEY_FILE'
ALLOWLIST_ENV = 'AOT_MCP_REDIRECT_ALLOWLIST'

#: 등록을 받는 되돌림 주소 — aot-auth `auth_server/config.py` 의 첫 값과 같다. 루프백(Claude Code)은 포트·경로를 가리지 않는다.
DEFAULT_REDIRECT_ALLOWLIST = (
    'https://claude.ai/api/mcp/auth_callback',
    'https://claude.com/api/mcp/auth_callback',
    'http://localhost',
    'http://127.0.0.1',
)
LOOPBACK_HOSTS = ('localhost', '127.0.0.1', '::1')

MAX_CLIENTS = 500
MAX_REDIRECT_URIS = 10
CLIENT_STALE_DAYS = 7
GRANT_KEEP_DAYS = 30
_NAME_RE = re.compile(r'[\x00-\x1f\x7f]')


class OAuthError(Exception):
    """RFC 6749 오류 응답 — error 코드, 설명, HTTP 상태."""

    def __init__(self, error, description='', status=400):
        super().__init__(error)
        self.error = error
        self.description = description
        self.status = status


# ── 시간·해시·무작위 ────────────────────────────────────────────────────────

def sha256_hex(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def new_secret():
    return secrets.token_urlsafe(32)


def pkce_ok(verifier, challenge):
    """code_verifier(43~128자) 의 S256 값이 챌린지와 같은가."""
    import base64
    if not isinstance(verifier, str) or not 43 <= len(verifier) <= 128 or not isinstance(challenge, str):
        return False
    digest = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode('ascii', 'ignore')).digest()).decode().rstrip('=')
    return secrets.compare_digest(digest, challenge)


# ── 서명 키 ─────────────────────────────────────────────────────────────────

_key_cache = {}


def key_path():
    explicit = (os.environ.get(KEY_FILE_ENV) or '').strip()
    if explicit:
        return explicit
    from aot.config import DATABASE_PATH
    return os.path.join(DATABASE_PATH, KEY_FILE)


def ensure_key(path=None):
    """서명 키 파일이 없으면 만든다(권한 600). 있으면 건드리지 않는다. 워커 여럿이 동시에 불러도 안전하다
    (임시 파일에 쓰고 링크로 한 번에 자리를 잡는다 — 반쯤 쓴 파일을 읽는 일이 없다)."""
    from joserfc.jwk import ECKey
    path = path or key_path()
    if os.path.exists(path):
        return path
    folder = os.path.dirname(path) or '.'
    os.makedirs(folder, exist_ok=True)
    tmp = '%s.%d.%s.tmp' % (path, os.getpid(), secrets.token_hex(4))
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, 'wb') as out:
            out.write(ECKey.generate_key('P-256').as_pem(private=True))
        try:
            os.link(tmp, path)
        except FileExistsError:
            pass
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass
    return path


def _load_key(path):
    from joserfc.jwk import ECKey
    stat = os.stat(path)
    cached = _key_cache.get(path)
    if cached is not None and cached[0] == stat.st_mtime_ns:
        return cached[1]
    raw = ECKey.import_key(open(path, 'rb').read())
    key = ECKey.import_key(raw.as_dict(private=True), {'kid': raw.thumbprint(), 'use': 'sig', 'alg': ALG})
    _key_cache[path] = (stat.st_mtime_ns, key)
    return key


def signing_key():
    """서명 키. 처음 쓰는 때 만든다(내장 모드를 처음 켜고 첫 토큰을 낼 때). 서명은 aot-app 만 한다 — aot_mcp 는 읽기만."""
    return _load_key(ensure_key())


def public_key_set():
    """JWKS 에 싣고 검증에 쓰는 공개 키 전부 — 서명 키와 `<이름>.*.pem`(교체 중인 옛·새 키). 키 파일이 없으면 None."""
    import glob

    from joserfc.jwk import ECKey, KeySet
    path = key_path()
    if not os.path.exists(path):
        return None
    keys = {}
    stem = path[:-4] if path.endswith('.pem') else path
    for candidate in [path] + sorted(glob.glob(stem + '.*.pem')):
        try:
            key = _load_key(candidate)
        except (OSError, ValueError):
            logger.warning('[MCP] 서명 키 파일을 읽지 못했다: %s', os.path.basename(candidate))
            continue
        keys.setdefault(key.kid, ECKey.import_key(key.as_dict(private=False),
                                                   {'kid': key.kid, 'use': 'sig', 'alg': ALG}))
    return KeySet(list(keys.values())) if keys else None


def jwks():
    keys = public_key_set()
    return {'keys': [key.as_dict(private=False) for key in keys.keys] if keys is not None else []}


# ── 되돌림 주소 ─────────────────────────────────────────────────────────────

def redirect_allowlist():
    raw = (os.environ.get(ALLOWLIST_ENV) or '').strip()
    if raw:
        return tuple(item.strip() for item in raw.split(',') if item.strip())
    return DEFAULT_REDIRECT_ALLOWLIST


def _is_loopback_entry(parts):
    return parts.hostname in LOOPBACK_HOSTS and parts.path in ('', '/')


def redirect_allowed(uri, allowlist=None):
    """등록을 받아도 되는 되돌림 주소인가 — 정확히 일치, 루프백 항목은 스킴·호스트만 맞으면 포트·경로 무관."""
    if not isinstance(uri, str) or len(uri) > 2048:
        return False
    try:
        parts = urlsplit(uri)
        parts.port
    except ValueError:
        return False
    if parts.fragment or parts.username or parts.password or not parts.hostname:
        return False
    for allowed in (allowlist if allowlist is not None else redirect_allowlist()):
        allowed_parts = urlsplit(allowed)
        if _is_loopback_entry(allowed_parts):
            if parts.scheme == allowed_parts.scheme and parts.hostname == allowed_parts.hostname:
                return True
        elif uri == allowed:
            return True
    return False


def redirect_matches(registered, uri):
    """인가 요청의 redirect_uri 가 등록된 것 중 하나인가 — 정확히 일치, 루프백은 포트만 달라도 된다(RFC 8252 §7.3)."""
    if uri in registered:
        return True
    try:
        parts = urlsplit(uri)
        parts.port
    except ValueError:
        return False
    if parts.scheme != 'http' or parts.hostname not in LOOPBACK_HOSTS or parts.fragment:
        return False
    for item in registered:
        other = urlsplit(item)
        if other.scheme == 'http' and other.hostname == parts.hostname and other.path == parts.path \
                and other.query == parts.query:
            return True
    return False


# ── 클라이언트 등록(/register) ──────────────────────────────────────────────

def register_client(payload, allowlist=None):
    """RFC 7591 요청 본문(dict) → 응답 dict. 틀리면 OAuthError. 공개 클라이언트(비밀 없음)만 받는다."""
    from aot.aot_flask.extensions import db
    from aot.databases.models import OAuthClient

    if not isinstance(payload, dict):
        raise OAuthError('invalid_client_metadata', 'The request body must be a JSON object.')
    uris = payload.get('redirect_uris')
    if not isinstance(uris, list) or not uris or len(uris) > MAX_REDIRECT_URIS \
            or not all(isinstance(item, str) for item in uris):
        raise OAuthError('invalid_redirect_uri', 'redirect_uris must be a list of 1 to %d addresses.' % MAX_REDIRECT_URIS)
    for uri in uris:
        if not redirect_allowed(uri, allowlist):
            raise OAuthError('invalid_redirect_uri', 'This redirect URI is not allowed on this server.')
    method = payload.get('token_endpoint_auth_method', 'none')
    if method != 'none':
        raise OAuthError('invalid_client_metadata', 'Only token_endpoint_auth_method "none" (PKCE) is supported.')
    grants = payload.get('grant_types', ['authorization_code', 'refresh_token'])
    if not isinstance(grants, list) or not grants or not set(grants) <= {'authorization_code', 'refresh_token'} \
            or 'authorization_code' not in grants:
        raise OAuthError('invalid_client_metadata', 'grant_types may only be authorization_code and refresh_token.')
    if payload.get('response_types', ['code']) != ['code']:
        raise OAuthError('invalid_client_metadata', 'Only the "code" response type is supported.')
    name = payload.get('client_name', '')
    if not isinstance(name, str):
        raise OAuthError('invalid_client_metadata', 'client_name must be a string.')
    name = _NAME_RE.sub('', name).strip()[:100] or 'MCP client'

    prune()
    if OAuthClient.query.count() >= MAX_CLIENTS:
        raise OAuthError('temporarily_unavailable', 'Too many registered clients. Try again later.', 503)
    client_id = secrets.token_urlsafe(24)
    now = naive_utc(utc_now())
    db.session.add(OAuthClient(client_id=client_id, client_name=name, redirect_uris=json.dumps(uris),
                               created_at=now))
    db.session.commit()
    return {
        'client_id': client_id,
        'client_id_issued_at': int(time.time()),
        'client_name': name,
        'redirect_uris': uris,
        'grant_types': grants,
        'response_types': ['code'],
        'token_endpoint_auth_method': 'none',
    }


def get_client(client_id):
    from aot.databases.models import OAuthClient
    if not isinstance(client_id, str) or not client_id or len(client_id) > 64:
        return None
    return OAuthClient.query.filter_by(client_id=client_id).first()


def client_redirects(client):
    try:
        return json.loads(client.redirect_uris)
    except ValueError:
        return []


def prune():
    """쓰다 만 찌꺼기 정리 — 만료된 코드, 오래 전 끊긴·만료된 연결, 연결 없이 묵은 클라이언트."""
    from aot.aot_flask.extensions import db
    from aot.databases.models import OAuthClient, OAuthCode, OAuthGrant

    now = naive_utc(utc_now())
    OAuthCode.query.filter(OAuthCode.expires_at < now - timedelta(days=1)).delete(synchronize_session=False)
    old = now - timedelta(days=GRANT_KEEP_DAYS)
    OAuthGrant.query.filter(
        db.or_(db.and_(OAuthGrant.status == OAuthGrant.REVOKED, OAuthGrant.created_at < old),
               OAuthGrant.refresh_expires_at < old)).delete(synchronize_session=False)
    stale = now - timedelta(days=CLIENT_STALE_DAYS)
    live = db.session.query(OAuthGrant.client_id).filter(OAuthGrant.status == OAuthGrant.ACTIVE)
    OAuthClient.query.filter(
        OAuthClient.created_at < stale,
        db.or_(OAuthClient.last_used_at.is_(None), OAuthClient.last_used_at < stale),
        ~OAuthClient.client_id.in_(live)).delete(synchronize_session=False)
    db.session.commit()


# ── 인가 요청 검사(/authorize) ──────────────────────────────────────────────

class AuthorizeRequest:
    """검사를 통과한 인가 요청. `error` 가 있으면 클라이언트를 믿을 수 있는지에 따라 `redirect_ok` 로 갈린다."""

    def __init__(self):
        self.client = None
        self.issuer = ''           # 응답에 싣는 iss — 부르는 쪽이 채운다
        self.redirect_uri = ''
        self.state = ''
        self.resource = ''
        self.scopes = []           # 요청한 범위 ∩ 지원 범위 (읽기는 언제나 들어간다)
        self.code_challenge = ''
        self.error = None          # OAuthError
        self.redirect_ok = False   # True 면 오류를 redirect_uri 로 돌려줘도 된다(클라이언트·주소가 맞다)


def parse_authorize(args, public_url):
    """쿼리/폼 값 → AuthorizeRequest. 클라이언트·되돌림 주소가 틀리면 오류를 화면에, 그 밖의 오류는 되돌림 주소로 돌려준다."""
    from aot.tools import mcp_central
    from aot.tools.central_verify import normalize_resource

    req = AuthorizeRequest()
    client = get_client(args.get('client_id'))
    if client is None:
        req.error = OAuthError('invalid_client', 'Unknown client_id.')
        return req
    uri = args.get('redirect_uri') or ''
    if not uri or not redirect_matches(client_redirects(client), uri):
        req.error = OAuthError('invalid_request', 'redirect_uri does not match the registered address.')
        return req
    req.client, req.redirect_uri, req.redirect_ok = client, uri, True
    req.state = args.get('state') or ''

    if args.get('response_type') != 'code':
        req.error = OAuthError('unsupported_response_type', 'Only response_type=code is supported.')
        return req
    challenge = args.get('code_challenge') or ''
    if args.get('code_challenge_method') != 'S256' or not 43 <= len(challenge) <= 128:
        req.error = OAuthError('invalid_request', 'PKCE with code_challenge_method=S256 is required.')
        return req
    req.code_challenge = challenge
    resource = normalize_resource(args.get('resource') or '')
    if resource is None or resource != public_url:
        req.error = OAuthError('invalid_target', 'The resource must be this server\'s MCP address.')
        return req
    req.resource = resource
    supported = [name for name, _required in mcp_central.SCOPES]
    asked = (args.get('scope') or '').split()
    chosen = [name for name in supported if name in asked] if asked else list(supported)
    if mcp_central.SCOPE_READ not in chosen:
        chosen.insert(0, mcp_central.SCOPE_READ)
    req.scopes = chosen
    return req


def create_code(req, user, scopes):
    """동의가 끝난 요청 → 인가 코드 원문(저장은 해시만)."""
    from aot.aot_flask.extensions import db
    from aot.databases.models import OAuthCode

    raw = new_secret()
    db.session.add(OAuthCode(
        code_hash=sha256_hex(raw), client_id=req.client.client_id, user_id=user.id, resource=req.resource,
        scope=' '.join(scopes), code_challenge=req.code_challenge, redirect_uri=req.redirect_uri,
        expires_at=naive_utc(utc_now()) + timedelta(seconds=CODE_SECONDS)))
    db.session.commit()
    return raw


# ── 토큰 발급(/token) ───────────────────────────────────────────────────────

def _user_usable(user):
    return user is not None and getattr(user, 'is_enabled', True) and getattr(user, 'is_approved', True)


def issue_access(issuer, grant, scopes, now=None):
    """연결 하나에 대한 접근 토큰(JWT) 과 claims."""
    from joserfc import jwt
    key = signing_key()
    now = int(now or time.time())
    claims = {
        'iss': issuer, 'sub': str(grant.user_id), 'aud': grant.resource, 'client_id': grant.client_id,
        'scope': ' '.join(scopes), 'gid': grant.gid, 'client_name': grant.client_name or '',
        'iat': now, 'nbf': now, 'exp': now + ACCESS_SECONDS, 'jti': secrets.token_urlsafe(16),
    }
    return jwt.encode({'alg': ALG, 'typ': ACCESS_TYP, 'kid': key.kid}, claims, key), claims


def _token_response(issuer, grant, scopes, refresh_raw):
    access, claims = issue_access(issuer, grant, scopes)
    return {'access_token': access, 'token_type': 'Bearer', 'expires_in': claims['exp'] - int(time.time()),
            'refresh_token': refresh_raw, 'scope': ' '.join(scopes)}


def _check_resource(requested, expected):
    if requested:
        from aot.tools.central_verify import normalize_resource
        if normalize_resource(requested) != expected:
            raise OAuthError('invalid_target', 'The resource does not match this authorization.')


def exchange_code(*, issuer, public_url, client_id, code, redirect_uri, code_verifier, resource=None):
    """authorization_code 교환. 코드는 한 번만 쓰인다 — 검사가 하나라도 틀려도 이미 소모된 것으로 본다."""
    from aot.aot_flask.extensions import db
    from aot.databases.models import OAuthCode, OAuthGrant, User

    client = get_client(client_id)
    if client is None:
        raise OAuthError('invalid_client', 'Unknown client_id.')
    row = OAuthCode.query.filter_by(code_hash=sha256_hex(code or '')).first() if code else None
    if row is None or row.client_id != client.client_id:
        raise OAuthError('invalid_grant', 'The authorization code is not valid.')
    claimed = OAuthCode.query.filter_by(id=row.id, used=False).update({'used': True}, synchronize_session=False)
    db.session.commit()
    if claimed != 1:
        # 이미 쓴 코드가 다시 왔다 — 그 코드로 만든 연결이 있으면 훔쳐 쓴 것으로 보고 끊는다.
        if row.gid:
            revoke_grant(row.gid, 'code_reuse')
        raise OAuthError('invalid_grant', 'The authorization code was already used.')
    if row.expires_at < naive_utc(utc_now()):
        raise OAuthError('invalid_grant', 'The authorization code expired.')
    if redirect_uri != row.redirect_uri:
        raise OAuthError('invalid_grant', 'redirect_uri does not match the authorization request.')
    if not pkce_ok(code_verifier, row.code_challenge):
        raise OAuthError('invalid_grant', 'The PKCE code_verifier does not match.')
    _check_resource(resource, row.resource)
    if row.resource != public_url:
        raise OAuthError('invalid_target', 'This server\'s MCP address changed. Authorize again.')
    user = User.query.filter(User.id == row.user_id).first()
    if not _user_usable(user):
        raise OAuthError('invalid_grant', 'This account can no longer be used.')

    refresh_raw = new_secret()
    grant = OAuthGrant(
        gid=secrets.token_urlsafe(16), user_id=row.user_id, client_id=client.client_id,
        client_name=client.client_name or '', resource=row.resource, scope=row.scope,
        refresh_hash=sha256_hex(refresh_raw), refresh_expires_at=naive_utc(utc_now()) + timedelta(days=REFRESH_DAYS),
        status=OAuthGrant.ACTIVE, created_at=naive_utc(utc_now()), last_used_at=naive_utc(utc_now()))
    db.session.add(grant)
    row.gid = grant.gid
    client.last_used_at = naive_utc(utc_now())
    db.session.commit()
    return _token_response(issuer, grant, row.scope.split(), refresh_raw), grant


def refresh_grant(*, issuer, public_url, client_id, refresh_token, scope=None, resource=None):
    """refresh_token 교환 — 매번 새 갱신 토큰으로 교체한다. 옛 갱신 토큰이 다시 오면 연결 전체를 끊는다."""
    from aot.aot_flask.extensions import db
    from aot.databases.models import OAuthGrant, User

    client = get_client(client_id)
    if client is None:
        raise OAuthError('invalid_client', 'Unknown client_id.')
    if not refresh_token:
        raise OAuthError('invalid_request', 'refresh_token is required.')
    digest = sha256_hex(refresh_token)
    grant = OAuthGrant.query.filter(OAuthGrant.client_id == client.client_id,
                                    db.or_(OAuthGrant.refresh_hash == digest,
                                           OAuthGrant.prev_refresh_hash == digest)).first()
    if grant is None or grant.status != OAuthGrant.ACTIVE:
        raise OAuthError('invalid_grant', 'The refresh token is not valid.')
    if grant.refresh_hash != digest:
        revoke_grant(grant.gid, 'refresh_reuse')
        raise OAuthError('invalid_grant', 'The refresh token was already used. The connection was closed; authorize again.')
    if grant.refresh_expires_at < naive_utc(utc_now()):
        raise OAuthError('invalid_grant', 'The refresh token expired.')
    _check_resource(resource, grant.resource)
    if grant.resource != public_url:
        raise OAuthError('invalid_target', 'This server\'s MCP address changed. Authorize again.')
    user = User.query.filter(User.id == grant.user_id).first()
    if not _user_usable(user):
        revoke_grant(grant.gid, 'user_unusable')
        raise OAuthError('invalid_grant', 'This account can no longer be used.')
    granted = grant.scope.split()
    scopes = granted
    if scope:
        asked = scope.split()
        if not set(asked) <= set(granted):
            raise OAuthError('invalid_scope', 'The requested scope is wider than the original authorization.')
        scopes = [name for name in granted if name in asked]

    refresh_raw = new_secret()
    rotated = OAuthGrant.query.filter_by(id=grant.id, refresh_hash=digest, status=OAuthGrant.ACTIVE).update({
        'refresh_hash': sha256_hex(refresh_raw), 'prev_refresh_hash': digest,
        'refresh_expires_at': naive_utc(utc_now()) + timedelta(days=REFRESH_DAYS), 'last_used_at': naive_utc(utc_now())},
        synchronize_session=False)
    db.session.commit()
    if rotated != 1:
        # 같은 갱신 토큰을 동시에 두 번 보냈다 — 한쪽만 이긴다. 진 쪽은 거절.
        raise OAuthError('invalid_grant', 'The refresh token was already used.')
    db.session.refresh(grant)
    return _token_response(issuer, grant, scopes, refresh_raw), grant


# ── 끊기 ────────────────────────────────────────────────────────────────────

def revoke_grant(gid, reason):
    """연결 하나를 끊는다(이미 끊겼으면 그대로). 끊은 행 수."""
    from aot.aot_flask.extensions import db
    from aot.databases.models import OAuthGrant
    count = OAuthGrant.query.filter_by(gid=gid, status=OAuthGrant.ACTIVE).update(
        {'status': OAuthGrant.REVOKED, 'revoked_reason': reason}, synchronize_session=False)
    db.session.commit()
    return count


def revoke_user_grants(user_id, reason):
    """한 사용자의 연결을 전부 끊는다. 커밋은 부른 쪽이 한다(비밀번호 변경 등 다른 변경과 함께 확정)."""
    from aot.databases.models import OAuthGrant
    return OAuthGrant.query.filter_by(user_id=user_id, status=OAuthGrant.ACTIVE).update(
        {'status': OAuthGrant.REVOKED, 'revoked_reason': reason}, synchronize_session=False)


def revoke_token(token, client_id, issuer):
    """/revoke — 갱신 토큰이든 접근 토큰이든 그 연결을 끊는다. 모르는 토큰은 조용히 넘어간다(RFC 7009). 끊은 gid 또는 None."""
    from aot.aot_flask.extensions import db
    from aot.databases.models import OAuthGrant

    client = get_client(client_id)
    if client is None or not token:
        return None
    grant = None
    if token.count('.') == 2:
        claims = decode_own(token, issuer)
        if claims is not None and claims.get('client_id') == client.client_id:
            grant = OAuthGrant.query.filter_by(gid=claims.get('gid')).first()
    else:
        digest = sha256_hex(token)
        grant = OAuthGrant.query.filter(OAuthGrant.client_id == client.client_id,
                                        db.or_(OAuthGrant.refresh_hash == digest,
                                               OAuthGrant.prev_refresh_hash == digest)).first()
    if grant is None:
        return None
    revoke_grant(grant.gid, 'client_revoke')
    return grant.gid


def decode_own(token, issuer):
    """이 서버가 서명한 접근 토큰이면 claims(만료는 보지 않는다 — 끊기용), 아니면 None."""
    from joserfc import jwt
    keys = public_key_set()
    if keys is None:
        return None
    try:
        decoded = jwt.decode(token, keys, algorithms=[ALG])
    except Exception:
        return None
    if decoded.header.get('typ') != ACCESS_TYP or decoded.claims.get('iss') != issuer:
        return None
    return decoded.claims


# ── 메타데이터 ──────────────────────────────────────────────────────────────

def authorization_server_metadata(issuer):
    from aot.tools import mcp_central
    return {
        'issuer': issuer,
        'authorization_endpoint': issuer + '/authorize',
        'token_endpoint': issuer + '/token',
        'registration_endpoint': issuer + '/register',
        'revocation_endpoint': issuer + '/revoke',
        'jwks_uri': issuer + '/.well-known/jwks.json',
        'scopes_supported': [name for name, _required in mcp_central.SCOPES],
        'response_types_supported': ['code'],
        'response_modes_supported': ['query'],
        'grant_types_supported': ['authorization_code', 'refresh_token'],
        'token_endpoint_auth_methods_supported': ['none'],
        'revocation_endpoint_auth_methods_supported': ['none'],
        'code_challenge_methods_supported': ['S256'],
        'authorization_response_iss_parameter_supported': True,
    }


# ── 토큰 검증(aot_mcp) ──────────────────────────────────────────────────────

def make_verifier(issuer, resource):
    """공용 검증 코드(`CentralTokenVerifier`)를 파일 키 + 연결 상태 조회로 바꾼 것. 요청마다 DB 한 줄을 본다."""
    from aot.tools.central_verify import CentralTokenVerifier

    class EmbeddedTokenVerifier(CentralTokenVerifier):
        def _key_set(self, kid):
            return public_key_set()

        def _maybe_refresh_revocations(self):
            return None  # 폐지 목록을 받아 오지 않는다 — 아래에서 oauth_grant 를 직접 본다

        def verify(self, token):
            claims = super().verify(token)
            if claims is None:
                return None
            from aot.databases.models import OAuthGrant
            grant = OAuthGrant.query.filter_by(gid=claims.gid).first()
            if (grant is None or grant.status != OAuthGrant.ACTIVE or grant.refresh_expires_at < naive_utc(utc_now())
                    or str(grant.user_id) != claims.sub or grant.client_id != claims.client_id
                    or grant.resource != claims.aud):
                return None
            return claims

    return EmbeddedTokenVerifier(issuer, resource, http=object())


def check(cfg, _=lambda text, **values: text % values if values else text):
    """설정 화면의 "연결 점검" (내장) — 외부에 나가지 않고 이 서버 안의 준비 상태를 본다."""
    results = []
    if not cfg.public_url:
        results.append(('public_url', False, _('The public MCP address is empty or malformed (it needs a path such as /mcp).')))
        return results
    if not cfg.issuer:
        results.append(('issuer', False, _('The public MCP address must be https (http only for localhost).')))
        return results
    results.append(('public_url', True, _('Issuer (this server): %(issuer)s', issuer=cfg.issuer)))
    try:
        ensure_key()
        count = len(jwks()['keys'])
    except Exception as exc:
        results.append(('jwks', False, _('Cannot create or read the signing key (%(error)s).', error=type(exc).__name__)))
        return results
    results.append(('jwks', count > 0, _('%(count)s signing key(s) published.', count=count) if count
                    else _('No ES256 signing keys at /.well-known/jwks.json.')))
    return results
