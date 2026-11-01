# coding=utf-8
"""센서 유효성 검사(계약 §10.5)와 일 격자 입력."""
import math

import numpy as np
import pytest

from aot.functions.utils.field_twin import forcing as fz
from aot.functions.utils.field_twin import validity as vz

TZ = 9 * 3600
T0 = fz.day_number(2026, 8, 5) * 86400 - TZ        # 현지 08-05 00:00 의 epoch


def _hours(n_days):
    return [T0 + h * 3600 for h in range(24 * n_days)]


def test_air_only_junk_channels_are_rejected():
    """김제 `온습도_N`: '토양수분' 3.7 % 고정(표준편차 0.02), '토양온도' −95 °C."""
    rng = np.random.default_rng(0)
    t = _hours(10)
    vwc = list(3.7 + rng.normal(0, 0.02, len(t)))
    ts = list(-95.0 + rng.normal(0, 3.0, len(t)))
    v1 = vz.channel_verdict(t, vwc)
    v2 = vz.channel_verdict(t, ts, value_range=vz.SOIL_T_RANGE_C)
    assert not v1['usable'] and v1['reasons'].get('flat', 0) == len(t)
    assert not v2['usable'] and v2['reasons'].get('range', 0) == len(t)


def test_real_soil_channel_with_diurnal_wiggle_is_kept():
    t = _hours(10)
    v = [20 + 1.5 * math.sin(2 * math.pi * h / 24) for h in range(len(t))]
    r = vz.channel_verdict(t, v)
    assert r['usable'] and r['valid_frac'] == 1.0


def test_out_of_range_points_are_dropped_one_by_one():
    t = _hours(2)
    v = [50 + (h % 5) for h in range(len(t))]
    v[10] = 80.0          # 포화 너머(> 70 %) — 그 점만 버린다
    v[11] = -1.0
    ok, reason = vz.screen_series(t, v)
    assert not ok[10] and not ok[11] and reason[10] == 'range'
    assert ok.sum() == len(t) - 2


def test_daily_and_boundary_means():
    t = _hours(3)
    v = [float(h // 24) * 10 + 5 for h in range(len(t))]     # 날마다 5, 15, 25
    dm = vz.daily_means(t, v, tz_offset_s=TZ)
    d0 = fz.day_number(2026, 8, 5)
    assert dm[d0][0] == 5 and dm[d0 + 1][0] == 15
    bm = vz.boundary_means(t, v, tz_offset_s=TZ)
    # 08-06 00 시 ±2 h = 앞날 22·23 시(5) + 그날 0·1·2 시(15)
    assert bm[d0 + 1][0] == pytest.approx((2 * 5 + 3 * 15) / 5)


def test_placement_change_from_soil_temperature_range():
    """토양온도 일교차가 6 °C → 30 °C 로 커진 날을 센서 위치 변화로 잡는다."""
    t = _hours(14)
    ts = []
    for h in range(len(t)):
        amp = 3.0 if h < 24 * 9 else 15.0
        ts.append(25 + amp * math.sin(2 * math.pi * (h % 24 - 9) / 24))
    days = vz.placement_changes(t, ts, tz_offset_s=TZ)
    assert days == [fz.day_number(2026, 8, 5) + 9]
    # 날마다 같은 일교차면 아무 일도 없다
    assert vz.placement_changes(t, [25 + 3 * math.sin(h) for h in range(len(t))]) == []


def test_hargreaves_is_plausible_in_late_summer():
    """김제(35.85 N) 8 월 말 22~31 °C → ET0 4~6 mm/일 범위."""
    doy = fz.date_of(fz.day_number(2026, 8, 25)).timetuple().tm_yday
    e = fz.hargreaves_et0(22.0, 31.0, 35.85, doy)
    assert 3.5 < e < 6.5


def test_et0_daily_falls_back_when_power_is_missing():
    power = {
        'T2M': {'20260801': 27.0, '20260802': 27.0, '20260803': -999.0},
        'T2M_MAX': {'20260801': 31.0, '20260802': 31.0, '20260803': -999.0},
        'T2M_MIN': {'20260801': 23.0, '20260802': 23.0, '20260803': -999.0},
        'RH2M': {'20260801': 75.0, '20260802': 75.0, '20260803': -999.0},
        'WS2M': {'20260801': 2.0, '20260802': 2.0, '20260803': -999.0},
        'ALLSKY_SFC_SW_DWN': {'20260801': 20.0, '20260802': -999.0, '20260803': -999.0},
    }
    d1 = fz.day_number(2026, 8, 1)
    pm = lambda *a: 4.2                                     # noqa: E731 — PM 대역
    out = fz.et0_daily(power, 35.85, pm=pm, fallback_temps={d1 + 2: (22.0, 30.0)})
    assert out[d1] == (4.2, 'pm')
    assert out[d1 + 1][1] == 'hs' and out[d1 + 1][0] > 0
    assert out[d1 + 2][1] == 'hs_alt'


def test_daily_sum_counts_hours():
    pts = [(T0 + h * 3600, 0.5) for h in range(30)]
    s = fz.daily_sum(pts, TZ, scale=4.0)
    d0 = fz.day_number(2026, 8, 5)
    assert s[d0] == (48.0, 24) and s[d0 + 1] == (12.0, 6)
