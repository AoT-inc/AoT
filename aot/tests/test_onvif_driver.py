# coding=utf-8
"""ONVIF 드라이버 × 모의 서버 — 인증 보호 계약·오류 분류·능력 협상·비노출 (범위 문서 O1).

핵심 판정 기준은 모의 서버가 본 '자격 증명이 실린 요청' 수다: 틀린 자격 증명이 두 번 가는 경로가 없어야 한다.
"""
import logging
import socket
import threading
from datetime import datetime, timedelta, timezone

import pytest

from aot import camera_drivers
from aot.camera_drivers import auth_guard as AG
from aot.camera_drivers import capabilities as C
from aot.camera_drivers.auth_guard import AuthGuard, InMemoryAuthStore
from aot.camera_drivers.driver import CameraDriver, CamState, Credential, ErrorClass
from aot.camera_drivers.onvif import capability_map as CM
from aot.camera_drivers.onvif import errors as E
from aot.camera_drivers.onvif import soap as S
from aot.camera_drivers.onvif.driver import OnvifDriver
from aot.tests.fixtures.onvif_mock import MockOnvifServer
from aot.tests.test_vigi_openapi import SqliteAuthStore

KEY = b'unit-test-fp-key'
GOOD = 'correct-horse-battery'
BAD = 'definitely-wrong-pw-123'
CID = 'cam-onvif-1'
T0 = datetime(2026, 11, 7, 12, 0, tzinfo=timezone.utc)


class Clock:
    def __init__(self):
        self.now = T0

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += timedelta(seconds=seconds)


@pytest.fixture(params=['memory', 'sqlite'])
def store(request, tmp_path):
    return InMemoryAuthStore() if request.param == 'memory' else SqliteAuthStore(str(tmp_path / 'a.db'))


def make(srv, store, password=GOOD, clock=None, **kw):
    clock = clock or Clock()
    guard = AuthGuard(store, clock)
    d = OnvifDriver('127.0.0.1', Credential('admin', password), camera_id=CID, guard=guard,
                    fp_key=KEY, openapi_port=srv.port, timeout=3.0, **kw)
    return d, guard


def state(store):
    return store.load(CID).auth_state


# -- 인증 계약 ---------------------------------------------------------------
@pytest.mark.parametrize('auth', ['wsse', 'digest'])
def test_verify_ok_sends_exactly_one_credentialed_request(store, auth):
    with MockOnvifServer(auth=auth) as srv:
        d, _ = make(srv, store)
        r = d.verify(Credential('admin', GOOD))
        assert r.accepted and r.interface == 'onvif'
        assert srv.credentialed_attempts() == 1
        assert state(store) == AG.OK


@pytest.mark.parametrize('auth,style', [('wsse', 'fault'), ('wsse', 'http'), ('digest', 'fault')])
def test_wrong_password_latches_after_one_attempt_and_never_resends(store, auth, style):
    with MockOnvifServer(auth=auth, unauth_style=style) as srv:
        d, _ = make(srv, store, password=BAD)
        r = d.verify()
        assert r.state is CamState.FAILED and r.error_class is ErrorClass.AUTH_FAILED
        assert srv.credentialed_attempts() == 1 and srv.wrong_attempts() == 1
        assert state(store) == AG.FAILED
        before = len(srv.request_log)
        # 어떤 경로로도 카메라에 아무것도 가지 않는다
        for res in (d.verify(), d.verify(reuse=True), d.device_info(),
                    d.api.call('device', 'GetServices'), d.api.call('media', 'GetProfiles')):
            assert res.state is CamState.REFUSED
        assert d.capabilities(refresh=True) is None
        assert d.stream_profiles() == []
        assert len(srv.request_log) == before
        assert srv.credentialed_attempts() == 1


def test_wrong_password_two_threads_only_one_attempt(tmp_path):
    st = SqliteAuthStore(str(tmp_path / 'race.db'))
    with MockOnvifServer() as srv:
        drivers = [make(srv, st, password=BAD)[0] for _ in range(4)]
        out = []
        ts = [threading.Thread(target=lambda dd=dd: out.append(dd.verify())) for dd in drivers]
        [t.start() for t in ts]
        [t.join() for t in ts]
        assert srv.credentialed_attempts() == 1
        assert sum(1 for r in out if r.error_class is ErrorClass.AUTH_FAILED) == 1


