# coding=utf-8
"""what-if 시나리오 실행기(E2): 가정 해석 · 시설/노지 모델 입력 · 작동 시계열 · 머리말 효과 개수 · 서비스 대기열."""
import math
import time

import numpy as np
import pytest

from aot.functions.utils.twin_effects import scenario as SC
from aot.functions.utils.twin_effects.aggregate import Device
from aot.twin import engine, models, output as O
from aot.twin.scenario_queue import ScenarioQueue
from aot.twin.scenario_run import run_scenario
from aot.twin.service import ServiceSettings, TwinService
from aot.twin import gate as G
from aot.twin.types import Series, Status, TargetKind, WriteResult

from .helpers import MemSource
from .test_facility_effects import H, W, _dev_spec
from .test_facility_greybox import CAP, _data, _spec as fac_spec
from .test_field_bucket import CAP as FCAP, PLOT, _spec as fld_spec, _synthetic


class Sink:
    def __init__(self):
        self.points = []

    def write(self, points):
        self.points.extend(points)
        return WriteResult(written=len(points))


# ── 가정 해석(순수) ────────────────────────────────────────────────────────────────

def test_parse_rejects_what_it_cannot_run_instead_of_ignoring():
    bad = [({"actuators": [{"channel": "heat", "t0": 0, "value": 120}]}, "facility"),
           ({"actuators": [{"channel": "heat", "t0": 0, "value": 50, "unit": "mm"}]}, "facility"),
           ({"actuators": [{"channel": "heat", "t0": 5, "t1": 5, "value": 50}]}, "facility"),
           ({"actuators": [{"t0": 0, "value": 50}]}, "facility"),
           ({"weather": [{"var": "rain_x", "op": "add", "value": 1, "t0": 0}]}, "facility"),
           ({"weather": [{"var": "T_ext", "op": "mul", "value": 1, "t0": 0}]}, "facility"),
           ({"actuators": [{"channel": "heat", "t0": 0, "t1": 9, "value": 3}]}, "field"),
           ({"actuators": [{"channel": "irrigation_mm", "t0": 0, "value": 3}]}, "field"),       # 노지는 t1 필수
           ({"weather": [{"var": "T_ext", "op": "add", "value": 1, "t0": 0}]}, "field")]
    for ov, kind in bad:
        with pytest.raises(SC.ScenarioError):
            SC.parse(ov, kind)
    p = SC.parse({"actuators": [{"channel_or_device_uid": "shade", "t0": 0, "value": 0}],
                  "weather": [{"var": "temp_c", "op": "add", "value": 2, "t0": 0, "t1": 10}],
                  "supply": [{"name": "water_temp_c", "value": 12}]}, "facility")
    assert p.actuators[0].key == "shade" and p.actuators[0].t1 == math.inf
    assert p.weather[0].var == "T_ext" and p.supply[0]["name"] == "water_temp_c"


def test_modes_beyond_hold_and_whatif_wait_for_e5():
    SC.check_modes("hold", "whatif")
    for base, fut in (("schedule", "whatif"), ("policy", "hold"), ("hold", "schedule")):
        with pytest.raises(SC.ScenarioError):
            SC.check_modes(base, fut)


def test_cmd_plan_channel_override_is_piecewise_and_future_only():
    p = SC.parse({"actuators": [{"channel": "shade", "t0": 1000, "t1": 2000, "value": 0.0},
                                {"channel": "shade", "t0": 1500, "t1": 3000, "value": 40.0}]}, "facility")
    plan = SC.facility_cmd_plan(p, 500.0, 5000.0, {"shade": 100.0, "heat": 7.0})
    assert plan(600)["shade"] == 100.0 and plan(1200)["shade"] == 0.0
    assert plan(1700)["shade"] == 40.0                            # 겹치면 목록에서 뒤의 것이 이긴다
    assert plan(3000)["shade"] == 100.0 and plan(1700)["heat"] == 7.0
    with pytest.raises(SC.ScenarioError):
        SC.facility_cmd_plan(SC.parse({"actuators": [{"channel": "nope", "t0": 0, "value": 1}]}, "facility"),
                             0, 9, {})


def test_cmd_plan_device_override_remerges_by_catalog_rule():
    devs = [Device("h1", "heater", {"rated_kW_thermal": 30.0}), Device("h2", "heater", {"rated_kW_thermal": 10.0})]
    p = SC.parse({"actuators": [{"channel": "h2", "t0": 100, "t1": 200, "value": 100.0}]}, "facility")
    plan = SC.facility_cmd_plan(p, 0.0, 1000.0, {"heat": 0.0}, devs, {"h1": 0.0, "h2": 0.0})
    assert plan(50)["heat"] == 0.0
    assert plan(150)["heat"] == pytest.approx(25.0)               # 정격 가중: 10/(30+10) × 100 %
    assert plan(250)["heat"] == 0.0
    assert SC.unmodeled_targets(SC.parse({"actuators": [{"channel": "l1", "t0": 0, "value": 5}]}, "facility"),
                                [Device("l1", "lighting", {})]) == ["l1"]


