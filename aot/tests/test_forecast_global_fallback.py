# coding=utf-8
"""get_weather_forecast 의 Open-Meteo 예보, 그리고 query() 의 meta 분리.

예보는 Open-Meteo 하나다(forecast.json 은 읽지 않는다). 출처·모델 격자 좌표를
응답에 싣고, 출처가 없으면 추가 안내 한 줄을 낸다. DB·망·create_app 없음.
"""
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from aot.tools.aot_data_tool_service import AoTDataToolService as S

_FEED = 'aot.functions.utils.env_control.forecast_feedforward._load_forecast'


def _provider(describe, query_result):
    svc = MagicMock()
    svc.describe_all.return_value = describe
    svc.query.return_value = query_result
    prov = MagicMock()
    prov.get.return_value = svc
    return prov, svc


_OM = [{'source_id': 'src-om', 'label': 'SIM 김제', 'preset': 'ext_openmeteo'}]
_GET = 'aot.ai.context.ext.openmeteo_forecast_cache.get_bundle'
_SEOUL = {'name': 'farm default', 'kind': 'farm', 'id': None, 'lat': 35.8,
          'lon': 126.9, 'tz': 'Asia/Seoul', 'basis': 'default',
          'coord_source': 'system'}


def _bundle(hours, tz='Asia/Seoul'):
    return {'meta': {'grid_latitude': 35.86, 'grid_longitude': 126.88,
                     'elevation_m': 12.0, 'timezone': tz},
            'hourly': [{'time': h, 'temperature_2m (°C)': float(i)}
                       for i, h in enumerate(hours)],
            'daily': []}


_NOW = (2099, 10, 12, 2, 10)          # 서울 11:10
_INFO = {'from': 'live', 'fetched_at': 0.0, 'age_min': 0, 'stale': False}


def _run(bundle, now=None, hours=24, place=_SEOUL, found='om'):
    """출처·장소·예보 묶음을 가짜로 두고 도구를 부른다. (결과, get_bundle 모의)."""
    prov, svc = _provider(_OM, (None, None))
    svc.source_api_key.return_value = ''
    src = {"kind": "data_source", "svc": svc, "src": _OM[0]}
    ctx = [patch.object(S, '_open_meteo_forecast_source', return_value=src),
           patch.object(S, '_forecast_place', return_value=dict(place)),
           patch(_GET, return_value=(bundle, _INFO, None)) if bundle else
           patch(_GET, return_value=(None, None, 'connect_error'))]
    if now:
        ctx.append(patch('aot.utils.timekit.utc_now',
                         return_value=datetime(*now, tzinfo=timezone.utc)))
    mocks = []
    for c in ctx:
        mocks.append(c.start())
    try:
        r = S.get_weather_forecast(hours=hours)
    finally:
        for c in ctx:
            c.stop()
    return r, mocks[2]


class TestGetWeatherForecast:
    def test_reads_openmeteo_and_labels_the_grid_point(self):
        r, get = _run(_bundle(['2099-10-12T12:00', '2099-10-12T13:00']), now=_NOW)
        assert r['status'] == 'success', r
        assert r['source'] == 'open_meteo'
        assert r['source_name'] == 'SIM 김제' and r['source_ref'] == 'src-om'
        assert r['latitude'] == 35.86 and r['longitude'] == 126.88
        assert r['forecasts'][0]['hour_offset'] > 0  # 먼 미래 행: 지난 칸이 아니다
        # 출처는 화면이 표시한다 — AI 가 답변에 되풀이하지 않도록 응답에는 싣지 않는다
        assert not {'attribution', 'attribution_note', 'source_url'} & set(r)
        for k in ('fallback_from', 'fallback_reason', 'source_choice'):
            assert k not in r
        # 좌표·시간대는 장소에서 온다
        assert get.call_args[0][:3] == (35.8, 126.9, 'Asia/Seoul')

    def test_operator_attribution_stays_off_the_response_but_caveat_travels(self):
        prov, svc = _provider(_OM, (None, None))
        svc.source_api_key.return_value = ''
        svc.source_config.return_value = {'attribution': '날씨 자료: Open-Meteo (운영자)',
                                          'caveat': '격자 값'}
        src = {"kind": "data_source", "svc": svc, "src": _OM[0]}
        with patch.object(S, '_open_meteo_forecast_source', return_value=src), \
             patch.object(S, '_forecast_place', return_value=dict(_SEOUL)), \
             patch('aot.utils.timekit.utc_now',
                   return_value=datetime(*_NOW, tzinfo=timezone.utc)), \
             patch(_GET, return_value=(_bundle(['2099-10-12T12:00']), _INFO, None)):
            r = S.get_weather_forecast()
        assert 'attribution' not in r and 'attribution_note' not in r
        assert r['caveat'] == '격자 값'

    def test_never_reads_forecast_json(self):
        with patch(_FEED, side_effect=AssertionError('forecast.json read')):
            r, _ = _run(_bundle(['2099-10-12T12:00']), now=_NOW)
        assert r['status'] == 'success'

    def test_no_source_says_to_add_the_input(self):
        prov, _ = _provider([], (None, None))
        with patch('aot.tools.providers', prov), \
             patch.object(S, '_open_meteo_forecast_source', return_value=None):
            r = S.get_weather_forecast()
        assert r['status'] == 'unavailable'
        assert 'OPEN_METEO_FORECAST' in r['forecast_hint']
        assert 'KMA' not in r['message']

    def test_query_error_is_unavailable(self):
        r, _ = _run(None)
        assert r['status'] == 'unavailable'
        assert 'KMA' not in r['message']

    def test_input_with_coordinates_is_a_source(self):
        inp = MagicMock(latitude=35.8, longitude=126.9, unique_id='in-1')
        inp.name = 'OM input'
        with patch('aot.tools.data_tools.measurement.Input') as I, \
             patch.object(S, '_open_meteo_forecast_source',
                          return_value={"kind": "input", "input": inp,
                                        "svc": MagicMock()}), \
             patch.object(S, '_forecast_place', return_value=dict(_SEOUL)), \
             patch('aot.utils.timekit.utc_now', return_value=datetime(*_NOW, tzinfo=__import__('datetime').timezone.utc)), \
             patch(_GET, return_value=(_bundle(['2099-10-12T12:00']), _INFO, None)):
            I.query.filter.return_value.first.return_value = inp
            r = S.get_weather_forecast()
        assert r['status'] == 'success' and r['source_ref'] == 'in-1'
        assert 'attribution' not in r

    def test_forecast_input_hint_only_when_nothing_exists(self):
        prov, _ = _provider([], (None, None))
        with patch('aot.tools.providers', prov), \
             patch.object(S, '_open_meteo_forecast_source', return_value=None):
            assert 'OPEN_METEO_FORECAST' in S.forecast_input_hint()
        prov, _ = _provider(_OM, (None, None))
        with patch('aot.tools.providers', prov):
            assert S.forecast_input_hint() is None

    def test_a_coordinate_input_counts_as_a_source(self):
        # 좌표를 가진 입력도 출처다(힌트가 비어 있다)
        inp = MagicMock(latitude=35.8, longitude=126.9, is_activated=True)
        prov, _ = _provider([], (None, None))
        with patch('aot.tools.providers', prov), \
             patch('aot.tools.data_tools.measurement.Input') as I:
            I.query.filter.return_value.first.return_value = inp
            assert S._open_meteo_forecast_source()['kind'] == 'input'


