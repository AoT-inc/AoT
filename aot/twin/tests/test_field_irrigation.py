# coding=utf-8
"""노지 과거 관수 — 구획의 일 물 깊이(`water_day`)가 트윈 입력으로 들어가는 길.

판정 규칙: 점이 없는 날은 모름(NaN), 0 L 점은 아는 0, `irrigation_known` 은 동기화 창 안에서 닫혔어야 할 날로 잰다.
시험의 날짜 순서는 실제 기록과 맞췄다 — 어제의 점은 다음 날 정오 뒤에 생긴다(개발서버 `water_day` 대조, 2026-11-01).
"""
import math
import time

import numpy as np
import pytest

from aot.functions.utils.field_twin import FieldBucketModel, FieldEnKF, FieldPrior, SensorSpec
from aot.functions.utils.field_twin.sim.field_plant import FieldPlant
from aot.functions.utils.water_net import result as R
from aot.twin import engine, models, output as O
from aot.twin.bench import Capability
from aot.twin.models.field_bucket import CLOSE_LAG_S, closable, daily_depth
from aot.twin.types import Provenance, SeriesRef, Status, TargetKind, TargetSpec

from .helpers import MemSource

M = Provenance.MEASURED
TZ = 9 * 3600
DAY = 86400.0
CAP = Capability("full", 50, 1.0, 3600.0, 0.01)
PLOT = "53bdbec9-3507-4944-a7c2-778758196d8a"
IRR = (PLOT, R.M_DAY, R.DAY_FIELDS.index("mm"))
GRACE = R.CLOSE_GRACE_S + CLOSE_LAG_S


def _clock(hour):
    """현지 `hour` 시의 epoch."""
    today = (int(time.time()) + TZ) // 86400
    return today * DAY - TZ + hour * 3600.0


def _series(now, days=20, rain_every=9):
    """구획 입력 — 센서는 없다(`sensorless`). 비·기온만 있고 관수는 시험마다 넣는다."""
    today = int(math.floor((now + TZ) / DAY))
    start = today - days
    rain, temp = [], []
    for d in range(start, today):
        t0 = d * DAY - TZ
        for h in range(24):
            temp.append((t0 + h * 3600.0, 18.0 + 6.0 * math.sin((h - 9) / 24 * 2 * math.pi)))
        rain.append((t0 + 3600.0, 6.0 if (d - start) % rain_every == 4 else 0.0))
    planted = str(np.datetime64("1970-01-01") + np.timedelta64(start, "D"))
    return {("kma", "mm", 6): rain, ("kma", "C", 0): temp}, planted, today


def _spec(planted, wired=True, **opts):
    o = {"planted_on": planted, "timezone": "Asia/Seoul", "lat": 35.85, "members": 32,
         "rain": {"agg": "daily_sum", "kind": "station"}}
    o.update(opts)
    inputs = {"rain": SeriesRef("kma", "mm", 6, M), "t_air": SeriesRef("kma", "C", 0, M)}
    if wired:
        inputs["irrigation"] = SeriesRef(*IRR)
    return TargetSpec("mem", TargetKind.FIELD, PLOT, inputs=inputs, options=o)


def _points(today, days):
    """`{일 번호: mm}` → 일 깊이 계열(시각 = 현지 0시)."""
    return [((d * DAY) - TZ, mm) for d, mm in sorted(days.items())]


def _run(now, data, planted, days=None, **opts):
    src = dict(data)
    if days is not None:
        src[IRR] = _points(0, days)
    return engine.run_target(_spec(planted, **opts), MemSource(src), models.get("field"), CAP, now)


def _closed_days(today, since, n=None, value=0.0):
    return {d: value for d in range(since, today - (n or 0))}


# ── 일 격자 ─────────────────────────────────────────────────────────────────

def test_a_local_midnight_lands_on_its_own_day():
    tz = float(TZ)
    d = 20390
    assert daily_depth([d * DAY - tz], [3.0], tz) == {d: 3.0}


@pytest.mark.parametrize("shift", [-3600.0, 3600.0])
def test_a_midnight_an_hour_off_by_daylight_saving_stays_on_its_day(shift):
    tz = 3600.0
    d = 20390
    assert daily_depth([d * DAY - tz + shift], [4.0], tz) == {d: 4.0}


