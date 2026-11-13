# coding=utf-8
"""CameraDriverService 가 vendor='onvif' 행을 ONVIF 드라이버로 연결 확인한다(새 RPC 없음) × 모의 서버, 테스트 DB."""
import uuid

from aot.camera_drivers import secrets as S
from aot.camera_drivers.service import CameraDriverService
from aot.config import AOT_DB_PATH
from aot.databases.models import Camera, CameraDriver
from aot.databases.utils import session_scope
from aot.tests.fixtures.onvif_mock import MockOnvifServer

GOOD = 'correct-horse-battery'


def _make(port, password=GOOD):
    cid = str(uuid.uuid4())
    with session_scope(AOT_DB_PATH) as s:
        s.add(Camera(unique_id=cid, name='t-' + cid[:8], library='onvif', camera_type='onvif'))
        s.flush()
        s.add(CameraDriver(camera_id=cid, vendor='onvif', host='127.0.0.1', openapi_port=port,
                           username='admin', password_sealed=S.seal_password(password)))
    return cid


def _row(cid):
    with session_scope(AOT_DB_PATH) as s:
        r = s.query(CameraDriver).filter_by(camera_id=cid).one()
        return {c.name: getattr(r, c.name) for c in r.__table__.columns}


def test_verify_stores_info_and_capabilities_and_status_shows_them():
    with MockOnvifServer() as srv:
        cid = _make(srv.port)
        svc = CameraDriverService()
        res = svc.call('verify', cid)
        assert res['ok'] and res['state'] == 'accepted'
        row = _row(cid)
        assert row['auth_state'] == 'ok' and row['capabilities']
        assert row['device_info']['Manufacturer'] == 'MockCam'
        st = svc.call('status', cid)
        assert st['device_info'].get('model') and st['onvif_port'] == srv.port
        assert svc.call('refresh_capabilities', cid)['ok']
        assert srv.credentialed_attempts() >= 1


def test_wrong_password_latches_with_single_attempt():
    with MockOnvifServer() as srv:
        cid = _make(srv.port, password='definitely-wrong-pw-123')
        svc = CameraDriverService()
        res = svc.call('verify', cid)
        assert not res['ok']
        assert _row(cid)['auth_state'] == 'failed'
        svc.call('verify', cid)           # 래치가 걸려 있으면 카메라에 다시 가지 않는다
        assert srv.wrong_attempts() == 1
