# coding=utf-8
"""축별 기능 상태(1단계) — 장치 조합 × 측정 유무.

1단계는 계산·기록·표시만 한다. 여기서는 판정 표가 맞는지와, 기존 판정과
갈리는 곳(VPD)이 실제로 드러나는지를 본다.
"""
from types import SimpleNamespace as NS

from aot.functions.utils.env_control.authority import derive_authority
from aot.functions.utils.env_control.capability import (
    AXES, STATE_BLIND, STATE_CONTROL, STATE_NONE, STATE_OBSERVE_ONLY,
    STATE_ONE_WAY_DOWN, STATE_ONE_WAY_UP, assess_capability,
    capability_signature, compare_with_legacy, measured_axes)

ALL = {'T': 20.0, 'RH': 60.0, 'CO2': 400.0, 'light': 100.0}


def _p(kind, aid=None):
    return NS(kind=kind, actuator_id=aid or kind)


def _cap(kinds, internal=ALL, **kw):
    return assess_capability([_p(k) for k in kinds],
                             measured=measured_axes(internal), **kw)


def test_heater_and_opening_control_temperature_both_ways():
    c = _cap(['heater', 'opening'])
    assert c['temperature']['state'] == STATE_CONTROL
    assert c['temperature']['up'] == 'ACTIVE'
    assert c['temperature']['down'] == 'PASSIVE'


def test_heater_only_is_one_way_up():
    assert _cap(['heater'])['temperature']['state'] == STATE_ONE_WAY_UP


def test_opening_only_is_one_way_down_for_humidity():
    assert _cap(['opening'])['humidity']['state'] == STATE_ONE_WAY_DOWN


def test_sensor_without_device_is_observe_only():
    assert _cap(['heater'])['co2']['state'] == STATE_OBSERVE_ONLY


def test_device_without_sensor_is_blind():
    c = _cap(['co2_injector'], internal={'T': 20.0, 'RH': 60.0})
    assert c['co2']['state'] == STATE_BLIND
    assert c['co2']['measured'] is False


def test_neither_is_none():
    c = _cap(['heater'], internal={'T': 20.0})
    assert c['co2']['state'] == STATE_NONE


def test_unknown_measurement_is_none_not_false():
    """판정이 없던 사이클에 False 를 지어내면 BLIND 로 거짓말한다."""
    c = assess_capability([_p('co2_injector')], measured=None)
    assert c['co2']['measured'] is None
    assert c['co2']['state'] == STATE_ONE_WAY_UP


def test_fogger_only_can_lower_vpd():
    """기존 판정은 VPD 를 온도 등급으로 근사해 이것을 못 본다(계획서 D1)."""
    c = _cap(['fogger'])
    assert c['vpd']['down'] == 'ACTIVE'
    assert c['vpd']['state'] == STATE_ONE_WAY_DOWN


def test_vpd_needs_temperature_and_humidity():
    m = measured_axes({'T': 20.0})
    assert m['vpd'] is False
    assert measured_axes({'T': 20.0, 'RH': 50.0})['vpd'] is True


def test_light_estimate_counts_as_measured():
    assert measured_axes({'light_est': 300.0})['light'] is True


def test_devices_are_named():
    c = assess_capability([_p('heater', 'h1')], measured=measured_axes(ALL),
                          names={'h1': '난방기 1'})
    assert c['temperature']['devices_up'] == ['난방기 1']


def test_excluded_device_is_listed_on_its_axes_only():
    c = _cap(['opening'], excluded=[{'name': '보일러', 'kind': 'heater',
                                     'reason': 'disabled'}])
    assert c['temperature']['excluded'] == [{'name': '보일러', 'reason': 'disabled'}]
    assert c['co2']['excluded'] == []


def test_commissioning_flags_are_evidence_not_downgrade():
    """1단계는 등급을 깎지 않는다 — 판정은 근거로만 싣는다."""
    c = assess_capability(
        [_p('heater', 'h1')], measured=measured_axes(ALL),
        commissioning_state={'k_upper_bounds': {'h1': {'var': 'T', 'ratio': 0.5}}})
    assert c['temperature']['up'] == 'ACTIVE'
    assert c['temperature']['flags'] == [{'name': 'heater', 'flag': 'device_fault'}]


def test_every_axis_is_present():
    assert set(_cap([])) == set(AXES)


def test_signature_changes_with_state():
    a = capability_signature(_cap(['heater']))
    b = capability_signature(_cap(['heater', 'opening']))
    assert a != b


def test_legacy_comparison_reports_the_vpd_gap():
    """분무기만 있는 시설: VPD 내림이 기존은 PASSIVE(증발 냉각), 새는 ACTIVE(가습)."""
    profiles = [_p('fogger')]
    cap = _cap(['fogger'])
    diffs = compare_with_legacy(cap, derive_authority(profiles), [], ['vpd'])
    assert diffs == ['vpd down: 기존=PASSIVE / 새=ACTIVE']


def test_legacy_comparison_is_quiet_when_they_agree():
    profiles = [_p('heater'), _p('opening')]
    cap = _cap(['heater', 'opening'])
    assert compare_with_legacy(cap, derive_authority(profiles), [],
                               ['temperature', 'humidity']) == []


def test_side_effect_only_axis_without_sensor_is_none_not_blind():
    """창은 CO₂ 를 부수적으로 내린다 — 주입기가 없으면 CO₂ 센서 없음을 떠들지 않는다."""
    c = _cap(['opening'], internal={'T': 20.0, 'RH': 60.0})
    assert c['co2']['down'] == 'PASSIVE'
    assert c['co2']['state'] == STATE_NONE
