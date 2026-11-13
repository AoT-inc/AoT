# coding=utf-8
"""VIGI 이벤트(P4): 구독 수명·버스·기록·디스패치·보존 (설계 §6.2, §6.3, §10.1). 모의 서버 + 테스트 DB."""
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from aot.camera_drivers import secrets as S
from aot.camera_drivers.event_hub import (DISPATCHED, ERROR, NONE, RATE_LIMIT, SUP_COOLDOWN,
                                          SUP_RATE, EventHub, TriggerDispatcher, purge_old,
                                          record_event)
from aot.camera_drivers.events import CameraEvent, CameraEventBus
from aot.camera_drivers.service import CameraDriverService
from aot.camera_drivers.vigi import capability_map
from aot.camera_drivers.vigi.subscribe import CameraSubscription
from aot.config import AOT_DB_PATH
from aot.databases.models import Camera, CameraDriver
from aot.databases.models import CameraEvent as EventRow
from aot.databases.models import Trigger
from aot.databases.utils import session_scope
from aot.tests.fixtures.vigi_mock import MockVigiServer
from aot.utils.timekit import naive_utc, utc_now

GOOD = 'correct-horse-battery'


def _make(port, password=GOOD, enabled=True, kinds=None):
    cid = str(uuid.uuid4())
    with session_scope(AOT_DB_PATH) as s:
        s.add(Camera(unique_id=cid, name='t-' + cid[:8], library='vigi', camera_type='vigi'))
        s.flush()
        s.add(CameraDriver(camera_id=cid, vendor='vigi', host='127.0.0.1', openapi_port=port,
                           username='admin', password_sealed=S.seal_password(password),
                           events_enabled=enabled, event_kinds=kinds))
    return cid


def _driver_row(cid):
    with session_scope(AOT_DB_PATH) as s:
        r = s.query(CameraDriver).filter_by(camera_id=cid).one()
        return {c.name: getattr(r, c.name) for c in r.__table__.columns}


def _trigger(cid, kinds, period=60, active=True, name='t'):
    uid = str(uuid.uuid4())
    with session_scope(AOT_DB_PATH) as s:
        s.add(Trigger(unique_id=uid, name=name, trigger_type='trigger_camera_event',
                      unique_id_1=cid, event_kinds=kinds, period=period, is_activated=active))
    return uid


def _events(cid):
    with session_scope(AOT_DB_PATH) as s:
        rows = s.query(EventRow).filter_by(camera_id=cid).order_by(EventRow.id).all()
        return [(r.kind, r.dispatch_state, r.dispatch_note) for r in rows]


def _wait(cond, timeout=8.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.02)
    return False


class FakeControl:
    def __init__(self, ret='msg'):
        self.calls = []
        self.ret = ret

    def trigger_all_actions(self, uid, message=''):
        self.calls.append((uid, message))
        if isinstance(self.ret, Exception):
            raise self.ret
        return self.ret


@pytest.fixture
def mock():
    with MockVigiServer() as m:
        yield m


@pytest.fixture
def verified(mock):
    """연결 확인까지 끝난 카메라(auth ok)와 서비스."""
    svc = CameraDriverService()
    cid = _make(mock.port)
    assert svc.verify(cid)['ok']
    return cid, svc


def _sub(cid, svc, **kw):
    hub = EventHub(svc)
    got, states, gaps = [], [], []
    kw.setdefault('sleep', lambda sec: False)
    sub = CameraSubscription(
        cid, make_api=lambda: (svc._driver(cid)[0].api, None),
        eligible=lambda: hub._eligible(cid),
        on_event=got.append, on_state=lambda st, n: states.append((st, n)),
        on_gap=lambda a, b: gaps.append((a, b)), **kw)
    return sub, got, states, gaps


# -- 이벤트 해석 ------------------------------------------------------------------------
def test_parse_event_part():
    assert capability_map.parse_event_part({'Heartbeat': '30'}) == ('heartbeat', None)
    what, ev = capability_map.parse_event_part(
        {'msg': [{'event_type': 'motionDetection', 'time': 1700000000}]})
    assert what == 'event' and ev['kind'] == 'motion' and ev['camera_epoch'] == 1700000000
    what, ev = capability_map.parse_event_part({'event_type': 'NoSuchThing'})
    assert ev['kind'] == 'unknown' and ev['raw_type'] == 'NoSuchThing'
    assert capability_map.parse_event_part({'x': 1}) == ('ignore', None)
    assert capability_map.parse_event_part('junk') == ('ignore', None)


