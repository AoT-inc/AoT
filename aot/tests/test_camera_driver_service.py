# coding=utf-8
"""DbAuthStore(compare-and-set)·CameraDriverService × 모의 서버, 테스트 DB 사용 (설계 §10.1)."""
import threading
import uuid

import pytest

from aot.camera_drivers import auth_guard as AG
from aot.camera_drivers import secrets as S
from aot.camera_drivers.auth_guard import AuthGuard
from aot.camera_drivers.db_store import DbAuthStore
from aot.camera_drivers.service import CameraDriverService
from aot.config import AOT_DB_PATH
from aot.databases.models import Camera, CameraDriver
from aot.databases.utils import session_scope
from aot.tests.fixtures.vigi_mock import MockVigiServer

GOOD = 'correct-horse-battery'
BAD = 'definitely-wrong-pw-123'


def _make(host='127.0.0.1', port=20443, password=GOOD, user='admin'):
    cid = str(uuid.uuid4())
    with session_scope(AOT_DB_PATH) as s:
        s.add(Camera(unique_id=cid, name='t-' + cid[:8], library='vigi', camera_type='vigi'))
        s.flush()
        s.add(CameraDriver(camera_id=cid, vendor='vigi', host=host, openapi_port=port,
                           username=user, password_sealed=S.seal_password(password),
                           credential_fp=None))
    return cid


def _row(cid):
    with session_scope(AOT_DB_PATH) as s:
        r = s.query(CameraDriver).filter_by(camera_id=cid).one()
        return {c.name: getattr(r, c.name) for c in r.__table__.columns}


@pytest.fixture
def mock():
    with MockVigiServer() as m:
        yield m


@pytest.fixture
def svc():
    return CameraDriverService()


def test_lease_is_compare_and_set_across_sessions():
    cid = _make()
    st1, st2 = DbAuthStore(), DbAuthStore()
    g1, g2 = AuthGuard(st1), AuthGuard(st2)
    results = []
    barrier = threading.Barrier(8)

    def go(g):
        barrier.wait()
        results.append(g.begin(cid, 'fp-x'))
    ts = [threading.Thread(target=go, args=(g1 if i % 2 else g2,)) for i in range(8)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert sum(1 for r in results if r) == 1


def test_store_state_transitions():
    cid = _make()
    st = DbAuthStore()
    g = AuthGuard(st)
    p = g.begin(cid, 'fp1')
    g.report_failure(p, __import__('aot.camera_drivers.driver', fromlist=['ErrorClass']).ErrorClass.AUTH_FAILED, -10020)
    r = st.load(cid)
    assert r.auth_state == AG.FAILED and r.auth_code == -10020 and r.attempt_lease_until is None
    assert not g.begin(cid, 'fp1')
    st.reset_credentials(cid, 'fp2')
    assert st.load(cid).auth_state == AG.UNVERIFIED
    p = g.begin(cid, 'fp2')
    g.report_success(p)
    assert st.load(cid).verified_fp == 'fp2' and st.load(cid).auth_state == AG.OK


def test_missing_row_is_refused_not_crashed():
    g = AuthGuard(DbAuthStore())
    assert not g.begin('no-such-camera', 'fp')


def test_verify_success_saves_info_caps_and_pins_certificate(mock, svc):
    cid = _make(port=mock.port)
    out = svc.verify(cid)
    assert out['ok'] and out['auth_state'] == 'ok'
    row = _row(cid)
    assert row['tls_pin_sha256'] == mock.cert_sha256          # TOFU
    assert row['device_info']['model'] == 'VIGI C540V' and row['mac'] == 'AA-BB-CC-00-11-22'
    assert 'ptz.pan_tilt' in row['capabilities']['features']
    assert row['verified_fp'] and GOOD not in repr(row) and GOOD not in repr(out)
    assert row['password_sealed'] != GOOD
    # 기능 다시 읽기는 검증된 자격 증명으로 재인증 없이(또는 재인증 1회로) 된다
    mock.expire_all_stoks()
    assert svc.refresh_capabilities(cid)['ok']
    assert mock.failed_auth_attempts == 0


def test_wrong_password_one_attempt_then_latched_until_reconnect(mock, svc):
    cid = _make(port=mock.port, password=BAD)
    out = svc.verify(cid)
    assert not out['ok'] and out['auth_state'] == 'failed' and out['error_class'] == 'auth_failed'
    for _ in range(3):
        again = svc.verify(cid)
        assert again['state'] == 'refused'
    assert mock.step2_count == 1
    assert BAD not in repr(out) and BAD not in repr(_row(cid))
    # 사용자가 "다시 연결"을 누르면 시도 1회가 더 허용된다
    svc.reconnect(cid)
    assert mock.step2_count == 2


def test_certificate_change_flow_requires_user_confirmation(mock, svc):
    cid = _make(port=mock.port)
    with session_scope(AOT_DB_PATH) as s:
        s.query(CameraDriver).filter_by(camera_id=cid).one().tls_pin_sha256 = '0' * 64
    out = svc.verify(cid)
    assert out['auth_state'] == 'cert_changed' and mock.raw_bodies == []
    seen = svc.observe_cert(cid)
    assert seen['ok'] and seen['old'] == '0' * 16 and seen['new'] == mock.cert_sha256[:16]
    assert not svc.trust_new_cert(cid, 'ffffffffffffffff')['ok']        # 본 것과 다르면 거부
    assert _row(cid)['auth_state'] == 'cert_changed'
    assert svc.trust_new_cert(cid, seen['new'])['ok']
    assert _row(cid)['tls_pin_sha256'] == mock.cert_sha256
    assert svc.verify(cid)['ok']


def test_unconfigured_and_missing_password_never_touch_network(mock, svc):
    assert svc.verify('nope')['state'] == 'unconfigured'
    cid = _make(port=mock.port, password=None)
    assert svc.verify(cid)['reason'] == 'no_password'
    assert mock.auth_log == []
