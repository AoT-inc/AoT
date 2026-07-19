# coding=utf-8
"""G3 — EffectFn 면적·u_eff 가중 검증."""
import pytest
from aot.functions.utils.env_control.effect_functions import (
    opening_temp_effect, opening_humid_effect, opening_co2_effect,
    shade_temp_effect, cooler_temp_effect,
    build_effect_model,
    REFERENCE_OPENING_AREA_M2, REFERENCE_U_EFF,
)
from aot.functions.utils.env_control.types import ActuatorProfile


def _profile(area_m2=None, u_eff=None):
    cap = {}
    if u_eff is not None:
        cap['u_effective'] = u_eff
    return ActuatorProfile(actuator_id='test', kind='opening',
                           area_m2=area_m2, capacity_meta=cap)


# ─── opening_temp_effect ────────────────────────────────────────────────────

def test_opening_temp_no_profile_keeps_v1_magnitude():
    env = {'T_ext': 30.0, 'T_int': 25.0}
    r1 = opening_temp_effect(env, 100.0)              # no profile
    r2 = opening_temp_effect(env, 100.0, profile=None)
    assert r1.magnitude_native == r2.magnitude_native


def test_opening_temp_larger_area_larger_magnitude():
    env = {'T_ext': 30.0, 'T_int': 25.0}
    r_small = opening_temp_effect(env, 100.0, profile=_profile(area_m2=5.0))
    r_large = opening_temp_effect(env, 100.0, profile=_profile(area_m2=20.0))
    assert r_large.magnitude_native > r_small.magnitude_native
    # area 4배 → magnitude 4배 (다른 인자 일정)
    ratio = r_large.magnitude_native / r_small.magnitude_native
    assert 3.9 < ratio < 4.1


def test_opening_temp_unaffected_by_u_eff():
    # 개구부가 열리면 envelope u_eff 는 우회됨 → opening 효과는 u_eff 무관
    env = {'T_ext': 30.0, 'T_int': 25.0}
    r_low_u  = opening_temp_effect(env, 100.0, profile=_profile(u_eff=2.0))
    r_high_u = opening_temp_effect(env, 100.0, profile=_profile(u_eff=8.0))
    assert r_low_u.magnitude_native == r_high_u.magnitude_native


def test_opening_temp_zero_delta_returns_zero():
    env = {'T_ext': 25.0, 'T_int': 25.0}
    r = opening_temp_effect(env, 100.0, profile=_profile(area_m2=20.0))
    assert r.direction == '0'


# ─── opening_co2_effect — only area_factor ─────────────────────────────────

def test_opening_co2_area_only_no_u_factor():
    env = {'CO2_int': 800.0, 'CO2_ext': 400.0}
    r_ref = opening_co2_effect(env, 100.0, profile=_profile(area_m2=10.0, u_eff=8.0))
    r_no  = opening_co2_effect(env, 100.0, profile=_profile(area_m2=10.0))
    # u_eff=8.0 (4보다 큼) 이어도 co2 는 u_factor 무관 → 동일
    assert abs(r_ref.magnitude_native - r_no.magnitude_native) < 1e-6


# ─── shade_temp_effect — area only ──────────────────────────────────────────

def test_shade_area_factor_applied():
    env = {}
    r_small = shade_temp_effect(env, 100.0, profile=_profile(area_m2=5.0))
    r_large = shade_temp_effect(env, 100.0, profile=_profile(area_m2=20.0))
    assert r_large.magnitude_native > r_small.magnitude_native


# ─── cooler — no GIS effect ────────────────────────────────────────────────

def test_cooler_unaffected_by_profile():
    env = {}
    r_no   = cooler_temp_effect(env, 100.0)
    r_big  = cooler_temp_effect(env, 100.0, profile=_profile(area_m2=100.0))
    assert r_no.magnitude_native == r_big.magnitude_native


# ─── build_effect_model with k overrides keeps GIS weighting ──────────────

def test_build_effect_model_opening_with_k_override_still_applies_gis():
    em = build_effect_model('opening', {'K_OPENING_T': 0.16})
    env = {'T_ext': 30.0, 'T_int': 25.0}
    r_small = em['temperature'](env, 100.0, _profile(area_m2=5.0))
    r_large = em['temperature'](env, 100.0, _profile(area_m2=20.0))
    assert r_large.magnitude_native > r_small.magnitude_native


def test_build_effect_model_cooler_accepts_profile_kwarg():
    em = build_effect_model('cooler', {'K_COOLER_T': 3.0})
    env = {}
    # 단순 호출 (profile=None 기본값)
    r1 = em['temperature'](env, 100.0)
    r2 = em['temperature'](env, 100.0, _profile(area_m2=20.0))
    # cooler 는 GIS 가중 적용 안 함 → 동일
    assert r1.magnitude_native == r2.magnitude_native