# -- 버스 -------------------------------------------------------------------------------
def _ev(i=0, kind='motion', cid='c', at=None):
    return CameraEvent(camera_id=cid, kind=kind, received_at_utc=at or utc_now(), raw_type=str(i))


def test_bus_caps_at_1000_drops_oldest_and_counts():
    bus = CameraEventBus()
    for i in range(1005):
        bus.publish(_ev(i))
    assert len(bus) == 1000 and bus.dropped == 5
    assert bus.get(0).raw_type == '5'      # 가장 오래된 5개가 버려졌다
    assert CameraEventBus.MAXSIZE == 1000


def test_bus_get_times_out_empty():
    assert CameraEventBus().get(0.01) is None


# -- 구독 수명 --------------------------------------------------------------------------
def test_subscription_delivers_events_and_filters_kinds(mock, verified):
    cid, svc = verified
    sub, got, states, _ = _sub(cid, svc, kinds=['motion'])
    sub.start()
    try:
        assert _wait(lambda: sub.state == 'subscribed')
        mock.push_event({'event_type': 'motionDetection', 'time': int(time.time())})
        mock.push_event({'event_type': 'CrossLineDetection'})       # 받기로 하지 않은 종류
        mock.push_event({'event_type': 'WhoKnows'})                  # 모르는 종류는 버리지 않는다
        assert _wait(lambda: len(got) == 2)
    finally:
        sub.stop()
    assert [e.kind for e in got] == ['motion', 'unknown']
    assert got[0].received_at_utc.tzinfo is not None and got[0].camera_time_epoch


def test_heartbeat_silence_goes_to_backoff_then_resubscribes(mock, verified):
    cid, svc = verified
    mock.stop_heartbeats()
    sub, got, states, gaps = _sub(cid, svc, heartbeat_timeout=0.3)
    sub.start()
    try:
        assert _wait(lambda: any(n == 'heartbeat_timeout' for _, n in states))
        assert _wait(lambda: mock.subscribe_attempts >= 2)      # 백오프 뒤 다시 붙음
        assert 4 <= sub.delays[0] <= 6.1                          # 네트워크 백오프 5초 ±20%
    finally:
        sub.stop()
    assert _wait(lambda: len(gaps) >= 1, 3)                      # 끊겼던 구간이 기록됨


def test_stream_close_then_resubscribe_records_gap(mock, verified):
    cid, svc = verified
    sub, got, states, gaps = _sub(cid, svc)
    sub.start()
    try:
        assert _wait(lambda: sub.state == 'subscribed')
        mock.close_subscriptions()
        assert _wait(lambda: len(gaps) == 1)
        assert gaps[0][1] >= gaps[0][0]
        assert _wait(lambda: sub.state == 'subscribed')
    finally:
        sub.stop()


def test_backoff_sequence_is_5_10_20_with_jitter(mock, verified):
    cid, svc = verified
    mock.overrides['subscribeMsg'] = -40000          # 알 수 없는 카메라 오류 → 네트워크형 백오프
    stop = threading.Event()
    sub, _, states, _ = _sub(cid, svc, sleep=lambda s: stop.is_set() or (len(sub.delays) >= 4))
    sub.start()
    assert _wait(lambda: len(sub.delays) >= 4)
    sub.stop()
    for got, nominal in zip(sub.delays, (5, 10, 20, 40)):
        assert nominal * 0.8 - 1e-6 <= got <= nominal * 1.2 + 1e-6


def test_minus_10021_is_long_backoff_not_latch(mock, verified):
    cid, svc = verified
    mock.overrides['subscribeMsg'] = -10021
    sub, _, states, _ = _sub(cid, svc, sleep=lambda s: len(sub.delays) >= 3)
    sub.start()
    assert _wait(lambda: len(sub.delays) >= 3)
    sub.stop()
    for got, nominal in zip(sub.delays[:3], (60, 120, 240)):          # 60→120→240초(±20%)
        assert nominal * 0.8 - 1e-6 <= got <= nominal * 1.2 + 1e-6
    assert any(st == 'stopped_limit' for st, _ in states)
    assert _driver_row(cid)['auth_state'] == 'ok'                      # 래치 아님


