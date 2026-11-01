# coding=utf-8
"""AI 카드 URL 가져오기 — 공개 https 주소의 파일을 서버가 받아 오는 길 (2026-10-20, P4).

screen_action(action='post', attach={url}) 와 본문 `![alt](https://…)` 승격이 쓴다. 받은 바이트는
기존 검사 경로(ai_card_files.inspect_bytes·store) 를 그대로 지난다. 이 모듈은 **SSRF 방어**가
전부다 — 계약 p4_contract_20261020.md ②·③·⑤.

방어 순서(한 단계도 빼지 않는다):
  1 문자열 → 2 urlsplit → 3 호스트 모양 → 4 DNS(2초, 실행기) → 5 IP 판정(해석된 **모든** 주소) →
  6 검증한 IP 로 직접 연결(SNI·Host·인증서는 원래 호스트) → 7 고정 헤더 → 7b 프록시 환경변수
  무시 → 8 리다이렉트 수동 3회(홉마다 1~7 다시) → 9 응답(200·identity·스트리밍 상한·총 12초) →
  10 이름 → 11 검사(슬롯 반납 뒤).

설계 메모:
  - 연결은 urllib3 `HTTPSConnectionPool(host=<검증한 IP>)` 다. 다시 해석하지 않으므로 DNS
    리바인딩이 막힌다. `requests`·`httpx` 는 환경변수(HTTP(S)_PROXY·ALL_PROXY)와 쿠키·인증을
    따로 해석하므로 **쓰지 않는다**(테스트가 이 파일의 import 를 고정한다).
  - 총 시간 12초는 소켓마다 감시 타이머(watchdog)로 강제한다. 읽기 5초 제한은 수신 한 번마다라
    1바이트/초 전송이나 헤더 찔끔 보내기로는 끝없이 늘어난다.
  - 오류 문구는 차단 사유·호스트 종류를 구분하지 않는다(내부망 존재 탐색 오라클 방지). 구분은
    감사 detail 의 code 에만 남긴다.
  - `_resolver`·`_pool_factory` 는 테스트 전용 키워드다. ai_card_files.prepare 는 `fetch(url,
    user, limit)` 만 부르므로 도구 인자로는 닿지 않는다.
"""
import collections
import concurrent.futures
import contextlib
import ipaddress
import logging
import re
import socket
import threading
import time
from urllib.parse import unquote, urljoin, urlsplit

from aot.utils.ai_card_files import ALLOWED, MAX_FILE_BYTES, FileError

logger = logging.getLogger(__name__)

MAX_URL = 2048
MAX_REDIRECTS = 3
DNS_S = 2
CONNECT_S = 3
READ_S = 5
TOTAL_S = 12
CHUNK = 64 * 1024
FETCH_SLOTS = 2
PER_USER_CONCURRENT = 1
PER_HOUR = 30
PER_DAY = 100
UA = 'AoT-AI-Card/1.0'
MAX_ADDRS = 2

MSG_SHAPE = "attach url must be a public https:// address with a host name."
MSG_FAILED = ("The file at that URL could not be fetched. Use a public https link to the "
              "file itself, or send b64.")
MSG_BUSY = "The AoT server is busy fetching other files. Try again shortly."
MSG_HOUR = "URL fetch limit reached (%d per hour). Try again later." % PER_HOUR
MSG_DAY = "URL fetch limit reached (%d per day). Try again later." % PER_DAY

_REDIRECT_STATUS = frozenset({301, 302, 303, 307, 308})


class FetchError(FileError):
    """AI 에게 그대로 보내도 안전한 문구(message)와 감사 전용 code 를 함께 든다."""

    def __init__(self, message, code, http=None):
        super().__init__(message)
        self.code = code
        self.http = http                                # 상대 서버가 준 HTTP 상태(감사 진단용, AI 에게는 안 보임)


def _shape():
    return FetchError(MSG_SHAPE, 'bad_url')


def _failed(code, http=None):
    return FetchError(MSG_FAILED, code, http)


def _too_large(max_bytes):
    from aot.utils.ai_card_files import _too_large as make
    err = make(max_bytes)
    return FetchError(str(err), 'too_large')


# ── 1~3 단계: 문자열·구문·호스트 (DNS 없음) ─────────────────────────────────

