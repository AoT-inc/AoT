# coding=utf-8
"""2026-11-04 MCP 수정 S6 B — `measure.freshness` 일부 채널 끊김 집계.

정상 분류("어느 채널이든 최근이면 정상")는 그대로 두고, 정상 장치 중 일부 채널이 허용 시간 안에 값이 없는 것을
`partial_silent_count` / `partial_silent_devices` 로 따로 센다(정상 수 `fresh_count` 의 부분집합). 전체 장치를
채널마다 묻지 않고 Flux 질의 한 번으로 본다. 시각 표시는 장치 위치 시계(`iso_at`).
"""
import time
import unittest
from unittest import mock

from aot.tools.aot_data_tool_service import AoTDataToolService  # noqa: F401 — 순환 import 순서
from aot.tools.data_tools import measurement as M

NOW = time.time()


def _dev(uid, name='s'):
    d = mock.Mock(unique_id=uid)
    d.name = name
    return d


class PartialSilent(unittest.TestCase):

    def _run(self, chans, last, ok=True, within=900, detail=False):
        """chans: [(채널번호, 측정이름)]; last: {측정이름: 마지막 epoch|없음}."""
        rows = [mock.Mock(channel=c, conversion_id=None, measurement=n, is_enabled=True) for c, n in chans]
        q = mock.Mock()
        q.query.filter.return_value.all.return_value = rows
        calls = []

        def bulk(specs, past_sec=600):
            calls.append((len(specs), past_sec))
            out = {('u', 'd1', str(sp[2]), sp[3]): [last[sp[3]], 1.0]
                   for sp in specs if last.get(sp[3]) and NOW - last[sp[3]] <= past_sec}
            return out, ok

        with mock.patch.object(M, 'DeviceMeasurements', q), \
                mock.patch.object(M, 'return_measurement_info', lambda m, _c: (m.channel, 'u', m.measurement)), \
                mock.patch('aot.utils.influx.query_last_values_bulk_status', bulk), \
                mock.patch.object(M, 'iso_at', lambda v, _w: 'iso'):
            got = M.MeasurementToolsMixin.partial_silent_channels([(_dev('d1'), within)], detail=detail)
        return got, calls

    def test_battery_alive_but_temperature_silent_is_partial(self):
        got, calls = self._run([(0, 'temperature'), (1, 'humidity'), (2, 'electrical_potential')],
                               {'temperature': NOW - 7 * 86400, 'electrical_potential': NOW - 60})
        self.assertEqual({'d1': [{'measurement': 'temperature'}, {'measurement': 'humidity'}]}, got)
        self.assertEqual(1, len(calls))                       # 질의 한 번
        self.assertEqual(900, calls[0][1])                    # 그 장치의 허용 시간만큼만 거슬러 본다

    def test_every_channel_recent_is_not_partial(self):
        got, _ = self._run([(0, 'temperature'), (1, 'electrical_potential')],
                           {'temperature': NOW - 10, 'electrical_potential': NOW - 60})
        self.assertEqual({}, got)

    def test_device_with_only_a_battery_channel_is_not_partial(self):
        got, _ = self._run([(0, 'electrical_potential')], {'electrical_potential': NOW - 30})
        self.assertEqual({}, got)

    def test_fully_silent_device_is_not_counted_here(self):
        # 전부 끊긴 장치는 정상이 아니라 stale — 이 집계의 대상이 아니다
        got, _ = self._run([(0, 'temperature'), (1, 'humidity')], {})
        self.assertEqual({}, got)

    def test_failed_query_claims_nothing(self):
        got, _ = self._run([(0, 'temperature'), (1, 'humidity')], {'temperature': NOW - 1}, ok=False)
        self.assertEqual({}, got)

    def test_detail_reuses_silent_channels_for_the_partial_device_only(self):
        rows = [mock.Mock(channel=c, conversion_id=None, measurement=n, is_enabled=True)
                for c, n in [(0, 'temperature'), (1, 'electrical_potential')]]
        q = mock.Mock()
        q.query.filter.return_value.all.return_value = rows

        def bulk(specs, past_sec=600):
            return {('u', 'd1', '1', 'electrical_potential'): [NOW - 5, 3.7]}, True

        quiet = [{'measurement': 'temperature', 'last_seen': 'iso', 'age_readable': '5h 0m'}]
        with mock.patch.object(M, 'DeviceMeasurements', q), \
                mock.patch.object(M, 'return_measurement_info', lambda m, _c: (m.channel, 'u', m.measurement)), \
                mock.patch('aot.utils.influx.query_last_values_bulk_status', bulk), \
                mock.patch.object(M.MeasurementToolsMixin, 'silent_channels', return_value=quiet) as sc:
            got = M.MeasurementToolsMixin.partial_silent_channels([(_dev('d1'), 900)], detail=True)
        self.assertEqual({'d1': quiet}, got)
        sc.assert_called_once_with('d1', 900)

    def test_devices_are_queried_in_groups_by_their_own_window(self):
        """질의 시간은 창 길이에 비례한다 — 느린 센서(허용 9시간) 하나가 15분 센서들의 창을 늘리지 않는다."""
        rows = [mock.Mock(channel=0, conversion_id=None, measurement='temperature', is_enabled=True)]
        q = mock.Mock()
        q.query.filter.return_value.all.return_value = rows
        windows = []

        def bulk(specs, past_sec=600):
            windows.append((past_sec, len(specs)))
            return {}, True

        with mock.patch.object(M, 'DeviceMeasurements', q), \
                mock.patch.object(M, 'return_measurement_info', lambda m, _c: (m.channel, 'u', m.measurement)), \
                mock.patch('aot.utils.influx.query_last_values_bulk_status', bulk):
            M.MeasurementToolsMixin.partial_silent_channels(
                [(_dev('a'), 900), (_dev('b'), 900), (_dev('c'), 32400)])
        self.assertEqual([(900, 2), (32400, 1)], sorted(windows))


