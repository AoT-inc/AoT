# coding=utf-8
"""IP 카메라 경량 방식(ip_snapshot)과 접속 재시도·종료·로그 마스킹 회귀."""
import ast
import pathlib
import threading
import time
from types import SimpleNamespace
from unittest import mock

import pytest

from aot.aot_flask.camera import base_camera, camera_ip_camera, camera_ip_snapshot
from aot.aot_flask.camera.base_camera import BaseCamera
from aot.aot_flask.camera.net_auth import (
    RetryBackoff, SnapshotAuthError, SnapshotError, build_stream_url,
    fetch_snapshot, is_jpeg, redact_url)

JPEG = b'\xff\xd8\xff\xe0fakejpeg\xff\xd9'
ROOT = pathlib.Path(__file__).resolve().parents[1]


# --- URL / 마스킹 / 백오프 -------------------------------------------------

def test_build_stream_url_encodes_special_characters():
    url = build_stream_url('rtsp://10.0.0.5:554/stream2', 'aot', 'p@ss:w/rd')
    from urllib.parse import urlparse, unquote
    p = urlparse(url)
    assert p.hostname == '10.0.0.5' and p.port == 554
    assert unquote(p.password) == 'p@ss:w/rd'


def test_build_stream_url_keeps_existing_credentials_and_no_user():
    assert build_stream_url('rtsp://a:b@h/x', 'u', 'p') == 'rtsp://a:b@h/x'
    assert build_stream_url('rtsp://h/x', '', 'p') == 'rtsp://h/x'


def test_redact_url_hides_password_only():
    out = redact_url('rtsp://aot:secret@10.0.0.5:554/stream2')
    assert 'secret' not in out and 'aot' in out and ':554' in out
    assert redact_url('rtsp://10.0.0.5/x') == 'rtsp://10.0.0.5/x'
    assert redact_url(None) is None


def test_backoff_grows_caps_and_resets_with_longer_auth_start():
    b = RetryBackoff()
    assert [b.next_delay() for _ in range(8)] == [5, 10, 20, 40, 80, 160, 300, 300]
    b.reset()
    assert b.next_delay() == 5
    a = RetryBackoff()
    assert a.next_delay(auth=True) == 60
    assert [a.next_delay(auth=True) for _ in range(6)][-1] == 900


# --- fetch_snapshot -------------------------------------------------------

def _resp(status, content=b'', www=''):
    headers = {'WWW-Authenticate': www} if www else {}
    return SimpleNamespace(status_code=status, content=content, headers=headers, close=lambda: None)


def test_fetch_snapshot_ok_without_auth():
    session = mock.Mock()
    session.get.return_value = _resp(200, JPEG)
    assert fetch_snapshot('http://h/s.jpg', session=session) == JPEG


def test_fetch_snapshot_falls_back_from_basic_to_digest():
    session = mock.Mock()
    session.get.side_effect = [_resp(401, www='Digest realm="x", nonce="n"'), _resp(200, JPEG)]
    assert fetch_snapshot('http://h/s.jpg', 'u', 'p', session=session) == JPEG
    kinds = [type(c.kwargs['auth']).__name__ for c in session.get.call_args_list]
    assert kinds == ['HTTPBasicAuth', 'HTTPDigestAuth']


def test_fetch_snapshot_basic_only_camera_gets_one_attempt_on_401():
    session = mock.Mock()
    session.get.return_value = _resp(401, www='Basic realm="x"')
    with pytest.raises(SnapshotAuthError):
        fetch_snapshot('http://h/s.jpg', 'u', 'p', session=session)
    assert session.get.call_count == 1


def test_fetch_snapshot_403_is_not_retried():
    session = mock.Mock()
    session.get.return_value = _resp(403, www='Digest realm="x"')
    with pytest.raises(SnapshotAuthError):
        fetch_snapshot('http://h/s.jpg', 'u', 'p', session=session)
    assert session.get.call_count == 1


def test_auth_latch_follows_credentials():
    from aot.aot_flask.camera.net_auth import (
        clear_auth_latch, credential_fingerprint, is_auth_latched, latch_auth_failure)
    fp = credential_fingerprint('http://h/s', 'u', 'old')
    assert not is_auth_latched('cam-x', fp)
    latch_auth_failure('cam-x', fp)
    assert is_auth_latched('cam-x', fp)
    # 비밀번호를 바꾸면 래치가 풀린다
    assert not is_auth_latched('cam-x', credential_fingerprint('http://h/s', 'u', 'new'))
    assert not is_auth_latched('cam-x', fp)
    latch_auth_failure('cam-x', fp)
    clear_auth_latch('cam-x')
    assert not is_auth_latched('cam-x', fp)


