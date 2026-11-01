# coding=utf-8
"""폐루프 시뮬레이터 시나리오(sim/scenarios.py) — 재현성과 범위."""
import datetime as dt
import json

import pytest

from aot.functions.utils.env_control.sim import scenarios as S


def _range(sc, key, h_from=0.0, h_to=None):
    wx = sc.weather()
    vals = [v for t, v in zip(wx.t, wx.data[key])
            if (t - sc.t0) / 3600 >= h_from and (h_to is None or (t - sc.t0) / 3600 < h_to)]
    return min(vals), max(vals)


def test_same_name_same_weather():
    a = S.get('hot_dry').weather().to_dict()
    b = S.get('hot_dry').weather().to_dict()
    assert a == b


def test_baseline_names_exist():
    for n in S.BASELINE:
        S.get(n)


def test_hot_dry_ranges():
    sc = S.get('hot_dry')
    lo, hi = _range(sc, 'T')
    assert hi == pytest.approx(35.0, abs=0.3) and lo >= 25.5
    wx = sc.weather()
    rh_at_peak = [rh for t, T, rh in zip(wx.t, wx.data['T'], wx.data['RH']) if T >= 33.0]
    assert rh_at_peak and all(30.0 <= x <= 40.0 for x in rh_at_peak)


def test_extreme_and_cold():
    assert _range(S.get('extreme_tunnel'), 'T')[1] >= 35.0
    assert S.get('extreme_tunnel').plant_overrides['opening_area_scale'] < 0.5
    assert any(f.kind == 'water_off' for f in S.get('extreme_tunnel_nowater').faults)
    lo, hi = _range(S.get('cold_night'), 'T')
    assert lo == pytest.approx(-5.0, abs=0.3) and hi <= 2.1


def test_rain_heat_has_rain_while_hot():
    sc = S.get('rain_heat')
    wx = sc.weather()
    hot_rain = [T for T, r in zip(wx.data['T'], wx.data['rain']) if r > 0]
    assert hot_rain and max(hot_rain) >= 30.0
    gate = S.get('rain_heat_gate').weather()
    assert max(T for T, r in zip(gate.data['T'], gate.data['rain']) if r > 0) >= 45.0


def test_solar_zero_at_night_positive_at_noon():
    noon = dt.datetime(2027, 7, 25, 12, 30, tzinfo=S.KST).timestamp()
    night = dt.datetime(2027, 7, 25, 1, 0, tzinfo=S.KST).timestamp()
    assert S.clear_sky_ghi(night) == 0.0
    assert 800.0 < S.clear_sky_ghi(noon) < 1100.0


def test_fault_window():
    f = S.Fault('indoor_missing', 6.0, 12.0)
    t0 = 1_800_000_000.0
    assert not f.active(t0 + 5.9 * 3600, t0)
    assert f.active(t0 + 6.0 * 3600, t0)
    assert not f.active(t0 + 12.0 * 3600, t0)


def test_synthetic_scenarios_are_after_snapshot():
    # 런타임 상태 시각보다 앞이면 시계가 거꾸로 간다(2026-10-08 스냅숏).
    snap = dt.datetime(2026, 10, 9, tzinfo=S.KST).timestamp()
    for n in S.names():
        if n != 'recorded':
            assert S.get(n).t0 > snap, n


def test_recorded_reads_kma_series(tmp_path):
    t0 = dt.datetime(2026, 10, 5, 23, 15, tzinfo=S.KST).timestamp()
    pts = [[t0 + i * 900, 10.0 + i * 0.1] for i in range(400)]
    raw = {'series': [
        {'device_id': 'd', 'measurement_id': 'f9b6779d-x', 'role': 'outdoor', 'points': pts},
        {'device_id': 'd', 'measurement_id': 'd5584725-x', 'role': 'outdoor',
         'points': [[p[0], 70.0] for p in pts]},
        {'device_id': 'd', 'measurement_id': '22dfd1eb-x', 'role': 'outdoor',
         'points': [[p[0], 1.0 if i == 10 else 0.0] for i, p in enumerate(pts)]},
    ]}
    path = tmp_path / 'ts.json'
    path.write_text(json.dumps(raw))
    sc = S.get('recorded', recorded_path=str(path))
    wx = sc.weather()
    assert wx(t0)['T'] == pytest.approx(10.0)
    assert wx(t0 + 450)['T'] == pytest.approx(10.05)
    assert wx(t0 + 10 * 900 + 60)['rain'] == pytest.approx(4.0)     # mm/15분 → mm/h
