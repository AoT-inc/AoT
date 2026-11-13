# coding=utf-8
"""ONVIF SOAP 클라이언트 — WS-UsernameToken(PasswordDigest) / HTTP Digest, 표준 라이브러리만.

WSDL 을 내려받지 않는다(onvif-zeep 은 WSDL 적재가 필요해 폐쇄망·모의 서버와 맞지 않는다).
Profile S 에 쓰는 몇 개 작업만 봉투를 직접 만든다. 필요해지면 O3~ 에서 작업을 더한다.

인증 보호가 최우선 계약이다 (vigi openapi.py 와 같다):
- 자격 증명이 카메라로 나가는 모든 요청 앞에는 `AuthGuard.begin` 이 선다. 거부되면 **아무것도 보내지 않는다.**
- 자격 증명 없는 탐지(GetSystemDateAndTime·인증 방식 판별)는 시도로 세지 않는다.
- 첫 자격 증명 시도 1회가 인증 실패(HTTP 401·NotAuthorized·모르는 응답)면 즉시 래치한다. 재시도 루프 없음.
- 인증 뒤 호출(`call`)은 verified_fp 와 같은 자격 증명만 쓴다. 인증 계열 오류면 래치하고 다시 보내지 않는다.
  유일한 예외: HTTP Digest 의 `stale=true`(nonce 만료 — 자격 증명 탓이 아니다) 는 새 챌린지로 1회.
- 요청은 설정된 host 로만 간다. 카메라가 알려준 XAddr 의 host 는 쓰지 않고 경로만 쓴다(자격 증명이 다른 곳으로 가지 않게).
- 비밀번호·digest·nonce 는 로그·예외·CamResult 에 남기지 않는다.
"""
import base64
import hashlib
import http.client
import logging
import re
import secrets
import socket
import threading
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from xml.sax.saxutils import escape

from aot.camera_drivers.auth_guard import AuthGuard, Permit
from aot.camera_drivers.auth_guard import credential_fp as make_fp
from aot.camera_drivers.driver import CamResult, Credential, ErrorClass
from aot.camera_drivers.onvif import errors as E
from aot.utils.timekit import utc_now

logger = logging.getLogger(__name__)

IFACE = 'onvif'
DEFAULT_PORT = 80
MAX_BODY = 2 * 1024 * 1024

NS_SOAP = 'http://www.w3.org/2003/05/soap-envelope'
NS_DEVICE = 'http://www.onvif.org/ver10/device/wsdl'
NS_MEDIA = 'http://www.onvif.org/ver10/media/wsdl'
NS_PTZ = 'http://www.onvif.org/ver20/ptz/wsdl'
NS_IMAGING = 'http://www.onvif.org/ver20/imaging/wsdl'
NS_EVENTS = 'http://www.onvif.org/ver10/events/wsdl'
NS_SCHEMA = 'http://www.onvif.org/ver10/schema'
NS_WSSE = 'http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-secext-1.0.xsd'
NS_WSU = 'http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-utility-1.0.xsd'
_PW_DIGEST = 'http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-username-token-profile-1.0#PasswordDigest'
_B64 = 'http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-soap-message-security-1.0#Base64Binary'

# 서비스 키 → (네임스페이스, 기본 경로). GetServices 가 경로를 덮어쓴다.
SERVICES = {
    'device': (NS_DEVICE, '/onvif/device_service'),
    'media': (NS_MEDIA, '/onvif/media_service'),
    'ptz': (NS_PTZ, '/onvif/ptz_service'),
    'imaging': (NS_IMAGING, '/onvif/imaging_service'),
    'events': (NS_EVENTS, '/onvif/events_service'),
}
NS_TO_SERVICE = {ns: k for k, (ns, _p) in SERVICES.items()}

SCHEME_WSSE = 'wsse'
SCHEME_DIGEST = 'digest'


class TransportError(Exception):
    """연결·전송 오류. `sent` 가 True 면 요청 본문이 이미 카메라로 나갔다."""

    def __init__(self, message, sent=False, refused=False):
        super().__init__(message)
        self.sent = sent
        self.refused = refused