def test_minus_10020_latches_once_and_never_retries(mock, verified):
    cid, svc = verified
    before = mock.step2_count
    mock.overrides['subscribeMsg'] = -10020
    sub, _, states, _ = _sub(cid, svc)
    sub.start()
    assert _wait(lambda: sub.state == 'stopped_auth')
    time.sleep(0.3)
    sub.stop()
    # 구독 자신의 인증 1회(성공한 자격 증명)뿐 — 거절 뒤에 자격 증명이 다시 가지 않는다
    assert mock.subscribe_attempts == 1 and mock.step2_count == before + 1
    assert _driver_row(cid)['auth_state'] == 'failed'
    assert not sub.alive


def test_not_eligible_when_disabled_or_unverified(mock):
    svc = CameraDriverService()
    hub = EventHub(svc)
    cid = _make(mock.port, enabled=False)
    assert hub._eligible(cid)[0] is False
    cid2 = _make(mock.port, enabled=True)                    # 확인 안 한 자격 증명
    ok, st, why = hub._eligible(cid2)
    assert not ok and why == 'unverified'
    assert mock.subscribe_attempts == 0 and mock.step2_count == 0


def test_hub_restart_rejoins_only_eligible(mock, verified):
    cid, svc = verified
    off = _make(mock.port, enabled=False)
    unv = _make(mock.port, enabled=True)
    hub = EventHub(svc)
    hub.start_all()
    try:
        assert _wait(lambda: _driver_row(cid)['event_state'] == 'subscribed')
        assert off not in hub._subs and unv not in hub._subs
        assert mock.step2_count == 2          # 연결 확인 1 + 확인된 카메라의 구독 1. 확인 안 된 카메라는 0
    finally:
        hub.stop()


def test_ensure_does_not_reconnect_when_already_running(mock, verified):
    cid, svc = verified
    hub = EventHub(svc)
    hub.ensure(cid)
    try:
        assert _wait(lambda: _driver_row(cid)['event_state'] == 'subscribed')
        n = mock.subscribe_attempts
        hub.ensure(cid)
        hub.ensure(cid)
        time.sleep(0.2)
        assert mock.subscribe_attempts == n
        with session_scope(AOT_DB_PATH) as s:
            s.query(CameraDriver).filter_by(camera_id=cid).one().events_enabled = False
        hub.ensure(cid)
        assert cid not in hub._subs
        assert _driver_row(cid)['event_state'] == 'off'
    finally:
        hub.stop()


# -- 기록 · 시계 어긋남 --------------------------------------------------------------------
def test_record_uses_server_time_and_notes_clock_skew(mock):
    cid = _make(mock.port)
    now = utc_now()
    ev = CameraEvent(cid, 'motion', now, camera_time_epoch=int(now.timestamp()) - 500)
    rid, note = record_event(ev)
    assert note == 'camera_clock_skew_s=-500'
    with session_scope(AOT_DB_PATH) as s:
        r = s.query(EventRow).filter_by(id=rid).one()
        assert r.received_at_utc == naive_utc(now) and r.dispatch_note == note
    ok_ev = CameraEvent(cid, 'motion', now, camera_time_epoch=int(now.timestamp()) - 100)
    assert record_event(ok_ev)[1] is None


# -- 디스패치 ---------------------------------------------------------------------------
def _disp(ctl=None):
    ctl = ctl or FakeControl()
    return TriggerDispatcher(control=ctl), ctl


def test_dispatch_filters_kinds_and_says_requested_only(mock):
    cid = _make(mock.port)
    t = _trigger(cid, ['motion', 'people'])
    _trigger(cid, ['tamper'], name='other')
    _trigger(cid, ['motion'], active=False, name='off')
    d, ctl = _disp()
    st, note = d.dispatch(_ev(kind='motion', cid=cid))
    assert st == DISPATCHED and [c[0] for c in ctl.calls] == [t]
    assert d.dispatch(_ev(kind='vehicle', cid=cid))[0] == NONE
    assert d.dispatch(_ev(kind='unknown', cid=cid)) == (NONE, 'unknown_kind')


