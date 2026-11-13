# coding=utf-8
"""2026-11-03 MCP 수정 S4 #1 — 도메인 층에서 응답을 줄이고(안쪽 도구는 그대로), 목록 op 가 limit·offset 을 받는다."""
import json
import unittest

from aot.tools.domain import contract, dispatch, slim
from aot.tools.domain.registry import find_op
from aot.tools.domain.registry_data import OPS


def _out(body):
    return [{'type': 'text', 'text': json.dumps(body)}]


def _body(out):
    return json.loads(out[0]['text'])


class SlimTest(unittest.TestCase):

    def test_registry_still_keeps_the_contract(self):
        self.assertEqual([], contract.problems())

    def test_programs_rows_lose_their_text(self):
        row = {'unique_id': 'p1', 'name': '고추', 'kind': 'vegetation', 'subject': 'pepper', 'variety': None,
               'source': 'user', 'source_note': 'x' * 500, 'notes': 'n' * 500, 'guidance_text': 'g' * 500,
               'stage_count': 4, 'total_days': 120, 'tab_id': 't', 'usable_for_control': True, 'editable': True,
               'derived_from': None, 'reviewed_at': None, 'version': 1, 'target_methods': {}}
        got = _body(slim.apply(_out({'status': 'success', 'count': 1, 'programs': [row]}), 'programs', {}))
        r = got['programs'][0]
        self.assertEqual(('p1', '고추', 4, 120), (r['unique_id'], r['name'], r['stage_count'], r['total_days']))
        for k in ('source_note', 'notes', 'guidance_text'):
            self.assertNotIn(k, r)
        self.assertIn('detail.program', got['omitted'])

    def test_widget_schema_only_on_request(self):
        base = {'status': 'success', 'widget': {'widget_id': 'w', 'options': {'a': 1}, 'option_schema': [{'id': 'a'}] * 3}}
        no = _body(slim.apply(_out(json.loads(json.dumps(base))), 'widget', {}))
        self.assertNotIn('option_schema', no['widget'])
        self.assertIn("fields=['schema']", no['omitted'])
        yes = _body(slim.apply(_out(json.loads(json.dumps(base))), 'widget', {'fields': ['schema']}))
        self.assertEqual(3, len(yes['widget']['option_schema']))
        allf = _body(slim.apply(_out(json.loads(json.dumps(base))), 'widget', {'fields': 'all'}))
        self.assertIn('option_schema', allf['widget'])

    def test_map_equipment_default_is_counts_and_totals(self):
        base = {'status': 'success', 'sprinkler_count': 2, 'sprinklers': [[1, 2], [3, 4]],
                'sprinklers_format': 'x', 'drip_pipes': [{'pipe': 'a'}],
                'pipes': [{'name': 'a', 'sub_type': 'pipe_main', 'length_m': 10.0},
                          {'name': 'b', 'sub_type': 'pipe_branch', 'length_m': 5.5},
                          {'name': 'c', 'sub_type': 'pipe_branch', 'length_m': 4.5}]}
        got = _body(slim.apply(_out(json.loads(json.dumps(base))), 'map_equipment', {}))
        self.assertNotIn('sprinklers', got)
        self.assertEqual({'count': 2, 'length_m': 10.0}, got['pipes']['pipe_branch'])
        self.assertEqual(1, len(got['drip_pipes']))
        full = _body(slim.apply(_out(json.loads(json.dumps(base))), 'map_equipment', {'fields': ['sprinklers', 'pipes']}))
        self.assertEqual(2, len(full['sprinklers']))
        self.assertEqual(3, len(full['pipes']))

    def test_paging(self):
        base = {'status': 'success', 'count': 5, 'tabs': list(range(5))}
        got = _body(slim.apply(_out(dict(base)), 'page', {'limit': 2}))
        self.assertEqual([0, 1], got['tabs'])
        self.assertEqual((True, 5, 2), (got['truncated'], got['total'], got['next_offset']))
        nxt = _body(slim.apply(_out(dict(base)), 'page', {'limit': 2, 'offset': 4}))
        self.assertEqual([4], nxt['tabs'])
        self.assertNotIn('truncated', nxt)
        whole = _body(slim.apply(_out(dict(base)), 'page', {}))
        self.assertEqual(5, len(whole['tabs']))
        self.assertNotIn('truncated', whole)

    def test_device_types_page_keeps_kind(self):
        """find.device_types — 입력 종류 200개 가까이가 한 번에 나가던 것(약 1만 자)을 쪽으로 나눈다."""
        base = {'kind': 'input', 'types': [{'type': 'T%d' % i, 'name': 'n', 'interfaces': None} for i in range(7)]}
        got = _body(slim.apply(_out(json.loads(json.dumps(base))), find_op(OPS, 'find', 'device_types').slim,
                               {'limit': 3}))
        self.assertEqual(('input', ['T0', 'T1', 'T2']), (got['kind'], [t['type'] for t in got['types']]))
        self.assertEqual((True, 7, 3), (got['truncated'], got['total'], got['next_offset']))

    def test_errors_pass_through(self):
        err = _out({'status': 'error', 'message': 'x'})
        self.assertEqual(err, slim.apply(err, 'programs', {}))


class PlanTest(unittest.TestCase):

    def test_limit_is_taken_not_rejected_and_not_sent_inside(self):
        for tool, op in (('find', 'programs'), ('find', 'tabs'), ('find', 'lookup_sources'), ('find', 'widget_types'),
                         ('find', 'gis_inputs'), ('find', 'ai_agents'), ('records', 'ai_entries'),
                         ('find', 'device_types')):
            args = {'op': op, 'limit': 3, 'offset': 1}
            if op == 'tabs':
                args['page_type'] = 'dashboard'
            if op == 'device_types':
                args['kind'] = 'input'
            verdict = dispatch.plan(tool, args)
            self.assertEqual('call', verdict[0], (op, verdict))
            inner_args = verdict[2]
            self.assertNotIn('limit', inner_args)
            self.assertEqual({'limit': 3, 'offset': 1}, inner_args[dispatch.META_KEY]['slim'])

    def test_fields_on_widget_detail(self):
        o = find_op(OPS, 'detail', 'widget')
        self.assertIn('fields', o.args)
        self.assertEqual('widget', o.slim)


if __name__ == '__main__':
    unittest.main()
