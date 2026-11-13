# coding=utf-8
"""`weather.now` 의 지난 구간 — 2026-10-31 사용자 질문("어제 날씨·이번 주 날씨를 AI 가 조회할 수 있나")에서 나온 것.

고정하는 계약:
  1. period 는 끝까지 지킨다(`range` 모양). 끝난 구간의 마지막 값은 latest 가 아니라 last 다.
  2. 시간별 예보 입력은 측정마다 리드가 가장 짧은 채널 하나를 **대상 시각**으로 읽고, 예보값임을 밝힌다.
  3. 구름량·일사량이 들어오고, 강수량은 칸마다 한 값으로 기간 합을 낸다(그대로 더하면 곱절이 된다).
  4. 카드 제목이 조회 기간과 일치한다.
  5. 네 가지 질문의 호출을 고정한다.
  6. 도메인 표면 밖(인앱 AI·개요)의 `get_weather` 응답은 바뀌지 않는다.

강수·시각 예시는 8084 실측(10-29~30 김제 Open-Meteo Forecast)을 줄인 것이다. DB·Influx 없이 경계를 패치한다.
"""
import unittest
from datetime import date, datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

# 도구 서비스를 먼저 불러야 data_tools 믹스인의 순환 import 가 풀린다.
from aot.tools.aot_data_tool_service import AoTDataToolService as S
from aot.tools.data_tools import weather_summary as ws
from aot.tools.domain import server_card, vocab
from aot.tools.domain.registry_data import OPS

KST = timezone(timedelta(hours=9))
NOW = datetime(2026, 10, 31, 13, 57, tzinfo=KST)
DRIVER = 'OPEN_METEO_HOURLY_FORECAST'
#: 드라이버 채널 메타와 같은 뜻 — 채널 번호: (리드, 칸 종류).
LEADS = {0: (1, 'instant'), 2: (1, 'cell'), 3: (1, 'cell'), 5: (1, 'cell'), 6: (1, 'cell'),
         7: (3, 'instant'), 9: (3, 'cell'), 14: (6, 'instant'), 16: (6, 'cell')}


def _at(day, hour, minute=0):
    return datetime(2026, 10, day, hour, minute, tzinfo=KST).timestamp()


class LeadPoints(unittest.TestCase):

    def test_an_instant_value_moves_to_the_time_it_was_forecast_for(self):
        got = ws.lead_points([(_at(30, 12), 19.2)], 1, 'instant', _at(30, 0), _at(31, 0))
        self.assertEqual([(_at(30, 13), 19.2)], got)

    def test_all_leads_of_one_peak_land_on_the_same_time(self):
        """실측 — 어제 최고가 +1h 12:00·+3h 09:00·+6h 06:00 에 찍혀 있었다. 모두 12~13시를 가리킨다."""
        for lead, hour in ((1, 12), (3, 10), (6, 7)):
            got = ws.lead_points([(_at(30, hour), 19.4)], lead, 'instant', _at(30, 0), _at(31, 0))
            self.assertEqual(_at(30, 13), got[0][0])

    def test_samples_of_one_cell_count_once_and_the_later_issue_wins(self):
        got = ws.lead_points([(_at(29, 22, 10), 0.5), (_at(29, 22, 40), 0.6)], 1, 'cell', _at(29, 0), _at(31, 0))
        self.assertEqual([(_at(30, 0), 0.6)], got)      # 두 번 받은 칸(끝 00:00) 하나

    def test_real_rain_is_not_doubled(self):
        """10-29~30: 30분마다 받아 같은 칸이 두 번씩 있다 — 그대로 더하면 1.2 mm, 칸으로 세면 발표본 L0 와 같은 0.6 mm."""
        raw = [(_at(29, 22, 10), 0.6), (_at(29, 22, 40), 0.6), (_at(29, 21, 10), 0.0), (_at(29, 21, 40), 0.0)]
        self.assertAlmostEqual(1.2, sum(v for _t, v in raw))
        got = ws.lead_points(raw, 1, 'cell', _at(29, 0), _at(31, 0))
        self.assertAlmostEqual(0.6, sum(v for _t, v in got))

    def test_a_cell_belongs_to_the_period_it_ends_in(self):
        start, end = _at(30, 0), _at(31, 0)
        self.assertEqual([], ws.lead_points([(_at(29, 22, 40), 0.6)], 1, 'cell', _at(30, 1), end))
        self.assertEqual([], ws.lead_points([(_at(30, 23, 40), 0.6)], 1, 'cell', start, end))  # 끝 01:00 — 다음 날
        self.assertEqual([(_at(31, 0), 0.1)], ws.lead_points([(_at(30, 22, 40), 0.1)], 1, 'cell', start, end))

    def test_a_cell_still_open_at_the_end_is_left_out(self):
        got = ws.lead_points([(_at(31, 12, 50), 0.4)], 1, 'cell', _at(31, 0), NOW.timestamp())
        self.assertEqual([], got)                       # 14:00 에 끝나는 칸은 아직 끝나지 않았다


