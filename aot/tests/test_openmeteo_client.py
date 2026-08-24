# coding=utf-8
"""Open-Meteo 클라이언트(EXT-GL-02) — 망을 타지 않는 부분의 계약.

fetch_operation 자체는 실제 API 로 검증했다(2026-08-25: ET0·토양 4깊이·
VPD·archive 월별집계 전부 실측). 여기서 지키는 것은 그 실측이 **조용히
깨지는 방식들**이다 — 단위가 사라지거나, 선택 파라미터가 질의로 새거나,
이틀치 예보가 오늘까지로 잘리는 것.
"""
import unittest

from aot.ai.context.ext import openmeteo_client as om


class TestRequestBuilding(unittest.TestCase):
    def test_required_coords_are_enforced(self):
        with self.assertRaises(ValueError) as ctx:
            om.build_request('soil', {'latitude': '35.8'})
        self.assertIn('longitude', str(ctx.exception))

    def test_unknown_operation_raises_keyerror(self):
        """smartfarmkorea_client.build_url 과 같은 오류 계약 —
        data_source_query_service 가 두 계열을 한 갈래로 처리한다."""
        with self.assertRaises(KeyError):
            om.build_request('no_such_op', {'latitude': '1', 'longitude': '2'})

    def test_client_side_options_never_leak_into_the_query(self):
        """step 은 우리가 응답을 솎을 때 쓰는 값이다. 질의문자열에 섞이면
        Open-Meteo 가 모르는 파라미터로 400 을 돌려준다."""
        _, query = om.build_request('soil', {'latitude': '1', 'longitude': '2', 'step': '6'})
        self.assertNotIn('step', query)
        self.assertIn('forecast_days', query)

    def test_timezone_is_auto(self):
        """UTC 로 받으면 '내일 아침' 이 어긋난다."""
        _, query = om.build_request('forecast_daily', {'latitude': '1', 'longitude': '2'})
        self.assertEqual(query['timezone'], 'auto')

    def test_api_key_switches_to_the_commercial_host(self):
        """무료 엔드포인트는 약관상 비상업 전용이다. 키를 넣은 설치는
        상업 엔드포인트로 가야 한다 — 안 그러면 키를 넣고도 약관을 어긴다."""
        free, _ = om.build_request('soil', {'latitude': '1', 'longitude': '2'})
        paid, query = om.build_request('soil', {'latitude': '1', 'longitude': '2', 'apikey': 'K'})
        self.assertTrue(free.startswith('https://api.open-meteo.com'))
        self.assertTrue(paid.startswith('https://customer-api.open-meteo.com'))
        self.assertEqual(query['apikey'], 'K')

    def test_archive_has_its_own_commercial_host_mapping(self):
        """archive-api 는 호스트가 달라서 같은 replace 로는 안 바뀐다."""
        paid, _ = om.build_request('climate_history', {
            'latitude': '1', 'longitude': '2',
            'start_date': '2025-01-01', 'end_date': '2025-01-31', 'apikey': 'K'})
        self.assertTrue(paid.startswith('https://customer-api.open-meteo.com'))
        self.assertIn('/archive', paid)


class TestRowShaping(unittest.TestCase):
    _PAYLOAD = {
        'latitude': 35.8, 'longitude': 126.875, 'elevation': 18.0, 'timezone': 'Asia/Seoul',
        'hourly_units': {'time': 'iso8601', 'soil_moisture_3_to_9cm': 'm³/m³'},
        'hourly': {'time': ['2026-08-25T00:00', '2026-08-25T01:00'],
                   'soil_moisture_3_to_9cm': [0.268, None]},
    }

    def test_units_are_written_into_the_column_name(self):
        """0.268 을 26.8% 로 읽는 사고는 단위가 없으면 반드시 난다."""
        rows = om._rows_from_block(self._PAYLOAD, 'hourly')
        self.assertIn('soil_moisture_3_to_9cm (m³/m³)', rows[0])
        self.assertEqual(rows[0]['soil_moisture_3_to_9cm (m³/m³)'], 0.268)

    def test_missing_values_are_dropped_not_rendered_as_none(self):
        rows = om._rows_from_block(self._PAYLOAD, 'hourly')
        self.assertEqual(list(rows[1]), ['time'])

    def test_empty_block_yields_no_rows(self):
        self.assertEqual(om._rows_from_block({'hourly': {}}, 'hourly'), [])