def test_hourly_mean_hold_is_time_weighted_and_handoff_to_plan():
    ts, vs = [0.0, 1800.0], [0.0, 100.0]
    t, v = SC.hourly_mean_hold(ts, vs, 0.0, 7200.0)
    assert t == [0.0, 3600.0] and v == [50.0, 100.0]
    plan = SC.CmdPlan(3600.0, [3600.0, 5400.0], [{"c": 100.0}, {"c": 0.0}])
    t, v = SC.hourly_mean_hold(ts, vs, 3600.0, 7200.0, future=plan, channel="c", future_from=3600.0)
    assert v == [50.0]                                            # 한 시간 안에서 계획이 100 → 0 으로 바뀐다
    assert SC.hourly_mean_hold([], [], 0.0, 7200.0) == ([], [])


def test_weather_overrides_and_irrigation_split():
    p = SC.parse({"weather": [{"var": "RH_ext", "op": "set", "value": 130, "t0": 0, "t1": 10},
                              {"var": "solar", "op": "scale", "value": 0.5, "t0": 0, "t1": 10}]}, "facility")
    e = SC.apply_weather_ext(p, {"RH_ext": 50.0, "solar": 800.0, "wind": 1.0}, 5.0)
    assert e["RH_ext"] == 100.0 and e["solar"] == 400.0           # 범위 밖은 자른다
    assert SC.apply_weather_ext(p, {"RH_ext": 50.0, "solar": 800.0}, 20.0) == {"RH_ext": 50.0, "solar": 800.0}
    f = SC.parse({"actuators": [{"channel": "irrigation_mm", "t0": 3600.0 * 22, "t1": 3600.0 * 26, "value": 8.0}],
                  "weather": [{"var": "precip_mm", "op": "add", "value": 5, "t0": 0, "t1": 86400.0}]}, "field")
    hourly = SC.irrigation_hourly(f)
    assert sum(hourly.values()) == pytest.approx(8.0) and hourly[3600.0 * 22] == pytest.approx(2.0)
    assert SC.irrigation_daily(hourly, [0.0, 86400.0]) == {0: pytest.approx(4.0), 1: pytest.approx(4.0)}
    assert SC.apply_weather_day(f, "rain", 0.0, None) == 5.0       # 예보 비가 없던 날도 add 는 값을 만든다
    assert SC.apply_weather_day(f, "rain", 86400.0, 2.0) == 2.0    # 구간 밖
    assert SC.apply_weather_day(f, "et0", 0.0, None) is None


def test_effects_report_unknown_kind_has_no_channel_and_counts_split():
    rep = SC.effects_report([{"id": "w", "kind": "opening", "ratings": {"area_m2": 10}},
                             {"id": "h", "kind": "heater", "ratings": {}},
                             {"id": "f", "kind": "fogger", "ratings": {"fog_flow_lpm": 5}},
                             {"id": "l", "kind": "lighting"}, {"id": "x", "kind": "mystery"}, {"id": "n", "kind": None}],
                            "facility", assumed=["h"])
    by = {r["id"]: r for r in rep}
    assert by["w"]["status"] == "modeled" and by["w"]["channel"] == "vent" and by["w"]["source"] == "measured"
    assert by["h"]["source"] == "unknown"                          # 정격 모름, 종류 기본값도 없다
    assert by["f"]["status"] == "partial" and by["l"]["status"] == "unmodeled" and by["l"]["channel"] is None
    assert by["x"]["status"] == "unknown" and by["x"]["channel"] is None and by["n"]["status"] == "unknown"
    assert SC.header_counts(rep) == (2, 4)                         # modeled(창·난방기) 2 · partial+unmodeled+unknown 4


# ── 시설 모델 ──────────────────────────────────────────────────────────────────────

def _fac(data, now, scenario=None, devices=None):
    spec = _dev_spec(devices or [W, H])
    if scenario is not None:
        spec.options = {**spec.options, "scenario": scenario}
    return engine.run_target(spec, MemSource(data), models.get("facility"), CAP, now)


