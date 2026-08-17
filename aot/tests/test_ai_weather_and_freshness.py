# coding=utf-8
"""
Regression tests for three MCP-tool defects found while using the koat farm's
server on 2026-08-17. No DB, no InfluxDB, no network — every boundary is patched.

1) get_weather answered with whatever Input happened to sit inside the polygon.
   '1포장' returned "No data for device '토양온습도_2'" (a soil probe) and '3포장'
   returned a plain air node's readings, LoRaWAN rssi/snr included and not one
   rain/wind field — while a KMA input and a SenseCAP weather station stood on
   both plots unused. Selection now prefers real weather drivers and says so in
   the reply; the generic fallback is labelled as NOT a weather observation.

2) get_anomalies' comm_offline_devices stayed 0 with a sensor 39 hours silent —
   which is CORRECT (comm_fault comes from the driver, never from data age).
   The gap was that nothing else answered "what stopped reporting?".
   get_device_freshness fills it WITHOUT touching the comm verdict, and judges
   lateness against each device's own period, never a global constant.

3) The KMA driver renamed its precipitation channels at write time only, so
   every read filtered on a `measure` tag that was never written.
"""
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(
    0,
    os.path.abspath(os.path.join(os.path.dirname(__file__), os.path.pardir, os.path.pardir))
)
os.environ.setdefault("ALEMBIC_RUNNING", "1")

from aot.ai.services import aot_data_tool_service as ADT
from aot.ai.services.aot_data_tool_service import AoTDataToolService as S


def _fake_input(uid, name, device, period=300, is_activated=True):
    inp = MagicMock()
    inp.unique_id = uid
    inp.name = name
    inp.device = device
    inp.period = period
    inp.is_activated = is_activated
    return inp


def _fake_shape(uid='shape-1', map_uuid='map-1', name='1포장'):
    shape = MagicMock()
    shape.unique_id = uid
    shape.geo_id = map_uuid
    shape.feature = {'type': 'Feature', 'properties': {'name': name},
                     'geometry': {'type': 'Point', 'coordinates': [127.0, 35.9]}}
    return shape


# ---------------------------------------------------------------------------
# 1. Weather device selection
# ---------------------------------------------------------------------------
class TestWeatherDeviceSelection(unittest.TestCase):

    def test_known_weather_drivers_are_declared(self):
        """The koat devices that were being ignored must all be recognised."""
        for driver in ('KMA_weather_500', 'sensecap_weather'):
            self.assertIn(driver, ADT._WEATHER_INPUT_DEVICES)

    def test_generic_air_sensor_driver_is_not_a_weather_station(self):
        self.assertNotIn('th1x', ADT._WEATHER_INPUT_DEVICES)

    def test_bare_speed_is_not_a_weather_marker(self):
        """'speed' alone would match non-weather hardware; wind always has direction."""
        self.assertNotIn('speed', ADT._WEATHER_MEASUREMENTS)
        self.assertIn('direction', ADT._WEATHER_MEASUREMENTS)
        self.assertIn('precipitation', ADT._WEATHER_MEASUREMENTS)

    def test_name_affinity(self):
        self.assertEqual(1, S._name_affinity('기상청-1포장', '1포장'))
        self.assertEqual(1, S._name_affinity('기상청 - 3포장', '3포장'))
        self.assertEqual(0, S._name_affinity('기상청-1포장', '3포장'))
        # 한 글자 이름으로는 부분일치를 하지 않는다(우연한 매치 방지).
        self.assertEqual(0, S._name_affinity('기상대', '3'))

    def test_in_zone_beats_same_map(self):
        near = _fake_input('w-in', '기상대', 'sensecap_weather')
        far = _fake_input('w-map', '기상청-9포장', 'KMA_weather_500')
        with patch.object(S, '_weather_inputs',
                          return_value={'w-in': near, 'w-map': far}), \
             patch('aot.aot_flask.geo.device_membership.device_ids_in_shape',
                   return_value={'w-in', 'soil-1'}), \
             patch.object(ADT, '_devices_on_map_p2', return_value={'w-in', 'w-map'}):
            chosen, scope, others = S._pick_weather_input(_fake_shape(), '1포장')
        self.assertEqual('w-in', chosen.unique_id)
        self.assertEqual('in_zone', scope)
        self.assertEqual([], others)

    def test_name_affinity_breaks_the_tie_when_nothing_is_placed(self):
        """A KMA input often has no marker; its name is then the only link."""
        a = _fake_input('kma-1', '기상청-1포장', 'KMA_weather_500')
        b = _fake_input('kma-3', '기상청-3포장', 'KMA_weather_500')
        with patch.object(S, '_weather_inputs',
                          return_value={'kma-1': a, 'kma-3': b}), \
             patch('aot.aot_flask.geo.device_membership.device_ids_in_shape',
                   return_value=set()), \
             patch.object(ADT, '_devices_on_map_p2', return_value=set()):
            chosen, scope, others = S._pick_weather_input(_fake_shape(), '3포장')
        self.assertEqual('kma-3', chosen.unique_id)
        self.assertEqual('elsewhere', scope)
        self.assertEqual(['kma-1'], [o['device_id'] for o in others])

    def test_no_weather_device_at_all(self):
        with patch.object(S, '_weather_inputs', return_value={}):
            chosen, scope, others = S._pick_weather_input(_fake_shape(), '1포장')
        self.assertIsNone(chosen)
        self.assertIsNone(scope)

    def test_lookback_is_period_aware_never_a_global_constant(self):
        """A daily sensor must not be asked for 'the last 1h' and reported empty."""
        self.assertEqual('1h', S._weather_time_range(_fake_input('x', 'x', 'y', period=300)))
        self.assertEqual('1h', S._weather_time_range(_fake_input('x', 'x', 'y', period=60)))
        self.assertEqual('72h', S._weather_time_range(_fake_input('x', 'x', 'y', period=86400)))
        # 주기를 모르면 요청 창(1h)을 그대로 쓴다.
        self.assertEqual('1h', S._weather_time_range(_fake_input('x', 'x', 'y', period=None)))

    def test_precipitation_survives_the_weather_filter(self):
        """'rain' is not a substring of 'precipitation' — that was the bug."""
        for name in ('precipitation', 'snowfall', 'visibility', 'temperature',
                     'speed', 'direction', 'dewpoint'):
            self.assertTrue(
                any(kw in name for kw in ADT._WEATHER_METRIC_KEYWORDS), name)
        for noise in ('rssi', 'snr', 'electrical_potential', 'battery_voltage'):
            self.assertFalse(
                any(kw in noise for kw in ADT._WEATHER_METRIC_KEYWORDS), noise)