class RainTotals(unittest.TestCase):

    def test_overlapping_readings_count_once_per_interval(self):
        """5분마다 받은 1시간 합(12번) — 7.2 가 아니라 0.6(10-29~30 Open-Meteo 지금 칸 실측)."""
        pts = [(_at(30, 0, 5 * i), 0.6) for i in range(1, 12)] + [(_at(30, 1), 0.6)]
        self.assertAlmostEqual(7.2, sum(v for _t, v in pts))
        self.assertEqual((0.6, 1), ws.cell_total(pts, 3600))

    def test_a_15_minute_sum_read_every_5_minutes(self):
        pts = [(_at(30, 12, 5), 0.4), (_at(30, 12, 10), 0.4), (_at(30, 12, 15), 0.4), (_at(30, 12, 20), 0.1)]
        self.assertEqual((0.5, 2), ws.cell_total(pts, 900))

    def test_only_rain_amounts_are_summed(self):
        self.assertTrue(ws.is_rain_amount('rain', 'mm'))
        self.assertTrue(ws.is_rain_amount('precipitation', 'mm'))
        self.assertFalse(ws.is_rain_amount('precipitation', 'percent'))     # 강수 확률
        self.assertFalse(ws.is_rain_amount('precipitation', 'none'))        # 감우기
        self.assertFalse(ws.is_rain_amount('temperature', 'C'))

    def test_interval_comes_from_the_driver_then_the_channel_name(self):
        from aot.utils.inputs import rain_accum_seconds as secs
        self.assertEqual(900, secs('mm', 'precipitation', '15-min Precipitation', 'KMA_weather_500'))
        self.assertEqual(3600, secs('mm', 'rain', '', DRIVER))
        self.assertEqual(1800, secs('mm', 'rain', 'rain 30 min', 'other'))
        self.assertIsNone(secs('mm_h', 'precipitation', 'Rainfall Hourly', 'sensecap_weather'))     # 강우율
        self.assertIsNone(secs('mm', 'precipitation', 'Rain Accumulation', 'sensecap_weather'))     # 누적 계기


def _row(name, unit, channel='', **extra):
    read = [{'t': '2026-10-30T%02d:00:00+09:00' % h, 'v': float(h), 'u': unit} for h in (6, 13)]
    stats = {'min': 6.0, 'max': 13.0, 'avg': 9.5, 'count': 2, 'min_at': read[0]['t'], 'max_at': read[1]['t']}
    stats.update(extra.pop('stats', {}))
    return dict({'measurement': name, 'channel': channel, 'readings': read, 'stats': stats}, **extra)