def test_baseline_run_writes_act_series_and_header_counts():
    now, data = _data()
    r = _fac(data, now + 60, devices=[W, H, {"id": "l1", "kind": "lighting", "ratings": {}}])
    assert r.output.meta["plan_src"] == 0.0
    assert r.output.meta["effects_modeled"] == 2.0 and r.output.meta["effects_unmodeled"] == 1.0
    assert {e["id"]: e["status"] for e in r.effects} == {"w1": "modeled", "h1": "modeled", "l1": "unmodeled"}
    by = {(a.effect, a.basis): a for a in r.act}
    assert ("vent", "plan") in by and ("heat", "plan") in by
    past = [a for a in r.act if a.basis != "plan"]
    assert past and all(max(a.times) < math.floor(r.output.t0 / 3600) * 3600 + 1 for a in past)
    plan = by[("heat", "plan")]
    assert plan.times[0] == math.floor(r.output.t0 / 3600) * 3600 and len(plan.times) >= 11            # 능력 판정의 지평(1/4) = 12 h
    assert len(set(round(v, 6) for v in plan.values[1:])) == 1    # 현재 유지 = 마지막 값이 계속
    pts = O.run_act_points(r.output, r.act)
    assert pts and {p.measurement for p in pts} == {"env_twin_act"} and {p.tags["scenario"] for p in pts} == {"baseline"}
    assert {p.tags["effect"] for p in pts} == {"vent", "heat"}


def test_scenario_without_changes_equals_baseline_and_is_deterministic():
    now, data = _data()
    base = _fac(data, now + 60)
    same = _fac(data, now + 60, {"id": "s1", "overrides": {}})
    again = _fac(data, now + 60, {"id": "s1", "overrides": {}})
    for var in ("T", "RH", "CO2"):
        assert same.output.quantiles["fast"][var]["p50"] == base.output.quantiles["fast"][var]["p50"]
        assert same.output.quantiles["fast"][var]["p10"] == again.output.quantiles["fast"][var]["p10"]
    assert same.output.meta["plan_src"] == 2.0


def test_heater_off_and_warm_outside_whatif_move_the_forecast_in_the_right_direction():
    now, data = _data()
    base = _fac(data, now + 60)
    t0 = base.output.t0
    hot = _fac(data, now + 60, {"id": "s2", "overrides": {            # 시험 자료의 난방은 늘 100 % — 끄면 내려간다
        "actuators": [{"channel": "heat", "t0": t0, "t1": t0 + 8 * 3600, "value": 0.0}]}})
    warm = _fac(data, now + 60, {"id": "s3", "overrides": {
        "weather": [{"var": "T_ext", "op": "add", "value": 8.0, "t0": t0, "t1": t0 + 12 * 3600}]}})
    k = 36                                                          # 6 시간 뒤(600 s 격자)
    b = base.output.quantiles["fast"]["T"]["p50"]
    assert hot.output.quantiles["fast"]["T"]["p50"][k] < b[k] - 0.5
    assert warm.output.quantiles["fast"]["T"]["p50"][k] > b[k] + 0.1
    assert hot.output.quantiles["fast"]["T"]["p50"][0] == b[0]      # 시작점(동기화 결과)은 같다 — 가정은 앞날에만
    heat = {a.basis: a for a in hot.act if a.effect == "heat"}["plan"]
    assert heat.values[1] == pytest.approx(0.0) and heat.values[-1] == pytest.approx(100.0)


def test_device_level_whatif_and_bad_target_fail_visibly():
    now, data = _data()
    t0 = _fac(data, now + 60).output.t0
    ok = _fac(data, now + 60, {"id": "s4", "overrides": {
        "actuators": [{"channel": "h1", "t0": t0, "t1": t0 + 4 * 3600, "value": 100.0}]}})
    assert ok.status in (Status.OK, Status.DEGRADED)
    bad = _fac(data, now + 60, {"id": "s5", "overrides": {"actuators": [{"channel": "ghost", "t0": t0, "value": 1}]}})
    assert bad.status == Status.ERROR and "이 시설에 없는" in bad.reason and not bad.output.grids


# ── 실행기 ─────────────────────────────────────────────────────────────────────────

