# coding=utf-8
"""2026-11-03 MCP 수정 S3 #7 — help 가 모르는 op 일 때 후보·전체 목록, 가짜 help.op 없음, 효과 이름 통일."""
import unittest

from aot.tools.domain import dispatch
from aot.tools.domain.registry_data import OPS


class UnknownOperation(unittest.TestCase):

    def setUp(self):
        dispatch._INNER_TO_OP.clear()
        self.addCleanup(dispatch._INNER_TO_OP.clear)

    def test_nothing_matched_lists_every_tool_in_full(self):
        card = dispatch.help_card('zzzz', ops=OPS)
        self.assertEqual('error', card['status'])
        ops = card['operations']
        self.assertEqual(sorted({o.tool for o in OPS if o.tool != 'help'}), sorted(ops))
        total = sum(len(v) for v in ops.values())
        self.assertEqual(len([o for o in OPS if o.tool != 'help']), total)    # 60 에서 자르지 않는다
        self.assertIn('find.devices', card['next'])

    def test_word_in_a_name_or_use_gives_a_flat_closest_first_list(self):
        card = dispatch.help_card('humidity forecast', ops=OPS)
        self.assertIsInstance(card['operations'], list)
        self.assertTrue(card['operations'])

    def test_known_tool_with_a_wrong_op_lists_that_tools_ops(self):
        card = dispatch.help_card('control.fan', ops=OPS)
        want = ['control.%s' % o.op for o in OPS if o.tool == 'control']
        self.assertEqual(want, [n for n in card['operations'] if n.startswith('control.')][:len(want)])

    def test_overview_has_no_fake_help_op(self):
        card = dispatch.help_card('', ops=OPS)
        self.assertNotIn('help', card['tools'])

    def test_effect_name_matches_the_tool_list(self):
        card = dispatch.help_card('remove.delete')
        self.assertEqual('setup', card['effect'])


if __name__ == '__main__':
    unittest.main()
