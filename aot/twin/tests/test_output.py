# coding=utf-8
from aot.twin import output as O
from aot.twin.types import TargetKind, TwinOutput


def _fac(n=289, with_band=True):
    times = [1000.0 + 600 * k for k in range(n)]
    trio = {"p10": [10.0] * n, "p50": [20.0] * n, "p90": [30.0] * n} if with_band else {"p50": [20.0] * n}
    return TwinOutput(TargetKind.FACILITY, "coord-1", 1000.0, "a3d725da",
                      grids={"fast": times}, quantiles={"fast": {"T": trio}},
                      events={"fast": {"frost": [0.25] * n}},
                      meta={"status": 0, "valid_until": 8200.0, "ensemble_size": 50, "model_rev": 3})


def test_facility_counts_and_channels():
    pts = O.flatten(_fac())
    main = [p for p in pts if p.measurement == "env_twin"]
    assert len(main) == 289 * 3 + 289                       # T p10/50/90 + frost
    assert {p.channel for p in main if p.channel < 50} == {0, 1, 2}
    assert {p.channel for p in main if p.channel >= 50} == {52}
    assert all(p.tags.get("facility") == "a3d725da" for p in main)
    assert {p.device_id for p in pts} == {"coord-1"}


def test_lead_points_fixed_cardinality():
    pts = O.flatten(_fac())
    lead = [p for p in pts if p.measurement == "env_twin_lead"]
    assert {p.tags["lead_h"] for p in lead} == {"1", "3", "6", "12", "24", "48"}
    assert len(lead) == 6 * 4                                # 선행 6 × (T 3 + frost 1)
    p1 = [p for p in lead if p.tags["lead_h"] == "1" and p.channel == 1][0]
    assert p1.timestamp == 1000.0 + 3600


def test_meta_last_and_at_t0():
    pts = O.flatten(_fac())
    assert pts[-1].measurement == "env_twin_meta"            # 머리말은 곡선 뒤 (§7-4 읽기 순서)
    meta = {p.channel: p for p in pts if p.measurement == "env_twin_meta"}
    assert meta[0].value == 0 and meta[1].value == 8200.0 and meta[9].value == 3
    assert all(p.timestamp == 1000.0 for p in meta.values())


def test_quantile_crossing_is_sorted():
    out = _fac(n=3)
    out.quantiles["fast"]["T"] = {"p10": [25.0] * 3, "p50": [20.0] * 3, "p90": [10.0] * 3}
    pts = [p for p in O.flatten(out) if p.measurement == "env_twin" and p.channel < 3 and p.timestamp == 1000.0]
    v = {p.channel: p.value for p in pts}
    assert v[0] <= v[1] <= v[2] and (v[0], v[2]) == (10.0, 25.0)


def test_no_fake_band_when_deterministic():
    pts = O.flatten(_fac(with_band=False))
    assert {p.channel for p in pts if p.measurement == "env_twin" and p.channel < 50} == {1}


def test_nan_and_short_horizon_skipped():
    out = _fac(n=145)                                        # 24 h 경량: 48 h 선행 점은 없다
    out.quantiles["fast"]["T"]["p50"][5] = float("nan")
    pts = O.flatten(out)
    assert not any(p.tags.get("lead_h") == "48" for p in pts)
    assert not any(p.channel == 1 and p.timestamp == 1000.0 + 600 * 5 and p.measurement == "env_twin" for p in pts)


def test_event_probability_clamped():
    out = _fac(n=2)
    out.events["fast"]["frost"] = [1.5, -0.2]
    vals = [p.value for p in O.flatten(out) if p.measurement == "env_twin" and p.channel == 52]
    assert vals == [1.0, 0.0]


def test_field_daily_mapping():
    d = [86400.0 * k for k in range(15)]
    out = TwinOutput(TargetKind.FIELD, "plot-1", 3600.0,
                     grids={"daily": d},
                     quantiles={"daily": {"theta_root": {"p10": [20.0] * 15, "p50": [25.0] * 15, "p90": [30.0] * 15},
                                          "fc": {"p50": [0.4] * 15}}},
                     events={"daily": {"water_deficit": [0.1] * 15}},
                     meta={"status": 1, "valid_until": 1e9, "horizon_d": 14, "obs_n": 1, "irrigation_known": 0})
    pts = O.flatten(out)
    m = {}
    for p in pts:
        m.setdefault(p.measurement, set()).add(p.channel)
    assert m["env_twin_field"] == {0, 1, 2, 60, 70}
    assert m["env_twin_field_meta"] == {0, 1, 2, 20, 22}
    assert {p.tags["lead_d"] for p in pts if p.measurement == "env_twin_field_lead"} == {"1", "3", "7"}
    assert all(p.tags["target"] == "field" for p in pts)
    lead_ch = {p.channel for p in pts if p.measurement == "env_twin_field_lead"}
    assert 60 not in lead_ch and 70 in lead_ch              # fc 는 보관본에 없다(계약 §10.4)