class SummaryLines(unittest.TestCase):

    def test_an_ended_period_says_last_not_latest(self):
        out = ws.summarize_observed({'period_ended': True, 'data': [_row('temperature', 'C')]})
        line = out['summary'][0]
        self.assertEqual((13.0, '10-30 13:00'), (line['last'], line['last_at']))
        self.assertNotIn('latest', line)

    def test_a_period_running_to_now_keeps_latest(self):
        line = ws.summarize_observed({'data': [_row('temperature', 'C')]})['summary'][0]
        self.assertIn('latest', line)
        self.assertNotIn('last', line)

    def test_forecast_lines_name_their_channel(self):
        out = ws.summarize_observed({'data': [_row('temperature', 'C', 'Temperature +1h', lead_h=1)]})
        self.assertEqual('Temperature +1h', out['summary'][0]['channel'])

    def test_a_repeated_measurement_names_its_channel_and_a_single_one_does_not_grow(self):
        rows = [_row('temperature', 'C', 'Outdoor'), _row('temperature', 'C', 'Indoor'), _row('humidity', 'percent', 'RH')]
        got = ws.summarize_observed({'data': rows})['summary']
        self.assertEqual(['Outdoor', 'Indoor', None], [r.get('channel') for r in got])

    def test_rain_carries_its_total_and_any_gap(self):
        row = _row('rain', 'mm', 'Rain (1h sum) +1h', lead_h=1, stats={'sum': 0.6, 'missing_hours': 2})
        line = ws.summarize_observed({'data': [row]})['summary'][0]
        self.assertEqual((0.6, 2), (line['sum'], line['missing_hours']))

    def test_cloud_and_solar_words_find_their_channels(self):
        rows = [_row('sky_condition', 'percent', 'Cloud Cover +1h', lead_h=1), _row('light', 'W_m2', 'Solar +1h', lead_h=1),
                _row('temperature', 'C', 'Temperature +1h', lead_h=1)]
        out = ws.summarize_observed({'data': rows}, ws.field_tokens('cloud, solar'))
        self.assertEqual(['sky_condition', 'light'], [r['measurement'] for r in out['summary']])

    def test_cloud_word_finds_a_station_channel_without_a_name(self):
        out = ws.summarize_observed({'data': [_row('sky_condition', 'percent')]}, ws.field_tokens('cloud'))
        self.assertEqual(1, len(out['summary']))


def _channel(ch, measurement, unit, name):
    m = MagicMock()
    m.channel, m.measurement, m.unit, m.name, m.conversion_id = ch, measurement, unit, name, None
    return m


_CHANNELS = [_channel(0, 'temperature', 'C', 'Temperature +1h'), _channel(2, 'rain', 'mm', 'Rain (1h sum) +1h'),
             _channel(7, 'temperature', 'C', 'Temperature +3h'), _channel(9, 'rain', 'mm', 'Rain (1h sum) +3h'),
             _channel(21, 'temperature', 'C', 'Window Max Temperature')]


def _dev():
    d = MagicMock()
    d.unique_id, d.name, d.device = 'dev-1', 'Open-Meteo Forecast 김제', DRIVER
    d.period, d.max_age_s = 1800, None
    return d


class _Reader:
    """`read_influxdb_list` 대역 — {채널: [(현지 datetime, 값)]} 를 요청 구간으로 자른다."""

    def __init__(self, series):
        self.series, self.calls = series, []

    def __call__(self, unique_id, unit, channel, measure=None, start_str=None, end_str=None, datetime_obj=False):
        self.calls.append((channel, start_str, end_str))
        fmt = '%Y-%m-%dT%H:%M:%S.%fZ'
        lo = datetime.strptime(start_str, fmt).replace(tzinfo=timezone.utc)
        hi = datetime.strptime(end_str, fmt).replace(tzinfo=timezone.utc)
        return [(t, v) for t, v in self.series.get(channel, []) if lo <= t <= hi]


def _dt(day, hour, minute=0):
    return datetime(2026, 10, day, hour, minute, tzinfo=KST)


class _Env:
    """`_weather_lead_read` 의 경계."""

    def __init__(self, series, channels=_CHANNELS):
        self.reader = _Reader(series)
        query = MagicMock()
        query.query.filter.return_value.all.return_value = channels
        self.ps = [
            patch('aot.tools.data_tools.measurement.DeviceMeasurements', query),
            patch('aot.tools.data_tools.measurement.read_influxdb_list', self.reader),
            patch('aot.tools.data_tools.measurement.return_measurement_info',
                  side_effect=lambda m, c: (m.channel, m.unit, m.measurement)),
            patch('aot.tools.data_tools.measurement.utc_now', return_value=NOW),
            patch('aot.utils.timekit.tz_of', return_value=KST),
            patch('aot.utils.timekit.iso_at',
                  side_effect=lambda v, _i, cache=None: datetime.fromtimestamp(v, KST).isoformat()),
            patch('aot.tools.data_tools.measurement.iso_at',
                  side_effect=lambda v, _i, cache=None: datetime.fromtimestamp(v, KST).isoformat()),
        ]

    def __enter__(self):
        for p in self.ps:
            p.start()
        return self

    def __exit__(self, *exc):
        for p in self.ps:
            p.stop()


