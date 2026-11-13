# coding=utf-8
"""ONVIF 라이브용 FrameSource(RTSP→JPEG)와 스냅샷. 범위 문서 O2.

RTSP 주소는 드라이버의 `stream_profiles()`(GetStreamUri)에서 얻는다 — 경로를 짐작하지 않는다.
주소에는 자격 증명이 없고, 열 때만 `with_credentials` 로 붙여 OpenCV 에 넘긴다(로그·반환값에 남기지 않는다).
SOAP 호출은 모두 OnvifSoap 을 거치므로 래치·재인증 규칙을 그대로 따른다. 이 클래스에는 인증 재시도 루프가 없다.
"""
import http.client
import logging
import secrets
import threading
import time
from urllib.parse import quote, urlsplit

from aot.camera_drivers import frames as F
from aot.camera_drivers.auth_guard import Permit, credential_fp
from aot.camera_drivers.driver import ErrorClass
from aot.camera_drivers.onvif import soap as S
from aot.camera_drivers.onvif.driver import OnvifDriver
from aot.camera_drivers.vigi import rtsp_probe
from aot.camera_drivers.vigi.sources import open_capture
from aot.utils.timekit import utc_now

logger = logging.getLogger(__name__)

#: 잠금·인증 계열 — 사용자가 풀기 전에는 다시 시도하지 않는다
_FATAL = (ErrorClass.AUTH_FAILED, ErrorClass.LOCKED, ErrorClass.CERT_CHANGED)
_URL_TTL = 300.0
_url_cache = {}
_url_lock = threading.Lock()


class SnapshotError(Exception):
    pass


def with_credentials(url, username, password):
    """열기 직전에만 쓴다. 결과를 로그·반환값·DB 에 남기지 않는다."""
    u = urlsplit(url)
    host = u.hostname or ''
    if ':' in host:
        host = '[%s]' % host
    netloc = '%s:%s@%s' % (quote(username, safe=''), quote(password, safe=''), host)
    if u.port:
        netloc += ':%d' % u.port
    return '%s://%s%s%s' % (u.scheme, netloc, u.path or '', ('?' + u.query) if u.query else '')


def pick_profile(profiles, live):
    """랭킹된 StreamProfile 목록(해상도 큰 순)에서 설정한 화질을 고른다. main=가장 큼, sub=두 번째, mjpeg=MJPEG."""
    if not profiles:
        return None
    if live == 'main':
        return profiles[0]
    if live == 'mjpeg':
        for p in profiles:
            if p.codec in ('mjpeg', 'jpeg'):
                return p
    return profiles[1] if len(profiles) > 1 else profiles[0]


def make_driver(camera_id, credential, host, onvif_port, guard, fp_key, transport=None):
    return OnvifDriver(host, credential, camera_id=camera_id, guard=guard, fp_key=fp_key,
                       openapi_port=onvif_port, transport=transport)


def _fail_reason(drv):
    """(사유, 치명 여부). 네트워크 오류만 재시도 대상이다 — 인증·거부는 사용자가 풀 때까지 멈춘다."""
    r = drv.last_negotiation
    if r is None:
        return 'no_profiles', False
    if r.error_class is ErrorClass.NETWORK:
        return 'unreachable', False
    if r.error_class in _FATAL:
        return 'auth:' + r.error_class.value, True
    if r.state.value == 'refused':       # 확인 안 된 자격 증명·래치
        return 'auth:not_verified', True
    return 'no_profiles', False


def resolve_stream_url(camera_id, credential, host, onvif_port, guard, fp_key, live, transport=None):
    """(url, codec). 못 얻으면 SourceError. 최근에 얻은 주소는 잠시 재사용한다(재연결마다 SOAP 을 반복하지 않는다)."""
    key = (camera_id, host, int(onvif_port), live)
    now = time.monotonic()
    with _url_lock:
        hit = _url_cache.get(key)
        if hit and now - hit[2] < _URL_TTL:
            return hit[0], hit[1]
    drv = make_driver(camera_id, credential, host, onvif_port, guard, fp_key, transport)
    try:
        chosen = pick_profile(drv.stream_profiles(), live)
        if chosen is None:
            reason, fatal = _fail_reason(drv)
            raise F.SourceError(reason, fatal=fatal)
    finally:
        drv.close()
    with _url_lock:
        _url_cache[key] = (chosen.url, chosen.codec, now)
    return chosen.url, chosen.codec


def forget_url(camera_id):
    with _url_lock:
        for k in [k for k in _url_cache if k[0] == camera_id]:
            _url_cache.pop(k, None)


def diagnose_rtsp(guard, camera_id, credential, url, fp_key, timeout=5.0):
    """열기에 실패한 뒤 이유를 한 번만 본다. 401 이면 래치하고 'auth_failed' 를 돌려준다."""
    fp = credential_fp(credential.username, credential.password, fp_key)
    permit = guard.begin(camera_id, fp, 'rtsp', reauth=True)
    if not isinstance(permit, Permit):
        return 'auth_failed'
    u = urlsplit(url)
    path = (u.path or '/') + (('?' + u.query) if u.query else '')
    result, status = rtsp_probe.describe(u.hostname, u.port or 554, path,
                                         credential.username, credential.password, timeout)
    if result == 'auth_failed':
        guard.report_failure(permit, ErrorClass.AUTH_FAILED, status)
    return result


