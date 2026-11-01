# coding=utf-8
"""get_weather_forecast 의 장소·기간 지정 — 김제 고정 해소(PR 0).

HTTP·캐시는 가짜(openmeteo_forecast_cache.get_bundle), 장소 이름은 임시 DB 의
GeoShape·Input 으로 푼다. 좌표·시간대 해석(resolve_coords / resolve_location_tz)은
데몬 DB 를 타므로 id 별 표로 대체한다.
"""
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytz

from aot.tools.aot_data_tool_service import AoTDataToolService as S

_GET = 'aot.ai.context.ext.openmeteo_forecast_cache.get_bundle'

# id → (lat, lon, tz)
_SPOTS = {
    'site-gimje': (35.80, 126.88, 'Asia/Seoul'),
    'site-yeongyang': (36.67, 129.11, 'Asia/Seoul'),
    'site-kumamoto': (32.80, 130.71, 'Asia/Tokyo'),
    'site-la': (34.05, -118.24, 'America/Los_Angeles'),
    'fac-yy': (36.70, 129.12, 'Asia/Seoul'),
    'dev-th7': (36.68, 129.10, 'Asia/Seoul'),
}
_DEFAULT = (35.80, 126.88, 'Asia/Seoul')


def _square(x0, y0, size=0.002):
    return {'type': 'Polygon', 'coordinates': [[
        [x0, y0], [x0 + size, y0], [x0 + size, y0 + size], [x0, y0 + size],
        [x0, y0]]]}


def _fake_coords(entity=None, *, target_id=None):
    if target_id in _SPOTS:
        la, lo, _ = _SPOTS[target_id]
        return la, lo, 'shape'
    if target_id == 'site-nocoords':
        return _DEFAULT[0], _DEFAULT[1], 'system'
    return _DEFAULT[0], _DEFAULT[1], 'system'


def _fake_tz(target_id):
    return pytz.timezone(_SPOTS.get(target_id, _DEFAULT)[2])


def make_bundle(now_utc, tz_name, grid=(35.81, 126.89)):
    """오늘 0시(지역)부터 14일치 시간별 + 일별."""
    tz = pytz.timezone(tz_name)
    today0 = now_utc.astimezone(tz).replace(
        tzinfo=None, hour=0, minute=0, second=0, microsecond=0)
    hourly = [{'time': (today0 + timedelta(hours=i)).strftime('%Y-%m-%dT%H:%M'),
               'temperature_2m (°C)': float(i % 30)} for i in range(14 * 24)]
    daily = [{'time': (today0 + timedelta(days=i)).strftime('%Y-%m-%d'),
              'temperature_2m_max (°C)': 20.0 + i,
              'precipitation_sum (mm)': 0.0} for i in range(14)]
    return {'meta': {'grid_latitude': grid[0], 'grid_longitude': grid[1],
                     'elevation_m': 12.0, 'timezone': tz_name},
            'hourly': hourly, 'daily': daily}


