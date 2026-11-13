# coding=utf-8
"""네트워크 카메라 공용 도우미: 자격 증명 URL, 로그 마스킹, 재시도 간격, 스냅샷 받기.

표준 라이브러리와 requests 만 쓴다(cv2 에 의존하지 않는다) — 파이급 장비에서
스냅샷 방식이 OpenCV 없이도 돌도록.
"""
import hashlib
import threading
import time
from urllib.parse import quote, urlparse, urlunparse

AUTH_FAIL_CODES = (401, 403)

# --- 인증 실패 래치 -----------------------------------------------------------
# 카메라는 로그인을 몇 번 틀리면 잠근다. 인증 실패가 한 번이라도 나면 그 카메라의 자동 재접속을
# 멈추고, 사용자가 자격 증명(주소·계정·비밀번호)을 바꾸거나 설정 저장·활성화로 풀 때까지 두드리지 않는다.
# 래치는 프로세스 메모리다(gunicorn 은 워커 1개) — 재시작하면 풀리고, 그때 최대 한 번 더 시도한다.
_LATCH = {}
_LATCH_LOCK = threading.Lock()


def credential_fingerprint(url, username, password):
    """주소·계정·비밀번호가 바뀌면 달라지는 지문(래치가 낡은 자격 증명에만 묶이게)."""
    raw = '\x00'.join((url or '', username or '', password or ''))
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()[:16]


def latch_auth_failure(unique_id, fingerprint):
    with _LATCH_LOCK:
        _LATCH[unique_id] = (fingerprint, time.time())


def is_auth_latched(unique_id, fingerprint):
    """같은 자격 증명으로 이미 거절당했으면 True. 자격 증명이 바뀌었으면 래치를 풀고 False."""
    with _LATCH_LOCK:
        entry = _LATCH.get(unique_id)
        if entry is None:
            return False
        if entry[0] == fingerprint:
            return True
        del _LATCH[unique_id]
        return False


def latched_cameras():
    """{unique_id: 래치가 걸린 시각(epoch 초)} — 화면 알림용 사본."""
    with _LATCH_LOCK:
        return {uid: ts for uid, (_fp, ts) in _LATCH.items()}


def clear_auth_latch(unique_id):
    with _LATCH_LOCK:
        _LATCH.pop(unique_id, None)


def _wants_digest(response):
    headers = getattr(response, 'headers', None) or {}
    return 'digest' in str(headers.get('WWW-Authenticate', '')).lower()


class SnapshotError(Exception):
    """스냅샷을 받지 못했다."""


class SnapshotAuthError(SnapshotError):
    """카메라가 자격 증명을 거부했다(401/403) — 재시도하면 로그인 잠금을 키운다."""


def build_stream_url(url, username, password):
    """URL 에 user:password 를 넣는다(퍼센트 인코딩). 이미 들어 있으면 그대로."""
    if not username or not url or '://' not in url:
        return url
    parsed = urlparse(url)
    if parsed.username:
        return url
    host = parsed.hostname or ''
    if ':' in host:  # IPv6
        host = f'[{host}]'
    netloc = f"{quote(username, safe='')}:{quote(password or '', safe='')}@{host}"
    if parsed.port:
        netloc += f":{parsed.port}"
    return urlunparse(parsed._replace(netloc=netloc))


def redact_url(url):
    """로그용: URL 안의 비밀번호를 가린다. URL 이 아니면 그대로 돌려준다."""
    if not url or not isinstance(url, str) or '://' not in url:
        return url
    try:
        parsed = urlparse(url)
        if parsed.password is None:
            return url
        host = parsed.hostname or ''
        if ':' in host:
            host = f'[{host}]'
        netloc = f"{parsed.username or ''}:***@{host}"
        if parsed.port:
            netloc += f":{parsed.port}"
        return urlunparse(parsed._replace(netloc=netloc))
    except ValueError:
        return '<unparseable url>'


