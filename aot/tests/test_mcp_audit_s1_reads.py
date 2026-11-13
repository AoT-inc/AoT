# coding=utf-8
"""2026-11-03 MCP 점검 S1 — 읽기 결과가 거짓으로 보이던 것(A1~A5).

  A1 overview.brief 의 장치 수는 첫 쪽 크기(40)가 아니라 전체 수다.
  A2 get_sensor_detail 의 모르는 time_range 는 조용히 24h 가 되지 않고 오류다.
  A3 weather.forecast 의 내일 요약에 다음 날 00시 행이 섞이지 않는다.
  A4 measure.latest(장치)가 항목·기간을 받고 채널 이름을 싣는다.
  A5 records.schedule 의 기간은 안쪽 상한을 넘기 전에 읽은 행에서 거른다.

DB 없이 도는 결정론적 시험이다.
"""
import json
import unittest
from datetime import date
from unittest import mock

from aot.tools.domain.registry import Op


class RangeWords(unittest.TestCase):

    def _svc(self):
        from aot.tools.aot_data_tool_service import AoTDataToolService as MeasurementTools
        return MeasurementTools

    def test_known_shapes_pass(self):
        s = self._svc()
        for text in ('1h', '24h', '7d', '3600', '', None, '48H'):
            self.assertTrue(s._range_ok(text), text)

    def test_unknown_words_are_refused_not_read_as_24h(self):
        s = self._svc()
        for text in ('yesterday', 'last_week', 'this_week', 'xh', '15m'):
            self.assertFalse(s._range_ok(text), text)
        err = s._bad_range('yesterday')
        self.assertEqual('bad_period', err['reason_code'])
        self.assertIn('FROM/TO', err['error'])


