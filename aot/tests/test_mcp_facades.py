# coding=utf-8
"""MCP 묶음 도구(tool_registry.MCP_FACADES) — 목록은 줄이고 실행은 그대로.

묶음 도구는 안쪽 도구로 위임하는 껍데기다. 그래서 지켜야 할 것은 셋이다.

  1. 광고한 것만 부를 수 있다 — operation·인자가 안쪽 도구의 스키마와 맞고,
     그 키가 쓸 수 없는 operation 은 목록에 없다.
  2. 승인 큐·감사에는 **안쪽 도구 이름**이 남는다(사람이 무엇을 승인하는지 안다).
  3. 묶음·역할 판정은 안쪽 도구 기준이다 — 묶음 도구로 감싸 부른다고 넓어지지 않는다.
"""
import json
import os
import unittest
from unittest import mock

from aot.tests.test_mcp_tool_profiles import CFG, OPS, R, _AppFixture, _PREFIX


def _inner_payload(name):
    for p in R._MCP_TOOL_PAYLOADS:
        if p['tool_name'] == name:
            return p
    raise AssertionError('%s 가 MCP 카탈로그에 없다' % name)


class FacadeDeclarationTest(unittest.TestCase):
    """선언만으로 판정한다(앱 없음)."""

    def test_operations_are_real_catalogued_tools(self):
        for name, spec in R.MCP_FACADES.items():
            self.assertNotIn(name, R._BY_NAME, '묶음 이름이 실제 도구 이름과 겹친다')
            for op in spec['operations']:
                with self.subTest(facade=name, op=op):
                    self.assertTrue(R.is_declared_tool(op))
                    _inner_payload(op)
                    self.assertEqual(name, R.facade_of(op))

    def test_advertised_arguments_are_accepted_by_the_inner_tool(self):
        """광고한 인자는 안쪽 도구가 받는다 — 아니면 고른 operation 이 인자 검사에서
        거절된다. 안쪽 도구의 필수 인자도 전부 광고한다."""
        for name, spec in R.MCP_FACADES.items():
            for op, (_text, op_args) in spec['operations'].items():
                inner = _inner_payload(op)['input_schema']
                offered = set(spec['common']) | set(op_args)
                with self.subTest(facade=name, op=op):
                    self.assertLessEqual(offered, set(inner['properties']))
                    self.assertLessEqual(set(inner.get('required', [])), offered)

    def test_same_approval_class_inside_a_family(self):
        """승인 성격이 다른 도구를 한 묶음에 넣지 않는다 — 넣으면 설명 한 줄
        ("Requires human approval")이 일부 operation 에 거짓말이 된다."""
        from aot.tools import mcp_safety_gate as gate
        for name, spec in R.MCP_FACADES.items():
            kinds = {(gate.classify_permission(op),
                      op in gate.approval_tools())
                     for op in spec['operations']}
            self.assertEqual(1, len(kinds), (name, kinds))

    def test_payload_carries_only_the_chosen_operations(self):
        p = R.facade_payload('plot_stage', ['undo_plot_stage'])
        props = p['input_schema']['properties']
        self.assertEqual(['undo_plot_stage'], props['operation']['enum'])
        self.assertEqual({'operation', 'plot_id'}, set(props))
        self.assertNotIn('add_plot_stage', p['description'])
        self.assertIsNone(R.facade_payload('plot_stage', []))

    def test_full_payload_is_smaller_than_the_members(self):
        from aot.tools.tool_execution import _estimate_tokens
        for name, spec in R.MCP_FACADES.items():
            whole = _estimate_tokens(json.dumps(R.facade_payload(name),
                                                ensure_ascii=False))
            parts = _estimate_tokens(json.dumps(
                [_inner_payload(op) for op in spec['operations']],
                ensure_ascii=False))
            self.assertLess(whole, parts * 0.6, (name, whole, parts))