def test_clear_latch_allows_exactly_one_new_attempt(store):
    with MockOnvifServer() as srv:
        d, guard = make(srv, store, password=BAD)
        d.verify()
        guard.store.clear_latch(CID)
        d.verify()
        assert srv.credentialed_attempts() == 2      # 사용자가 "다시 연결"을 눌렀을 때만 한 번 더
        assert state(store) == AG.FAILED
        d.verify()
        assert srv.credentialed_attempts() == 2


def test_lockout_fault_latches_locked(store):
    with MockOnvifServer(lock_after=1) as srv:
        d, _ = make(srv, store, password=BAD)
        r = d.verify()
        assert r.error_class is ErrorClass.AUTH_FAILED      # 첫 시도는 일반 거부
        srv.locked = True
        guard = AuthGuard(InMemoryAuthStore(), Clock())
        d2 = OnvifDriver('127.0.0.1', Credential('admin', GOOD), camera_id='c2', guard=guard,
                         fp_key=KEY, openapi_port=srv.port)
        r = d2.verify()
        assert r.error_class is ErrorClass.LOCKED
        assert guard.store.load('c2').auth_state == AG.LOCKED


def test_client_limit_does_not_latch_and_can_retry(store):
    with MockOnvifServer() as srv:
        srv.limit = True
        d, _ = make(srv, store)
        r = d.verify()
        assert r.error_class is ErrorClass.CLIENT_LIMIT
        assert state(store) not in AG.LATCHED_STATES
        srv.limit = False
        assert d.verify().accepted


def test_network_error_does_not_latch(store):
    s = socket.socket()
    s.bind(('127.0.0.1', 0))
    port = s.getsockname()[1]
    s.close()
    guard = AuthGuard(store, Clock())
    d = OnvifDriver('127.0.0.1', Credential('admin', GOOD), camera_id=CID, guard=guard, fp_key=KEY,
                    openapi_port=port, timeout=1.0)
    r = d.verify()
    assert r.error_class is ErrorClass.NETWORK
    assert state(store) not in AG.LATCHED_STATES
    assert store.load(CID).attempt_lease_until is None


@pytest.mark.parametrize('override', ['empty', 'garbage', ('status', 500), ('status', 403)])
def test_unintelligible_auth_response_latches_safely(store, override):
    with MockOnvifServer() as srv:
        srv.override = override
        d, _ = make(srv, store)
        r = d.verify()
        assert r.error_class is ErrorClass.AUTH_FAILED and not r.accepted
        assert state(store) == AG.FAILED
        assert srv.credentialed_attempts() <= 1


def test_call_before_verify_is_refused_without_traffic(store):
    with MockOnvifServer() as srv:
        d, _ = make(srv, store)
        r = d.device_info()
        assert r.state is CamState.REFUSED
        assert srv.request_log == [] and srv.ops_seen == []


def test_password_changed_on_camera_latches_on_first_failure(store):
    with MockOnvifServer() as srv:
        d, _ = make(srv, store)
        assert d.verify().accepted
        srv.password = 'someone-changed-it'
        r = d.device_info()
        assert r.error_class is ErrorClass.AUTH_FAILED
        assert state(store) == AG.FAILED
        n = srv.credentialed_attempts()
        assert d.device_info().state is CamState.REFUSED
        assert srv.credentialed_attempts() == n


def test_changed_password_never_reauths_with_unverified_credential(store):
    with MockOnvifServer() as srv:
        d, guard = make(srv, store)
        assert d.verify().accepted
        d2, _ = make(srv, store, password='typed-but-unverified')
        n = srv.credentialed_attempts()
        r = d2.device_info()                     # call 은 verified_fp 와 같은 자격 증명만 쓴다
        assert r.state is CamState.REFUSED
        assert srv.credentialed_attempts() == n


def test_digest_stale_nonce_retries_once_without_latch(store):
    with MockOnvifServer(auth='digest', stale_after=2) as srv:
        d, _ = make(srv, store)
        assert d.verify().accepted
        for _ in range(4):
            assert d.device_info().accepted
        assert state(store) == AG.OK
        assert srv.wrong_attempts() == 0


