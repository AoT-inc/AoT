# coding=utf-8
"""greybox 모델 v2 — 수증기압 상태·증산·광합성·풍속·차광(계획서 env-mpc-reinforcement A).

보존과 극한: 환기가 없으면 수증기량이 그대로, 환기가 크면 외기로 수렴, 가온하면
RH 가 내려간다. v1 은 수분을 상대습도 차로 섞어 이 셋을 틀렸다.
"""
import pytest

from aot.functions.utils.env_control import psychro as ps
from aot.functions.utils.env_control.greybox.model import predict_horizon, step
from aot.functions.utils.env_control.greybox.params import GreyboxParams


def _p(**kw):
    p = GreyboxParams(volume_m3=1000.0, k_transp=0.0, k_photo=0.0, Q_plant_base=0.0,
                      alpha_sol=0.0)
    for k, v in kw.items():
        setattr(p, k, v)
    return p


EXT = {'T_ext': 20.0, 'RH_ext': 60.0, 'CO2_ext': 400.0, 'solar': 0.0, 'wind': 0.0}


def _ah(T, RH):
    return ps.vapor_pressure(T, RH) * 1000.0 / (461.5 * (T + 273.15))


def test_closed_house_keeps_its_water():
    """환기·분무·증산이 없으면 온도가 바뀌어도 수증기량은 그대로다(이슬점 위에서)."""
    p = _p(tau_T=3600.0)
    T, RH, _ = step(25.0, 60.0, 400.0, dict(EXT, T_ext=20.0), {}, p, 600.0)
    assert 20.0 < T < 25.0
    assert _ah(T, RH) == pytest.approx(_ah(25.0, 60.0), rel=1e-3)


def test_cooling_below_the_dew_point_condenses():
    """이슬점(25 °C·60 % → 16.7 °C) 아래로 식으면 포화에서 맺힌다 — RH 100 %."""
    p = _p()
    T, RH, _ = step(25.0, 60.0, 400.0, dict(EXT, T_ext=10.0), {}, p, 1800.0)
    assert T < 16.0
    assert RH == pytest.approx(100.0, abs=0.01)
    assert _ah(T, RH) < _ah(25.0, 60.0)


def test_heating_lowers_rh():
    """v1 은 이것을 무시했다 — 가온하면 RH 가 내려간다."""
    p = _p(UA_eff=100.0, tau_T=3600.0, Q_heat=5000.0)
    T, RH, _ = step(20.0, 80.0, 400.0, dict(EXT, T_ext=20.0), {'heat': 100.0}, p, 600.0)
    assert T > 20.0 and RH < 80.0
    assert _ah(T, RH) == pytest.approx(_ah(20.0, 80.0), rel=1e-3)


def test_extreme_heating_does_not_blow_up_humidity():
    """온도가 물리 범위에서 잘려도 수분은 발산하지 않는다(e 직접 적분 때의 실패)."""
    p = _p(UA_eff=10.0)
    T, RH, _ = step(20.0, 80.0, 400.0, dict(EXT, T_ext=20.0), {'heat': 100.0}, p, 600.0)
    assert T == pytest.approx(60.0) and RH < 20.0


def test_strong_ventilation_converges_to_outdoor_water():
    p = _p(m_vent_coef=50.0)
    traj = predict_horizon(25.0, 90.0, 900.0, [EXT] * 30, [{'vent': 100.0}] * 30, p, 60.0)
    T, RH, CO2 = traj[-1]
    assert _ah(T, RH) == pytest.approx(_ah(20.0, 60.0), rel=0.05)
    assert CO2 == pytest.approx(400.0, abs=10.0)


def test_cold_humid_outdoor_air_can_dry_the_house():
    """외기 RH 90 % 라도 5 °C 면 수증기가 적다 — 섞이는 것은 수증기량이다.

    v1(상대습도 차로 혼합)은 RH_ext 90 > RH 70 이라 실내를 적신다고 예측했다.
    """
    p = _p(m_vent_coef=2.0, UA_eff=10.0, tau_T=3600.0)
    ext = dict(EXT, T_ext=5.0, RH_ext=90.0)
    T, RH, _ = step(18.0, 70.0, 400.0, ext, {'vent': 100.0}, p, 300.0)
    assert _ah(T, RH) < _ah(18.0, 70.0)


