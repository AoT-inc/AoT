# coding=utf-8
"""VIGI Open API V1.1 클라이언트 — HTTPS JSON, doAuth 2단계 SHA-256. 설계 §6, 조사 §2.2.

인증 보호가 최우선 계약이다:
- 모든 인증 시도는 `AuthGuard.begin` 을 거친다. 거부되면 **카메라에 아무것도 보내지 않는다.**
- 인증 실패(-10020/-10022, 모르는 인증 응답)는 즉시 래치한다. 이 클라이언트에는 재시도 루프가 없다.
- 재인증(stok 만료)은 `verified_fp` 와 같은 자격 증명으로 1회만.
- TLS 지문(TOFU 고정)이 다르면 **자격 증명을 보내기 전에** 멈춘다.
- 비밀번호·digest response·stok 은 로그·예외·CamResult 에 남기지 않는다(stok 은 앞 4자).
"""
import hashlib
import http.client
import json
import logging
import socket
import ssl
import threading
import time

from aot.camera_drivers.auth_guard import AuthGuard, Permit
from aot.camera_drivers.auth_guard import credential_fp as make_fp
from aot.camera_drivers.driver import CamResult, Credential, ErrorClass, short_token
from aot.camera_drivers.vigi import errors as E

logger = logging.getLogger(__name__)

DEFAULT_PORT = 20443
STOK_REFRESH_S = 25 * 60   # stok 수명 30분 [문서]. 25분이 지나면 다음 호출 전에 새로 받는다(§6.2)


class TransportError(Exception):
    """연결·전송 오류. `sent` 가 True 면 요청 본문이 이미 카메라로 나갔다."""

    def __init__(self, message, sent=False, refused=False):
        super().__init__(message)
        self.sent = sent
        self.refused = refused   # 포트가 닫혀 있음(연결 거부) — OpenAPI 꺼짐의 근거


class CertMismatch(Exception):
    """서버 인증서 지문이 고정값과 다르다. 본문을 보내기 전에 던진다."""

    def __init__(self, observed):
        super().__init__('certificate fingerprint changed')
        self.observed = observed


def https_post(host, port, path, body: bytes, tls_pin=None, timeout=5.0):
    """요청마다 새 연결(문서 원칙). 반환: (http_status, body_bytes, peer_pin_sha256).

    자체 서명 인증서를 받아들이되 지문을 TOFU 로 고정한다. 지문 불일치면 본문을 쓰기 전에 끊는다."""
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    conn = http.client.HTTPSConnection(host, port, timeout=timeout, context=ctx)
    sent = False
    try:
        try:
            conn.connect()
        except (OSError, ssl.SSLError, socket.timeout) as exc:
            raise TransportError('connect failed: %s' % type(exc).__name__,
                                 refused=isinstance(exc, ConnectionRefusedError))
        der = conn.sock.getpeercert(binary_form=True)
        peer = hashlib.sha256(der).hexdigest() if der else ''
        if tls_pin and peer != tls_pin:
            raise CertMismatch(peer)
        try:
            sent = True
            conn.request('POST', path, body=body,
                         headers={'Content-Type': 'application/json'})
            resp = conn.getresponse()
            data = resp.read()
        except (OSError, http.client.HTTPException, ssl.SSLError) as exc:
            raise TransportError('request failed: %s' % type(exc).__name__, sent=sent)
        return resp.status, data, peer
    finally:
        conn.close()


class OpenStream:
    """subscribeMsg 같은 오래 열려 있는 응답. `body` 가 있으면 스트림이 아니라 일반 JSON 응답이다."""

    def __init__(self, status, ctype, resp, conn, peer, body=None, sock=None):
        self.status, self.ctype, self.resp, self.conn, self.peer, self.body = \
            status, ctype, resp, conn, peer, body
        self.sock = sock       # 응답이 연결을 넘겨받으면 conn.sock 은 None 이 된다

    @property
    def is_stream(self):
        return self.body is None

    def close(self):
        for closer in (getattr(self.resp, 'close', None), getattr(self.sock, 'close', None),
                       self.conn.close):
            try:
                if closer:
                    closer()
            except Exception:  # noqa: BLE001
                pass