def test_yesterdays_water_goes_into_yesterday(monkeypatch):
    now = _clock(15)
    data, planted, today = _series(now)
    calls = []
    real = FieldEnKF.forecast

    def spy(self, u=None, w=None, *a, **k):
        if u is not None and "irr_mm" in u and w is not None and "dap" in w:
            calls.append((int(w["dap"]), u["irr_mm"]))
        return real(self, u, w, *a, **k)

    monkeypatch.setattr(FieldEnKF, "forecast", spy)
    start = today - 20
    res = _run(now, data, planted, {d: (9.0 if d == today - 1 else 0.0) for d in range(start, today)})
    assert res.output is not None
    past = dict(calls[:20])                                       # 앞날 굴리기 전까지가 과거 루프
    assert past[today - 1 - start] == 9.0 and past[today - 2 - start] == 0.0


# ── 모름과 0 ────────────────────────────────────────────────────────────────

def test_a_day_without_a_point_is_unknown_not_zero(monkeypatch):
    now = _clock(15)
    data, planted, today = _series(now)
    seen = []
    real = FieldEnKF.forecast
    monkeypatch.setattr(FieldEnKF, "forecast",
                        lambda self, u=None, w=None, *a, **k: (seen.append(u), real(self, u, w, *a, **k))[1])
    days = {d: 2.0 for d in range(today - 20, today) if d != today - 5}
    res = _run(now, data, planted, days)
    assert any(u and math.isnan(u["irr_mm"]) for u in seen[:20])  # 빈 날은 NaN 으로 넘어간다
    assert res.output.meta["irrigation_known"] == 0.0
    assert "관수 기록 없는 날 1/" in res.reason and "관수 모름" in res.reason


def test_a_zero_litre_point_is_a_known_zero():
    assert R.day_depth({0: 0.0, 1: 0.0, 4: 0.0, 5: 0.0, 6: 0.0}) == 0.0          # 실행이 없는 날은 mm 칸이 없다
    assert R.day_depth({0: 500.0, 1: 500.0, 5: 1.0}) is None                      # 물이 나갔는데 면적을 모른다
    assert R.day_depth({0: 500.0, 2: 3.2}) == 3.2
    now = _clock(15)
    data, planted, today = _series(now)
    res = _run(now, data, planted, _closed_days(today, today - 20))
    assert res.output.meta["irrigation_known"] == 1.0


# ── irrigation_known 판정 ───────────────────────────────────────────────────

def test_known_does_not_blink_off_in_the_morning():
    """오전에는 어제가 아직 닫힐 수 없다 — 어제 점이 없어도 1 이고, 빠졌다는 사실은 메모에 남는다."""
    morning = _clock(6)
    data, planted, today = _series(morning)
    res = _run(morning, data, planted, _closed_days(today, today - 20, n=1, value=1.0))
    assert res.output.meta["irrigation_known"] == 1.0
    assert "아직 닫히지 않은" in res.reason


def test_after_the_close_a_missing_yesterday_is_a_gap():
    evening = _clock(18)
    data, planted, today = _series(evening)
    res = _run(evening, data, planted, _closed_days(today, today - 20, n=1, value=1.0))
    assert res.output.meta["irrigation_known"] == 0.0


def test_closable_follows_the_close_grace():
    d = 20000
    end = (d + 1) * DAY - TZ
    assert not closable(d, end + GRACE - 1.0, TZ) and closable(d, end + GRACE, TZ)


def test_a_season_older_than_the_backfill_still_gets_known():
    """백필은 시작일이 있다 — 그 앞의 빈 날이 영구히 0 을 만들면 안 된다. 창 밖 빈 날은 메모로만 남는다."""
    now = _clock(15)
    data, planted, today = _series(now, days=40)
    res = _run(now, data, planted, _closed_days(today, today - 14, value=1.0))
    assert res.output.meta["irrigation_known"] == 1.0
    assert "그 전 관수 기록 없는 날 26 일" in res.reason


def test_water_day_without_the_irrigated_option_still_counts():
    now = _clock(15)
    data, planted, today = _series(now)
    res = _run(now, data, planted, _closed_days(today, today - 20, value=1.0), irrigated=False)
    assert res.output.meta["irrigation_known"] == 1.0


def test_irrigated_option_only_changes_the_note_when_water_is_unknown():
    now = _clock(15)
    data, planted, today = _series(now)
    assert "관수 제외" in _run(now, data, planted, irrigated=True).reason
    assert "관수 제외" not in _run(now, data, planted, _closed_days(today, today - 20), irrigated=True).reason


# ── 변하면 안 되는 것 ───────────────────────────────────────────────────────