def http_post(host, port, path, body: bytes, headers, timeout=5.0):
    """평문 HTTP POST. 반환 (status, {소문자 헤더: 값}, body). 응답은 MAX_BODY 로 자른다."""
    conn = http.client.HTTPConnection(host, port, timeout=timeout)
    sent = False
    try:
        try:
            conn.connect()
        except (OSError, socket.timeout) as exc:
            raise TransportError('connect failed: %s' % type(exc).__name__,
                                 refused=isinstance(exc, ConnectionRefusedError))
        try:
            sent = True
            conn.request('POST', path, body=body, headers=headers)
            resp = conn.getresponse()
            data = resp.read(MAX_BODY + 1)[:MAX_BODY]
        except (OSError, http.client.HTTPException) as exc:
            raise TransportError('request failed: %s' % type(exc).__name__, sent=sent)
        return resp.status, {k.lower(): v for k, v in resp.getheaders()}, data
    finally:
        conn.close()


# -- XML 도우미 --------------------------------------------------------------
def local(tag):
    return tag.rsplit('}', 1)[-1] if isinstance(tag, str) else ''


def parse_xml(raw: bytes):
    """안전하게 파싱한다. DTD·엔티티 선언이 있으면 거부한다(billion-laughs). 실패하면 None."""
    if not raw or b'<!DOCTYPE' in raw.upper() or b'<!ENTITY' in raw.upper():
        return None
    try:
        return ET.fromstring(raw)
    except ET.ParseError:
        return None


def descendants(el, name):
    return [e for e in el.iter() if local(e.tag) == name]


def first(el, name):
    for e in el.iter():
        if local(e.tag) == name:
            return e
    return None


def text_of(el, name, default=''):
    e = first(el, name) if el is not None else None
    return (e.text or '').strip() if e is not None and e.text else default


def envelope(body_xml, header_xml=''):
    return ('<?xml version="1.0" encoding="UTF-8"?>'
            '<s:Envelope xmlns:s="%s">%s<s:Body>%s</s:Body></s:Envelope>'
            % (NS_SOAP, ('<s:Header>%s</s:Header>' % header_xml) if header_xml else '', body_xml)
            ).encode('utf-8')


def operation(ns, op, inner=''):
    return '<x:%s xmlns:x="%s">%s</x:%s>' % (op, ns, inner, op)


def q(text):
    """요청 본문에 넣는 값을 이스케이프한다."""
    return escape(str(text))


# -- 인증 헤더 ---------------------------------------------------------------
def wsse_header(username, password, nonce_raw: bytes, created: str) -> str:
    digest = base64.b64encode(hashlib.sha1(nonce_raw + created.encode() + password.encode()).digest())
    return ('<wsse:Security xmlns:wsse="%s" xmlns:wsu="%s"><wsse:UsernameToken>'
            '<wsse:Username>%s</wsse:Username><wsse:Password Type="%s">%s</wsse:Password>'
            '<wsse:Nonce EncodingType="%s">%s</wsse:Nonce><wsu:Created>%s</wsu:Created>'
            '</wsse:UsernameToken></wsse:Security>'
            % (NS_WSSE, NS_WSU, escape(username), _PW_DIGEST, digest.decode(), _B64,
               base64.b64encode(nonce_raw).decode(), created))


def parse_digest_challenge(value):
    """`WWW-Authenticate: Digest realm="x", nonce="y", qop="auth", stale=true` → dict. Digest 가 아니면 None."""
    if not value or not value.strip().lower().startswith('digest'):
        return None
    params = dict(re.findall(r'(\w+)="([^"]*)"', value))
    for k, v in re.findall(r'(\w+)=([^",\s]+)', value):
        params.setdefault(k, v)
    if 'nonce' not in params or 'realm' not in params:
        return None
    return {k.lower(): v for k, v in params.items()}