def https_open_stream(host, port, path, body: bytes, tls_pin=None, timeout=5.0, read_timeout=70.0):
    """https_post 와 같되 응답 본문을 다 읽지 않고 열어 둔다(multipart/mixed 일 때).
    읽기 제한 시간 `read_timeout` 이 곧 하트비트 감시다(설계 §6.2: 70초)."""
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    conn = http.client.HTTPSConnection(host, port, timeout=timeout, context=ctx)
    try:
        try:
            conn.connect()
        except (OSError, ssl.SSLError, socket.timeout) as exc:
            raise TransportError('connect failed: %s' % type(exc).__name__,
                                 refused=isinstance(exc, ConnectionRefusedError))
        der = conn.sock.getpeercert(binary_form=True)
        peer = hashlib.sha256(der).hexdigest() if der else ''
        if tls_pin and peer != tls_pin:
            raise CertMismatch(peer)
        try:
            conn.request('POST', path, body=body, headers={'Content-Type': 'application/json'})
            sock = conn.sock
            resp = conn.getresponse()
            ctype = resp.getheader('Content-Type') or ''
            if 'multipart' in ctype.lower():
                sock.settimeout(read_timeout)
                return OpenStream(resp.status, ctype, resp, conn, peer, sock=sock)
            data = resp.read()
        except (OSError, http.client.HTTPException, ssl.SSLError) as exc:
            raise TransportError('request failed: %s' % type(exc).__name__, sent=True)
        conn.close()
        return OpenStream(resp.status, ctype, None, conn, peer, body=data)
    except BaseException:
        conn.close()
        raise


def peer_pin(host, port, timeout=5.0):
    """TLS 핸드셰이크만 해서 인증서 지문을 얻는다. 본문도 자격 증명도 보내지 않는다. 실패하면 None."""
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    conn = http.client.HTTPSConnection(host, port, timeout=timeout, context=ctx)
    try:
        conn.connect()
        der = conn.sock.getpeercert(binary_form=True)
        return hashlib.sha256(der).hexdigest() if der else None
    except (OSError, ssl.SSLError, socket.timeout):
        return None
    finally:
        conn.close()


def digest_response(username, password, realm, nonce, method, uri) -> str:
    """조사 §2.2: A1=SHA256(user:realm:pw), A2=SHA256(method:uri), response=SHA256(A1:nonce:A2)."""
    a1 = hashlib.sha256(('%s:%s:%s' % (username, realm, password)).encode()).hexdigest()
    a2 = hashlib.sha256(('%s:%s' % (method, uri)).encode()).hexdigest()
    return hashlib.sha256(('%s:%s:%s' % (a1, nonce, a2)).encode()).hexdigest()


def _code_of(obj):
    """error_code 를 읽는다(`errCode` 도 허용). 없으면 None."""
    if not isinstance(obj, dict):
        return None
    for k in ('error_code', 'errCode'):
        if k in obj:
            v = obj[k]
            if isinstance(v, bool):
                return None
            if isinstance(v, int):
                return v
            if isinstance(v, str) and v.lstrip('-').isdigit():
                return int(v)
            return None
    return None


def _result_of(obj):
    for k in ('result', 'data'):
        if k in obj:
            return obj[k]
    return None


def _find_challenge(obj):
    """챌린지(authenticate{realm,nonce,…})를 최상위·result·data 어디에 있든 찾는다. 응답 위치가 [미확인]이다."""
    for holder in (obj, _result_of(obj)):
        if isinstance(holder, dict):
            a = holder.get('authenticate')
            if isinstance(a, dict):
                return a
            if 'nonce' in holder and 'realm' in holder:
                return holder
    return {}