def _hours(start_day, n):
    return [{'time': '2026-11-%02dT%02d:00' % (start_day + h // 24, h % 24),
             'precipitation (mm)': 0.5 if h == 24 else 0.0, 'temperature (C)': 10 + h % 24}
            for h in range(n)]


class ForecastSummary(unittest.TestCase):

    def _fc(self, rows, **period):
        base = {'start': '2026-11-04T00:00', 'end': '2026-11-05T00:00', 'hours': 24}
        return {'status': 'success', 'forecasts': rows, 'period': dict(base, **period)}

    def test_calendar_day_summary_excludes_next_midnight(self):
        from aot.tools.data_tools.weather_summary import summarize_forecast
        out = summarize_forecast(self._fc(_hours(4, 25)))
        self.assertEqual(24, out['summary_rows'])
        self.assertEqual(0.0, out['summary']['precipitation (mm)']['max'])   # 익일 00시의 0.5 는 빠진다

    def test_rolling_window_keeps_the_end_row(self):
        from aot.tools.data_tools.weather_summary import summarize_forecast
        out = summarize_forecast(self._fc(_hours(4, 25), start='2026-11-04T10:00'))
        self.assertEqual(25, out['summary_rows'])

    def test_short_hourly_horizon_says_what_it_covers(self):
        from aot.tools.data_tools.weather_summary import summarize_forecast
        out = summarize_forecast(self._fc(_hours(5, 8), truncated=True, start='2026-11-05T00:00',
                                          end='2026-11-05T08:00'))
        self.assertEqual('11-05 00:00 to 11-05 07:00', out['covers'])
        full = summarize_forecast(self._fc(_hours(4, 24)))
        self.assertNotIn('covers', full)


class DeviceCount(unittest.TestCase):

    def test_brief_counts_the_whole_list_not_the_first_page(self):
        from aot.tools.aot_data_tool_service import AoTDataToolService as SystemTools
        src = __import__('inspect').getsource(SystemTools.get_system_brief)
        # 자르기 전 전체 수(page.total)와 종류별 수(count_by_type)를 쓴다.
        self.assertIn('_page.get("total")', src)
        self.assertIn('count_by_type', src)


class SensorReading(unittest.TestCase):

    def _read(self, series, measurement=None, time_range=None):
        from aot.tools.aot_native_tool_engine import AoTNativeToolEngine as N
        from aot.tools.aot_data_tool_service import AoTDataToolService as S
        from flask import Flask
        row = mock.Mock(unique_id='d1')
        row.name = '토양센서'
        with Flask('t').app_context(), \
                mock.patch.object(S, '_read_device', return_value=(row, 'input', None)), \
                mock.patch.object(S, 'get_sensor_detail', return_value=series) as detail:
            out = N._sensor_reading_one('d1', measurement, time_range)
        return out, detail

    @staticmethod
    def _ch(name, v):
        return {'measurement': name, 'readings': [{'t': '2026-11-03T08:00', 'v': v, 'u': 'x'}]}

    def test_measurement_and_period_reach_the_reader(self):
        out, detail = self._read([self._ch('moisture', 31.0)], 'moisture', '24h')
        self.assertEqual('moisture', detail.call_args.kwargs['sensor_type'])
        self.assertEqual('24h', detail.call_args.kwargs['time_range'])
        self.assertEqual('moisture', out['measurement'])

    def test_default_is_the_last_hour_and_one_channel_has_no_channel_list(self):
        out, detail = self._read([self._ch('temperature', 3.5)])
        self.assertEqual('1h', detail.call_args.kwargs['time_range'])
        self.assertIsNone(detail.call_args.kwargs['sensor_type'])
        self.assertNotIn('channels', out)

    def test_several_channels_are_all_named(self):
        out, _ = self._read([self._ch('temperature', 3.5), self._ch('humidity', 80.0)])
        self.assertEqual(['temperature', 'humidity'], [c['measurement'] for c in out['channels']])
        self.assertEqual('temperature', out['measurement'])

    def test_handler_params_are_declared_for_the_contract(self):
        from aot.tools.aot_native_tool_engine import AoTNativeToolEngine as N
        self.assertLessEqual({'measurement_type', 'time_range'}, N.HANDLER_PARAMS['get_sensor_reading'])


_SCHEDULE = Op(
    tool='records', op='schedule', use='x',
    inner={'none': 'search_schedule'}, effect='read',
    args={'query': 'query', 'limit': 'limit'}, extra_args={'include_past': 'x'},
    period_field='when', rows_key='results')


def _rows(days):
    return [{'job': i, 'when': '2026-11-%02dT09:00:00+09:00' % d} for i, d in enumerate(days)]


class SchedulePeriod(unittest.TestCase):

    def _plan(self, args):
        from aot.tools.domain import dispatch
        with mock.patch.object(dispatch, 'today_at', lambda *_a: date(2026, 11, 3)):
            return dispatch.plan('records', dict(args, op='schedule'), ops=[_SCHEDULE])

    def test_period_reads_wide_before_filtering(self):
        v = self._plan({'period': 'tomorrow', 'limit': 5})
        self.assertEqual(('call', 'search_schedule'), v[:2])
        self.assertEqual(500, v[2]['limit'])                      # 사용자의 5 는 거른 뒤에 쓴다
        self.assertNotIn('include_past', v[2])                    # 앞날만이면 지난 일정은 읽지 않는다

    def test_period_reaching_back_includes_the_past(self):
        v = self._plan({'period': 'yesterday'})
        self.assertTrue(v[2]['include_past'])

    def test_filter_applies_the_user_limit_after_the_period(self):
        from aot.tools.domain import dispatch
        body = {'status': 'success', 'count': 8, 'truncated': True, 'note': 'first 20',
                'results': _rows([9, 4, 4, 4, 4, 4, 4, 1])}
        out = [{'type': 'text', 'text': json.dumps(body)}]
        with mock.patch.object(dispatch, 'today_at', lambda *_a: date(2026, 11, 3)):
            got = json.loads(dispatch._filter_period(out, _SCHEDULE, '2026-11-04', 3)[0]['text'])
        self.assertEqual(3, got['count'])
        self.assertTrue(got['truncated'])
        self.assertIn('first 3', got['note'])

    def test_filter_without_truncation_drops_the_stale_note(self):
        from aot.tools.domain import dispatch
        body = {'status': 'success', 'count': 3, 'truncated': True, 'note': 'first 20',
                'results': _rows([9, 4, 1])}
        out = [{'type': 'text', 'text': json.dumps(body)}]
        got = json.loads(dispatch._filter_period(out, _SCHEDULE, '2026-11-04', None)[0]['text'])
        self.assertEqual(1, got['count'])
        self.assertNotIn('truncated', got)
        self.assertNotIn('note', got)

    def test_period_read_is_not_size_capped_inside(self):
        """안쪽 응답을 크기 상한으로 먼저 자르면 거를 행이 사라진다 — count 0 + results_truncated (시험 #2)."""
        from aot.tools.domain import dispatch
        seen = {}

        def fake(app, inner, args, **kw):
            seen.update(kw)
            return [{'type': 'text', 'text': json.dumps(
                {'status': 'success', 'count': 3, 'results': _rows([9, 4, 4])})}]

        for period, want in (('2026-11-04', True), (None, False)):
            args = {'op': 'schedule', 'limit': 5}
            if period:
                args['period'] = period
            seen.clear()
            with mock.patch.object(dispatch, 'today_at', lambda *_a: date(2026, 11, 3)), \
                    mock.patch.object(dispatch, '_ops', lambda: [_SCHEDULE]), \
                    mock.patch('aot.tools.tool_execution._execute_tool', fake):
                dispatch._run_call_inner(None, 'records', args, {}, None, None)
            self.assertEqual(want, bool(seen.get('uncapped')), period)


if __name__ == '__main__':
    unittest.main()
