# coding=utf-8
"""극한 기상 시나리오(sim/storm.py · scenarios.STORM)와 극한 기상 지표(metrics.storm_kpis).

시나리오가 거짓이면 그 위에서 제어기를 평가한 모든 판정이 거짓이 된다. 여기서는
  - 같은 이름이면 언제나 같은 값인가(결정성)
  - 물리 상식 안에 있는가(RH ≤ 100, 돌풍 ≥ 평균, 야간 일사 0, 맑은 하늘 일사 이하 …)
  - 사용자가 요구한 모양(태풍의 풍속·기압·풍향 회전, 스콜의 15 K/20 분 …)을 실제로 내는가
  - 지표가 손으로 센 값과 맞는가
를 본다.
"""
import bisect
import datetime as dt
import importlib.util
import math
import os

import pytest

from aot.functions.utils.env_control.sim import scenarios as S
from aot.functions.utils.env_control.sim import storm as W
from aot.functions.utils.env_control.sim.metrics import STORM_COLUMNS, storm_kpis, summarize
from aot.functions.utils.env_control.sim.plant import ActuatorSpec, Plant, PlantParams


def _wx(name):
    sc = S.get(name)
    return sc, sc.weather()


def _hours(sc, wx):
    return [(t - sc.t0) / 3600.0 for t in wx.t]


def _kst(t):
    return dt.datetime.fromtimestamp(t, S.KST)


def _trailing(vs, i, n=10):
    lo = max(0, i - n + 1)
    return sum(vs[lo:i + 1]) / (i + 1 - lo)


# ─────────────────────────────────────────────────────────────────────────────
# 등록·결정성·물리 상식
# ─────────────────────────────────────────────────────────────────────────────

def test_storm_group_is_registered():
    assert S.group('storm') == S.STORM
    assert 'storm' in S.GROUP_NAMES
    assert set(S.STORM) <= set(S.names())
    assert S.group('baseline') == S.BASELINE
    assert set(S.group('all')) == set(S.names())
    with pytest.raises(KeyError):
        S.group('nope')
    # 기본 묶음은 그대로 — 기존 비교 결과가 바뀌면 안 된다.
    assert not set(S.STORM) & set(S.BASELINE)


@pytest.mark.parametrize('name', S.STORM)
def test_deterministic_and_after_snapshot(name):
    a = S.get(name).weather().to_dict()
    b = S.get(name).weather().to_dict()
    assert a == b
    assert S.get(name).t0 > dt.datetime(2026, 10, 9, tzinfo=S.KST).timestamp()


@pytest.mark.parametrize('name', S.STORM)
def test_duration_and_grid(name):
    sc, wx = _wx(name)
    assert 24 <= sc.hours <= (72 if name == 'heatwave_tropical_night' else 48)
    assert wx.t[1] - wx.t[0] == 60.0
    assert len(wx.t) == int(round(sc.hours * 60)) + 1
    assert wx.t[-1] == pytest.approx(sc.t_end)


@pytest.mark.parametrize('name', S.STORM)
def test_physical_bounds(name):
    sc, wx = _wx(name)
    d = wx.data
    n = len(wx.t)
    for k in ('T', 'RH', 'solar', 'wind', 'gust', 'wind_dir', 'rain', 'pressure', 'visibility'):
        assert len(d[k]) == n, k
        assert all(math.isfinite(v) for v in d[k]), k
    assert all(0.0 < v <= 100.0 for v in d['RH'])
    assert all(v >= 0.0 for v in d['wind'])
    assert all(g >= w for g, w in zip(d['gust'], d['wind']))
    assert all(0.0 <= v < 360.0 for v in d['wind_dir'])
    assert all(v >= 0.0 for v in d['rain'])
    assert max(d['rain']) <= 80.0
    assert all(-15.0 <= v <= 45.0 for v in d['T'])
    assert all(940.0 <= v <= 1040.0 for v in d['pressure'])
    assert all(v > 0.0 for v in d['visibility'])
    for t, s, c in zip(wx.t, d['solar'], d['cloud']):
        clear = S.clear_sky_ghi(t, sc.lat, sc.lon)
        assert 0.0 <= s <= clear + 0.2
        assert 0.0 <= c <= 1.0
    # 이슬점이 기온을 넘을 수 없다 — 모든 RH 가 100 이하인 것으로 확인했다. 기온 변화율도 상식 안:
    # 1 분에 2.5 K 이상 뛰지 않는다(스콜 앞머리가 가장 가파르다).
    assert max(abs(a - b) for a, b in zip(d['T'], d['T'][1:])) < 2.5


