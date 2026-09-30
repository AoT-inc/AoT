import json
import logging
import threading
import time
from dataclasses import dataclass, field
from urllib.parse import urlsplit

import httpx
from joserfc import jws, jwt
from joserfc.errors import JoseError
from joserfc.jwk import KeySet

log = logging.getLogger("aot_auth_verify")

ALG = "ES256"
ACCESS_TYP = "at+jwt"
REVOCATIONS_TYP = "revocations+jwt"
LEEWAY = 60
JWKS_TTL = 3600
JWKS_RETRY = 60
REVOCATIONS_EVERY = 60
REVOCATIONS_STALE_WARN = 600
FETCH_TIMEOUT = 5.0


def normalize_resource(value):
    """인증 서버(auth_server.resources.normalize)와 같은 규칙: 소문자 호스트 · 기본 포트 없음 · 끝 / 없음."""
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parts = urlsplit(value.strip())
        port = parts.port
    except ValueError:
        return None
    if parts.scheme not in ("https", "http") or not parts.hostname:
        return None
    if parts.query or parts.fragment or parts.username or parts.password:
        return None
    host = parts.hostname.lower()
    default = 443 if parts.scheme == "https" else 80
    netloc = host if port in (None, default) else f"{host}:{port}"
    return f"{parts.scheme}://{netloc}{parts.path.rstrip('/')}"


@dataclass(frozen=True)
class Claims:
    """확인을 통과한 접근 토큰. sub 로 그 사이트의 사용자를 찾는다(계정 연결, DESIGN §6)."""

    token: str
    sub: str
    client_id: str
    scopes: list = field(default_factory=list)
    gid: str = ""
    client_name: str = ""
    exp: int = 0
    aud: str = ""
    iss: str = ""


class _Http:
    """기본 받아 오기(httpx). 시험에서는 get(url) -> (status, headers, bytes) 인 것을 넘긴다."""

    def __init__(self, timeout=FETCH_TIMEOUT):
        self.client = httpx.Client(timeout=timeout, follow_redirects=False)

    def get(self, url):
        response = self.client.get(url)
        return response.status_code, response.headers, response.content


