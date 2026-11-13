# coding=utf-8
"""2026-11-03 MCP 점검 D1 — find.controllable · control.output_timed 를 외부 연결에서 쓸 수 있게 되살린다.

안쪽 도구(list_available_devices · set_output_state)가 퇴역이라 두 operation 이 어느 묶음 목록에도 안 떴다.
되살리는 길은 도메인 operation 뿐이다: 옛 tools/list 에는 여전히 없고, 이름으로 직접 부르면 예전처럼 묶음 밖 거절이다.
"""
import json
import unittest
from unittest import mock

from aot.tools import tool_execution as te
from aot.tools import tool_registry as R

OPS, CFG = R.TOOL_PROFILE_OPERATIONS, 'configuration'


class DomainRouteTest(unittest.TestCase):

    def test_the_two_operations_are_listed_for_keys(self):
        from aot.tools.domain import surface
        from aot.tools.domain.registry_data import OPS as REGISTRY
        for prof in (OPS, CFG):
            p = te._effective_profile(prof)
            ent = surface.entries(REGISTRY, lambda n: R.tool_in_profile(n, p, via_domain=True),
                                  set(R.approval_required_tools()))
            by = {e['name']: e['description'] for e in ent}
            self.assertIn('controllable —', by['find'], prof)
            self.assertIn('output_timed —', by['control'], prof)

    def test_direct_calls_by_name_stay_refused_for_keys(self):
        for name in ('set_output_state', 'list_available_devices'):
            self.assertFalse(R.tool_in_profile(name, OPS), name)
            self.assertIsNotNone(te._profile_refusal(name, OPS, 'mcp_http'), name)
            self.assertIsNone(te._profile_refusal(name, OPS, 'mcp_http', via_domain=True), name)

    def test_only_those_two_open_through_the_domain_route(self):
        self.assertFalse(R.tool_in_profile('create_function', OPS, via_domain=True))
        self.assertTrue(R.tool_in_profile('operate_device', OPS, via_domain=True))
        self.assertEqual({'set_output_state', 'list_available_devices'}, set(R.DOMAIN_ROUTED_TOOLS))

    def test_the_legacy_listing_still_omits_them(self):
        for name in R.DOMAIN_ROUTED_TOOLS:
            self.assertTrue(R.is_retired_from_mcp(name))


class TimedRunTest(unittest.TestCase):

    def _run(self, **params):
        from flask import Flask
        from aot.tools.aot_native_tool_engine import AoTNativeToolEngine as N
        from aot.tools.aot_data_tool_service import AoTDataToolService as S
        out_row = mock.Mock(unique_id='o1')
        action = mock.Mock()
        action.execute_action.return_value = {'status': 'success'}
        with Flask('t').app_context(), \
                mock.patch.object(S, '_read_device', return_value=(out_row, 'output', None)), \
                mock.patch('aot.aot_flask.access.write_scope.enforce'), \
                mock.patch('aot.tools.providers.get', return_value=action):
            res = N._exec_set_output_state(dict(params, device_id='o1', state='on'))
        return res, action

    def test_duration_seconds_is_the_run_time(self):
        res, action = self._run(duration_seconds='30')
        self.assertEqual('success', res['status'])
        self.assertEqual(30, action.execute_action.call_args.args[2]['duration_seconds'])

    def test_legacy_duration_still_works_and_none_means_indefinite(self):
        _, action = self._run(duration=45)
        self.assertEqual(45, action.execute_action.call_args.args[2]['duration_seconds'])
        _, action = self._run()
        self.assertEqual(0, action.execute_action.call_args.args[2]['duration_seconds'])

    def test_a_bad_run_time_is_an_error_before_dispatch(self):
        res, action = self._run(duration_seconds='abc')
        self.assertEqual('error', res['status'])
        self.assertIs(res['dispatched'], False)
        action.execute_action.assert_not_called()

    def test_handler_param_is_declared_and_the_approval_note_reads_it(self):
        from aot.tools.aot_native_tool_engine import AoTNativeToolEngine as N
        from aot.utils import water_estimate
        self.assertIn('duration_seconds', N.HANDLER_PARAMS['set_output_state'])
        self.assertEqual(30.0, water_estimate._seconds_of(
            'set_output_state', {'state': 'on', 'duration_seconds': 30}))


if __name__ == '__main__':
    unittest.main()