def test_http_auth_rejected_classifies_without_false_positives():
    from aot.aot_flask.camera.net_auth import http_auth_rejected
    with mock.patch('requests.get') as get:
        get.return_value = _resp(401, www='Basic realm="x"')
        assert http_auth_rejected('http://h/v', 'u', 'p') is True
        assert get.call_count == 1
        get.reset_mock()
        get.return_value = _resp(200)
        assert http_auth_rejected('http://h/v', 'u', 'p') is False
        import requests
        get.side_effect = requests.ConnectionError('x')
        assert http_auth_rejected('http://h/v', 'u', 'p') is False
    assert http_auth_rejected('rtsp://h/v', 'u', 'p') is False  # rtsp 는 판정하지 않는다
    assert http_auth_rejected('http://h/v', '', '') is False


def test_fetch_snapshot_auth_rejected_raises_auth_error():
    session = mock.Mock()
    session.get.return_value = _resp(401)
    with pytest.raises(SnapshotAuthError):
        fetch_snapshot('http://h/s.jpg', 'u', 'p', session=session)


def test_fetch_snapshot_rejects_non_jpeg_and_http_errors():
    session = mock.Mock()
    session.get.return_value = _resp(200, b'<html>login</html>')
    with pytest.raises(SnapshotError):
        fetch_snapshot('http://h/s.jpg', session=session)
    session.get.return_value = _resp(500)
    with pytest.raises(SnapshotError):
        fetch_snapshot('http://h/s.jpg', session=session)
    assert is_jpeg(JPEG) and not is_jpeg(b'')


def test_fetch_snapshot_error_message_has_no_credentials():
    import requests
    session = mock.Mock()
    session.get.side_effect = requests.ConnectionError('http://u:SECRET@h/x refused')
    with pytest.raises(SnapshotError) as exc:
        fetch_snapshot('http://u:SECRET@h/x', session=session)
    assert 'SECRET' not in str(exc.value)


# --- BaseCamera 종료 규칙 -------------------------------------------------

@pytest.fixture
def cam_id():
    uid = 'test-cam-%d' % time.time_ns()
    BaseCamera.running[uid] = True
    BaseCamera.last_access[uid] = time.time()
    BaseCamera.thread[uid] = None
    BaseCamera.event[uid] = base_camera.CameraEvent()
    yield uid
    for d in (BaseCamera.running, BaseCamera.last_access, BaseCamera.thread, BaseCamera.event):
        d.pop(uid, None)


def test_should_stop_conditions(cam_id):
    assert BaseCamera.should_stop(cam_id) is False
    BaseCamera.last_access[cam_id] = time.time() - 11
    assert BaseCamera.should_stop(cam_id) is True
    BaseCamera.last_access[cam_id] = time.time()
    BaseCamera.stop(cam_id)
    assert BaseCamera.should_stop(cam_id) is True


def test_sleep_unless_stopped_returns_early(cam_id):
    threading.Timer(0.3, BaseCamera.stop, args=(cam_id,)).start()
    t0 = time.time()
    assert BaseCamera.sleep_unless_stopped(cam_id, 30) is True
    assert time.time() - t0 < 3


class _NeverOpens:
    def __init__(self, *_a, **_k):
        pass

    def isOpened(self):
        return False

    def release(self):
        pass


def _settings(**kw):
    base = dict(is_activated=True, url_stream='rtsp://10.0.0.5:554/stream2',
                url_still='http://10.0.0.5/snap.jpg', auth_username='aot',
                auth_password='pw', stream_fps=5, custom_options='', json_headers='')
    base.update(kw)
    return SimpleNamespace(**base)


def test_ip_camera_retry_loop_ends_when_stopped_even_if_never_opened(cam_id, monkeypatch):
    """(d) 한 번도 열리지 않는 카메라도 stop() 으로 스레드가 끝나야 한다."""
    monkeypatch.setattr(camera_ip_camera, 'load_camera_settings',
                        lambda uid, fallback=None: _settings())
    monkeypatch.setattr(camera_ip_camera.cv2, 'VideoCapture', _NeverOpens)
    t = threading.Thread(target=BaseCamera._thread.__func__, args=(camera_ip_camera.Camera, cam_id))
    t.start()
    time.sleep(0.5)
    assert t.is_alive()
    BaseCamera.stop(cam_id)
    t.join(timeout=5)
    assert not t.is_alive()
    assert BaseCamera.thread[cam_id] is None


