# coding=utf-8
"""ONVIF 라이브·스냅샷 (범위 문서 O2) × 모의 서버. 실카메라 없음 — OpenCV 는 가짜 캡처로 대신한다."""
import pytest

from aot.camera_drivers import auth_guard as AG
from aot.camera_drivers import frames as F
from aot.camera_drivers.auth_guard import AuthGuard, InMemoryAuthStore
from aot.camera_drivers.driver import Credential, StreamProfile
from aot.camera_drivers.onvif import sources as OS
from aot.camera_drivers.onvif.driver import OnvifDriver
from aot.tests.fixtures.onvif_mock import MockOnvifServer

KEY = b'unit-test-fp-key'
GOOD = 'correct-horse-battery'
CID = 'cam-onvif-live'
CRED = Credential('admin', GOOD)


class FakeCap:
    def __init__(self, opened=True):
        self.opened = opened
        self.released = False

    def isOpened(self):
        return self.opened

    def release(self):
        self.released = True


@pytest.fixture(autouse=True)
def _clear_cache():
    OS._url_cache.clear()
    yield
    OS._url_cache.clear()


def verified(srv, store, password=GOOD):
    guard = AuthGuard(store)
    d = OnvifDriver('127.0.0.1', Credential('admin', password), camera_id=CID, guard=guard, fp_key=KEY,
                    openapi_port=srv.port, timeout=3.0)
    d.verify()
    d.close()
    return guard


def test_pick_profile():
    ps = [StreamProfile('main', 'rtsp://h/a', 'h265', 1920, 1080), StreamProfile('sub', 'rtsp://h/b', 'h264', 640, 360)]
    assert OS.pick_profile(ps, 'main').name == 'main'
    assert OS.pick_profile(ps, 'sub').name == 'sub'
    assert OS.pick_profile(ps[:1], 'sub').name == 'main'          # 프로필이 하나면 그것
    assert OS.pick_profile([], 'sub') is None


def test_with_credentials_quotes_and_keeps_port_path():
    u = OS.with_credentials('rtsp://10.0.0.5:8554/live/ch1?x=1', 'ad min', 'p@ss:w/d')
    assert u == 'rtsp://ad%20min:p%40ss%3Aw%2Fd@10.0.0.5:8554/live/ch1?x=1'


def test_live_open_uses_profile_uri_and_credentials_only_at_open():
    with MockOnvifServer() as srv:
        guard = verified(srv, InMemoryAuthStore())
        seen = []

        def opener(url, cv2):
            seen.append(url)
            return FakeCap()

        src = OS.OnvifRtspSource(guard, CID, CRED, '127.0.0.1', srv.port, KEY, 'sub',
                                 cv2_module=object(), capture_opener=opener)
        src.open()
        assert len(seen) == 1
        assert seen[0].startswith('rtsp://admin:' + GOOD + '@127.0.0.1:554/stream/')
        src.close()
        # 캐시된 주소에는 자격 증명이 없다
        assert all('@' not in v[0] for v in OS._url_cache.values())


def test_live_before_verify_is_fatal_and_sends_no_credential():
    with MockOnvifServer() as srv:
        guard = AuthGuard(InMemoryAuthStore())
        src = OS.OnvifRtspSource(guard, CID, CRED, '127.0.0.1', srv.port, KEY, 'sub',
                                 cv2_module=object(), capture_opener=lambda u, c: FakeCap())
        with pytest.raises(F.SourceError) as e:
            src.open()
        assert e.value.fatal and srv.credentialed_attempts() == 0


def test_live_wrong_password_after_verified_latches_once():
    with MockOnvifServer() as srv:
        store = InMemoryAuthStore()
        verified(srv, store)
        guard = AuthGuard(store)
        bad = Credential('admin', 'wrong-password-xyz')
        src = OS.OnvifRtspSource(guard, CID, bad, '127.0.0.1', srv.port, KEY, 'sub',
                                 cv2_module=object(), capture_opener=lambda u, c: FakeCap())
        with pytest.raises(F.SourceError) as e:
            src.open()
        assert e.value.fatal            # 확인된 자격 증명과 다르면 재인증하지 않는다
        assert srv.wrong_attempts() == 0


def test_live_unreachable_is_not_fatal():
    with MockOnvifServer() as srv:
        guard = verified(srv, InMemoryAuthStore())      # 확인된 자격 증명, 그러나 포트가 닫혀 있다
    src = OS.OnvifRtspSource(guard, CID, CRED, '127.0.0.1', 9, KEY, 'sub', cv2_module=object(),
                             capture_opener=lambda u, c: FakeCap())
    with pytest.raises(F.SourceError) as e:
        src.open()
    assert not e.value.fatal and e.value.reason == 'unreachable'


