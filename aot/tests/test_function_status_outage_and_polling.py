# coding=utf-8
"""함수 상태 위젯 폴링의 장애·낭비 방어 (2026-11-11 점검 6·7·5번).

  6. 데몬이 멈췄거나 느릴 때(전송 실패) 폴링마다 RPC 를 다시 걸지 않는다 —
     `DaemonControl.function_status` 가 실패를 짧게 기억한다. 함수별 키이고, 데몬이 응답한
     `{'error': [...]}` 는 캐시하지 않는다.
  7. 시퀀스가 아닌 함수(Conditional·PID·env_coordinator)의 정상 응답은 `'error': []` 키를
     달고 있는데, 예전 조건 `'error' in data` 가 그것을 오류로 보고 폴링마다 Trigger 정적
     조회를 했다.
  5. RPC 시간 상한 캐시(`_rpc_timeout_cache`)는 만료한다 — 설정을 바꿔도 워커가 옛 값을
     계속 쓰던 결함.
"""
import json
from types import SimpleNamespace
from unittest import mock

import Pyro5.errors
import pytest

from aot import aot_client
from aot.aot_client import DaemonControl


# ── 공통 ─────────────────────────────────────────────────────────────────────
class _Clock:
    """`time.monotonic` 대역 — 테스트가 시간을 직접 흘린다."""

    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


@pytest.fixture
def clock():
    c = _Clock()
    with mock.patch.object(aot_client.time, 'monotonic', c):
        yield c


@pytest.fixture(autouse=True)
def _clean_class_state():
    DaemonControl._function_status_fail = {}
    DaemonControl._rpc_timeout_cache = {}
    yield
    DaemonControl._function_status_fail = {}
    DaemonControl._rpc_timeout_cache = {}


def _client(proxy):
    ctrl = DaemonControl.__new__(DaemonControl)
    ctrl.pyro_timeout = 8
    ctrl.uri = 'PYRO:unreachable@127.0.0.1:1'
    ctrl.proxy = lambda *a, **kw: proxy
    return ctrl


class _Proxy:
    def __init__(self, behaviour):
        self.calls = []
        self.behaviour = behaviour

    def function_status(self, function_id):
        self.calls.append(function_id)
        result = self.behaviour(function_id)
        if isinstance(result, Exception):
            raise result
        return result


# ── 6. 전송 실패 캐시 ─────────────────────────────────────────────────────────
def test_timeout_is_remembered_and_polls_do_not_redial(clock):
    proxy = _Proxy(lambda _id: Pyro5.errors.TimeoutError('receiving: timeout'))
    ctrl = _client(proxy)
    for _ in range(5):                       # 폴링 5번
        with pytest.raises(Pyro5.errors.TimeoutError, match='receiving: timeout'):
            ctrl.function_status('f-1')
    assert proxy.calls == ['f-1']            # 데몬에는 한 번만 닿았다


def test_retries_after_the_ttl_and_recovers(clock):
    state = {'down': True}
    proxy = _Proxy(lambda _id: Pyro5.errors.CommunicationError('refused')
                   if state['down'] else {'string_status': 'ok', 'error': []})
    ctrl = _client(proxy)
    with pytest.raises(Pyro5.errors.CommunicationError):
        ctrl.function_status('f-1')
    clock.now += DaemonControl._FUNCTION_STATUS_FAIL_TTL - 0.1
    with pytest.raises(Pyro5.errors.CommunicationError):
        ctrl.function_status('f-1')
    assert len(proxy.calls) == 1
    state['down'] = False
    clock.now += 0.2                         # TTL 경과 → 다시 시도
    assert ctrl.function_status('f-1')['string_status'] == 'ok'
    assert len(proxy.calls) == 2
    ctrl.function_status('f-1')              # 성공했으므로 실패 기록은 지워졌다
    assert len(proxy.calls) == 3


def test_failure_of_one_function_does_not_block_another(clock):
    proxy = _Proxy(lambda fid: Pyro5.errors.TimeoutError('slow')
                   if fid == 'slow' else {'string_status': fid, 'error': []})
    ctrl = _client(proxy)
    with pytest.raises(Pyro5.errors.TimeoutError):
        ctrl.function_status('slow')
    assert ctrl.function_status('fine')['string_status'] == 'fine'
    assert ctrl.function_status('fine')['string_status'] == 'fine'
    assert proxy.calls == ['slow', 'fine', 'fine']    # 정상 함수는 캐시되지 않는다


def test_daemon_replies_and_other_errors_are_not_cached(clock):
    replies = iter([{'error': ['Function ID not found.']},
                    {'error': ['Function ID not found.']}])
    proxy = _Proxy(lambda _id: next(replies))
    ctrl = _client(proxy)
    ctrl.function_status('f-1')
    ctrl.function_status('f-1')
    assert len(proxy.calls) == 2             # 응답은 응답일 뿐 — 캐시하지 않는다

    boom = _Proxy(lambda _id: ValueError('bug'))
    ctrl = _client(boom)
    for _ in range(2):
        with pytest.raises(ValueError):
            ctrl.function_status('f-1')
    assert len(boom.calls) == 2              # 전송 실패가 아닌 예외도 캐시하지 않는다


