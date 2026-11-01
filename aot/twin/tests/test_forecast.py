# coding=utf-8
"""앞날 입력(aot.twin.forecast) + 노지 모델 연결 — 예보 사다리 읽기, 비 배율 오차, 상태.

외부 API 는 부르지 않는다. 예보 입력이 '받은 시각에 k 일 뒤 값을 채널 k 에 쓴다' 는 모양을 메모리 계열로 만든다.
"""
import math
import time

import numpy as np
import pytest

from aot.twin import forecast as FC
from aot.twin.models.field_bucket import TRUST_D
from aot.twin.types import Provenance, SeriesRef, Status, TargetKind, TargetSpec, Series

from . import test_field_bucket as FB
from .helpers import MemSource

TZ = FB.TZ
DAY = 86400.0


def _tz_day(t):
    return int(math.floor((t + TZ) / DAY))


def _ladder_data(uid, unit, base_ch, issued, values_by_lead):
    """issued(받은 시각)에 리드 k 채널로 values_by_lead[k] 를 쓴 계열."""
    return {(uid, unit, base_ch + k): [(issued, v)] for k, v in enumerate(values_by_lead) if v is not None}


def _fc_opts(**kw):
    o = {"timezone": "Asia/Seoul",
         "rain": {"unique_id": "omd", "unit": "mm", "channels": list(range(0, 8))},
         "et0": {"unique_id": "omd", "unit": "mm", "channels": list(range(8, 16))}}
    o.update(kw)
    return o


class TestParse:
    def test_no_forecast_is_empty(self):
        assert FC.parse({}) == {}

    def test_channels_become_ladder(self):
        g = FC.parse({"forecast": _fc_opts()})
        assert set(g) == {"rain", "et0"} and g["rain"].refs[3] == SeriesRef("omd", "mm", 3, Provenance.MIRROR)

    def test_null_channel_skipped(self):
        g = FC.parse({"forecast": {"rain": {"unique_id": "x", "unit": "mm", "channels": [5, None, 7]}}})
        assert set(g["rain"].refs) == {0, 2}

    @pytest.mark.parametrize("bad", [{"rain": {"unit": "mm", "channels": [0]}},
                                     {"rain": {"unique_id": "x", "unit": "mm", "channels": []}},
                                     {"foo": {}}])
    def test_bad_config(self, bad):
        with pytest.raises(FC.ForecastConfigError):
            FC.parse({"forecast": bad})

    def test_rain_sd_grows_with_lead_and_caps(self):
        g = FC.parse({"forecast": _fc_opts()})["rain"]
        fc = FC.Forecast(rain_groups=g)
        assert fc.rain_log_sd(0) == pytest.approx(0.35)
        assert fc.rain_log_sd(3) == pytest.approx(0.35 + 3 * 0.08)
        assert fc.rain_log_sd(30) == pytest.approx(1.0)