class FacadeListingTest(_AppFixture):

    def _tools(self, role, profile):
        from aot.tools import tool_execution as te
        return {t['name']: t for t in te._get_all_tools(
            self.app, role=role, tiered=False, profile=profile)}

    def _ops(self, tools):
        return set(tools['plot_stage']['inputSchema']['properties']
                   ['operation']['enum'])

    def test_operations_key_gets_its_three(self):
        tools = self._tools(self._auth(self._issue('Editor', 'full', OPS)), OPS)
        self.assertEqual({'confirm_plot_stage', 'reschedule_plot_stage',
                          'undo_plot_stage'}, self._ops(tools))
        props = tools['plot_stage']['inputSchema']['properties']
        self.assertNotIn('name', props)          # add_plot_stage 전용 인자
        for op in R.MCP_FACADES['plot_stage']['operations']:
            self.assertNotIn(op, tools)

    def test_configuration_key_gets_all_six(self):
        tools = self._tools(self._auth(self._issue('Editor', 'full', CFG)), CFG)
        self.assertEqual(set(R.MCP_FACADES['plot_stage']['operations']),
                         self._ops(tools))

    def test_readonly_key_gets_no_facade(self):
        tools = self._tools(self._auth(self._issue('Editor', 'readonly', CFG)), CFG)
        self.assertNotIn('plot_stage', tools)

    def test_schedule_add_carries_both_and_hides_from_readonly(self):
        tools = self._tools(self._auth(self._issue('Editor', 'full', OPS)), OPS)
        ops = set(tools['schedule_add']['inputSchema']['properties']
                  ['operation']['enum'])
        self.assertEqual({'add_schedule', 'add_schedule_batch'}, ops)
        self.assertNotIn('add_schedule', tools)
        self.assertIn('edit_schedule', tools)       # 승인 필요 — 묶지 않았다
        ro = self._tools(self._auth(self._issue('Editor', 'readonly', OPS)), OPS)
        self.assertNotIn('schedule_add', ro)

    def test_single_visible_operation_lists_the_original_tool(self):
        """운영 키의 공지 쓰기는 create_notice 하나 — 묶음으로 내면 원래보다 크다."""
        ops_tools = self._tools(self._auth(self._issue('Editor', 'full', OPS)), OPS)
        self.assertIn('create_notice', ops_tools)
        self.assertNotIn('notice', ops_tools)
        original = _inner_payload('create_notice')
        self.assertEqual(original['description'],
                         ops_tools['create_notice']['description'])
        cfg = self._tools(self._auth(self._issue('Editor', 'full', CFG)), CFG)
        self.assertEqual({'create_notice', 'modify_notice', 'delete_notice'},
                         set(cfg['notice']['inputSchema']['properties']
                             ['operation']['enum']))
        self.assertNotIn('create_notice', cfg)

    def test_switch_off_lists_the_members(self):
        role = self._auth(self._issue('Editor', 'full', OPS))
        with mock.patch.dict(os.environ, {'AOT_MCP_FACADES': '0'}):
            tools = self._tools(role, OPS)
        self.assertNotIn('plot_stage', tools)
        self.assertIn('confirm_plot_stage', tools)
        self.assertNotIn('add_plot_stage', tools)

    def test_drawer_hands_out_the_real_tools(self):
        from aot.tools import tool_execution as te
        names = te._drawer_contents(self.app, role=self._auth(
            self._issue('Editor', 'full', CFG)), profile=CFG)
        self.assertIn('add_plot_stage', names)
        self.assertNotIn('plot_stage', names)


class FacadeDispatchTest(_AppFixture):

    _PLOT = '00000000-0000-4000-8000-0000000000aa'

    def _call(self, role, args):
        from aot.tools import mcp_auth
        from aot.tools import tool_execution as te
        out = te._execute_tool(self.app, 'plot_stage', dict(args),
                               agent_id='user:%s' % _PREFIX.lower(), role=role,
                               scope_user_uuid=getattr(role, 'user_id', None),
                               transport='mcp_http',
                               tool_profile=mcp_auth.tool_profile_of(role))
        return json.loads(out[0]['text'])

    def test_approval_queue_and_audit_name_the_inner_tool(self):
        from aot.databases.models import MCPAuditLog, MCPConfirmation
        role = self._auth(self._issue('Editor', 'full', OPS))
        body = self._call(role, {'operation': 'undo_plot_stage',
                                 'plot_id': self._PLOT})
        self.assertEqual('pending_approval', body.get('status'), body)
        self.db.session.remove()
        conf = self._mine_confirmations().order_by(
            MCPConfirmation.id.desc()).first()
        self.assertEqual('undo_plot_stage', conf.tool_name)
        self.assertNotIn('operation', json.loads(conf.params_json or '{}'))
        # 이 시험이 남긴 행만 — 앞선 파일이 남긴 감사 행(내부 AI 등)은 우리 것이 아니다.
        rows = self._mine_audit().order_by(MCPAuditLog.id).all()
        self.assertEqual(['undo_plot_stage'], [r.tool_name for r in rows])

    def test_out_of_profile_operation_is_refused_by_the_inner_tool(self):
        role = self._auth(self._issue('Editor', 'full', OPS))
        body = self._call(role, {'operation': 'add_plot_stage',
                                 'plot_id': self._PLOT, 'name': 'x', 'days': 3})
        self.assertEqual('refused', body.get('status'), body)
        self.assertEqual('tool_profile', body.get('reason_code'))

    def test_missing_operation_names_the_choices(self):
        role = self._auth(self._issue('Editor', 'full', OPS))
        for args in ({'plot_id': self._PLOT},
                     {'operation': 'delete_everything', 'plot_id': self._PLOT}):
            body = self._call(role, args)
            text = json.dumps(body, ensure_ascii=False)
            self.assertIn('confirm_plot_stage', text)
            self.assertIn('undo_plot_stage', text)


if __name__ == '__main__':
    unittest.main()