class VigiOpenApi:
    """카메라 하나당 클라이언트 하나. 호출은 락으로 한 줄에 세운다(동시 제어 호출 1개)."""

    def __init__(self, host, credential: Credential, *, camera_id, guard: AuthGuard,
                 fp_key, port=DEFAULT_PORT, tls_pin=None, timeout=5.0,
                 transport=None, monotonic=time.monotonic, stok_refresh_s=STOK_REFRESH_S,
                 stream_transport=None):
        self.host = host
        self.port = port
        self.camera_id = camera_id
        self.guard = guard
        self.tls_pin = tls_pin
        self.observed_pin = None
        self.timeout = timeout
        self._cred = credential
        self._fp = make_fp(credential.username, credential.password, fp_key)
        self._transport = transport or https_post
        self._stream_transport = stream_transport or https_open_stream
        self._mono = monotonic
        self._refresh_s = stok_refresh_s
        self._stok = None
        self._stok_at = None
        self._ever_authed = False
        self._lock = threading.RLock()

    def __repr__(self):
        return 'VigiOpenApi(host=%r, camera_id=%r)' % (self.host, self.camera_id)

    # -- 전송 ---------------------------------------------------------------
    def _post(self, path, payload):
        """(parsed_json|None, status, sent) 또는 예외(TransportError/CertMismatch)."""
        body = json.dumps(payload).encode()
        status, raw, peer = self._transport(self.host, self.port, path, body,
                                            self.tls_pin, self.timeout)
        self.observed_pin = peer or self.observed_pin
        if not raw:
            return None, status
        try:
            obj = json.loads(raw.decode('utf-8', 'replace'))
        except ValueError:
            return None, status
        return (obj if isinstance(obj, dict) else None), status

    def _cert_changed(self, observed):
        self.observed_pin = observed
        self.guard.latch_any_interface(self.camera_id, 'cert_changed', 'openapi')
        self._drop_session()
        return CamResult.failed('certificate fingerprint changed; credentials were not sent',
                                ErrorClass.CERT_CHANGED)

    def _drop_session(self):
        self._stok = None
        self._stok_at = None

    # -- 인증 ---------------------------------------------------------------
    def connect(self, _reauth=False) -> CamResult:
        """doAuth 2단계. 성공하면 stok 을 보관한다(밖으로 내보내지 않는다)."""
        with self._lock:
            return self._authenticate(reauth=_reauth)

    def ensure_session(self) -> CamResult:
        """이미 stok 이 있으면 재사용하고 없을 때만 인증한다. 카메라의 클라이언트 수 제한(-10021)을
        지키려고, "연결 확인"이 누를 때마다 세션을 새로 여는 일을 없앤다."""
        with self._lock:
            if self._stok is not None and (self._mono() - self._stok_at) < self._refresh_s:
                return CamResult.ok({})
            return self._authenticate(reauth=self._ever_authed)

    def _authenticate(self, reauth) -> CamResult:
        permit = self.guard.begin(self.camera_id, self._fp, 'openapi', reauth=reauth)
        if not isinstance(permit, Permit):
            return CamResult.refused(permit.message)
        # 1단계: params null — 자격 증명 없음
        try:
            obj, _ = self._post('/', {'method': 'doAuth', 'params': None})
        except CertMismatch as cm:
            self.guard.report_failure(permit, ErrorClass.CERT_CHANGED)
            return self._cert_changed(cm.observed)
        except TransportError as exc:
            self.guard.report_failure(permit, ErrorClass.NETWORK)
            if exc.refused:
                # 20443 이 닫혀 있다: OpenAPI 가 꺼졌다. 래치가 아니다 — RTSP 는 계속 쓸 수 있다(§6.1-5)
                self.guard.mark_openapi_off(self.camera_id)
            return CamResult.failed(str(exc), ErrorClass.NETWORK)
        if obj is None:
            self.guard.report_failure(permit, ErrorClass.PROTOCOL)
            return CamResult.unverified('empty or malformed challenge response')
        code = _code_of(obj)
        if code == E.ERR_LOCKED:
            self.guard.report_failure(permit, ErrorClass.LOCKED, code)
            return CamResult.failed('camera has locked login', ErrorClass.LOCKED, code)
        if code == E.ERR_CLIENT_LIMIT:
            self.guard.report_failure(permit, ErrorClass.CLIENT_LIMIT, code)
            return CamResult.failed('too many clients on camera', ErrorClass.CLIENT_LIMIT, code)
        auth = _find_challenge(obj)
        realm, nonce = auth.get('realm'), auth.get('nonce')
        # 1단계 정상 응답은 -10020 + authenticate{realm,nonce,...} 다
        if not (isinstance(auth, dict) and realm and nonce):
            self.guard.report_failure(permit, ErrorClass.PROTOCOL)
            return CamResult.unverified('challenge missing realm/nonce')
        algo = str(auth.get('algorithm', 'SHA-256')).upper().replace('_', '-')
        if algo not in ('SHA-256', 'SHA256'):
            # 문서는 SHA-256 계산만 정의한다. 모르는 알고리즘으로는 자격 증명을 보내지 않는다
            self.guard.report_failure(permit, ErrorClass.PROTOCOL)
            return CamResult.unsupported('auth algorithm %s' % algo[:16])
        response = digest_response(self._cred.username, self._cred.password, realm, nonce,
                                   auth.get('method', 'POST'), auth.get('uri', '/'))
        # 2단계: 여기서부터 자격 증명이 카메라에 간다 = 시도 1회
        try:
            obj, _ = self._post('/', {'method': 'doAuth',
                                      'params': {'nonce': nonce, 'response': response}})
        except CertMismatch as cm:
            self.guard.report_failure(permit, ErrorClass.CERT_CHANGED)
            return self._cert_changed(cm.observed)
        except TransportError as exc:
            if exc.sent:
                # 본문이 나갔는데 결과를 모른다. 같은 자격 증명을 다시 보내지 않기 위해 래치한다
                self.guard.report_failure(permit, ErrorClass.AUTH_FAILED)
                return CamResult.failed(
                    'no response to authentication; not retrying automatically',
                    ErrorClass.NETWORK)
            self.guard.report_failure(permit, ErrorClass.NETWORK)
            return CamResult.failed(str(exc), ErrorClass.NETWORK)
        code = _code_of(obj)
        res = _result_of(obj) if obj else None
        stok = res.get('stok') if isinstance(res, dict) else None
        if code == 0 and stok:
            self._stok, self._stok_at = stok, self._mono()
            self._ever_authed = True
            self.guard.report_success(permit)
            logger.debug('vigi auth ok camera=%s stok=%s', self.camera_id, short_token(stok))
            return CamResult.ok({'authenticated': True})
        return self._auth_failure(permit, code, obj)

    def _auth_failure(self, permit, code, obj):
        cls = E.classify(code) if code is not None else ErrorClass.PROTOCOL
        if cls is ErrorClass.CLIENT_LIMIT:
            self.guard.report_failure(permit, cls, code)
            return CamResult.failed('too many clients on camera', cls, code)
        if cls is ErrorClass.LOCKED:
            self.guard.report_failure(permit, cls, code)
            return CamResult.failed('camera has locked login', cls, code)
        # -10020, 모르는 코드, 빈/깨진 응답 — 결과를 증명할 수 없으면 안전하게 래치한다
        self.guard.report_failure(permit, ErrorClass.AUTH_FAILED, code)
        if cls is ErrorClass.AUTH_FAILED:
            return CamResult.failed('authentication failed', cls, code)
        return CamResult.failed('authentication response not understood; latched',
                                ErrorClass.AUTH_FAILED, code)

    # -- 호출 ---------------------------------------------------------------
    def call(self, method, params=None) -> CamResult:
        """메서드 하나를 호출한다. 판정은 JSON 의 error_code 로 한다(HTTP 200 은 근거가 아니다)."""
        with self._lock:
            if self._stok is None or (self._mono() - self._stok_at) >= self._refresh_s:
                r = self._authenticate(reauth=self._ever_authed)
                if not r.accepted:
                    return r
            res = self._call_once(method, params)
            if res.error_class is ErrorClass.SESSION_INVALID:
                # 성공한 자격 증명으로 딱 1회 재인증하고 딱 1회 다시 보낸다
                self._drop_session()
                r = self._authenticate(reauth=True)
                if not r.accepted:
                    return r
                res = self._call_once(method, params)
                if res.error_class is ErrorClass.SESSION_INVALID:
                    self._drop_session()
            return res

    def _call_once(self, method, params):
        try:
            obj, _status = self._post('/stok=%s' % self._stok,
                                      {'method': method, 'params': params})
        except CertMismatch as cm:
            return self._cert_changed(cm.observed)
        except TransportError as exc:
            return CamResult.failed(str(exc), ErrorClass.NETWORK)
        if obj is None:
            return CamResult.unverified('empty or malformed response to %s' % method)
        code = _code_of(obj)
        if code is None:
            return CamResult.unverified('response to %s has no error_code' % method)
        if code == 0:
            return CamResult.ok(_result_of(obj), code)
        cls = E.classify(code)
        if cls in (ErrorClass.AUTH_FAILED, ErrorClass.LOCKED):
            # 세션 중 인증 계열 오류 — 안전하게 래치한다
            state = 'locked' if cls is ErrorClass.LOCKED else 'failed'
            self.guard.latch_any_interface(self.camera_id, state, 'openapi', code)
            self._drop_session()
        return CamResult.failed('%s returned error %d' % (method, code), cls, code)

    def open_stream(self, method, params=None, read_timeout=70.0):
        """오래 열려 있는 응답(subscribeMsg)을 연다. 반환 (CamResult, OpenStream|None).
        인증·재인증 규칙은 call() 과 같다(세션 무효 → 성공한 자격으로 1회). 락은 연결을 여는 동안만 잡는다."""
        with self._lock:
            if self._stok is None or (self._mono() - self._stok_at) >= self._refresh_s:
                r = self._authenticate(reauth=self._ever_authed)
                if not r.accepted:
                    return r, None
            for attempt in (0, 1):
                body = json.dumps({'method': method, 'params': params}).encode()
                try:
                    st = self._stream_transport(self.host, self.port, '/stok=%s' % self._stok, body,
                                                self.tls_pin, self.timeout, read_timeout)
                except CertMismatch as cm:
                    return self._cert_changed(cm.observed), None
                except TransportError as exc:
                    return CamResult.failed(str(exc), ErrorClass.NETWORK), None
                self.observed_pin = st.peer or self.observed_pin
                if st.is_stream:
                    return CamResult.ok({}), st
                try:
                    obj = json.loads((st.body or b'').decode('utf-8', 'replace'))
                except ValueError:
                    obj = None
                code = _code_of(obj) if isinstance(obj, dict) else None
                if code is None:
                    return CamResult.unverified('malformed response to %s' % method), None
                cls = E.classify(code)
                if cls is ErrorClass.SESSION_INVALID and attempt == 0:
                    self._drop_session()
                    r = self._authenticate(reauth=True)
                    if not r.accepted:
                        return r, None
                    continue
                if cls in (ErrorClass.AUTH_FAILED, ErrorClass.LOCKED):
                    state = 'locked' if cls is ErrorClass.LOCKED else 'failed'
                    self.guard.latch_any_interface(self.camera_id, state, 'openapi', code)
                    self._drop_session()
                if cls is ErrorClass.SESSION_INVALID:
                    self._drop_session()
                return CamResult.failed('%s returned error %d' % (method, code), cls, code), None
            return CamResult.unverified('no stream'), None

    def close(self):
        with self._lock:
            self._drop_session()
