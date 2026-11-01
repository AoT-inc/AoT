# coding=utf-8
"""예보 시계열(대지의 지정 예보 입력) → 트윈 시설 부품의 전망 외기 (예보 단일 출처 3단계)."""
import math

import pytest

from aot.twin import bench, engine, models
from aot.twin.ext_forecast import SeriesExt
from aot.twin.sources.remote import RemoteSource, RestClient
from aot.twin.types import ForecastSeries, Status
from .fakes import FakeAoT
from .helpers import MemSource
from .test_facility_greybox import CAP, _data, _spec

H = 3600.0


def _resp(t0, hours=60, solar=True, **over):
    """서버 응답 모양(계약): 한 시간 칸 행 + 메타. t0 는 칸 시작 정렬."""
    t0 = math.floor(t0 / H) * H
    rows = []
    for i in range(hours):
        t = t0 + i * H
        hr = (t / H) % 24
        r = {"time": t, "end": t + H, "temp_c": 10.0 + 5.0 * math.sin((hr - 9) / 24 * 2 * math.pi),
             "rh_pct": 70.0, "wind_ms": 2.0, "wind_dir_deg": 200.0, "precip_mm_h": 0.0, "cloud_pct": 20.0}
        if solar:
            r["solar_w_m2"] = max(0.0, 700.0 * math.sin((hr - 6) / 12 * math.pi))
        rows.append(r)
    d = {"available": True, "rows": rows, "source": {"name": "시간별 예보", "input_id": "in-1", "model": "best_match"},
         "fetched_at": t0, "horizon": rows[-1]["end"], "resolution": {"step_s": 3600, "kind": "hourly"},
         "covers_request": True}
    d.update(over)
    return d


# ── 값 모양 ──────────────────────────────────────────────────────────────────

def test_from_response_ok_unavailable_and_garbage():
    ok = ForecastSeries.from_response(_resp(1.7e9, hours=3))
    assert ok.available and len(ok.rows) == 3 and ok.source == "시간별 예보" and ok.step_s == 3600.0
    assert ok.horizon == ok.rows[-1]["end"] and ok.covers_request
    no = ForecastSeries.from_response({"available": False, "reason": "none_designated", "reason_text": "지정 없음"})
    assert not no.available and no.rows == [] and no.reason == "none_designated"
    assert not ForecastSeries.from_response("junk").available
    assert not ForecastSeries.from_response({"available": True, "rows": [{"time": "x"}]}).available   # 쓸 행이 없다
    # 키가 없는 변수는 그대로 없다(0 으로 채우지 않는다)
    r = ForecastSeries.from_response({"available": True, "rows": [{"time": 1.0, "end": 2.0, "temp_c": 3}]}).rows[0]
    assert "solar_w_m2" not in r and r["temp_c"] == 3.0


# ── 전망 외기 만들기 ──────────────────────────────────────────────────────────

def _fb(t):
    return {"T_ext": -99.0, "RH_ext": -99.0, "wind": -99.0, "solar": -99.0, "CO2_ext": 420.0}


def test_series_ext_interpolates_instants_steps_cells_and_falls_back():
    t0 = 7200.0
    rows = [{"time": t0, "end": t0 + H, "temp_c": 10.0, "rh_pct": 50.0, "wind_ms": 1.0, "solar_w_m2": 100.0},
            {"time": t0 + H, "end": t0 + 2 * H, "temp_c": 20.0, "rh_pct": 70.0, "wind_ms": 3.0, "solar_w_m2": 300.0}]
    fs = ForecastSeries(available=True, rows=rows, horizon=t0 + 2 * H)
    e = SeriesExt(fs, _fb)
    mid = e(t0 + 1800.0)
    assert mid["T_ext"] == pytest.approx(15.0) and mid["RH_ext"] == pytest.approx(60.0) and mid["wind"] == pytest.approx(2.0)
    assert mid["solar"] == 100.0                                    # 칸 값은 계단(보간하지 않는다)
    assert e(t0 + H)["solar"] == 300.0                              # 다음 칸 시작에서 바뀐다
    assert e(t0 + 2 * H - 1.0)["T_ext"] == pytest.approx(20.0)      # 마지막 칸 안에서는 마지막 정시 값을 유지
    beyond = e(t0 + 2 * H)                                          # 지평 밖 → 폴백
    assert beyond["T_ext"] == -99.0 and beyond["solar"] == -99.0
    assert e(t0 - 10.0)["T_ext"] == -99.0                           # 첫 칸 앞 → 폴백
    assert e(t0)["CO2_ext"] == 420.0                                # 예보에 없는 항목은 폴백 값 그대로
    cov = e.coverage()
    assert 0.0 < cov["T_ext"] < 1.0 and cov["T_ext"] == cov["solar"]