def test_run_scenario_writes_scn_curves_and_future_act_with_tag():
    now, data = _data()
    spec = _dev_spec([W, H])
    sink = Sink()
    t0 = _fac(data, now + 60).output.t0
    scn = {"id": "a1b2c3d4", "base_mode": "hold", "future_input_mode": "whatif",
           "overrides": {"actuators": [{"channel": "w1", "t0": t0, "t1": t0 + 6 * 3600, "value": 0.0}]}}
    out = run_scenario(spec, MemSource(data), sink, CAP, now + 60, scn)
    assert out.ok, out.reason
    ms = {p.measurement for p in sink.points}
    assert ms == {"env_twin_scn", "env_twin_act"}                   # 머리말·기본 측정은 쓰지 않는다
    assert {p.tags["scenario"] for p in sink.points} == {"a1b2c3d4"}
    act = [p for p in sink.points if p.measurement == "env_twin_act"]
    assert {p.tags["basis"] for p in act} == {"plan"} and {p.tags["dev"] for p in act} == {"all"}
    assert all(p.timestamp >= math.floor(out.t0 / 3600) * 3600 for p in act)
    assert out.lineage["model_rev"] == 1 and out.lineage["weather_src"] == 4
    assert [e["status"] for e in out.effects] == ["modeled", "modeled"]
    # 재실행은 같은 점 (같은 id → 같은 결과)
    sink2 = Sink()
    run_scenario(spec, MemSource(data), sink2, CAP, now + 60, scn)
    key = lambda p: (p.measurement, p.channel, p.timestamp, tuple(sorted(p.tags.items())))
    assert {key(p): p.value for p in sink.points} == {key(p): p.value for p in sink2.points}


def test_run_scenario_refuses_what_it_cannot_do_without_writing():
    now, data = _data()
    spec = _dev_spec([W, H])
    for scn, why in (({"id": "s", "base_mode": "schedule", "overrides": {}}, "E5"),
                     ({"id": "s", "future_input_mode": "policy", "overrides": {}}, "E5"),
                     ({"id": "baseline", "overrides": {}}, "id"),
                     ({"id": "s", "overrides": {"weather": [{"var": "zz", "op": "add", "value": 1, "t0": 0}]}}, "기상")):
        sink = Sink()
        out = run_scenario(spec, MemSource(data), sink, CAP, now + 60, scn)
        assert not out.ok and why in out.reason and not sink.points
    sink = Sink()
    out = run_scenario(spec, MemSource({}), sink, CAP, now + 60, {"id": "s", "overrides": {}})   # 관측이 없다 → 기본 예측도 못 낸다
    assert not out.ok and "계산할 수 없다" in out.reason and not sink.points