class _Fixture(unittest.TestCase):
    NOW = datetime(2026, 10, 13, 1, 41, tzinfo=timezone.utc)   # 서울 10-13 10:41

    @classmethod
    def setUpClass(cls):
        from flask import Flask
        from flask_babel import Babel
        from aot.aot_flask.extensions import db
        import aot.databases.models  # noqa: F401
        from aot.databases.models import GeoMap, GeoShape, Input

        cls._tmp = tempfile.TemporaryDirectory()
        app = Flask(__name__)
        app.config['SQLALCHEMY_DATABASE_URI'] = \
            'sqlite:///' + os.path.join(cls._tmp.name, 'fc.db')
        app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
        db.init_app(app)
        Babel(app)
        cls._ctx = app.app_context()
        cls._ctx.push()
        db.create_all()
        db.session.add(GeoMap(unique_id='map-a', name='지도A'))

        def shape(uid, typ, name, geom, **kw):
            db.session.add(GeoShape(
                unique_id=uid, geo_id='map-a', type=typ,
                feature={'type': 'Feature', 'properties': {'name': name},
                         'geometry': geom}, **kw))
        shape('site-gimje', 'site', '김제 농장', _square(126.88, 35.80))
        shape('site-yeongyang', 'site', '영양 농장', _square(129.11, 36.67))
        shape('site-kumamoto', 'site', '구마모토 농장', _square(130.71, 32.80))
        shape('site-la', 'site', '로스앤젤레스 농장', _square(-118.24, 34.05))
        shape('site-nocoords', 'site', '도형없는 부지',
              {'type': 'Polygon', 'coordinates': []})
        shape('zone-twin-a', 'zone', '쌍둥이 구역', _square(126.9, 35.9))
        shape('zone-twin-b', 'zone', '쌍둥이 구역', _square(129.2, 36.7))
        db.session.add(Input(unique_id='dev-th7', name='온습도_7',
                             device='OPEN_METEO_FORECAST'))
        db.session.commit()

    @classmethod
    def tearDownClass(cls):
        from aot.aot_flask.extensions import db
        db.session.remove()
        cls._ctx.pop()
        cls._tmp.cleanup()

    def setUp(self):
        self.calls = []
        self.svc = MagicMock()
        self.svc.source_api_key.return_value = ''
        self.found = {"kind": "data_source", "svc": self.svc,
                      "src": {'source_id': 'src-om', 'label': 'SIM'}}
        self.info = {'from': 'live', 'fetched_at': self.NOW.timestamp(),
                     'age_min': 0, 'stale': False}
        self.err = None
        self.default = _DEFAULT
        self._patches = [
            patch.object(S, '_open_meteo_forecast_source', return_value=self.found),
            patch(_GET, side_effect=self._get_bundle),
            patch('aot.utils.timekit.utc_now', return_value=self.NOW),
            patch('aot.utils.timekit.resolve_coords', side_effect=self._coords),
            patch('aot.utils.device_tz.resolve_location_tz_and_source',
                  side_effect=lambda i: (_fake_tz(i), 'explicit')),
        ]
        for p in self._patches:
            p.start()
            self.addCleanup(p.stop)

    def _coords(self, entity=None, *, target_id=None):
        if target_id is None:
            return self.default[0], self.default[1], 'system'
        return _fake_coords(entity, target_id=target_id)

    def _get_bundle(self, lat, lon, tz, api_key=None):
        self.calls.append({'lat': lat, 'lon': lon, 'tz': tz, 'key': api_key})
        if self.err:
            return None, None, self.err
        return make_bundle(self.NOW, tz), self.info, None