def test_series_ext_missing_variable_falls_back_only_for_that_variable():
    rows = [{"time": 0.0, "end": H, "temp_c": 12.0}]                # 일사·습도·풍속 없음
    e = SeriesExt(ForecastSeries(available=True, rows=rows, horizon=H), _fb)
    out = e(100.0)
    assert out["T_ext"] == 12.0 and out["solar"] == -99.0 and out["RH_ext"] == -99.0


def test_series_ext_without_series_is_pure_fallback():
    e = SeriesExt(None, _fb)
    assert e(5.0)["T_ext"] == -99.0 and e.coverage()["T_ext"] == 0.0 and e.horizon is None


# ── 원격 통로 ─────────────────────────────────────────────────────────────────

def _remote(fake):
    return RemoteSource("dev", RestClient(fake.url, fake.api_key, retries=0), [])


def test_remote_read_forecast_reads_the_server_endpoint():
    with FakeAoT() as fake:
        fake.forecast = _resp(1.8e9, hours=5)
        fs = _remote(fake).read_forecast("site-uuid", 1.8e9, 1.8e9 + 4 * H, ["temp_c", "solar_w_m2"])
        assert fs.available and len(fs.rows) == 5 and fs.source == "시간별 예보"
        q = fake.forecast_queries[-1]
        assert q["site"] == "site-uuid" and float(q["start"]) == 1.8e9 and q["variables"] == "temp_c,solar_w_m2"


def test_remote_read_forecast_gate_closed_or_unavailable_is_not_an_error():
    with FakeAoT() as fake:
        fake.forecast = None                                        # 404: 트윈 플래그 닫힘 등
        fs = _remote(fake).read_forecast("s", 0.0, 1.0)
        assert not fs.available and fs.reason == "error"
        fake.forecast = {"available": False, "reason": "none_designated", "reason_text": "지정된 예보 입력이 없다"}
        fs = _remote(fake).read_forecast("s", 0.0, 1.0)
        assert not fs.available and fs.reason == "none_designated"


# ── 시설 부품 ─────────────────────────────────────────────────────────────────

class _FcSource(MemSource):
    def __init__(self, data, fs):
        super().__init__(data)
        self.fs = fs
        self.calls = []

    def read_forecast(self, site, t0, t1, variables=None):
        self.calls.append((site, t0, t1, tuple(variables or ())))
        return self.fs


def _run(spec, src, now):
    return engine.run_target(spec, src, models.get("facility"), CAP, now)


def test_facility_uses_series_when_designated_and_reports_it():
    now, data = _data()
    src = _FcSource(data, ForecastSeries.from_response(_resp(now, hours=60)))
    spec = _spec(forecast_series={"site": "site-1"})
    r = _run(spec, src, now + 60)
    assert r.status in (Status.OK, Status.DEGRADED), r.reason
    assert r.output.meta["weather_src"] == 5.0
    site, t0, t1, variables = src.calls[0]
    assert site == "site-1" and t1 - t0 == 12 * H            # 요청 구간 = 이 시험 능력의 지평(48 h × 0.25)
    assert set(variables) == {"temp_c", "rh_pct", "wind_ms", "solar_w_m2"}
    f = r.info["forecast"]
    assert f["source"] == "시간별 예보" and f["coverage"]["solar"] > 0.9 and f["coverage"]["T_ext"] > 0.9


def test_facility_without_designation_falls_back_and_says_so():
    now, data = _data()
    src = _FcSource(data, ForecastSeries(reason="none_designated", reason_text="지정된 예보 입력이 없다"))
    r = _run(_spec(forecast_series={"site": "site-1"}), src, now + 60)
    assert r.status == Status.DEGRADED and "예보 입력 없음" in r.reason and "지정된 예보 입력이 없다" in r.reason
    assert r.output.meta["weather_src"] == 4.0 and "forecast" not in r.info


def test_facility_partial_horizon_is_flagged_and_filled_by_persistence():
    now, data = _data()
    src = _FcSource(data, ForecastSeries.from_response(_resp(now, hours=5)))     # 5 h 만 있는 예보
    r = _run(_spec(forecast_series={"site": "s"}), src, now + 60)
    assert r.status == Status.DEGRADED and "까지 — 이후는 일주기 지속" in r.reason
    assert r.output.meta["weather_src"] == 5.0
    assert r.info["forecast"]["coverage"]["T_ext"] < 0.5


