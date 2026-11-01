# coding=utf-8
"""L0 예보 발표본 저장 (`fc_hourly`·`fc_daily`) — 예보·트윈 데이터 관리 D2.

지키는 계약
1. 발표 시각은 태그가 아니다 — 대상 시각 − 리드 로 복원되고, 발표가 쌓여도 계열 수가 고정이다.
2. 값은 제공자 행 그대로다. 없으면 쓰지 않는다(0 으로 채우지 않는다).
3. 시간별 발표 기준은 받은 시각을 내린 정시, 일별은 받은 시각의 현지 날짜다.
4. 저장이 실패해도 입력의 채널 값·시간열 파일은 그대로 나온다. 꺼 두면(`off`) Influx 를 건드리지 않는다.
5. 파일 사본에는 `issued_epoch`·`l0_ref` 가 붙는다(L0 에 같은 발표본이 있을 때만).

Influx·네트워크·DB 없음 — 쓰기와 읽기는 대역으로 잡는다.
"""
import json
import math
from datetime import date, datetime, timezone
from types import SimpleNamespace
from unittest import mock

import pytest

import aot.inputs.open_meteo_daily_forecast as df
import aot.inputs.open_meteo_hourly_forecast as hf
import aot.inputs.open_meteo_weather as live
from aot.utils import fc_store as F

H = 3600
T0 = int(datetime(2026, 10, 13, 5, 0, tzinfo=timezone.utc).timestamp())
IN_UUID = '5f0c2a8e-3b1d-4c7a-9e2f-6a4b8d1c0e93'


def _series(base=T0, hours=50, **fn):
    return {var: {base + o * H: f(o) for o in range(hours)} for var, f in fn.items()}


class TestHourlyPoints:
    def test_one_point_per_var_and_lead_with_tags_and_target_time(self):
        s = _series(T=lambda o: 10.0 + o, RAIN=lambda o: float(o))
        pts = F.hourly_points(IN_UUID, T0 + 30 * 60, s)
        assert len(pts) == 2 * 49
        p = next(p for p in pts if p.tags == {'var': 'T', 'lead_h': '3'})
        assert p.measurement == 'fc_hourly' and p.device_id == IN_UUID and p.channel is None
        assert p.timestamp == T0 + 3 * H and p.value == 13.0       # 대상 시각 = 발표 정시 + 리드

    def test_issue_is_floored_to_the_hour(self):
        a = F.hourly_points(IN_UUID, T0 + 5, _series(T=lambda o: 1.0))
        b = F.hourly_points(IN_UUID, T0 + 59 * 60, _series(T=lambda o: 2.0))
        # 같은 발표 정시 → 같은 (시각, 태그) 계열: 나중 것이 덮어쓴다(발표 정시 하나에 점 하나).
        assert {(p.timestamp, tuple(sorted(p.tags.items()))) for p in a} == \
               {(p.timestamp, tuple(sorted(p.tags.items()))) for p in b}

    def test_values_are_verbatim_and_missing_is_skipped_never_zero(self):
        s = {'T': {T0: 0.0, T0 + H: float('nan'), T0 + 2 * H: None, T0 + 3 * H: True, T0 + 4 * H: -3.5},
             'RH': {}}
        pts = F.hourly_points(IN_UUID, T0, s, leads=range(0, 6))
        got = {p.tags['lead_h']: p.value for p in pts}
        assert got == {'0': 0.0, '4': -3.5}          # 0.0 은 값이다. NaN·None·bool 은 버린다
        assert all(math.isfinite(p.value) for p in pts)

    def test_unknown_var_and_missing_device_write_nothing(self):
        assert F.hourly_points(IN_UUID, T0, {'WMO': {T0: 1.0}}) == []
        assert F.hourly_points(None, T0, _series(T=lambda o: 1.0)) == []

    def test_thin_leads(self):
        assert F.HOURLY_LEADS_THIN[:25] == tuple(range(25))
        assert F.HOURLY_LEADS_THIN[25:] == (27, 30, 33, 36, 39, 42, 45, 48)
        pts = F.hourly_points(IN_UUID, T0, _series(T=lambda o: 1.0), F.HOURLY_LEADS_THIN)
        assert len(pts) == 33

    def test_series_count_is_fixed_no_matter_how_many_issues(self):
        keys = set()
        for k in range(10):                      # 열 번의 발표
            for p in F.hourly_points(IN_UUID, T0 + k * H, _series(base=T0 + k * H, T=lambda o: 1.0)):
                keys.add((p.measurement, p.device_id, tuple(sorted(p.tags.items()))))
        assert len(keys) == 49                   # 변수 1 × 리드 49 (발표 수와 무관)

    def test_meta_is_stamped_at_the_receive_time(self):
        m = F.hourly_meta_points(IN_UUID, T0 + 1234, 392, lat=35.86, lon=126.88, elev=12.0, model='icc')
        assert {p.channel: p.value for p in m} == {0: 392.0, 1: 35.86, 2: 126.88, 3: 12.0, 4: float(T0)}
        assert all(p.timestamp == T0 + 1234 and p.tags == {'model': 'icc'} for p in m)
        # 값이 없는 칸(고도 없음)은 쓰지 않는다
        assert 3 not in {p.channel for p in F.hourly_meta_points(IN_UUID, T0, 1)}