class TestPlaceByRequest(_Fixture):

    def test_gimje_and_yeongyang_names_ask_their_own_coordinates(self):
        a = S.get_weather_forecast(place='김제 농장')
        b = S.get_weather_forecast(place='영양 농장')
        self.assertEqual(a['status'], 'success')
        self.assertEqual((self.calls[0]['lat'], self.calls[0]['lon']), (35.80, 126.88))
        self.assertEqual((self.calls[1]['lat'], self.calls[1]['lon']), (36.67, 129.11))
        self.assertEqual(a['answered_for']['basis'], 'request')
        self.assertEqual(b['answered_for']['name'], '영양 농장')
        self.assertEqual(b['answered_for']['kind'], 'site')
        self.assertNotIn('id', b['answered_for'])
        self.assertIn('distance_km', b['grid'])
        self.assertGreater(b['grid']['distance_km'], 0)

    def test_site_id_and_name_variants_resolve(self):
        r = S.get_weather_forecast(place='site-yeongyang')
        self.assertEqual(r['answered_for']['name'], '영양 농장')
        r = S.get_weather_forecast(place='영양농장')           # 공백 변형
        self.assertEqual(r['status'], 'success')
        self.assertEqual(self.calls[-1]['lat'], 36.67)

    def test_device_name_with_space_variant_uses_device_location(self):
        r = S.get_weather_forecast(place='온습도 7')
        self.assertEqual(r['status'], 'success', r)
        self.assertEqual(r['answered_for']['kind'], 'device')
        self.assertEqual((self.calls[0]['lat'], self.calls[0]['lon']), (36.68, 129.10))

    def test_kumamoto_requests_its_own_timezone_and_local_tomorrow(self):
        r = S.get_weather_forecast(place='구마모토 농장', start='tomorrow', hours=24)
        self.assertEqual(self.calls[0]['tz'], 'Asia/Tokyo')
        self.assertEqual(r['timezone'], 'Asia/Tokyo')
        # 도쿄는 서울과 같은 시각 → 날짜 10-13, 내일 = 10-14
        self.assertEqual(r['period']['start'], '2026-10-14T00:00')

    def test_negative_offset_zone_tomorrow_is_that_regions_date(self):
        # UTC 10-13 01:41 = 로스앤젤레스 10-12 18:41 → 내일 = 10-13
        r = S.get_weather_forecast(place='로스앤젤레스 농장', start='tomorrow', hours=6)
        self.assertEqual(self.calls[0]['tz'], 'America/Los_Angeles')
        self.assertEqual(r['period']['start'], '2026-10-13T00:00')
        self.assertEqual(r['forecasts'][0]['time'], '2026-10-13T00:00')

    def test_unknown_name_is_an_error_with_candidates_and_no_http(self):
        r = S.get_weather_forecast(place='없는 곳 xyz')
        self.assertIn('error', r)
        self.assertIn('available_targets', r)
        self.assertEqual(self.calls, [])

    def test_ambiguous_name_asks_instead_of_guessing(self):
        r = S.get_weather_forecast(place='쌍둥이 구역')
        self.assertEqual(r.get('status'), 'needs_disambiguation')
        self.assertTrue(r.get('candidates'))
        self.assertEqual(self.calls, [])

    def test_place_without_coordinates_is_no_coords(self):
        r = S.get_weather_forecast(place='도형없는 부지')
        self.assertEqual(r['status'], 'unavailable')
        self.assertEqual(r['reason'], 'no_coords')
        self.assertEqual(self.calls, [])

    def test_given_place_never_falls_back_to_default(self):
        r = S.get_weather_forecast(place='없는 곳 xyz')
        self.assertNotIn('answered_for', r)
        self.assertEqual(self.calls, [])


class TestPlaceFromScreenAndDefault(_Fixture):

    def _screen(self, items, user='u1'):
        """items: 화면마다 (열린 항목 | None, 나이 초)."""
        rows = []
        for i, (item, age) in enumerate(items):
            rows.append({'client_state': '{"dialog": "x (map)"}',
                         'client_at': self.NOW.timestamp() - age + 0,
                         'browser_key': 'b%d' % i, '_item': item})
        import time as _t
        real = _t.time()
        for r in rows:
            r['client_at'] = real - items[rows.index(r)][1]

        def open_item(row, dialog):
            return row['_item']
        return (patch('aot.utils.web_presence.recent', return_value=rows),
                patch.object(S, '_screen_open_item', side_effect=open_item))

    def _run(self, items, user_id='u1'):
        p1, p2 = self._screen(items)
        with p1, p2:
            return S.get_weather_forecast(user_id=user_id)

    def test_fresh_screen_with_one_open_item_wins(self):
        r = self._run([({'kind': 'site', 'name': '영양 농장', 'id': 'site-yeongyang'}, 3)])
        self.assertEqual(r['answered_for']['basis'], 'screen')
        self.assertEqual(self.calls[0]['lat'], 36.67)

    def test_several_screens_with_the_same_item_still_use_it(self):
        item = {'kind': 'site', 'name': '영양 농장', 'id': 'site-yeongyang'}
        r = self._run([(item, 2), (item, 5)])
        self.assertEqual(r['answered_for']['basis'], 'screen')

    def test_stale_screen_falls_to_default(self):
        r = self._run([({'kind': 'site', 'name': '영양 농장', 'id': 'site-yeongyang'}, 60)])
        self.assertEqual(r['answered_for']['basis'], 'default')
        self.assertEqual(self.calls[0]['lat'], 35.80)

    def test_conflicting_screens_fall_to_default_with_note(self):
        r = self._run([
            ({'kind': 'site', 'name': '영양 농장', 'id': 'site-yeongyang'}, 2),
            ({'kind': 'site', 'name': '김제 농장', 'id': 'site-gimje'}, 2)])
        self.assertEqual(r['answered_for']['basis'], 'default')
        self.assertIn('screen ambiguous', r['note'])

    def test_fresh_screen_without_open_window_has_no_ambiguity_note(self):
        import time as _t
        rows = [{'client_state': '{"route": "/dashboard"}',
                 'client_at': _t.time() - 3, 'browser_key': 'b0'}]
        with patch('aot.utils.web_presence.recent', return_value=rows):
            r = S.get_weather_forecast(user_id='u1')
        self.assertEqual(r['answered_for']['basis'], 'default')
        self.assertNotIn('screen ambiguous', r['note'])
        self.assertNotIn('attribution', r)   # 출처는 화면이 표시한다

    def test_no_user_id_skips_the_screen_step(self):
        with patch('aot.utils.web_presence.recent',
                   side_effect=AssertionError('screen read')):
            r = S.get_weather_forecast()
        self.assertEqual(r['answered_for']['basis'], 'default')

    def test_default_names_the_nearest_site_and_lists_other_places(self):
        r = S.get_weather_forecast()
        self.assertEqual(r['answered_for']['name'], '김제 농장')
        self.assertEqual(r['answered_for']['basis'], 'default')
        self.assertIn('영양 농장', r['other_places'])
        self.assertNotIn('김제 농장', r['other_places'])
        self.assertLessEqual(len(r['other_places']), 8)
        self.assertIn('Other sites exist', r['note'])

    def test_default_with_no_nearby_site_is_called_farm_default(self):
        self.default = (0.0, 0.0, 'Asia/Seoul')
        r = S.get_weather_forecast()
        self.assertEqual(r['answered_for']['name'], 'farm default')