def test_ip_camera_retry_loop_ends_on_idle(cam_id, monkeypatch):
    monkeypatch.setattr(camera_ip_camera, 'load_camera_settings',
                        lambda uid, fallback=None: _settings())
    monkeypatch.setattr(camera_ip_camera.cv2, 'VideoCapture', _NeverOpens)
    BaseCamera.last_access[cam_id] = time.time() - 11
    gen = camera_ip_camera.Camera.frames(cam_id)
    assert list(gen) == []


def test_ip_camera_stops_when_deactivated_or_password_missing(cam_id, monkeypatch):
    opened = []

    class Spy(_NeverOpens):
        def __init__(self, *a, **k):
            opened.append(a)

    monkeypatch.setattr(camera_ip_camera.cv2, 'VideoCapture', Spy)
    for s in (_settings(is_activated=False), _settings(auth_password='')):
        monkeypatch.setattr(camera_ip_camera, 'load_camera_settings',
                            lambda uid, fallback=None, s=s: s)
        assert list(camera_ip_camera.Camera.frames(cam_id)) == []
    assert opened == []


def test_ip_camera_rereads_settings_on_each_reconnect(cam_id, monkeypatch):
    """(a) 재접속마다 설정을 다시 읽는다."""
    urls = []

    class Rec(_NeverOpens):
        def __init__(self, url):
            urls.append(url)

    seq = iter([_settings(auth_password='old'), _settings(auth_password='new')])
    monkeypatch.setattr(camera_ip_camera, 'load_camera_settings',
                        lambda uid, fallback=None: next(seq))
    monkeypatch.setattr(camera_ip_camera.cv2, 'VideoCapture', Rec)
    monkeypatch.setattr(BaseCamera, 'sleep_unless_stopped',
                        classmethod(lambda cls, uid, sec: False))
    gen = camera_ip_camera.Camera.frames(cam_id)
    next(gen)  # 첫 실패 후 None 하트비트
    next(gen)
    assert 'old' in urls[0] and 'new' in urls[1]


def test_camera_options_are_kept_per_camera():
    for mod in (camera_ip_camera, camera_ip_snapshot):
        mod.Camera.set_camera_options(SimpleNamespace(unique_id='a'))
        mod.Camera.set_camera_options(SimpleNamespace(unique_id='b'))
        assert {'a', 'b'} <= set(mod.Camera.camera_options)


# --- ip_snapshot 중계 -----------------------------------------------------

def test_snapshot_relay_yields_jpeg_unchanged_and_stops_on_auth_error(cam_id, monkeypatch):
    monkeypatch.setattr(camera_ip_snapshot, 'load_camera_settings',
                        lambda uid, fallback=None: _settings())
    calls = []

    def fake_fetch(url, *a, **k):
        calls.append(url)
        if len(calls) == 1:
            return JPEG
        raise SnapshotAuthError('no')

    monkeypatch.setattr(camera_ip_snapshot, 'fetch_snapshot', fake_fetch)
    monkeypatch.setattr(BaseCamera, 'sleep_unless_stopped',
                        classmethod(lambda cls, uid, sec: False))
    assert list(camera_ip_snapshot.Camera.frames(cam_id)) == [JPEG]
    assert len(calls) == 2  # 401 이후에는 더 두드리지 않는다


def test_snapshot_relay_backs_off_on_failure_and_ends_when_stopped(cam_id, monkeypatch):
    monkeypatch.setattr(camera_ip_snapshot, 'load_camera_settings',
                        lambda uid, fallback=None: _settings())
    monkeypatch.setattr(camera_ip_snapshot, 'fetch_snapshot',
                        mock.Mock(side_effect=SnapshotError('down')))
    delays = []

    def sleeper(cls, uid, sec):
        delays.append(sec)
        return len(delays) >= 3

    monkeypatch.setattr(BaseCamera, 'sleep_unless_stopped', classmethod(sleeper))
    assert list(camera_ip_snapshot.Camera.frames(cam_id)) == [None, None]
    assert delays == [5, 10, 20]