class TestSampling(unittest.TestCase):
    def test_the_last_row_always_survives(self):
        """기간의 끝을 잘라 버리면 '모레까지 비' 가 '내일까지 비' 가 된다."""
        rows = [{'time': i} for i in range(10)]
        out = om._sample(rows, 3)
        self.assertEqual(out[-1], rows[-1])

    def test_step_one_is_a_passthrough(self):
        rows = [{'time': i} for i in range(5)]
        self.assertEqual(om._sample(rows, 1), rows)

    def test_garbage_step_does_not_raise(self):
        rows = [{'time': i} for i in range(5)]
        self.assertEqual(om._sample(rows, 'abc'), rows)

    def test_two_days_of_hourly_fits_under_the_query_row_cap(self):
        """48행을 그대로 두면 조회 상한(25행)에 걸려 오늘까지만 남는다 —
        '내일 아침 추워지나' 가 정확히 잘려 나가는 자리다."""
        from aot.ai.services.data_source_query_service import _MAX_LIMIT
        rows = [{'time': i} for i in range(48)]
        step = int(om.OPERATIONS['forecast_hourly']['client_optional']['step'])
        # +1: fetch_operation 이 맨 앞에 격자 정보 행을 붙인다.
        self.assertLessEqual(len(om._sample(rows, step)) + 1, _MAX_LIMIT)


class TestMonthlyAggregation(unittest.TestCase):
    def _rows(self):
        return [
            {'time': '2025-11-01', 'temperature_2m_max (°C)': 14.0,
             'temperature_2m_min (°C)': 5.0, 'precipitation_sum (mm)': 10.0,
             'et0_fao_evapotranspiration (mm)': 1.0},
            {'time': '2025-11-02', 'temperature_2m_max (°C)': 16.0,
             'temperature_2m_min (°C)': -1.9, 'precipitation_sum (mm)': 0.0,
             'et0_fao_evapotranspiration (mm)': 2.0},
            {'time': '2025-12-01', 'temperature_2m_max (°C)': 5.0,
             'temperature_2m_min (°C)': -4.0, 'precipitation_sum (mm)': 3.0,
             'et0_fao_evapotranspiration (mm)': 0.5},
        ]

    def test_months_are_folded_and_ordered(self):
        out = om._aggregate_monthly(self._rows())
        self.assertEqual([r['month'] for r in out], ['2025-11', '2025-12'])
        self.assertEqual(out[0]['days'], 2)

    def test_frost_is_reported_by_extremes_not_the_mean(self):
        """11월 평균 최저기온은 영상(1.55°C)이지만 서리는 내렸다.
        평균만 내면 '서리 없음' 으로 읽힌다."""
        out = om._aggregate_monthly(self._rows())
        nov = out[0]
        self.assertGreater(nov['mean_tmin (°C)'], 0)
        self.assertEqual(nov['min_tmin (°C)'], -1.9)
        self.assertEqual(nov['days_below_0C'], 1)

    def test_totals_are_sums_not_averages(self):
        out = om._aggregate_monthly(self._rows())
        self.assertEqual(out[0]['precip_total (mm)'], 10.0)
        self.assertEqual(out[0]['et0_total (mm)'], 3.0)

    def test_rows_without_a_month_are_ignored(self):
        self.assertEqual(om._aggregate_monthly([{'time': ''}]), [])


class TestFamilyDispatch(unittest.TestCase):
    """data_source_query_service 가 두 소스 계열을 갈라 보내는지."""

    def test_openmeteo_is_queryable_without_an_api_key(self):
        """무료 엔드포인트는 키를 요구하지 않는다. 키를 강제하면 아무도 못 쓴다."""
        from aot.ai.services.data_source_query_service import _FAMILIES
        self.assertFalse(_FAMILIES['openmeteo']['key_required'])
        self.assertTrue(_FAMILIES['smartfarmkorea']['key_required'])

    def test_each_family_routes_to_its_own_client(self):
        from aot.ai.services.data_source_query_service import _client_for
        ops_for, fetch = _client_for('openmeteo')
        self.assertIn('soil', ops_for('openmeteo'))
        self.assertIs(fetch, om.fetch_operation)

        ops_for_sfk, fetch_sfk = _client_for('smartfarmkorea_outdoor')
        self.assertIn('identity', ops_for_sfk('smartfarmkorea_outdoor'))
        self.assertIsNot(fetch_sfk, om.fetch_operation)


if __name__ == '__main__':
    unittest.main()