class CentralTokenVerifier:
    def __init__(self, issuer, resource, *, http=None, clock=time.time, leeway=LEEWAY,
                 jwks_url=None, revocations_url=None):
        self.issuer = issuer.rstrip("/")
        self.resource = normalize_resource(resource)
        if self.resource is None:
            raise ValueError(f"resource 모양이 틀렸다: {resource!r}")
        self.jwks_url = jwks_url or f"{self.issuer}/.well-known/jwks.json"
        self.revocations_url = revocations_url or f"{self.issuer}/revocations"
        self.http = http or _Http()
        self.clock = clock
        self.leeway = leeway
        self._lock = threading.Lock()
        self._keys = None
        self._keys_at = 0.0
        self._keys_retry_at = 0.0
        self._revoked_grants = frozenset()
        self._revoked_accounts = {}
        self._revocations_at = None  # 마지막으로 받은 시각
        self._revocations_tried_at = 0.0
        self._warned_stale_at = 0.0

    # ── 받아 오기 ──

    def _fetch_keys(self):
        status, _headers, body = self.http.get(self.jwks_url)
        if status != 200:
            raise RuntimeError(f"JWKS {status}")
        keys = [key for key in json.loads(body)["keys"] if key.get("kty") == "EC" and key.get("kid")]
        self._keys = KeySet.import_key_set({"keys": keys})
        self._keys_at = self.clock()

    def _key_set(self, kid):
        now = self.clock()
        with self._lock:
            known = self._keys is not None and any(key.kid == kid for key in self._keys.keys)
            expired = self._keys is None or now - self._keys_at > JWKS_TTL
            if (expired or not known) and now >= self._keys_retry_at:
                self._keys_retry_at = now + JWKS_RETRY
                try:
                    self._fetch_keys()
                except Exception as error:  # 가용성 우선 — 가진 키로 계속
                    log.warning("JWKS 를 받지 못했다: %s", error)
            return self._keys

    def refresh_revocations(self):
        """폐지 목록을 받는다. 실패하면 마지막 것을 그대로 두고 False."""
        now = self.clock()
        self._revocations_tried_at = now
        try:
            status, _headers, body = self.http.get(self.revocations_url)
            if status != 200:
                raise RuntimeError(f"revocations {status}")
            keys = self._key_set(_kid_of(body.decode()))
            if keys is None:
                raise RuntimeError("no keys")
            obj = jws.deserialize_compact(body.decode(), keys, algorithms=[ALG])
            if obj.headers().get("typ") != REVOCATIONS_TYP:
                raise RuntimeError("wrong typ")
            document = json.loads(obj.payload)
            if document.get("iss") != self.issuer:
                raise RuntimeError("wrong iss")
            issued = int(document["issued_at"])
            if self._revocations_at is not None and issued < self._revocations_at - LEEWAY:
                raise RuntimeError("older list")
        except Exception as error:
            log.warning("폐지 목록을 받지 못했다: %s", error)
            self._warn_if_stale(now)
            return False
        self._revoked_grants = frozenset(document.get("grants") or ())
        self._revoked_accounts = {row["sub"]: int(row["not_before"]) for row in document.get("accounts") or ()}
        self._revocations_at = issued
        return True

    def _warn_if_stale(self, now):
        # 가용성 우선(DESIGN §3-4): 막지 않고, 10분 넘게 낡으면 경고만 남긴다(10분마다 한 번)
        age = None if self._revocations_at is None else now - self._revocations_at
        if (age is None or age > REVOCATIONS_STALE_WARN) and now - self._warned_stale_at > REVOCATIONS_STALE_WARN:
            self._warned_stale_at = now
            log.error("폐지 목록이 %s 낡았다 — 인증 서버(%s)에 닿는지 확인", "처음부터" if age is None else f"{int(age)}초", self.issuer)

    def _maybe_refresh_revocations(self):
        if self.clock() - self._revocations_tried_at >= REVOCATIONS_EVERY:
            self.refresh_revocations()

    # ── 확인 ──

    def verify(self, token):
        """통과하면 Claims, 아니면 None."""
        if not token or token.count(".") != 2:
            return None
        try:
            header = _header_of(token)
        except ValueError:
            return None
        if header.get("alg") != ALG or header.get("typ") != ACCESS_TYP or not header.get("kid"):
            return None
        keys = self._key_set(header["kid"])
        if keys is None:
            return None
        try:
            decoded = jwt.decode(token, keys, algorithms=[ALG])
            registry = jwt.JWTClaimsRegistry(
                now=int(self.clock()),
                leeway=self.leeway,
                iss={"essential": True, "value": self.issuer},
                sub={"essential": True},
                exp={"essential": True},
                nbf={"essential": True},
                iat={"essential": True},
            )
            registry.validate(decoded.claims)
        except (JoseError, ValueError, KeyError):
            return None
        claims = decoded.claims
        # aud 는 문자열 하나, 자기 주소와 정확히 같아야 한다(DESIGN §3-2). 목록·정규화 전 값은 받지 않는다
        if not isinstance(claims.get("aud"), str) or claims["aud"] != self.resource:
            return None
        if not claims.get("gid") or not claims.get("client_id"):
            return None
        self._maybe_refresh_revocations()
        if claims["gid"] in self._revoked_grants:
            return None
        not_before = self._revoked_accounts.get(claims["sub"])
        if not_before is not None and int(claims["iat"]) <= not_before:
            return None
        return Claims(
            token=token,
            sub=claims["sub"],
            client_id=claims["client_id"],
            scopes=(claims.get("scope") or "").split(),
            gid=claims["gid"],
            client_name=claims.get("client_name") or "",
            exp=int(claims["exp"]),
            aud=claims["aud"],
            iss=claims["iss"],
        )

    async def verify_token(self, token):
        """MCP SDK 의 TokenVerifier. 받아 오기가 막을 수 있어 스레드에서 돌린다."""
        import anyio.to_thread
        from mcp.server.auth.provider import AccessToken

        claims = await anyio.to_thread.run_sync(self.verify, token)
        if claims is None:
            return None
        return AccessToken(
            token=token,
            client_id=claims.client_id,
            scopes=claims.scopes,
            expires_at=claims.exp,
            resource=claims.aud,
            subject=claims.sub,
            claims={"iss": claims.iss, "gid": claims.gid, "client_name": claims.client_name},
        )


class IdTokenError(Exception):
    pass


def verify_id_token(verifier, id_token, client_id, nonce=None):
    """계정 연결(DESIGN §6)의 ID 토큰. aud = 이 사이트의 연결 클라이언트 ID. 통과하면 claims(dict)."""
    try:
        header = _header_of(id_token)
    except ValueError as error:
        raise IdTokenError("malformed") from error
    if header.get("alg") != ALG or header.get("typ") != "JWT":
        raise IdTokenError("wrong header")
    keys = verifier._key_set(header.get("kid"))
    if keys is None:
        raise IdTokenError("no keys")
    try:
        decoded = jwt.decode(id_token, keys, algorithms=[ALG])
        jwt.JWTClaimsRegistry(
            now=int(verifier.clock()),
            leeway=verifier.leeway,
            iss={"essential": True, "value": verifier.issuer},
            aud={"essential": True, "value": client_id},
            sub={"essential": True},
            exp={"essential": True},
        ).validate(decoded.claims)
    except (JoseError, ValueError) as error:
        raise IdTokenError(str(error)) from error
    if nonce is not None and decoded.claims.get("nonce") != nonce:
        raise IdTokenError("wrong nonce")
    return decoded.claims


def _header_of(token):
    import base64

    head = token.split(".", 1)[0]
    try:
        return json.loads(base64.urlsafe_b64decode(head + "=" * (-len(head) % 4)))
    except Exception as error:
        raise ValueError("bad header") from error


def _kid_of(compact):
    try:
        return _header_of(compact).get("kid")
    except ValueError:
        return None