class TestDailyPoints:
    KST = 9 * H

    def test_timestamp_is_target_local_date_at_utc_midnight(self):
        # 2026-10-21 16:00 UTC = KST 10-22 01:00 → 발표일 10-22
        now = datetime(2026, 10, 21, 16, 0, tzinfo=timezone.utc).timestamp()
        pts = F.daily_points(IN_UUID, now, self.KST, {('RAIN', 0): 2.0, ('TMAX', 3): 18.5})
        by = {(p.tags['var'], p.tags['lead_d']): p for p in pts}
        assert by[('RAIN', '0')].timestamp == datetime(2026, 10, 22, tzinfo=timezone.utc).timestamp()
        assert by[('TMAX', '3')].timestamp == datetime(2026, 10, 25, tzinfo=timezone.utc).timestamp()
        assert by[('TMAX', '3')].value == 18.5 and by[('RAIN', '0')].measurement == 'fc_daily'

    def test_invalid_var_lead_value_are_dropped(self):
        pts = F.daily_points(IN_UUID, T0, 0, {('BAD', 0): 1.0, ('RAIN', 9): 1.0, ('RAIN', 1): float('nan'),
                                              ('ET0', 2): 0.0})
        assert [(p.tags['var'], p.tags['lead_d'], p.value) for p in pts] == [('ET0', '2', 0.0)]

    def test_local_day_crosses_midnight_with_offset(self):
        now = datetime(2026, 10, 21, 16, 0, tzinfo=timezone.utc).timestamp()
        assert F.local_day(now, self.KST) == date(2026, 10, 22)
        assert F.local_day(now, 0) == date(2026, 10, 21)


class TestStore:
    def test_writes_points_plus_meta_in_one_batch(self):
        with mock.patch('aot.utils.influx.write_influxdb_points', return_value=99) as w:
            n = F.store_hourly(IN_UUID, T0, _series(T=lambda o: 1.0), model='best_match')
        assert n == 99
        pts = w.call_args[0][0]
        assert sum(p.measurement == 'fc_hourly' for p in pts) == 49
        assert sum(p.measurement == 'fc_hourly_meta' for p in pts) == 2      # 점 수·기준 정시 (격자 없음)
        n_meta = next(p.value for p in pts if p.measurement == 'fc_hourly_meta' and p.channel == 0)
        assert n_meta == 49.0

    def test_nothing_to_write_touches_nothing(self):
        with mock.patch('aot.utils.influx.write_influxdb_points') as w:
            assert F.store_hourly(IN_UUID, T0, {}) == 0
            assert F.store_daily(IN_UUID, T0, 0, {}) == 0
        w.assert_not_called()

    def test_failures_propagate_to_the_caller(self):
        with mock.patch('aot.utils.influx.write_influxdb_points', side_effect=RuntimeError('down')):
            with pytest.raises(RuntimeError):
                F.store_daily(IN_UUID, T0, 0, {('RAIN', 0): 1.0})


class TestReadIssue:
    def test_picks_only_points_whose_target_minus_lead_is_the_issue(self):
        rows = [(T0 + 2 * H, 12.0, {'var': 'T', 'lead_h': '2'}),        # 이 발표
                (T0 + 2 * H, 99.0, {'var': 'T', 'lead_h': '1'}),        # 한 시간 뒤 발표의 리드 1
                (T0 + 5 * H, 15.0, {'var': 'T', 'lead_h': '5'}),
                (T0 + 3 * H, 1.0, {'var': 'T', 'lead_h': 'x'})]         # 망가진 태그는 건너뛴다
        with mock.patch('aot.utils.influx.read_layer_points', return_value=rows):
            got = F.read_hourly_issue(IN_UUID, T0 + 600, vars_=['T'])
        assert got == {'T': {2: 12.0, 5: 15.0}}

    def test_daily_issue(self):
        base = datetime(2026, 10, 22, tzinfo=timezone.utc).timestamp()
        rows = [(base + 86400, 3.0, {'var': 'RAIN', 'lead_d': '1'}),
                (base + 86400, 8.0, {'var': 'RAIN', 'lead_d': '0'})]    # 전날 발표의 리드 0 아님 → 제외
        with mock.patch('aot.utils.influx.read_layer_points', return_value=rows):
            got = F.read_daily_issue(IN_UUID, date(2026, 10, 22))
        assert got['RAIN'] == {1: 3.0}

    def test_leads_helper_drops_tags(self):
        with mock.patch('aot.utils.influx.read_layer_points',
                        return_value=[(10.0, 1.5, {}), (20.0, 2.5, {})]) as r:
            assert F.read_hourly_leads(IN_UUID, 'T', 0, 100, 24) == [(10.0, 1.5), (20.0, 2.5)]
        assert r.call_args[0][2] == {'var': 'T', 'lead_h': '24'}


