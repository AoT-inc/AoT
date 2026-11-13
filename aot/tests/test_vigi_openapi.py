# coding=utf-8
"""VIGI Open API 클라이언트 × 모의 서버 — 인증 보호 계약 (설계 §6, §10.1).

핵심 판정 기준은 모의 서버가 본 시도 횟수다: 카메라에 틀린 자격 증명이 두 번 가는 경로가 없어야 한다.
"""
import http.client
import json
import logging
import sqlite3
import ssl
import threading
import time
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from aot.camera_drivers import auth_guard as AG
from aot.camera_drivers.auth_guard import AuthGuard, AuthRecord, AuthStore, InMemoryAuthStore
from aot.camera_drivers.driver import CamState, Credential, ErrorClass
from aot.camera_drivers.vigi import capability_map as CM
from aot.camera_drivers.vigi.openapi import VigiOpenApi
from aot.tests.fixtures.vigi_mock import MockVigiServer

KEY = b'unit-test-fp-key'
GOOD = 'correct-horse-battery'
BAD = 'definitely-wrong-pw-123'
T0 = datetime(2026, 11, 4, 12, 0, tzinfo=timezone.utc)


class Clock:
    def __init__(self):
        self.now = T0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += timedelta(seconds=seconds)


class SqliteAuthStore(AuthStore):
    """P2 의 DB 구현과 같은 compare-and-set 문장을 쓰는 시험용 저장소.
    호출마다 새 연결을 열어 서로 다른 프로세스/세션을 흉내 낸다."""

    def __init__(self, path):
        self.path = path
        c = self._c()
        c.execute('CREATE TABLE IF NOT EXISTS cd (camera_id TEXT PRIMARY KEY, auth_state TEXT,'
                  ' credential_fp TEXT, verified_fp TEXT, lease TEXT, iface TEXT, code INT, at TEXT)')
        c.commit()
        c.close()

    def _c(self):
        return sqlite3.connect(self.path, timeout=10, isolation_level=None)

    @staticmethod
    def _ts(d):
        return d.isoformat() if d else None

    def _ensure(self, c, cid):
        c.execute("INSERT OR IGNORE INTO cd (camera_id, auth_state) VALUES (?, 'unverified')", (cid,))

    def load(self, camera_id):
        c = self._c()
        try:
            self._ensure(c, camera_id)
            r = c.execute('SELECT auth_state, credential_fp, verified_fp, lease, iface, code, at'
                          ' FROM cd WHERE camera_id=?', (camera_id,)).fetchone()
        finally:
            c.close()
        f = lambda s: datetime.fromisoformat(s) if s else None  # noqa: E731
        return AuthRecord(r[0], r[1], r[2], f(r[3]), r[4] or '', r[5], f(r[6]))

    def acquire_lease(self, camera_id, fp, now, until):
        c = self._c()
        try:
            self._ensure(c, camera_id)
            cur = c.execute(
                "UPDATE cd SET lease=? WHERE camera_id=? AND auth_state NOT IN "
                "('failed','locked','cert_changed') AND (verified_fp IS NULL OR verified_fp != ?) "
                "AND (lease IS NULL OR lease < ?)",
                (self._ts(until), camera_id, fp, self._ts(now)))
            return cur.rowcount == 1
        finally:
            c.close()

    def _upd(self, camera_id, sql, args):
        c = self._c()
        try:
            self._ensure(c, camera_id)
            c.execute(sql, args + (camera_id,))
        finally:
            c.close()

    def mark_verified(self, camera_id, fp, now):
        self._upd(camera_id, "UPDATE cd SET auth_state='ok', verified_fp=?, credential_fp=?,"
                  " lease=NULL, iface='', code=NULL, at=NULL WHERE camera_id=?", (fp, fp))

    def mark_latched(self, camera_id, state, iface, code, now):
        self._upd(camera_id, 'UPDATE cd SET auth_state=?, iface=?, code=?, at=?, lease=NULL'
                  ' WHERE camera_id=?', (state, iface, code, self._ts(now)))

    def release_lease(self, camera_id):
        self._upd(camera_id, 'UPDATE cd SET lease=NULL WHERE camera_id=?', ())

    def set_state(self, camera_id, state):
        self._upd(camera_id, 'UPDATE cd SET auth_state=?, lease=NULL WHERE camera_id=?', (state,))

    def reset_credentials(self, camera_id, new_fp):
        self._upd(camera_id, "UPDATE cd SET credential_fp=?, auth_state='unverified', lease=NULL,"
                  " iface='', code=NULL, at=NULL WHERE camera_id=?", (new_fp,))

    def clear_latch(self, camera_id):
        self._upd(camera_id, "UPDATE cd SET auth_state='unverified', lease=NULL, iface='',"
                  " code=NULL, at=NULL WHERE camera_id=? AND auth_state IN"
                  " ('failed','locked','cert_changed','openapi_off')", ())


