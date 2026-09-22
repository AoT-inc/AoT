# coding=utf-8
"""습공기 계산과 분무 증발 — 계획서 env-mpc-reinforcement 4.1 의 단위 테스트.

보존(질량·엔탈피), 한계(노즐·공기), 포화 공기, 출구 온도 하한, 2차 보정, 그리고
습공기 선도의 알려진 값.
"""
import pytest

from aot.functions.utils.env_control import psychro as ps
from aot.functions.utils.env_control.situation import svp as situation_svp


# ── 기본 상태량 — 선도 값과 대조 ────────────────────────────────────────────

def test_svp_matches_the_rest_of_the_codebase():
    for T in (0.0, 12.0, 25.0, 38.0):
        assert ps.svp(T) == pytest.approx(situation_svp(T))


def test_known_values():
    assert ps.svp(20.0) == pytest.approx(2.338, abs=0.005)
    assert ps.humidity_ratio(ps.vapor_pressure(20.0, 50.0)) == pytest.approx(0.00726, abs=0.0001)
    assert ps.pressure_from_elevation(1000.0) == pytest.approx(89.87, abs=0.05)
    assert ps.pressure_from_elevation(None) == ps.P_STD_KPA


# 기준값: PsychroLib 2.5.0(ASHRAE Handbook 식) `GetTWetBulbFromRelHum(T, RH, 101325)`.
# ⚠ Stull(2011) 근사식은 ±0.3~0.6 °C 라 기준으로 쓰지 않는다 — 35 °C·30 % 에서 22.14 를
#   내 이 테스트를 한 번 틀리게 만들었다.
@pytest.mark.parametrize('T,RH,wb', [(25.0, 50.0, 17.889), (30.0, 40.0, 20.064),
                                      (35.0, 30.0, 21.524), (20.0, 80.0, 17.679)])
def test_adiabatic_saturation_matches_ashrae_wet_bulb(T, RH, wb):
    w = ps.humidity_ratio(ps.vapor_pressure(T, RH))
    assert ps.adiabatic_saturation_temperature(T, w) == pytest.approx(wb, abs=0.05)


def test_saturated_air_is_its_own_adiabatic_saturation():
    w = ps.w_sat(20.0)
    assert ps.adiabatic_saturation_temperature(20.0, w) == pytest.approx(20.0, abs=1e-6)


def test_enthalpy_roundtrip():
    w = 0.01
    assert ps.temperature_from_enthalpy(ps.enthalpy(27.3, w), w) == pytest.approx(27.3)


def test_altitude_changes_the_humidity_ratio():
    """해발 1,000 m 면 같은 수증기압의 습도비가 약 11 % 크다."""
    e = ps.vapor_pressure(25.0, 50.0)
    r = ps.humidity_ratio(e, ps.pressure_from_elevation(1000.0)) / ps.humidity_ratio(e)
    assert r == pytest.approx(1.13, abs=0.03)


# ── 분무 증발 ───────────────────────────────────────────────────────────────

def _run(**kw):
    base = dict(T_in=35.0, RH_in=30.0, m_da=1.0, m_w=0.005, eta=0.9, eps=0.9)
    base.update(kw)
    return ps.evaporate(**base)


def test_mass_is_conserved():
    r = _run()
    assert 1.0 * (r.w_out - r.w_in) == pytest.approx(r.E, rel=1e-9)
    assert r.E + r.unevaporated == pytest.approx(0.005)


def test_energy_is_conserved():
    """ṁ_da·h_in + E·h_물(T_물) = ṁ_da·h_out."""
    Tw = 15.0
    r = _run(T_water=Tw)
    h_in = ps.enthalpy(35.0, r.w_in)
    h_out = ps.enthalpy(r.T_out, r.w_out)
    assert h_in + r.E * ps.CP_W * Tw == pytest.approx(h_out, abs=1e-6)


def test_evaporation_cools_and_humidifies_at_once():
    r = _run()
    assert r.T_out < 35.0 and r.RH_out > 30.0


def test_spray_limited_when_water_is_scarce():
    r = _run(m_w=0.001)
    assert r.limited_by == 'spray' and r.E == pytest.approx(0.9 * 0.001)


def test_air_limited_when_water_is_plenty():
    """물이 넘치면 공기가 받을 수 있는 만큼만 — 나머지는 못 날린 물(잎 젖음)."""
    r = _run(m_w=0.1)
    assert r.limited_by == 'air'
    assert r.unevaporated > 0.05


def test_outlet_never_goes_below_the_adiabatic_saturation_temperature():
    r = _run(m_w=1.0, eps=1.0, eta=1.0)
    assert r.T_out >= r.T_as - 0.05
    assert r.RH_out == pytest.approx(100.0, abs=0.5)


def test_saturated_air_cannot_evaporate():
    r = _run(RH_in=100.0)
    assert r.E == pytest.approx(0.0, abs=1e-9)
    assert r.T_out == pytest.approx(35.0, abs=1e-6)


def test_no_airflow_means_no_evaporation():
    """모르는 풍량을 지어내지 않는다."""
    r = _run(m_da=0.0)
    assert r.E == 0.0 and r.limited_by == 'none' and r.unevaporated == 0.005