@pytest.mark.parametrize('name', S.STORM)
def test_night_solar_is_zero(name):
    sc, wx = _wx(name)
    for t, s in zip(wx.t, wx.data['solar']):
        if S.sun_sin_elevation(t, sc.lat, sc.lon) <= 0.0:
            assert s == 0.0


# ─────────────────────────────────────────────────────────────────────────────
# 1) 태풍
# ─────────────────────────────────────────────────────────────────────────────

class TestTyphoon:
    def setup_method(self):
        self.sc, self.wx = _wx('typhoon')
        self.d = self.wx.data
        self.h = _hours(self.sc, self.wx)
        self.w10 = [_trailing(self.d['wind'], i) for i in range(len(self.h))]

    def test_wind_ramps_to_20_30_with_gusts(self):
        peak = max(self.w10)
        assert 20.0 <= peak <= 30.0
        assert 26.0 <= max(self.d['gust']) <= 40.0
        i = self.w10.index(peak)
        assert self.d['gust'][i] > self.w10[i]            # 돌풍이 평균보다 세다
        # 오르막이 있다: 12 h 전 평균은 최대의 70 % 미만
        assert self.w10[max(0, i - 12 * 60)] < 0.7 * peak
        # 최대풍은 시작 후 18~23 h(9/6 오전)
        assert 18.0 <= self.h[i] <= 23.0

    def test_pressure_drops_and_recovers(self):
        p = self.d['pressure']
        assert p[0] - min(p) >= 40.0
        assert min(p) <= 965.0
        i = p.index(min(p))
        assert abs(self.h[i] - self.h[self.w10.index(max(self.w10))]) < 3.0   # 기압 최저 ≈ 최대풍
        assert p[-1] >= 1000.0

    def test_rain_bands_10_to_50(self):
        r = self.d['rain']
        assert 40.0 <= max(r) <= 60.0
        # 10 mm/h 이상이 여러 시간 이어진다
        heavy_h = sum(1 for v in r if v >= 10.0) / 60.0
        assert 8.0 <= heavy_h <= 20.0
        # 띠 사이에는 약해진다(이슬비) — 연속 폭우가 아니다
        core = [v for h, v in zip(self.h, r) if 12 <= h <= 31]
        assert min(core) < 8.0

    def test_wind_direction_rotates_clockwise(self):
        i = self.w10.index(max(self.w10))
        before = self.d['wind_dir'][i - 6 * 60]
        at = self.d['wind_dir'][i]
        after = self.d['wind_dir'][i + 6 * 60]
        assert before < at < after
        assert after - before >= 90.0

    def test_humid_dark_in_the_core_then_hot_humid_sun(self):
        core = [i for i, h in enumerate(self.h) if 16 <= h <= 30]
        assert all(self.d['RH'][i] >= 95.0 for i in core if self.d['rain'][i] >= 10.0)
        assert sum(self.d['RH'][i] for i in core) / len(core) >= 97.0
        day_core = [i for i in core
                    if S.clear_sky_ghi(self.wx.t[i], self.sc.lat, self.sc.lon) > 200.0]
        assert day_core
        ratio = [self.d['solar'][i] / S.clear_sky_ghi(self.wx.t[i], self.sc.lat, self.sc.lon)
                 for i in day_core]
        assert max(ratio) <= 0.15
        # 갠 뒤: 마지막 2 시간은 덥고 습한 맑은 날, 그 앞(아침)에 이미 비가 없다
        tail = [i for i, h in enumerate(self.h) if h >= self.sc.hours - 2]
        assert all(self.d['rain'][i] == 0.0 for i, h in enumerate(self.h) if h >= 34.0)
        assert all(self.d['T'][i] >= 30.0 for i in tail)
        assert all(55.0 <= self.d['RH'][i] <= 75.0 for i in tail)
        assert all(self.d['solar'][i] >= 600.0 for i in tail)

    def test_outage_variant_shares_the_weather(self):
        a = S.get('typhoon').weather().to_dict()
        b = S.get('sensor_storm_outage').weather().to_dict()
        assert a == b


# ─────────────────────────────────────────────────────────────────────────────
# 2) 스콜
# ─────────────────────────────────────────────────────────────────────────────