class TestHourOffsetFromNow:
    """hour_offset 0 = 지금 시간 칸, 지난 칸 제외 — 시간대 경계 포함."""

    def _run(self, now_utc, tz, hours):
        place = dict(_SEOUL, tz=tz)
        r, _ = _run(_bundle(hours, tz), now=now_utc, hours=4, place=place)
        return r

    def test_past_hours_dropped_and_current_slot_is_zero_in_kst(self):
        # 서버는 UTC 10-12 21:41 = 서울 10-13 06:41 (날짜가 다르다)
        r = self._run((2026, 10, 12, 21, 41), 'Asia/Seoul',
                      ['2026-10-13T04:00', '2026-10-13T05:00', '2026-10-13T06:00',
                       '2026-10-13T07:00', '2026-10-13T08:00'])
        assert [f['hour_offset'] for f in r['forecasts']] == [0, 1, 2]
        assert r['forecasts'][0]['time'] == '2026-10-13T06:00'

    def test_negative_offset_zone_midnight_boundary(self):
        # UTC 10-13 06:30 = 로스앤젤레스 10-12 23:30 → 지금 칸은 23:00
        r = self._run((2026, 10, 13, 6, 30), 'America/Los_Angeles',
                      ['2026-10-12T22:00', '2026-10-12T23:00', '2026-10-13T00:00'])
        assert [f['time'] for f in r['forecasts']] == [
            '2026-10-12T23:00', '2026-10-13T00:00']
        assert [f['hour_offset'] for f in r['forecasts']] == [0, 1]

    def test_all_past_rows_is_unavailable_not_stale_data(self):
        r = self._run((2026, 10, 14, 0, 0), 'Asia/Seoul',
                      ['2026-10-13T04:00', '2026-10-13T05:00'])
        assert r['status'] == 'unavailable'

    def test_request_goes_out_with_the_places_timezone(self):
        r, get = _run(_bundle(['2099-10-12T12:00']), hours=6,
                      place=dict(_SEOUL, tz='Asia/Tokyo'))
        assert get.call_args[0][2] == 'Asia/Tokyo'


class TestForecastHintFreshness:
    def test_registered_but_switched_off_input_has_its_own_line(self):
        inp = MagicMock(latitude=35.8, longitude=126.9, is_activated=False)
        prov, _ = _provider([], (None, None))
        with patch('aot.tools.providers', prov), \
             patch('aot.tools.data_tools.measurement.Input') as I:
            I.query.filter.return_value.first.return_value = inp
            hint = S.forecast_input_hint()
        assert hint and '꺼져' in hint and '예보 입력 없음' not in hint

    def test_running_input_gives_no_hint(self):
        inp = MagicMock(latitude=35.8, longitude=126.9, is_activated=True)
        prov, _ = _provider([], (None, None))
        with patch('aot.tools.providers', prov), \
             patch('aot.tools.data_tools.measurement.Input') as I:
            I.query.filter.return_value.first.return_value = inp
            assert S.forecast_input_hint() is None


class TestQueryMetaSeparation:
    def _run(self, limit):
        from aot.ai.services import data_source_query_service as q
        src = MagicMock(source_id='s', source_ref='s')
        src.source_name = 'OM'
        rows = [{'time': 't%d' % i, 'v': i} for i in range(5)]
        head = {'grid_latitude': 35.8, 'elevation_m': 3.0}
        fetch = lambda op, params, operations=None: ([head] + rows, None)
        with patch.object(q, '_sources', return_value=[(src, {'preset_key': 'ext_openmeteo'})]), \
             patch.object(q, '_client_for', return_value=(None, fetch)), \
             patch.object(q, '_operations', return_value={'forecast_daily': {'params': []}}):
            return q.query('s', 'forecast_daily', limit=limit)

    def test_head_row_does_not_eat_the_limit(self):
        payload, err = self._run(3)
        assert err is None
        assert [r['v'] for r in payload['rows']] == [0, 1, 2]
        assert payload['total_available'] == 5
        assert payload['meta'] == {'grid_latitude': 35.8, 'elevation_m': 3.0}