Target = collections.namedtuple('Target', 'host target url')

_PRINTABLE = re.compile(r'[\x21-\x7e]+')            # ASCII 인쇄 문자 — 공백·제어·비ASCII 없음
_NETLOC = re.compile(r'([^:]+)(?::([0-9]+))?')
_HOST = re.compile(r'[a-z0-9-]{1,63}(?:\.[a-z0-9-]{1,63})+')
#: 마지막 라벨이 숫자면 IP 의 변형이다 — 십진 `2130706433`·`127.1`·8진 `0177`·16진 `0x7f`.
#: (glibc·macOS 의 getaddrinfo 는 inet_aton 규칙으로 이런 글자를 IP 로 풀어 버린다.)
_NUMERIC_LABEL = re.compile(r'(?:0x[0-9a-f]*|[0-9]+)')
_BAD_SUFFIXES = ('.localhost', '.local', '.internal', '.lan', '.home.arpa', '.localdomain',
                 '.intranet', '.corp', '.private', '.arpa')


def check_url(raw):
    """URL 구문만 검사한다(DNS 없음). 통과하면 Target(host, target, url), 아니면 모양 문구.

    host 는 소문자 ASCII, target 은 요청 줄에 쓸 `/path?query`, url 은 포트·fragment 를 뗀
    정규형이다(리다이렉트의 urljoin 기준)."""
    # 1 문자열
    if not isinstance(raw, str) or not raw or len(raw) > MAX_URL:
        raise _shape()
    if not _PRINTABLE.fullmatch(raw) or '\\' in raw:
        raise _shape()
    # 2 urlsplit
    try:
        parts = urlsplit(raw)
    except ValueError:
        raise _shape()
    if parts.scheme != 'https':
        raise _shape()
    netloc = parts.netloc
    if not netloc or '@' in netloc or '[' in netloc or ']' in netloc:
        raise _shape()
    m = _NETLOC.fullmatch(netloc)
    if m is None or m.group(2) not in (None, '443'):
        raise _shape()
    host = m.group(1).lower()
    # 3 호스트
    _check_host(host)
    path = parts.path or '/'
    target = path + ('?' + parts.query if parts.query else '')
    return Target(host, target, 'https://%s%s' % (host, target))


def _check_host(host):
    if len(host) > 253 or not _HOST.fullmatch(host):
        raise _shape()
    labels = host.split('.')
    if any(lab.startswith('-') or lab.endswith('-') for lab in labels):
        raise _shape()
    if _NUMERIC_LABEL.fullmatch(labels[-1]):
        raise _shape()
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        raise _shape()
    if host == 'localhost' or host.endswith(_BAD_SUFFIXES):
        raise _shape()


# ── 5 단계: IP 판정 ─────────────────────────────────────────────────────────

_V4_BLOCKED = tuple(ipaddress.ip_network(n) for n in (
    '0.0.0.0/8', '10.0.0.0/8', '100.64.0.0/10', '127.0.0.0/8', '169.254.0.0/16',
    '172.16.0.0/12', '192.0.0.0/24', '192.0.2.0/24', '192.88.99.0/24', '192.168.0.0/16',
    '198.18.0.0/15', '198.51.100.0/24', '203.0.113.0/24', '224.0.0.0/4', '240.0.0.0/4',
    '255.255.255.255/32'))
_V6_BLOCKED = tuple(ipaddress.ip_network(n) for n in (
    '64:ff9b::/96', '64:ff9b:1::/48', '2001::/23', '2001:db8::/32', '100::/64', 'fc00::/7',
    'fe80::/10', 'fec0::/10', 'ff00::/8', '::/128', '::1/128', '3fff::/20'))
_V6_GLOBAL = ipaddress.ip_network('2000::/3')       # 지금 배정된 공인 유니캐스트는 모두 여기