class TestGetWeatherToolEnvelope(unittest.TestCase):
    """End-to-end shape of the reply, with the DB and Influx read patched out."""

    def _run(self, chosen, scope='in_zone', others=None, sensor_payload=None,
             fallback_dev=None):
        shape = _fake_shape()
        geo = MagicMock()
        geo.query.filter_by.return_value.first.return_value = shape
        inp = MagicMock()
        inp.query.filter.return_value.first.return_value = fallback_dev
        payload = sensor_payload if sensor_payload is not None else [
            {"device_name": "기상대", "measurement": "temperature",
             "readings": [{"t": "2026-08-17T09:00:00+09:00", "v": 27.1, "u": "C"}]}]
        with patch.object(ADT, 'GeoShape', geo), \
             patch.object(ADT, 'Input', inp), \
             patch('aot.aot_flask.geo.device_membership.device_ids_in_shape',
                   return_value={'any-1'}), \
             patch.object(S, '_pick_weather_input',
                          return_value=(chosen, scope, others or [])), \
             patch.object(S, 'get_sensor_detail', return_value=payload):
            return S.get_weather_tool(zone_id='shape-1')

    def test_weather_station_is_reported_as_such(self):
        out = self._run(_fake_input('w1', '기상대', 'sensecap_weather'))
        self.assertEqual('weather_station', out['weather_source'])
        self.assertEqual('기상대', out['weather_device']['name'])
        self.assertEqual('sensecap_weather', out['weather_device']['driver'])
        self.assertEqual('1포장', out['zone_name'])
        self.assertNotIn('weather_source_warning', out)

    def test_out_of_zone_station_is_flagged(self):
        out = self._run(_fake_input('w1', '기상청-1포장', 'KMA_weather_500'),
                        scope='elsewhere')
        self.assertEqual('elsewhere', out['weather_device_scope'])
        self.assertIn('weather_device_note', out)

    def test_fallback_is_never_presented_as_weather(self):
        soil = _fake_input('soil-2', '토양온습도_2', 'th1x', period=3600)
        out = self._run(None, fallback_dev=soil)
        self.assertEqual('nearby_sensor', out['weather_source'])
        self.assertIn('weather_source_warning', out)
        self.assertIn('NOT weather observations', out['weather_source_warning'])
        self.assertNotIn('weather_device', out)
        # 어느 센서를 읽었는지 밝힌다 — 예전에는 이름조차 응답에 없었다.
        self.assertEqual('토양온습도_2', out['fallback_device']['name'])

    def test_fallback_window_follows_the_devices_own_period(self):
        """koat '1포장' 의 "No data ... in the last 1h" 가 이 자리에서 났다."""
        slow = _fake_input('slow-1', '하루한번', 'th1x', period=86400)
        with patch.object(S, '_weather_time_range',
                          wraps=S._weather_time_range) as spy, \
             patch.object(S, 'get_sensor_detail', return_value=[]) as read:
            shape = _fake_shape()
            geo = MagicMock()
            geo.query.filter_by.return_value.first.return_value = shape
            inp = MagicMock()
            inp.query.filter.return_value.first.return_value = slow
            with patch.object(ADT, 'GeoShape', geo), \
                 patch.object(ADT, 'Input', inp), \
                 patch('aot.aot_flask.geo.device_membership.device_ids_in_shape',
                       return_value={'slow-1'}), \
                 patch.object(S, '_pick_weather_input', return_value=(None, None, [])):
                S.get_weather_tool(zone_id='shape-1')
        spy.assert_called_once_with(slow)
        self.assertEqual('72h', read.call_args_list[0].kwargs['time_range'])

    def test_zone_not_found_still_returns_the_old_error_contract(self):
        geo = MagicMock()
        geo.query.filter_by.return_value.first.return_value = None
        geo.query.all.return_value = []
        geo.query.limit.return_value.all.return_value = []
        with patch.object(ADT, 'GeoShape', geo):
            out = S.get_weather_tool(zone_name='없는포장')
        self.assertEqual('zone_not_found', out['error'])