def test_facility_forecast_without_solar_is_flagged():
    now, data = _data()
    src = _FcSource(data, ForecastSeries.from_response(_resp(now, hours=60, solar=False)))
    r = _run(_spec(forecast_series={"site": "s"}), src, now + 60)
    assert r.status == Status.DEGRADED and "예보에 일사 없음" in r.reason


def test_facility_no_config_is_unchanged_and_never_calls_the_reader():
    now, data = _data()
    src = _FcSource(data, ForecastSeries.from_response(_resp(now, hours=60)))
    r = _run(_spec(), src, now + 60)
    assert src.calls == [] and r.output.meta["weather_src"] == 4.0


def test_facility_source_without_reader_is_flagged_not_crashing():
    now, data = _data()
    r = _run(_spec(forecast_series={"site": "s"}), MemSource(data), now + 60)     # MemSource 에는 read_forecast 가 없다
    assert r.status == Status.DEGRADED and "지원하지 않음" in r.reason


def test_facility_reader_exception_falls_back():
    now, data = _data()

    class Boom(_FcSource):
        def read_forecast(self, *a, **k):
            raise RuntimeError("boom")

    r = _run(_spec(forecast_series={"site": "s"}), Boom(data, None), now + 60)
    assert r.status == Status.DEGRADED and "읽지 못함" in r.reason


# ── 내장 통로 ─────────────────────────────────────────────────────────────────

def test_service_and_node_channels_read_the_site_series_through_one_shared_app(monkeypatch):
    """서비스(`service._embedded_channel`)·노드(`node.build_channel`)는 내장 통로를 앱 없이 만든다. 그래도 노지 예보가
    'no_app' 으로 비면 안 된다(10-25 8084 '예보 비 반영 0/8' 결함) — 프로세스 공유 앱으로 서버 계열을 읽는다."""
    import sys
    import types as _t
    from contextlib import contextmanager

    from aot.twin import gate, service

    made = []

    class App:
        @contextmanager
        def app_context(self):
            yield

    def create_app():
        made.append(1)
        return App()

    monkeypatch.setattr(gate, "_SHARED_APP", None)
    monkeypatch.setitem(sys.modules, "aot.aot_flask.app", _t.SimpleNamespace(create_app=create_app))
    fake = _t.SimpleNamespace(read=lambda site, t0, t1, v: {
        "available": True, "source_basis": "designated", "source": {"name": "일별", "input_id": "d"},
        "rows": [], "daily": [{"date": "2026-11-01", "time": 1.0, "end": 2.0, "precip_mm": 10.8}],
        "segments": [{"kind": "daily", "source": {"name": "일별"}}]})
    import aot.aot_flask.geo as geo_pkg
    monkeypatch.setattr(geo_pkg, "forecast_series", fake, raising=False)
    monkeypatch.setitem(sys.modules, "aot.aot_flask.geo.forecast_series", fake)

    src, _sink = service._embedded_channel(type("P", (), {"targets": []})())
    fs = src.read_forecast("site", 0.0, 3.0)
    assert fs.available and fs.daily[0]["precip_mm"] == 10.8 and fs.source_basis == "designated"
    assert gate.LazyApp().get() is gate.LazyApp().get() and made == [1]        # 앱은 프로세스에 하나


def test_embedded_read_forecast_calls_the_server_function_in_app_context(monkeypatch):
    import sys
    import types as _t
    from contextlib import contextmanager

    from aot.twin.sources.embedded import EmbeddedSource

    seen = {}

    class App:
        @contextmanager
        def app_context(self):
            seen["ctx"] = True
            yield

    class Lazy:
        def get(self):
            return App()

    mod = _t.ModuleType("aot.aot_flask.geo.forecast_series")
    mod.read = lambda site, t0, t1, variables=None: (seen.update(args=(site, t0, t1, variables)) or _resp(1.8e9, hours=2))
    monkeypatch.setitem(sys.modules, "aot.aot_flask.geo.forecast_series", mod)
    import aot.aot_flask.geo as geo_pkg
    monkeypatch.setattr(geo_pkg, "forecast_series", mod, raising=False)
    fs = EmbeddedSource("local", [], app=Lazy()).read_forecast("site-1", 1.0, 2.0, ["temp_c"])
    assert fs.available and len(fs.rows) == 2 and seen["ctx"] and seen["args"] == ("site-1", 1.0, 2.0, ["temp_c"])
