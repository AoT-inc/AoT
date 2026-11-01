# coding=utf-8
"""날씨 도구의 요약형 기본 응답 — 2026-10-27 음성 점검에서 나온 것.

고정하는 계약:
  1. 관측·예보의 기본(`detail=False`, 도메인 틀이 넣는다)은 항목별 최저·최고·평균과 극값의 시각이다.
     시계열은 `detail=True` 일 때만 싣는다.
  2. 안쪽 도구를 `detail` 없이 부르는 옛 호출(None)은 예전 모양 그대로다.
  3. 일 단위 예보 행은 이미 요약이라 접지 않는다.
  4. 항목 지정(`sensor_type`)은 일상어도 받고, 못 찾은 낱말은 말한다.

DB·모델 없이 도는 결정론적 테스트다.
"""
import unittest

from aot.tools.data_tools import weather_summary as ws


def _observed():
    def row(name, unit, vals):
        readings = [{'t': '2026-10-27T%02d:00:00+09:00' % h, 'v': v, 'u': unit} for h, v in enumerate(vals)]
        hi, lo = max(vals), min(vals)
        return {'device_name': 'meteo', 'device_kind': 'input', 'measurement': name,
                'readings': readings[-5:], 'total_readings': len(vals),
                'stats': {'min': lo, 'max': hi, 'avg': 1.0, 'count': len(vals),
                          'min_at': readings[vals.index(lo)]['t'], 'max_at': readings[vals.index(hi)]['t']}}
    return {'zone_name': '3-1', 'weather_source': 'weather_station',
            'other_weather_devices': [{'name': 'a'}, {'name': 'b'}], 'weather_pick': {'x': 1},
            'data': [row('temperature', 'C', [10.0, 12.0, 20.0, 15.0, 11.0, 9.0]),
                     row('speed', 'm_s', [1.0, 5.0, 2.0, 3.0, 2.0, 1.0])]}


def _forecast(daily=False):
    rows = [{'hour_offset': h, 'time': '2026-10-27T%02d:00' % h, 'temperature_2m (°C)': 10.0 + h,
             'wind_speed (m/s)': 8.0 - h, 'precipitation (mm)': 0.5, 'precipitation_probability (%)': 40.0}
            for h in range(4)]
    return {'status': 'success', 'grid': {'lat': 1}, 'latitude': 1, 'count': 4, 'period': {'daily': daily},
            'forecasts': rows, 'note': 'model forecast'}


class ObservedSummary(unittest.TestCase):

    def test_rows_fold_to_extremes_with_their_time(self):
        out = ws.summarize_observed(_observed())
        self.assertNotIn('data', out)
        t = out['summary'][0]
        self.assertEqual(('temperature', 20.0, '10-27 02:00', 9.0, '10-27 05:00'),
                         (t['measurement'], t['max'], t['max_at'], t['min'], t['min_at']))
        self.assertEqual(9.0, t['latest'])
        self.assertEqual(2, out['other_weather_devices_count'])
        self.assertNotIn('weather_pick', out)
        self.assertEqual('weather_station', out['weather_source'])

    def test_field_pick_takes_everyday_words_and_names_the_misses(self):
        out = ws.summarize_observed(_observed(), ws.field_tokens('temp, hail'))
        self.assertEqual(['temperature'], [r['measurement'] for r in out['summary']])
        self.assertEqual(['hail'], out['fields_not_found'])
        self.assertEqual(['temperature', 'speed'], out['available_fields'])

    def test_error_bodies_pass_through(self):
        err = {'error': 'zone_not_found'}
        self.assertIs(err, ws.summarize_observed(err))

    def test_detail_filter_keeps_the_series(self):
        out = ws.filter_observed(_observed(), ws.field_tokens(['temperature']))
        self.assertEqual(1, len(out['data']))
        self.assertEqual(5, len(out['data'][0]['readings']))