# ── 드라이버 ────────────────────────────────────────────────────────────────

class _Resp:
    def __init__(self, status, payload):
        self.status_code, self._p, self.headers = status, payload, {}

    def json(self):
        return self._p

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)


def _hourly_payload():
    times = [T0 + o * H for o in range(-1, 50)]
    return {'latitude': 35.86, 'longitude': 126.88, 'elevation': 12.0,
            'hourly': {'time': times,
                       'temperature_2m': [10.0 + i for i in range(len(times))],
                       'relative_humidity_2m': [50.0] * len(times),
                       'precipitation': [0.0] * len(times),
                       'wind_speed_10m': [2.0] * len(times),
                       'wind_direction_10m': [200.0] * len(times),
                       'weather_code': [2] * len(times),
                       'precipitation_probability': [10.0] * len(times),
                       'cloud_cover': [5.0] * len(times),
                       'shortwave_radiation': [100.0] * len(times)}}


@pytest.fixture
def hourly(monkeypatch, tmp_path):
    import aot.config as cfg
    monkeypatch.setattr(cfg, 'DATABASE_PATH', str(tmp_path))
    monkeypatch.setattr(hf, '_now', lambda: T0 + 30 * 60)
    monkeypatch.setattr(hf.requests, 'get', lambda url, params=None, timeout=None: _Resp(200, _hourly_payload()))
    live._RATE_LIMITED_UNTIL.clear()

    def make(**attrs):
        m = hf.InputModule(SimpleNamespace(unique_id=IN_UUID, latitude=35.86, longitude=126.88), testing=True)
        m.unique_id, m.latitude, m.longitude = IN_UUID, 35.86, 126.88
        m.is_enabled = lambda ch: ch in set(range(28))
        for k, v in attrs.items():
            setattr(m, k, v)
        return m
    make.path = tmp_path / 'openmeteo' / ('forecast_%s.json' % IN_UUID)
    yield make
    live._RATE_LIMITED_UNTIL.clear()


class TestHourlyDriver:
    def test_default_testing_instance_never_touches_influx(self, hourly):
        with mock.patch('aot.utils.fc_store.store_hourly') as s:
            hourly().get_measurement()
        s.assert_not_called()

    def test_full_stores_neutral_variables_and_marks_the_file_copy(self, hourly):
        with mock.patch('aot.utils.fc_store.store_hourly', return_value=392) as s:
            out = hourly(l0_leads='full').get_measurement()
        assert out is not None
        dev, fetched, series = s.call_args[0][:3]
        assert dev == IN_UUID and fetched == T0 + 30 * 60
        assert set(series) == {'T', 'RH', 'WS', 'WD', 'RAIN', 'SOL', 'CLD', 'POP'}     # WMO 코드는 L0 가 아니다
        assert series['T'][T0 + 3 * H] == 10.0 + 4             # 제공자 행 그대로(past 1h 행이 첫 칸)
        assert s.call_args[0][3] == F.HOURLY_LEADS_FULL
        assert s.call_args[1]['lat'] == 35.86 and s.call_args[1]['model'] == 'best_match'
        meta = json.loads(hourly.path.read_text())
        assert meta['issued_epoch'] == T0 and meta['l0_ref'] == 'fc_hourly'

    def test_thin_option(self, hourly):
        with mock.patch('aot.utils.fc_store.store_hourly', return_value=1) as s:
            hourly(l0_leads='thin').get_measurement()
        assert s.call_args[0][3] == F.HOURLY_LEADS_THIN

    def test_store_failure_keeps_channels_and_file_without_the_l0_marks(self, hourly):
        with mock.patch('aot.utils.fc_store.store_hourly', side_effect=RuntimeError('influx down')):
            out = hourly(l0_leads='full').get_measurement()
        assert out is not None and out[0]['value'] is not None
        meta = json.loads(hourly.path.read_text())
        assert 'issued_epoch' not in meta and 'l0_ref' not in meta
        assert meta['forecasts']['0']['TMP'] == 11.0

    def test_off_does_not_mark_the_file(self, hourly):
        hourly(l0_leads='off').get_measurement()
        assert 'l0_ref' not in json.loads(hourly.path.read_text())

    def test_option_is_declared_with_the_user_facing_default(self):
        opt = next(o for o in hf.INPUT_INFORMATION['custom_options'] if o['id'] == 'l0_leads')
        assert opt['default_value'] == 'full'
        assert {v for v, _ in opt['options_select']} == {'full', 'thin', 'off'}
        # 필수로 두면 이 옵션이 없던 기존 입력이 시작할 때마다 ERROR 로그를 남긴다(기본값은 어차피 적용된다).
        assert opt['required'] is False


