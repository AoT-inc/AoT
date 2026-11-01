# coding=utf-8
"""시설 부품(그레이박스 + UKF)을 엔진에 끼워 시험한다. 자료는 쌍둥이 실험(facility_twin 시험)에서 만든다."""
import math

import numpy as np
import pytest

from aot.functions.utils.env_control.greybox.params import GreyboxParams
from aot.functions.utils.facility_twin.tests.test_facility_twin import GP, _twin_truth
from aot.twin import bench, engine, models
from aot.twin.models import facility_greybox as FG
from aot.twin.types import Provenance, SeriesRef, Status, TargetKind, TargetSpec
from .helpers import MemSource

CAP = bench.Capability("full", 6, 0.25, 3600.0, 0.0)
M, V = Provenance.MEASURED, Provenance.VIRTUAL


def _data(hours=30, theta_ua=1.4, seed=5):
    t0, t1, obs, ext, cmd = _twin_truth(hours, np.random.default_rng(seed), theta=(theta_ua, 1, 1, 1, 1))
    src = {}
    for k, (u, ch) in {"T": ("in", 0), "RH": ("in", 1), "CO2": ("in", 2)}.items():
        src[(u, k, ch)] = list(zip(*obs[k]))
    for k, ch in (("T_ext", 0), ("RH_ext", 1), ("solar", 2), ("wind", 3)):
        src[("out", k, ch)] = list(zip(*ext[k]))
    for k, ch in (("vent", 0), ("heat", 1)):
        src[("act", k, ch)] = list(zip(*cmd[k]))
    return t1, src


def _spec(prov=M, ctl_prov=M, controls=True, **opts):
    inputs = {"T_int": SeriesRef("in", "T", 0, prov), "RH_int": SeriesRef("in", "RH", 1, prov),
              "CO2_int": SeriesRef("in", "CO2", 2, prov),
              "T_ext": SeriesRef("out", "T_ext", 0, prov), "RH_ext": SeriesRef("out", "RH_ext", 1, prov),
              "solar": SeriesRef("out", "solar", 2, prov), "wind": SeriesRef("out", "wind", 3, prov)}
    ctl = {"vent": SeriesRef("act", "vent", 0, ctl_prov), "heat": SeriesRef("act", "heat", 1, ctl_prov)} if controls else {}
    o = {"greybox": GP.to_dict(), "sync_window_h": 28, "filter_dt_s": 300.0, "obs_sd": {"T": 0.15, "RH": 1.5, "CO2": 15.0}}
    o.update(opts)
    return TargetSpec("dev", TargetKind.FACILITY, "coord-1", facility="a3d725da", inputs=inputs, controls=ctl, options=o)


def _run(spec, data, now):
    return engine.run_target(spec, MemSource(data), models.get("facility"), CAP, now)


def test_default_facility_model_is_greybox_and_constants_match():
    from aot.functions.utils.facility_twin.model import MODEL_REV, PARAM_NAMES
    assert isinstance(models.get("facility"), FG.FacilityGreyboxTwin)
    assert FG.MODEL_REV == MODEL_REV and FG.PARAM_NAMES == PARAM_NAMES
    from aot.functions.utils.facility_twin.sync import DEFAULT_CMDS
    assert FG.CONTROL_NAMES == tuple(DEFAULT_CMDS)


def test_synced_run_publishes_bands_and_sync_meta():
    now, data = _data()
    r = _run(_spec(), data, now + 60)
    assert r.status in (Status.OK, Status.DEGRADED), r.reason
    o = r.output
    assert o.meta["valid_until"] > o.t0
    assert o.meta["sync_rmse_T_1h"] < 2.0
    q = o.quantiles["fast"]
    assert set(q) >= {"T", "RH", "VPD", "CO2"}
    n = len(o.grids["fast"])
    for var in q:
        for k in range(n):
            assert q[var]["p10"][k] <= q[var]["p50"][k] <= q[var]["p90"][k]
    assert o.meta["ensemble_size"] == 6 and o.meta["model_rev"] == FG.MODEL_REV
    assert all(0.0 <= p <= 1.0 for ev in o.events["fast"].values() for p in ev)
    assert r.info["theta"]["theta_UA"] > 1.1                       # 참값 1.4 배 쪽으로 학습


def test_same_seed_same_output():
    now, data = _data()
    a = _run(_spec(), data, now + 60).output
    b = _run(_spec(), data, now + 60).output
    assert a.quantiles["fast"]["T"]["p50"] == b.quantiles["fast"]["T"]["p50"]


def test_no_actuator_feedback_is_not_twinnable():
    now, data = _data()
    r = _run(_spec(controls=False), data, now + 60)
    assert r.status == Status.NOT_TWINNABLE and "장치" in r.reason
    assert r.output.meta["valid_until"] == r.output.t0              # 즉시 만료(계약 §7-3)


def test_provenance_labels_are_not_a_gate():
    """출처 표시는 판정에 쓰지 않는다 — 미러 센서는 현장 실측의 사본이고 위치로 정해진다(2026-10-26)."""
    now, data = _data()
    assert _run(_spec(ctl_prov=V), data, now + 60).status != Status.NOT_TWINNABLE
    assert _run(_spec(prov=Provenance.MIRROR), data, now + 60).status != Status.NOT_TWINNABLE


def test_stale_observations_are_unsynced():
    now, data = _data()
    r = _run(_spec(), data, now + 3 * 3600)
    assert r.status == Status.UNSYNCED and "낡음" in r.reason


def test_short_history_cannot_judge_agreement():
    now, data = _data(hours=3)
    r = _run(_spec(sync_window_h=3), data, now + 60)
    assert r.status == Status.UNSYNCED


def test_missing_solar_is_flagged_degraded():
    now, data = _data()
    spec = _spec()
    del spec.inputs["solar"]
    r = _run(spec, data, now + 60)
    assert r.status in (Status.DEGRADED, Status.UNSYNCED)
    if r.status == Status.DEGRADED:
        assert "solar" in r.reason


def test_light_mode_has_no_fake_band():
    now, data = _data()
    det = bench.Capability("deterministic", 1, 0.25, 3600.0, 0.0)
    r = engine.run_target(_spec(), MemSource(data), models.get("facility"), det, now + 60)
    assert r.output is not None and r.status in (Status.OK, Status.DEGRADED)
    assert set(r.output.quantiles["fast"]["T"]) == {"p50"}