# ---------------------------------------------------------------------------
# 2. Device freshness — an OBSERVATION tool, separate from the comm verdict
# ---------------------------------------------------------------------------
class TestDeviceFreshness(unittest.TestCase):

    def _run(self, devices, ages):
        """ages: {device_id: age_seconds or None}"""
        inp = MagicMock()
        inp.query.all.return_value = devices
        inp.query.filter.return_value.all.return_value = devices

        def _last_seen(device_id):
            age = ages.get(device_id)
            if age is None:
                return None, None, None
            return age, '2026-08-15T00:00:00+00:00', 'temperature (ch0)'

        with patch.object(ADT, 'Input', inp), \
             patch.object(S, '_last_seen_seconds', side_effect=_last_seen):
            return S.get_device_freshness()

    def test_long_silent_device_is_listed_with_its_period_multiple(self):
        dev = _fake_input('soil-2', '토양온습도_2', 'th1x', period=600)
        out = self._run([dev], {'soil-2': 39 * 3600})
        self.assertEqual(1, out['stale_count'])
        entry = out['stale_devices'][0]
        self.assertEqual('토양온습도_2', entry['name'])
        self.assertEqual(234.0, entry['periods_late'])
        self.assertEqual('1d 15h', entry['age_readable'])

    def test_a_daily_sensor_20h_silent_is_not_stale(self):
        """A fixed 300s/1h threshold would call this broken. It is healthy."""
        dev = _fake_input('daily-1', '일1회센서', 'KMA_weather_500', period=86400)
        out = self._run([dev], {'daily-1': 20 * 3600})
        self.assertEqual(0, out['stale_count'])
        self.assertEqual(1, out['fresh_count'])

    def test_short_period_device_uses_the_minimum_floor_not_3x15s(self):
        """15s * 3 = 45s would flag every jitter; the floor keeps it usable."""
        dev = _fake_input('fast-1', '빠른센서', 'th1x', period=15)
        out = self._run([dev], {'fast-1': 120})
        self.assertEqual(0, out['stale_count'])
        out = self._run([dev], {'fast-1': 900})
        self.assertEqual(1, out['stale_count'])

    def test_deactivated_device_is_separated_not_reported_as_silent(self):
        dev = _fake_input('off-1', '겨울에끔', 'th1x', period=600, is_activated=False)
        out = self._run([dev], {'off-1': 30 * 86400})
        self.assertEqual(0, out['stale_count'])
        self.assertEqual(1, out['inactive_count'])

    def test_device_with_no_stored_value_is_its_own_bucket(self):
        dev = _fake_input('new-1', '신규', 'th1x', period=600)
        out = self._run([dev], {'new-1': None})
        self.assertEqual(0, out['stale_count'])
        self.assertEqual(1, out['no_data_count'])

    def test_the_reply_refuses_to_call_silence_a_fault(self):
        dev = _fake_input('soil-2', '토양온습도_2', 'th1x', period=600)
        out = self._run([dev], {'soil-2': 39 * 3600})
        # comm_fault 축과 섞이지 않는다 — 이름도 판정도 분리돼 있어야 한다.
        self.assertNotIn('comm_offline_devices', out)
        self.assertNotIn('anomaly_detected', out)
        self.assertIn('Silence is not proof of failure', out['caveat'])

    def test_stale_list_is_ordered_by_how_late_it_is(self):
        a = _fake_input('a', 'A', 'th1x', period=600)
        b = _fake_input('b', 'B', 'th1x', period=600)
        out = self._run([a, b], {'a': 4 * 3600, 'b': 40 * 3600})
        self.assertEqual(['B', 'A'], [e['name'] for e in out['stale_devices']])

    def test_readable_age(self):
        self.assertEqual('30s', S._readable_age(30))
        self.assertEqual('5m', S._readable_age(300))
        self.assertEqual('2h 30m', S._readable_age(9000))
        self.assertEqual('7d 0h', S._readable_age(7 * 86400))