def test_dispatch_cooldown_uses_period_from_server_time(mock):
    cid = _make(mock.port)
    _trigger(cid, ['motion'], period=30)
    d, ctl = _disp()
    t0 = datetime(2026, 11, 4, 3, 0, 0, tzinfo=timezone.utc)
    assert d.dispatch(_ev(cid=cid, at=t0))[0] == DISPATCHED
    assert d.dispatch(_ev(cid=cid, at=t0 + timedelta(seconds=29)))[0] == SUP_COOLDOWN
    assert d.dispatch(_ev(cid=cid, at=t0 + timedelta(seconds=31)))[0] == DISPATCHED
    assert len(ctl.calls) == 2


def test_cooldown_across_dst_boundary_uses_absolute_time(mock):
    """뉴욕 DST 시작(2026-03-08 02:00→03:00): 벽시계로는 1시간이 아니라 실제 2분 차이."""
    cid = _make(mock.port)
    _trigger(cid, ['motion'], period=300)
    d, ctl = _disp()
    ny = ZoneInfo('America/New_York')
    a = datetime(2026, 3, 8, 1, 59, tzinfo=ny)
    b = datetime(2026, 3, 8, 3, 1, tzinfo=ny)
    assert (b - a.astimezone(timezone.utc)).total_seconds() == 120
    assert d.dispatch(_ev(cid=cid, at=a))[0] == DISPATCHED
    assert d.dispatch(_ev(cid=cid, at=b))[0] == SUP_COOLDOWN


def test_dispatch_rate_limit_30_per_minute_per_camera(mock):
    cid = _make(mock.port)
    _trigger(cid, ['motion'], period=0)
    d, ctl = _disp()
    t0 = datetime(2026, 11, 4, 3, 0, 0, tzinfo=timezone.utc)
    states = [d.dispatch(_ev(cid=cid, at=t0 + timedelta(seconds=i * 0.1)))[0] for i in range(31)]
    assert states.count(DISPATCHED) == RATE_LIMIT == 30 and states[-1] == SUP_RATE
    # 1분이 지나면 다시 열린다
    assert d.dispatch(_ev(cid=cid, at=t0 + timedelta(seconds=61)))[0] == DISPATCHED
    # 다른 카메라는 영향이 없다
    cid2 = _make(mock.port)
    _trigger(cid2, ['motion'], period=0)
    assert d.dispatch(_ev(cid=cid2, at=t0 + timedelta(seconds=1)))[0] == DISPATCHED


@pytest.mark.parametrize('ret', ['Could not trigger Conditional Actions: boom', RuntimeError('x')])
def test_dispatch_failure_is_dispatch_error(mock, ret):
    cid = _make(mock.port)
    _trigger(cid, ['motion'])
    d, _ = _disp(FakeControl(ret))
    st, note = d.dispatch(_ev(cid=cid))
    assert st == ERROR and note


def test_other_return_text_is_not_failure(mock):
    cid = _make(mock.port)
    _trigger(cid, ['motion'])
    d, _ = _disp(FakeControl('Output turned on'))       # 문자열이어도 'Could not trigger' 가 아니면 실패 아님
    assert d.dispatch(_ev(cid=cid))[0] == DISPATCHED


# -- 소비자 스레드 전체 경로 ---------------------------------------------------------------
def test_pipeline_mock_event_to_trigger_to_record(mock, verified):
    cid, svc = verified
    uid = _trigger(cid, ['motion'])
    ctl = FakeControl()
    hub = EventHub(svc, dispatcher=TriggerDispatcher(control=ctl))
    svc.events_hub = hub
    hub.start()
    hub.ensure(cid)
    try:
        assert _wait(lambda: _driver_row(cid)['event_state'] == 'subscribed')
        mock.push_event({'event_type': 'motionDetection', 'time': int(time.time())})
        assert _wait(lambda: any(s == DISPATCHED for _, s, _ in _events(cid)))
        assert ctl.calls and ctl.calls[0][0] == uid
        assert 'event: motion' in ctl.calls[0][1]
    finally:
        hub.stop()


