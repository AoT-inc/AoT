# coding=utf-8
"""값 조회(measure.latest·history)는 게이지·미니그래프 카드를 서버가 직접 올린다 — 사용자 결정 2026-11-06.

고정하는 계약:
  1. 외부 연결의 measure.latest(장치 현재값)는 게이지, measure.history(짧은 이력)는 spark 타일을 서버가 올린다.
     올리는 길은 AI 와 같다(screen_action action=post, attach=[*.viz]). 텍스트 응답은 병행(그대로 둔다).
  2. 서버가 만든 타일은 언제나 `parse_viz_spec` 을 통과하는 올바른 스펙이다(렌더러가 받는 모양).
  3. 눈금을 모르는 측정 항목·구역 요약(한 값이 아님)·실패한 조회에는 타일을 만들지 않는다 — 그때는 글만 남는다.
  4. dict 본문에는 `card`(state posted|already_shown|skipped)를 싣고 옛 안내(card_hint)를 뗀다. 인앱·자동 꺼짐·
     화면 꺼짐은 올리지 않는다(`server_card.skip_reason` 과 같은 문).
"""
import json
import unittest
from unittest import mock

from aot.utils import ai_card_files as files
from aot.tools.domain import server_viz


def _out(body):
    return [{'type': 'text', 'text': json.dumps(body, ensure_ascii=False)}]


_READING = {"status": "success", "device_id": "d1", "name": "3포장 온습도",
            "measurement": "temperature", "timestamp": "2026-11-06T10:00:00+09:00",
            "value": 26.4, "unit": "°C"}

_HISTORY = [{"device_name": "3포장 온습도", "device_kind": "input", "measurement": "temperature",
             "readings": [{"t": "t1", "v": 22.0, "u": "°C"}, {"t": "t2", "v": 24.5, "u": "°C"},
                          {"t": "t3", "v": 26.4, "u": "°C"}],
             "total_readings": 3, "stats": {"min": 22.0, "max": 26.4, "avg": 24.3, "count": 3}}]


class BuildTest(unittest.TestCase):

    def test_latest_single_is_a_gauge(self):
        title, msg, tiles = server_viz._build('gauge', dict(_READING))
        self.assertEqual('3포장 온습도 reading', title)
        self.assertEqual(1, len(tiles))
        self.assertEqual('gauge', tiles[0]['viz'])
        self.assertEqual(26.4, tiles[0]['value'])
        self.assertEqual('26.4', tiles[0]['valueText'])      # 숫자만 — 단위는 unit 칸
        self.assertEqual('°C', tiles[0]['unit'])
        self.assertLess(tiles[0]['min'], tiles[0]['max'])
        self.assertIn('Temperature', tiles[0]['label'])

    def test_multichannel_latest_is_several_gauges(self):
        body = dict(_READING, channels=[
            {"measurement": "temperature", "value": 26.4, "unit": "°C"},
            {"measurement": "humidity", "value": 61.0, "unit": "%"},
            {"measurement": "battery", "value": 88.0, "unit": "%"}])
        _t, _m, tiles = server_viz._build('gauge', body)
        self.assertEqual(3, len(tiles))
        self.assertEqual([0.0, 100.0], [tiles[1]['min'], tiles[1]['max']])   # humidity 0–100

    def test_history_single_is_a_spark(self):
        title, _m, tiles = server_viz._build('spark', [dict(r) for r in _HISTORY])
        self.assertEqual(1, len(tiles))
        self.assertEqual('spark', tiles[0]['viz'])
        self.assertEqual([22.0, 24.5, 26.4], tiles[0]['points'])
        self.assertEqual('26.4', tiles[0]['valueText'])      # 숫자만 — 단위는 unit 칸(머리줄에 '°C °C' 로 겹치지 않게)

    def test_history_single_target_results_wrapper(self):
        # 실제 measure.history 단수 대상 모양 — {results: [채널행]} (각 행에 readings 직접).
        body = {"status": "success", "results": [dict(_HISTORY[0], readings=[
            {"t": "a", "v": 22.0, "u": "C"}, {"t": "b", "v": 23.0, "u": "C"}])]}
        _t, _m, tiles = server_viz._build('spark', body)
        self.assertEqual(1, len(tiles))
        self.assertEqual('spark', tiles[0]['viz'])
        self.assertEqual('°C', tiles[0]['unit'])             # 원문 "C" → 표시 "°C"

    def test_unknown_measurement_makes_no_gauge(self):
        body = dict(_READING, measurement="mystery_index", value=7.0, unit="x")
        self.assertIsNone(server_viz._build('gauge', body))

    def test_zone_summary_shape_makes_nothing(self):
        # get_zone_sensor_summary 모양 — 한 값이 아니다(top-level value 없음).
        body = {"status": "success", "zones": [{"name": "A", "sensors": {}}]}
        self.assertIsNone(server_viz._build('gauge', body))

    def test_fahrenheit_temperature_scale_shifts(self):
        body = dict(_READING, value=79.5, unit="°F")
        _t, _m, tiles = server_viz._build('gauge', body)
        self.assertGreater(tiles[0]['max'], 100)             # 45°C → 113°F 쪽 눈금

    def test_value_outside_scale_widens_not_pins(self):
        body = dict(_READING, measurement="temperature", value=60.0, unit="°C")
        _t, _m, tiles = server_viz._build('gauge', body)
        self.assertGreaterEqual(tiles[0]['max'], 60.0)

    def test_history_downsamples_to_cap(self):
        many = [{"device_name": "x", "measurement": "temperature",
                 "readings": [{"t": str(i), "v": float(i), "u": "°C"} for i in range(200)],
                 "stats": {}}]
        _t, _m, tiles = server_viz._build('spark', many)
        self.assertLessEqual(len(tiles[0]['points']), files.VIZ_MAX_POINTS)
        self.assertEqual(199.0, tiles[0]['points'][-1])      # 최신값은 보존

    def test_multi_target_latest_is_one_gauge_each(self):
        body = {"count": 2, "results": [
            dict(_READING, requested="3포장"),
            dict(_READING, requested="1포장", name="1포장 온습도", value=19.1)]}
        _t, _m, tiles = server_viz._build('gauge', body)
        self.assertEqual(2, len(tiles))
        self.assertEqual([26.4, 19.1], [t['value'] for t in tiles])

    def test_every_built_tile_passes_parse_viz_spec(self):
        for kind, body in (('gauge', dict(_READING)), ('spark', [dict(r) for r in _HISTORY])):
            _t, _m, tiles = server_viz._build(kind, body)
            for spec in tiles:
                files.parse_viz_spec(json.dumps(spec))        # raises FileError if invalid


