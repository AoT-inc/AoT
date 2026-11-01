# coding=utf-8
"""AI·MCP 도구가 내는 측정 시각은 그 장치·장소가 놓인 곳의 시각이다.

InfluxDB 는 UTC 로 저장하고, 화면은 장치 위치의 시간대로 보인다. 그런데 LLM 이
받는 응답에는 UTC 가 섞여 있었다(2026-10-09) — 구역 센서 요약의 마지막 측정
시각, 구획 목표 대조의 측정 시각, 제어 주기의 epoch 숫자. 나머지도 위치를 못
풀면 예외 처리에서 UTC 로 떨어졌다. 로컬 장치가 전부 +09:00 이라 "장치 위치
기준" 과 "농장 기준" 은 응답으로 가려지지 않으므로, 여기서는 농장과 다른
시간대를 가정해 확인한다.
"""
import ast
import os
import unittest
from datetime import datetime, timezone
from unittest import mock

import pytz

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_NY = pytz.timezone('America/New_York')
_UTC_NOON = datetime(2026, 10, 8, 12, 0, tzinfo=timezone.utc)


class TestLocationIso(unittest.TestCase):

    def _iso(self, value, target='dev-1', **kw):
        from aot.utils import device_tz
        with mock.patch.object(device_tz, 'resolve_location_tz',
                               return_value=_NY) as m:
            return device_tz.location_iso(value, target, **kw), m

    def test_utc_becomes_the_place_time(self):
        out, _ = self._iso(_UTC_NOON)
        self.assertEqual(out, '2026-10-08T08:00:00-04:00')

    def test_every_input_shape_is_read_as_utc(self):
        """InfluxDB 행(datetime), epoch 초(사이클 요약), ISO 문자열('Z' 포함),
        naive datetime — 도구마다 다른 모양으로 들고 온다."""
        for value in (_UTC_NOON, _UTC_NOON.timestamp(),
                      '2026-10-08T12:00:00Z', '2026-10-08T12:00:00+00:00',
                      datetime(2026, 10, 8, 12, 0)):
            out, _ = self._iso(value)
            self.assertEqual(out, '2026-10-08T08:00:00-04:00', value)

    def test_an_unresolvable_place_falls_back_to_farm_time_not_utc(self):
        """예전에는 위치를 못 풀면 except 에서 UTC 를 그대로 냈다."""
        from aot.utils import device_tz, time_utils
        with mock.patch.object(device_tz, 'resolve_location_tz',
                               side_effect=RuntimeError('boom')), \
                mock.patch.object(time_utils, 'get_timezone_name',
                                  return_value='Asia/Seoul'):
            out = device_tz.location_iso(_UTC_NOON, 'dev-1')
        self.assertEqual(out, '2026-10-08T21:00:00+09:00')

    def test_one_lookup_per_target_with_a_cache(self):
        cache = {}
        from aot.utils import device_tz
        with mock.patch.object(device_tz, 'resolve_location_tz',
                               return_value=_NY) as m:
            for _ in range(5):
                device_tz.location_iso(_UTC_NOON, 'dev-1', cache)
        self.assertEqual(m.call_count, 1)

    def test_nothing_in_nothing_out(self):
        out, m = self._iso(None)
        self.assertIsNone(out)
        self.assertEqual(m.call_count, 0)


class TestToolsRouteThroughOnePlace(unittest.TestCase):
    """도구가 시간대를 직접 풀면 변환을 빠뜨리거나 실패 시 UTC 로 떨어지는 자리가
    다시 생긴다. 측정·장치 시각을 내는 파일은 `location_iso` 만 쓴다."""

    _FILES = ('tools/data_tools/measurement.py',
              'tools/data_tools/device.py',
              'tools/data_tools/space.py')

    def test_no_direct_timezone_resolution(self):
        for rel in self._FILES:
            tree = ast.parse(open(os.path.join(_ROOT, rel), encoding='utf-8').read())
            used = [n.lineno for n in ast.walk(tree)
                    if isinstance(n, ast.Name) and n.id == 'resolve_location_tz']
            used += [n.lineno for n in ast.walk(tree)
                     if isinstance(n, ast.alias) and n.name == 'resolve_location_tz']
            self.assertEqual(used, [], '%s: location_iso 를 쓸 것 (%s)' % (rel, used))

    def test_known_leaks_go_through_location_iso(self):
        src = {rel: open(os.path.join(_ROOT, rel), encoding='utf-8').read()
               for rel in self._FILES}
        # 구역 센서 요약 · 구획 목표 대조 · 제어 주기 · 출력 동작 시각
        self.assertIn('"last_time": location_iso(t, did, _tzc)',
                      src['tools/data_tools/measurement.py'])
        self.assertIn("'at': location_iso(at, dev, _tzc)",
                      src['tools/data_tools/space.py'])
        dev = src['tools/data_tools/device.py']
        self.assertIn("ts=location_iso(", dev)
        self.assertIn('pos["last_moved_at"] = location_iso(', dev)
        self.assertNotIn('serialize_ts(', dev)


if __name__ == '__main__':
    unittest.main()