def test_squall_gust_front_drop_rain_and_sun_returns():
    sc, wx = _wx('squall_heat')
    d, h = wx.data, _hours(sc, wx)
    tf = W.SQ_TF
    pre = [i for i, x in enumerate(h) if tf - 1.0 <= x < tf - 0.2]
    assert all(33.0 <= d['T'][i] <= 35.5 for i in pre)
    assert max(d['wind'][i] for i in pre) < 5.0
    assert all(d['rain'][i] == 0.0 for i in pre)
    # 20 분에 15 K 하강
    k = 20
    drop = max(a - b for a, b in zip(d['T'], d['T'][k:]))
    assert 14.0 <= drop <= 17.0
    # 돌풍전선: 풍속·풍향이 순식간에 바뀐다
    i0 = bisect.bisect_left(h, tf - 0.01)
    assert max(d['gust'][i0:i0 + 15]) >= 20.0
    assert abs(d['wind_dir'][i0 + 15] - d['wind_dir'][i0 - 5]) >= 90.0
    # 호우 30 분: 30 mm/h 이상이 20~40 분
    heavy_min = sum(1 for v in d['rain'] if v >= 30.0)
    assert 20 <= heavy_min <= 40
    assert max(d['rain']) >= 50.0
    # 기온 하강 중 습도는 이슬점 지배 — 비가 오는 동안 RH ≥ 95 %
    rainy = [i for i, v in enumerate(d['rain']) if v >= 10.0]
    assert all(d['RH'][i] >= 95.0 for i in rainy)
    # 17:30 이후 다시 해가 난다(저녁 해라 맑은 하늘 일사의 70 % 이상), 이튿날은 맑고 덥다
    i1 = bisect.bisect_left(h, tf + 1.9)
    clear = S.clear_sky_ghi(wx.t[i1], sc.lat, sc.lon)
    assert d['solar'][i1] >= 0.7 * clear
    day2 = [d['T'][i] for i, x in enumerate(h) if x >= 24.0]
    assert max(day2) >= 33.0
    assert all(v == 0.0 for i, v in enumerate(d['rain']) if h[i] > tf + 2.0)


# ─────────────────────────────────────────────────────────────────────────────
# 3) 폭염 + 열대야
# ─────────────────────────────────────────────────────────────────────────────

def test_heatwave_tropical_night():
    sc, wx = _wx('heatwave_tropical_night')
    d = wx.data
    days = {}
    for t, T in zip(wx.t, d['T']):
        days.setdefault(_kst(t).date(), []).append(T)
    peaks = [max(v) for k, v in sorted(days.items())][:3]
    for got, want in zip(peaks, (36.0, 37.5, 38.0)):
        assert got == pytest.approx(want, abs=0.3)
    assert 36.0 <= max(d['T']) <= 38.5
    night = [i for i, t in enumerate(wx.t)
             if d['solar'][i] == 0.0 and (_kst(t).hour >= 22 or _kst(t).hour < 6)]
    assert night
    assert min(d['T'][i] for i in night) >= 27.0           # 열대야: 밤 최저 27 °C 이상
    # 새벽 최저 기온 때 RH 는 높다
    dawn = [i for i, t in enumerate(wx.t) if _kst(t).hour == 5]
    assert sum(d['RH'][i] for i in dawn) / len(dawn) >= 88.0
    assert all(d['rain'][i] == 0.0 for i in range(len(wx.t)))


# ─────────────────────────────────────────────────────────────────────────────
# 4) 푄(건조열풍)
# ─────────────────────────────────────────────────────────────────────────────

def test_foehn_dry_hot_steady_wind():
    sc, wx = _wx('foehn_dry_wind')
    d, h = wx.data, _hours(sc, wx)
    day = [i for i, x in enumerate(h) if x >= 3.0 and d['solar'][i] > 850.0]
    assert day
    assert all(14.0 <= d['RH'][i] <= 21.0 for i in day)
    assert all(28.0 <= d['T'][i] <= 32.0 for i in day)
    after = [i for i, x in enumerate(h) if x >= 3.0]
    w10 = [_trailing(d['wind'], i) for i in after]
    assert 8.5 <= sum(w10) / len(w10) <= 11.5
    assert max(w10) - min(w10) < 7.0                        # 정속에 가깝다(10 분 평균 ±3 m/s 이내)
    # 강한 해: 낮 일사는 맑은 하늘의 95 % 이상
    assert all(d['solar'][i] >= 0.95 * S.clear_sky_ghi(wx.t[i], sc.lat, sc.lon) for i in day)
    # 밤에도 마르고 따뜻하다
    night = [i for i in after if d['solar'][i] == 0.0]
    assert all(d['RH'][i] <= 30.0 for i in night)
    assert min(d['T'][i] for i in night) >= 23.0


# ─────────────────────────────────────────────────────────────────────────────
# 5) 늦서리
# ─────────────────────────────────────────────────────────────────────────────