class GateTest(unittest.TestCase):
    _CTX = {'scope_user_uuid': 'u', 'transport': 'mcp_http', 'tool_profile': None}

    def _post_for(self, body, op='latest', ctx=None, show=None, auto=True, posted=None):
        calls = []

        def fake_execute(app, name, args, **kw):
            calls.append((name, dict(args)))
            return _out(posted if posted is not None else {"status": "posted", "card": "abcd1234"})
        with mock.patch('aot.tools.tool_execution._execute_tool', fake_execute), \
                mock.patch('aot.utils.ai_screen_cards.card_auto_enabled', lambda: auto):
            got = server_viz.post_for(None, 'measure', op, _out(body), ctx or self._CTX, show)
        return json.loads(got[0]['text']), calls

    def test_latest_posts_a_viz_card_and_drops_the_hint(self):
        body, calls = self._post_for(dict(_READING, card_hint="show one card now."))
        self.assertEqual(1, len(calls))
        self.assertEqual('post', calls[0][1]['action'])
        attach = calls[0][1]['attach']
        self.assertTrue(attach and attach[0]['name'].endswith('.viz'))
        self.assertEqual('gauge', json.loads(attach[0]['text'])['viz'])
        self.assertEqual({'state': 'posted', 'title': '3포장 온습도 reading'}, body['card'])
        self.assertNotIn('card_hint', body)

    def test_history_list_body_posts_but_leaves_body(self):
        body, calls = self._post_for([dict(r) for r in _HISTORY], op='history')
        self.assertEqual(1, len(calls))
        self.assertEqual('spark', json.loads(calls[0][1]['attach'][0]['text'])['viz'])
        self.assertIsInstance(body, list)                    # list 본문은 그대로

    def test_setting_off_posts_nothing(self):
        body, calls = self._post_for(dict(_READING), auto=False)
        self.assertEqual([], calls)
        self.assertEqual('card_auto_off', body['card']['reason'])

    def test_in_app_is_not_this_exit(self):
        body, calls = self._post_for(dict(_READING, card_hint="x"),
                                     ctx={'scope_user_uuid': 'u', 'transport': None})
        self.assertEqual([], calls)
        self.assertNotIn('card', body)
        self.assertIn('card_hint', body)

    def test_failed_lookup_posts_nothing(self):
        body, calls = self._post_for({"status": "error", "message": "No data"})
        self.assertEqual([], calls)
        self.assertNotIn('card', body)

    def test_nothing_to_show_says_so(self):
        body, calls = self._post_for({"status": "success", "zones": []})
        self.assertEqual([], calls)
        self.assertEqual('nothing_to_show', body['card']['reason'])

    def test_auto_cards_leave_the_rest_of_the_inbox_limit_to_the_ai(self):
        # 26-11-08 실사용: 하루씩 나눈 이력 조회 7번 → 자동 카드 7장이 수신함 분당 한도(6)를 다 써 AI 의 요약 카드가 막혔다.
        from aot.tools.domain import server_card
        got = [self._post_for([dict(r) for r in _HISTORY], op='history')[1] for _ in range(server_card.AUTO_PER_MIN)]
        self.assertEqual([1] * server_card.AUTO_PER_MIN, [len(c) for c in got])
        body, calls = self._post_for(dict(_READING))
        self.assertEqual([], calls)
        self.assertEqual({'state': 'skipped', 'reason': 'auto_card_budget'}, body['card'])
        self.assertNotIn('next', body)                       # AI 에게 대신 올리라고 하지 않는다

    def test_the_budget_is_per_user_and_frees_after_a_minute(self):
        from aot.tools.domain import server_card
        for _ in range(server_card.AUTO_PER_MIN):
            self.assertTrue(server_card.take_auto_slot('a', now=100.0))
        self.assertFalse(server_card.take_auto_slot('a', now=130.0))
        self.assertTrue(server_card.take_auto_slot('b', now=130.0))
        self.assertTrue(server_card.take_auto_slot('a', now=161.0))