NOW_D = datetime(2026, 10, 21, 16, 0, tzinfo=timezone.utc).timestamp()      # KST 10-22 01:00


def _daily_module(monkeypatch, **attrs):
    mod = df.InputModule.__new__(df.InputModule)
    mod.logger = SimpleNamespace(error=lambda *a, **k: None, debug=lambda *a, **k: None,
                                 warning=lambda *a, **k: None)
    mod.unique_id = IN_UUID
    mod.latitude, mod.longitude, mod.api_key, mod.model = 35.8, 127.1, None, 'best_match'
    mod.is_enabled = lambda ch: True
    mod.value_set = lambda ch, v: None
    for k, v in attrs.items():
        setattr(mod, k, v)
    payload = {'latitude': 35.8, 'longitude': 127.1, 'elevation': 30.0, 'utc_offset_seconds': 9 * H,
               'daily': {'time': ['2026-10-%02d' % d for d in range(22, 30)],
                         'precipitation_sum': [1.0 + i for i in range(8)],
                         'temperature_2m_max': [20.0] * 8}}
    monkeypatch.setattr(df, '_now', lambda: NOW_D)
    monkeypatch.setattr(df.requests, 'get', lambda url, params=None, timeout=None: _Resp(200, payload))
    live._RATE_LIMITED_UNTIL.clear()
    return mod


class TestDailyDriver:
    def test_not_set_means_off_and_never_touches_influx(self, monkeypatch):
        with mock.patch('aot.utils.fc_store.store_daily') as s:
            assert _daily_module(monkeypatch).get_measurement() is not None
        s.assert_not_called()

    def test_store_maps_channels_to_var_and_lead(self, monkeypatch):
        with mock.patch('aot.utils.fc_store.store_daily', return_value=16) as s:
            _daily_module(monkeypatch, store_issue=True).get_measurement()
        dev, fetched, offset, vals = s.call_args[0][:4]
        assert dev == IN_UUID and fetched == NOW_D and offset == 9 * H
        assert vals[('RAIN', 0)] == 1.0 and vals[('RAIN', 7)] == 8.0
        assert vals[('TMAX', 3)] == 20.0
        assert s.call_args[1]['elev'] == 30.0

    def test_store_failure_does_not_block_channels(self, monkeypatch):
        with mock.patch('aot.utils.fc_store.store_daily', side_effect=RuntimeError('down')):
            assert _daily_module(monkeypatch, store_issue=True).get_measurement() is not None

    def test_option_default_is_on(self):
        opt = next(o for o in df.INPUT_INFORMATION['custom_options'] if o['id'] == 'store_issue')
        assert opt['default_value'] is True


class TestWritePointsWithoutChannel:
    def test_channel_none_writes_no_channel_tag(self):
        from aot.tests.test_influx_layers import LEGACY, _FakeClient, _with_layout
        from aot.utils import influx as I
        c = _FakeClient()
        with mock.patch.object(I, '_influx_connection_params', return_value=('http://x', 't', 'aot_db', '2')), \
                mock.patch.object(I, 'InfluxDBClient', return_value=c), _with_layout(LEGACY):
            I.write_influxdb_points(F.hourly_points(IN_UUID, T0, _series(T=lambda o: 1.0), (0,)))
        line = c.writes['aot_db'][0].to_line_protocol()
        assert 'channel=' not in line and 'var=T' in line and 'lead_h=0' in line


class TestReadLayerPoints:
    def test_tags_are_returned_internal_keys_are_not_and_new_bucket_wins(self):
        from aot.tests.test_influx_layers import LAYERED, _FakeClient, _Rec, _with_layout
        from aot.utils import influx as I
        base = dict(device_id='d', var='T', lead_h='3', result='_result', table=0, _field='value')
        c = _FakeClient(data={
            'aot_fc': [_Rec(100, 2.0, **base)],
            'aot_db': [_Rec(100, 9.0, **base), _Rec(50, 1.0, **base)]})
        with mock.patch.object(I, '_influx_connection_params', return_value=('http://x', 't', 'aot_db', '2')), \
                mock.patch.object(I, 'InfluxDBClient', return_value=c), _with_layout(LAYERED):
            rows = I.read_layer_points('fc_hourly', 'd', {'var': 'T'}, 0, 200)
        assert rows == [(50.0, 1.0, {'var': 'T', 'lead_h': '3'}), (100.0, 2.0, {'var': 'T', 'lead_h': '3'})]
        assert c.queries == ['aot_fc', 'aot_db']