def is_public_ip(ip):
    """전 세계에 라우팅되는 공인 주소인가. 모르면 False.

    IPv4 매핑 IPv6(::ffff:a.b.c.d)·6to4(2002::/16)는 안쪽 v4 로 다시 판정한다(3.10 의
    `is_global` 은 이를 직접 보지 않는다). 사설·루프백·링크로컬(메타데이터 169.254.169.254)·
    CGNAT·예약·멀티캐스트·문서용·NAT64·Teredo 는 명시 목록으로 거부하고, 마지막에
    `is_global` 도 참이어야 한다. routes_notice 의 링크 미리보기도 이 함수를 쓴다."""
    try:
        if isinstance(ip, str):
            ip = ipaddress.ip_address(ip.strip().split('%', 1)[0])
        if isinstance(ip, ipaddress.IPv6Address):
            inner = ip.ipv4_mapped
            if inner is None and ip in ipaddress.ip_network('2002::/16'):
                inner = ip.sixtofour
            if inner is not None:
                return is_public_ip(inner)
            if ip not in _V6_GLOBAL or any(ip in net for net in _V6_BLOCKED):
                return False
            return bool(ip.is_global)
        if isinstance(ip, ipaddress.IPv4Address):
            if any(ip in net for net in _V4_BLOCKED):
                return False
            return bool(ip.is_global)
    except (ValueError, TypeError, AttributeError):
        pass
    return False


# ── 4 단계: DNS ─────────────────────────────────────────────────────────────

_dns_executor = None
_dns_lock = threading.Lock()


def _executor():
    global _dns_executor
    with _dns_lock:
        if _dns_executor is None:
            _dns_executor = concurrent.futures.ThreadPoolExecutor(
                max_workers=2, thread_name_prefix='ai-card-dns')
        return _dns_executor


def _system_resolve(host):
    return [info[4][0] for info in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)]


def resolve_public(host, deadline, *, _resolver=None):
    """host → 연결해 볼 공인 IP 목록(IPv4 먼저, 최대 2개). **해석된 주소가 하나라도 비공인이면
    전체 거부**한다(섞인 레코드 트릭). 실패·시간 초과는 일반 문구다.

    getaddrinfo 는 취소할 수 없다 — 2초 안에 못 돌아오면 포기하지만 그 스레드는 호출이 끝날 때까지
    실행기(2개)를 쥔다. 그동안은 새 해석이 줄을 서다 같은 한도에서 실패한다."""
    resolver = _resolver or _system_resolve
    wait = min(DNS_S, deadline - time.monotonic())
    if wait <= 0:
        raise _failed('timeout')
    future = _executor().submit(resolver, host)
    try:
        raw = list(future.result(timeout=wait))
    except concurrent.futures.TimeoutError:
        future.cancel()
        raise _failed('timeout')
    except Exception:
        raise _failed('dns')
    ips = []
    for item in raw:
        try:
            ip = ipaddress.ip_address(str(item).strip().split('%', 1)[0])
        except ValueError:
            raise _failed('blocked')
        if not is_public_ip(ip):
            raise _failed('blocked')
        if ip not in ips:
            ips.append(ip)
    if not ips:
        raise _failed('dns')
    ips.sort(key=lambda a: a.version)               # IPv4 먼저(안정 정렬)
    return [str(a) for a in ips[:MAX_ADDRS]]


# ── 6~7 단계: 연결·요청 ─────────────────────────────────────────────────────

_ctx = None
_ctx_lock = threading.Lock()


def _ssl_context():
    """TLS 1.2 이상, 인증서·호스트 이름 검증, certifi 번들."""
    global _ctx
    with _ctx_lock:
        if _ctx is None:
            import ssl
            import certifi
            ctx = ssl.create_default_context(cafile=certifi.where())
            ctx.minimum_version = ssl.TLSVersion.TLSv1_2
            ctx.check_hostname = True
            ctx.verify_mode = ssl.CERT_REQUIRED
            _ctx = ctx
        return _ctx


class _Watchdog:
    """총 시간(TOTAL_S) 감시 — 때가 되면 등록된 소켓을 끊어 막힌 읽기를 깨운다."""

    def __init__(self, seconds):
        self.expired = False
        self._socks = []
        self._lock = threading.Lock()
        self._timer = threading.Timer(max(seconds, 0.01), self._fire)
        self._timer.daemon = True
        self._timer.start()

    def watch(self, sock):
        with self._lock:
            self._socks.append(sock)
            late = self.expired
        if late:
            self._kill(sock)

    def _fire(self):
        with self._lock:
            self.expired = True
            socks = list(self._socks)
        for sock in socks:
            self._kill(sock)

    @staticmethod
    def _kill(sock):
        try:
            socket.socket.shutdown(sock, socket.SHUT_RDWR)   # SSL 계층을 건드리지 않고 fd 만
        except Exception:
            pass

    def cancel(self):
        self._timer.cancel()


