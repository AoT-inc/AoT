# coding=utf-8
"""예보 단일 출처 2·3단계 — 대지의 예보 계열 하나를 지도 슬라이더·AI 예보(·트윈)가 함께 읽는다.

지정이 없으면 공통 폴백(지도 날씨 레이어). 대지가 아닌 장소(또는 출처가 하나도 없는 대지)만 AI 가 사용자가 등록한
Open-Meteo 로 좌표 조회한다 — 사용자는 지정되지 않은 위치의 기상정보도 물을 수 있어야 한다.
"""
import time
import unittest
from unittest.mock import patch

from aot.aot_flask.geo import forecast_series as fs
from aot.aot_flask.geo import weather_state as ws
from aot.tests.test_forecast_place import _Fixture, S

H = 3600.0
T0 = 1_800_000_000.0 - (1_800_000_000.0 % H)      # 정시


def _rows(n=6, rain=None):
    rain = rain or {}
    out = []
    for i in range(n):
        ep = T0 + i * H
        out.append((ep, {'epoch': ep, 'TMP': 20.0 + i, 'REH': 80, 'WSD': 2.0, 'VEC': 350 + 10 * i,
                         'RN1': rain.get(i, 0.0), 'POP': 50, 'CLD': 100, 'SOL': 10 * i}))
    return out


class TestValuesAt(unittest.TestCase):
    def test_instant_values_interpolate_between_hours(self):
        v = fs.values_at(_rows(), T0 + 0.5 * H)
        self.assertAlmostEqual(v['temp'], 20.5)
        self.assertAlmostEqual(v['wind_speed'], 2.0)

    def test_wind_direction_is_circular(self):
        v = fs.values_at(_rows(), T0 + 0.5 * H)           # 350° → 0° 의 중간 = 355°
        self.assertAlmostEqual(v['wind_dir'], 355.0)

    def test_rain_is_the_cell_ending_at_ceil_hour_not_interpolated(self):
        rows = _rows(rain={1: 4.0, 2: 0.0})
        # T0+0.5h 는 T0~T0+1h 칸 — 그 칸이 끝나는 T0+1h 행(4.0)
        self.assertEqual(fs.values_at(rows, T0 + 0.5 * H)['precip'], 4.0)
        # 정각이면 그 정시 행(방금 끝난 칸)
        self.assertEqual(fs.values_at(rows, T0 + 2 * H)['precip'], 0.0)
        self.assertEqual(fs.values_at(rows, T0 + 1 * H)['precip'], 4.0)

    def test_outside_the_file_range_is_empty_and_missing_is_not_zero(self):
        rows = _rows()
        self.assertEqual(fs.values_at(rows, T0 - 2 * H), {})
        self.assertEqual(fs.values_at(rows, T0 + 99 * H), {})
        rows[2][1].pop('RN1')
        self.assertNotIn('precip', fs.values_at(rows, T0 + 1.5 * H))

    def test_span_starts_one_cell_before_first_row(self):
        self.assertEqual(fs.span_of(_rows(3)), (T0 - H, T0 + 2 * H))


class TestRowsForAi(unittest.TestCase):
    def _cells(self, n=4, rain=None):
        series = {'rows': _rows(n, rain=rain)}
        return fs._file_cells(series)

    def test_cell_values_sit_on_the_hour_they_start(self):
        rows = fs.ai_hourly_rows(self._cells(4, rain={1: 4.0, 2: 5.2, 3: 0.2}), 'Asia/Tokyo')
        self.assertEqual([r.get('precipitation (mm)') for r in rows], [4.0, 5.2, 0.2])
        self.assertEqual(len(rows), 3)                       # 마지막 정시는 다음 칸이 없어 빠진다
        self.assertIn('temperature_2m (°C)', rows[0])
        self.assertEqual(rows[0]['temperature_2m (°C)'], 20.0)

    def test_dew_point_and_vpd_are_computed_from_t_and_rh(self):
        r = fs.ai_hourly_rows(self._cells(2), 'Asia/Tokyo')[0]
        self.assertAlmostEqual(r['dew_point_2m (°C)'], 16.4, delta=0.3)
        self.assertAlmostEqual(r['vapour_pressure_deficit (kPa)'], 0.47, delta=0.03)