def test_latent_heat_dominates_water_temperature():
    """물 온도는 2차다 — 15 °C 와 25 °C 물의 출구 온도 차가 작다."""
    cold = _run(T_water=15.0)
    warm = _run(T_water=25.0)
    drop = 35.0 - cold.T_out
    assert abs(cold.T_out - warm.T_out) < 0.05 * drop


def test_second_order_term_is_off_by_default_and_zero_at_wet_bulb():
    r0 = _run(m_w=0.1)
    r1 = _run(m_w=0.1, include_unevaporated_sensible=True, T_water=r0.T_as)
    assert r1.T_out == pytest.approx(r0.T_out, abs=1e-6)
    r2 = _run(m_w=0.1, include_unevaporated_sensible=True, T_water=12.0)
    assert r2.T_out < _run(m_w=0.1, T_water=12.0).T_out, '차가운 잔여 물은 공기에서 열을 더 가져간다'


def test_dry_air_mass_flow():
    """1 m³/s · 25 °C · 해면 → 약 1.17 kg_da/s."""
    e = ps.vapor_pressure(25.0, 50.0)
    assert ps.dry_air_mass_flow(1.0, 25.0, e) == pytest.approx(1.17, abs=0.02)


# ── PI 분무 효과가 psychro 를 쓴다 (2026-09-22) ─────────────────────────────

def _fog_env(T=30.0, RH=60.0):
    return {'T_int': T, 'RH_int': RH, 'cycle_sec': 600.0}


def _fog_profile(flow=10.0, vol=1000.0, wetting=False):
    from types import SimpleNamespace
    return SimpleNamespace(
        kind='fogger', cmd_constraints=None,
        capacity_meta={'fog_flow_lpm': flow, 'volume_m3': vol,
                       'nozzle': {'wetting': wetting}})


def test_fog_effects_come_from_one_evaporation():
    """온도·습도·VPD 가 같은 증발 한 번에서 나온다 — 따로 추정하지 않는다."""
    from aot.functions.utils.env_control.effect_functions import (
        fogger_humid_effect, fogger_temp_effect, fogger_vpd_effect)
    env, prof = _fog_env(), _fog_profile(flow=1.0)
    dT = -fogger_temp_effect(env, 100.0, prof).magnitude_native
    dRH = fogger_humid_effect(env, 100.0, prof).magnitude_native
    dV = -fogger_vpd_effect(env, 100.0, prof).magnitude_native
    e0 = ps.vapor_pressure(30.0, 60.0)
    e1 = ps.vapor_pressure(30.0 + dT, 60.0 + dRH)
    assert dV == pytest.approx(ps.vpd(30.0 + dT, e1) - ps.vpd(30.0, e0), abs=1e-3)


def test_fog_humidity_counts_the_rh_rise_from_cooling():
    """증발로 식으면서 RH 가 더 오른다 — 수분만 센 RH 상승보다 커야 한다."""
    from aot.functions.utils.env_control.effect_functions import fogger_humid_effect
    env, prof = _fog_env(), _fog_profile(flow=1.0)
    dRH = fogger_humid_effect(env, 100.0, prof).magnitude_native
    p = ps.P_STD_KPA
    e0 = ps.vapor_pressure(30.0, 60.0)
    kg = 1.0 * 600.0 / 60.0 * 0.9
    m_da = ps.dry_air_density(30.0, e0, p) * 1000.0
    w1 = ps.humidity_ratio(e0, p) + kg / m_da
    moisture_only = ps.relative_humidity(30.0, ps.vapor_pressure_from_ratio(w1, p)) - 60.0
    assert dRH > moisture_only


def test_fog_humidity_is_no_longer_ten_times_too_small():
    """옛 근사(ΔRH = L×1000/vol×0.5)는 실제의 약 1/10 이었다."""
    from aot.functions.utils.env_control.effect_functions import fogger_humid_effect
    env, prof = _fog_env(25.0, 50.0), _fog_profile(flow=0.1)   # 1 L / 사이클
    old = 1.0 * 1000.0 / 1000.0 * 0.5
    new = fogger_humid_effect(env, 100.0, prof).magnitude_native
    assert new > 5 * old


def test_fog_capacity_is_the_adiabatic_limit_not_the_current_temperature():
    """물이 넘치면 공기는 단열포화까지만 받는다 — 지금 온도의 포화보다 적다."""
    from aot.functions.utils.env_control.effect_functions import fogger_temp_effect
    env, prof = _fog_env(30.0, 60.0), _fog_profile(flow=500.0, vol=100.0)
    dT = fogger_temp_effect(env, 100.0, prof).magnitude_native
    w = ps.humidity_ratio(ps.vapor_pressure(30.0, 60.0))
    assert 30.0 - dT >= ps.adiabatic_saturation_temperature(30.0, w) - 0.05


def test_fog_without_flow_falls_back_to_the_constant():
    from aot.functions.utils.env_control.effect_functions import (
        K_FOG_T, fogger_temp_effect)
    from types import SimpleNamespace
    prof = SimpleNamespace(kind='fogger', cmd_constraints=None, capacity_meta={})
    r = fogger_temp_effect(_fog_env(30.0, 40.0), 100.0, prof)
    assert r.magnitude_native == pytest.approx(K_FOG_T)
