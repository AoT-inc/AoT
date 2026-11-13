# coding=utf-8
"""공지·지식 출처 설정·도구 묶음 변경의 필요 역할 권한 — 웹과 같게 (2026-11-04).

  - 공지 작성·수정·삭제, configure_library_source → `edit_settings` (제어 아님)
  - set_tool_profile → 필요 권한 없음(자기 연결), 승인은 유지
목록 숨기기(_hidden_tools)·호출 거절(role_refusal)·승인 판정(role_allows_tool)이 같은 표를 본다.
"""
import unittest
from types import SimpleNamespace

from aot.tools import mcp_auth
from aot.tools import mcp_safety_gate as gate
from aot.tools import tool_execution as te
from aot.tools import tool_registry as R

_SETTINGS = ('create_notice', 'modify_notice', 'delete_notice',
             'configure_library_source')


def _info(controllers=False, settings=False, plots=False):
    return mcp_auth.RoleInfo(name='x', can_write=controllers, user_id='u',
                             can_edit_settings=settings, can_use_ai_chat=True,
                             can_edit_plots=plots or settings)


def _row(**kw):
    base = dict(edit_controllers=False, edit_settings=False, edit_plots=False,
                use_ai_chat=False)
    base.update(kw)
    return SimpleNamespace(**base)


class TestSettingsEditClassification(unittest.TestCase):

    def test_table(self):
        for t in _SETTINGS:
            self.assertEqual(gate.required_write_permission(t), 'edit_settings', t)
        self.assertEqual(gate.required_write_permission('set_tool_profile'), '')
        self.assertEqual(gate.required_write_permission('operate_device'),
                         'edit_controllers')

    def test_registry_sets_are_writes(self):
        self.assertEqual(R.settings_edit_tools(), frozenset(_SETTINGS))
        self.assertEqual(R.self_service_tools(), frozenset({'set_tool_profile'}))

    def test_settings_only_role(self):
        info = _info(settings=True)
        row = _row(edit_settings=True)
        hidden = te._hidden_tools(info)
        for t in _SETTINGS:
            self.assertIsNone(gate.role_refusal(t, info), t)
            self.assertNotIn(t, hidden)
            self.assertTrue(gate.role_allows_tool(info, t))
            self.assertTrue(gate.role_allows_tool(row, t))
        self.assertIsNotNone(gate.role_refusal('operate_device', info))
        self.assertIn('operate_device', hidden)
        self.assertFalse(gate.role_allows_tool(row, 'operate_device'))

    def test_controls_only_role(self):
        info = _info(controllers=True)
        row = _row(edit_controllers=True)
        hidden = te._hidden_tools(info)
        for t in _SETTINGS:
            self.assertEqual(
                gate.role_refusal(t, info)['reason_code'], 'insufficient_role', t)
            self.assertIn(t, hidden)
            self.assertFalse(gate.role_allows_tool(info, t))
            self.assertFalse(gate.role_allows_tool(row, t))
        self.assertIsNone(gate.role_refusal('operate_device', info))

    def test_monitor_changes_own_tool_profile_with_approval(self):
        monitor = _info()                       # 제어·설정 없음
        self.assertIsNone(gate.role_refusal('set_tool_profile', monitor))
        self.assertNotIn('set_tool_profile', te._hidden_tools(monitor))
        self.assertTrue(gate.role_allows_tool(_row(), 'set_tool_profile'))
        # 승인은 유지 — 레지스트리에서 승인 필요 쓰기다.
        self.assertIn('set_tool_profile', R.approval_required_tools())
        self.assertIsNotNone(gate.role_refusal('set_tool_profile', None))
        ro = monitor._replace(read_only=True)
        self.assertIsNotNone(gate.role_refusal('set_tool_profile', ro))
        self.assertIn('set_tool_profile', te._hidden_tools(ro))
        self.assertIn('set_tool_profile', te._hidden_tools(None))


if __name__ == '__main__':
    unittest.main()