class ComfortBandTest(unittest.TestCase):
    """게이지 녹색(okMin/okMax)은 구획(시설 코디네이터)이 정한 적정 밴드가 먼저다 — 사용자 결정
    2026-11-06. 범위가 분명한 온도·습도만 그 길로 녹색을 받고, 단일 목표(vpd·co2)는 받지 않는다.
    구획이 범위를 못 주면 아래 `DisplayBandTest` 의 지도 밴드로 내려간다(여기서는 그 길을 끈다)."""

    def _build_with_ranges(self, body, ranges, display=None):
        with mock.patch(
                'aot.aot_flask.geo.coordinator_plot.comfort_ranges_for_device',
                return_value=ranges), \
             mock.patch.object(server_viz, '_display_bands', return_value=display or {}):
            return server_viz._build('gauge', body)

    def test_temperature_and_humidity_gauges_get_the_band(self):
        body = dict(_READING, channels=[
            {"measurement": "temperature", "value": 26.4, "unit": "°C"},
            {"measurement": "humidity", "value": 61.0, "unit": "%"},
            {"measurement": "battery", "value": 88.0, "unit": "%"}])
        _t, _m, tiles = self._build_with_ranges(
            body, {'temperature': (22.0, 28.0), 'relative_humidity': (55.0, 75.0)})
        temp, hum, batt = tiles
        self.assertEqual((22.0, 28.0), (temp['okMin'], temp['okMax']))
        self.assertEqual((55.0, 75.0), (hum['okMin'], hum['okMax']))
        self.assertNotIn('okMin', batt)          # 배터리엔 적정 밴드가 없다

    def test_band_is_clamped_into_the_scale(self):
        spec = server_viz._gauge_from('T', 26.4, '°C', 'temperature', ok=(-50.0, 999.0))
        self.assertEqual(spec['okMin'], spec['min'])
        self.assertEqual(spec['okMax'], spec['max'])

    def test_band_reversed_input_is_sorted(self):
        spec = server_viz._gauge_from('T', 26.4, '°C', 'temperature', ok=(28.0, 22.0))
        self.assertLess(spec['okMin'], spec['okMax'])

    def test_fahrenheit_gauge_converts_the_band(self):
        self.assertEqual((68.0, 86.0),
                         server_viz._band_for({'temperature': (20.0, 30.0)},
                                              'temperature', '°F'))

    def test_single_target_measurements_get_no_band(self):
        # vpd·co2 는 단일 목표라 범위가 아니다 — comfort_ranges 가 내지 않으니 녹색도 없다.
        self.assertIsNone(server_viz._band_for(
            {'temperature': (22.0, 28.0)}, 'vapour_pressure_deficit', 'kPa'))
        self.assertIsNone(server_viz._band_for(
            {'temperature': (22.0, 28.0)}, 'co2', 'ppm'))

    def test_no_coordinator_means_no_band(self):
        body = dict(_READING)
        _t, _m, tiles = self._build_with_ranges(body, {})
        self.assertNotIn('okMin', tiles[0])      # 빈 범위 → 게이지만, 녹색 없음
        self.assertEqual('gauge', tiles[0]['viz'])

    def test_ranges_resolved_once_per_device(self):
        body = dict(_READING, channels=[
            {"measurement": "temperature", "value": 26.4, "unit": "°C"},
            {"measurement": "humidity", "value": 61.0, "unit": "%"}])
        with mock.patch(
                'aot.aot_flask.geo.coordinator_plot.comfort_ranges_for_device',
                return_value={'temperature': (22.0, 28.0)}) as m, \
             mock.patch.object(server_viz, '_display_bands', return_value={}) as d:
            server_viz._build('gauge', body)
        self.assertEqual(1, m.call_count)        # 두 채널·한 장치 → 한 번만 해석
        self.assertEqual(1, d.call_count)


