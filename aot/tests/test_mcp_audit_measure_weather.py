# coding=utf-8
"""measure·weather 조회 정리(2026-10-28 MCP 점검 D).

- measure.history 가 limit 을 거부하고, 시각이 든 FROM/TO 가 하루 전체로 읽히던 것
- weather.forecast 의 focus 가 안쪽 도구로 새어 "받지 않는 인자를 무시했다" 경고가 붙던 것
- measure.energy 요약이 기간을 고른 것처럼 'monthly' 라 쓰던 것
"""
import unittest
from datetime import date

# 도구 서비스를 먼저 불러야 data_tools 믹스인의 순환 import 가 풀린다.
from aot.tools.aot_data_tool_service import AoTDataToolService


class TimedPeriodTest(unittest.TestCase):
    TODAY = date(2026, 10, 28)

    def _range(self, text):
        from aot.tools.domain import vocab
        return vocab.period_to('range', text, today=self.TODAY)[0]

    def test_clock_times_reach_the_inner_tool(self):
        self.assertEqual({'value': '2026-10-28T12:00/2026-10-28T14:00'},
                         self._range('2026-10-28T12:00/2026-10-28T14:00'))

    def test_space_and_open_end_are_normalised(self):
        self.assertEqual({'value': '2026-10-28T12:00/'}, self._range('2026-10-28 12:00/'))

    def test_date_only_ranges_still_read_whole_days(self):
        self.assertEqual({'value': '2026-10-20/2026-10-21'}, self._range('2026-10-20/2026-10-21'))


class HistoryAndFocusArgsTest(unittest.TestCase):

    def test_history_takes_samples(self):
        """채널당 읽은 건수는 `samples`(옛 이름 `limit` 은 별칭이 받는다 — test_mcp_domain_vocab)."""
        from aot.tools.domain import dispatch
        from aot.tools.domain.registry import find_op
        from aot.tools.domain.registry_data import OPS
        o = find_op(OPS, 'measure', 'history')
        got = dispatch._inner_args(o, {'samples': 3, 'measurement': 'temperature'},
                                   'get_sensor_detail', 'loc_id', [], False)
        self.assertNotIsInstance(got, list, got)
        self.assertEqual(3, got['limit'])

    def test_focus_stays_in_the_frame_and_is_not_forwarded(self):
        from aot.tools.domain import dispatch
        from aot.tools.domain.registry import find_op
        from aot.tools.domain.registry_data import OPS
        o = find_op(OPS, 'weather', 'forecast')
        got = dispatch._inner_args(o, {'focus': 'rain_start', 'detail': False}, 'get_weather_forecast',
                                   None, [], False)
        self.assertNotIsInstance(got, list, got)
        self.assertNotIn('focus', got)
        self.assertIn('detail', got)


class EnergySummaryTest(unittest.TestCase):

    def test_summary_does_not_claim_a_period_filter(self):
        import inspect
        src = inspect.getsource(AoTDataToolService.get_energy_report)
        self.assertNotIn('Energy analysis for {period}', src)
        self.assertIn('period does not filter', src)


if __name__ == '__main__':
    unittest.main()