@pytest.fixture
def mock():
    with MockVigiServer() as m:
        yield m


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def store():
    return InMemoryAuthStore()


@pytest.fixture
def guard(store, clock):
    return AuthGuard(store, clock)


def make_client(mock, guard, password=GOOD, camera_id='cam1', username='admin', **kw):
    kw.setdefault('timeout', 5.0)
    return VigiOpenApi('127.0.0.1', Credential(username, password), camera_id=camera_id,
                       guard=guard, fp_key=KEY, port=mock.port, **kw)


def fp_of(password, username='admin'):
    return AG.credential_fp(username, password, KEY)


# ---------------------------------------------------------------------------
# 래치: 실패 1회면 모든 경로 중단
# ---------------------------------------------------------------------------
def test_wrong_password_latches_after_exactly_one_attempt(mock, guard, store):
    c = make_client(mock, guard, BAD)
    r = c.connect()
    assert r.state is CamState.FAILED and r.error_class is ErrorClass.AUTH_FAILED
    assert r.code == -10020
    assert store.load('cam1').auth_state == AG.FAILED
    # 이후 어떤 경로를 불러도 카메라에 아무것도 가지 않는다
    probes_before = mock.probe_count
    for _ in range(3):
        assert c.connect().state is CamState.REFUSED
        assert c.call('getModuleList').state is CamState.REFUSED
    other = make_client(mock, guard, BAD)       # 구독/라이브/스냅샷 경로를 흉내 낸 다른 클라이언트
    assert other.connect().state is CamState.REFUSED
    assert other.call('getDeviceInfo').state is CamState.REFUSED
    assert mock.step2_count == 1 and mock.failed_auth_attempts == 1
    assert mock.probe_count == probes_before


def test_even_correct_password_is_refused_while_latched(mock, guard, store):
    make_client(mock, guard, BAD).connect()
    assert make_client(mock, guard, GOOD).connect().state is CamState.REFUSED
    assert mock.step2_count == 1


def test_user_unlocks_by_saving_new_password_then_one_try(mock, guard, store):
    make_client(mock, guard, BAD).connect()
    store.reset_credentials('cam1', fp_of(GOOD))           # 비밀번호를 새로 저장
    r = make_client(mock, guard, GOOD).connect()
    assert r.accepted and store.load('cam1').auth_state == AG.OK
    assert store.load('cam1').verified_fp == fp_of(GOOD)


def test_reconnect_button_allows_exactly_one_more_attempt(mock, guard, store):
    c = make_client(mock, guard, BAD)
    c.connect()
    store.clear_latch('cam1')                              # "다시 연결"
    assert c.connect().error_class is ErrorClass.AUTH_FAILED
    assert c.connect().state is CamState.REFUSED
    assert mock.step2_count == 2                           # 사용자가 누른 만큼만


def test_wrong_username_latches_once(mock, guard):
    c = make_client(mock, guard, GOOD, username='operator')
    assert c.connect().error_class is ErrorClass.AUTH_FAILED
    assert c.connect().state is CamState.REFUSED
    assert mock.step2_count == 1


def test_locked_camera_latches_without_sending_credentials(mock, guard, store):
    mock.locked = True
    r = make_client(mock, guard, GOOD).connect()
    assert r.error_class is ErrorClass.LOCKED and r.code == -10022
    assert store.load('cam1').auth_state == AG.LOCKED
    n = len(mock.auth_log)
    make_client(mock, guard, GOOD).connect()
    assert len(mock.auth_log) == n                          # 잠금 뒤 시도 0
    assert mock.step2_count == 0 and mock.commands == []   # 자격 증명(2단계)은 한 번도 안 갔다


