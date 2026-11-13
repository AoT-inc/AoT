# coding=utf-8
"""VIGI 제어(P3): 모의 서버가 받은 명령 순서·데드맨·프리셋·능력 게이트 (설계 §9.3, §11 P3)."""
import time

import pytest

from aot.camera_drivers.service import CameraDriverService
from aot.tests.fixtures.vigi_mock import MockVigiServer
from aot.tests.test_camera_driver_service import _make



@pytest.fixture
def mock():
    with MockVigiServer(variant='full') as m:
        yield m


@pytest.fixture
def svc():
    s = CameraDriverService(deadman_s=0.25)
    yield s
    for t in list(s._dead.values()):
        t.cancel()


def _ready(svc, mock):
    cid = _make(port=mock.port)
    assert svc.verify(cid)['ok']
    mock.commands.clear()
    return cid


def _names(mock, skip=('getDeviceInfo',)):
    return [m for m, _ in mock.commands if m not in skip]


def test_press_then_release_sends_move_then_stop(mock, svc):
    cid = _ready(svc, mock)
    r = svc.call('ptz_move', cid, {'vector': [1, 0, 0], 'speed': 3}, control=True)
    assert r['ok'] and r['state'] == 'accepted'
    assert svc.call('ptz_stop', cid, None, control=True)['ok']
    assert _names(mock) == ['cruiseMove', 'stopMove']
    assert mock.commands[0][1]['pan'] == 1 and mock.commands[0][1]['speed'] == 3
    time.sleep(0.5)
    assert _names(mock) == ['cruiseMove', 'stopMove']        # 정지 뒤 데드맨이 또 보내지 않는다


def test_deadman_stops_after_silence(mock, svc):
    cid = _ready(svc, mock)
    svc.call('ptz_move', cid, {'vector': [0, 1, 0]}, control=True)
    time.sleep(0.6)
    assert _names(mock) == ['cruiseMove', 'stopMove']


def test_keepalive_defers_deadman_then_it_fires(mock, svc):
    cid = _ready(svc, mock)
    svc.call('ptz_move', cid, {'vector': [-1, 0, 0]}, control=True)
    for _ in range(4):
        time.sleep(0.12)
        assert svc.call('ptz_keepalive', cid, None, control=True)['ok']
    assert _names(mock) == ['cruiseMove']                    # 갱신 중에는 멈추지 않는다
    time.sleep(0.6)
    assert _names(mock) == ['cruiseMove', 'stopMove']


def test_keepalive_without_move_is_refused_and_sends_nothing(mock, svc):
    cid = _ready(svc, mock)
    assert not svc.call('ptz_keepalive', cid, None, control=True)['ok']
    assert _names(mock) == []


def test_new_move_replaces_old_timer_single_stop(mock, svc):
    cid = _ready(svc, mock)
    svc.call('ptz_move', cid, {'vector': [1, 0, 0]}, control=True)
    svc.call('ptz_move', cid, {'vector': [0, 1, 0]}, control=True)
    time.sleep(0.6)
    assert _names(mock) == ['cruiseMove', 'cruiseMove', 'stopMove']


def test_presets_validate_range_and_use_ids(mock, svc):
    cid = _ready(svc, mock)
    assert svc.call('ptz_set_preset', cid, {'preset': 3, 'name': 'door'}, control=True)['ok']
    assert svc.call('ptz_goto', cid, {'preset': 3}, control=True)['ok']
    assert svc.call('ptz_remove_preset', cid, {'preset': 3}, control=True)['ok']
    assert _names(mock) == ['setPresetPoint', 'gotoPresetPoint', 'removePresetPoint']
    n = len(mock.commands)
    for bad in (0, 9, 'x', None):
        assert svc.call('ptz_goto', cid, {'preset': bad}, control=True)['state'] == 'refused'
    assert len(mock.commands) == n                            # 범위 밖은 카메라에 보내지 않는다


def test_day_night_and_alarm(mock, svc):
    cid = _ready(svc, mock)
    assert svc.call('day_night_set', cid, {'mode': 'night'}, control=True)['ok']
    got = svc.call('day_night_get', cid, None, control=True)
    assert got['ok'] and got['data']['mode'] == 'night'
    assert svc.call('day_night_set', cid, {'mode': 'bogus'}, control=True)['state'] == 'refused'
    assert svc.call('alarm', cid, {'start': True}, control=True)['ok']
    assert svc.call('alarm', cid, {'start': False}, control=True)['ok']
    assert _names(mock)[-2:] == ['manualAlarm', 'manualAlarm']


