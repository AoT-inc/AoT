# coding=utf-8
"""숨은 op 별칭 — measure.now 는 measure.latest 다 (2026-10-30 claude.ai 체험 피드백 3-3).

모델이 "지금 값" 을 보고 `now` 를 짐작한다. 목록·스키마·help 의 이름 목록에는 올리지 않아(토큰 0) 정식 이름만 보이고,
짐작한 이름은 받아 준다.
"""
import json
import unittest
from unittest import mock


def _plan(tool, args, kind='input'):
    from aot.tools.domain import dispatch

    def resolve(ref, **kw):
        return 'ok', {'kind': kind, 'id': 'id-1', 'name': str(ref),
                      'path': 'map > %s' % ref, 'matched': 'exact'}
    with mock.patch.object(dispatch.targets, 'resolve', resolve), \
            mock.patch.object(dispatch.targets, 'snapshot', lambda t: {}):
        return dispatch.plan(tool, args)


class OpAliasTest(unittest.TestCase):

    def test_now_plans_exactly_like_latest(self):
        a = _plan('measure', {'op': 'now', 'target': '3-1', 'measurement': 'temperature'})
        b = _plan('measure', {'op': 'latest', 'target': '3-1', 'measurement': 'temperature'})
        self.assertEqual('call', a[0], a)
        self.assertEqual(b, a)

    def test_unknown_names_are_still_unknown(self):
        v = _plan('measure', {'op': 'right_now', 'target': '3-1'})
        self.assertEqual('refuse', v[0])
        self.assertEqual('unknown_op', json.loads(v[1][0]['text'])['reason_code'])

    def test_aliases_point_at_real_ops_and_are_not_in_the_registry(self):
        from aot.tools.domain import renames
        from aot.tools.domain.registry import find_op
        from aot.tools.domain.registry_data import OPS
        for (tool, alias), real in renames.OP_ALIASES.items():
            self.assertIsNotNone(find_op(OPS, real.tool or tool, real.op), (tool, alias))
            self.assertIsNone(find_op(OPS, tool, alias), (tool, alias))

    def test_the_alias_costs_no_tokens_it_is_not_listed_anywhere(self):
        from aot.tools import tool_registry as R
        from aot.tools.domain import surface
        from aot.tools.domain.registry_data import OPS
        ents = surface.entries(OPS, lambda n: True, set(R.approval_required_tools()))
        measure = next(e for e in ents if e['name'] == 'measure')
        self.assertNotIn('now', measure['inputSchema']['properties']['op']['enum'])
        self.assertNotIn('\nnow ', measure['description'])

    def test_help_accepts_the_alias(self):
        from aot.tools.domain import dispatch
        card = dispatch.help_card('measure.now')
        self.assertEqual('success', card['status'], card)
        self.assertEqual(dispatch.help_card('measure.latest'), card)

    def test_run_normalises_the_op_for_everything_after_the_plan(self):
        # 응답 계약·서버 카드는 arguments['op'] 를 본다 — 별칭이 끝까지 가도 정식 이름으로 보인다.
        from aot.tools.domain import dispatch
        seen = {}

        def inner(app, tool, arguments, ctx, show, answer_time):
            seen['op'] = arguments.get('op')
            return [{'type': 'text', 'text': '{"status": "success"}'}]
        with mock.patch.object(dispatch, '_run_call_inner', inner):
            dispatch._run_call(None, 'measure', {'op': 'now', 'target': 'x'},
                               {'scope_user_uuid': 'u', 'transport': 'mcp_http'})
        self.assertEqual('latest', seen['op'])


if __name__ == '__main__':
    unittest.main()
