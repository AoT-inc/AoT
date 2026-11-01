# coding=utf-8
"""help·도구 묶음이 이 연결의 사정을 말한다 — 2026-10-28 claude.ai 점검(세션 A 항목 1·6·8).

- help 는 명부 전체를 설명하지만 목록은 이 키가 닿는 것만 싣는다. 못 부르는
  operation 이면 왜 못 부르는지(어느 모듈·지금 묶음)를 help 가 말한다
  (device_location_set 이 help 에만 있어 모델이 프로필을 두 번 바꿨다).
- help(tool_name='control') 처럼 도구 이름만 와도 operation 목록을 준다.
- tool_profile_set 의 help 에 지금 묶음과 묶음·모듈의 포함 관계를 싣는다.
- tool_profile_set 응답은 켜진 모듈을 싣고, 같은 값이면 바뀐 것이 없다고 말한다.
- 묶음 거절 문구가 이 연결 스스로 바꾸는 길(승인)도 말한다.
"""
import unittest
from unittest import mock

from aot.tools import tool_registry as R


def _editor(profile):
    from aot.tools import mcp_auth
    return mcp_auth.RoleInfo(name='Editor', can_write=True, user_id='u',
                             can_edit_settings=True, can_use_ai_chat=True,
                             can_edit_plots=True, tool_profile=profile, link_id=7)


def _ctx(profile):
    return {'tool_profile': profile, 'transport': 'mcp_http', 'role': _editor(profile)}


def _card(ref, profile=None):
    from aot.tools.domain import dispatch
    return dispatch.help_card(ref, ctx=_ctx(profile) if profile else None)


class HelpAvailabilityTest(unittest.TestCase):

    def test_op_outside_the_profile_says_which_module(self):
        card = _card('configure.device_location_set', 'operations')
        self.assertEqual('success', card['status'])
        self.assertIs(False, card['callable_here'])
        self.assertEqual('map', card['tool_module'])
        self.assertIn('configure.tool_profile_set', card['why'])
        self.assertIn('(operations)', card['why'])

    def test_op_inside_the_profile_carries_no_mark(self):
        for profile in ('configuration', 'operations+map'):
            with self.subTest(profile=profile):
                card = _card('configure.device_location_set', profile)
                self.assertNotIn('callable_here', card)

    def test_no_context_means_no_mark(self):
        self.assertNotIn('callable_here', _card('configure.device_location_set'))

    def test_role_that_blocks_it_says_switching_would_not_help(self):
        from aot.tools import mcp_auth
        from aot.tools.domain import dispatch
        viewer = mcp_auth.RoleInfo(name='Viewer', can_write=False, user_id='u',
                                   tool_profile='configuration')
        card = dispatch.help_card('configure.input_create', ctx={
            'tool_profile': 'configuration', 'transport': 'mcp_http', 'role': viewer})
        self.assertIs(False, card['callable_here'])
        self.assertIn('would not help', card['why'])
        self.assertNotIn('tool_module', card)


class ToolLevelHelpTest(unittest.TestCase):

    def test_tool_name_alone_lists_its_operations(self):
        card = _card('control', 'operations')
        self.assertEqual('success', card['status'])
        self.assertIn('function_options', card['operations'])
        self.assertEqual('automation', card['off_here']['sequence_day'])
        self.assertEqual('not offered', card['off_here']['output_timed'])
        self.assertNotIn('device_set', card['off_here'])

    def test_configuration_reaches_every_configure_op(self):
        card = _card('configure', 'configuration')
        self.assertNotIn('off_here', card)

    def test_unknown_operation_is_still_an_error(self):
        self.assertEqual('error', _card('control.nope')['status'])


class BareHelpTest(unittest.TestCase):
    # 2026-10-29 재시험: 인자 없는 help 가 'Unknown operation' 이었다.

    def test_no_target_gives_tools_and_this_connection(self):
        card = _card('', 'operations+devices')
        self.assertEqual('success', card['status'])
        self.assertIn('function_options', card['tools']['control'])
        self.assertIn('help', card['next'])
        here = card['this_connection']
        self.assertEqual('operations+devices', here['tool_profile'])
        self.assertEqual(['devices'], here['modules_on'])
        self.assertIn('map', here['modules_off'])
        self.assertIn('configure.device_location_set', card['off_here']['map'])

    def test_run_without_arguments_answers(self):
        import json
        from aot.tools.domain import dispatch
        out = dispatch.run(None, 'help', {}, **_ctx('configuration'))
        card = json.loads(out[0]['text'])
        self.assertEqual('success', card['status'])
        self.assertEqual([], card['this_connection']['modules_off'])
        self.assertNotIn('map', card.get('off_here', {}))

    def test_in_app_caller_has_no_connection_block(self):
        card = _card('')
        self.assertEqual('success', card['status'])
        self.assertNotIn('this_connection', card)


class ProfileCardTest(unittest.TestCase):

    def test_profile_help_shows_current_profile_and_relations(self):
        card = _card('configure.tool_profile_set', 'operations+plots')
        self.assertEqual('operations+plots', card['this_connection']['tool_profile'])
        self.assertEqual(['plots'], card['this_connection']['modules_on'])
        self.assertNotIn('plots', card['this_connection']['modules_off'])
        self.assertIn('every setup module', card['profiles']['configuration'])
        self.assertEqual(set(R.TOOL_MODULES), set(card['modules']))

    def test_configuration_lists_every_module_on(self):
        card = _card('configure.tool_profile_set', 'configuration')
        self.assertEqual(list(R.TOOL_MODULES), card['this_connection']['modules_on'])


class SetToolProfileResultTest(unittest.TestCase):

    def _result(self, before, after):
        from aot.tools.aot_data_tool_service import AoTDataToolService as S
        return S._tool_profile_result({"status": "success"}, before, after, 'applies later')

    def test_same_value_says_nothing_changed(self):
        out = self._result('configuration', 'configuration')
        self.assertIs(False, out['changed'])
        self.assertIn('Nothing changed', out['note'])
        self.assertEqual(list(R.TOOL_MODULES), out['modules_on'])

    def test_change_lists_the_modules_now_on(self):
        out = self._result('configuration', 'operations+plots+map')
        self.assertNotIn('changed', out)
        self.assertEqual(['plots', 'map'], out['modules_on'])
        self.assertEqual('applies later', out['note'])
        self.assertEqual([], self._result('x', 'operations')['modules_on'])


class RefusalNamesTheSwitchTest(unittest.TestCase):

    def test_refusal_mentions_the_approved_switch(self):
        from aot.tools import tool_execution as te
        tool = sorted(R.profile_tools('configuration') - R.profile_tools('operations'))[0]
        with mock.patch.object(te, 'domain_surface_enabled', return_value=True):
            body = te._profile_refusal_body(tool, 'operations', _editor('operations'))
        self.assertIn('configure.tool_profile_set', body['message'])
        with mock.patch.object(te, 'domain_surface_enabled', return_value=False):
            body = te._profile_refusal_body(tool, 'operations', _editor('operations'))
        self.assertIn('set_tool_profile', body['message'])


if __name__ == '__main__':
    unittest.main()