def test_client_limit_is_not_a_latch(mock, guard, store):
    mock.max_clients = 1
    a = make_client(mock, guard, GOOD, camera_id='camA')
    assert a.connect().accepted
    b = make_client(mock, guard, GOOD, camera_id='camB')
    r = b.connect()
    assert r.error_class is ErrorClass.CLIENT_LIMIT and r.code == -10021
    rec = store.load('camB')
    assert rec.auth_state == AG.UNVERIFIED and rec.attempt_lease_until is None
    # 래치가 아니므로 슬롯이 비면 사용자 조작 없이 연결된다
    a.close()
    mock.expire_all_stoks()
    assert b.connect().accepted
    assert store.load('camB').auth_state == AG.OK


def test_unknown_auth_response_latches_safely(mock, guard, store):
    # 모의 서버가 2단계에서 알 수 없는 코드를 돌려주는 경우: 결과를 증명할 수 없으므로 래치
    orig = mock.handle_doauth

    def weird(params):
        if params is not None:
            mock.auth_log.append({'step': 2, 'ok': False, 'code': -777})
            return {'error_code': -777}
        return orig(params)
    mock.handle_doauth = weird
    c = make_client(mock, guard, GOOD)
    assert c.connect().state is CamState.FAILED
    assert store.load('cam1').auth_state == AG.FAILED
    assert c.connect().state is CamState.REFUSED


def test_unsupported_algorithm_never_sends_credentials(mock, guard, store):
    mock.algorithm = 'MD5'
    r = make_client(mock, guard, GOOD).connect()
    assert r.state is CamState.UNSUPPORTED
    assert mock.step2_count == 0
    assert store.load('cam1').attempt_lease_until is None


def test_network_error_does_not_latch(guard, store):
    from aot.camera_drivers.vigi.openapi import TransportError

    def timeout(*a, **k):
        raise TransportError('connect failed: timeout')
    c = VigiOpenApi('127.0.0.1', Credential('admin', GOOD), camera_id='cam1', guard=guard,
                    fp_key=KEY, port=1, transport=timeout)
    r = c.connect()
    assert r.error_class is ErrorClass.NETWORK
    rec = store.load('cam1')
    assert rec.auth_state == AG.UNVERIFIED and rec.attempt_lease_until is None


def test_closed_port_means_openapi_off_not_a_latch(guard, store):
    c = VigiOpenApi('127.0.0.1', Credential('admin', GOOD), camera_id='cam1', guard=guard,
                    fp_key=KEY, port=1, timeout=0.5)
    assert c.connect().error_class is ErrorClass.NETWORK
    assert store.load('cam1').auth_state == AG.OPENAPI_OFF


def test_no_response_after_credentials_sent_latches(mock, guard, store):
    # 본문이 나간 뒤 응답을 못 받으면 결과를 모른다 — 같은 자격 증명을 다시 보내지 않는다
    from aot.camera_drivers.vigi.openapi import TransportError, https_post
    calls = {'n': 0}

    def flaky(host, port, path, body, pin, timeout):
        calls['n'] += 1
        if calls['n'] == 2:
            raise TransportError('request failed: timeout', sent=True)
        return https_post(host, port, path, body, pin, timeout)
    c = make_client(mock, guard, GOOD, transport=flaky)
    r = c.connect()
    assert r.error_class is ErrorClass.NETWORK
    assert store.load('cam1').auth_state == AG.FAILED
    assert c.connect().state is CamState.REFUSED
    assert calls['n'] == 2


# ---------------------------------------------------------------------------
# 프로세스 간 1회
# ---------------------------------------------------------------------------
@pytest.mark.parametrize('rounds', [12])
def test_two_processes_with_unverified_credential_send_exactly_one_attempt(tmp_path, rounds):
    for i in range(rounds):
        with MockVigiServer() as m:
            path = str(tmp_path / ('auth%d.db' % i))
            SqliteAuthStore(path)                            # 스키마 준비
            g1 = AuthGuard(SqliteAuthStore(path))            # 서로 다른 연결 = 서로 다른 프로세스
            g2 = AuthGuard(SqliteAuthStore(path))
            c1 = make_client(m, g1, BAD)
            c2 = make_client(m, g2, BAD)
            barrier = threading.Barrier(2)
            out = []

            def run(c):
                barrier.wait()
                out.append(c.connect())
            ts = [threading.Thread(target=run, args=(c,)) for c in (c1, c2)]
            [t.start() for t in ts]
            [t.join() for t in ts]
            assert m.step2_count == 1, 'round %d: %d attempts' % (i, m.step2_count)
            assert sorted(r.state.value for r in out) == ['failed', 'refused']