class RetryBackoff:
    """연속 실패 횟수에 따라 늘어나는 재시도 간격(초).

    일반 실패 5→10→20…상한 300. 인증 실패는 60 에서 시작해 상한 900 —
    카메라는 로그인을 몇 번 틀리면 잠그기 때문에 더 길게 둔다.
    """

    def __init__(self, base=5.0, cap=300.0, auth_base=60.0, auth_cap=900.0):
        self.base = base
        self.cap = cap
        self.auth_base = auth_base
        self.auth_cap = auth_cap
        self.failures = 0

    def next_delay(self, auth=False):
        base, cap = (self.auth_base, self.auth_cap) if auth else (self.base, self.cap)
        delay = min(cap, base * (2 ** self.failures))
        self.failures += 1
        return delay

    def reset(self):
        self.failures = 0


def is_jpeg(data):
    return bool(data) and data[:2] == b'\xff\xd8' and data[-2:] == b'\xff\xd9'


def fetch_snapshot(url, username='', password='', verify=True, timeout=(3, 5),
                   headers=None, session=None):
    """HTTP 로 JPEG 한 장을 받아 바이트로 돌려준다(디코딩하지 않는다).

    자격 증명이 있으면 Basic 으로 먼저 시도한다. 401 이고 카메라가 Digest 를 요구할 때만(WWW-Authenticate)
    Digest 로 한 번 더 시도한다 — 틀린 시도를 한 번이라도 줄여 로그인 잠금을 피한다. 403 은 다시 시도하지 않는다.
    거절당하면 SnapshotAuthError. JPEG 가 아닌 응답(로그인 HTML 등)은
    SnapshotError.
    """
    import requests
    from requests.auth import HTTPBasicAuth, HTTPDigestAuth

    if not url:
        raise SnapshotError('No snapshot URL configured')
    getter = session.get if session is not None else requests.get
    attempts = [None]
    if username:
        attempts = [HTTPBasicAuth(username, password or ''),
                    HTTPDigestAuth(username, password or '')]
    last_status = None
    for auth in attempts:
        try:
            response = getter(url, auth=auth, headers=headers or {},
                              verify=verify, timeout=timeout)
        except requests.RequestException as err:
            raise SnapshotError(f'Snapshot request failed: {type(err).__name__}') from None
        last_status = response.status_code
        if response.status_code in AUTH_FAIL_CODES:
            if response.status_code == 401 and isinstance(auth, HTTPBasicAuth) and _wants_digest(response):
                continue
            break
        if response.status_code != 200:
            raise SnapshotError(f'Snapshot HTTP {response.status_code}')
        if not is_jpeg(response.content):
            raise SnapshotError('Response is not a JPEG image')
        return response.content
    raise SnapshotAuthError(f'Camera rejected credentials (HTTP {last_status})')


def http_auth_rejected(url, username, password, verify=True, timeout=(3, 5)):
    """http(s) 스트림 주소가 이 자격 증명을 거절하는지 한 번 확인한다(영상은 받지 않는다).

    cv2 는 열기에 실패한 이유를 알려 주지 않아, 비밀번호가 틀려도 '열 수 없음' 으로만 보인다.
    그 분류용이다. 401 은 Digest 를 요구할 때만 한 번 더 확인하고, 네트워크 오류는 거절이 아니다(False).
    rtsp:// 는 다루지 않는다(Digest 계산 없이 판정하면 맞는 자격 증명을 거절로 잘못 보게 된다).
    """
    import requests
    from requests.auth import HTTPBasicAuth, HTTPDigestAuth

    if not username or not url.lower().startswith(('http://', 'https://')):
        return False
    auths = [HTTPBasicAuth(username, password or ''), HTTPDigestAuth(username, password or '')]
    for auth in auths:
        try:
            response = requests.get(url, auth=auth, stream=True, verify=verify, timeout=timeout)
            status = response.status_code
            digest = _wants_digest(response)
            response.close()
        except requests.RequestException:
            return False
        if status not in AUTH_FAIL_CODES:
            return False
        if not (status == 401 and isinstance(auth, HTTPBasicAuth) and digest):
            return True
    return True