class LeadRead(unittest.TestCase):

    def test_one_channel_per_measurement_the_shortest_lead(self):
        series = {0: [(_dt(30, 12), 19.2)], 7: [(_dt(30, 10), 19.4)], 2: [(_dt(30, 12, 10), 0.0)],
                  9: [(_dt(30, 10, 10), 0.0)], 21: [(_dt(30, 12), 19.4)]}
        with _Env(series):
            rows = S._weather_lead_read(_dev(), '2026-10-30/2026-10-30', LEADS, 'zone-1')
        self.assertEqual(['Temperature +1h', 'Rain (1h sum) +1h'], [r['channel'] for r in rows])
        self.assertEqual('2026-10-30T13:00:00+09:00', rows[0]['stats']['max_at'])
        self.assertEqual({'from': '2026-10-30T00:00+09:00', 'to': '2026-10-31T00:00+09:00'}, rows[0]['period'])

    def test_it_reads_earlier_by_the_lead_so_the_day_is_complete(self):
        with _Env({0: [(_dt(29, 23, 30), 9.0), (_dt(30, 22, 50), 10.0), (_dt(30, 23, 30), 99.0)]}) as env:
            rows = S._weather_lead_read(_dev(), '2026-10-30/2026-10-30', LEADS, 'zone-1')
        first = next(c for c in env.reader.calls if c[0] == 0)
        self.assertEqual('2026-10-29T14:00:00.000000Z', first[1])       # 10-29 23:00 KST
        self.assertEqual([9.0, 10.0], sorted(r['v'] for r in rows[0]['readings']))     # 23:30+1h 는 다음 날

    def test_an_open_end_stops_at_now(self):
        with _Env({0: [(_dt(31, 12, 55), 17.0), (_dt(31, 13, 41), 17.2)]}):
            rows = S._weather_lead_read(_dev(), '2026-10-31/', LEADS, 'zone-1')
        self.assertEqual([17.0], [r['v'] for r in rows[0]['readings']])     # 13:41+1h 는 아직 오지 않았다

    def test_a_silent_channel_falls_to_the_next_lead(self):
        with _Env({7: [(_dt(30, 9), 18.0)]}):
            rows = S._weather_lead_read(_dev(), '2026-10-30/2026-10-30', LEADS, 'zone-1')
        self.assertEqual(('Temperature +3h', 3), (rows[0]['channel'], rows[0]['lead_h']))

    def test_rain_total_counts_cells_and_reports_gaps(self):
        series = {2: [(_dt(29, 22, 10), 0.6), (_dt(29, 22, 40), 0.6), (_dt(29, 23, 10), 0.0)]}
        with _Env(series):
            rows = S._weather_lead_read(_dev(), '2026-10-30T00:00/2026-10-30T03:00', LEADS, 'zone-1')
        self.assertEqual(0.0, rows[0]['stats']['sum'])
        with _Env(series):
            rows = S._weather_lead_read(_dev(), '2026-10-29T23:00/2026-10-30T03:00', LEADS, 'zone-1')
        self.assertEqual((0.6, 2), (rows[0]['stats']['sum'], rows[0]['stats']['missing_hours']))

    def test_no_values_say_so(self):
        with _Env({}):
            out = S._weather_lead_read(_dev(), '2026-10-30/2026-10-30', LEADS, 'zone-1')
        self.assertIn('No data', out['message'])
        self.assertEqual('2026-10-30T00:00+09:00', out['period']['from'])

    def test_a_period_still_ahead_reads_nothing(self):
        with _Env({0: [(_dt(31, 13), 1.0)]}) as env:
            out = S._weather_lead_read(_dev(), '2026-10-31T15:00/2026-10-31T18:00', LEADS, 'zone-1')
        self.assertIn('No data', out['message'])
        self.assertEqual([], env.reader.calls)

    def test_period_ended(self):
        with _Env({}):
            self.assertTrue(S._period_ended('2026-10-30/2026-10-30', 'zone-1'))
            self.assertTrue(S._period_ended('2026-10-30T11:00/2026-10-30T13:00', 'zone-1'))
            self.assertFalse(S._period_ended('2026-10-26/', 'zone-1'))      # 지금까지
            self.assertFalse(S._period_ended('2026-10-31/2026-10-31', 'zone-1'))    # 오늘은 아직 안 끝났다
            self.assertFalse(S._period_ended('24h', 'zone-1'))
            self.assertFalse(S._period_ended(None, 'zone-1'))