def _make_pool(ip, host, ctx, timeout, watch):
    """검증한 IP 로 직접 연결하는 풀. SNI·인증서 검증은 원래 호스트로, 다시 해석하지 않는다.
    환경변수 프록시를 읽지 않는다(ConnectionPool 은 읽지 않는다)."""
    from urllib3 import HTTPSConnectionPool
    from urllib3.connection import HTTPSConnection

    class _Conn(HTTPSConnection):
        def connect(self):
            super().connect()
            watch(self.sock)

    class _Pool(HTTPSConnectionPool):
        ConnectionCls = _Conn

    return _Pool(host=ip, port=443, server_hostname=host, assert_hostname=host,
                 ssl_context=ctx, retries=False, timeout=timeout, maxsize=1)


def _request_headers(host):
    return {'Host': host, 'User-Agent': UA, 'Accept': '*/*',
            'Accept-Encoding': 'identity', 'Connection': 'close'}


def _code_for(exc, wd):
    from urllib3 import exceptions as ue
    import ssl
    if wd.expired:
        return 'timeout'
    if isinstance(exc, ue.NewConnectionError):          # urllib3 에서는 ConnectTimeoutError 의 자식이다
        return 'connect'
    if isinstance(exc, (ue.TimeoutError, socket.timeout, TimeoutError)):
        return 'timeout'
    if isinstance(exc, (ue.SSLError, ssl.SSLError, ssl.CertificateError)):
        return 'tls'
    return 'connect'


def _open(target, ips, deadline, ctx, wd, pool_factory):
    """ips 를 차례로(최대 2개) 연결해 응답 헤더까지 받는다. (pool, resp) 를 돌려준다."""
    from urllib3 import Timeout
    last = 'connect'
    for ip in ips[:MAX_ADDRS]:
        remaining = deadline - time.monotonic()
        if remaining <= 0 or wd.expired:
            raise _failed('timeout')
        timeout = Timeout(connect=min(CONNECT_S, remaining), read=min(READ_S, remaining))
        pool = pool_factory(ip, target.host, ctx, timeout, wd.watch)
        try:
            resp = pool.urlopen(
                'GET', target.target, headers=_request_headers(target.host), redirect=False,
                retries=False, preload_content=False, decode_content=False,
                assert_same_host=False)
            return pool, resp
        except Exception as exc:
            last = _code_for(exc, wd)
            with contextlib.suppress(Exception):
                pool.close()
            logger.debug('[ai_card_fetch] 연결 실패(%s): %s', last, type(exc).__name__)
    raise _failed(last)


def _read_body(resp, cap, deadline, wd, truncate=False):
    """64 KiB 씩 읽다 누적이 cap 을 넘으면 즉시 끊는다. Content-Length 는 조기 거부에만 쓴다.
    truncate=True(공지 링크 미리보기)면 넘는 쪽을 오류 대신 cap 에서 자른 앞부분으로 돌려준다."""
    enc = (resp.headers.get('Content-Encoding') or '').strip().lower()
    if enc and enc != 'identity':
        raise _failed('encoding')
    length = (resp.headers.get('Content-Length') or '').strip()
    if length.isdigit() and int(length) > cap and not truncate:
        raise _too_large(cap)
    buf = bytearray()
    while True:
        if wd.expired or time.monotonic() > deadline:
            raise _failed('timeout')
        chunk = resp.read(CHUNK)
        if not chunk:
            break
        buf += chunk
        if len(buf) > cap:
            if truncate:
                return bytes(buf[:cap])
            raise _too_large(cap)
    return bytes(buf)