def test_plot_without_water_day_is_bit_identical_to_not_wired():
    now = _clock(15)
    data, planted, _ = _series(now)
    a = engine.run_target(_spec(planted, wired=False), MemSource(data), models.get("field"), CAP, now)
    b = engine.run_target(_spec(planted), MemSource(data), models.get("field"), CAP, now)
    assert a.output.quantiles == b.output.quantiles and repr(a.output.meta) == repr(b.output.meta)    # NaN 칸까지
    assert a.reason == b.reason and a.status == b.status and not b.act


def test_water_day_of_zero_mm_equals_no_water_in_the_curves():
    """아는 0 과 모름은 물 수지에서 같다(0 mm 가 들어간다) — 다른 것은 메타뿐이다."""
    now = _clock(15)
    data, planted, today = _series(now)
    a = _run(now, data, planted)
    b = _run(now, data, planted, _closed_days(today, today - 20))
    assert a.output.quantiles == b.output.quantiles
    assert (a.output.meta["irrigation_known"], b.output.meta["irrigation_known"]) == (0.0, 1.0)


# ── 늦게 도착한 어제 ─────────────────────────────────────────────────────────

def test_a_yesterday_that_arrives_later_is_read_by_the_next_run_and_runs_are_repeatable():
    morning = _clock(6)
    data, planted, today = _series(morning)
    start = today - 20
    before = {d: 0.0 for d in range(start, today - 1)}
    a = _run(morning, data, planted, before)
    assert _run(morning, data, planted, before).output.quantiles == a.output.quantiles   # 같은 입력 = 같은 결과
    after = {**before, today - 1: 20.0}
    noon = _clock(15)
    b = _run(noon, data, planted, after)
    c = _run(noon, data, planted, after)
    assert c.output.quantiles == b.output.quantiles and b.output.t0 == a.output.t0       # 같은 날 발행을 그대로 덮는다
    assert b.output.quantiles["daily"]["theta_root"]["p50"][0] > a.output.quantiles["daily"]["theta_root"]["p50"][0]
    assert b.output.meta["irrigation_known"] == 1.0


# ── 표시 ────────────────────────────────────────────────────────────────────

def test_water_is_written_as_past_act_and_never_as_measured_lineage():
    now = _clock(15)
    data, planted, today = _series(now)
    res = _run(now, data, planted, {d: 3.0 for d in range(today - 20, today)})
    act = res.act[0]
    assert (act.effect, act.basis) == ("irrigation_mm", "duty_log")
    assert len(act.times) == 14 and (act.times[-1] + TZ) % DAY == 0                       # 창 안만 쓴다(보존 밖 점은 Influx 가 거절한다)
    pts = O.run_act_points(res.output, res.act)
    assert {p.tags["effect"] for p in pts} == {"irrigation_mm"} and len(pts) == 14
    assert "obs_origin" not in res.output.meta                                            # 센서 없는 구획: 물은 관측이 아니다
    assert res.info["irrigation"]["basis"] == "design" and res.info["irrigation"]["level"] == "L0"
    assert "설계 추정" in res.reason


def test_field_header_counts_connected_outputs_and_ignores_other_plots_and_supply():
    now = _clock(15)
    data, planted, today = _series(now)
    roster = {"devices": [{"id": "v1", "kind": "irrigation_drip", "plots": [PLOT]},
                          {"id": "v2", "kind": "irrigation_sprinkler", "plots": ["other"]},
                          {"id": "p1", "kind": "pump"}, {"id": "x1", "kind": None}]}
    res = _run(now, data, planted, _closed_days(today, today - 20), effects=roster)
    m = res.output.meta
    assert (m["effects_modeled"], m["effects_unmodeled"]) == (1.0, 1.0)                   # v1 / x1. 펌프·다른 구획 밸브는 세지 않는다
    assert {e["id"]: e["status"] for e in res.effects} == {"v1": "partial", "p1": "supply", "x1": "unknown"}
    res = _run(now, data, planted, effects=roster)
    assert (res.output.meta["effects_modeled"], res.output.meta["effects_unmodeled"]) == (0.0, 2.0)   # 물이 안 들어갔다


# ── EnKF ────────────────────────────────────────────────────────────────────

def test_a_known_irrigation_day_is_not_read_as_a_sensor_step():
    model = FieldBucketModel()
    sensor = SensorSpec("theta", layer=1, a=1.0, b=0.0, r_sd=0.5)
    f = FieldEnKF(model, [sensor], n_members=32, prior=FieldPrior(theta0=[0.30] * 3), seed=1)
    w = {"rain_mm": 0.0, "et0_mm": 3.0, "t_mean": 20.0, "dap": 10}
    f.forecast({"irr_mm": float("nan")}, w)
    assert f._last_rain == 0.0                                    # 모르는 관수는 '물 없음' 그대로
    f.forecast({"irr_mm": 12.0}, w)
    assert f._last_rain == 12.0