def test_concurrent_clients_same_store_one_attempt(mock, guard):
    clients = [make_client(mock, guard, BAD) for _ in range(6)]
    barrier = threading.Barrier(len(clients))
    out = []

    def run(c):
        barrier.wait()
        out.append(c.connect())
    ts = [threading.Thread(target=run, args=(c,)) for c in clients]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert mock.step2_count == 1
    assert sum(1 for r in out if r.state is CamState.REFUSED) == 5


# ---------------------------------------------------------------------------
# 재인증은 성공한 자격 증명으로만
# ---------------------------------------------------------------------------
def test_stok_expiry_reauths_once_with_verified_credential(mock, guard, store):
    c = make_client(mock, guard, GOOD)
    assert c.call('getDeviceInfo').accepted
    mock.expire_all_stoks()
    r = c.call('getDeviceInfo')
    assert r.accepted
    assert mock.step2_count == 2 and mock.failed_auth_attempts == 0


def test_proactive_refresh_after_25_minutes(mock, guard):
    t = [0.0]
    c = make_client(mock, guard, GOOD, monotonic=lambda: t[0])
    assert c.call('getDeviceInfo').accepted
    t[0] += 24 * 60
    assert c.call('getDeviceInfo').accepted
    assert mock.step2_count == 1
    t[0] += 2 * 60
    assert c.call('getDeviceInfo').accepted
    assert mock.step2_count == 2


def test_no_reauth_when_credential_no_longer_matches_verified(mock, guard, store):
    c = make_client(mock, guard, GOOD)
    assert c.call('getDeviceInfo').accepted
    store.mark_verified('cam1', fp_of('some-other-password'), T0)   # 다른 자격이 확인된 상태
    mock.expire_all_stoks()
    n = mock.step2_count
    r = c.call('getDeviceInfo')
    assert r.state is CamState.REFUSED
    assert mock.step2_count == n and mock.probe_count == 1


def test_reauth_failure_latches_and_stops(mock, guard, store):
    c = make_client(mock, guard, GOOD)
    assert c.call('getDeviceInfo').accepted
    mock.set_password('rotated-on-camera')     # 카메라 쪽 비밀번호가 바뀜
    mock.expire_all_stoks()
    r = c.call('getDeviceInfo')
    assert r.error_class is ErrorClass.AUTH_FAILED
    assert store.load('cam1').auth_state == AG.FAILED
    assert c.call('getDeviceInfo').state is CamState.REFUSED
    assert mock.failed_auth_attempts == 1


def test_guard_reauth_requires_verified_fingerprint(store, clock):
    g = AuthGuard(store, clock)
    assert not g.begin('c', 'fp1', reauth=True)
    p = g.begin('c', 'fp1')
    assert p.kind == AG.FIRST_TRY
    g.report_success(p)
    assert g.begin('c', 'fp1', reauth=True).kind == AG.REAUTH
    assert not g.begin('c', 'fp2', reauth=True)


# ---------------------------------------------------------------------------
# 임대 규칙
# ---------------------------------------------------------------------------
def test_lease_blocks_second_attempt_until_it_expires(store, clock):
    g = AuthGuard(store, clock, lease_seconds=30)
    assert g.begin('c', 'fp1').kind == AG.FIRST_TRY
    r = g.begin('c', 'fp1')
    assert not r and r.reason == 'attempt_in_progress'
    clock.advance(31)                      # 시도한 프로세스가 죽었다면 임대가 만료된다
    assert g.begin('c', 'fp1').kind == AG.FIRST_TRY


def test_lease_released_after_non_auth_failure(store, clock):
    g = AuthGuard(store, clock)
    p = g.begin('c', 'fp1')
    g.report_failure(p, ErrorClass.NETWORK)
    assert g.begin('c', 'fp1').kind == AG.FIRST_TRY


def test_latch_cert_changed_and_openapi_off_rules(store, clock):
    g = AuthGuard(store, clock)
    store.set_state('c', AG.OPENAPI_OFF)
    assert not g.begin('c', 'fp', interface='openapi')       # OpenAPI 는 멈추고
    assert g.begin('c', 'fp', interface='rtsp').kind == AG.FIRST_TRY   # RTSP 가 1회 시도를 맡는다
    store.set_state('d', AG.CERT_CHANGED)
    assert not g.begin('d', 'fp', interface='rtsp')