class WholeTool(unittest.TestCase):
    """`get_weather_tool` 전체 — 장소 찾기·장치 고르기는 패치한다."""

    def _run(self, device, model=(DRIVER,), leads=None, details=None, forecast=(DRIVER,), influx=True,
             **kwargs):
        shape = MagicMock()
        shape.unique_id, shape.feature = 'zone-1', {'properties': {'name': '2포장'}}
        reads = []

        def read(**kw):
            reads.append(kw)
            return details if details is not None else [_row('temperature', 'C', 'Temperature', device_kind='input')]

        with patch.object(S, '_read_place', return_value=(shape, None)), \
                patch.object(S, '_pick_weather_input', return_value=(device, 'nearby', [])), \
                patch.object(S, '_control_outdoor', return_value={'name': 'x'}) as outdoor, \
                patch.object(S, 'forecast_input_hint', return_value=None), \
                patch.object(S, '_check_influxdb_available', return_value=(influx, 'x')), \
                patch.object(S, 'get_sensor_detail', side_effect=read), \
                patch('aot.tools.data_tools.weather_summary.sun_for', return_value=None), \
                patch('aot.utils.inputs.model_input_drivers', return_value=set(model)), \
                patch('aot.utils.inputs.forecast_time_input_drivers', return_value=set(forecast)), \
                patch('aot.utils.inputs.hourly_lead_channels', return_value=leads or {}):
            out = S.get_weather_tool(zone_name='2포장', **kwargs)
        return out, reads, outdoor

    def test_the_old_call_is_unchanged(self):
        """인앱 AI·개요·점검 스크립트의 호출 — 리드 읽기·`wide`·새 칸이 없다."""
        with _Env({}):
            out, reads, outdoor = self._run(_dev(), leads=LEADS)
        self.assertEqual({'loc_id', 'time_range', 'sensor_type', 'limit', 'peaks'}, set(reads[0]))
        self.assertEqual({'name', 'device_id', 'driver', 'data_origin'}, set(out['weather_device']))
        self.assertEqual("This weather source is a forecast model for these coordinates, not an observation "
                         "at the site. Say so.", out['weather_model_note'])
        self.assertTrue(outdoor.called)
        self.assertNotIn('period_ended', out)

    def test_detail_false_without_the_surface_flag_is_unchanged_too(self):
        with _Env({}):
            out, reads, _o = self._run(_dev(), leads=LEADS, detail=False)
        self.assertNotIn('wide', reads[0])
        self.assertIn('latest', out['summary'][0])

    def test_the_surface_reads_a_forecast_source_by_target_time_and_says_so(self):
        with _Env({0: [(_dt(30, 12), 19.2)]}):
            out, reads, outdoor = self._run(_dev(), leads=LEADS, detail=False, brief=True,
                                            time_range='2026-10-30/2026-10-30')
        self.assertEqual([], reads)                     # 저장 시각 그대로 읽는 길을 지나지 않는다
        line = out['summary'][0]
        self.assertEqual(('Temperature +1h', 19.2, '10-30 13:00'), (line['channel'], line['last'], line['max_at']))
        self.assertEqual(('model', 1, 'target'), tuple(out['weather_device'][k] for k in
                                                       ('data_origin', 'lead_h', 'time_basis')))
        self.assertIn('+1h forecast', out['weather_model_note'])
        self.assertTrue(out['period_ended'])
        self.assertFalse(outdoor.called)                # 지금 값과 지난 값을 견주지 않는다

    def test_influx_down_takes_the_old_path_and_says_times_are_stored(self):
        with _Env({}):
            out, reads, _o = self._run(_dev(), leads=LEADS, influx=False, detail=False, brief=True)
        self.assertTrue(reads)
        self.assertEqual('stored', out['weather_device']['time_basis'])

    def test_a_series_call_keeps_channels_and_target_times(self):
        with _Env({0: [(_dt(30, 12), 19.2)]}):
            out, _r, _o = self._run(_dev(), leads=LEADS, detail=True, brief=True,
                                    time_range='2026-10-30/2026-10-30')
        self.assertEqual('2026-10-30T13:00:00+09:00', out['data'][0]['readings'][0]['t'])
        self.assertEqual('Temperature +1h', out['data'][0]['channel'])

    def test_an_observed_station_stays_observed(self):
        station = _dev()
        station.device = 'KMA_weather_500'
        with _Env({}):
            out, reads, _o = self._run(station, model=(), detail=False, brief=True,
                                       time_range='2026-10-30/2026-10-30')
        self.assertTrue(reads[0]['wide'])
        self.assertEqual('2026-10-30/2026-10-30', reads[0]['time_range'])
        self.assertEqual('observed', out['weather_device']['data_origin'])
        self.assertNotIn('weather_model_note', out)
        self.assertNotIn('time_basis', out['weather_device'])

    def test_a_forecast_input_without_lead_channels_names_its_time_basis(self):
        daily = _dev()
        daily.device = 'OPEN_METEO_DAILY_FORECAST'
        with _Env({}):
            out, _r, _o = self._run(daily, model=(daily.device,), forecast=(daily.device,), detail=False, brief=True)
        self.assertEqual('stored', out['weather_device']['time_basis'])


