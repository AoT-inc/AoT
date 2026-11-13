# coding=utf-8
"""2026-11-03 MCP 수정 S4 #2 — 날짜 범위는 `period`(FROM/TO), 시각 창은 window_start/window_end. 옛 이름은 조용히 받는다."""
import unittest

from aot.tools.domain import contract, dispatch, renames


class DateRangeIsPeriod(unittest.TestCase):

    def test_contract_still_holds(self):
        self.assertEqual([], contract.problems())

    def _range(self, verdict):
        self.assertEqual('call', verdict[0], verdict)
        return verdict[2][dispatch.META_KEY]['journal_range']

    def test_journal_list_period_is_filtered_by_the_domain_not_sent_inside(self):
        # list_plot_journals 는 date_from/date_to 를 모른다 — 안쪽에 넘기면 조용히 무시된다(라운드 3 회귀)
        v = dispatch.plan('records', {'op': 'journals', 'period': '2026-10-01/2026-10-31', 'limit': 3})
        got = self._range(v)
        self.assertEqual(('2026-10-01', '2026-10-31'), got['range'])
        self.assertEqual(3, got['limit'])
        for k in ('date_from', 'date_to', 'period'):
            self.assertNotIn(k, v[2])
        self.assertEqual(200, v[2]['limit'])

    def test_open_ended_halves(self):
        self.assertEqual(('2026-10-01', None), self._range(
            dispatch.plan('records', {'op': 'journals', 'period': '2026-10-01/'}))['range'])
        self.assertEqual((None, '2026-10-31'), self._range(
            dispatch.plan('records', {'op': 'journals', 'period': '/2026-10-31'}))['range'])

    def test_one_journal_still_gets_date_from_to_inside(self):
        from aot.tools.domain.registry import find_op
        from aot.tools.domain.registry_data import OPS
        o = find_op(OPS, 'records', 'journals')
        got = dispatch._inner_args(o, {'_pair': ('2026-10-01', None)}, 'get_plot_journal', 'journal_id', [], False)
        self.assertEqual('2026-10-01', got['date_from'])
        self.assertNotIn('date_to', got)

    def test_filter_keeps_only_overlapping_journals(self):
        import json
        rows = [{'journal_id': 'in', 'period_start': '2026-10-05', 'period_end': '2026-10-10'},
                {'journal_id': 'edge', 'period_start': '2026-09-25', 'period_end': '2026-10-01'},
                {'journal_id': 'before', 'period_start': '2026-09-01', 'period_end': '2026-09-30'},
                {'journal_id': 'after', 'period_start': '2026-11-01', 'period_end': '2026-11-07'},
                {'journal_id': 'none', 'period_start': None, 'period_end': None}]
        out = [{'type': 'text', 'text': json.dumps({'count': 5, 'journals': rows})}]
        got = json.loads(dispatch._filter_journal_period(out, ('2026-10-01', '2026-10-31'), None)[0]['text'])
        self.assertEqual(['in', 'edge'], [r['journal_id'] for r in got['journals']])
        self.assertEqual(2, got['count'])
        none = json.loads(dispatch._filter_journal_period(out, ('2025-01-01', '2025-01-31'), 3)[0]['text'])
        self.assertEqual([], none['journals'])
        cut = json.loads(dispatch._filter_journal_period(out, ('2026-01-01', '2026-12-31'), 2)[0]['text'])
        self.assertEqual((2, True, 4), (cut['count'], cut['truncated'], cut['total']))
        open_end = json.loads(dispatch._filter_journal_period(out, ('2026-10-20', None), None)[0]['text'])
        self.assertEqual(['after'], [r['journal_id'] for r in open_end['journals']])

    def test_soil_forecast_period_rejection_carries_a_next(self):
        import json
        from aot.tools.domain.registry import find_op
        from aot.tools.domain.registry_data import OPS
        o = find_op(OPS, 'measure', 'soil_forecast')
        got = dispatch._inner_args(o, {'period': 'tomorrow'}, 'get_plot', 'plot_id', [], False)
        body = json.loads(got[0]['text'])
        self.assertEqual('unknown_argument', body['reason_code'])
        self.assertIn('measure.latest', body['next']['call'])
        self.assertIn('weather.forecast', body['next']['call'])

    def test_bad_period_is_refused_with_a_reason(self):
        v = dispatch.plan('records', {'op': 'journals', 'period': 'someday'})
        self.assertEqual('refuse', v[0])
        self.assertIn('bad_period', v[1][0]['text'])

    def test_old_names_still_work_and_say_so(self):
        tool, args, renamed = renames.resolve_call(
            'records', {'op': 'journals', 'date_from': '2026-10-01', 'date_to': '2026-10-31'})
        self.assertEqual('2026-10-01/2026-10-31', args['period'])
        self.assertNotIn('date_from', args)
        self.assertEqual({'date_from/date_to': 'period'}, renamed)
        # 옛 이름만 와도 같은 길 — 목록이면 도메인이 거른다(안쪽으로 date_from 을 넘기지 않는다)
        v = dispatch.plan('records', {'op': 'journals', 'date_from': '2026-10-01'})
        self.assertEqual(('2026-10-01', None), self._range(v)['range'])

    def test_new_name_wins_over_old(self):
        _t, args, renamed = renames.resolve_call(
            'records', {'op': 'journals', 'period': '7d', 'date_from': '2026-10-01'})
        self.assertEqual('7d', args['period'])
        self.assertEqual('2026-10-01', args['date_from'])
        self.assertEqual({}, renamed)

    def test_journal_create_needs_period_and_maps_start_end(self):
        v = dispatch.plan('record', {'op': 'journal_create', 'target_type': 'plot', 'target': 'x'})
        self.assertEqual('refuse', v[0])
        self.assertIn('period', v[1][0]['text'])
        _t, args, renamed = renames.resolve_call(
            'record', {'op': 'journal_create', 'target_type': 'plot', 'target': 'x',
                       'start': '2026-10-01', 'end': '2026-10-07'})
        self.assertEqual('2026-10-01/2026-10-07', args['period'])
        self.assertIn('start/end', renamed)


class ClockWindowIsWindow(unittest.TestCase):

    def test_old_start_end_are_renamed_quietly(self):
        for op in ('sequence_schedule', 'sequence_day'):
            _t, args, renamed = renames.resolve_call('control', {'op': op, 'start': '06:00', 'end': '18:00'})
            self.assertEqual(('06:00', '18:00'), (args['window_start'], args['window_end']), op)
            self.assertEqual({'start': 'window_start', 'end': 'window_end'}, renamed)

    def test_window_names_are_taken_by_the_registry(self):
        from aot.tools.domain.registry import find_op
        from aot.tools.domain.registry_data import OPS
        for op in ('sequence_schedule', 'sequence_day'):
            o = find_op(OPS, 'control', op)
            self.assertEqual({'window_start': 'start', 'window_end': 'end'},
                             {k: v for k, v in o.args.items() if k.startswith('window')})
            self.assertNotIn('start', o.extra_args)

    def test_every_registered_alias_has_a_date(self):
        for row in renames.rows():
            self.assertRegex(row[2], r'^\d{4}-\d{2}-\d{2}$', row)


if __name__ == '__main__':
    unittest.main()