# -- 시계 ----------------------------------------------------------------------
@pytest.mark.parametrize('skew', [3600, -7200])
def test_wsse_created_follows_camera_clock(store, skew):
    with MockOnvifServer(clock_skew=skew) as srv:
        # 시계 기준은 실제 현재 시각 — 모의 서버가 time.time() 을 쓰므로 고정 Clock 대신 utc_now 를 쓴다
        from aot.utils.timekit import utc_now
        guard = AuthGuard(store, utc_now)
        d = OnvifDriver('127.0.0.1', Credential('admin', GOOD), camera_id=CID, guard=guard,
                        fp_key=KEY, openapi_port=srv.port)
        assert d.verify().accepted
        assert srv.wrong_attempts() == 0


# -- 비밀 비노출 -----------------------------------------------------------------
@pytest.mark.parametrize('auth', ['wsse', 'digest'])
def test_password_never_on_the_wire_logs_or_results(store, auth, caplog):
    caplog.set_level(logging.DEBUG)
    with MockOnvifServer(auth=auth) as srv:
        d, _ = make(srv, store)
        results = [d.verify(), d.device_info(), d.stream_profiles()]
        bad, _ = make(srv, InMemoryAuthStore(), password=BAD)
        results.append(bad.verify())
        blob = '\n'.join(srv.wire)
        assert GOOD not in blob and BAD not in blob
        mine = ' '.join(repr(r) for r in results) + repr(d) + repr(d.api) + repr(Credential('a', GOOD))
        mine += caplog.text
        assert GOOD not in mine and BAD not in mine
        assert d.api.fingerprint not in mine


def test_error_messages_carry_no_fault_reason_text(store):
    with MockOnvifServer() as srv:
        d, _ = make(srv, store, password=BAD)
        r = d.verify()
        assert 'Sender not authorized' not in r.message and BAD not in r.message


def test_credentials_only_go_to_configured_host(store):
    with MockOnvifServer() as srv:
        d, _ = make(srv, store)
        assert d.verify().accepted and d.capabilities() is not None
        # 카메라가 알려 준 XAddr 의 host(10.9.9.9)는 쓰지 않고 경로만 쓴다
        assert d.api.paths['media'] == '/onvif/media_service'
        assert d.api.paths['events'] == '/onvif/events_service'
        assert all(e['path'].startswith('/onvif/') for e in srv.request_log)
    api = S.OnvifSoap('127.0.0.1', Credential('a', 'b'), camera_id='x', guard=AuthGuard(store, Clock()),
                      fp_key=KEY)
    api.set_service_path('media', 'http://evil.example:8080/../../x')
    assert api.paths['media'] == '/onvif/media_service'     # 경로 탈출 거부
    api.set_service_path('media', 'http://evil.example:8080/onvif/m2')
    assert api.paths['media'] == '/onvif/m2'


def test_doctype_and_entities_rejected():
    assert S.parse_xml(b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "b">]><x>&a;</x>') is None
    assert S.parse_xml(b'<a/>') is not None


# -- 능력 협상 ---------------------------------------------------------------------
def test_capabilities_full_camera(store):
    with MockOnvifServer(variant='ptz') as srv:
        d, _ = make(srv, store)
        assert d.verify().accepted
        caps = d.capabilities()
        assert caps.features >= {C.PTZ_PAN_TILT, C.PTZ_ZOOM, C.PTZ_PRESET, C.DAY_NIGHT, C.STORAGE_SD,
                                 C.EVENTS_PUSH, 'event.motion', 'event.crossline', 'event.intrusion',
                                 'event.tamper', 'event.scene_change', 'event.audio_anomaly'}
        assert caps.attr('ptz.preset_max') == 16 and caps.attr('onvif.profiles') == 2
        assert 'event.unknown' not in caps.features
        assert not caps.has(C.ALARM_SOUND) and not caps.has(C.RECORD_PLAYBACK)
        assert d.capabilities() is caps          # 캐시


def test_capabilities_fixed_camera_has_no_ptz_or_daynight(store):
    with MockOnvifServer(variant='fixed') as srv:
        d, _ = make(srv, store)
        d.verify()
        caps = d.capabilities()
        assert not caps.has(C.PTZ_PAN_TILT) and not caps.has(C.DAY_NIGHT) and not caps.has(C.STORAGE_SD)
        assert caps.event_kinds() == ['motion'] and caps.has(C.EVENTS_PUSH)
        assert 'partial' not in caps.attrs        # 'ActionNotSupported' 는 못 읽음이 아니다


def test_capabilities_bare_camera_has_no_events(store):
    with MockOnvifServer(variant='bare') as srv:
        d, _ = make(srv, store)
        d.verify()
        caps = d.capabilities()
        assert not caps.has(C.EVENTS_PUSH) and caps.event_kinds() == []