class RainStats(unittest.TestCase):

    def _stats(self, driver, unit, name):
        dev, m = MagicMock(), MagicMock()
        dev.device, m.name, m.measurement = driver, name, 'precipitation'
        data = [(_dt(30, 12, 5), 0.4), (_dt(30, 12, 10), 0.4), (_dt(30, 12, 20), 0.1)]
        with patch('aot.utils.inputs.forecast_time_input_drivers', return_value={DRIVER}):
            return S._rain_sum_stats(dev, m, 'precipitation', unit, data)

    def test_a_known_interval_sums_by_cell(self):
        self.assertEqual({'sum': 0.5}, self._stats('KMA_weather_500', 'mm', '15-min Precipitation'))

    def test_a_rate_or_counter_is_not_summed(self):
        self.assertEqual({'sum_why': 'no fixed interval'}, self._stats('sensecap_weather', 'mm_h', 'Rainfall Hourly'))
        self.assertEqual({'sum_why': 'no fixed interval'}, self._stats('sensecap_weather', 'mm', 'Rain Accumulation'))

    def test_rain_probability_has_no_total(self):
        self.assertEqual({}, self._stats('KMA_weather_500', 'percent', 'Probability'))


class DriverMeta(unittest.TestCase):

    def test_lead_channels_come_from_the_driver(self):
        from aot.inputs import open_meteo_hourly_forecast as hf
        from aot.utils import inputs
        info = {DRIVER: {'measurements_dict': hf.measurements_dict}}
        with patch.object(inputs, '_parsed_input_information', return_value=info):
            got = inputs.hourly_lead_channels(DRIVER)
        self.assertEqual(21, len(got))                  # 창 집계 6개·창 길이는 한 시각을 가리키지 않는다
        self.assertEqual((1, 'instant'), got[0])
        self.assertEqual((1, 'cell'), got[2])
        self.assertEqual((6, 'cell'), got[20])

    def test_an_unknown_driver_has_none(self):
        from aot.utils import inputs
        with patch.object(inputs, '_parsed_input_information', return_value={'X': {'measurements_dict': {0: {}}}}):
            self.assertEqual({}, inputs.hourly_lead_channels('X'))
            self.assertEqual({}, inputs.hourly_lead_channels('missing'))


class FourQuestions(unittest.TestCase):
    """사용자가 물은 네 질문의 호출 — 8084 재확인은 병합 뒤 관리자가 같은 인자로 한다."""

    TODAY = date(2026, 10, 31)

    def _read(self, text):
        from aot.tools.domain import dispatch
        o = next(x for x in OPS if (x.tool, x.op) == ('weather', 'now'))
        with patch.object(dispatch, 'today_at', return_value=self.TODAY):
            got = dispatch._period_args(o, 'get_weather', text)
        return got['time_range'], got[dispatch.META_KEY]['period']['read']

    def test_this_morning_at_seven(self):
        self.assertEqual('2026-10-31T06:30/2026-10-31T07:30',
                         self._read('2026-10-31T06:30/2026-10-31T07:30')[0])

    def test_yesterday_lunchtime_keeps_its_end(self):
        got, read = self._read('2026-10-30T11:00/2026-10-30T13:00')
        self.assertEqual('2026-10-30T11:00/2026-10-30T13:00', got)
        self.assertNotIn('to now', read)

    def test_yesterday_is_that_day_only(self):
        got, read = self._read('yesterday')
        self.assertEqual('2026-10-30/2026-10-30', got)
        self.assertEqual('2026-10-30 to 2026-10-30 (both days included)', read)

    def test_a_date_is_that_day_only(self):
        self.assertEqual('2026-10-29/2026-10-29', self._read('2026-10-29')[0])

    def test_this_week_runs_to_now(self):
        got, read = self._read('this_week')
        self.assertEqual('2026-10-26/', got)
        self.assertEqual('2026-10-26 to now', read)

    def test_today_runs_to_now(self):
        self.assertEqual('2026-10-31/', self._read('today')[0])

    def test_a_future_period_is_refused(self):
        from aot.tools.domain import dispatch
        o = next(x for x in OPS if (x.tool, x.op) == ('weather', 'now'))
        with patch.object(dispatch, 'today_at', return_value=self.TODAY):
            self.assertIsInstance(dispatch._period_args(o, 'get_weather', 'tomorrow'), list)


