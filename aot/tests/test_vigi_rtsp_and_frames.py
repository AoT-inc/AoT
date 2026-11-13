# coding=utf-8
"""RTSP 경로의 인증 보호(설계 §6.1, §10.1 RTSP)·FrameHub·최신 프레임 파일·스냅샷(§7)·camera_record 분기."""
import os
import threading
import time
import uuid

import pytest

from aot.camera_drivers import auth_guard as AG
from aot.camera_drivers import frames as F
from aot.camera_drivers.auth_guard import AuthGuard, InMemoryAuthStore
from aot.camera_drivers.driver import Credential
from aot.camera_drivers.vigi import rtsp_access, snapshot
from aot.camera_drivers.vigi.sources import RtspCv2Source
from aot.tests.fixtures.vigi_mock import MockVigiServer
from aot.tests.fixtures.vigi_mock.rtsp import MockRtspServer
from aot.tests.test_vigi_openapi import BAD, GOOD, KEY, SqliteAuthStore, make_client

JPEG = b'\xff\xd8\xff\xe0fakejpeg\xff\xd9'


@pytest.fixture
def rtsp():
    with MockRtspServer() as m:
        yield m


def _guard():
    return AuthGuard(InMemoryAuthStore())


def _auth(guard, rtsp, pw, cid='cam1'):
    return rtsp_access.authorize(guard, cid, Credential('admin', pw), '127.0.0.1', rtsp.port, KEY)


# --------------------------------------------------------------------------- RTSP 래치
def test_rtsp_wrong_password_sends_credentials_once_then_latches(rtsp):
    g = _guard()
    with pytest.raises(rtsp_access.RtspDenied) as e:
        _auth(g, rtsp, BAD)
    assert e.value.fatal and rtsp.credential_attempts == 1 and rtsp.failed_attempts == 1
    unauth = rtsp.unauth_requests
    for pw in (BAD, GOOD):
        with pytest.raises(rtsp_access.RtspDenied):
            _auth(g, rtsp, pw)
    assert rtsp.credential_attempts == 1 and rtsp.unauth_requests == unauth   # 카메라에 아무것도 안 감
    assert g.store.load('cam1').auth_state == AG.FAILED


def test_rtsp_failure_also_stops_openapi_and_vice_versa(rtsp):
    g = _guard()
    with MockVigiServer() as m:
        with pytest.raises(rtsp_access.RtspDenied):
            _auth(g, rtsp, BAD)
        assert make_client(m, g, BAD).connect().state.value == 'refused'
        assert m.auth_log == []
    # 반대 방향
    g2 = _guard()
    with MockVigiServer() as m:
        make_client(m, g2, BAD).connect()
        with pytest.raises(rtsp_access.RtspDenied):
            _auth(g2, rtsp, BAD)
        assert rtsp.credential_attempts == 1       # 위 시험의 1회 이후 늘지 않았다