class ForecastSummary(unittest.TestCase):

    def test_hourly_rows_fold(self):
        out = ws.summarize_forecast(_forecast())
        self.assertNotIn('forecasts', out)
        self.assertNotIn('grid', out)
        wind = out['summary']['wind_speed (m/s)']
        self.assertEqual((8.0, '10-27 00:00', 5.0, '10-27 03:00'),
                         (wind['max'], wind['max_at'], wind['min'], wind['min_at']))
        self.assertEqual(2.0, out['summary']['precipitation (mm)']['sum'])
        self.assertNotIn('sum', out['summary']['precipitation_probability (%)'])
        self.assertEqual('model forecast', out['note'])

    def test_daily_rows_stay(self):
        fc = _forecast(daily=True)
        self.assertIs(fc, ws.summarize_forecast(fc))

    def test_failure_bodies_stay(self):
        bad = {'status': 'unavailable', 'message': 'x'}
        self.assertIs(bad, ws.summarize_forecast(bad))

    def test_rain_word_picks_rain_columns(self):
        out = ws.summarize_forecast(_forecast(), ws.field_tokens('rain'))
        self.assertEqual({'precipitation (mm)', 'precipitation_probability (%)'}, set(out['summary']))

    def test_detail_filter_keeps_hourly_rows(self):
        out = ws.filter_forecast(_forecast(), ws.field_tokens('wind'))
        self.assertEqual(4, len(out['forecasts']))
        self.assertEqual({'hour_offset', 'time', 'wind_speed (m/s)'}, set(out['forecasts'][0]))


class Flags(unittest.TestCase):

    def test_only_explicit_false_summarizes(self):
        self.assertTrue(ws.wants_summary(False))
        self.assertFalse(ws.wants_summary(None))          # 옛 호출은 예전 모양
        self.assertFalse(ws.wants_summary(True))
        self.assertTrue(ws.wants_full(True))

    def test_window(self):
        self.assertEqual('24h', ws.window_label('3h', None, True))      # 요약 기본
        self.assertEqual('3h', ws.window_label('3h', None, False))
        self.assertEqual('48h', ws.window_label('3h', '2d', True))
        self.assertEqual('6h', ws.window_label('6h', '1h', False))      # 장치 창보다 좁아지지 않는다
        self.assertEqual('2026-10-01/2026-10-03', ws.window_label('3h', '2026-10-01/2026-10-03', True))


class Wiring(unittest.TestCase):

    def test_domain_ops_default_to_summary_and_take_the_new_words(self):
        from aot.tools.domain.registry_data import OPS
        by = {(o.tool, o.op): o for o in OPS}
        now, fc = by[('weather', 'now')], by[('weather', 'forecast')]
        for o in (now, fc):
            self.assertEqual('sensor_type', o.args['measurement'])
            self.assertIn('detail', o.extra_args)
            self.assertTrue(all(v.get('detail') is False for v in o.defaults_by_kind.values()))
        self.assertEqual('time_range', now.args['period'])


if __name__ == '__main__':
    unittest.main()


class SunTimesOnWeather(unittest.TestCase):
    """일출·일몰 — 예보 출처가 아니라 `aot.utils.solar` 의 좌표 계산(주야 판정과 같은 정본)."""

    def test_one_line_per_local_day_in_the_period(self):
        rows = ws.sun_for(lat=35.86, lon=126.88, dates=ws.period_dates('2026-10-27T00:00', '2026-10-29T00:00'))
        self.assertEqual(['2026-10-27', '2026-10-28'], [r['date'] for r in rows])
        self.assertRegex(rows[0]['sunrise'], r'^\d\d:\d\d$')
        self.assertLess(rows[0]['sunrise'], rows[0]['sunset'])

    def test_matches_the_solar_module_used_for_day_night(self):
        from datetime import date
        from aot.utils import solar
        st = solar.sun_times(latitude=35.86, longitude=126.88, date=date(2026, 10, 27))
        got = ws.sun_for(lat=35.86, lon=126.88, dates=[date(2026, 10, 27)])[0]
        self.assertEqual(st.sunrise.astimezone(__import__('pytz').timezone(st.tz_name)).strftime('%H:%M'),
                         got['sunrise'])

    def test_no_coordinates_means_no_sun_not_an_error(self):
        from unittest import mock
        with mock.patch('aot.utils.solar.sun_times', return_value=None):
            self.assertIsNone(ws.sun_for(lat=None, lon=None))
        with mock.patch('aot.utils.solar.sun_times', side_effect=RuntimeError('x')):
            self.assertIsNone(ws.sun_for(lat=1, lon=1))

    def test_polar_day_names_its_status(self):
        rows = ws.sun_for(lat=78.2, lon=15.6, dates=ws.period_dates('2026-06-21T00:00', '2026-06-22T00:00'))
        self.assertEqual('always_day', rows[0].get('status'))

    def test_weather_tools_use_the_solar_module_not_a_forecast_field(self):
        import os
        from aot.tools.data_tools import weather_summary
        with open(os.path.join(os.path.dirname(weather_summary.__file__), 'measurement.py'),
                  encoding='utf-8') as f:
            src = f.read()
        self.assertIn("_ws.sun_for(", src)
        self.assertNotIn("daily.sunrise", src)             # 예보 응답에서 읽지 않는다