def test_cold_snap_radiative_frost():
    sc, wx = _wx('cold_snap_frost')
    d, h = wx.data, _hours(sc, wx)
    day1 = [d['T'][i] for i, x in enumerate(h) if x <= 10.0]
    assert 17.5 <= max(day1) <= 18.5
    assert min(d['T']) == pytest.approx(-4.0, abs=0.3)
    i = d['T'].index(min(d['T']))
    assert 4 <= _kst(wx.t[i]).hour <= 6                   # 복사냉각 최저는 새벽
    assert d['solar'][i] == 0.0
    night = [j for j, t in enumerate(wx.t) if d['solar'][j] == 0.0 and 0 <= _kst(t).hour < 6]
    assert sum(d['wind'][j] for j in night) / len(night) <= 0.7     # 바람 없음
    assert all(d['cloud'][j] <= 0.05 for j in night)               # 맑음
    assert all(d['rain'][j] == 0.0 for j in range(len(wx.t)))
    assert d['RH'][i] >= 85.0                                      # 최저 때 포화 근처
    # 이튿날 아침은 쾌청하다
    morning = [j for j, t in enumerate(wx.t) if _kst(t).day == 11 and _kst(t).hour == 9]
    assert all(d['solar'][j] >= 500.0 for j in morning)


# ─────────────────────────────────────────────────────────────────────────────
# 6) 아침 안개
# ─────────────────────────────────────────────────────────────────────────────

def test_fog_then_sudden_clearing():
    sc, wx = _wx('fog_morning_overcast')
    d, h = wx.data, _hours(sc, wx)
    fog = [i for i, x in enumerate(h) if W.FOG_ON_H <= x < W.FOG_OFF_H]
    assert all(d['RH'][i] == 100.0 for i in fog)
    assert all(d['visibility'][i] <= 0.3 for i in fog)
    assert max(d['wind'][i] for i in fog) < 2.0
    morning = [i for i in fog if d['solar'][i] > 0.0]
    assert morning
    for i in morning:
        clear = S.clear_sky_ghi(wx.t[i], sc.lat, sc.lon)
        if _kst(wx.t[i]).hour < 10 or (_kst(wx.t[i]).hour == 10 and _kst(wx.t[i]).minute < 30):
            assert d['solar'][i] <= 0.15 * clear
    # 11:30 이후는 맑은 하늘의 70 % 이상, RH 는 눈에 띄게 내려간다
    late = [i for i, t in enumerate(wx.t) if _kst(t).day == 19 and 11 <= _kst(t).hour <= 14
            and (_kst(t).hour, _kst(t).minute) >= (11, 30)]
    assert all(d['solar'][i] >= 0.7 * S.clear_sky_ghi(wx.t[i], sc.lat, sc.lon) for i in late)
    assert min(d['RH'][i] for i in late) < 60.0
    # 걷히는 순간은 갑작스럽다: 30 분 사이 일사 +300 W/m² 이상
    k = 30
    assert max(b - a for a, b in zip(d['solar'], d['solar'][k:])) >= 300.0


# ─────────────────────────────────────────────────────────────────────────────
# 7·8) 예보 강수 · 관측소 두절
# ─────────────────────────────────────────────────────────────────────────────

def test_forecast_rain_vs_gauge():
    sc, wx = _wx('rain_gauge_vs_forecast')
    d = wx.data
    assert all(v == 0.0 for v in d['rain'])                 # 실측 강우계는 0
    assert 1.5 <= max(d['fc_rain']) <= 3.0
    assert sum(1 for v in d['fc_rain'] if v > 0) / 60.0 == pytest.approx(6.0, abs=0.1)
    hours = {_kst(t).hour for t, v in zip(wx.t, d['fc_rain']) if v > 0}
    assert hours == {12, 13, 14, 15, 16, 17}
    assert max(d['T']) >= 34.0                              # 덥고 맑은 날이 이어진다
    assert min(d['solar'][i] / max(1.0, S.clear_sky_ghi(wx.t[i], sc.lat, sc.lon))
               for i in range(len(wx.t)) if S.clear_sky_ghi(wx.t[i], sc.lat, sc.lon) > 500) > 0.7
    # 같은 날씨, 센서 순위만 다르다
    p = S.get('rain_gauge_vs_forecast_primary')
    assert p.weather().to_dict() == wx.to_dict()
    assert [e['tier'] for e in sc.extra_sensors] == ['backup']
    assert [e['tier'] for e in p.extra_sensors] == ['primary']
    assert sc.extra_sensors[0]['device'] == 'OPEN_METEO_FORECAST'
    assert sc.extra_sensors[0]['channels'][0]['key'] == 'fc_rain'
    assert sc.meta()['extra_sensors'][0]['tier'] == 'backup'