def test_credential_fp_hides_password_and_depends_on_key():
    a = AG.credential_fp('admin', 'pw', b'k1')
    assert 'pw' not in a and a != AG.credential_fp('admin', 'pw', b'k2')
    assert a != AG.credential_fp('admin', 'pw2', b'k1')
    assert a != AG.credential_fp('admin2', 'pw', b'k1')
    assert AG.credential_fp('ab', 'c', b'k') != AG.credential_fp('a', 'bc', b'k')


# ---------------------------------------------------------------------------
# TLS 지문 (TOFU)
# ---------------------------------------------------------------------------
def test_matching_pin_connects_and_observed_pin_is_reported(mock, guard):
    c = make_client(mock, guard, GOOD, tls_pin=mock.cert_sha256)
    assert c.connect().accepted
    assert c.observed_pin == mock.cert_sha256


def test_changed_certificate_stops_before_sending_anything(mock, guard, store):
    c = make_client(mock, guard, GOOD, tls_pin='0' * 64)
    r = c.connect()
    assert r.error_class is ErrorClass.CERT_CHANGED
    assert c.observed_pin == mock.cert_sha256
    assert mock.auth_log == [] and mock.raw_bodies == []     # 본문 한 바이트도 나가지 않았다
    assert store.load('cam1').auth_state == AG.CERT_CHANGED
    assert c.connect().state is CamState.REFUSED
    assert mock.raw_bodies == []


# ---------------------------------------------------------------------------
# 비밀 비노출
# ---------------------------------------------------------------------------
def test_no_secret_in_logs_results_exceptions_or_wire(mock, guard, store, caplog):
    caplog.set_level(logging.DEBUG)
    results = []
    good = make_client(mock, guard, GOOD, camera_id='camG')
    results.append(good.connect())
    results.append(good.call('getDeviceInfo'))
    results.append(good.call('cruiseMove', {'x': 1}))
    full_stoks = list(mock._stoks)
    bad = make_client(mock, guard, BAD, camera_id='camB')
    results.append(bad.connect())
    results.append(bad.connect())
    mock.locked = True
    results.append(make_client(mock, guard, GOOD, camera_id='camL').connect())
    digests = set()
    for raw in mock.raw_bodies:
        req = json.loads(raw)
        if isinstance(req.get('params'), dict) and 'response' in req['params']:
            digests.add(req['params']['response'])
    assert digests
    blob = caplog.text + ' '.join(repr(r) for r in results) + repr(good) + repr(bad) \
        + repr(Credential('admin', GOOD)) + repr(store.load('camB'))
    assert GOOD not in blob and BAD not in blob
    for d in digests:
        assert d not in blob
    for s in full_stoks:
        assert s not in blob
    # 와이어에도 평문 비밀번호는 없다(digest 만 간다)
    assert all(GOOD not in raw and BAD not in raw for raw in mock.raw_bodies)


# ---------------------------------------------------------------------------
# CamResult: 성공은 error_code 0 으로만 증명
# ---------------------------------------------------------------------------
def test_accepted_requires_error_code_zero(mock, guard):
    c = make_client(mock, guard, GOOD)
    r = c.call('cruiseMove', {'x': 1})
    assert r.accepted and r.code == 0
    assert mock.commands[-1] == ('cruiseMove', {'x': 1})

    mock.overrides['cruiseMove'] = -40210                  # HTTP 200 + error_code != 0
    r = c.call('cruiseMove', {'x': 1})
    assert r.state is CamState.FAILED and r.code == -40210 and not r.accepted

    mock.overrides['cruiseMove'] = 'empty'                 # 빈 본문
    assert c.call('cruiseMove').state is CamState.UNVERIFIED

    mock.overrides['cruiseMove'] = 'garbage'               # 깨진 JSON
    assert c.call('cruiseMove').state is CamState.UNVERIFIED

    mock.overrides['cruiseMove'] = {'result': {}}          # error_code 없는 200
    assert c.call('cruiseMove').state is CamState.UNVERIFIED

    mock.overrides['cruiseMove'] = {'errCode': 0, 'result': {'ok': 1}}   # 문서 철자 errCode 도 읽는다
    assert c.call('cruiseMove').accepted
    # 이 모든 실패가 인증 상태를 건드리지 않는다
    assert c.call('getDeviceInfo').accepted


