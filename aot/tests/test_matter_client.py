# coding=utf-8
"""Matter 서버 웹소켓 클라이언트(aot/devices/matter_client.py) 검사.

실제 matterjs-server 대신 같은 프로토콜을 말하는 가짜 서버를 unix socket 위에
띄운다. 지키는 것:
  - 접속 직후 ServerInfo → start_listening 스냅샷으로 캐시가 채워진다.
  - attribute_updated 이벤트가 캐시와 구독자에 반영된다. 스냅샷 직후에 온
    이벤트가 스냅샷에 덮이지 않는다(같은 스레드에서 순서대로 처리).
  - 명령의 성공·오류·시간초과가 각각 결과·MatterCommandError·MatterCommandTimeout.
  - 연결이 끊기면 대기 중인 명령이 즉시 실패하고, 서버가 돌아오면 다시 붙어
    스냅샷을 새로 받는다(P0 완료 기준).
  - 연결 전 명령은 기다리지 않고 MatterNotConnected.
  - 건강했던 연결이 끊기면 재접속 대기가 처음부터 다시 시작한다(서버를 여러 번
    재시작해도 대기가 계속 늘지 않는다).
  - 잘못된 이벤트 하나가 연결을 끊지 않는다.
  - 구독 콜백 안에서 명령을 보내면 시간초과까지 기다리지 않고 즉시 실패한다.
  - stop() 직후 ensure_started() 를 불러도 클라이언트가 죽은 채로 남지 않는다.
Docker·네트워크 없이 임시 폴더의 unix socket 으로만 돈다.
"""
import json
import os
import tempfile
import threading
import time

import pytest

websockets_server = pytest.importorskip('websockets.sync.server')

from aot.devices import matter_client as mc


SERVER_INFO = {
    'fabric_id': 1,
    'compressed_fabric_id': 1234,
    'schema_version': mc.CLIENT_SCHEMA_VERSION,
    'min_supported_schema_version': 5,
    'sdk_version': 'fake',
    'wifi_credentials_set': False,
    'thread_credentials_set': False,
    'bluetooth_enabled': False,
}


def _node(node_id, on=False):
    return {
        'node_id': node_id,
        'available': True,
        'is_bridge': False,
        'attributes': {'1/6/0': on, '0/40/3': 'Plug'},
    }


class FakeMatterServer:
    """Speaks just enough of the python-matter-server API for the client."""

    def __init__(self, path, nodes=None):
        self.path = path
        self.nodes = nodes if nodes is not None else [_node(5)]
        self.received = []
        self.connections = []
        self.after_listen = []      # events pushed right after the snapshot
        self.silent_commands = set()
        self._server = None
        self._thread = None

    def start(self):
        self._server = websockets_server.unix_serve(self._handler, self.path)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        return self

    def stop(self):
        for conn in list(self.connections):
            try:
                conn.close()
            except Exception:
                pass
        self._server.shutdown()
        self._thread.join(5)
        if os.path.exists(self.path):
            os.unlink(self.path)

    def push(self, event, data):
        for conn in list(self.connections):
            conn.send(json.dumps({'event': event, 'data': data}))

    def _handler(self, conn):
        self.connections.append(conn)
        try:
            conn.send(json.dumps(SERVER_INFO))
            for raw in conn:
                msg = json.loads(raw)
                self.received.append(msg)
                cmd, mid = msg['command'], msg['message_id']
                if cmd in self.silent_commands:
                    continue
                if cmd == 'start_listening':
                    conn.send(json.dumps({'message_id': mid, 'result': self.nodes}))
                    for event, data in self.after_listen:
                        conn.send(json.dumps({'event': event, 'data': data}))
                elif cmd == 'ping_node':
                    conn.send(json.dumps({'message_id': mid, 'result': {'ok': True}}))
                else:
                    conn.send(json.dumps({'message_id': mid, 'error_code': 9,
                                          'details': f'no such command {cmd}'}))
        except Exception:
            pass
        finally:
            self.connections.remove(conn)


@pytest.fixture
def sock_path():
    # AF_UNIX paths are limited to ~104 bytes on macOS; pytest's tmp_path is
    # too deep, so use a short private directory.
    d = tempfile.mkdtemp(prefix='mt')
    yield os.path.join(d, 's')
    try:
        os.rmdir(d)
    except OSError:
        pass


def _client(path):
    return mc.MatterServerClient(socket_path=path, connect_timeout=2,
                                 reconnect_min=0.05, reconnect_max=0.2)


def _wait(cond, timeout=3.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.01)
    return False


def test_snapshot_fills_cache(sock_path):
    server = FakeMatterServer(sock_path, nodes=[_node(5, on=True), _node(7)]).start()
    client = _client(sock_path)
    try:
        client.ensure_started()
        assert client.wait_ready(3)
        assert set(client.nodes()) == {5, 7}
        assert client.get_attribute(5, '1/6/0') is True
        assert client.get_attribute(99, '1/6/0', 'missing') == 'missing'
        status = client.status()
        assert status['connected'] and status['node_count'] == 2
        assert status['schema_version'] == mc.CLIENT_SCHEMA_VERSION
    finally:
        client.stop()
        server.stop()


