# coding=utf-8
"""G5 — lighting actuator 정식 등록 + R2 EnvTarget 분기."""
import pytest

from aot.functions.utils.env_control.types import ACTUATOR_KINDS
from aot.functions.utils.env_control.goal import build_env_target


def test_lighting_in_actuator_kinds():
    assert 'lighting' in ACTUATOR_KINDS


def test_env_target_no_light_when_not_set():
    t = build_env_target()
    assert 'light' not in t


def test_env_target_no_light_when_zero():
    t = build_env_target(Light_target=0)
    assert 'light' not in t


def test_env_target_light_present_when_set():
    t = build_env_target(Light_target=400)
    assert 'light' in t
    assert t['light'].value == 400
    assert t['light'].unit == 'µmol/m²/s'


def test_env_target_vpd_independent_of_light():
    t = build_env_target(VPD_target=1.0, Light_target=400)
    assert 'vpd' in t and 'light' in t