def test_sensor_storm_outage_windows_bracket_the_peak():
    sc, wx = _wx('sensor_storm_outage')
    w60 = [_trailing(wx.data['wind'], i, 60) for i in range(len(wx.t))]       # 1 시간 평균
    h_peak = (wx.t[w60.index(max(w60))] - sc.t0) / 3600.0
    stale = [f for f in sc.faults if f.kind == 'outdoor_stale']
    assert len(stale) == 2
    assert all(abs((f.end_h - f.start_h) - 2.0) < 1e-9 for f in stale)
    peak_win = [f for f in stale if f.start_h <= h_peak <= f.end_h]
    assert len(peak_win) == 1                               # 최대풍 한복판
    early = [f for f in stale if f is not peak_win[0]][0]
    # 첫 두절의 직전 풍속은 문턱(12 m/s) 아래 — 낡은 '평온' 이 되도록
    i = bisect.bisect_left(wx.t, sc.t0 + early.start_h * 3600.0)
    assert _trailing(wx.data['wind'], i) < 12.0
    assert _trailing(wx.data['rain'], i, 15) < 2.0           # 15 분 누적 0.5 mm 미만 — 게이트 문턱 아래
    # 두절 중에는 실제로 나빠진다(여는 근거로 쓰면 안 되는 이유)
    j = bisect.bisect_left(wx.t, sc.t0 + early.end_h * 3600.0)
    assert max(wx.data['rain'][i:j]) >= 4.0 or _trailing(wx.data['wind'], j) >= 11.0
    assert sc.meta()['faults'][0]['kind'] == 'outdoor_stale'


def test_sensor_outage_night_humid_stale_then_drizzle():
    """김제 10/10 밤(최종 회귀 §5-4): 습한 밤 → 22:30~01:30 두절 → 00:00 이슬비. 비는 두절 안에서 시작한다."""
    sc, wx = _wx('sensor_outage_night')
    hs = _hours(sc, wx)
    stale = [f for f in sc.faults if f.kind == 'outdoor_stale']
    assert len(stale) == 1
    f = stale[0]
    assert (_kst(sc.t0 + f.start_h * 3600.0).strftime('%H:%M'),
            _kst(sc.t0 + f.end_h * 3600.0).strftime('%H:%M')) == ('22:30', '01:30')
    assert f.target is None                                  # 실외 전부가 굳는다(기상청 두절)
    rain_h = [h for h, r in zip(hs, wx.data['rain']) if r > 0.0]
    assert rain_h and _kst(sc.t0 + rain_h[0] * 3600.0).strftime('%H:%M') == '00:00'
    assert f.start_h + 0.5 <= rain_h[0] < f.end_h            # 두절 30 분 뒤, 두절 안에서 시작
    # 이슬비 — 15 분 누적이 강우 게이트 문턱(0.5 mm)을 넘지 않을 만큼 가늘다
    assert max(wx.data['rain']) <= 2.5
    assert max(_trailing(wx.data['rain'], i, 15) for i in range(len(wx.t))) / 4.0 < 0.5
    # 두절 직전 마지막 실측은 비 없음(낡은 '비 안 옴' — 여는 근거가 못 된다)
    i = bisect.bisect_left(wx.t, sc.t0 + f.start_h * 3600.0)
    assert sum(wx.data['rain'][max(0, i - 15):i + 1]) == 0.0
    # 습한 밤: 바깥 RH 65 % 이상이되 비 오기 전에는 95 % 아래(실내보다 건조 — 습도 상한이 창을 여는 밤), 고요, 밤 일사 0
    night = [k for k, h in enumerate(hs) if 7.0 <= h <= 18.0]
    assert min(wx.data['RH'][k] for k in night) >= 65.0
    assert max(wx.data['RH'][k] for k, h in enumerate(hs) if 7.0 <= h < 12.0) < 95.0
    assert max(wx.data['wind'][k] for k in night) < 4.0
    assert all(wx.data['solar'][k] == 0.0 for k, h in enumerate(hs) if 7.0 <= h <= 18.0)
    assert sc.name in S.STORM and sc.init['RH'] >= 85.0