def test_rtsp_two_processes_one_attempt(rtsp, tmp_path):
    path = str(tmp_path / 'a.db')
    SqliteAuthStore(path)
    out = []
    barrier = threading.Barrier(2)

    def go():
        g = AuthGuard(SqliteAuthStore(path))
        barrier.wait()
        try:
            _auth(g, rtsp, BAD)
        except rtsp_access.RtspDenied as e:
            out.append(e.reason)
    ts = [threading.Thread(target=go) for _ in range(2)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert rtsp.credential_attempts == 1 and len(out) == 2


def test_verified_credential_opens_without_probe(rtsp):
    g = _guard()
    _auth(g, rtsp, GOOD)
    assert rtsp.credential_attempts == 1
    p = _auth(g, rtsp, GOOD)
    assert p.kind == AG.REAUTH and rtsp.credential_attempts == 1 and rtsp.unauth_requests == 1


def test_open_failure_after_password_rotation_is_diagnosed_once_and_latched(rtsp):
    g = _guard()
    _auth(g, rtsp, GOOD)
    rtsp.password = 'rotated'                  # 카메라 쪽 비밀번호가 바뀜

    class Cap:
        def isOpened(self):
            return False

        def release(self):
            pass
    src = RtspCv2Source(g, 'cam1', Credential('admin', GOOD), '127.0.0.1', rtsp.port, KEY,
                        cv2_module=object(), capture_opener=lambda url, cv2: Cap())
    with pytest.raises(F.SourceError) as e:
        src.open()
    assert e.value.fatal and rtsp.failed_attempts == 1
    with pytest.raises(F.SourceError) as e2:
        src.open()
    assert e2.value.fatal and rtsp.failed_attempts == 1       # 두 번째 열기는 카메라에 가지 않았다


def test_network_failure_is_not_fatal_and_does_not_latch():
    g = _guard()
    with MockRtspServer() as m:
        port = m.port
    with pytest.raises(rtsp_access.RtspDenied) as e:
        rtsp_access.authorize(g, 'cam1', Credential('admin', GOOD), '127.0.0.1', port, KEY, timeout=0.5)
    assert not e.value.fatal
    assert g.store.load('cam1').auth_state == AG.UNVERIFIED


def test_openapi_off_does_not_block_rtsp_and_survives_rtsp_success(rtsp):
    store = InMemoryAuthStore()
    g = AuthGuard(store)
    import socket
    s = socket.socket()
    s.bind(('127.0.0.1', 0))
    dead_port = s.getsockname()[1]
    s.close()
    from aot.camera_drivers.vigi.openapi import VigiOpenApi
    c = VigiOpenApi('127.0.0.1', Credential('admin', GOOD), camera_id='cam1', guard=g, fp_key=KEY,
                    port=dead_port, timeout=0.5)
    r = c.connect()
    assert r.error_class.value == 'network' and store.load('cam1').auth_state == AG.OPENAPI_OFF
    assert c.connect().state.value == 'refused'            # OpenAPI 는 멈춘다
    _auth(g, rtsp, GOOD)                                    # RTSP 가 그 1회 시도를 맡는다
    assert store.load('cam1').auth_state == AG.OPENAPI_OFF and store.load('cam1').verified_fp
    store.clear_latch('cam1')                               # 사용자가 카메라에서 켜고 "다시 연결"
    assert store.load('cam1').auth_state == AG.UNVERIFIED


# --------------------------------------------------------------------------- FrameHub
class FakeSource(F.FrameSource):
    def __init__(self, frames=3, fail_open=None):
        self.n, self.fail_open, self.opened, self.closed, self.i = frames, fail_open, False, False, 0

    def open(self):
        if self.fail_open:
            raise self.fail_open
        self.opened = True

    def read(self):
        if self.i >= self.n:
            time.sleep(0.01)
            return None
        self.i += 1
        from aot.utils.timekit import utc_now
        return F.Frame(utc_now(), self.i, JPEG + bytes([self.i]))

    def close(self):
        self.closed = True


def _wait(cond, t=3.0):
    end = time.time() + t
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.01)
    return False


def test_hub_fans_out_to_subscribers_and_stops_when_idle():
    got1, got2 = [], []
    hub = F.FrameHub(lambda: FakeSource(3), idle_stop_s=0.2, sleep=lambda s: time.sleep(0.01))
    hub.subscribe(lambda f: got1.append(f.seq))
    hub.subscribe(lambda f: got2.append(f.seq))
    assert _wait(lambda: len(got1) >= 3 and len(got2) >= 3)
    assert hub.latest().seq >= 3
    hub.stop()


def test_hub_fatal_error_stops_without_retry():
    opens = []

    def factory():
        opens.append(1)
        return FakeSource(fail_open=F.SourceError('auth:auth_failed', fatal=True))
    hub = F.FrameHub(factory, sleep=lambda s: time.sleep(0.01))
    hub.subscribe(lambda f: None)
    assert _wait(lambda: hub.dead_reason == 'auth:auth_failed')
    time.sleep(0.2)
    assert len(opens) == 1 and not hub.running
    # 죽은 허브는 레지스트리가 새로 만든다(사용자가 래치를 푼 뒤)
    h1 = F.get_hub('cam-dead', factory)
    h1.dead_reason = 'x'
    assert F.get_hub('cam-dead', factory) is not h1


