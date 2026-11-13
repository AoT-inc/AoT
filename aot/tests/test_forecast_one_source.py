# coding=utf-8
"""예보 단일 출처 3단계 — 대지 예보 계열 하나(시간별 뒤 일별)를 트윈·지도 날씨·AI 가 함께 읽는다.

지키는 것:
1. 시간별 지평 뒤는 **그 날의 일 행**이다 — 다른 출처로 메우지 않는다. 일별도 끝나면 '범위 밖'.
2. 일별 입력만 지정된 대지(김제 실험 설치)도 가까운 날부터 일 행으로 읽힌다.
3. 일별 입력이 없으면 시간 칸이 하루를 다 덮는 날만 일 값으로 접는다(모자란 날을 만들지 않는다).
4. 지정이 없으면 셋 다 같은 폴백(지도 날씨 레이어), 응답이 `source_basis` 로 밝힌다.
5. 트윈 노지 모델은 같은 계열의 일 행을 읽는다.
"""
import unittest
from unittest.mock import patch

from aot.space import forecast_series as fs
from aot.space import weather_state as ws
from aot.tests.test_forecast_series_read import patched

H = 3600.0
D = 86400.0
DAY0 = 20_000                                  # UTC 일 번호(시간대 UTC 로 고정)
T0 = DAY0 * D                                  # 그날 00:00


def _hourly(hours=36, anchor=T0):
    rows = []
    for i in range(hours + 1):
        ep = anchor + i * H
        rows.append((ep, {'epoch': ep, 'TMP': 10.0 + (i % 24) * 0.5, 'REH': 70, 'WSD': 2.0, 'VEC': 90,
                          'RN1': 0.5, 'POP': 40, 'CLD': 50, 'SOL': 0}))
    return {'rows': rows, 'input_id': 'in-h', 'source': '시간별 예보', 'fetched_epoch': anchor, 'model': 'm', 'meta': {}}


def _daily(days=8, first=DAY0):
    return {'input_id': 'in-d', 'source': '일별 예보', 'fetched_epoch': T0,
            'days': {first + k: {'precip_mm': float(k), 'temp_max_c': 20.0 + k, 'temp_min_c': 5.0, 'pop_pct': 10.0 * k}
                     for k in range(days)}}


class TestStitching(unittest.TestCase):
    def test_hourly_then_daily_segments_meet_at_the_hourly_horizon(self):
        with patched(_hourly(36), _daily()):
            ser = fs.site_series('site-1', T0 + 600)
            segs = fs.segments_of(ser)
        self.assertEqual([s['kind'] for s in segs], ['hourly', 'daily'])
        self.assertEqual(segs[0]['end'], T0 + 36 * H)
        self.assertEqual(segs[1]['start'], segs[0]['end'])                  # 틈 없이 잇는다
        self.assertEqual(segs[1]['end'], (DAY0 + 8) * D)                     # +7 일 끝
        self.assertEqual(segs[1]['source']['name'], '일별 예보')

    def test_value_after_the_horizon_is_that_days_row_and_beyond_is_out_of_range(self):
        with patched(_hourly(36), _daily()):
            ser = fs.site_series('site-1', T0 + 600)
            near = fs.at_time(ser, T0 + 3.5 * H)
            later = fs.at_time(ser, T0 + 6 * D + 12 * H)
            past = fs.at_time(ser, T0 + 9 * D)
        self.assertEqual(near['segment'], 'hourly')
        self.assertEqual(near['values']['precip_mm_h'], 0.5)
        self.assertEqual(later['segment'], 'daily')
        self.assertEqual((later['daily']['precip_mm'], later['daily']['temp_max_c']), (6.0, 26.0))
        self.assertIsNone(past['segment'])

    def test_daily_only_site_reads_daily_from_today(self):
        with patched(None, _daily()):
            ser = fs.site_series('site-1', T0 + 600)
            rng = fs.timeline_range('site-1', T0 + 600)
            got = fs.at_time(ser, T0 + 5 * H)
        self.assertEqual([s['kind'] for s in fs.segments_of(ser)], ['daily'])
        self.assertEqual(rng['end'], (DAY0 + 8) * D)
        self.assertEqual(got['daily']['date'], fs._date_text(DAY0))

    def test_without_daily_input_only_fully_covered_days_are_folded(self):
        with patched(_hourly(36)):                                          # 오늘 하루 + 내일 12 시간
            ser = fs.site_series('site-1', T0 + 600)
        self.assertEqual(ser['daily']['from'], 'hourly_sum')
        self.assertEqual(list(ser['daily']['days']), [DAY0])
        self.assertAlmostEqual(ser['daily']['days'][DAY0]['precip_mm'], 12.0)    # 24 칸 × 0.5
        self.assertEqual([s['kind'] for s in fs.segments_of(ser)], ['hourly'])    # 접은 날은 시간별 안에 있다

    def test_read_carries_daily_rows_segments_and_basis(self):
        with patched(_hourly(36), _daily()):
            out = fs.read('site-1', now=T0 + 600)
        self.assertEqual(out['source_basis'], 'designated')
        self.assertEqual([s['kind'] for s in out['segments']], ['hourly', 'daily'])
        self.assertEqual(len(out['daily']), 8)
        self.assertEqual(out['daily'][7]['precip_mm'], 7.0)
        self.assertEqual(out['coverage']['end'], (DAY0 + 8) * D)
        self.assertEqual(out['horizon'], T0 + 36 * H)
        with patched(_hourly(36), _daily()):
            self.assertTrue(fs.read('site-1', T0, T0 + 7 * D, now=T0 + 600)['covers_request'])

    def test_no_designation_uses_the_common_map_layer_fallback(self):
        cells = [{'time': T0 + i * 3 * H, 'end': T0 + (i + 1) * 3 * H, 'temp_c': 12.0, 'precip_mm_h': 1.0}
                 for i in range(16)]
        with patched(None, fallback=(cells, {'name': 'OpenWeather 레이어', 'layer_ids': ['g'], 'model': None}, 3 * H)):
            out = fs.read('site-1', now=T0 + 600)
        self.assertEqual(out['source_basis'], 'map_layer')
        self.assertEqual(out['source']['name'], 'OpenWeather 레이어')
        self.assertEqual(out['resolution']['step_s'], 3 * H)
        self.assertEqual(out['daily'][0]['precip_mm'], 24.0)                 # 8 칸 × 3 h × 1 mm/h
        self.assertEqual(out['daily_from'], 'hourly_sum')