class TestPeriod(_Fixture):

    def test_tomorrow_24_is_hourly(self):
        r = S.get_weather_forecast(place='김제 농장', start='tomorrow', hours=24)
        self.assertEqual(r['step_hours'], 1)
        self.assertEqual(r['period']['start'], '2026-10-14T00:00')
        self.assertEqual(r['forecasts'][0]['time'], '2026-10-14T00:00')
        self.assertEqual(r['forecasts'][0]['hour_offset'], 14)   # 지금 칸 10:00 기준
        self.assertEqual(r['count'], 25)

    def test_day_after_with_time_and_six_hours(self):
        r = S.get_weather_forecast(place='김제 농장', start='day_after 06:00', hours=6)
        self.assertEqual(r['forecasts'][0]['time'], '2026-10-15T06:00')
        self.assertEqual(r['forecasts'][-1]['time'], '2026-10-15T12:00')

    def test_72_hours_is_three_hourly(self):
        r = S.get_weather_forecast(place='김제 농장', hours=72)
        self.assertEqual(r['step_hours'], 3)
        self.assertEqual(r['count'], 25)
        self.assertEqual(r['forecasts'][0]['hour_offset'], 0)   # 지금 칸 유지

    def test_168_hours_is_daily_with_seven_rows(self):
        r = S.get_weather_forecast(place='김제 농장', hours=168)
        self.assertTrue(r['period']['daily'])
        self.assertEqual(r['count'], 7)
        self.assertEqual(r['forecasts'][0]['date'], '2026-10-13')
        self.assertEqual(r['forecasts'][0]['day_offset'], 0)
        self.assertEqual(r['forecasts'][6]['day_offset'], 6)
        self.assertIn('whole local day', r['note'])

    def test_336_hours_from_tomorrow_is_truncated_with_note(self):
        r = S.get_weather_forecast(place='김제 농장', start='tomorrow', hours=336)
        self.assertTrue(r['period']['truncated'])
        self.assertEqual(r['count'], 13)
        self.assertIn('Beyond the forecast range of Open-Meteo (14 days)', r['note'])

    def test_hours_over_the_max_are_cut_and_told(self):
        r = S.get_weather_forecast(place='김제 농장', hours=1000)
        self.assertEqual(r['requested_hours'], 336)
        self.assertIn('336', r['note'])

    def test_start_beyond_the_horizon_is_unavailable(self):
        r = S.get_weather_forecast(place='김제 농장', start='2026-10-28')
        self.assertEqual(r['status'], 'unavailable')

    def test_past_date_is_an_error_with_allowed_forms(self):
        r = S.get_weather_forecast(place='김제 농장', start='2026-10-10')
        self.assertEqual(r['status'], 'error')
        self.assertIn('tomorrow', r['message'])

    def test_unknown_format_is_an_error(self):
        r = S.get_weather_forecast(place='김제 농장', start='next week')
        self.assertEqual(r['status'], 'error')

    def test_hours_below_one_is_an_error(self):
        self.assertEqual(S.get_weather_forecast(hours=0)['status'], 'error')

    def test_past_hour_today_is_pulled_to_the_current_slot(self):
        r = S.get_weather_forecast(place='김제 농장', start='2026-10-13T03:00', hours=3)
        self.assertEqual(r['forecasts'][0]['time'], '2026-10-13T10:00')
        self.assertIn('moved to the current hour', r['note'])

    def test_iso_with_offset_is_converted_to_place_time(self):
        r = S.get_weather_forecast(place='김제 농장', start='2026-10-13T12:00+00:00',
                                   hours=2)
        self.assertEqual(r['forecasts'][0]['time'], '2026-10-13T21:00')

    def test_response_keeps_top_level_keys(self):
        r = S.get_weather_forecast(place='김제 농장')
        for k in ('latitude', 'longitude', 'timezone', 'step_hours',
                  'requested_hours', 'count', 'forecasts', 'source_name',
                  'source_ref', 'answered_for', 'grid', 'period', 'data'):
            self.assertIn(k, r)
        self.assertEqual(r['latitude'], 35.81)
        self.assertEqual(r['data']['from'], 'live')
        self.assertTrue(r['data']['fetched_at'].endswith('+09:00'))