def test_update_right_after_snapshot_is_not_lost(sock_path):
    server = FakeMatterServer(sock_path, nodes=[_node(5, on=False)])
    server.after_listen = [('attribute_updated', [5, '1/6/0', True])]
    server.start()
    client = _client(sock_path)
    try:
        client.ensure_started()
        assert client.wait_ready(3)
        assert _wait(lambda: client.get_attribute(5, '1/6/0') is True)
    finally:
        client.stop()
        server.stop()


def test_attribute_events_reach_cache_and_filtered_subscribers(sock_path):
    server = FakeMatterServer(sock_path, nodes=[_node(5), _node(7)]).start()
    client = _client(sock_path)
    seen_5, seen_all = [], []
    client.subscribe(lambda e, d: seen_5.append((e, d)), node_id=5)
    client.subscribe(lambda e, d: seen_all.append((e, d)))
    try:
        client.ensure_started()
        assert client.wait_ready(3)
        server.push('attribute_updated', [7, '1/6/0', True])
        server.push('attribute_updated', [5, '1/6/0', True])
        assert _wait(lambda: client.get_attribute(5, '1/6/0') is True)
        assert _wait(lambda: len([e for e in seen_all if e[0] == 'attribute_updated']) == 2)
        updates_5 = [d for e, d in seen_5 if e == 'attribute_updated']
        assert updates_5 == [[5, '1/6/0', True]]
        assert ('connected', None) in seen_5   # lifecycle reaches node subscribers

        server.push('node_removed', 7)
        assert _wait(lambda: 7 not in client.nodes())
        server.push('node_added', _node(9))
        assert _wait(lambda: 9 in client.nodes())
    finally:
        client.stop()
        server.stop()


def test_command_result_error_and_timeout(sock_path):
    server = FakeMatterServer(sock_path).start()
    server.silent_commands.add('interview_node')
    client = _client(sock_path)
    try:
        client.ensure_started()
        assert client.wait_ready(3)
        assert client.send_command('ping_node', {'node_id': 5}) == {'ok': True}

        with pytest.raises(mc.MatterCommandError) as err:
            client.send_command('bogus')
        assert err.value.error_code == 9

        started = time.monotonic()
        with pytest.raises(mc.MatterCommandTimeout):
            client.send_command('interview_node', {'node_id': 5}, timeout=0.3)
        assert time.monotonic() - started < 2
        assert client._pending == {}
    finally:
        client.stop()
        server.stop()


def test_not_connected_fails_fast(sock_path):
    client = _client(sock_path)   # nothing listening at sock_path
    try:
        started = time.monotonic()
        with pytest.raises(mc.MatterNotConnected):
            client.send_command('ping_node', {'node_id': 5})
        assert time.monotonic() - started < 0.5
        assert _wait(lambda: client.status()['last_error'] is not None)
    finally:
        client.stop()


def test_reconnects_after_server_restart(sock_path):
    server = FakeMatterServer(sock_path, nodes=[_node(5)]).start()
    client = _client(sock_path)
    events = []
    client.subscribe(lambda e, d: events.append(e))
    try:
        client.ensure_started()
        assert client.wait_ready(3)
        server.silent_commands.add('interview_node')
        hung = {}

        def call():
            try:
                client.send_command('interview_node', {'node_id': 5}, timeout=10)
            except Exception as err:  # noqa: BLE001
                hung['err'] = err

        t = threading.Thread(target=call)
        t.start()
        assert _wait(lambda: any(m['command'] == 'interview_node' for m in server.received))
        server.stop()

        # In-flight command fails promptly instead of waiting its 10s.
        t.join(3)
        assert isinstance(hung.get('err'), mc.MatterNotConnected)
        assert _wait(lambda: not client.is_connected())
        assert _wait(lambda: 'disconnected' in events)

        # Server comes back with a different node set.
        server = FakeMatterServer(sock_path, nodes=[_node(5), _node(8)]).start()
        assert _wait(client.is_connected, timeout=5)
        assert set(client.nodes()) == {5, 8}
        assert client.status()['connects'] == 2
        assert _wait(lambda: events.count('connected') == 2)
    finally:
        client.stop()
        server.stop()


def test_server_shutdown_event_triggers_reconnect(sock_path):
    server = FakeMatterServer(sock_path).start()
    client = _client(sock_path)
    try:
        client.ensure_started()
        assert client.wait_ready(3)
        server.push('server_shutdown', None)
        assert _wait(lambda: client.status()['connects'] == 2, timeout=5)
    finally:
        client.stop()
        server.stop()


