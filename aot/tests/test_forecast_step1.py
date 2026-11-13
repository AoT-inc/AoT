# coding=utf-8
"""예보 단일 출처 1단계 — 누적 mm 환산(드라이버 표), 구간 값 계단, 미세 강수 문턱.

구마모토 사례: 지도 '현재' 비가 Open-Meteo 입력의 단위 mm 를 못 읽어 OpenWeather 로 새고,
OpenWeather 3시간 블록 보간이 거의 그친 비를 계속 내리는 모양으로 그렸다.
"""
import time

from aot.space import weather_state as ws


class TestAccumulatedMmFromDriver:
    def test_open_meteo_current_input_mm_is_one_hour_sum(self):
        assert ws.to_standard('precip', 4.0, 'mm', '', 'OPEN_METEO_FORECAST') == 4.0

    def test_driver_period_scales_mm_to_per_hour(self):
        assert ws.to_standard('precip', 0.5, 'mm', '', 'KMA_weather_500') == 2.0       # 15분 합
        assert ws.to_standard('precip', 24.0, 'mm', '', 'OPEN_METEO_DAILY_FORECAST') == 1.0   # 일 합

    def test_unknown_driver_or_none_still_drops_mm(self):
        assert ws.to_standard('precip', 4.0, 'mm', '', 'SOME_RAIN_GAUGE') is None
        assert ws.to_standard('precip', 4.0, 'mm', '') is None

    def test_name_period_wins_over_driver_and_rate_units_unchanged(self):
        assert ws.to_standard('precip', 1.0, 'mm', '강수15분', 'OPEN_METEO_FORECAST') == 4.0
        assert ws.to_standard('precip', 2.0, 'mm/h', '', None) == 2.0


class TestTraceThreshold:
    def _fx(self, p, opts=None):
        return ws.decide_ambient({'precip': {'value': p}}, opts)['fx']['precip']

    def test_below_default_trace_is_no_rain(self):
        assert self._fx(0.09) is False and self._fx(0.1) is True

    def test_no_value_is_false(self):
        assert ws.decide_ambient({})['fx']['precip'] is False

    def test_widget_option_changes_threshold(self):
        assert self._fx(0.3, {'precip_trace_mm_h': 0.5}) is False
        assert self._fx(0.3, {'precip_trace_mm_h': 0.2}) is True

    def test_option_is_parsed_and_range_checked(self):
        assert ws.parse_options({'pt': '0.4'})['precip_trace_mm_h'] == 0.4
        assert ws.parse_options({'pt': '99'})['precip_trace_mm_h'] == ws.OPTION_DEFAULTS['precip_trace_mm_h']


class TestOpenWeatherStepPrecip:
    def _inst(self, items):
        from aot.inputs_gis.gis_openweather import InputModule
        inst = InputModule.__new__(InputModule)
        inst._fetch_forecast = lambda lat, lng: items
        return inst

    def _items(self, t0):
        # 블록 dt = 그 시각까지 직전 3시간 합. 18:00 9 mm, 21:00 3.46, 00:00 0.25
        return [{'dt': t0 + 3 * 3600 * i, 'main': {'temp': 20.0}, 'wind': {'speed': 2.0, 'deg': 10},
                 'clouds': {'all': 100}, 'rain': ({'3h': r} if r else {})}
                for i, r in enumerate((9.0, 3.46, 0.25, 0.0))]

    def test_precip_is_a_step_inside_the_block_not_interpolated(self):
        t0 = 1_800_000_000.0
        inst = self._inst(self._items(t0))
        # 두 번째 블록(dt=t0+3h, 3.46mm)의 구간 안
        v = inst.get_ambient_forecast(0, 0, t0 + 1.5 * 3600)['values']
        assert abs(v['precip'] - 3.46 / 3.0) < 1e-9
        # 마지막 비 블록(0.25) 안에서는 0.25/3 그대로이고 앞뒤로 번지지 않는다
        a = inst.get_ambient_forecast(0, 0, t0 + 6 * 3600 - 60)['values']['precip']
        b = inst.get_ambient_forecast(0, 0, t0 + 6 * 3600 - 3 * 3600 + 60)['values']['precip']
        assert abs(a - 0.25 / 3.0) < 1e-9 and abs(b - 0.25 / 3.0) < 1e-9
        # 다음 블록(비 없음) 구간에는 0
        assert inst.get_ambient_forecast(0, 0, t0 + 6 * 3600 + 60)['values']['precip'] == 0.0

    def test_instant_values_still_interpolate(self):
        t0 = 1_800_000_000.0
        items = self._items(t0)
        items[1]['main']['temp'] = 22.0
        inst = self._inst(items)
        v = inst.get_ambient_forecast(0, 0, t0 + 1.5 * 3600)['values']
        assert abs(v['temp'] - 21.0) < 1e-9