class TestFreshness(_Fixture):

    def test_stale_cache_says_so(self):
        self.info = {'from': 'cache', 'fetched_at': self.NOW.timestamp() - 3 * 3600,
                     'age_min': 180, 'stale': True}
        r = S.get_weather_forecast(place='김제 농장')
        self.assertTrue(r['data']['stale'])
        self.assertIn('3 h old', r['note'])

    def test_failure_without_cache_is_unavailable(self):
        self.err = 'connect_timeout'
        r = S.get_weather_forecast(place='김제 농장')
        self.assertEqual(r['status'], 'unavailable')
        self.assertIn('connect_timeout', r['message'])

    def test_commercial_key_is_passed_when_source_has_one(self):
        self.svc.source_api_key.return_value = 'KEY'
        S.get_weather_forecast(place='김제 농장')
        self.assertEqual(self.calls[0]['key'], 'KEY')


class TestToolExecutionPath(_Fixture):

    def test_place_passes_and_site_is_refused(self):
        from aot.tools.tool_execution import _dispatch_virtual_tool
        ok = _dispatch_virtual_tool('get_weather_forecast', {'place': '영양 농장'})
        self.assertEqual(ok['status'], 'success')
        self.assertNotIn('error', ok)
        self.assertNotIn('_ignored_arguments', ok)
        bad = _dispatch_virtual_tool('get_weather_forecast', {'site': '영양 농장'})
        self.assertEqual(bad['error'], 'unknown_scope_argument')
        self.assertIn('place', bad['message'])      # 받는 인자 목록에 place
        self.assertEqual(self.calls[-1]['lat'], 36.67)   # 거절한 호출은 조회하지 않았다
        n = len(self.calls)
        bad2 = _dispatch_virtual_tool('get_weather_forecast', {'target_name': 'x'})
        self.assertEqual(bad2['error'], 'unknown_scope_argument')
        self.assertEqual(len(self.calls), n)

    def test_execute_tool_injects_the_callers_user_id(self):
        import inspect
        from aot.tools import tool_execution
        src = inspect.getsource(tool_execution._execute_tool)
        self.assertIn('"get_weather_forecast"', src)
        self.assertIn('user_id=scope_user_uuid', src)


if __name__ == '__main__':
    unittest.main()