class Wiring(unittest.TestCase):

    def test_list_and_brief_carry_the_count(self):
        import inspect
        src = inspect.getsource(M.MeasurementToolsMixin.get_device_freshness)
        self.assertIn('partial_silent_channels(', src)
        self.assertIn('"partial_silent_count": len(partial)', src)
        brief = inspect.getsource(M.MeasurementToolsMixin._freshness_brief)
        self.assertIn('partial_silent_count', brief)
        self.assertIn('fresh_count', brief)               # 정상 수는 그대로

    def test_brief_shows_partial_devices_with_channel_names(self):
        full = {"status": "success", "basis": "b", "caveat": "c", "checked": 3, "stale_count": 0,
                "stale_devices": [], "no_data_count": 0, "no_data_devices": [], "inactive_count": 0,
                "known_status_count": 0, "removed_count": 0, "fresh_count": 3, "scan_window_days": 30,
                "partial_silent_count": 1,
                "partial_silent_devices": [{"name": "온습도_1", "device_id": "d1", "last_seen": "t",
                                            "silent_channels": [{"measurement": "temperature"}]}]}
        got = M.MeasurementToolsMixin._freshness_brief(full)
        self.assertEqual(3, got["fresh_count"])
        self.assertEqual(1, got["partial_silent_count"])
        self.assertEqual(["temperature"], got["partial_silent_devices"][0]["silent_channels"])
        self.assertEqual("온습도_1", got["partial_silent_devices"][0]["name"])

    def test_anomalies_and_system_brief_expose_it_without_changing_the_level(self):
        import inspect
        from aot.tools.data_tools import system
        src = inspect.getsource(M.MeasurementToolsMixin._silent_devices_in_scope)
        self.assertIn('"partial_silent_count"', src)
        self.assertIn('"silent_level": "none"', src)
        self.assertIn('silent_partial_count', inspect.getsource(system))


if __name__ == '__main__':
    unittest.main()