# ─────────────────────────────────────────────────────────────────────────────
# 시설 물리와의 합 — 극한 외기에서도 값이 터지지 않는다
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize('name,span,openpct', [
    ('typhoon', (16.0, 26.0), 100.0),
    ('typhoon', (16.0, 26.0), 0.0),
    ('squall_heat', (8.0, 14.0), 100.0),
    ('cold_snap_frost', (10.0, 24.0), 0.0),
])
def test_plant_stays_finite_under_extreme_weather(name, span, openpct):
    sc, wx = _wx(name)
    t_a, t_b = sc.t0 + span[0] * 3600.0, sc.t0 + span[1] * 3600.0
    win = ActuatorSpec('win', 'opening', area_m2=60.0)
    w = wx(t_a)
    pl = Plant(PlantParams(T_ground=10.0 if name == 'cold_snap_frost' else 18.0), [win], t_a,
               T=w['T'] + 1.0, RH=min(95.0, w['RH']))
    pl.set_position('win', openpct)
    pl.advance(t_b, wx, dt=30.0)
    for k in ('T', 'RH', 'VPD', 'Tm', 'CO2'):
        assert all(math.isfinite(v) for v in pl.fine[k]), k
    assert max(pl.fine['T']) < 60.0 and min(pl.fine['T']) > -30.0
    assert all(0.0 < v <= 105.0 for v in pl.fine['RH'])
    if openpct == 100.0 and name == 'typhoon':
        # 열어 둔 채 태풍 — 실내가 외기를 거의 따른다(밀폐 시보다 훨씬)
        ext = pl.fine['T_ext']
        assert abs(pl.fine['T'][-1] - ext[-1]) < 3.0


def test_closed_greenhouse_frost_follows_clear_sky_cooling():
    sc, wx = _wx('cold_snap_frost')
    t_a, t_b = sc.t0 + 6.0 * 3600.0, sc.t0 + 23.0 * 3600.0
    pl = Plant(PlantParams(T_ground=10.0), [ActuatorSpec('win', 'opening', area_m2=60.0)], t_a,
               T=16.0, RH=45.0)
    pl.advance(t_b, wx, dt=30.0)
    # 밀폐·무난방: 새벽에 0 °C 아래로 내려간다(이 시나리오가 서리 시험이 되려면)
    assert min(pl.fine['T']) < 0.0
    # 그러나 외기보다 낮아지지는 않는다 — 지중·질량 열이 막아 준다
    assert min(pl.fine['T']) >= min(pl.fine['T_ext']) - 2.5


# ─────────────────────────────────────────────────────────────────────────────
# 지표
# ─────────────────────────────────────────────────────────────────────────────

T0 = 1_800_000_000.0     # 2027-01-15 ~ 정오 KST 부근. 지표는 일사가 0 인지로 밤을 정한다.


def _trace(n, wind=None, gust=None, rain=None, solar=None, T=None, extT=None, open_=None,
           Tm=None, pool=None, fog=None, rh_ext=None, disp=None, faults=None, warm=0.0):
    z = [0.0] * n
    wind = wind or z
    wxd = {'t': [T0 + 60.0 * i for i in range(n)], 'T': extT or [20.0] * n, 'RH': rh_ext or [60.0] * n,
           'solar': solar or [500.0] * n, 'wind': wind, 'gust': gust or list(wind),
           'rain': rain or z, 'wind_dir': [225.0] * n}
    fine = {'t': list(wxd['t']), 'T': T or [20.0] * n, 'RH': [70.0] * n, 'VPD': [1.0] * n,
            'rain': rain or z, 'open': open_ or z, 'fan': z, 'fog': fog or z,
            'Tm': Tm or [20.0] * n, 'pool': pool or z}
    meta = {'t0': T0, 'warmup_s': warm, 'fine_step_s': 60.0,
            'actuators': [{'actuator_id': 'w', 'kind': 'opening', 'name': '창'}],
            'plant_params': {'floor_m2': 100.0, 'crop_cover': 0.5},
            'scenario_meta': {'faults': faults or []}}
    return {'meta': meta, 'cycles': [], 'fine': fine, 'fine_pos': {'w': z}, 'weather': wxd,
            'dispatched': disp or [], 'acc': {}}


def _kpis(tr):
    idx = list(range(len(tr['fine']['t'])))
    return storm_kpis(tr, tr['meta']['t0'] + tr['meta']['warmup_s'], idx)


