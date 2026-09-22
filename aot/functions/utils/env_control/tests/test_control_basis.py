# coding=utf-8
"""제어 기준 — 온도 우선 모드(`basis.py`).

온도를 1차로 좇고, VPD 목표는 그 온도에서의 습도 목표로 바꾼다. VPD 는 경계를
넘은 사이클에만 경계 항으로 든다. 단계에 온도가 없으면 온도는 밴드로만 다룬다.
"""
import pytest

from aot.functions.utils.env_control.basis import (
    VPD_BAND_ABOVE, VPD_BAND_BELOW, build_temperature_env_target,
    temperature_basis)
from aot.functions.utils.env_control.situation import _decompose_vpd, compute_vpd

GUIDE = (15.0, 30.0, 40.0, 90.0)


def test_humidity_target_reproduces_the_vpd_target_at_the_temperature_target():
    b = temperature_basis(1.0, 24.0, 27.0, 60.0, GUIDE)
    assert b['T_target'] == 24.0 and b['T_mode'] == 'stage'
    assert compute_vpd(b['T_target'], b['RH_target']) == pytest.approx(1.0, abs=0.01)


def test_humidity_target_uses_the_temperature_target_not_the_current_one():
    """기준 온도가 지금 온도면 온도가 흔들릴 때마다 습도 목표가 흔들린다(D1)."""
    a = temperature_basis(1.0, 24.0, 20.0, 60.0, GUIDE)
    b = temperature_basis(1.0, 24.0, 29.0, 60.0, GUIDE)
    assert a['RH_target'] == b['RH_target']


def test_without_a_stage_temperature_the_band_holds_still():
    """유도 범위 안이면 목표 = 지금 온도 → 편차 0. 중앙값(22.5)을 좇지 않는다."""
    b = temperature_basis(1.0, None, 27.0, 60.0, GUIDE)
    assert b['T_mode'] == 'band' and b['T_target'] == 27.0


def test_band_mode_pulls_back_only_at_the_edge():
    b = temperature_basis(1.0, None, 33.0, 60.0, GUIDE)
    assert b['T_target'] == 30.0


def test_unreachable_humidity_is_clamped_to_the_guide():
    """12 °C 에서 VPD 1.0 은 RH 29 % — 유도 하한 40 % 로 자른다."""
    b = temperature_basis(1.0, 12.0, 12.0, 80.0, (10.0, 30.0, 40.0, 90.0))
    assert b['RH_target'] == 40.0 and b['RH_clamped']


def test_vpd_band():
    b = temperature_basis(1.0, 24.0, 24.0, 60.0, GUIDE)
    assert b['vpd_band'] == (round(1.0 - VPD_BAND_BELOW, 3), round(1.0 + VPD_BAND_ABOVE, 3))


def test_vpd_enters_only_outside_the_band_and_as_a_limit():
    b = temperature_basis(1.0, 24.0, 24.0, 60.0, GUIDE)
    inside = build_temperature_env_target(b, 1.2, None, 100.0, 0.8)
    assert 'vpd' not in inside
    high = build_temperature_env_target(b, 2.5, None, 100.0, 0.8)
    assert high['vpd'].value == b['vpd_band'][1] and high['vpd'].limit
    low = build_temperature_env_target(b, 0.2, None, 100.0, 0.8)
    assert low['vpd'].value == b['vpd_band'][0]


def test_temperature_leads_humidity():
    b = temperature_basis(1.0, 24.0, 24.0, 60.0, GUIDE)
    t = build_temperature_env_target(b, 1.0, None, 100.0, 0.8)
    assert t['temperature'].priority > t['humidity'].priority


def test_a_vpd_limit_does_not_demote_temperature_and_humidity():
    """VPD 직접 모드에선 VPD 가 오면 온·습도를 제약으로 강등한다 — 경계 항은 아니다."""
    b = temperature_basis(1.0, 24.0, 24.0, 60.0, GUIDE)
    t = build_temperature_env_target(b, 2.5, None, 100.0, 0.8)
    out = _decompose_vpd(t, {'VPD_int': 2.5})
    assert 'temperature' in out and 'humidity' in out and 'vpd' in out