def test_get_client_reads_environment(monkeypatch):
    monkeypatch.setattr(mc, '_client', None)
    monkeypatch.setenv('AOT_MATTER_SOCKET', '/tmp/x.sock')
    monkeypatch.delenv('AOT_MATTER_URL', raising=False)
    client = mc.get_client()
    assert client.endpoint == 'unix:/tmp/x.sock'
    assert mc.get_client() is client
    assert client._thread is None   # constructing never connects (C2)
    monkeypatch.setattr(mc, '_client', None)


def test_backoff_resets_after_a_healthy_session(sock_path, monkeypatch):
    """서버 재시작마다 대기가 두 배로 늘던 버그(검토 #1). 매번 스냅샷까지 받은
    세션이므로 대기는 항상 최소값 근처여야 한다."""
    waits = []
    server = FakeMatterServer(sock_path).start()
    client = mc.MatterServerClient(socket_path=sock_path, connect_timeout=2,
                                   reconnect_min=0.05, reconnect_max=5.0)
    real_wait = client._stop.wait

    def recording_wait(timeout=None):
        if timeout is not None:
            waits.append(timeout)
        return real_wait(timeout)

    monkeypatch.setattr(client._stop, 'wait', recording_wait)
    try:
        client.ensure_started()
        for n in range(1, 6):
            assert _wait(lambda: client.status()['connects'] == n, timeout=5)
            server.push('server_shutdown', {})
        assert _wait(lambda: client.status()['connects'] == 6, timeout=5)
        assert len(waits) >= 5
        assert max(waits) < 0.05 * 1.2 + 1e-6, waits
    finally:
        client.stop()
        server.stop()


def test_malformed_event_does_not_drop_the_session(sock_path):
    server = FakeMatterServer(sock_path, nodes=[_node(5)]).start()
    client = _client(sock_path)
    try:
        client.ensure_started()
        assert client.wait_ready(3)
        server.push('attribute_updated', None)
        server.push('node_added', {'no_node_id': True})
        for conn in server.connections:
            conn.send('not json')
        server.push('attribute_updated', [5, '1/6/0', True])
        assert _wait(lambda: client.get_attribute(5, '1/6/0') is True)
        assert client.status()['connects'] == 1
        assert client.is_connected()
    finally:
        client.stop()
        server.stop()


def test_send_command_from_callback_fails_fast(sock_path):
    server = FakeMatterServer(sock_path).start()
    client = _client(sock_path)
    outcome = {}

    def callback(event, data):
        if event == 'attribute_updated':
            started = time.monotonic()
            try:
                client.send_command('ping_node', {'node_id': 5}, timeout=2)
            except mc.MatterError as err:
                outcome['err'] = err
            outcome['elapsed'] = time.monotonic() - started

    client.subscribe(callback)
    try:
        client.ensure_started()
        assert client.wait_ready(3)
        server.push('attribute_updated', [5, '1/6/0', True])
        assert _wait(lambda: 'elapsed' in outcome)
        assert isinstance(outcome.get('err'), mc.MatterError)
        assert not isinstance(outcome['err'], mc.MatterCommandTimeout)
        assert outcome['elapsed'] < 0.5
        # The reader is still alive and serving other callers.
        assert client.send_command('ping_node', {'node_id': 5}) == {'ok': True}
    finally:
        client.stop()
        server.stop()


def test_error_names_the_command(sock_path):
    server = FakeMatterServer(sock_path).start()
    client = _client(sock_path)
    try:
        client.ensure_started()
        assert client.wait_ready(3)
        with pytest.raises(mc.MatterCommandError) as err:
            client.send_command('bogus')
        assert err.value.command == 'bogus'
    finally:
        client.stop()
        server.stop()


def test_reply_that_landed_survives_disconnect():
    """응답이 이미 도착한 명령은 직후 연결이 끊겨도 성공으로 남는다(검토 #6)."""
    client = _client('/nonexistent')
    pending = mc._Pending('device_command')
    pending.result = {'ok': True}
    pending.event.set()
    client._pending['1'] = pending
    client._on_disconnect()
    assert pending.error is None and pending.result == {'ok': True}


def test_restart_right_after_stop_keeps_a_live_thread(sock_path):
    server = FakeMatterServer(sock_path).start()
    client = _client(sock_path)
    try:
        client.ensure_started()
        assert client.wait_ready(3)
        client.stop(timeout=0)       # don't wait for the thread to exit
        client.ensure_started()
        assert _wait(lambda: client._thread is not None and client._thread.is_alive())
        assert _wait(client.is_connected, timeout=5)
    finally:
        client.stop()
        server.stop()


def test_missing_websockets_is_reported_not_fatal(monkeypatch):
    """의존성이 빠진 옛 이미지에서 리더 스레드가 말없이 죽던 것(E2E)."""
    import builtins
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name.startswith('websockets'):
            raise ImportError('No module named websockets')
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, '__import__', fake_import)
    client = mc.MatterServerClient(socket_path='/nonexistent')
    client.ensure_started()
    assert _wait(lambda: client._thread is None)
    assert 'websockets is not installed' in client.status()['last_error']