class TestLoad:
    now = (int(time.time()) // 86400) * 86400 + 6 * 3600.0
    today = _tz_day(now)

    def _load(self, data, **opts):
        o = {"forecast": _fc_opts(**opts)}
        return FC.load(o, MemSource(data), self.now, TZ, self.today)

    def test_target_day_is_issue_day_plus_lead(self):
        data = _ladder_data("omd", "mm", 0, self.now - 3600, [1, 2, 3, 4, 5, 6, 7, 8])
        fc = self._load(data)
        assert fc.rain_mm == {self.today + k: float(k + 1) for k in range(8)}

    def test_freshest_issue_wins_per_day(self):
        old = _ladder_data("omd", "mm", 0, self.now - 10 * 3600, [10, 20, 30])
        new = _ladder_data("omd", "mm", 0, self.now - 1 * 3600, [None, 5, 6])
        data = {**old, **new}
        data[("omd", "mm", 1)] = old[("omd", "mm", 1)] + new[("omd", "mm", 1)]
        data[("omd", "mm", 2)] = old[("omd", "mm", 2)] + new[("omd", "mm", 2)]
        fc = self._load(data)
        assert fc.rain_mm[self.today] == 10.0            # 리드 0 은 낡은 값뿐
        assert fc.rain_mm[self.today + 1] == 5.0 and fc.rain_mm[self.today + 2] == 6.0
        # 어제 받은 리드 1 은 오늘을 가리킨다 — 오늘 받은 리드 0(10)과 겹치면 더 늦게 받은 쪽
        y = self.now - 20 * 3600
        data2 = {("omd", "mm", 0): [(self.now - 3600, 9.0)], ("omd", "mm", 1): [(y, 99.0)]}
        assert self._load(data2).rain_mm[self.today] == 9.0

    def test_stale_values_dropped_and_noted(self):
        data = _ladder_data("omd", "mm", 0, self.now - 50 * 3600, [1, 1, 1])
        fc = self._load(data)
        assert fc.rain_mm == {} and any("비었" in n for n in fc.notes)

    def test_past_days_are_not_forecast(self):
        # 이틀 전에 받은 리드 0 → 이틀 전 날짜(관측이 맡는다)
        data = {("omd", "mm", 0): [(self.now - 30 * 3600, 7.0)]}
        fc = FC.load({"forecast": _fc_opts(max_age_h=48)}, MemSource(data), self.now, TZ, self.today)
        assert fc.rain_mm == {}

    def test_scale_and_clip_negative(self):
        data = _ladder_data("omd", "mm", 0, self.now - 600, [10, -1])
        fc = self._load(data, rain={"unique_id": "omd", "unit": "mm", "channels": [0, 1], "scale": 0.5})
        assert fc.rain_mm == {self.today: 5.0, self.today + 1: 0.0}

    def test_t_mean_needs_both(self):
        data = {**_ladder_data("omd", "C", 16, self.now - 600, [20, 22]),
                **_ladder_data("omd", "C", 24, self.now - 600, [10, None])}
        fc = self._load(data, t_max={"unique_id": "omd", "unit": "C", "channels": [16, 17]},
                        t_min={"unique_id": "omd", "unit": "C", "channels": [24, 25]})
        assert fc.t_mean == {self.today: 15.0}

    def test_read_failure_does_not_raise(self):
        class Boom(MemSource):
            def read_series(self, ref, window_s, now):
                raise OSError("down")
        fc = FC.load({"forecast": _fc_opts()}, Boom({}), self.now, TZ, self.today)
        assert fc.rain_mm == {}

    def test_coverage_days(self):
        fc = FC.Forecast(rain_mm={self.today + k: 1.0 for k in (0, 1, 2, 5)})
        assert FC.coverage_days(fc, self.today, 7) == 4


# ── 노지 모델 연결 ────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def base():
    now = (int(time.time()) // 86400) * 86400 + 6 * 3600.0
    data, planted, _ = FB._synthetic(now)
    return now, data, planted


def _run(base, rain_by_lead=None, et0=None, **opts):
    from aot.twin import engine, models
    now, data, planted = base
    d = dict(data)
    fopts = {"timezone": "Asia/Seoul",
             "rain": {"unique_id": "omd", "unit": "mm", "channels": list(range(8))}}
    if rain_by_lead is not None:
        d.update(_ladder_data("omd", "mm", 0, now - 1800, rain_by_lead))
    spec = FB._spec(planted, forecast=fopts, **opts)
    return engine.run_target(spec, MemSource(d), models.get("field"), FB.CAP, now)


def test_full_forecast_is_ok_with_8_days(base):
    r = _run(base, [0.0] * 8)
    assert r.status == Status.OK and r.output.meta["rain_fc_days"] == TRUST_D + 1
    assert "예보 비 8 일" in r.reason


def test_partial_forecast_is_degraded(base):
    r = _run(base, [0.0, 0.0, 0.0])
    assert r.status == Status.DEGRADED and r.output.meta["rain_fc_days"] == 3
    assert "3 일만" in r.reason


def test_configured_but_empty_is_degraded_zero_days(base):
    r = _run(base, None)
    assert r.status == Status.DEGRADED and r.output.meta["rain_fc_days"] == 0
    assert "비었" in r.reason


def test_unconfigured_is_as_before(base):
    from aot.twin import engine, models
    now, data, planted = base
    r = engine.run_target(FB._spec(planted), MemSource(data), models.get("field"), FB.CAP, now)
    assert r.status == Status.DEGRADED and r.output.meta["rain_fc_days"] == 0
    assert "앞날 비 없음" in r.reason


def test_forecast_rain_wets_soil_and_widens_band(base):
    dry = _run(base, [0.0] * 8).output.quantiles["daily"]["theta_sensor"]
    wet = _run(base, [0.0, 0.0, 30.0, 0.0, 0.0, 0.0, 0.0, 0.0]).output.quantiles["daily"]["theta_sensor"]
    assert wet["p50"][2] == pytest.approx(dry["p50"][2], abs=1e-6)   # 비 오기 전(궤적 칸 3 에서 반영)은 같다
    assert wet["p50"][4] > dry["p50"][4] + 0.5              # 리드 2 의 30 mm → 그 뒤 더 젖음
    w_dry = dry["p90"][5] - dry["p10"][5]
    w_wet = wet["p90"][5] - wet["p10"][5]
    assert w_wet > w_dry                                     # 비 배율 오차가 띠를 넓힌다


def test_longer_lead_widens_more(base):
    near = _run(base, [20.0, 0, 0, 0, 0, 0, 0, 0]).output.quantiles["daily"]["theta_sensor"]
    far = _run(base, [0, 0, 0, 0, 0, 0, 20.0, 0]).output.quantiles["daily"]["theta_sensor"]
    # 같은 20 mm 라도 먼 리드일수록 배율 오차가 커서 비 직후 하루 띠가 더 넓다
    j_near, j_far = 1, 7
    assert (far["p90"][j_far] - far["p10"][j_far]) > (near["p90"][j_near] - near["p10"][j_near])


def test_bad_forecast_config_is_not_twinnable(base):
    from aot.twin import engine, models
    now, data, planted = base
    spec = FB._spec(planted, forecast={"rain": {"unit": "mm", "channels": [0]}})
    r = engine.run_target(spec, MemSource(data), models.get("field"), FB.CAP, now)
    assert r.status == Status.NOT_TWINNABLE and "예보 설정" in r.reason


def test_meta_passes_server_contract(base):
    from aot.twin import output as O
    from aot.twin import contract_check
    now, _, _ = base
    r = _run(base, [0.0] * 8)
    pts = O.flatten(r.output)
    body = {"pubs": O.publications(pts), "points": [
        {"m": p.measurement, "id": p.device_id, "ch": p.channel, "ts": p.timestamp, "v": p.value,
         "tags": dict(p.tags)} for p in pts]}
    res = contract_check.validate(body, now)
    assert res.rejected == 0
    assert any(p.measurement == O.M_FLD_META and p.channel == O.FIELD_META["rain_fc_days"] for p in pts)