def test_snapshot_relay_makes_no_request_when_nobody_watches(cam_id, monkeypatch):
    fetch = mock.Mock(return_value=JPEG)
    monkeypatch.setattr(camera_ip_snapshot, 'fetch_snapshot', fetch)
    monkeypatch.setattr(camera_ip_snapshot, 'load_camera_settings',
                        lambda uid, fallback=None: _settings())
    BaseCamera.last_access[cam_id] = time.time() - 60
    assert list(camera_ip_snapshot.Camera.frames(cam_id)) == []
    fetch.assert_not_called()


# --- 비활성화·삭제가 스레드에 전달된다 (소스 고정) -------------------------

def test_deactivate_delete_and_mod_stop_the_stream_thread():
    tree = ast.parse((ROOT / 'aot_flask/utils/utils_camera.py').read_text())
    funcs = {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}
    for name in ('camera_mod', 'camera_deactivate', 'camera_delete'):
        calls = [c.func.id for c in ast.walk(funcs[name])
                 if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)]
        assert '_stop_stream' in calls, name


# --- 로그에 비밀번호가 새지 않는다 (소스 고정) ----------------------------

@pytest.mark.parametrize('rel', ['aot_flask/camera/camera_ip_camera.py',
                                 'aot_flask/camera/camera_ip_snapshot.py'])
def test_logging_calls_never_pass_raw_urls(rel):
    tree = ast.parse((ROOT / rel).read_text())
    bad = []
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr in ('debug', 'info', 'warning', 'error', 'exception')):
            for arg in node.args[1:]:
                names = {n.id for n in ast.walk(arg) if isinstance(n, ast.Name)}
                wrapped = isinstance(arg, ast.Call) and getattr(arg.func, 'id', '') == 'redact_url'
                if names & {'stream_url', 'url', 'raw_url'} and not wrapped:
                    bad.append((node.lineno, sorted(names)))
    assert not bad, bad


# --- camera_record 의 ip_snapshot 분기 -----------------------------------

def _record(tmp_path, monkeypatch, settings, fetch):
    from aot.devices import camera as dev
    monkeypatch.setattr(dev, 'PATH_CAMERAS', str(tmp_path))
    monkeypatch.setattr(dev, 'db_retrieve_table_daemon', lambda *a, **k: settings)
    monkeypatch.setattr(dev, 'fetch_snapshot', fetch)
    monkeypatch.setattr(dev, 'set_user_grp', lambda *a, **k: None)
    monkeypatch.setattr(dev, 'session_scope', mock.MagicMock())
    return dev.camera_record('photo', 'cam-1')


def _rec_settings(path, **kw):
    base = dict(unique_id='cam-1', id=1, name='c', path_still=str(path), output_id=None,
                output_duration=0, library='ip_snapshot', hflip=False, vflip=False,
                rotation=0, json_headers='', custom_options='')
    base.update(kw)
    return _settings(**base)


def test_camera_record_ip_snapshot_writes_camera_bytes_unchanged(tmp_path, monkeypatch):
    import os
    path, name = _record(tmp_path, monkeypatch, _rec_settings(tmp_path),
                         mock.Mock(return_value=JPEG))
    assert open(os.path.join(path, name), 'rb').read() == JPEG


def test_camera_record_ip_snapshot_failure_returns_none(tmp_path, monkeypatch):
    path, name = _record(tmp_path, monkeypatch, _rec_settings(tmp_path),
                         mock.Mock(side_effect=SnapshotAuthError('no')))
    assert (path, name) == (None, None)


def test_camera_record_has_no_hand_rolled_credential_injection():
    src = (ROOT / 'devices/camera.py').read_text()
    assert 'f"{_username}:{_password}@' not in src


# --- 빠른 열기·유예 (rtsp_open, idle_grace) ---------------------------------

def test_open_capture_applies_options_only_during_open_and_restores(monkeypatch):
    import os
    from aot.aot_flask.camera import rtsp_open
    monkeypatch.delenv(rtsp_open.ENV_NAME, raising=False)
    monkeypatch.delenv(rtsp_open.OPTIONS_ENV, raising=False)
    seen = {}

    class FakeCv2:
        CAP_FFMPEG = 1900
        CAP_PROP_OPEN_TIMEOUT_MSEC = 53
        CAP_PROP_READ_TIMEOUT_MSEC = 54
        error = RuntimeError

        @staticmethod
        def VideoCapture(url, *rest):
            seen['env'] = os.environ.get(rtsp_open.ENV_NAME)
            seen['rest'] = rest
            return 'cap'

    assert rtsp_open.open_capture('rtsp://h/x', FakeCv2) == 'cap'
    assert 'rtsp_transport;tcp' in seen['env'] and 'analyzeduration' in seen['env']
    assert seen['rest'][0] == FakeCv2.CAP_FFMPEG and 53 in seen['rest'][1]
    assert rtsp_open.ENV_NAME not in os.environ  # 다른 열기에 새지 않는다