def test_fog_cools_and_humidifies_from_the_same_evaporation():
    # 1,000 m³ 공기 열용량 ≈ 1.2 MJ/K (tau_T·UA_eff) — 한 번 분무에 1 °C 남짓
    p = _p(m_fog_evap=20000.0, UA_eff=100.0, tau_T=12000.0)
    T, RH, _ = step(30.0, 50.0, 400.0, dict(EXT, T_ext=30.0), {'fog': 100.0}, p, 60.0)
    dT_energy = 30.0 - T
    added_kg = (_ah(T, RH) - _ah(30.0, 50.0)) * 1000.0
    # 잠열로 뺀 열 ≈ 더해진 물 × L_v (열용량 = tau_T·UA_eff)
    assert dT_energy * p.tau_T * p.UA_eff == pytest.approx(added_kg * 2.45e6, rel=0.05)


def test_fog_stops_at_saturation():
    p = _p(m_fog_evap=20000.0)
    T, RH, _ = step(25.0, 100.0, 400.0, dict(EXT, T_ext=25.0), {'fog': 100.0}, p, 60.0)
    assert T == pytest.approx(25.0, abs=0.01) and RH == pytest.approx(100.0, abs=0.01)


def test_transpiration_adds_water_more_by_day():
    p = _p(k_transp=5e-4)
    night = step(25.0, 60.0, 400.0, dict(EXT, T_ext=25.0, solar=0.0), {}, p, 600.0)
    day = step(25.0, 60.0, 400.0, dict(EXT, T_ext=25.0, solar=600.0), {}, p, 600.0)
    base = _ah(25.0, 60.0)
    assert _ah(*night[:2]) > base
    assert _ah(*day[:2]) - base > 3 * (_ah(*night[:2]) - base)


def test_shade_cuts_solar_gain():
    p = _p(alpha_sol=50.0, tau_shade=0.3)
    ext = dict(EXT, T_ext=25.0, solar=800.0)
    open_ = step(25.0, 60.0, 400.0, ext, {'shade': 100.0}, p, 600.0)[0]
    shut = step(25.0, 60.0, 400.0, ext, {'shade': 0.0}, p, 600.0)[0]
    none = step(25.0, 60.0, 400.0, ext, {}, p, 600.0)[0]
    assert (shut - 25.0) == pytest.approx(0.3 * (open_ - 25.0), rel=0.02)
    assert none == pytest.approx(open_), '차광막 입력이 없으면 걷힌 것으로 본다'


def test_photosynthesis_draws_co2_by_day():
    p = _p(k_photo=0.1)
    day = step(25.0, 60.0, 800.0, dict(EXT, solar=500.0), {}, p, 600.0)[2]
    night = step(25.0, 60.0, 800.0, dict(EXT, solar=0.0), {}, p, 600.0)[2]
    assert day < night == pytest.approx(800.0)


def test_wind_boosts_ventilation():
    p = _p(m_vent_coef=0.5)
    calm = step(25.0, 60.0, 900.0, dict(EXT, wind=0.0), {'vent': 50.0}, p, 600.0)[2]
    windy = step(25.0, 60.0, 900.0, dict(EXT, wind=6.0), {'vent': 50.0}, p, 600.0)[2]
    assert windy < calm


def test_v1_params_are_revalidated():
    """옛 판 파라미터는 학습 횟수·오차를 버린다 — 옛 오차로 새 모델을 통과시키지 않는다."""
    old = {'UA_eff': 900.0, 'n_updates': 115, 'rmse_T': 0.15, 'rmse_RH': 0.8}
    p = GreyboxParams.from_dict(old)
    assert p.UA_eff == 900.0 and p.n_updates == 0 and p.rmse_T == 999.0
    again = GreyboxParams.from_dict(p.to_dict())
    assert again.model_version == GreyboxParams().model_version


def test_identification_recovers_transpiration():
    from aot.functions.utils.env_control.greybox.identification import fit
    truth = _p(k_transp=4e-4, m_vent_coef=0.3)
    import math
    states, exts, cmds = [(24.0, 60.0, 400.0)], [], []
    for i in range(160):
        ext = dict(EXT, T_ext=22.0, solar=max(0.0, 600.0 * math.sin(i / 25.0)))
        c = {'vent': 30.0 if (i // 20) % 2 else 0.0}
        states.append(step(*states[-1], ext, c, truth, 60.0))
        exts.append(ext); cmds.append(c)
    got = fit(states, exts, cmds, dt=60.0, prev_params=_p(k_transp=1e-4, m_vent_coef=0.3),
              prior_weight=0.0)
    assert got is not None
    assert got.k_transp == pytest.approx(4e-4, rel=0.2)
