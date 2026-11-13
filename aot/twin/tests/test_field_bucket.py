# coding=utf-8
"""노지 물 수지 + EnKF 부품(models/field_bucket) — 배선·동화·출력·서버 계약.

쌍둥이 시험: 알려진 토양으로 만든 '참' 궤적에서 센서·비·기온 계열을 만들고, 트윈이 그것을
설정 배선만으로 읽어 동화한 뒤 +14 일 분위수를 내는지 본다. 외부 API 는 부르지 않는다.
"""
import math
import time

import numpy as np
import pytest

from aot.functions.utils.field_twin import FieldBucketModel, FieldPrior
from aot.twin import consumer, engine, models, output as O
from aot.twin.bench import Capability
from aot.twin.models.field_bucket import FieldBucketTwin, daily_rain
from aot.twin.types import Provenance, SeriesRef, Status, TargetKind, TargetSpec
from aot.twin import contract_check

from .fakes import FakeAoT
from .helpers import MemSource

M = Provenance.MEASURED
TZ = 9 * 3600
CAP = Capability("full", 50, 1.0, 3600.0, 0.01)
PLOT = "53bdbec9-3507-4944-a7c2-778758196d8a"


def _synthetic(now, days=40, a=1.3, b=0.0, seed=1):
    """참 모델로 일 궤적을 만들고 5 분 센서·시간 비·시간 기온 계열로 펼친다."""
    rng = np.random.default_rng(seed)
    model = FieldBucketModel()
    x = model.init_state(prior=FieldPrior(texture="silt_loam", theta0=[0.30] * 3))
    today = int(math.floor((now + TZ) / 86400.0))
    start = today - days
    rain_by_day = {d: (25.0 if (d - start) % 9 == 4 else 0.0) for d in range(start, today + 1)}
    theta, soil_t, rain, t_air = [], [], [], []
    for d in range(start, today):
        t_mid = d * 86400.0 - TZ                                     # 그날 00 시(현지)
        for h in range(24):
            t = t_mid + h * 3600
            temp = 18.0 + 6.0 * math.sin((h - 9) / 24 * 2 * math.pi)
            t_air.append((t + 60, temp))
            rain.append((t + 120, rain_by_day[d] / 24.0 / 4.0))      # 15 분 강수를 시간마다 하나(×4)
        for k in range(288):
            t = t_mid + k * 300.0
            y = a * 100.0 * x[model.idx["theta2"]] + b
            theta.append((t, y + rng.normal(0, 0.4)))
            soil_t.append((t, 18.0 + 2.0 * math.sin(k / 288 * 2 * math.pi)))
        x = model.step(x, {"irr_mm": float("nan")},
                       {"rain_mm": rain_by_day[d], "et0_mm": 3.5, "t_mean": 18.0, "dap": d - start}, 86400.0)
    for k in range(int((now - (today * 86400.0 - TZ)) // 300) + 1):  # 오늘 00 시 뒤 몇 점
        theta.append((today * 86400.0 - TZ + k * 300.0, a * 100.0 * x[model.idx["theta2"]] + b))
    truth_sensor = a * 100.0 * x[model.idx["theta2"]] + b
    planted = str(np.datetime64("1970-01-01") + np.timedelta64(start, "D"))
    return {("s3", "percent", 2): theta, ("s3", "C", 3): soil_t,
            ("kma", "mm", 6): rain, ("kma", "C", 0): t_air}, planted, truth_sensor


def _spec(planted, **opts):
    o = {"planted_on": planted, "timezone": "Asia/Seoul", "lat": 35.85,
         "rain": {"agg": "hourly_mean_sum", "scale": 4.0, "kind": "station"}, "members": 64}
    o.update(opts)
    return TargetSpec("mem", TargetKind.FIELD, PLOT, inputs={
        "theta": SeriesRef("s3", "percent", 2, M), "soil_t": SeriesRef("s3", "C", 3, M),
        "rain": SeriesRef("kma", "mm", 6, M), "t_air": SeriesRef("kma", "C", 0, M)}, options=o)


@pytest.fixture(scope="module")
def run():
    now = (int(time.time()) // 86400) * 86400 + 6 * 3600.0          # 15 시(현지) — 오늘 몇 시간 지남
    data, planted, truth = _synthetic(now)
    res = engine.run_target(_spec(planted), MemSource(data), models.get("field"), CAP, now)
    return now, res, truth


def test_field_bucket_is_default_field_model():
    assert isinstance(models.get("field"), FieldBucketTwin)


def test_publishes_daily_quantiles_and_meta(run):
    now, r, truth = run
    assert r.status == Status.DEGRADED and "앞날 비 없음" in r.reason     # 예보 미배선 = 예보 대체
    out = r.output
    days = out.grids["daily"]
    assert len(days) == 15 and days[1] - days[0] == 86400.0
    assert out.t0 == days[0] and (out.t0 + TZ) % 86400 == 0          # 현지 00 시 (계약 §10.3)
    q = out.quantiles["daily"]
    for var in ("theta_root", "Dr", "Ks", "Ts1", "GDD", "theta_sensor"):
        for k in range(15):
            assert q[var]["p10"][k] <= q[var]["p50"][k] <= q[var]["p90"][k]
    # 동화가 참을 따라왔다 — 오늘 00 시 센서 칸 예측이 참 센서 값 근처
    assert abs(q["theta_sensor"]["p50"][0] - truth) < 3.0
    # 비가 없다고 보았으니 7 일 뒤가 오늘보다 마르다
    assert q["theta_sensor"]["p50"][7] < q["theta_sensor"]["p50"][0]
    m = out.meta
    assert m["valid_until"] == out.t0 + 36 * 3600 and m["horizon_d"] == 14
    assert m["rain_src"] == 2 and m["irrigation_known"] == 0 and m["obs_n"] == 1
    assert 0 <= m["sync_rmse_theta_1d"] < 3.0 and 0 <= m["coverage_80"] <= 1
    assert set(out.events["daily"]) == {"water_deficit", "water_deficit_severe", "waterlogging"}


def test_output_passes_server_contract(run):
    now, r, _ = run
    pts = O.flatten(r.output)
    body = {"pubs": O.publications(pts), "points": [
        {"m": p.measurement, "id": p.device_id, "ch": p.channel, "ts": p.timestamp, "v": p.value,
         "tags": dict(p.tags)} for p in pts]}
    res = contract_check.validate(body, now)
    assert res.rejected == 0 and len(res.accepted) == len(pts)
    chans = {p.channel for p in pts if p.measurement == "env_twin_field"}
    assert {0, 1, 2, 90, 91, 92, 70, 71, 74} <= chans
    leads = {p.tags.get("lead_d") for p in pts if p.measurement == "env_twin_field_lead"}
    assert leads == {"1", "3", "7"}


@pytest.mark.parametrize("drop,why", [("rain", "비 입력"), ("planted_on", "planted_on")])
def test_missing_wiring_is_not_twinnable(drop, why):
    now = time.time()
    data, planted, _ = _synthetic(now, days=10)
    spec = _spec(planted)
    if drop == "rain":
        spec.inputs = {k: v for k, v in spec.inputs.items() if k != "rain"}
    else:
        spec.options = {k: v for k, v in spec.options.items() if k != "planted_on"}
    r = engine.run_target(spec, MemSource(data), models.get("field"), CAP, now)
    assert r.status == Status.NOT_TWINNABLE and why in r.reason
    assert r.output.meta["valid_until"] == r.output.t0                # 즉시 만료


def test_sensor_provenance_label_is_not_a_gate():
    now = time.time()
    data, planted, _ = _synthetic(now, days=10)
    spec = _spec(planted)
    spec.inputs = dict(spec.inputs, theta=SeriesRef("s3", "percent", 2, Provenance.VIRTUAL))
    r = engine.run_target(spec, MemSource(data), models.get("field"), CAP, now)
    assert r.status != Status.NOT_TWINNABLE                         # 출처 표시는 판정에 쓰지 않는다


def test_stale_rain_unsynced_unless_lag_allowed():
    """재분석 비(예: NASA POWER 입력)는 며칠 늦게 채워진다 — 허용 지연은 설정이 정한다."""
    now = (int(time.time()) // 86400) * 86400 + 6 * 3600.0
    data, planted, _ = _synthetic(now, days=20)
    cut = now - 5 * 86400
    data[("kma", "mm", 6)] = [(t, v) for t, v in data[("kma", "mm", 6)] if t < cut]
    r = engine.run_target(_spec(planted), MemSource(data), models.get("field"), CAP, now)
    assert r.status == Status.UNSYNCED and "비 계열" in r.reason
    spec = _spec(planted, rain={"agg": "hourly_mean_sum", "scale": 4.0, "kind": "reanalysis",
                                "max_lag_d": 7})
    r = engine.run_target(spec, MemSource(data), models.get("field"), CAP, now)
    assert r.status == Status.DEGRADED and r.output.meta["rain_src"] == 4 and "0 mm" in r.reason


def test_daily_rain_aggregations():
    t0 = 86400.0 * 100 - TZ                                           # 현지 00 시
    pts = [(t0 + i * 300.0, 0.5) for i in range(24)]                  # 2 시간 동안 15 분 강수 0.5 mm
    assert daily_rain(*zip(*pts), TZ, "hourly_mean_sum", 4.0) == {100: pytest.approx(4.0)}
    assert daily_rain([t0 + 3600, t0 + 7200], [3.0, 4.0], TZ, "daily_last", 1.0) == {100: 4.0}
    assert daily_rain([t0 + 3600, t0 + 7200], [3.0, 4.0], TZ, "daily_sum", 1.0) == {100: 7.0}


def test_remote_roundtrip_field_bucket_over_http():
    """원격 통로(진짜 HTTP) → 노지 모델 → 서버 검증기 → 저장 → 소비자 읽기."""
    from aot.twin import settings as S
    from aot.twin.node import TwinNode
    now = time.time()
    data, planted, _ = _synthetic(now, days=25)
    with FakeAoT() as fake:
        for (uid, unit, ch), rows in data.items():
            fake.store[(uid, unit, ch)] = {float(t): float(v) for t, v in rows}
        spec = _spec(planted)
        spec.server_id = "dev8084"
        srv = S.ServerSettings("dev8084", "remote", fake.url, "TWIN_KEY", targets=[spec])
        node = TwinNode(S.NodeSettings(enabled=True, servers=[srv]), env={"TWIN_KEY": fake.api_key},
                        remote_write=True)                       # 원격 쓰기는 제품에서 비활성 — 가짜 서버로만 켠다
        node.startup_bench()
        reps = node.run_once()
        assert len(reps) == 1 and reps[0].error is None and reps[0].rejected == 0
        assert reps[0].written == reps[0].points > 300
        src = node.channels["dev8084"][0]
        meta = consumer.usable_meta(src, TargetKind.FIELD, PLOT, time.time())
        assert meta is not None and meta.status == Status.DEGRADED
        p50 = fake.store[(PLOT, "env_twin_field", 91)]
        assert len(p50) == 15


# ── 센서 없는 구획: 관측 없이 모델만(참고용) ────────────────────────────────────

def _sensorless(planted, **opts):
    spec = _spec(planted, **opts)
    spec.inputs = {k: v for k, v in spec.inputs.items() if k not in ("theta", "soil_t")}
    return spec


def test_sensorless_runs_model_only_and_is_marked_no_observation():
    now = (int(time.time()) // 86400) * 86400 + 6 * 3600.0
    data, planted, _ = _synthetic(now)
    r = engine.run_target(_sensorless(planted), MemSource(data), models.get("field"), CAP, now)
    assert r.status == Status.DEGRADED and "관측 없음" in r.reason
    out = r.output
    assert out.meta["obs_n"] == 0.0 and out.meta["status"] == int(Status.DEGRADED)
    assert math.isnan(out.meta["sync_rmse_theta_1d"]) and math.isnan(out.meta["coverage_80"])
    assert out.meta["valid_until"] > out.t0                          # 곡선을 쓴다 — 즉시 만료 아님
    q = out.quantiles["daily"]
    assert "theta_sensor" not in q                                   # 센서가 읽을 값은 없다
    for var in ("theta_root", "Dr", "Ks"):
        assert len(q[var]["p50"]) == 15
    assert all(q["theta_root"]["p10"][k] <= q["theta_root"]["p50"][k] <= q["theta_root"]["p90"][k]
               for k in range(15))


def test_sensorless_band_is_wider_than_synchronized():
    now = (int(time.time()) // 86400) * 86400 + 6 * 3600.0
    data, planted, _ = _synthetic(now)
    src = MemSource(data)
    sync = engine.run_target(_spec(planted), src, models.get("field"), CAP, now).output
    free = engine.run_target(_sensorless(planted), src, models.get("field"), CAP, now).output

    def width(o):
        t = o.quantiles["daily"]["theta_root"]
        return t["p90"][0] - t["p10"][0]
    assert width(free) > width(sync)


def test_sensorless_off_is_not_twinnable():
    now = time.time()
    data, planted, _ = _synthetic(now, days=10)
    r = engine.run_target(_sensorless(planted, sensorless="off"), MemSource(data), models.get("field"), CAP, now)
    assert r.status == Status.NOT_TWINNABLE and "theta" in r.reason


def test_sensorless_still_needs_rain():
    now = time.time()
    data, planted, _ = _synthetic(now, days=10)
    spec = _sensorless(planted)
    spec.inputs = {k: v for k, v in spec.inputs.items() if k != "rain"}
    r = engine.run_target(spec, MemSource(data), models.get("field"), CAP, now)
    assert r.status == Status.NOT_TWINNABLE and "비 입력" in r.reason


def test_sensorless_publishes_without_sensor_curve():
    """TwinOutput → 점 변환이 theta_sensor 없이도 되고 계약 검사를 통과한다."""
    now = (int(time.time()) // 86400) * 86400 + 6 * 3600.0
    data, planted, _ = _synthetic(now)
    r = engine.run_target(_sensorless(planted), MemSource(data), models.get("field"), CAP, now)
    pts = O.flatten(r.output)
    meta = {p.channel: p.value for p in pts if p.measurement == "env_twin_field_meta"}
    assert meta[O.FIELD_META["obs_n"]] == 0.0
    assert not [p for p in pts if p.measurement == "env_twin_field" and p.channel in (O.FIELD_DAILY_Q["theta_sensor"],
                                                                                     O.FIELD_DAILY_Q["theta_sensor"] + 1,
                                                                                     O.FIELD_DAILY_Q["theta_sensor"] + 2)]


def test_unusable_header_shares_t0_with_a_later_good_run_of_the_same_day():
    """오전에 '계산 불가' 로 발행한 구획이 설정을 고친 뒤 정상으로 돌면 그 머리말을 덮어써야 한다.
    시간 단위 t0 로 내리면 낡은 머리말이 '가장 최근' 이라 다음 날 00 시까지 지도에서 숨었다(3포장 2026-10-25)."""
    now = (int(time.time()) // 86400) * 86400 + 6 * 3600.0
    data, planted, _ = _synthetic(now)
    morning = now - 5 * 3600 + 17 * 60
    spec = _spec(planted)
    spec.inputs = {k: v for k, v in spec.inputs.items() if k != "rain"}          # 비를 아직 안 골랐다
    bad = engine.run_target(spec, MemSource(data), models.get("field"), CAP, morning)
    good = engine.run_target(_spec(planted), MemSource(data), models.get("field"), CAP, now)
    assert bad.status == Status.NOT_TWINNABLE and good.output.grids
    assert bad.output.t0 == good.output.t0                              # 같은 시각 → 같은 날 나중 발행이 덮어쓴다
    assert (bad.output.t0 + TZ) % 86400 == 0 and bad.output.t0 <= morning       # 구획 시간대의 오늘 00 시


def test_daily_rain_and_temps_by_tz_name_follow_dst():
    """tz 가 IANA 이름이면 점마다 그 시각의 오프셋으로 접는다 — 뉴욕 가을 서머타임 끝(11-07, 25 시간)."""
    import datetime as dt
    from aot.functions.utils.field_twin import forcing as fz
    from aot.twin.models import field_bucket as fb
    from aot.utils.timekit import wall_to_utc
    NY = 'America/New_York'
    start = wall_to_utc(dt.datetime(2027, 11, 6, 12, 0), NY).timestamp()
    times = [start + h * 3600.0 for h in range(60)]
    d = fz.day_number(2027, 11, 7)
    rain = fb.daily_rain(times, [1.0] * 60, NY, 'hourly_mean_sum', 1.0)
    assert rain[d] == 25.0                           # 11-07 은 25 시간 — 반복되는 01 시를 둘 다 센다
    temps = fb.daily_temps(times, [10.0] * 60, NY)
    assert d in temps and temps[d][2] == 10.0
    # 지금의 오프셋 하나(EDT, -4h)로 접으면 11-07 이 24 시간으로 센다
    assert fb.daily_rain(times, [1.0] * 60, -4 * 3600.0, 'hourly_mean_sum', 1.0)[d] == 24.0
