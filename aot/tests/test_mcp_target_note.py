# coding=utf-8
"""target 인자 설명이 실제와 맞는다 — 2026-10-30 claude.ai 체험 피드백 3-1.

예전 설명은 "a list for several (reads)" 였다. 실제로는 읽기와 control.device_set(PR #377)이 여러 개를 받고,
설정 쓰기는 한 번에 하나다(dispatch.plan: "ONE target per call"). 표면의 설명이 도구별로 그 사실을 말하고,
말한 대로 실제로 거절·허용되는지 함께 본다.
"""
import json
import unittest
from unittest import mock


def _targets():
    from aot.tools import tool_registry as R
    from aot.tools.domain import surface
    from aot.tools.domain.registry_data import OPS
    ents = surface.entries(OPS, lambda n: True, set(R.approval_required_tools()))
    return {e['name']: e['inputSchema']['properties'].get('target', {}).get('description')
            for e in ents}


class TargetNoteTest(unittest.TestCase):

    def test_reads_say_a_list_is_fine(self):
        got = _targets()
        for tool in ('overview', 'measure', 'weather', 'find', 'detail', 'records'):
            self.assertIn('a list for several', got[tool], tool)

    def test_plain_writes_say_one_per_call(self):
        got = _targets()
        for tool in ('cultivate', 'remove', 'screen'):
            if got.get(tool):
                self.assertIn('one per call', got[tool], tool)
                self.assertNotIn('list', got[tool], tool)

    def test_writes_with_a_list_op_name_it(self):
        got = _targets()
        self.assertIn('device_set', got['control'])
        self.assertIn('sequence_create', got['configure'])

    def test_old_misleading_wording_is_gone(self):
        for tool, text in _targets().items():
            self.assertNotIn('(reads)', text or '', tool)

    def test_the_wording_matches_what_plan_does(self):
        from aot.tools.domain import dispatch
        from aot.tools.domain.registry_data import OPS

        def resolve(ref, **kw):
            return 'ok', {'kind': 'input', 'id': 'id-%s' % ref, 'name': str(ref),
                          'path': 'map > %s' % ref, 'matched': 'exact'}
        with mock.patch.object(dispatch.targets, 'resolve', resolve), \
                mock.patch.object(dispatch.targets, 'snapshot', lambda t: {}):
            # 설정 쓰기는 둘을 주면 거절 — 문구가 "one per call" 이라고 한 이유.
            v = dispatch.plan('configure', {'op': 'input_edit', 'target': ['a', 'b'], 'name': 'x'})
        self.assertEqual('refuse', v[0])
        self.assertEqual('single_target_only', json.loads(v[1][0]['text'])['reason_code'])
        # 문구가 이름 댄 operation 은 정말 여러 개를 받는다.
        named = {(o.tool, o.op) for o in OPS if o.expand_write or o.fan_write}
        self.assertIn(('control', 'device_set'), named)
        self.assertIn(('configure', 'sequence_create'), named)


if __name__ == '__main__':
    unittest.main()
