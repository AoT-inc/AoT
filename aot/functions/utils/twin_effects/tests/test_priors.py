# coding=utf-8
import pytest

from aot.functions.utils.twin_effects import priors as PR
from aot.functions.utils.twin_effects.aggregate import Device


def test_constants_match_the_models_they_stand_in_for():
    from aot.functions.utils.env_control.greybox import model as gb
    from aot.functions.utils.env_control.sim import plant
    assert PR.L_V_J == gb.L_V_J
    assert PR.CO2_KG_M3 == plant.CO2_KG_M3


def test_rating_sums_and_units():
    devs = [Device("h1", "heater", {"rated_kW_thermal": 30.0}), Device("h2", "heater", {"rated_kW_thermal": 10.0}),
            Device("c1", "cooler", {"rated_kW_thermal": 20.0}),
            Device("g1", "co2_injector", {"co2_kg_h": 3.6}),
            Device("f1", "fogger", {"fog_flow_lpm": 6.0, "fog_eta": 0.5})]
    p = PR.grey_priors(devs, volume_m3=1000.0)
    assert p["Q_heat"] == {"value": 40000.0, "basis": "physical"}
    assert p["Q_cool"]["value"] == pytest.approx(20000.0)
    assert p["K_CO2_inj"]["value"] == pytest.approx(3.6 / 3600.0 / (1.83 * 1000.0) * 1e6)
    assert p["m_fog_evap"]["basis"] == "upper_bound"
    assert p["m_fog_evap"]["value"] == pytest.approx(0.1 * 0.5 * 2.45e6)


def test_unknown_ratings_are_left_out_not_guessed():
    p = PR.grey_priors([Device("h1", "heater", {}), Device("g1", "co2_injector", {"co2_kg_h": 1.0})], volume_m3=None)
    assert p == {}