def _download(target, cap, wd, deadline, resolver, pool_factory, truncate=False,
              allow_hosts=None):
    """리다이렉트를 수동으로 따라가며 본문을 받는다. (바이트, 최종 Target).
    allow_hosts(P5 포스터·oEmbed)가 있으면 첫 홉과 **모든 리다이렉트 홉**의 호스트가 그 안에
    있어야 한다 — 밖이면 DNS 도 하기 전에 'redirect' 로 거부한다."""
    ctx = _ssl_context()
    current = target
    for hop in range(MAX_REDIRECTS + 1):
        if allow_hosts is not None and current.host not in allow_hosts:
            raise _failed('redirect')
        ips = resolve_public(current.host, deadline, _resolver=resolver)
        pool, resp = _open(current, ips, deadline, ctx, wd, pool_factory)
        try:
            status = resp.status
            if status in _REDIRECT_STATUS:
                location = resp.headers.get('Location')
                if not location or hop == MAX_REDIRECTS:
                    raise _failed('redirect')
                try:
                    current = check_url(urljoin(current.url, location))
                except FetchError:
                    raise _failed('redirect')
                continue
            if status != 200:
                raise _failed('status', status)
            try:
                return _read_body(resp, cap, deadline, wd, truncate), current
            except FetchError:
                raise
            except Exception as exc:
                raise _failed(_code_for(exc, wd))
        finally:
            with contextlib.suppress(Exception):
                resp.close()
            with contextlib.suppress(Exception):
                pool.close()
    raise _failed('redirect')                           # pragma: no cover - 루프가 이미 거른다


# ── 동시성·한도·감사 ────────────────────────────────────────────────────────

_slots = threading.BoundedSemaphore(FETCH_SLOTS)
_gate = threading.Lock()
_busy_users = set()


@contextlib.contextmanager
def _admission(user_key):
    """프로세스 슬롯 2개 + 사용자당 동시 1건. 기다리지 않고 즉시 '바쁨'."""
    with _gate:
        if user_key in _busy_users:
            raise FetchError(MSG_BUSY, 'busy')
        if not _slots.acquire(blocking=False):
            raise FetchError(MSG_BUSY, 'busy')
        _busy_users.add(user_key)
    try:
        yield
    finally:
        with _gate:
            _busy_users.discard(user_key)
        _slots.release()


#: 받기에 성공했지만 카드가 생기기 전이라 아직 감사 행이 되지 않은 시도(사용자별). 감사 행 수로만
#: 세면 post 하나(또는 겹친 post 여럿)가 상한을 그만큼 넘길 수 있어, 상한을 셀 때 함께 센다.
#: 이 프로세스 안에서만 듣는다(MCP 서버는 한 프로세스). 호출자가 finish 를 빠뜨려도 5분 뒤 잊는다.
_PENDING_TTL_S = 300
_pending = collections.defaultdict(list)           # user_id → [(시각, Attempt)]
_pending_lock = threading.Lock()


def _pending_count(user_id):
    now = time.monotonic()
    with _pending_lock:
        live = [(t, a) for t, a in _pending.get(user_id, ()) if not a.done
                and now - t < _PENDING_TTL_S]
        if live:
            _pending[user_id] = live
        else:
            _pending.pop(user_id, None)
        return len(live)


def _hold(user_id, attempt):
    if user_id is None:
        return
    with _pending_lock:
        _pending[user_id].append((time.monotonic(), attempt))


def _used(user_id, now=None):
    """(최근 1시간, 최근 24시간) 시도 수 — 감사 행 + 아직 행이 되지 않은 성공 시도."""
    import datetime
    from aot.databases.models import AuditLog
    from aot.utils import audit
    from aot.utils.ai_screen_cards import _now
    now = now or _now()
    base = AuditLog.query.filter(AuditLog.action == audit.AI_CARD_FETCH,
                                 AuditLog.user_id == user_id)
    held = _pending_count(user_id)
    return (base.filter(AuditLog.timestamp >= now - datetime.timedelta(hours=1)).count() + held,
            base.filter(AuditLog.timestamp >= now - datetime.timedelta(days=1)).count() + held)


def limit_problem(user_id, now=None):
    """시간 30·일 100 시도(실패·차단 포함). 감사 행 수로 세므로 여러 프로세스에서도 공유된다."""
    if user_id is None:
        return None
    hour, day = _used(user_id, now)
    if hour >= PER_HOUR:
        return MSG_HOUR
    if day >= PER_DAY:
        return MSG_DAY
    return None