def digest_authorization(username, password, chal, method, uri, nc, cnonce) -> str:
    """RFC 2617 MD5, qop=auth (없으면 RFC 2069 형)."""
    ha1 = hashlib.md5(('%s:%s:%s' % (username, chal['realm'], password)).encode()).hexdigest()
    ha2 = hashlib.md5(('%s:%s' % (method, uri)).encode()).hexdigest()
    qop = 'auth' if 'auth' in [p.strip() for p in chal.get('qop', '').split(',')] else ''
    if qop:
        resp = hashlib.md5(('%s:%s:%08x:%s:%s:%s' % (ha1, chal['nonce'], nc, cnonce, qop, ha2))
                           .encode()).hexdigest()
    else:
        resp = hashlib.md5(('%s:%s:%s' % (ha1, chal['nonce'], ha2)).encode()).hexdigest()
    out = ('Digest username="%s", realm="%s", nonce="%s", uri="%s", response="%s", algorithm=MD5'
           % (username.replace('"', ''), chal['realm'], chal['nonce'], uri, resp))
    if qop:
        out += ', qop=auth, nc=%08x, cnonce="%s"' % (nc, cnonce)
    if chal.get('opaque'):
        out += ', opaque="%s"' % chal['opaque']
    return out


class Reply:
    """HTTP 응답 하나를 풀어 둔 값."""

    def __init__(self, status, headers, raw):
        self.status, self.headers, self.raw = status, headers, raw
        self.root = parse_xml(raw)
        self.body = first(self.root, 'Body') if self.root is not None else None
        fault = first(self.body, 'Fault') if self.body is not None else None
        self.fault = fault
        self.subcodes, self.reason = [], ''
        if fault is not None:
            # SOAP 1.2: Code/Subcode/Value (중첩), Reason/Text.  SOAP 1.1: faultcode/faultstring
            for e in fault.iter():
                if local(e.tag) in ('Value', 'faultcode') and e.text:
                    self.subcodes.append(e.text.strip())
            self.reason = ' '.join((e.text or '').strip() for e in fault.iter()
                                   if local(e.tag) in ('Text', 'faultstring'))

    @property
    def ok_body(self):
        """성공 응답이면 Body 의 첫 자식 요소, 아니면 None."""
        if self.status == 200 and self.body is not None and self.fault is None:
            kids = list(self.body)
            return kids[0] if kids else None
        return None

    @property
    def challenge(self):
        return parse_digest_challenge(self.headers.get('www-authenticate'))