# ── 참값 위에서 ─────────────────────────────────────────────────────────────

def _plant_series(now, days=30):
    """독립 참값(`FieldPlant`)으로 땅을 굴려 센서·비·기온·물 깊이를 만든다."""
    today = int(math.floor((now + TZ) / DAY))
    start = today - days
    plant = FieldPlant(theta0=0.27)
    theta, rain, temp, water = [], [], [], {}
    for d in range(start, today):
        t0 = d * DAY - TZ
        irr = 18.0 if (d - start) % 6 == 2 else 0.0
        water[d] = irr
        for h in range(24):
            temp.append((t0 + h * 3600.0, 20.0 + 6.0 * math.sin((h - 9) / 24 * 2 * math.pi)))
        rain.append((t0 + 3600.0, 0.0))
        plant.step_day(0.0, irr, 4.0)
        end = t0 + DAY
        for k in range(-24, 25):
            theta.append((end + k * 300.0, 100.0 * plant.theta_at(0.10, 0.30)))
    planted = str(np.datetime64("1970-01-01") + np.timedelta64(start, "D"))
    return {("s3", "percent", 2): theta, ("kma", "mm", 6): rain, ("kma", "C", 0): temp,
            ("kma", "mm", 7): [(t0 + 7200.0, 4.0) for t0 in (d * DAY - TZ for d in range(start, today))]}, \
        planted, water, plant


def test_on_the_truth_plant_known_irrigation_tracks_the_sensor_better():
    now = _clock(15)
    data, planted, water, plant = _plant_series(now)

    def spec(wired):
        s = _spec(planted, wired=wired, sensor={"layer": 1, "a": 1.0, "b": 0.0, "r_sd": 1.0}, texture="loam")
        return TargetSpec("mem", TargetKind.FIELD, PLOT,
                          inputs={**s.inputs, "theta": SeriesRef("s3", "percent", 2, M),
                                  "et0": SeriesRef("kma", "mm", 7, M)}, options=s.options)

    src = dict(data)
    src[IRR] = _points(0, water)
    with_water = engine.run_target(spec(True), MemSource(src), models.get("field"), CAP, now)
    without = engine.run_target(spec(False), MemSource(data), models.get("field"), CAP, now)
    assert with_water.output.meta["irrigation_known"] == 1.0
    assert without.output.meta["irrigation_known"] == 0.0
    a, b = with_water.output.meta["sync_rmse_theta_1d"], without.output.meta["sync_rmse_theta_1d"]
    assert a < b, (a, b)                                          # 물을 알면 1 일 앞 오차가 준다
    assert abs(plant.check_balance()) < 1e-6


# ── 읽는 통로 ───────────────────────────────────────────────────────────────

def test_embedded_source_reads_stored_depths_and_a_failed_read_is_unknown(monkeypatch):
    from aot.twin.sources.embedded import EmbeddedSource
    from aot.utils import water_store
    src = EmbeddedSource("local", [], app=object())
    ref = SeriesRef(*IRR)
    monkeypatch.setattr(water_store, "read_depths", lambda p, a, b: ([1000.0], [2.5]))
    s = src.read_series(ref, 86400.0, 2000.0)
    assert (s.times, s.values) == ([1000.0], [2.5])

    def boom(*_a):
        raise RuntimeError("influx down")

    monkeypatch.setattr(water_store, "read_depths", boom)
    s = src.read_series(ref, 86400.0, 2000.0)
    assert (s.times, s.values) == ([], [])                        # 못 읽으면 모름이다 — 0 을 지어내지 않는다


def test_remote_source_asks_the_server_for_the_depth():
    from aot.twin.sources.remote import RemoteSource

    class Client:
        path = None

        def get_json(self, path):
            Client.path = path
            return {"measurements": [{"time": 5.0, "value": 1.5}, {"time": 1.0, "value": 0.0}]}

    s = RemoteSource("r", Client(), []).read_series(SeriesRef(*IRR), 3600.0, 2000.0)
    assert Client.path == "/api/twin/state/water_day/%s?past=3600" % PLOT
    assert (s.times, s.values) == ([1.0, 5.0], [0.0, 1.5])