def _patched(series, daily=None, fallback=None):
    from aot.tests.test_forecast_series_read import patched
    return patched(series, daily, fallback)


class TestSliderUsesDesignatedSource(unittest.TestCase):
    GOT = {'rows': _rows(rain={1: 4.0}), 'input_id': 'in-1', 'source': 'OM', 'fetched_epoch': T0}

    def test_forecast_mode_reads_the_site_series(self):
        with _patched(self.GOT):
            c = fs.candidates('site-1', T0 + 0.5 * H, now=T0)
        self.assertEqual(c['precip'][0]['value'], 4.0)
        self.assertEqual((c['precip'][0]['src'], c['precip'][0]['src_id']), ('field', 'in-1'))

    def test_get_state_forecast_uses_only_the_designated_series(self):
        gis = {'precip': [{'key': 'precip', 'value': 9.0, 'src': 'gis', 'at': None, 'src_id': 'g',
                           'max_age': 0.0, 'exact': False}],
               'visibility': [{'key': 'visibility', 'value': 7.0, 'src': 'gis', 'at': None, 'src_id': 'g',
                               'max_age': 0.0, 'exact': False}]}
        now = T0 - 0.5 * H
        with _patched(self.GOT), patch.object(ws, 'collect_gis_at', return_value=gis) as g, \
                patch.object(ws, 'collect_timeline', return_value={}):
            st = ws.get_state(35.0, 127.0, site='site-1', now=now, t=T0 + 0.5 * H)
        self.assertEqual(st['mode'], 'forecast')
        self.assertEqual(st['items']['precip']['value'], 4.0)
        self.assertNotIn('visibility', st['items'])          # 한 출처 — 지정 계열에 없는 항목을 gis 로 메우지 않는다
        g.assert_not_called()
        self.assertEqual(st['forecast_source']['basis'], 'designated')
        self.assertEqual(st['forecast_source']['segment'], 'hourly')

    def test_without_designation_gis_is_the_common_fallback(self):
        gis = {'precip': [{'key': 'precip', 'value': 9.0, 'src': 'gis', 'at': None, 'src_id': 'g',
                           'max_age': 0.0, 'exact': False}]}
        with _patched(None), patch.object(ws, 'collect_gis_at', return_value=gis):
            st = ws.get_state(35.0, 127.0, site='site-1', now=T0 - 3 * H, t=T0 + 0.5 * H)
        self.assertEqual(st['items']['precip']['value'], 9.0)
        self.assertEqual(st['forecast_source']['basis'], 'map_layer')

    def test_beyond_the_designated_series_is_out_of_range_not_gis(self):
        with _patched(self.GOT), patch.object(ws, 'collect_gis_at', return_value={'precip': []}):
            st = ws.get_state(35.0, 127.0, site='site-1', now=T0, t=T0 + 30 * H)
        self.assertTrue(st['out_of_range'])
        self.assertEqual(st['items'], {})

    def test_timeline_range_covers_the_file_from_now(self):
        got = dict(self.GOT, rows=_rows(6))
        with _patched(got):
            rng = fs.timeline_range('site-1', T0 + 0.5 * H)
        self.assertEqual((rng['start'], rng['end'], rng['step_s']), (T0 + 0.5 * H, T0 + 5 * H, H))