class TestAnomalyMetricDefinitions(unittest.TestCase):
    """The two device counts differ by definition — the reply must say so."""

    def test_metrics_definitions_are_attached(self):
        current = {'metrics': {'total_devices': 32}, 'timestamp': 'now'}
        summary = MagicMock()
        summary.gather_scope_data.return_value = current
        summary.get_latest_summary.return_value = None
        detector = MagicMock()
        detector.detect_anomalies.return_value = {'anomaly_detected': False}
        mods = {
            'aot.ai.services.ai_summary_service': MagicMock(AISummaryService=summary),
            'aot.ai.services.ai_anomaly_detector': MagicMock(AIAnomalyDetector=detector),
        }
        with patch.dict(sys.modules, mods):
            out = S.get_anomalies()
        defs = out['metrics_definitions']
        self.assertIn('device_count', defs['total_devices'])
        self.assertIn('Inputs (sensors) in this scope ONLY', defs['total_devices'])
        self.assertIn('get_device_freshness', defs['comm_offline_devices'])


# ---------------------------------------------------------------------------
# 3. KMA precipitation measurement naming
# ---------------------------------------------------------------------------
class TestKmaPrecipitationNaming(unittest.TestCase):

    def test_the_split_option_is_gone(self):
        from aot.inputs.kma_weather_500 import INPUT_INFORMATION
        ids = {o['id'] for o in INPUT_INFORMATION['custom_options']}
        self.assertNotIn('split_precip_measurements', ids)

    def test_channel_names_stay_as_declared(self):
        from aot.inputs.kma_weather_500 import measurements_dict
        self.assertEqual('precipitation', measurements_dict[5]['measurement'])
        self.assertEqual('precipitation', measurements_dict[6]['measurement'])
        # 두 채널은 채널 번호와 단위로 이미 구분된다 — 이름을 바꿀 이유가 없었다.
        self.assertNotEqual(measurements_dict[5]['unit'], measurements_dict[6]['unit'])

    def test_backfill_writes_the_declared_measurement_name(self):
        """The write tag must equal what DeviceMeasurements holds, or every read
        filters on a tag that was never written (graphs, /last, MCP tools)."""
        import datetime
        import pytz
        from aot.inputs.kma_weather_500 import InputModule

        inst = InputModule.__new__(InputModule)
        inst.logger = MagicMock()
        inst.unique_id = 'kma-test'
        inst.input_dev = MagicMock()
        inst.is_enabled = lambda ch: True
        inst._last_good = None
        inst._last_good_ts = None
        inst._qc_backfill_replaced = 0
        inst._qc_backfill_dropped = 0
        inst._qc_backfill_zero_ta_dropped = 0
        inst._persist_latest_datetime = MagicMock()
        inst.get_custom_option = lambda key: None
        inst.run_input_actions = None

        rows = [{
            'pub_timestamp': (datetime.datetime.now() -
                              datetime.timedelta(hours=1)).strftime('%Y%m%d%H%M'),
            'ta': 21.0, 'hm': 55.0, 'wd_10m': 180.0, 'ws_10m': 1.2, 'pa': 1010.0,
            'rn_ox': 0.0, 'rn_15m': 0.0, 'vs': 20.0, 'sd_tot': 0.0,
        }]

        captured = {}

        def _capture(uid, measurements, use_same_timestamp=True):
            captured.update(measurements)

        with patch('aot.inputs.kma_weather_500.add_measurements_influxdb', _capture):
            inst._write_backfill_rows(rows, pytz.timezone('Asia/Seoul'))

        self.assertEqual('precipitation', captured[5]['measurement'])
        self.assertEqual('precipitation', captured[6]['measurement'])
        # 눈은 원래 잘 저장되던 채널 — 회귀 대조군.
        self.assertEqual('snowfall', captured[8]['measurement'])
        # 비가 안 왔을 때 0.0 이 실제로 기록되어야 한다("데이터 없음"이 아니라).
        self.assertEqual(0.0, captured[5]['value'])
        self.assertEqual(0.0, captured[6]['value'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
