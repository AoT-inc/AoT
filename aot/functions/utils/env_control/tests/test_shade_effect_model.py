# coding=utf-8
"""차광막 효과 모델 — 열부하(현열)와 증산(잠열)을 함께 본다 (Phase 5b-1, 2026-10-09).

- 기본 경로와 계수 오버라이드 경로가 **같은 함수**다(예전에는 두 벌이라 θ 를 한쪽만 곱했다).
- 막이 막는 몫은 (1 − τ) 다. K 를 2.0 으로 올려 τ = 0.5 에서 예전과 같은 크기다.
- VPD 는 연쇄법칙이 아니라 dVPD = (svp 기울기 − γ·r)·dT 로 직접 — 열면 VPD 는 오르되
  예전보다 덜 오른다(증산이 수증기를 보탠다).
"""
import types

import pytest

from aot.functions.utils.env_control import effect_functions as ef
from aot.utils import psychro as ps


def _env(T=30.0, RH=50.0, solar=600.0, **kw):
    e = {'solar': solar, 'T_int': T, 'RH_int': RH}
    e.update(kw)
    return e


def _prof(tau=None, theta=None, area=None):
    cm = {'shade_transmittance': tau} if tau is not None else {}
    return types.SimpleNamespace(capacity_meta=cm, area_m2=area,
                                 calibrated_K=({'temperature': theta} if theta else None))


class TestPsychrometricConstant:
    def test_value_near_sea_level(self):
        assert ps.psychrometric_constant() == pytest.approx(0.067, abs=0.001)

    def test_scales_with_pressure(self):
        assert ps.psychrometric_constant(p=80.0) < ps.psychrometric_constant()


class TestMagnitudeAndTau:
    def test_same_size_as_before_at_default_tau(self):
        """τ = 0.5 · 600 W/m² · 개도 100 → 예전 K 1.0 과 같은 1.0 °C/사이클."""
        r = ef.SHADE_EFFECT_MODEL['temperature'](_env(), 100.0, None)
        assert r.direction == '↑'
        assert r.magnitude_native == pytest.approx(1.0)

    def test_denser_screen_does_more(self):
        dense = ef.shade_temp_effect(_env(), 100.0, _prof(tau=0.3)).magnitude_native
        thin = ef.shade_temp_effect(_env(), 100.0, _prof(tau=0.7)).magnitude_native
        assert dense > thin
        assert dense == pytest.approx(2.0 * 0.7)

    def test_facility_tau_is_the_fallback(self):
        r = ef.shade_temp_effect(_env(shade_tau_default=0.25), 100.0, None)
        assert r.magnitude_native == pytest.approx(2.0 * 0.75)

    def test_undeclared_facility_does_not_zero_the_effect(self):
        """시설이 막을 선언하지 않으면 시설값이 1.0 — 장치가 있는데 효과 0 을 지어내지 않는다."""
        r = ef.shade_temp_effect(_env(shade_tau_default=1.0), 100.0, None)
        assert r.magnitude_native == pytest.approx(1.0)

    def test_no_sun_no_effect(self):
        m = ef.SHADE_EFFECT_MODEL
        for var in ('temperature', 'vpd', 'humidity'):
            assert m[var](_env(solar=0.0), 100.0, None).magnitude_native == 0.0


class TestOnePathOnly:
    def test_override_path_matches_default(self):
        dflt = ef.build_effect_model('shade', {})
        ovr = ef.build_effect_model('shade', {'K_SHADE_T': ef.K_SHADE_T})
        for var in ('temperature', 'vpd', 'humidity'):
            a = dflt[var](_env(), 70.0, None)
            b = ovr[var](_env(), 70.0, None)
            assert a.direction == b.direction
            assert a.magnitude_native == pytest.approx(b.magnitude_native)

    def test_override_k_scales(self):
        ovr = ef.build_effect_model('shade', {'K_SHADE_T': 4.0})
        assert ovr['temperature'](_env(), 100.0, None).magnitude_native == pytest.approx(2.0)

    def test_theta_applies_on_both_paths(self):
        p = _prof(theta=1.5)
        for model in (ef.build_effect_model('shade', {}),
                      ef.build_effect_model('shade', {'K_SHADE_T': 2.0001})):
            assert model['temperature'](_env(), 100.0, p).magnitude_native == pytest.approx(
                1.5, rel=1e-3)

    def test_vpd_is_declared_not_derived(self):
        """`_inject_vpd` 가 연쇄법칙으로 덮지 않는다."""
        assert ef.build_effect_model('shade', {})['vpd'] is ef.shade_vpd_effect


class TestVpdAndHumidity:
    def test_opening_raises_vpd_but_less_than_the_chain_rule(self):
        env = _env(T=30.0, RH=50.0)
        dT = ef.shade_temp_effect(env, 100.0, None).magnitude_native
        old = ps.svp_slope(30.0) * dT
        new = ef.shade_vpd_effect(env, 100.0, None)
        assert new.direction == '↑'
        assert 0.5 * old < new.magnitude_native < 0.85 * old

    def test_sign_never_flips(self):
        for T in (5.0, 15.0, 25.0, 35.0, 42.0):
            for RH in (20.0, 60.0, 95.0):
                r = ef.shade_vpd_effect(_env(T=T, RH=RH), 100.0, None)
                assert r.direction == '↑', (T, RH)

    def test_stomata_close_at_high_vpd(self):
        """VPD 가 높으면 잠열 몫이 줄어 VPD 효과가 연쇄법칙에 가까워진다."""
        lo = ef.shade_latent_ratio(_env(T=30.0, RH=60.0))
        hi = ef.shade_latent_ratio(_env(T=40.0, RH=15.0))
        assert hi < lo

    def test_humidity_drops_less_than_dry_heating(self):
        env = _env(T=25.0, RH=60.0)
        dT = ef.shade_temp_effect(env, 100.0, None).magnitude_native
        e = ps.vapor_pressure(25.0, 60.0)
        dry = 60.0 - 100.0 * e / ps.svp(25.0 + dT)
        r = ef.shade_humid_effect(env, 100.0, None)
        assert r.direction == '↓'
        assert 0.0 < r.magnitude_native < dry

    def test_unknown_indoor_gives_no_drive(self):
        env = {'solar': 600.0}
        assert ef.shade_vpd_effect(env, 100.0, None).magnitude_native == 0.0
        assert ef.shade_humid_effect(env, 100.0, None).magnitude_native == 0.0
