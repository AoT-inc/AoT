# coding=utf-8
"""2026-11-03 MCP 수정 S5 A — 여러 곳을 묶어 읽으면 대상마다 오고, 첫 건만 오지 않는다.

실측: overview.place 에 두 곳을 주면 첫 곳만 왔고 둘째는 표시 없이 빠졌다(안쪽 도구가 대상 하나만 받는데 틀이 `vals[0]` 만 넘김).
"""
import json
import unittest
from unittest import mock

from aot.tools.domain import dispatch
from aot.tools.domain.registry_data import OPS


def _res(kind):
    def res(ref, accepts=(), only=None):
        return 'ok', {'kind': kind, 'id': 'id-' + ref, 'name': ref, 'path': 'M > ' + ref}
    return res


def _plan(tool, args, kind='site'):
    with mock.patch.object(dispatch.targets, 'resolve', _res(kind)):
        return dispatch.plan(tool, args, ops=list(OPS))


class ReadListGoesPerTarget(unittest.TestCase):

    def test_one_target_inner_gets_one_call_per_target(self):
        v = _plan('overview', {'op': 'place', 'target': ['1포장', '2포장']})
        self.assertEqual(('fanout',), v[:1])
        self.assertTrue(v[3].get('per_target'))
        self.assertEqual(['1포장', '2포장'], [c['name'] for c, _a in v[2]])
        # 대상마다 자기 id 한 건씩 — 첫 건만 넘기지 않는다
        self.assertEqual(2, len({json.dumps(a, sort_keys=True, default=str) for _c, a in v[2]}))

    def test_json_string_list_works_too(self):
        v = _plan('overview', {'op': 'place', 'target': '["1포장","2포장"]'})
        self.assertEqual('fanout', v[0])
        self.assertEqual(2, len(v[2]))

    def test_same_target_twice_is_one_call(self):
        v = _plan('overview', {'op': 'place', 'target': ['1포장', '1포장']})
        self.assertEqual('call', v[0])

    def test_list_taking_inner_still_one_call(self):
        v = _plan('measure', {'op': 'latest', 'target': ['1포장', '2포장']})
        self.assertEqual('call', v[0])
        self.assertEqual(2, len([x for a in v[2].values() if isinstance(a, list) for x in a]))

    def test_over_the_limit_is_refused_loudly(self):
        v = _plan('overview', {'op': 'place', 'target': ['a', 'b', 'c', 'd', 'e', 'f']})
        self.assertEqual('refuse', v[0])
        self.assertIn('too_many_targets', v[1][0]['text'])

    def test_every_one_target_read_op_fans_out(self):
        # 읽기 op 중 안쪽이 대상 하나만 받는 것은 전부 목록에서 대상별로 간다(표: plans/mcp_fix_s5_report.md)
        from aot.tools.domain.registry import READ_TOOLS, leaves
        from aot.tools.domain.dispatch import _arg_is_list
        checked = 0
        for o in OPS:
            if o.tool not in READ_TOOLS:
                continue
            for _k, l in leaves(o):
                for kind, inner in l.inner.items():
                    ta = l.target_arg.get(kind)
                    if kind == 'none' or not ta or _arg_is_list(inner, ta):
                        continue
                    args = {'op': l.op, 'target': ['a', 'b']}
                    for r in l.required:
                        args.setdefault(r, 'x')
                    with mock.patch.object(dispatch.targets, 'resolve', _res(kind)):
                        v = dispatch.plan(l.tool, args, ops=list(OPS))
                    if v[0] == 'refuse':
                        continue                      # 필수 인자 따위로 거절 — 이 시험의 대상이 아님
                    self.assertEqual('fanout', v[0], '%s.%s %s' % (l.tool, l.op, kind))
                    checked += 1
        self.assertGreater(checked, 20)


class RunsEveryTarget(unittest.TestCase):

    def test_each_target_result_comes_back_with_its_name(self):
        seen = []

        def fake(app, inner, args, **kw):
            seen.append((inner, args))
            name = args.get('target_name') or args.get('place_id') or str(sorted(args.items()))
            return [{'type': 'text', 'text': json.dumps({'status': 'success', 'place': name})}]
        with mock.patch.object(dispatch.targets, 'resolve', _res('site')), \
                mock.patch('aot.tools.tool_execution._execute_tool', fake):
            out = dispatch._run_call_inner(
                None, 'overview', {'op': 'place', 'target': ['1포장', '2포장']}, {}, 'off', None)
        body = json.loads(out[0]['text'])
        self.assertEqual('success', body['status'])
        self.assertEqual(['1포장', '2포장'], [r['target']['name'] for r in body['results']])
        self.assertEqual(2, len(seen))
        self.assertEqual(2, len({json.dumps(a, sort_keys=True, default=str) for _i, a in seen}))