class TestMapDock(unittest.TestCase):
    def test_daily_segment_gives_the_days_values_and_says_so(self):
        with patched(_hourly(36), _daily()), patch.object(ws, 'collect_gis_at') as g:
            st = ws.get_state(35.8, 126.9, site='site-1', now=T0 + 600, t=T0 + 6 * D + 12 * H)
        g.assert_not_called()
        self.assertEqual(st['items'], {})
        self.assertEqual(st['daily']['precip_mm'], 6.0)
        self.assertEqual(st['forecast_source']['segment'], 'daily')
        self.assertEqual([s['kind'] for s in st['forecast_source']['segments']], ['hourly', 'daily'])
        self.assertNotIn('out_of_range', st)

    def test_timeline_reports_the_designated_range_and_source(self):
        with patched(_hourly(36), _daily()), patch.object(ws, '_ordered_gis_layers', return_value=[]):
            tl = ws.collect_timeline('site-1', T0 + 600)
        self.assertEqual(tl['forecast']['end_ms'], int((DAY0 + 8) * D * 1000))
        self.assertEqual(tl['forecast_source']['basis'], 'designated')


class TestTwinFieldReadsTheSameSeries(unittest.TestCase):
    def test_daily_rows_become_the_field_forecast(self):
        from aot.twin.models.field_bucket import _series_forecast
        from aot.twin.types import ForecastSeries
        with patched(_hourly(36), _daily()):
            data = fs.read('site-1', now=T0 + 600)

        class Src:
            def read_forecast(self, site, t0, t1, variables=None):
                return ForecastSeries.from_response(data)

        notes = []
        fc = _series_forecast(Src(), 'site-1', T0 + 600, 0.0, DAY0, notes)
        self.assertEqual(fc.rain_mm[DAY0 + 7], 7.0)
        self.assertEqual(fc.t_mean[DAY0 + 1], 0.5 * (21.0 + 5.0))
        self.assertTrue(any('일별 예보' in n and '지정' in n for n in notes))


if __name__ == '__main__':
    unittest.main()


class TestSiteBlockForScreens(unittest.TestCase):
    """트윈 탭·기상원 지정 화면이 함께 쓰는 묶음 — 시간별만 지정한 대지도 트윈이 쓸 날 수를 밝힌다."""

    def test_hourly_only_site_reports_the_days_the_twin_can_use(self):
        with patched(_hourly(36)), patch.object(fs, 'forecast_candidates', return_value=[{'device_id': 'in-1'}]):
            b = fs.site_forecast_block('site-1', T0 + 600)
        self.assertEqual(b['selected'], ['in-1'])
        self.assertEqual((b['days'], b['daily_from']), (1, 'hourly_sum'))          # 하루가 다 덮인 날만
        self.assertEqual([s['kind'] for s in b['segments']], ['hourly'])

    def test_hourly_then_daily_site_reports_eight_days(self):
        with patched(_hourly(36), _daily()), patch.object(fs, 'forecast_candidates', return_value=[]):
            b = fs.site_forecast_block('site-1', T0 + 600)
        self.assertEqual((b['days'], b['daily_from']), (8, 'daily_input'))
        self.assertEqual([s['kind'] for s in b['segments']], ['hourly', 'daily'])
