# coding=utf-8
"""2026-11-03 MCP 수정 S4 #3~#6 — 토양 예측 막다른 길, 급수 사전 계산 시각, 날씨 출처 표시, 센서 대표값."""
import json
import unittest

from aot.tools.domain import dispatch


def _out(body):
    return [{'type': 'text', 'text': json.dumps(body, ensure_ascii=False)}]


def _body(out):
    return json.loads(out[0]['text'])


class SoilForecastDeadEnd(unittest.TestCase):

    def test_unavailable_points_at_current_value_and_rain(self):
        got = _body(dispatch._unavailable_next(_out(
            {'status': 'unavailable', 'reason': 'no_publication', 'message': 'x', 'plot': '1포장'})))
        self.assertEqual(['status', 'next'], list(got)[:2])
        self.assertIn("measure.latest(target='1포장', measurement='soil moisture')", got['next']['call'])
        self.assertIn("weather.forecast(", got['next']['call'])

    def test_success_and_existing_next_are_untouched(self):
        ok = _out({'status': 'success', 'days': []})
        self.assertEqual(ok, dispatch._unavailable_next(ok))
        has = _out({'status': 'unavailable', 'next': {'call': 'x'}})
        self.assertEqual(has, dispatch._unavailable_next(has))


class WaterEstimateWindow(unittest.TestCase):

    def test_window_is_iso_with_offset_and_duration_comes_back(self):
        # 2026-11-03T00:00:00Z — 시계는 timekit 이 구획에서 푼다(구획이 없으면 농장 시계)
        base = 1793664000.0
        got = _body(dispatch._estimate_window_iso(_out(
            {'plot': 'nope', 'window': {'from': base, 'to': base + 600}, 'litres': 12.0}), '10m'))
        w = got['window']
        self.assertIsInstance(w['from'], str)
        self.assertRegex(w['from'], r'^2026-11-0[23]T\d\d:00:00[+-]\d\d:\d\d$')
        self.assertEqual('10m', got['duration'])
        self.assertTrue(w['to'].endswith(w['from'][-6:]))             # 같은 시계
        self.assertIn(':10:00', w['to'])

    def test_several_plots_and_errors(self):
        base = 1793664000.0
        got = _body(dispatch._estimate_window_iso(_out(
            {'count': 2, 'results': [{'plot': 'a', 'window': {'from': base, 'to': base + 60}},
                                     {'status': 'error', 'message': 'm'}]}), 60))
        self.assertIsInstance(got['results'][0]['window']['from'], str)
        self.assertEqual(60, got['results'][0]['duration'])
        err = _out({'status': 'error', 'message': 'm'})
        self.assertEqual(err, dispatch._estimate_window_iso(err, '10m'))


class WeatherOrigin(unittest.TestCase):

    def test_model_value_shows_at_top_level_and_source_is_unchanged(self):
        got = _body(dispatch._weather_origin(_out(
            {'status': 'success', 'weather_source': 'weather_station',
             'weather_device': {'name': 'x', 'data_origin': 'model'}, 'data': []})))
        self.assertEqual('weather_station', got['weather_source'])
        self.assertEqual('model', got['weather_data_origin'])
        keys = list(got)
        self.assertEqual(keys.index('weather_source') + 1, keys.index('weather_data_origin'))

    def test_no_origin_no_change(self):
        o = _out({'status': 'success', 'weather_source': 'nearby_sensor'})
        self.assertEqual(o, dispatch._weather_origin(o))


class LatestRepresentative(unittest.TestCase):

    def _battery_only(self):
        return {'status': 'success', 'name': '온습도_1', 'measurement': 'electrical_potential', 'timestamp': 't',
                'value': 3.71, 'unit': 'V', 'channels': [{'measurement': 'electrical_potential', 'value': 3.71}],
                'silent_channels': ['temperature', 'humidity'],
                'note': "No value in the last 1h for: temperature, humidity. The value above is from another channel of this device."}

    def test_main_channels_silent_blanks_the_representative(self):
        got = _body(dispatch._latest_tidy(_out(self._battery_only()), False))
        for k in ('measurement', 'value', 'unit', 'timestamp'):
            self.assertNotIn(k, got)
        self.assertEqual(1, len(got['channels']))
        self.assertEqual(['temperature', 'humidity'], got['silent_channels'])
        self.assertNotIn('The value above', got['note'])

    def test_real_battery_only_sensor_stays(self):
        body = {'status': 'success', 'measurement': 'electrical_potential', 'value': 3.7, 'unit': 'V'}
        self.assertEqual(body, _body(dispatch._latest_tidy(_out(body), False)))

    def test_asked_measurement_or_main_representative_stays(self):
        self.assertIn('value', _body(dispatch._latest_tidy(_out(self._battery_only()), True)))
        body = dict(self._battery_only(), measurement='temperature')
        self.assertIn('value', _body(dispatch._latest_tidy(_out(body), False)))

    def test_old_time_range_key_becomes_period(self):
        got = _body(dispatch._latest_tidy(_out({'status': 'success', 'scope': 'farm', 'time_range': '7d'}), False))
        self.assertNotIn('time_range', got)
        self.assertEqual('7d', got['period'])
        both = _body(dispatch._latest_tidy(_out({'status': 'success', 'time_range': None, 'period': 'p'}), False))
        self.assertNotIn('time_range', both)
        self.assertEqual('p', both['period'])


if __name__ == '__main__':
    unittest.main()