class TestMcpForecastFollowsTheSameSource(_Fixture):
    def _series(self, anchor_epoch, hours=48, rain=None):
        rows = []
        for i in range(hours + 1):
            ep = anchor_epoch + i * H
            rows.append((ep, {'epoch': ep, 'TMP': 21.0, 'REH': 90, 'WSD': 2.0, 'VEC': 10,
                              'RN1': (rain or {}).get(i, 0.0), 'POP': 80, 'CLD': 100, 'SOL': 0}))
        return {'rows': rows, 'input_id': 'in-hourly', 'source': 'Kumamoto 예보 입력',
                'fetched_epoch': anchor_epoch + 0.5 * H, 'model': 'open_meteo',
                'meta': {'grid_latitude': 32.75, 'grid_longitude': 130.69, 'elevation': 4.0}}

    def _anchor(self):
        return (int(self.NOW.timestamp() // H)) * H

    def _patch(self, series, daily=None):
        stack = _patched(series, daily)
        stack.enter_context(patch.object(fs, '_site_tz_name', return_value='Asia/Tokyo'))
        return stack

    def test_designated_site_answers_from_its_input_without_calling_open_meteo(self):
        # 구마모토 10-13 10:41 → 10:00 행이 지금 칸. 비는 파일의 11:00 행(=10~11시 칸) 4.0
        series = self._series(self._anchor(), rain={1: 4.0, 2: 5.2, 3: 0.0})
        with self._patch(series):
            r = S.get_weather_forecast(place='구마모토 농장', hours=6)
        self.assertEqual(r['status'], 'success', r)
        self.assertEqual(self.calls, [])                              # Open-Meteo 직접 호출 없음
        self.assertEqual(r['source_name'], 'Kumamoto 예보 입력')
        self.assertEqual(r['source_basis'], 'designated')
        self.assertEqual([x['precipitation (mm)'] for x in r['forecasts'][:3]], [4.0, 5.2, 0.0])
        self.assertEqual(r['forecasts'][0]['time'][-5:], '10:00')

    def test_place_without_any_source_queries_the_registered_open_meteo(self):
        with self._patch(None):
            r = S.get_weather_forecast(place='김제 농장', hours=6)
        self.assertEqual(r['status'], 'success', r)
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(r['source_basis'], 'coordinate_query')

    def test_short_designated_series_is_cut_not_filled_from_elsewhere(self):
        series = self._series(self._anchor(), hours=6)               # 6시간치뿐
        with self._patch(series):
            r = S.get_weather_forecast(place='구마모토 농장', hours=24)    # 24시간은 못 덮는다
            self.assertEqual(r['status'], 'success', r)
            self.assertEqual(self.calls, [])
            self.assertTrue(r['period'].get('truncated'))
            self.assertIn('Beyond the forecast range', r['note'])
            r = S.get_weather_forecast(hours=6)                          # 장소 없음(농장 기본값) — 대지를 모른다
            self.assertEqual(r['source_basis'], 'coordinate_query')

    def test_days_after_the_hourly_horizon_come_from_the_daily_input(self):
        series = self._series(self._anchor(), hours=24)
        tz = 9 * 3600.0
        today = int((self.NOW.timestamp() + tz) // 86400)
        daily = {'input_id': 'in-daily', 'source': 'Kumamoto 일별', 'fetched_epoch': self._anchor(),
                 'days': {today + k: {'precip_mm': float(k), 'temp_max_c': 20.0 + k, 'temp_min_c': 10.0}
                          for k in range(8)}}
        with self._patch(series, daily):
            r = S.get_weather_forecast(place='구마모토 농장', hours=72)
            self.assertEqual(r['status'], 'success', r)
            self.assertEqual(self.calls, [])
            tail = r['daily_forecasts']
            self.assertEqual(tail[0]['date'], (self.NOW + __import__('datetime').timedelta(days=1)).astimezone(
                __import__('pytz').timezone('Asia/Tokyo')).date().isoformat())
            self.assertEqual(tail[0]['precipitation_sum (mm)'], 1.0)
            self.assertEqual([sg['kind'] for sg in r['source_segments']], ['hourly', 'daily'])
            r = S.get_weather_forecast(place='구마모토 농장', hours=168)      # 먼 날은 일 행
            self.assertTrue(r['period']['daily'])
            self.assertEqual(r['forecasts'][-1]['precipitation_sum (mm)'], 6.0)
            self.assertEqual(self.calls, [])