class OnvifRtspSource(F.FrameSource):
    def __init__(self, guard, camera_id, credential, host, onvif_port, fp_key, profile='sub',
                 cv2_module=None, capture_opener=None, transport=None):
        self.guard, self.camera_id, self.cred = guard, camera_id, credential
        self.host, self.onvif_port, self.fp_key, self.profile = host, onvif_port, fp_key, profile
        self._cv2, self._opener, self._transport = cv2_module, capture_opener, transport
        self._cap = None
        self._seq = 0

    def open(self):
        url, _codec = resolve_stream_url(self.camera_id, self.cred, self.host, self.onvif_port,
                                         self.guard, self.fp_key, self.profile, self._transport)
        cv2 = self._cv2 or __import__('cv2')
        cap = (self._opener or open_capture)(
            with_credentials(url, self.cred.username, self.cred.password), cv2)
        if not cap.isOpened():
            cap.release()
            forget_url(self.camera_id)
            if diagnose_rtsp(self.guard, self.camera_id, self.cred, url, self.fp_key) == 'auth_failed':
                raise F.SourceError('auth:auth_failed', fatal=True)
            raise F.SourceError('open_failed')
        self._cap = cap

    def read(self):
        ok, img = self._cap.read()
        if not ok or img is None:
            return None
        cv2 = self._cv2 or __import__('cv2')
        okj, buf = cv2.imencode('.jpg', img)
        if not okj:
            return None
        self._seq += 1
        return F.Frame(utc_now(), self._seq, buf.tobytes(), None)

    def close(self):
        if self._cap is not None:
            self._cap.release()
            self._cap = None


# -- 스냅샷 (설계 §7 제안 A, 범위 문서 D5) -------------------------------------------
def _http_get(url, username, password, timeout=5.0, limit=8 * 1024 * 1024, conn_factory=None):
    """정지 이미지 한 장. 챌린지(Digest/Basic)를 받은 뒤 자격 증명을 **한 번** 보낸다. 반환 JPEG bytes."""
    u = urlsplit(url)
    if u.scheme != 'http' or not u.hostname:
        raise SnapshotError('bad_snapshot_uri')
    path = (u.path or '/') + (('?' + u.query) if u.query else '')
    factory = conn_factory or http.client.HTTPConnection
    conn = factory(u.hostname, u.port or 80, timeout=timeout)
    try:
        conn.request('GET', path)
        r = conn.getresponse()
        body = r.read(limit)
        if r.status == 401:
            hdr = r.getheader('www-authenticate') or ''
            chal = S.parse_digest_challenge(hdr)
            if chal:
                auth = S.digest_authorization(username, password, chal, 'GET', path, 1,
                                              secrets.token_hex(8))
            elif hdr.lower().startswith('basic'):
                import base64
                auth = 'Basic ' + base64.b64encode(('%s:%s' % (username, password)).encode()).decode()
            else:
                raise SnapshotError('auth_failed')
            conn.close()
            conn = factory(u.hostname, u.port or 80, timeout=timeout)
            conn.request('GET', path, headers={'Authorization': auth})
            r = conn.getresponse()
            body = r.read(limit)
        if r.status in (401, 403):
            raise SnapshotError('auth_failed')
        if r.status != 200 or not body.startswith(b'\xff\xd8'):
            raise SnapshotError('no_image')
        return body
    except (OSError, http.client.HTTPException):
        raise SnapshotError('network')
    finally:
        conn.close()


def take_snapshot(camera_id, credential, host, onvif_port, guard, fp_key, source_factory,
                  max_age=3.0, directory=None, transport=None, http_get=None):
    """1) 최신 프레임 파일(3초 이내) 2) GetSnapshotUri 3) RTSP 한 프레임. 래치가 걸려 있으면 SnapshotError."""
    data = F.LatestFrameFile.read_fresh(camera_id, max_age=max_age, directory=directory)
    if data:
        return data
    drv = make_driver(camera_id, credential, host, onvif_port, guard, fp_key, transport)
    try:
        uri = drv.snapshot_uri()
        if drv.capabilities() is None:
            reason, fatal = _fail_reason(drv)
            if fatal:
                raise SnapshotError(reason)
    finally:
        drv.close()
    if uri:
        fp = credential_fp(credential.username, credential.password, fp_key)
        permit = guard.begin(camera_id, fp, 'rtsp', reauth=True)     # 래치·미확인 자격 증명이면 보내지 않는다
        if isinstance(permit, Permit):
            try:
                return (http_get or _http_get)(uri, credential.username, credential.password)
            except SnapshotError as exc:
                if str(exc) == 'auth_failed':
                    guard.report_failure(permit, ErrorClass.AUTH_FAILED, 401)
                    raise
                logger.info('onvif snapshot uri failed (%s); falling back to RTSP', exc)
    src = source_factory()
    try:
        try:
            src.open()
        except F.SourceError as exc:
            raise SnapshotError(exc.reason)
        for _ in range(5):
            frame = src.read()
            if frame is not None and frame.jpeg:
                return frame.jpeg
        raise SnapshotError('no_frame')
    finally:
        src.close()
