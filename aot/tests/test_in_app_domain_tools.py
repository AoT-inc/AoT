# -*- coding: utf-8 -*-
"""인앱 AI 의 도구 표면 = 도메인 명부 하나(아키텍처 개선 26-11 5단계).

지키는 것:
- 인앱 매니페스트의 도구 항목은 도메인 도구 + 제어 흐름 셋뿐이다(옛 도구 매니페스트 없음).
- 도메인 쓰기의 승인 판정은 **안쪽 도구**로 한다 — 이름(`control`)만 보면 승인 집합에
  없어서 엔진의 자체 도구 루프가 장치 제어를 승인 없이 실행하려 든다.
- 승인이 필요한 쓰기는 안쪽 도구 호출로 바뀌어 지금의 인앱 승인 경로를 탄다.
- 나머지(읽기 등)는 도구 실행층으로 간다.
"""
import unittest
from unittest import mock

from aot.ai.services import in_app_tools
from aot.tools.domain import dispatch
from aot.tools.domain.registry import DOMAIN_TOOLS


def _plan_returning(verdict):
    return mock.patch.object(dispatch, 'plan', return_value=verdict)


class TestManifestEntries(unittest.TestCase):

    def test_control_flow_entries_only_in_registry_manifest(self):
        from aot.tools import tool_registry as R
        names = {e.get('tool_name') or e.get('action_type')
                 for e in R.manifest_system_tools()}
        self.assertEqual(names, {'read_manual', 'get_detailed_manifest', 'ask_user'})

    def test_domain_entries_shape(self):
        fake = [{"name": "find", "description": "Find things.\nop:\ndevices — x",
                 "inputSchema": {"type": "object", "required": ["op"], "properties": {
                     "op": {"type": "string", "enum": ["devices", "tree"]},
                     "target": {"description": "Name or id"}}}}]
        with mock.patch('aot.tools.tool_execution.tools_for_agent', return_value=fake):
            out = in_app_tools.domain_tool_entries(app=object())
        self.assertEqual(out[0]['tool_name'], 'find')
        self.assertNotIn('action_type', out[0])
        self.assertIn('op*: devices|tree', out[0]['usage_hint'])
        self.assertIn('target: Name or id', out[0]['usage_hint'])
        # 설명을 자르지 않는다 — operation 목록이 설명 안에 있다.
        self.assertEqual(out[0]['description'], fake[0]['description'])

    def test_listing_failure_is_empty_not_raise(self):
        with mock.patch('aot.tools.tool_execution.tools_for_agent',
                        side_effect=RuntimeError('boom')):
            self.assertEqual(in_app_tools.domain_tool_entries(app=object()), [])


class TestApprovalFollowsInnerTool(unittest.TestCase):

    def test_read_tools_never_need_approval(self):
        from aot.ai.services.ai_action_service import AIActionService
        for t in ('find', 'measure', 'overview', 'weather', 'detail', 'records'):
            self.assertFalse(AIActionService.requires_approval(t, {'op': 'x'}), t)

    def test_write_tool_without_arguments_is_gated(self):
        from aot.ai.services.ai_action_service import AIActionService
        self.assertTrue(AIActionService.requires_approval('control'))
        self.assertFalse(AIActionService.requires_approval('find'))

    def test_physical_inner_needs_approval(self):
        from aot.ai.services.ai_action_service import AIActionService
        verdict = ('call', 'operate_device',
                   {'device_id': 'D1', 'state': 'on', dispatch.SNAPSHOT_KEY: {'x': 1}})
        with _plan_returning(verdict):
            self.assertTrue(AIActionService.requires_approval(
                'control', {'op': 'device_set', 'target': '펌프', 'state': 'on'}))
            # 엔진 어댑터가 한 겹 더 싼 모양도 같다.
            self.assertTrue(AIActionService.requires_approval(
                'control', {'arguments': {'op': 'device_set', 'target': '펌프'}}))

    def test_record_write_without_approval_goes_direct(self):
        with _plan_returning(('call', 'create_note', {'content': 'x'})):
            self.assertEqual(in_app_tools.plan('record', {'op': 'note'}), ('direct',))

    def test_refusal_goes_direct(self):
        with _plan_returning(('refuse', [{'type': 'text', 'text': '{}'}])):
            self.assertEqual(in_app_tools.plan('control', {'op': 'device_set'}), ('direct',))

    def test_plan_failure_is_gated_not_executed(self):
        with mock.patch.object(dispatch, 'plan', side_effect=RuntimeError('db')):
            self.assertEqual(in_app_tools.plan('control', {'op': 'device_set'})[0], 'error')
            self.assertTrue(in_app_tools.requires_approval('control', {'op': 'device_set'}))