# -- 보존 -------------------------------------------------------------------------------
def _fill(cid, n, start):
    with session_scope(AOT_DB_PATH) as s:
        s.bulk_insert_mappings(EventRow, [
            dict(camera_id=cid, kind='motion', received_at_utc=naive_utc(start + timedelta(seconds=i)),
                 dispatch_state='none') for i in range(n)])


def test_purge_by_age_and_by_rows(mock):
    cid = _make(mock.port)
    now = utc_now()
    _fill(cid, 5, now - timedelta(days=31))           # 30일 넘음
    _fill(cid, 120, now - timedelta(hours=2))
    removed = purge_old(now, retain_rows=100)
    assert removed == 5 + 20
    assert len(_events(cid)) == 100
    # 다른 카메라 행은 그대로
    cid2 = _make(mock.port)
    _fill(cid2, 10, now - timedelta(hours=1))
    assert purge_old(now, retain_rows=100) == 0 and len(_events(cid2)) == 10


def test_retention_constants():
    from aot.camera_drivers import event_hub as H
    assert (H.RETAIN_DAYS, H.RETAIN_ROWS) == (30, 10000)


# -- 감지 스위치 읽기 · 상태 · 라우트 게이트 ---------------------------------------------------
def test_event_switches_reads_only_and_reports_unknown_as_missing(verified, mock):
    cid, svc = verified
    mock.switches['motionDetection'] = {'enabled': True, 'msg_push_enabled': False}
    mock.switches['tamperDetection'] = {'enabled': False, 'msg_push_enabled': False}
    out = svc.call('event_switches', cid)
    assert out['ok'] and out['data']['motion'] == {'enabled': True, 'msg_push_enabled': False}
    assert out['data']['tamper']['enabled'] is False
    assert 'crossline' not in out['data']                 # 읽지 못한 종류는 "모름" — 꺼짐으로 쓰지 않는다
    assert not any(m.startswith('set') for m, _ in mock.commands)


def test_status_has_events_and_recent_five(mock):
    cid = _make(mock.port, enabled=True, kinds=['motion'])
    now = utc_now()
    for i in range(7):
        record_event(CameraEvent(cid, 'motion', now + timedelta(seconds=i)))
    st = CameraDriverService().status(cid)
    assert st['events_enabled'] and st['event_kinds'] == ['motion']
    assert len(st['recent_events']) == 5
    assert st['recent_events'][0]['received_at'] > st['recent_events'][-1]['received_at']


def test_event_routes_ask_role_and_scope_before_touching_daemon_or_db():
    import ast
    src = open('aot/aot_flask/routes_camera_driver.py', encoding='utf-8').read()
    tree = ast.parse(src)
    for name in ('driver_events', 'driver_event_switches'):
        fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == name)
        first = {}
        for node in ast.walk(fn):
            if isinstance(node, ast.Call):
                f = node.func
                label = f.attr if isinstance(f, ast.Attribute) else getattr(f, 'id', '')
                if label in ('user_has_permission', 'can_operate_device', 'DaemonControl',
                             'commit', 'filter_by'):
                    first[label] = min(first.get(label, 10 ** 9), node.lineno)
        assert first['user_has_permission'] < first['can_operate_device'] < \
            min(first.get('DaemonControl', 10 ** 9), first.get('commit', 10 ** 9))


# -- 트리거 저장 검증 (빈 목록 거절) ------------------------------------------------------
def test_trigger_form_rejects_empty_kinds_and_bad_values(mock):
    from aot.camera_drivers.trigger_camera_event import validate_camera_event_form as V
    cid = _make(mock.port)
    errs, _ = V(cid, [], 60)
    assert errs                                           # 빈 목록 거절
    assert V(cid, ['nonsense'], 60)[0]                    # 모르는 종류 거절
    assert V('', ['motion'], 60)[0] and V(str(uuid.uuid4()), ['motion'], 60)[0]   # 카메라 없음
    assert V(cid, ['motion'], -1)[0] and V(cid, ['motion'], 'abc')[0]
    errs, vals = V(cid, ['motion', 'motion', 'people'], '30')
    assert not errs and vals == {'camera_id': cid, 'kinds': ['motion', 'people'], 'period': 30.0}
    assert V(cid, ['cv.person'], None)[1]['period'] == 60.0   # cv. 이름 공간 허용, 기본 60초