class DisplayBandTest(unittest.TestCase):
    """구획이 범위를 못 주면 지도·구획 카드와 **같은 표**(시설 sensor_ranges → 앱 기본 5단계 밴드의
    밴드 3)로 녹색을 그린다 — 지도 라벨 색·구획 카드 초록과 같은 숫자(사용자 지적 2026-11-09:
    "지도·구획 위젯은 목표와 현재가 구분되는데 AI 카드 게이지는 밋밋하다").

    고정하는 계약:
      1. 측정마다 구획 범위가 이긴다 — 지도 밴드는 빈 자리만 채운다.
      2. 구획 프로그램이 그 항목을 정했으면(값 하나라 녹색을 못 그려도) 지도 밴드를 덧그리지 않는다.
      3. 시설 sensor_ranges 가 있으면 그것, 없으면 앱 기본값. 온도·습도·VPD 만.
    """

    def _cp(self, precise=None, spoken=(), facility=None):
        return (mock.patch('aot.aot_flask.geo.coordinator_plot.comfort_ranges_for_device',
                           return_value=precise or {}),
                mock.patch('aot.aot_flask.geo.coordinator_plot.program_spoken_measurements',
                           return_value=set(spoken)),
                mock.patch('aot.aot_flask.geo.coordinator_plot.facility_of_device',
                           return_value=facility))

    def _gauges(self, body, precise=None, spoken=(), sensor_ranges=None):
        a, b, c = self._cp(precise, spoken, facility='fac-1' if sensor_ranges else None)
        with a, b, c, mock.patch.object(server_viz, '_facility_sensor_ranges',
                                        return_value=sensor_ranges):
            return server_viz._build('gauge', body)[2]

    def test_no_plot_range_falls_back_to_the_map_band(self):
        tiles = self._gauges(dict(_READING))
        self.assertEqual((18.0, 26.0), (tiles[0]['okMin'], tiles[0]['okMax']))   # 앱 기본 T 밴드 3

    def test_plot_range_wins_per_measurement(self):
        body = dict(_READING, channels=[
            {"measurement": "temperature", "value": 26.4, "unit": "°C"},
            {"measurement": "humidity", "value": 61.0, "unit": "%"}])
        temp, hum = self._gauges(body, precise={'temperature': (22.0, 28.0)})
        self.assertEqual((22.0, 28.0), (temp['okMin'], temp['okMax']))   # 구획
        self.assertEqual((55.0, 70.0), (hum['okMin'], hum['okMax']))     # 빈 자리 → 앱 기본 RH

    def test_program_spoken_measurement_gets_no_map_band(self):
        body = dict(_READING, channels=[
            {"measurement": "humidity", "value": 61.0, "unit": "%"},
            {"measurement": "vapor_pressure_deficit", "value": 0.9, "unit": "kPa"}])
        hum, vpd = self._gauges(body, spoken={'relative_humidity', 'vapor_pressure_deficit'})
        self.assertNotIn('okMin', hum)
        self.assertNotIn('okMin', vpd)

    def test_facility_sensor_ranges_override_defaults(self):
        tiles = self._gauges(dict(_READING),
                             sensor_ranges={'T': {'stages': [5, 15, 22, 30, 40], 'colors': []}})
        self.assertEqual((15.0, 22.0), (tiles[0]['okMin'], tiles[0]['okMax']))

    def test_vpd_band_follows_the_stored_unit(self):
        body = dict(_READING, measurement='vapor_pressure_deficit', value=950.0, unit='Pa')
        tiles = self._gauges(body)
        self.assertEqual((800.0, 1200.0), (tiles[0]['okMin'], tiles[0]['okMax']))
        self.assertEqual((0.0, 5000.0), (tiles[0]['min'], tiles[0]['max']))   # 눈금도 Pa

    def test_unbanded_measurement_stays_plain(self):
        body = dict(_READING, measurement='co2', value=612.0, unit='ppm')
        self.assertNotIn('okMin', self._gauges(body)[0])

    def test_band_lookup_failure_keeps_the_gauge(self):
        a, b, c = self._cp()
        with a, c, mock.patch('aot.aot_flask.geo.coordinator_plot.program_spoken_measurements',
                              side_effect=RuntimeError('db')):
            tiles = server_viz._build('gauge', dict(_READING))[2]
        self.assertEqual('gauge', tiles[0]['viz'])
        self.assertNotIn('okMin', tiles[0])


if __name__ == '__main__':
    unittest.main()