class Registry(unittest.TestCase):

    def test_the_surface_turns_it_on_and_the_schema_does_not_show_it(self):
        from aot.tools.domain.contract import catalog
        o = next(x for x in OPS if (x.tool, x.op) == ('weather', 'now'))
        self.assertEqual('range', o.period_form)
        self.assertTrue(all(v.get('brief') is True for v in o.defaults_by_kind.values()))
        schema = catalog()['get_weather']['inputSchema']['properties']
        self.assertNotIn('brief', schema)
        self.assertNotIn('wide', schema)


def _past(asked, rows=None, **extra):
    return dict({'read_as': {'target': {'name': '2포장'}, 'period': {'asked': asked, 'read': 'x'}},
                 'summary': rows or [{'measurement': 'temperature', 'unit': 'C', 'last': 10.4, 'min': 8.2, 'max': 19.2}],
                 'period_ended': True}, **extra)


class CardTitle(unittest.TestCase):

    def _title(self, asked):
        return server_card.compose('now', _past(asked))[0]

    def test_title_follows_the_period(self):
        self.assertEqual('2포장 weather, yesterday', self._title('yesterday'))
        self.assertEqual('2포장 weather, yesterday', self._title('어제'))
        self.assertEqual('2포장 weather, this week', self._title('this_week'))
        self.assertEqual('2포장 weather, today', self._title('today'))
        self.assertEqual('2포장 weather, last 24h', self._title('24h'))
        self.assertEqual('2포장 weather, 10-29', self._title('2026-10-29'))
        self.assertEqual('2포장 weather, 10-26–10-28', self._title('2026-10-26/2026-10-28'))
        self.assertEqual('2포장 weather, 10-30 11:00–13:00', self._title('2026-10-30T11:00/2026-10-30T13:00'))

    def test_no_period_is_still_now(self):
        body = {'read_as': {'target': {'name': '2포장'}}, 'summary': [{'measurement': 'temperature', 'latest': 1}]}
        self.assertEqual('2포장 weather now', server_card.compose('now', body)[0])
        self.assertEqual('2포장 weather now', self._title('now'))

    def test_fanned_out_read_uses_the_period_too(self):
        row = {'target': {'name': '1포장'}, 'result': {'summary': [{'measurement': 'temperature', 'last': 1, 'min': 0, 'max': 2}]}}
        body = {'status': 'success', 'target': {'name': '김제'}, 'results': [row, row],
                'period': {'asked': 'yesterday', 'read': 'x'}}
        self.assertEqual('김제 weather, yesterday', server_card.compose('now', body)[0])

    def test_lines_show_the_range_of_an_ended_period_not_its_last_value(self):
        rows = [{'measurement': 'temperature', 'unit': '°C', 'last': 10.4, 'min': 8.2, 'max': 19.2},
                {'measurement': 'rain', 'unit': 'mm', 'last': 0.0, 'min': 0.0, 'max': 0.6, 'sum': 0.6},
                {'measurement': 'precipitation', 'unit': 'percent', 'last': 0.0, 'min': 0.0, 'max': 85.0}]
        msg = server_card.compose('now', _past('yesterday', rows))[1]
        self.assertEqual(['Temperature 8.2–19.2 °C', 'Rain total 0.6 mm', 'Chance of rain 0–85 percent'],
                         msg.splitlines())


if __name__ == '__main__':
    unittest.main()