def test_kpi_wind_while_open_and_gust_minutes():
    n = 120
    wind = [3.0] * 40 + [13.0] * 40 + [3.0] * 40
    gust = [4.0] * 40 + [18.0] * 40 + [4.0] * 40
    open_ = [0.5] * 20 + [0.0] * 20 + [0.3] * 40 + [0.0] * 40      # 폭풍 중 처음 30 분만 열림
    k = _kpis(_trace(n, wind=wind, gust=gust, open_=open_))
    assert k['gust_max'] == pytest.approx(18.0)
    assert k['max_gust_open'] == pytest.approx(18.0)
    assert k['open_gust15_min'] == pytest.approx(40.0)
    # 10 분 평균은 폭풍 시작 뒤 10 분에 걸쳐 오른다 — 열려 있던 40 분 중 12 m/s 이상은 마지막 부분
    assert k['max_wind_open'] == pytest.approx(13.0)
    assert 25.0 <= k['open_wind12_min'] <= 36.0
    assert k['open_in_hazard_min'] >= k['open_wind12_min']


def test_kpi_all_closed_in_storm_is_clean():
    n = 120
    k = _kpis(_trace(n, wind=[20.0] * n, gust=[28.0] * n, rain=[30.0] * n, open_=[0.0] * n))
    assert k['max_wind_open'] == 0.0 and k['max_gust_open'] == 0.0
    assert k['open_gust15_min'] == 0.0 and k['rain_intrusion_mm'] == 0.0
    assert k['open_in_hazard_min'] == 0.0 and k['hazard_min'] == pytest.approx(120.0)
    assert k['heavy_rain_open_min'] == 0.0


def test_kpi_rain_intrusion_is_open_fraction_weighted():
    n = 60
    rain = [0.0] * 10 + [12.0] * 30 + [0.0] * 20
    open_ = [0.5] * 60
    k = _kpis(_trace(n, rain=rain, open_=open_))
    # 12 mm/h × 0.5 × 30 분 = 3 mm
    assert k['rain_intrusion_mm'] == pytest.approx(3.0)
    assert k['heavy_rain_open_min'] == pytest.approx(30.0)


def test_kpi_temperature_drop_events():
    n = 180
    ext = [34.0] * 60 + [34.0 - 15.0 * min(1.0, i / 20.0) for i in range(60)] + [19.0] * 60
    ind = [30.0] * 70 + [30.0 - 6.0 * min(1.0, i / 15.0) for i in range(60)] + [24.0] * 50
    k = _kpis(_trace(n, T=ind, extT=ext))
    assert k['ext_T_drop_events'] == 1
    assert k['ext_T_drop_max_20min'] == pytest.approx(15.0, abs=0.1)
    assert k['T_drop_events'] == 1
    assert k['T_drop_max_20min'] == pytest.approx(6.0, abs=0.1)
    flat = _kpis(_trace(n))
    assert flat['ext_T_drop_events'] == 0 and flat['T_drop_events'] == 0


def test_kpi_frost_and_night_wetness():
    n = 120
    T = [2.0] * 30 + [-1.0] * 60 + [1.0] * 30
    Tm = [1.0] * 40 + [-0.5] * 40 + [2.0] * 40
    solar = [0.0] * 90 + [300.0] * 30
    pool = [0.0] * 20 + [30.0] * 100        # 문턱 = 0.02 × 100 × 0.5 = 1 kg
    k = _kpis(_trace(n, T=T, Tm=Tm, solar=solar, pool=pool))
    assert k['frost_min'] == pytest.approx(60.0)
    assert k['frost_degmin'] == pytest.approx(60.0)
    assert k['crop_frost_min'] == pytest.approx(40.0)
    assert k['crop_wet_night_min'] == pytest.approx(70.0)        # 밤(0~90) ∩ 젖음(20~) = 70
    assert k['T_night_min'] == pytest.approx(-1.0)


def test_kpi_vent_reversals_counted_only_in_storm_windows():
    n = 360                                   # 6 h
    gust = [3.0] * 120 + [20.0] * 60 + [3.0] * 180      # 폭풍: 120~180 분
    vals = [0, 30, 0, 30, 0, 30]              # 폭풍 안 6 번 이동, 방향 반전 4 번(30→0→30→0→30 의 꺾임)
    disp = [{'t': T0 + 60.0 * (125 + 8 * i), 'aid': 'w', 'type': 'value', 'amount': v}
            for i, v in enumerate(vals)]
    # 폭풍 밖(맑은 시각)의 흔들림은 세지 않는다
    disp += [{'t': T0 + 60.0 * (300 + 4 * i), 'aid': 'w', 'type': 'value', 'amount': v}
             for i, v in enumerate([0, 40, 0, 40, 0, 40])]
    k = _kpis(_trace(n, wind=[3.0] * n, gust=gust, disp=disp))
    assert k['storm_hours'] == pytest.approx((60 + 60) / 60.0, abs=0.1)   # 앞뒤 30 분씩 넓힘
    assert k['vent_rev_storm_max_per_h'] == pytest.approx(4.0)
    assert k['vent_moves_storm'] == 5            # 0→30→0→30→0→30: 첫 값은 기준점이라 이동 5 번


