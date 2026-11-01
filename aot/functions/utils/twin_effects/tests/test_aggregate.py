# coding=utf-8
"""채널 합치기 — 장치 1대는 env_control 과 같아야 하고, 여럿은 용량 규칙을 따른다."""
import pytest

from aot.functions.utils.twin_effects import catalog as C
from aot.functions.utils.twin_effects.aggregate import Device, merge


def _env_ref(kinds_pct, ratings):
    """env_control 이 같은 입력에서 내는 채널 값(비교 기준)."""
    from types import SimpleNamespace
    from aot.functions.utils.env_control.greybox.channels import aggregate_cmds_by_kind, vent_capacities
    cmds = {a: p for a, (k, p) in kinds_pct.items()}
    kinds = {a: k for a, (k, p) in kinds_pct.items()}
    profiles = [SimpleNamespace(actuator_id=a, kind=k, vent_form=None, area_m2=ratings.get(a, {}).get("area_m2"),
                                capacity_meta={"rated_m3h": ratings.get(a, {}).get("rated_m3h") or 0.0})
                for a, (k, p) in kinds_pct.items()]
    return aggregate_cmds_by_kind(cmds, kinds, vent_capacities(profiles))


@pytest.mark.parametrize("kind,ch", [("heater", "heat"), ("cooler", "cool"), ("fogger", "fog"),
                                     ("co2_injector", "co2_inj"), ("shade", "shade"), ("curtain", "curtain")])
def test_single_device_equals_env_control(kind, ch):
    devs = [Device("a", kind, {})]
    got = merge(devs, {"a": 37.0})
    assert got.values[ch] == pytest.approx(_env_ref({"a": (kind, 37.0)}, {})[ch])


def test_vent_equals_env_control_vent_channel_value():
    devs = [Device("w1", "opening", {"area_m2": 20.0}), Device("w2", "roof_vent", {"area_m2": 10.0}),
            Device("f1", "exhaust_fan", {"rated_m3h": 18000.0})]
    pct = {"w1": 50.0, "w2": 0.0, "f1": 100.0}
    ref = _env_ref({"w1": ("opening", 50.0), "w2": ("roof_vent", 0.0), "f1": ("exhaust_fan", 100.0)},
                   {"w1": {"area_m2": 20.0}, "w2": {"area_m2": 10.0}, "f1": {"rated_m3h": 18000.0}})
    got = merge(devs, pct)
    assert got.values["vent"] == pytest.approx(ref["vent"])
    assert got.members["vent"] == ["w1", "w2", "f1"]
    assert not got.assumed


def test_two_heaters_are_capacity_weighted_not_max():
    devs = [Device("h1", "heater", {"rated_kW_thermal": 30.0}), Device("h2", "heater", {"rated_kW_thermal": 10.0})]
    got = merge(devs, {"h1": 0.0, "h2": 100.0})
    assert got.values["heat"] == pytest.approx(25.0)           # 10 kW / 40 kW — env_control 의 최댓값이면 100
    assert _env_ref({"h1": ("heater", 0.0), "h2": ("heater", 100.0)}, {})["heat"] == 100.0


def test_unknown_rating_is_assumed_and_listed():
    devs = [Device("h1", "heater", {"rated_kW_thermal": 20.0}), Device("h2", "heater", {})]
    got = merge(devs, {"h1": 100.0, "h2": 0.0})
    assert got.values["heat"] == pytest.approx(50.0)           # h2 는 알려진 평균 20 kW 로 가정
    assert got.assumed == ["h2"]


def test_vent_default_area_is_listed_as_assumed():
    got = merge([Device("w1", "opening", {})], {"w1": 100.0})
    assert got.assumed == ["w1"]


def test_unmodeled_devices_are_kept_not_dropped():
    devs = [Device("l1", "lighting", {"rated_kW": 5.0}), Device("c1", "circulation_fan", {}),
            Device("x1", "weird_kind", {}), Device("h1", "heater", {"rated_kW_thermal": 10.0})]
    got = merge(devs, {"l1": 100.0, "c1": 100.0, "x1": 100.0, "h1": 50.0})
    assert got.values == {"heat": pytest.approx(50.0)}
    assert [u["actuator_id"] for u in got.unmodeled] == ["l1", "c1", "x1"]
    assert "unknown_kind" in got.unmodeled[2]["effects"]


def test_missing_command_counts_as_zero():
    got = merge([Device("h1", "heater", {"rated_kW_thermal": 10.0})], {})
    assert got.values["heat"] == 0.0


def test_field_irrigation_sums_mm_and_frost_fan_unmodeled():
    devs = [Device("v1", "irrigation_sprinkler", {}), Device("v2", "irrigation_drip", {}),
            Device("ff", "frost_fan", {})]
    got = merge(devs, {"v1": 6.0, "v2": 2.5, "ff": 1.0}, domain=C.FIELD)
    assert got.values == {"irrigation_mm": pytest.approx(8.5)}
    assert [u["kind"] for u in got.unmodeled] == ["frost_fan"]