def test_control_call_auth_error_midsession_latches(mock, guard, store):
    c = make_client(mock, guard, GOOD)
    assert c.call('getDeviceInfo').accepted
    mock.overrides['getDeviceInfo'] = -10020
    assert c.call('getDeviceInfo').error_class is ErrorClass.AUTH_FAILED
    assert store.load('cam1').auth_state == AG.FAILED
    assert c.call('getDeviceInfo').state is CamState.REFUSED


# ---------------------------------------------------------------------------
# 능력 협상
# ---------------------------------------------------------------------------
def _negotiate(variant, guard):
    with MockVigiServer(variant=variant) as m:
        c = make_client(m, guard, GOOD, camera_id='cap-' + variant)
        r = CM.negotiate(c.call)
        assert r.accepted
        return r.data


def test_capabilities_pt_camera(guard):
    caps = _negotiate('pt', guard)
    for f in ('ptz.pan_tilt', 'ptz.preset', 'day_night', 'alarm.sound', 'alarm.light',
              'alarm.manual', 'audio.speaker', 'audio.mic', 'storage.sd', 'events.push',
              'record.playback', 'event.enhance.people', 'event.enhance.vehicle'):
        assert caps.has(f), f
    assert not caps.has('ptz.zoom')
    assert caps.attr('ptz.preset_max') == 8 and caps.attr('ptz.speed_max') == 7
    assert caps.event_kinds() == ['motion', 'people', 'vehicle', 'tamper']


def test_capabilities_fixed_camera_draws_no_ptz_or_alarm(guard):
    caps = _negotiate('fixed', guard)
    assert not any(caps.has(f) for f in ('ptz.pan_tilt', 'ptz.zoom', 'ptz.preset', 'alarm.manual',
                                         'audio.speaker'))
    assert caps.has('storage.sd') and caps.has('day_night')
    assert caps.event_kinds() == ['motion', 'tamper']
    assert caps.attr('ptz.speed_max') is None


def test_capabilities_zoom_camera(guard):
    caps = _negotiate('zoom', guard)
    assert caps.has('ptz.pan_tilt') and caps.has('ptz.zoom')
    assert 'intrusion' in caps.event_kinds() and 'crossline' in caps.event_kinds()
    assert not caps.has('alarm.manual')


def test_negotiation_partial_failure_keeps_what_was_read(mock, guard):
    mock.overrides['getPTZCapability'] = -1
    c = make_client(mock, guard, GOOD)
    r = CM.negotiate(c.call)
    assert r.accepted and r.data.has('ptz.pan_tilt')
    assert r.data.attr('partial') == ['getPTZCapability']
    assert r.data.attr('ptz.speed_max') is None


def test_negotiation_failure_of_module_list_is_returned_as_is(mock, guard):
    mock.overrides['getModuleList'] = 'empty'
    r = CM.negotiate(make_client(mock, guard, GOOD).call)
    assert r.state is CamState.UNVERIFIED


# ---------------------------------------------------------------------------
# 모의 서버 자체 점검: subscribeMsg
# ---------------------------------------------------------------------------
def test_mock_subscribe_streams_events_and_heartbeats_then_closes(mock, guard):
    c = make_client(mock, guard, GOOD)
    assert c.connect().accepted
    stok = next(iter(mock._stoks))
    mock.heartbeat_s = 0.1
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    conn = http.client.HTTPSConnection('127.0.0.1', mock.port, timeout=5, context=ctx)
    conn.request('POST', '/stok=' + stok, body=json.dumps({'method': 'subscribeMsg',
                 'params': {'msg_type': 'all'}}), headers={'Content-Type': 'application/json'})
    resp = conn.getresponse()
    assert resp.status == 200 and 'multipart/mixed' in resp.getheader('Content-Type')
    mock.push_event({'event_type': 'TamperDetection', 'time': 1})
    seen = ''
    deadline = time.time() + 5
    while time.time() < deadline and not ('TamperDetection' in seen and 'Heartbeat' in seen):
        seen += resp.fp.readline().decode()
    assert 'TamperDetection' in seen and 'Heartbeat' in seen
    mock.close_subscriptions()
    rest = resp.read()                                     # 서버가 끊으면 EOF
    assert isinstance(rest, bytes)
    conn.close()