def test_capabilities_none_when_not_verified(store):
    with MockOnvifServer() as srv:
        d, _ = make(srv, store)
        assert d.capabilities() is None
        assert d.last_negotiation.state is CamState.REFUSED


def test_capabilities_roundtrip_json(store):
    with MockOnvifServer() as srv:
        d, _ = make(srv, store)
        d.verify()
        caps = d.capabilities()
        assert C.Capabilities.from_json(caps.to_json()) == caps


@pytest.mark.parametrize('topic,kind', [
    ('tns1:RuleEngine/CellMotionDetector/Motion', 'motion'),
    ('tns1:VideoSource/MotionAlarm', 'motion'),
    ('RuleEngine/LineDetector/Crossed', 'crossline'),
    ('tns1:RuleEngine/FieldDetector/ObjectsInside', 'intrusion'),
    ('tns1:RuleEngine/TamperDetector/Tamper', 'tamper'),
    ('tns1:Device/Trigger/tamper', 'tamper'),
    ('tns1:VideoSource/GlobalSceneChange/ImagingService', 'scene_change'),
    ('tns1:AudioAnalytics/Audio/DetectedSound', 'audio_anomaly'),
    ('tns1:RuleEngine/MyRuleDetector/PeopleDetect', 'people'),
    ('tns1:RuleEngine/MyRuleDetector/VehicleDetect', 'vehicle'),
    ('tns1:Device/Trigger/Relay', 'unknown'),
    ('', 'unknown'), (None, 'unknown'),
])
def test_topic_normalization(topic, kind):
    assert CM.normalize_topic(topic) == kind
    assert kind == 'unknown' or kind in C.EVENT_KINDS


# -- 기기 정보·스트림 -----------------------------------------------------------------
def test_device_info(store):
    with MockOnvifServer() as srv:
        d, _ = make(srv, store)
        d.verify()
        r = d.device_info()
        assert r.accepted and r.data['Manufacturer'] == 'MockCam' and r.data['SerialNumber'] == 'SN0001'


def test_stream_profiles_rank_strip_credentials_and_use_configured_host(store):
    with MockOnvifServer() as srv:
        srv.embed_creds_in_uri = True
        d, _ = make(srv, store)
        d.verify()
        ps = d.stream_profiles()
        assert [p.name for p in ps] == ['main', 'sub']
        assert (ps[0].width, ps[0].height, ps[0].codec) == (1920, 1080, 'h265')
        for p in ps:
            assert p.url.startswith('rtsp://127.0.0.1:554/stream/')
            assert '@' not in p.url and 'admin' not in p.url and GOOD not in p.url


# -- 틀 ------------------------------------------------------------------------------------
def test_registered_and_unsupported_defaults():
    assert camera_drivers.get_driver_class('onvif') is OnvifDriver
    assert OnvifDriver.vendor == 'onvif' and issubclass(OnvifDriver, CameraDriver)
    d = OnvifDriver.__new__(OnvifDriver)
    for r in (d.ptz_move((1, 0, 0)), d.ptz_stop(), d.ptz_goto(1), d.ptz_set_preset(1),
              d.set_day_night('auto'), d.manual_alarm(True)):
        assert r.state is CamState.UNSUPPORTED
    with pytest.raises(NotImplementedError):
        d.open_event_stream()


def test_error_classification():
    assert E.classify_http(401) is ErrorClass.AUTH_FAILED
    assert E.classify_http(503) is ErrorClass.CLIENT_LIMIT
    assert E.classify_http(500) is ErrorClass.DEVICE and E.classify_http(200) is ErrorClass.NONE
    assert E.classify_fault(['s:Sender', 'ter:NotAuthorized']) is ErrorClass.AUTH_FAILED
    assert E.classify_fault(['wsse:FailedAuthentication']) is ErrorClass.AUTH_FAILED
    assert E.classify_fault(['ter:NotAuthorized'], 'account locked out') is ErrorClass.LOCKED
    assert E.classify_fault(['ter:Action'], 'Too many sessions') is ErrorClass.CLIENT_LIMIT
    assert E.classify_fault(['ter:ActionNotSupported']) is ErrorClass.UNSUPPORTED
    assert E.classify_fault(['ter:InvalidArgVal']) is ErrorClass.DEVICE
    assert E.safe_token('ter:Not Authorized<script>') == 'ter:NotAuthorizedscript'