def test_hub_retries_nonfatal_open_failures_with_backoff_delays():
    sleeps = []
    seq = iter([F.SourceError('open_failed'), F.SourceError('open_failed'), None])

    def factory():
        nxt = next(seq, None)
        return FakeSource(2, fail_open=nxt)
    hub = F.FrameHub(factory, retry_delays=(2, 5), sleep=lambda s: (sleeps.append(s), time.sleep(0.01)))
    got = []
    hub.subscribe(lambda f: got.append(1))
    assert _wait(lambda: len(got) >= 2)
    assert sleeps[:2] == [2, 5]
    hub.stop()


def test_latest_frame_file_atomic_rate_limited_and_freshness(tmp_path):
    t = [0.0]
    lf = F.LatestFrameFile('c1', directory=str(tmp_path), min_interval=1.0, monotonic=lambda: t[0])
    from aot.utils.timekit import utc_now
    lf(F.Frame(utc_now(), 1, b'one'))
    lf(F.Frame(utc_now(), 2, b'two'))                      # 1초 안: 건너뜀
    assert open(lf.path, 'rb').read() == b'one'
    t[0] = 1.5
    lf(F.Frame(utc_now(), 3, b'three'))
    assert open(lf.path, 'rb').read() == b'three'
    assert not [f for f in os.listdir(tmp_path) if f.endswith('.tmp')]
    assert F.LatestFrameFile.read_fresh('c1', directory=str(tmp_path)) == b'three'
    assert F.LatestFrameFile.read_fresh('c1', directory=str(tmp_path), now=lambda: time.time() + 10) is None
    assert F.LatestFrameFile.read_fresh('nope', directory=str(tmp_path)) is None


# --------------------------------------------------------------------------- 스냅샷
def test_snapshot_uses_fresh_frame_file_without_opening_a_connection(tmp_path):
    F.LatestFrameFile('c1', directory=str(tmp_path), min_interval=0)(
        F.Frame(__import__('aot.utils.timekit', fromlist=['utc_now']).utc_now(), 1, JPEG))

    def boom():
        raise AssertionError('must not open')
    assert snapshot.take_snapshot('c1', boom, directory=str(tmp_path)) == JPEG


def test_snapshot_opens_stream_once_and_closes(tmp_path):
    src = FakeSource(2)
    assert snapshot.take_snapshot('c2', lambda: src, directory=str(tmp_path)).startswith(b'\xff\xd8')
    assert src.opened and src.closed


def test_snapshot_refused_when_latched(tmp_path):
    def factory():
        return FakeSource(fail_open=F.SourceError('auth:latched:failed', fatal=True))
    with pytest.raises(snapshot.SnapshotError):
        snapshot.take_snapshot('c3', factory, directory=str(tmp_path))


# --------------------------------------------------------------------------- camera_record
def test_camera_record_vigi_branch_writes_snapshot(tmp_path, monkeypatch):
    from aot.camera_drivers import runtime
    from aot.config import AOT_DB_PATH
    from aot.databases.models import Camera
    from aot.databases.utils import session_scope
    from aot.devices.camera import camera_record
    cid = str(uuid.uuid4())
    with session_scope(AOT_DB_PATH) as s:
        s.add(Camera(unique_id=cid, name='rec-' + cid[:6], library='vigi', camera_type='vigi',
                     path_still=str(tmp_path), output_duration=0))
    monkeypatch.setattr(runtime, 'snapshot_jpeg', lambda uid, **kw: JPEG)
    path, filename = camera_record('photo', cid)
    assert os.path.isfile(os.path.join(path, filename)) or os.path.isfile(os.path.join(str(tmp_path), filename))
    assert open(os.path.join(str(tmp_path), filename), 'rb').read() == JPEG