# ── 노지 모델 ──────────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def field_runs():
    now = (int(time.time()) // 86400) * 86400 + 6 * 3600.0
    data, planted, _ = _synthetic(now)
    roster = {"devices": [{"id": "v1", "kind": "irrigation_drip"}, {"id": "v2", "kind": None}]}

    def run(scn=None):
        spec = fld_spec(planted, effects=roster)
        if scn is not None:
            spec.options = {**spec.options, "scenario": scn}
        return engine.run_target(spec, MemSource(data), models.get("field"), FCAP, now)

    base = run()
    t0 = base.output.t0
    wet = run({"id": "f1", "overrides": {"actuators": [
        {"channel": "irrigation_mm", "t0": t0 + 3600.0, "t1": t0 + 3600.0 * 4, "value": 30.0}]}})
    rain = run({"id": "f2", "overrides": {"weather": [{"var": "precip_mm", "op": "set", "value": 40.0,
                                                       "t0": t0 + 86400.0, "t1": t0 + 2 * 86400.0}]}})
    return base, wet, rain, run


def test_field_baseline_header_counts_roster_as_not_applied(field_runs):
    base = field_runs[0]
    m = base.output.meta
    assert m["plan_src"] == 0.0 and m["effects_modeled"] == 0.0 and m["effects_unmodeled"] == 2.0
    by = {e["id"]: e for e in base.effects}
    assert by["v1"]["status"] == "partial" and by["v1"]["channel"] == "irrigation_mm"
    assert by["v2"]["status"] == "unknown" and by["v2"]["channel"] is None
    assert not base.act


def test_field_irrigation_whatif_wets_the_soil_and_emits_hourly_mm(field_runs):
    base, wet, rain, _ = field_runs
    q0, q1 = base.output.quantiles["daily"]["theta_root"]["p50"], wet.output.quantiles["daily"]["theta_root"]["p50"]
    assert q1[0] == q0[0] and q1[1] > q0[1] + 0.2                  # 첫 날(과거 동기화 끝)은 같고 관수 다음 날부터 젖는다
    a = wet.act[0]
    assert a.effect == "irrigation_mm" and a.basis == "plan" and sum(a.values) == pytest.approx(30.0)
    assert a.times == sorted(a.times) and all(t % 3600 == 0 for t in a.times)
    pts = O.run_act_points(wet.output, wet.act, scenario="f1", plan_only=True)
    assert {p.tags["effect"] for p in pts} == {"irrigation_mm"} and sum(p.value for p in pts) == pytest.approx(30.0)


def test_field_rain_whatif_changes_only_the_assumed_day_onward(field_runs):
    base, _, rain, _ = field_runs
    q0, q1 = base.output.quantiles["daily"]["theta_root"]["p50"], rain.output.quantiles["daily"]["theta_root"]["p50"]
    assert q1[1] == q0[1] and q1[2] > q0[2]                        # 비를 가정한 날(k=1)의 다음 날부터 오른다
    flat = O.flatten_scenario(rain.output, "f2")
    assert {p.measurement for p in flat} == {"env_twin_scn_field"} and {p.tags["scenario"] for p in flat} == {"f2"}


# ── 서비스 대기열 ───────────────────────────────────────────────────────────────────

class MemQueue(ScenarioQueue):
    def __init__(self, items):
        self.items, self.done_, self.failed_, self.recovered = list(items), {}, {}, 0

    def recover(self):
        self.recovered += 1
        return 0

    def claim(self):
        return self.items.pop(0) if self.items else None

    def done(self, sid, outcome):
        self.done_[sid] = outcome

    def failed(self, sid, reason):
        self.failed_[sid] = reason


def _service_with(queue, data, spec, enabled=True, locked=False):
    from aot.twin.discovery import SitePlan, SiteInfo
    plan = SitePlan("site-A", "A", "UTC")
    plan.targets.append(spec)

    class Chan:
        points = []

        def write(self, points):
            self.points.extend(points)
            return WriteResult(written=len(points))

    chan = Chan()
    src = MemSource(data)
    svc = TwinService(G.FakeGate(is_enabled=enabled, is_supported=not locked), lambda: [], lambda uid: [], lambda: {},
                      settings=ServiceSettings(force_tier="light"), channel_factory=lambda p: (src, chan),
                      clock=lambda: 0.0, scenarios=queue)
    from aot.twin.service import _SiteState
    svc.state = {"site-A": _SiteState(plan, ((6, 10),), 1e18)}
    svc._planned_at = 0.0
    svc.capability = CAP
    svc._clock = lambda: _NOW[0]
    return svc, chan


_NOW = [0.0]


def test_service_runs_queued_scenarios_and_records_each_outcome():
    now, data = _data()
    _NOW[0] = now + 60
    spec = _dev_spec([W, H])
    t0 = _fac(data, now + 60).output.t0
    good = {"id": "g1", "target": {"kind": "facility", "id": spec.target_id}, "base_mode": "hold",
            "future_input_mode": "whatif", "overrides": {"actuators": [{"channel": "heat", "t0": t0, "value": 100.0}]}}
    orphan = {"id": "o1", "target": {"kind": "facility", "id": "no-such"}, "overrides": {}}
    sched = {"id": "z1", "target": {"kind": "facility", "id": spec.target_id}, "base_mode": "schedule", "overrides": {}}
    q = MemQueue([good, orphan, sched])
    svc, chan = _service_with(q, data, spec)
    svc._planned_at = _NOW[0]                                       # 계획을 다시 만들지 않는다
    assert svc.start() and q.recovered == 1
    assert svc.run_scenarios() == 3
    assert set(q.done_) == {"g1"} and q.done_["g1"].t0 == pytest.approx(t0)
    assert "트윈 대상이 아님" in q.failed_["o1"] and "E5" in q.failed_["z1"]
    assert any(p.measurement == "env_twin_scn" for p in chan.points)


def test_service_leaves_scenarios_queued_while_off_or_locked():
    now, data = _data()
    _NOW[0] = now + 60
    spec = _dev_spec([W, H])
    q = MemQueue([{"id": "g1", "target": {"kind": "facility", "id": spec.target_id}, "overrides": {}}])
    svc, _ = _service_with(q, data, spec, enabled=False)
    assert svc.run_scenarios() == 0 and len(q.items) == 1
    svc2, _ = _service_with(q, data, spec, locked=True)
    assert svc2.start() is False and q.recovered == 0               # 잠긴 기기에서는 DB 를 열지 않는다
    assert svc2.step() <= svc2.s.heartbeat_s


def test_service_per_step_cap_does_not_starve_scheduled_runs():
    now, data = _data()
    _NOW[0] = now + 60
    spec = _dev_spec([W, H])
    items = [{"id": "i%d" % k, "target": {"kind": "facility", "id": "none"}, "overrides": {}} for k in range(7)]
    q = MemQueue(items)
    svc, _ = _service_with(q, data, spec)
    svc._planned_at = _NOW[0]
    assert svc.run_scenarios() == svc.s.scenarios_per_step == 3 and len(q.items) == 4
