# coding=utf-8
"""CamResult·능력 어휘·오류 분류·이벤트 type 정규화·백오프 수열·registry."""
import random

import pytest

from aot import camera_drivers
from aot.camera_drivers import capabilities as C
from aot.camera_drivers.capabilities import Capabilities
from aot.camera_drivers.driver import (CameraDriver, CamResult, CamState, Credential,
                                       ErrorClass, scrub, short_token)
from aot.camera_drivers.vigi import errors as E
from aot.camera_drivers.vigi.capability_map import normalize_event_type


def test_camresult_states_and_accepted_only_for_ok():
    assert CamResult.ok({'a': 1}).accepted
    for r in (CamResult.refused('x'), CamResult.failed('x'), CamResult.unsupported(),
              CamResult.unverified('x')):
        assert not r.accepted
    assert CamResult.unsupported().state is CamState.UNSUPPORTED


def test_base_driver_returns_unsupported_for_everything():
    d = CameraDriver()
    for r in (d.ptz_move((1, 0)), d.ptz_stop(), d.ptz_goto(1), d.ptz_set_preset(1),
              d.set_day_night('auto'), d.manual_alarm(True), d.device_info(),
              d.verify(Credential('admin', 'pw'))):
        assert r.state is CamState.UNSUPPORTED


def test_credential_repr_hides_password():
    assert 'hunter2' not in repr(Credential('admin', 'hunter2'))


def test_scrub_removes_secrets_and_digests():
    digest = 'a' * 64
    out = scrub('pw=hunter2 resp=%s' % digest, 'hunter2')
    assert 'hunter2' not in out and digest not in out
    assert short_token('abcdef123456') == 'abcd…'


def test_error_classification():
    assert E.classify(0) is ErrorClass.NONE
    assert E.classify(-10020) is ErrorClass.AUTH_FAILED
    assert E.classify(-10021) is ErrorClass.CLIENT_LIMIT
    assert E.classify(-10022) is ErrorClass.LOCKED
    assert E.classify(-40401) is ErrorClass.SESSION_INVALID
    assert E.classify(-99999) is ErrorClass.DEVICE


def test_backoff_sequences_and_jitter():
    class Mid:
        def uniform(self, a, b):
            return 0.0
    b = E.Backoff('client_limit', Mid())
    assert [round(b.next_delay()) for _ in range(6)] == [60, 120, 240, 480, 900, 900]
    n = E.Backoff('network', Mid())
    assert [round(n.next_delay()) for _ in range(8)] == [5, 10, 20, 40, 80, 160, 300, 300]
    j = E.Backoff('network', random.Random(1))
    for i in range(50):
        d = j.next_delay()
        nominal = min(5 * 2 ** i, 300)
        assert 0.8 * nominal <= d <= 1.2 * nominal
    j.reset()
    assert j.attempt == 0


@pytest.mark.parametrize('raw,expected', [
    ('TamperDetection', ('tamper', '')),
    ('tamper_detection', ('tamper', '')),
    ('motionDetection', ('motion', '')),
    ('CrossLineDetection', ('crossline', '')),
    ('invasion_people_enhance', ('intrusion', 'people')),
    ('CrossLineDetection_vehicle_enhance', ('crossline', 'vehicle')),
    ('SomethingNew', ('unknown', '')),
    ('', ('unknown', '')),
    (None, ('unknown', '')),
])
def test_normalize_event_type(raw, expected):
    assert normalize_event_type(raw) == expected


def test_capabilities_json_roundtrip_and_event_kinds():
    c = Capabilities({C.PTZ_PAN_TILT, C.event_cap('tamper'), C.event_cap('motion')},
                     {'ptz.speed_max': 5})
    assert Capabilities.from_json(c.to_json()) == c
    assert c.event_kinds() == ['motion', 'tamper']
    assert not Capabilities.from_json(None).has(C.PTZ_PAN_TILT)


def test_registry_rejects_conflicting_registration():
    class A(CameraDriver):
        vendor = 'zz-test-a'

    class B(CameraDriver):
        vendor = 'zz-test-a'
    camera_drivers.register_driver('zz-test-a', A)
    camera_drivers.register_driver('zz-test-a', A)  # 같은 클래스 재등록은 허용
    with pytest.raises(ValueError):
        camera_drivers.register_driver('zz-test-a', B)
    assert camera_drivers.get_driver_class('zz-test-a') is A