class OnvifSoap:
    """카메라 하나당 클라이언트 하나. 호출은 락으로 한 줄에 세운다."""

    def __init__(self, host, credential: Credential, *, camera_id, guard: AuthGuard, fp_key,
                 port=DEFAULT_PORT, timeout=5.0, transport=None, clock=utc_now):
        self.host = host
        self.port = int(port)
        self.camera_id = camera_id
        self.guard = guard
        self.timeout = timeout
        self._cred = credential
        self._fp = make_fp(credential.username, credential.password, fp_key)
        self._transport = transport or http_post
        self._clock = clock
        self._lock = threading.RLock()
        self.paths = {k: p for k, (_ns, p) in SERVICES.items()}
        self._scheme = None
        self._skew = 0.0          # 카메라 UTC − 우리 UTC (초). WSSE Created 보정용
        self._chal = None         # HTTP Digest 챌린지
        self._nc = 0
        self.last_reply_status = None

    def __repr__(self):
        return 'OnvifSoap(host=%r, port=%r, camera_id=%r)' % (self.host, self.port, self.camera_id)

    @property
    def fingerprint(self):
        return self._fp

    def set_service_path(self, service, xaddr):
        """GetServices 가 준 XAddr 에서 **경로만** 취한다. host·port 는 설정값을 유지한다."""
        if service not in SERVICES or not isinstance(xaddr, str):
            return
        m = re.match(r'^[a-z]+://[^/]+(/[^?#\s]*)?', xaddr.strip(), re.I)
        path = (m.group(1) if m else None) or None
        if path and re.fullmatch(r'/[A-Za-z0-9_./~-]*', path) and '..' not in path.split('/') \
                and '//' not in path:
            self.paths[service] = path

    # -- 전송 ---------------------------------------------------------------
    def _send(self, path, body_xml, header_xml='', extra_headers=None):
        env = envelope(body_xml, header_xml)
        headers = {'Content-Type': 'application/soap+xml; charset=utf-8',
                   'Content-Length': str(len(env))}
        headers.update(extra_headers or {})
        status, hdrs, raw = self._transport(self.host, self.port, path, env, headers, self.timeout)
        self.last_reply_status = status
        return Reply(status, hdrs, raw)

    def _created(self):
        """WSSE Created: 우리 시계 + 카메라와의 차이(UTC)."""
        t = self._clock().timestamp() + self._skew
        return datetime.fromtimestamp(t, tz=timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')

    def _authed_send(self, service, op, inner):
        """자격 증명을 실어 보낸다. 이 호출이 곧 '자격 증명이 카메라로 나가는 것'이다."""
        ns, _p = SERVICES[service]
        path = self.paths[service]
        body = operation(ns, op, inner)
        if self._scheme == SCHEME_DIGEST and self._chal:
            self._nc += 1
            auth = digest_authorization(self._cred.username, self._cred.password, self._chal,
                                        'POST', path, self._nc, secrets.token_hex(8))
            return self._send(path, body, extra_headers={'Authorization': auth})
        hdr = wsse_header(self._cred.username, self._cred.password, secrets.token_bytes(16),
                          self._created())
        return self._send(path, body, header_xml=hdr)

    def _anon(self, service, op, inner=''):
        ns, _p = SERVICES[service]
        return self._send(self.paths[service], operation(ns, op, inner))

    # -- 자격 증명 없는 탐지 -----------------------------------------------------
    def _probe(self):
        """GetSystemDateAndTime(무인증) 으로 시계 차이를, GetDeviceInformation(무인증) 으로 인증 방식을 안다.
        자격 증명은 나가지 않는다. 전송 오류는 TransportError 로 올린다."""
        r = self._anon('device', 'GetSystemDateAndTime')
        body = r.ok_body
        if body is not None:
            self._learn_skew(body)
        chal = r.challenge if r.status == 401 else None
        if chal is None:
            r2 = self._anon('device', 'GetDeviceInformation')
            chal = r2.challenge if r2.status == 401 else None
        if chal is not None:
            self._scheme, self._chal, self._nc = SCHEME_DIGEST, chal, 0
        else:
            self._scheme, self._chal = SCHEME_WSSE, None

    def _learn_skew(self, body):
        u = first(body, 'UTCDateTime')
        if u is None:
            return
        try:
            dt = datetime(int(text_of(u, 'Year')), int(text_of(u, 'Month')), int(text_of(u, 'Day')),
                          int(text_of(u, 'Hour')), int(text_of(u, 'Minute')), int(text_of(u, 'Second')),
                          tzinfo=timezone.utc)
        except ValueError:
            return
        self._skew = dt.timestamp() - self._clock().timestamp()

    # -- 결과 판정 ----------------------------------------------------------
    def _judge(self, r: Reply, what):
        """응답 → CamResult. 인증 계열이면 error_class 로 알린다(래치는 호출자가 한다)."""
        if r.status == 401:
            return CamResult.failed('%s: HTTP 401' % what, ErrorClass.AUTH_FAILED, 401, IFACE)
        if r.fault is not None:
            cls = E.classify_fault(r.subcodes, r.reason)
            sub = E.safe_token(r.subcodes[-1]) if r.subcodes else ''
            if cls is ErrorClass.UNSUPPORTED:
                return CamResult.unsupported('%s: %s' % (what, sub))
            return CamResult.failed('%s: fault %s' % (what, sub), cls, r.status, IFACE)
        if r.status in (429, 503):
            return CamResult.failed('%s: HTTP %d' % (what, r.status), ErrorClass.CLIENT_LIMIT,
                                    r.status, IFACE)
        if r.ok_body is not None:
            return CamResult.ok(r.ok_body, 0, IFACE)
        if r.status and r.status >= 400:
            return CamResult.failed('%s: HTTP %d' % (what, r.status), ErrorClass.DEVICE, r.status, IFACE)
        return CamResult.unverified('%s: empty or malformed response' % what, IFACE)

    # -- 인증 ---------------------------------------------------------------
    def connect(self, reauth=False) -> CamResult:
        """연결 확인 = 검증 안 된 자격 증명의 단 한 번의 시도. 사용자가 누를 때만 호출한다."""
        with self._lock:
            return self._authenticate(reauth)

    def _authenticate(self, reauth) -> CamResult:
        permit = self.guard.begin(self.camera_id, self._fp, IFACE, reauth=reauth)
        if not isinstance(permit, Permit):
            return CamResult.refused(permit.message, interface=IFACE)
        try:
            self._probe()
        except TransportError as exc:
            self.guard.report_failure(permit, ErrorClass.NETWORK)
            return CamResult.failed(str(exc), ErrorClass.NETWORK, interface=IFACE)
        # 여기서부터 자격 증명이 카메라로 간다 = 시도 1회
        try:
            r = self._authed_send('device', 'GetDeviceInformation', '')
        except TransportError as exc:
            if exc.sent:
                # 본문이 나갔는데 결과를 모른다. 같은 자격 증명을 다시 보내지 않기 위해 래치한다
                self.guard.report_failure(permit, ErrorClass.AUTH_FAILED)
                return CamResult.failed('no response to authentication; not retrying automatically',
                                        ErrorClass.NETWORK, interface=IFACE)
            self.guard.report_failure(permit, ErrorClass.NETWORK)
            return CamResult.failed(str(exc), ErrorClass.NETWORK, interface=IFACE)
        res = self._judge(r, 'authenticate')
        if res.accepted:
            self.guard.report_success(permit)
            return CamResult.ok({'authenticated': True}, 0, IFACE)
        cls = res.error_class
        if cls in (ErrorClass.CLIENT_LIMIT, ErrorClass.LOCKED):
            self.guard.report_failure(permit, cls, res.code)
            return res
        # 인증 실패, 모르는 Fault, 빈/깨진 응답 — 결과를 증명할 수 없으면 안전하게 래치한다
        self.guard.report_failure(permit, ErrorClass.AUTH_FAILED, res.code)
        if cls is ErrorClass.AUTH_FAILED:
            return CamResult.failed('authentication failed', cls, res.code, IFACE)
        return CamResult.failed('authentication response not understood; latched',
                                ErrorClass.AUTH_FAILED, res.code, IFACE)

    # -- 호출 ---------------------------------------------------------------
    def call(self, service, op, inner='') -> CamResult:
        """검증된 자격 증명으로 작업 하나를 호출한다. 성공하면 data 는 응답 본문 요소(ET.Element)."""
        with self._lock:
            permit = self.guard.begin(self.camera_id, self._fp, IFACE, reauth=True)
            if not isinstance(permit, Permit):
                return CamResult.refused(permit.message, interface=IFACE)
            what = '%s.%s' % (service, op)
            try:
                if self._scheme is None:
                    self._probe()
                r = self._authed_send(service, op, inner)
                chal = r.challenge
                if r.status == 401 and self._scheme == SCHEME_DIGEST and chal \
                        and chal.get('stale', '').lower() == 'true':
                    # nonce 만료는 자격 증명 탓이 아니다. 새 챌린지로 1회만
                    self._chal, self._nc = chal, 0
                    r = self._authed_send(service, op, inner)
            except TransportError as exc:
                return CamResult.failed(str(exc), ErrorClass.NETWORK, interface=IFACE)
            res = self._judge(r, what)
            if res.error_class in (ErrorClass.AUTH_FAILED, ErrorClass.LOCKED):
                state = 'locked' if res.error_class is ErrorClass.LOCKED else 'failed'
                self.guard.latch_any_interface(self.camera_id, state, IFACE, res.code)
                self._scheme = None
            return res

    def close(self):
        with self._lock:
            self._scheme, self._chal = None, None
