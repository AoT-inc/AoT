# coding=utf-8
"""배기·흡기팬 효과의 단위와 도달 한계 (B3 회귀).

· 효과는 **사이클당** native 단위다(`types` R1). 팬은 ACH 로 계산하는데 예전에는
  `ACH/60`(분당)이라 사이클 길이와 무관했다 — 600 초 사이클이면 10 배 과소.
· 환기 계열이므로 실외를 지나칠 수 없다(VPD 는 잘려 있는데 T/RH 는 안 잘렸다).
"""
from types import SimpleNamespace

import pytest

from aot.functions.utils.env_control import effect_functions as ef


def _env(cycle_sec, T_int=30.0, T_ext=20.0, RH_int=50.0, RH_ext=80.0, **kw):
    e = {'T_int': T_int, 'T_ext': T_ext, 'RH_int': RH_int, 'RH_ext': RH_ext,
         'CO2_int': 800.0, 'CO2_ext': 400.0, 'cycle_sec': cycle_sec,
         'vent_open_frac': 0.0}
    e.update(kw)
    return e


def _fan(rated=3000.0, volume=5000.0, calibrated=None):
    meta = {}
    if rated is not None:
        meta['rated_m3h'] = rated
    meta['volume_m3'] = volume
    return SimpleNamespace(kind='exhaust_fan', capacity_meta=meta,
                           calibrated_K=calibrated or {})


@pytest.mark.parametrize('fn,var', [
    (ef.exhaust_fan_temp_effect, 10.0),     # |ΔT| = 10
    (ef.exhaust_fan_humid_effect, 30.0),    # |ΔRH| = 30
    (ef.exhaust_fan_co2_effect, 400.0),     # 초과분 400 ppm
])
def test_effect_is_per_cycle_and_scales_with_cycle_length(fn, var):
    prof = _fan()                            # ACH(100%) = 0.6
    ach = 3000.0 / 5000.0
    m60 = fn(_env(60.0), 100.0, prof).magnitude_native
    m600 = fn(_env(600.0), 100.0, prof).magnitude_native
    assert m60 == pytest.approx(var * ach * 60.0 / 3600.0)
    assert m600 == pytest.approx(var * ach * 600.0 / 3600.0)
    assert m600 == pytest.approx(10.0 * m60)


def test_missing_cycle_sec_keeps_the_reference_60s_behaviour():
    env = _env(60.0)
    env.pop('cycle_sec')
    prof = _fan()
    assert ef.exhaust_fan_temp_effect(env, 100.0, prof).magnitude_native == \
        pytest.approx(ef.exhaust_fan_temp_effect(_env(60.0), 100.0, prof).magnitude_native)


@pytest.mark.parametrize('theta', [1.0, 3.0])
def test_fan_never_overshoots_outdoor_temperature_or_humidity(theta):
    """아주 큰 팬 + 긴 사이클 + 큰 학습 배율에도 |효과| ≤ |구배|."""
    prof = _fan(rated=1.0e6, volume=100.0,
                calibrated={'temperature': theta, 'humidity': theta, 'co2': theta})
    env = _env(600.0)
    t = ef.exhaust_fan_temp_effect(env, 100.0, prof)
    assert t.direction == '↓'
    assert t.magnitude_native == pytest.approx(10.0)          # 30 → 20 (T_ext) 까지만
    assert env['T_int'] - t.magnitude_native >= env['T_ext'] - 1e-9
    h = ef.exhaust_fan_humid_effect(env, 100.0, prof)
    assert h.direction == '↑'
    assert h.magnitude_native == pytest.approx(30.0)          # 50 → 80 (RH_ext) 까지만
    c = ef.exhaust_fan_co2_effect(env, 100.0, prof)
    assert c.magnitude_native == pytest.approx(400.0)         # 외기 농도까지만


def test_unrated_fan_fallback_is_also_bounded_by_the_gradient():
    prof = _fan(rated=None, calibrated={'temperature': 50.0})
    r = ef.exhaust_fan_temp_effect(_env(60.0), 100.0, prof)
    assert r.magnitude_native == pytest.approx(10.0)


def test_intake_fan_shares_the_same_model():
    assert ef.INTAKE_FAN_EFFECT_MODEL['temperature'] is ef.exhaust_fan_temp_effect