def attempts_left(user_id, now=None):
    """지금 더 시도할 수 있는 횟수(시간·일 중 작은 쪽). post 가 시작할 때 한 번 재서 그 안에서만
    가져오기를 시도한다(P5 보안 리뷰)."""
    if user_id is None:
        return 0
    hour, day = _used(user_id, now)
    return max(0, min(PER_HOUR - hour, PER_DAY - day))


_AUDIT_HOST = re.compile(r'[a-z0-9.-]{1,100}')


def _audit_host(raw):
    """감사에는 호스트만 남긴다(경로·쿼리·userinfo 0). 호스트 모양이 아니면 비운다."""
    try:
        host = (urlsplit(raw).hostname or '').lower() if isinstance(raw, str) else ''
    except ValueError:
        return None
    return host if _AUDIT_HOST.fullmatch(host or '') else None


class Attempt:
    """시도 한 번 = 감사 한 행. 성공은 카드가 생긴 뒤에 `finish('ok', size, card_uuid)`."""

    def __init__(self, user, host=None):
        self.user = user
        self.host = host
        self.done = False

    def finish(self, code, size=0, card_uuid=None, http=None):
        if self.done:
            return
        self.done = True        # _pending 은 done 인 시도를 세지 않는다
        detail = '%s %d' % (code, size)
        if isinstance(http, int) and 100 <= http <= 599:
            detail += ' http=%d' % http
        from aot.utils import audit
        audit.audit_log(
            audit.AI_CARD_FETCH, target_type='AICardFetch', target_id=card_uuid,
            target_name=self.host, result='success' if code == 'ok' else 'failure',
            detail=detail, user_id=getattr(self.user, 'id', None),
            username=getattr(self.user, 'name', None))


Fetched = collections.namedtuple('Fetched', 'name_hint data host attempt')


def fetch(url, user, max_bytes=MAX_FILE_BYTES, allow_hosts=None, truncate=False, *, _resolver=None,
          _pool_factory=None):
    """공개 https URL 의 파일을 받아 Fetched(name_hint, data, host, attempt) 를 돌려준다.
    실패는 FetchError(FileError). 감사 한 행이 생긴다(한도 거부는 0행).
    allow_hosts: frozenset — 영상 포스터·oEmbed 가 고정 호스트에서만 받도록(리다이렉트 포함).
    truncate: True 면 상한을 넘는 응답을 오류 없이 앞부분으로 자른다(웹페이지 og 태그용)."""
    uid = getattr(user, 'id', None)
    problem = limit_problem(uid)
    if problem:
        raise FetchError(problem, 'limit')
    attempt = Attempt(user, _audit_host(url))
    wd = None
    try:
        target = check_url(url)
        attempt.host = target.host
        with _admission(uid):
            wd = _Watchdog(TOTAL_S)
            deadline = time.monotonic() + TOTAL_S
            try:
                data, final = _download(target, max_bytes, wd, deadline, _resolver,
                                        _pool_factory or _make_pool, truncate, allow_hosts)
            finally:
                wd.cancel()
    except FetchError as exc:
        attempt.finish(exc.code, http=getattr(exc, 'http', None))
        raise
    except Exception:
        logger.exception('[ai_card_fetch] 예상 밖 오류')
        attempt.finish('connect')
        raise _failed('connect') from None
    _hold(uid, attempt)         # 성공한 시도 — 호출자가 finish 할 때까지 상한에 센다
    hint = None
    for candidate in (url, final.url):
        name = name_from_url(candidate)
        if name and '.' in name and name.rsplit('.', 1)[-1].lower() in ALLOWED:
            hint = name
            break
    return Fetched(hint, data, target.host, attempt)


def fetch_public(url, max_bytes, *, truncate=False, total_s=TOTAL_S, _resolver=None,
                 _pool_factory=None):
    """공개 https URL 의 앞쪽 max_bytes 를 받아 (바이트, 최종 URL) 로 돌려준다 — 공지 링크 미리보기용.

    `fetch` 와 같은 방어(1~9 단계: 검증 IP 직접 연결·프록시 무시·수동 리다이렉트·스트리밍 상한·총 시간)를
    쓰되 사용자·슬롯·한도·감사는 없다(호출 쪽이 자기 한도를 건다). truncate=True 면 상한을 넘는 응답을
    오류 없이 앞부분으로 자른다. 실패는 모두 FetchError(문구 일반화). 테스트 키워드는 도구 경로에 닿지 않는다."""
    target = check_url(url)
    wd = _Watchdog(total_s)
    try:
        deadline = time.monotonic() + total_s
        data, final = _download(target, max_bytes, wd, deadline, _resolver,
                                _pool_factory or _make_pool, truncate)
    except FetchError:
        raise
    except Exception:
        logger.exception('[ai_card_fetch] 예상 밖 오류')
        raise _failed('connect') from None
    finally:
        wd.cancel()
    return data, final.url


