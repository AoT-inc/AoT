# coding=utf-8
"""OPEN_METEO_DAILY_FORECAST — 일별 예보 입력(노지 트윈의 앞날 비·ET0 입력).

지키는 것: 채널 규칙(묶음×리드), 리드는 응답 날짜와 받은 시각의 현지 날짜 차로 정한다,
결측은 쓰지 않는다(0 으로 채우지 않음), 요청 파라미터, 429 공유, 모델 입력·예보 시각 표식.
네트워크·DB 없음.
"""
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

import aot.inputs.open_meteo_daily_forecast as df
import aot.inputs.open_meteo_weather as live

KST = 9 * 3600
# 2026-10-21 16:00 UTC = KST 10-22 01:00 — 현지 날짜가 UTC 날짜와 다른 시각
NOW = datetime(2026, 10, 21, 16, 0, tzinfo=timezone.utc).timestamp()      # KST 10-22 01:00


def _daily(start="2026-10-22", n=8, **fn):
    import datetime as _d
    d0 = _d.date.fromisoformat(start)
    out = {"time": [(d0 + _d.timedelta(days=i)).isoformat() for i in range(n)]}
    for var, f in fn.items():
        out[var] = [f(i) for i in range(n)]
    return out


class TestChannels:
    def test_layout(self):
        assert df.channel_of("rain", 0) == 0 and df.channel_of("rain", 7) == 7
        assert df.channel_of("et0", 0) == 8 and df.channel_of("t_max", 3) == 19
        assert df.channel_of("pop", 7) == 39 and len(df.measurements_dict) == 40

    def test_units(self):
        m = df.measurements_dict
        assert (m[0]["measurement"], m[0]["unit"]) == ("rain", "mm")
        assert (m[8]["measurement"], m[8]["unit"]) == ("evapotranspiration", "mm")
        assert m[16]["unit"] == "C" and m[32]["unit"] == "percent"


class TestValues:
    def test_lead_from_local_date_not_array_order(self):
        # 현지(KST)는 10-22 01:00. 응답이 하루 전(10-21)부터 오더라도 리드 0 은 10-22
        d = _daily(start="2026-10-21", n=9, precipitation_sum=lambda i: float(i))
        out = df.values_from_daily(d, NOW, KST)
        assert out[0] == 1.0 and out[7] == 8.0 and len(out) == 8        # 10-21(리드 −1) 은 버린다

    def test_utc_offset_zero_would_shift_the_day(self):
        d = _daily(start="2026-10-22", n=8, precipitation_sum=lambda i: float(i))
        assert df.values_from_daily(d, NOW, KST)[0] == 0.0
        # 오프셋을 UTC 로 잘못 보면 현지 10-21 이 오늘 — 리드가 하루 밀려 7 이 나온다는 점을 확인(그래서 오프셋 없으면 쓰지 않는다)
        assert df.values_from_daily(d, NOW, 0)[1] == 0.0

    def test_missing_and_bad_values_are_skipped_not_zero(self):
        d = _daily(precipitation_sum=lambda i: None if i == 2 else (float("nan") if i == 3 else (True if i == 4 else 1.5)))
        out = df.values_from_daily(d, NOW, KST)
        assert 2 not in out and 3 not in out and 4 not in out and out[0] == 1.5

    def test_groups(self):
        d = _daily(precipitation_sum=lambda i: 1.0, et0_fao_evapotranspiration=lambda i: 3.0,
                   temperature_2m_max=lambda i: 20.0, temperature_2m_min=lambda i: 10.0,
                   precipitation_probability_max=lambda i: 80)
        out = df.values_from_daily(d, NOW, KST)
        assert out[df.channel_of("et0", 2)] == 3.0 and out[df.channel_of("pop", 0)] == 80.0
        assert out[df.channel_of("t_min", 7)] == 10.0

    def test_disabled_channels_skipped(self):
        d = _daily(precipitation_sum=lambda i: 1.0, et0_fao_evapotranspiration=lambda i: 3.0)
        out = df.values_from_daily(d, NOW, KST, is_enabled=lambda ch: ch < 8)
        assert set(out) == set(range(8))

    @pytest.mark.parametrize("bad", [None, [], {"time": "x"}, {"time": ["not-a-date"]}])
    def test_malformed(self, bad):
        assert df.values_from_daily(bad, NOW, KST) == {}

    def test_needed_variables(self):
        assert df.needed_variables(lambda ch: ch < 8) == {"precipitation_sum"}
        assert "et0_fao_evapotranspiration" in df.needed_variables(lambda ch: True)


class _Resp:
    def __init__(self, payload, status=200):
        self._p, self.status_code, self.headers = payload, status, {}

    def json(self):
        return self._p

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)


def _module(monkeypatch, resp, calls):
    mod = df.InputModule.__new__(df.InputModule)
    mod.logger = SimpleNamespace(error=lambda *a, **k: calls.setdefault("err", []).append(a),
                                 debug=lambda *a, **k: None, warning=lambda *a, **k: None)
    mod.latitude, mod.longitude, mod.api_key, mod.model = 35.8, 127.1, None, "best_match"
    mod.is_enabled = lambda ch: True
    mod.value_set = lambda ch, v: calls.setdefault("set", {}).__setitem__(ch, v)
    monkeypatch.setattr(df, "_now", lambda: NOW)
    monkeypatch.setattr(df.requests, "get", lambda url, params=None, timeout=None:
                        calls.setdefault("req", []).append(params) or resp)
    live._RATE_LIMITED_UNTIL.clear()
    return mod


class TestGetMeasurement:
    def test_request_and_values(self, monkeypatch):
        calls = {}
        payload = {"utc_offset_seconds": KST, "daily": _daily(precipitation_sum=lambda i: 2.0)}
        mod = _module(monkeypatch, _Resp(payload), calls)
        assert mod.get_measurement() is not None
        p = calls["req"][0]
        assert p["timezone"] == "auto" and p["forecast_days"] == 8 and p["precipitation_unit"] == "mm"
        assert "precipitation_sum" in p["daily"]
        assert calls["set"][0] == 2.0 and calls["set"][7] == 2.0

    def test_no_offset_writes_nothing(self, monkeypatch):
        calls = {}
        mod = _module(monkeypatch, _Resp({"daily": _daily(precipitation_sum=lambda i: 2.0)}), calls)
        mod.get_measurement()
        assert "set" not in calls

    def test_429_is_shared_and_blocks(self, monkeypatch):
        calls = {}
        mod = _module(monkeypatch, _Resp({"reason": "Daily API request limit exceeded"}, 429), calls)
        mod.get_measurement()
        assert live._RATE_LIMITED_UNTIL                       # 같은 dict 에 기록
        mod.get_measurement()
        assert len(calls["req"]) == 1                          # 두 번째는 묻지 않는다
        live._RATE_LIMITED_UNTIL.clear()


class TestMarkers:
    def test_model_and_forecast_time_drivers(self):
        info = df.INPUT_INFORMATION
        assert info["data_origin"] == "model" and info["data_time"] == "forecast"

    def test_rain_accumulation_table(self):
        from aot.utils.inputs import _RAIN_ACCUM_BY_DRIVER
        assert _RAIN_ACCUM_BY_DRIVER["OPEN_METEO_DAILY_FORECAST"] == {"mm": 86400}