def test_expired_failure_entries_are_pruned(clock):
    proxy = _Proxy(lambda _id: Pyro5.errors.TimeoutError('t'))
    ctrl = _client(proxy)
    for fid in ('a', 'b', 'c'):
        with pytest.raises(Pyro5.errors.TimeoutError):
            ctrl.function_status(fid)
    clock.now += 100
    with pytest.raises(Pyro5.errors.TimeoutError):
        ctrl.function_status('d')
    assert set(DaemonControl._function_status_fail) == {'d'}


# ── 7. 라우트: 시퀀스일 때만 정적 상태를 조회 ──────────────────────────────────
@pytest.fixture
def app(tmp_path):
    from aot.aot_flask.app import create_app
    from aot.aot_flask.extensions import db
    from aot.config import ProdConfig

    class _Config(ProdConfig):
        SQLALCHEMY_DATABASE_URI = f"sqlite:///{tmp_path / 'fsw_route.db'}"
        TESTING = True

    application = create_app(config=_Config)
    with application.app_context():
        db.create_all()
    yield application
    with application.app_context():
        db.session.remove()


def _poll(app, daemon_reply, static_reply=None):
    from aot.aot_flask import routes_function as rf
    static = mock.Mock(return_value=static_reply or {'error': ['Trigger x not found']})
    view = rf.function_status_activated.__wrapped__
    with app.test_request_context('/function_status_activated/x-1'):
        with mock.patch.object(rf, 'DaemonControl') as daemon, \
                mock.patch('aot.utils.sequence_status.static_status', static):
            if isinstance(daemon_reply, Exception):
                daemon.return_value.function_status.side_effect = daemon_reply
            else:
                daemon.return_value.function_status.return_value = daemon_reply
            response = view('x-1')
    return response.get_json(), static


@pytest.mark.parametrize('reply', [
    {'status_facts': {'kind': 'conditional', 'is_activated': True, 'period_s': 60,
                      'last_run_age_s': 5.0, 'action_fired': False, 'next_check_s': 55.0},
     'error': []},
    {'string_status': 'PID', 'error': []},
    {'status_facts': {'kind': 'env_coordinator', 'paused': None, 'summary': None,
                      'age_s': None}, 'error': []},
    {'string_status': 'user code returned no error key'},
])
def test_non_sequence_status_does_not_query_the_sequence_table(app, reply):
    data, static = _poll(app, reply)
    assert static.call_count == 0
    assert 'string_status' in data


def test_empty_error_list_is_not_an_error(app):
    data, static = _poll(app, {'string_status': 'x', 'error': []})
    assert static.call_count == 0 and data['error'] == []


def test_sequence_without_steps_is_still_merged_with_static_steps(app):
    reply = {'status_facts': {'kind': 'sequence', 'state': 'initializing'},
             'status_text': 'Initializing'}
    data, static = _poll(app, reply, {'steps': [{'unique_id': 'a1'}]})
    assert static.call_count == 1
    assert [step['unique_id'] for step in data['steps']] == ['a1']


@pytest.mark.parametrize('reply', [
    {'error': ['Function ID not found. Is the Function activated?']},
    None,
    {},
])
def test_daemon_failure_still_tries_the_static_sequence_status(app, reply):
    static_reply = {'steps': [{'unique_id': 'a1'}], 'status_facts': {'kind': 'sequence',
                                                                    'state': 'idle'}}
    data, static = _poll(app, reply, static_reply)
    assert static.call_count == 1
    assert [s['unique_id'] for s in data['steps']] == ['a1']


# ── 5. RPC 시간 상한 캐시 만료 ────────────────────────────────────────────────
def test_rpc_timeout_cache_follows_a_settings_change_after_the_ttl(clock):
    misc = SimpleNamespace(rpyc_timeout=3)
    with mock.patch.object(aot_client, 'db_retrieve_table_daemon', side_effect=lambda *a, **k: misc):
        assert DaemonControl().pyro_timeout == 3
        misc.rpyc_timeout = 9                       # 설정 화면에서 바꿈
        clock.now += DaemonControl._RPC_TIMEOUT_CACHE_TTL - 1
        assert DaemonControl().pyro_timeout == 3    # TTL 안에서는 DB 를 다시 읽지 않는다
        clock.now += 2
        assert DaemonControl().pyro_timeout == 9    # TTL 이 지나면 수렴한다


def test_rpc_timeout_cache_still_avoids_a_db_read_per_instance(clock):
    misc = SimpleNamespace(rpyc_timeout=5)
    read = mock.Mock(return_value=misc)
    with mock.patch.object(aot_client, 'db_retrieve_table_daemon', read):
        for _ in range(10):
            DaemonControl()
    assert read.call_count == 1