def test_camera_error_code_is_failed_not_accepted(mock, svc):
    cid = _ready(svc, mock)
    mock.overrides['cruiseMove'] = -40210
    r = svc.call('ptz_move', cid, {'vector': [1, 0, 0]}, control=True)
    assert not r['ok'] and r['state'] == 'failed' and r['code'] == -40210
    assert cid not in svc._dead                                # 실패한 이동은 데드맨을 걸지 않는다
    mock.overrides['stopMove'] = 'empty'
    assert svc.call('ptz_stop', cid, None, control=True)['state'] == 'unverified'


def test_unsupported_capability_never_reaches_camera():
    with MockVigiServer(variant='fixed') as m:
        s = CameraDriverService(deadman_s=0.25)
        cid = _make(port=m.port)
        assert s.verify(cid)['ok']
        m.commands.clear()
        for op, arg in (('ptz_move', {'vector': [1, 0, 0]}), ('ptz_goto', {'preset': 1}),
                        ('alarm', {'start': True})):
            assert s.call(op, cid, arg, control=True)['state'] == 'unsupported'
        assert _names(m) == []


def test_zoom_requires_zoom_capability():
    with MockVigiServer(variant='pt') as m:
        s = CameraDriverService(deadman_s=0.25)
        cid = _make(port=m.port)
        assert s.verify(cid)['ok']
        assert s.call('ptz_move', cid, {'vector': [0, 0, 1]}, control=True)['state'] == 'unsupported'


def test_control_ops_unreachable_through_plain_camera_driver_call(mock, svc):
    cid = _ready(svc, mock)
    r = svc.call('ptz_move', cid, {'vector': [1, 0, 0]})       # control=False
    assert r['reason'] == 'unknown_op' and _names(mock) == []
    assert svc.call('verify', cid, None, control=True)['reason'] == 'unknown_op'


def test_one_authentication_serves_many_commands(mock, svc):
    cid = _ready(svc, mock)
    svc.call('ptz_stop', cid, None, control=True)    # 제어 드라이버의 첫 인증 1회
    base = mock.step2_count
    for _ in range(5):
        svc.call('ptz_stop', cid, None, control=True)
    assert mock.step2_count == base                            # 캐시된 stok 재사용


def test_msg_push_enable_writes_only_that_field_and_verifies(mock, svc):
    cid = _ready(svc, mock)
    mock.switches['motionDetection'] = {'enabled': True, 'msg_push_enabled': False, 'sens': 5}
    r = svc.call('msg_push_on', cid, {'kind': 'motion'}, control=True)
    assert r['ok']
    assert mock.switches['motionDetection'] == {'enabled': True, 'msg_push_enabled': True, 'sens': 5}
    assert _names(mock) == ['getmotionDetectionSwitch', 'setmotionDetectionSwitch',
                            'getmotionDetectionSwitch']


def test_msg_push_refuses_when_detection_off(mock, svc):
    cid = _ready(svc, mock)
    mock.switches['motionDetection'] = {'enabled': False, 'msg_push_enabled': False}
    r = svc.call('msg_push_on', cid, {'kind': 'motion'}, control=True)
    assert r['state'] == 'refused'
    assert 'setmotionDetectionSwitch' not in _names(mock)


# -- 세션(stok) 재사용: 모의 서버 기본값 max_clients=4 -----------------------------------
@pytest.fixture
def mock4():
    with MockVigiServer(variant='full') as m:     # max_clients 기본값(4) 그대로
        yield m


def test_repeated_verify_and_control_reuse_one_session(mock4, svc):
    """연결 확인을 6번 눌러도 카메라 세션은 하나만 쓴다 — 기존에는 4번째에 -10021 로 막혔다."""
    cid = _make(port=mock4.port)
    for _ in range(6):
        out = svc.verify(cid)
        assert out['ok'], out
    assert svc.refresh_capabilities(cid)['ok']
    assert svc.call('ptz_stop', cid, None, control=True)['ok']
    assert len(mock4._stoks) == 1
    assert mock4.step2_count == 1


def test_client_limit_is_reported_as_such_and_never_latches(mock4, svc):
    cid = _make(port=mock4.port)
    for i in range(4):                       # 다른 클라이언트 4개가 세션을 차지
        mock4._stoks['other%d' % i] = mock4.clock()
    out = svc.verify(cid)
    assert not out['ok'] and out['error_class'] == 'client_limit' and out['code'] == -10021
    assert 'too many clients' in out['reason']
    from aot.tests.test_camera_driver_service import _row
    assert _row(cid)['auth_state'] != 'failed' and _row(cid)['auth_state'] != 'locked'
    mock4._stoks.clear()                     # 자리가 나면 곧바로 다시 된다(래치 없음)
    assert svc.verify(cid)['ok']
