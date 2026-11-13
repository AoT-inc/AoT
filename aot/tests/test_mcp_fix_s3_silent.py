# coding=utf-8
"""2026-11-03 MCP 수정 S3 #3 — 값이 끊긴 채널을 말한다(분류는 그대로).

  - measure.latest: 항목을 말하지 않으면 온도·습도 같은 주 채널이 대표값, 값이 없는 채널은 silent_channels.
  - measure.freshness(장치 지목): 정상으로 분류된 장치의 끊긴 채널을 곁에 적는다.
"""
import time
import unittest
from unittest import mock

from flask import Flask

from aot.tools.aot_native_tool_engine import AoTNativeToolEngine as N
from aot.tools.aot_data_tool_service import AoTDataToolService as S


def _ch(name, v):
    return {'measurement': name, 'readings': [{'t': '2026-11-03T08:00', 'v': v, 'u': 'x'}]}


class Latest(unittest.TestCase):

    def _read(self, series, names, measurement=None):
        row = mock.Mock(unique_id='d1')
        row.name = '온습도_1'
        with Flask('t').app_context(), \
                mock.patch.object(S, '_read_device', return_value=(row, 'input', None)), \
                mock.patch.object(S, 'channel_names', return_value=names), \
                mock.patch.object(S, 'get_sensor_detail', return_value=series):
            return N._sensor_reading_one('d1', measurement, None)

    def test_primary_channel_is_the_representative(self):
        out = self._read([_ch('electrical_potential', 3.7), _ch('temperature', 21.0)],
                         ['electrical_potential', 'temperature'])
        self.assertEqual('temperature', out['measurement'])
        self.assertNotIn('silent_channels', out)

    def test_silent_channels_are_named_when_only_side_channels_report(self):
        out = self._read([_ch('electrical_potential', 3.71), _ch('rssi', -80)],
                         ['temperature', 'humidity', 'electrical_potential', 'rssi'])
        self.assertEqual('electrical_potential', out['measurement'])          # 고를 주 채널이 없다
        self.assertEqual(['temperature', 'humidity'], out['silent_channels'])
        self.assertIn('temperature, humidity', out['note'])

    def test_a_named_measurement_adds_no_silent_list(self):
        out = self._read([_ch('humidity', 55.0)], ['temperature', 'humidity'], measurement='humidity')
        self.assertNotIn('silent_channels', out)


class FreshnessChannels(unittest.TestCase):

    def test_only_the_channels_without_a_recent_value_are_listed(self):
        from aot.tools.data_tools import measurement as M
        now = time.time()
        rows = [mock.Mock(channel=i, conversion_id=None, measurement=n, is_enabled=True)
                for i, n in enumerate(['temperature', 'humidity', 'electrical_potential'])]
        last = {'temperature': now - 7 * 86400, 'humidity': None, 'electrical_potential': now - 60}

        def influx(_dev, _unit, _ch, measure=None, **_kw):
            return last[measure], 0

        q = mock.Mock()
        q.query.filter.return_value.all.return_value = rows
        with mock.patch.object(M, 'DeviceMeasurements', q), \
                mock.patch.object(M, 'return_measurement_info',
                                  lambda m, _c: (m.channel, 'u', m.measurement)), \
                mock.patch('aot.utils.influx.read_influxdb_single', influx), \
                mock.patch.object(M, 'iso_at', lambda v, _w: 'iso'):
            got = M.MeasurementToolsMixin.silent_channels('d1', 900)
        self.assertEqual(['temperature', 'humidity'], [c['measurement'] for c in got])
        self.assertIsNone(got[1]['last_seen'])


if __name__ == '__main__':
    unittest.main()