class TestNormalize(unittest.TestCase):

    def test_approval_write_becomes_inner_call(self):
        action = {'tool_name': 'control',
                  'params': {'arguments': {'op': 'device_set', 'target': '펌프', 'state': 'on'}}}
        verdict = ('call', 'operate_device', {'device_id': 'D1', 'state': 'on',
                                              dispatch.SNAPSHOT_KEY: {'id': 'D1'},
                                              dispatch.META_KEY: {'m': 1}})
        with _plan_returning(verdict):
            out = in_app_tools.normalize(action, 'control')
        self.assertIsNone(out)
        self.assertEqual(action['params'], {'tool_name': 'operate_device',
                                            'arguments': {'device_id': 'D1', 'state': 'on'}})
        self.assertNotIn('action_type', action)

    def test_multi_target_approval_write_is_refused(self):
        action = {'params': {'tool_name': 'control', 'arguments': {'op': 'device_set'}}}
        with _plan_returning(('fanwrite', 'operate_device', [], {})):
            ok, msg = in_app_tools.normalize(action, 'control')
        self.assertFalse(ok)
        self.assertIn('once per target', msg)

    def test_read_goes_to_execution_layer(self):
        action = {'params': {'tool_name': 'find', 'arguments': {'op': 'devices'}}}
        self.assertEqual(in_app_tools.normalize(action, 'find'), (True, 'OK'))
        self.assertEqual(action['action_type'], 'virtual_tool_call')
        self.assertEqual(action['params']['tool_name'], 'find')
        self.assertEqual(action['params']['arguments'], {'op': 'devices'})

    def test_routing_normalizes_domain_names(self):
        from aot.ai.ai_routing_service import AIRoutingService
        action = {'tool_name': 'measure', 'params': {'arguments': {'op': 'latest'}}}
        self.assertEqual(AIRoutingService._validate_and_normalize_action(action), (True, 'OK'))
        self.assertEqual(action['action_type'], 'virtual_tool_call')

    def test_other_mcp_servers_same_name_untouched(self):
        """사용자가 등록한 다른 MCP 서버의 'find' 는 그 서버로 간다."""
        from aot.ai.ai_routing_service import AIRoutingService
        action = {'action_type': 'mcp_tool_call', 'target_id': 'other-server',
                  'params': {'tool_name': 'find', 'arguments': {'q': 'x'}}}
        with mock.patch('aot.ai.ai_routing_service._is_builtin_mcp', return_value=False), \
                mock.patch.object(in_app_tools, 'normalize') as norm:
            AIRoutingService._validate_and_normalize_action(action)
        norm.assert_not_called()
        self.assertEqual(action['action_type'], 'mcp_tool_call')

    def test_virtual_resolver_runs_domain_tools_via_execution_layer(self):
        from aot.ai.services.resolvers.virtual_tool_resolver import VirtualToolResolver
        with mock.patch.object(in_app_tools, 'run',
                               return_value={'status': 'success', 'result': {}}) as run:
            res = VirtualToolResolver().execute(
                'virtual_tool_call', 'system_internal',
                {'tool_name': 'find', 'arguments': {'op': 'devices'}}, None)
        run.assert_called_once()
        self.assertEqual(run.call_args[0][:2], ('find', {'op': 'devices'}))
        self.assertEqual(res['status'], 'success')


class TestUnnormalizedApprovalWriteIsNotRun(unittest.TestCase):

    def test_run_refuses_approval_write(self):
        with _plan_returning(('call', 'operate_device', {'device_id': 'D1'})), \
                mock.patch('aot.tools.tool_execution.execute_for_agent') as ex:
            res = in_app_tools.run('control', {'op': 'device_set'})
        ex.assert_not_called()
        self.assertEqual(res['reason_code'], 'needs_approval')


class TestDomainNamesDoNotCollideWithLegacy(unittest.TestCase):

    def test_no_overlap(self):
        from aot.tools.tool_registry import virtual_tool_registry
        self.assertFalse(set(DOMAIN_TOOLS) & set(virtual_tool_registry()))


if __name__ == '__main__':
    unittest.main()