def test_capture_open_failure_diagnoses_once_and_not_fatal_on_network(monkeypatch):
    with MockOnvifServer() as srv:
        guard = verified(srv, InMemoryAuthStore())
        calls = []
        monkeypatch.setattr(OS.rtsp_probe, 'describe', lambda *a, **k: calls.append(a) or ('network', None))
        cap = FakeCap(opened=False)
        src = OS.OnvifRtspSource(guard, CID, CRED, '127.0.0.1', srv.port, KEY, 'sub',
                                 cv2_module=object(), capture_opener=lambda u, c: cap)
        with pytest.raises(F.SourceError) as e:
            src.open()
        assert not e.value.fatal and e.value.reason == 'open_failed' and cap.released
        assert len(calls) == 1 and OS._url_cache == {}


def test_capture_open_failure_401_latches_fatal(monkeypatch):
    with MockOnvifServer() as srv:
        store = InMemoryAuthStore()
        guard = verified(srv, store)
        monkeypatch.setattr(OS.rtsp_probe, 'describe', lambda *a, **k: ('auth_failed', 401))
        src = OS.OnvifRtspSource(guard, CID, CRED, '127.0.0.1', srv.port, KEY, 'sub',
                                 cv2_module=object(), capture_opener=lambda u, c: FakeCap(opened=False))
        with pytest.raises(F.SourceError) as e:
            src.open()
        assert e.value.fatal and store.load(CID).auth_state == AG.FAILED


# -- 스냅샷 -------------------------------------------------------------------------
class FakeSource(F.FrameSource):
    def __init__(self):
        self.closed = False

    def open(self):
        pass

    def read(self):
        return F.Frame(None, 1, b'\xff\xd8rtsp', None)

    def close(self):
        self.closed = True


def snap(srv, guard, tmp_path, **kw):
    return OS.take_snapshot(CID, CRED, '127.0.0.1', srv.port, guard, KEY, kw.pop('src', FakeSource),
                            directory=str(tmp_path), **kw)


def test_snapshot_prefers_fresh_frame_file(tmp_path):
    F.LatestFrameFile(CID, directory=str(tmp_path))(F.Frame(None, 1, b'\xff\xd8file', None))
    with MockOnvifServer() as srv:
        assert snap(srv, AuthGuard(InMemoryAuthStore()), tmp_path) == b'\xff\xd8file'
        assert srv.request_log == []


def test_snapshot_falls_back_to_rtsp_frame_when_no_snapshot_uri(tmp_path):
    with MockOnvifServer() as srv:
        guard = verified(srv, InMemoryAuthStore())
        assert snap(srv, guard, tmp_path) == b'\xff\xd8rtsp'


def test_snapshot_uses_snapshot_uri_when_supported(tmp_path, monkeypatch):
    with MockOnvifServer() as srv:
        guard = verified(srv, InMemoryAuthStore())
        monkeypatch.setattr(OnvifDriver, 'snapshot_uri', lambda self: 'http://127.0.0.1:80/snap.jpg')
        got = []
        out = snap(srv, guard, tmp_path, http_get=lambda u, a, b: got.append(u) or b'\xff\xd8http')
        assert out == b'\xff\xd8http' and got == ['http://127.0.0.1:80/snap.jpg']


def test_snapshot_uri_failure_falls_back_but_auth_failure_latches(tmp_path, monkeypatch):
    with MockOnvifServer() as srv:
        store = InMemoryAuthStore()
        guard = verified(srv, store)
        monkeypatch.setattr(OnvifDriver, 'snapshot_uri', lambda self: 'http://127.0.0.1:80/snap.jpg')

        def boom(kind):
            def f(u, a, b):
                raise OS.SnapshotError(kind)
            return f
        assert snap(srv, guard, tmp_path, http_get=boom('network')) == b'\xff\xd8rtsp'
        with pytest.raises(OS.SnapshotError):
            snap(srv, guard, tmp_path, http_get=boom('auth_failed'))
        assert store.load(CID).auth_state == AG.FAILED


def test_snapshot_refused_when_credential_not_verified(tmp_path):
    with MockOnvifServer() as srv:
        with pytest.raises(OS.SnapshotError):
            snap(srv, AuthGuard(InMemoryAuthStore()), tmp_path)
        assert srv.credentialed_attempts() == 0


def test_snapshot_uri_helper_rejects_non_http_and_strips_credentials():
    class Conn:
        def __init__(self, *a, **k):
            pass

        def request(self, *a, **k):
            raise AssertionError('must not connect')
    with pytest.raises(OS.SnapshotError):
        OS._http_get('rtsp://127.0.0.1/x', 'a', 'b', conn_factory=Conn)