def test_open_capture_leaves_non_rtsp_and_operator_env_alone(monkeypatch):
    import os
    from aot.aot_flask.camera import rtsp_open
    calls = []

    class FakeCv2:
        CAP_FFMPEG = 1900
        CAP_PROP_OPEN_TIMEOUT_MSEC = 53
        CAP_PROP_READ_TIMEOUT_MSEC = 54
        error = RuntimeError

        @staticmethod
        def VideoCapture(url, *rest):
            calls.append((url, rest, os.environ.get(rtsp_open.ENV_NAME)))
            return 'cap'

    monkeypatch.delenv(rtsp_open.ENV_NAME, raising=False)
    rtsp_open.open_capture('http://h/stream.mjpg', FakeCv2)
    assert calls[-1] == ('http://h/stream.mjpg', (), None)
    monkeypatch.setenv(rtsp_open.ENV_NAME, 'operator;set')
    rtsp_open.open_capture('rtsp://h/x', FakeCv2)
    assert calls[-1][2] == 'operator;set'
    assert os.environ[rtsp_open.ENV_NAME] == 'operator;set'
    monkeypatch.delenv(rtsp_open.ENV_NAME)
    monkeypatch.setenv(rtsp_open.OPTIONS_ENV, '')  # 빈 값 = 끔
    rtsp_open.open_capture('rtsp://h/x', FakeCv2)
    assert calls[-1][2] is None


def test_open_capture_falls_back_when_opencv_lacks_timeout_params(monkeypatch):
    from aot.aot_flask.camera import rtsp_open

    class FakeCv2:
        CAP_FFMPEG = 1900
        CAP_PROP_OPEN_TIMEOUT_MSEC = 53
        CAP_PROP_READ_TIMEOUT_MSEC = 54
        error = RuntimeError

        @staticmethod
        def VideoCapture(url, *rest):
            if rest:
                raise TypeError('old opencv')
            return 'plain'

    assert rtsp_open.open_capture('rtsp://h/x', FakeCv2) == 'plain'


def test_idle_grace_extends_only_while_set(cam_id):
    BaseCamera.last_access[cam_id] = time.time() - 30
    assert BaseCamera.should_stop(cam_id) is True       # 기본 10초
    BaseCamera.idle_grace[cam_id] = 60
    assert BaseCamera.should_stop(cam_id) is False      # 연결 유지 중
    BaseCamera.last_access[cam_id] = time.time() - 61
    assert BaseCamera.should_stop(cam_id) is True
    BaseCamera.idle_grace.pop(cam_id)


class _FakeCapture:
    """프레임 3장 뒤 끊기는 가짜 캡처."""
    instances = []

    def __init__(self, *_a, **_k):
        self.n = 0
        self.released = False
        _FakeCapture.instances.append(self)

    def isOpened(self):
        return True

    def grab(self):
        self.n += 1
        return self.n <= 3

    def retrieve(self):
        import numpy as np
        return True, np.zeros((4, 4, 3), np.uint8)

    def release(self):
        self.released = True


def test_connected_stream_keeps_alive_then_grace_is_cleared_on_disconnect(cam_id, monkeypatch):
    monkeypatch.setattr(camera_ip_camera, 'load_camera_settings',
                        lambda uid, fallback=None: _settings(stream_fps=1000))
    monkeypatch.setattr(camera_ip_camera.cv2, 'VideoCapture', _FakeCapture)
    monkeypatch.setattr(camera_ip_camera, 'KEEP_ALIVE_SECONDS', 60)
    graces = []
    gen = camera_ip_camera.Camera.frames(cam_id)
    frame = next(gen)
    graces.append(BaseCamera.idle_grace.get(cam_id))
    assert frame[:2] == b'\xff\xd8' and graces == [60]
    BaseCamera.stop(cam_id)
    assert list(gen) == []
    assert cam_id not in BaseCamera.idle_grace      # 끊기면 기본 유예로 복귀
    assert _FakeCapture.instances[-1].released