# ── 10 단계: 이름·형식 추측 ─────────────────────────────────────────────────

def name_from_url(url):
    """URL 경로의 마지막 조각(퍼센트 디코드 UTF-8). 없거나 디코드 실패면 None.
    Content-Disposition 은 믿지 않는다 — 어차피 확장자는 inspect 가 다시 본다."""
    if not isinstance(url, str):
        return None
    try:
        path = urlsplit(url).path
    except ValueError:
        return None
    base = path.rsplit('/', 1)[-1]
    if not base:
        return None
    try:
        return unquote(base, errors='strict') or None
    except UnicodeDecodeError:
        return None


def sniff_ext(data):
    """매직바이트로 이미지 4종·pdf 만 추측한다(텍스트류는 이름이 있어야 한다)."""
    if data.startswith(b'\x89PNG\r\n\x1a\n'):
        return 'png'
    if data.startswith(b'\xff\xd8\xff'):
        return 'jpg'
    if data.startswith((b'GIF87a', b'GIF89a')):
        return 'gif'
    if data[:4] == b'RIFF' and data[8:12] == b'WEBP':
        return 'webp'
    if data.startswith(b'%PDF-'):
        return 'pdf'
    return None


#: 본문의 이미지 후보 — 유계·선형(대괄호 안 200자, 주소 2048자, 닫는 괄호가 없으면 바로 실패).
#: ① `![alt](https://…)` ② `[글](https://…)` ③ 맨 `https://…` 토큰. ②③ 은 아래에서 확장자로 거른다.
_MD_IMAGE = re.compile(
    r'(?P<bang>!?)\[[^\]\n]{0,200}\]\((?P<link>https://[^\s()<>]{1,2048})\)'
    r'|(?P<bare>https://[^\s()<>\[\]]{1,2048})')

_IMAGE_EXTS = ('.jpg', '.jpeg', '.png', '.gif', '.webp')
_BARE_TAIL = '.,;:!?*_\'"'


def _has_image_ext(url):
    """주소의 경로(쿼리·# 제외)가 이미지 확장자로 끝나는가(대소문자 무시)."""
    path = url.split('#', 1)[0].split('?', 1)[0].lower()
    return path.endswith(_IMAGE_EXTS)


def iter_md_links(text):
    """본문의 링크 후보를 등장 순서대로 (오프셋, 주소, 느낌표 여부) 로 낸다 — 이미지·영상 인식이
    같은 유계 정규식을 쓴다. `![alt](url)` 는 forced=True, 일반 링크·맨 주소는 False."""
    if not isinstance(text, str):
        return
    for m in _MD_IMAGE.finditer(text):
        if m.group('link') is not None:
            yield m.start(), m.group('link'), bool(m.group('bang'))
        else:
            yield m.start(), m.group('bare').rstrip(_BARE_TAIL), False


def find_md_image_spans(text, limit=1):
    """find_md_images 와 같지만 (오프셋, 주소) 쌍으로 돌려준다(본문 영상 링크와 순서를 맞추려고)."""
    out, seen = [], set()
    if limit <= 0:
        return out
    for pos, url, forced in iter_md_links(text):
        if not (forced or _has_image_ext(url)) or url in seen:
            continue
        seen.add(url)
        out.append((pos, url))
        if len(out) >= limit:
            break
    return out


def find_md_images(text, limit=1):
    """본문에서 이미지로 보이는 https 주소를 앞에서부터 limit 개(중복 제외).

    `![alt](https://…)` 는 확장자와 무관하게(서명 주소 등 — 받아서 매직바이트로 판정), `[글](https://…)`
    와 맨 주소는 경로가 이미지 확장자로 끝날 때만."""
    return [url for _pos, url in find_md_image_spans(text, limit)]