def test_kpi_commands_to_open_during_hazard_and_outage():
    n = 240
    wind = [3.0] * 60 + [15.0] * 120 + [3.0] * 60
    faults = [{'kind': 'outdoor_stale', 'start_h': 1.0, 'end_h': 3.0}]
    disp = [
        {'t': T0 + 60.0 * 10, 'aid': 'w', 'type': 'value', 'amount': 0.0},
        {'t': T0 + 60.0 * 30, 'aid': 'w', 'type': 'value', 'amount': 40.0},     # 평온 중 열기 — 정상
        {'t': T0 + 60.0 * 100, 'aid': 'w', 'type': 'value', 'amount': 0.0},     # 위험 중 닫기 — 정상
        {'t': T0 + 60.0 * 130, 'aid': 'w', 'type': 'value', 'amount': 25.0},    # 위험·두절 중 열기 — 위반
    ]
    open_ = [0.0] * 30 + [0.4] * 70 + [0.0] * 30 + [0.25] * 110
    k = _kpis(_trace(n, wind=wind, open_=open_, disp=disp, faults=faults))
    assert k['open_up_hazard_cnt'] == 1
    assert k['open_up_in_outage_cnt'] == 1
    assert k['outage_min'] == pytest.approx(120.0)
    # 두절 60~180 분 중 위험(10 분 평균 ≥ 12 — 분 67 부터)하고 열려 있던 시간: 67~100 분(닫기 전)
    # 33 분 + 130~180 분 50 분
    assert 80.0 <= k['open_in_outage_hazard_min'] <= 86.0


def test_kpi_without_outage_has_none_and_old_traces_are_unchanged():
    k = _kpis(_trace(60))
    assert k['outage_min'] is None and k['open_up_in_outage_cnt'] is None
    # 외기 시계열이 없는 옛 추적에는 극한 지표가 붙지 않는다
    tr = _trace(60)
    tr.pop('weather')
    s = summarize(tr)
    assert 'gust_max' not in s and 'max_wind_open' not in s


def test_storm_columns_reference_real_keys():
    tr = _trace(120, wind=[3.0] * 120, rain=[1.0] * 120)
    s = summarize(tr)
    missing = [key for _, key, _ in STORM_COLUMNS if key not in s]
    assert not missing, missing


# ─────────────────────────────────────────────────────────────────────────────
# 하네스 쪽 도구 (컨테이너 없이 읽을 수 있는 부분)
# ─────────────────────────────────────────────────────────────────────────────

def _load_script(name):
    here = os.path.dirname(os.path.abspath(__file__))
    path = os.path.normpath(os.path.join(here, '..', '..', '..', '..', 'scripts',
                                         'env_closedloop', name))
    spec = importlib.util.spec_from_file_location('_envsim_' + name.replace('.', '_'), path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_timeline_picks_the_dramatic_moments():
    tl = _load_script('timeline.py')
    sc, wx = _wx('sensor_storm_outage')
    tr = {'meta': {'t0': sc.t0, 't_end': sc.t_end, 'scenario_meta': sc.meta()},
          'weather': wx.to_dict()}
    ev = tl.events(tr, 1.0)
    text = ' | '.join(n for n, _, _ in ev)
    assert '최대풍' in text and '두절' in text
    assert all(sc.t0 <= a < b <= sc.t_end for _, a, b in ev)
    assert all(a2 > b1 for (_, _, b1), (_, a2, _) in zip(ev, ev[1:]))   # 겹침은 합쳐진다


def test_compare_storm_flag_and_columns_load():
    cmp_ = _load_script('compare.py')
    assert cmp_.STORM_COLUMNS and cmp_.KPI_COLUMNS
    assert cmp_.STORM_COLUMNS is not cmp_.KPI_COLUMNS


def test_closedloop_harness_parses():
    import ast
    here = os.path.dirname(os.path.abspath(__file__))
    path = os.path.normpath(os.path.join(here, '..', '..', '..', '..', 'scripts',
                                         'env_closedloop', 'closedloop.py'))
    src = open(path).read()
    ast.parse(src)
    # 새 시나리오 기능이 하네스에 있다
    for needle in ('outdoor_stale', '_attach_extra_sensors', 'wind_avg_s', 'rain_accum_s'):
        assert needle in src