def test_failing_connection_never_gets_the_long_grace(cam_id, monkeypatch):
    monkeypatch.setattr(camera_ip_camera, 'load_camera_settings',
                        lambda uid, fallback=None: _settings())
    monkeypatch.setattr(camera_ip_camera.cv2, 'VideoCapture', _NeverOpens)
    monkeypatch.setattr(BaseCamera, 'sleep_unless_stopped',
                        classmethod(lambda cls, uid, sec: False))
    gen = camera_ip_camera.Camera.frames(cam_id)
    next(gen)
    assert cam_id not in BaseCamera.idle_grace
    BaseCamera.last_access[cam_id] = time.time() - 11
    assert BaseCamera.should_stop(cam_id) is True   # 실패 중에는 10초 뒤 종료


def test_ip_camera_http_stream_latches_on_auth_rejection_and_does_not_reopen(cam_id, monkeypatch):
    from aot.aot_flask.camera import net_auth
    opened = []

    class Spy(_NeverOpens):
        def __init__(self, url):
            opened.append(url)

    settings = _settings(url_stream='http://10.0.0.5/video.mjpg')
    monkeypatch.setattr(camera_ip_camera, 'load_camera_settings', lambda uid, fallback=None: settings)
    monkeypatch.setattr(camera_ip_camera.cv2, 'VideoCapture', Spy)
    monkeypatch.setattr(camera_ip_camera, 'http_auth_rejected', lambda *a, **k: True)
    try:
        assert list(camera_ip_camera.Camera.frames(cam_id)) == []
        assert len(opened) == 1
        # 같은 자격 증명으로 다시 시청해도 열지 않는다
        assert list(camera_ip_camera.Camera.frames(cam_id)) == []
        assert len(opened) == 1
        # 설정 저장(래치 해제) 뒤에는 한 번 다시 시도한다
        net_auth.clear_auth_latch(cam_id)
        assert list(camera_ip_camera.Camera.frames(cam_id)) == []
        assert len(opened) == 2
    finally:
        net_auth.clear_auth_latch(cam_id)


def test_ip_camera_rtsp_failure_with_credentials_uses_auth_backoff(cam_id, monkeypatch):
    delays = []
    monkeypatch.setattr(camera_ip_camera, 'load_camera_settings', lambda uid, fallback=None: _settings())
    monkeypatch.setattr(camera_ip_camera.cv2, 'VideoCapture', _NeverOpens)
    monkeypatch.setattr(BaseCamera, 'sleep_unless_stopped',
                        classmethod(lambda cls, uid, sec: delays.append(sec) or False))
    gen = camera_ip_camera.Camera.frames(cam_id)
    next(gen)
    assert delays == [60]


def test_ip_snapshot_latches_after_one_rejection(cam_id, monkeypatch):
    from aot.aot_flask.camera import net_auth
    calls = []

    def reject(*a, **k):
        calls.append(1)
        raise SnapshotAuthError('no')

    monkeypatch.setattr(camera_ip_snapshot, 'load_camera_settings', lambda uid, fallback=None: _settings())
    monkeypatch.setattr(camera_ip_snapshot, 'fetch_snapshot', reject)
    try:
        assert list(camera_ip_snapshot.Camera.frames(cam_id)) == []
        assert list(camera_ip_snapshot.Camera.frames(cam_id)) == []
        assert len(calls) == 1
    finally:
        net_auth.clear_auth_latch(cam_id)


def test_latched_cameras_lists_with_timestamp():
    from aot.aot_flask.camera import net_auth
    net_auth.latch_auth_failure('cam-list', 'fp')
    try:
        got = net_auth.latched_cameras()
        assert 'cam-list' in got and got['cam-list'] > 0
        net_auth.clear_auth_latch('cam-list')
        assert 'cam-list' not in net_auth.latched_cameras()
    finally:
        net_auth.clear_auth_latch('cam-list')


def test_layout_polls_camera_auth_alerts_and_route_exists():
    layout = (ROOT / 'aot_flask/templates/layout.html').read_text(encoding='utf-8')
    routes = (ROOT / 'aot_flask/routes_general.py').read_text(encoding='utf-8')
    assert "'/camera_auth_alerts'" in layout
    assert "@blueprint.route('/camera_auth_alerts')" in routes
    # layout.html 은 서버 시작 때 update_layout() 이 layout_default.html(또는 DB 의
    # custom_layout)에서 다시 만든다 — 원본인 layout_default.html 에 없으면 재시작
    # 뒤 폴링이 사라져 토스트가 실배포에서 조용히 죽는다(2026-11-05 실측).
    layout_default = (ROOT / 'aot_flask/templates/layout_default.html').read_text(encoding='utf-8')
    assert "'/camera_auth_alerts'" in layout_default
