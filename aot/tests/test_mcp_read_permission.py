# coding=utf-8
"""MCP 읽기는 웹 화면의 권한을 따른다 — 읽기 판정표(`mcp_safety_gate.READ_PERMISSION`).

웹이 `login_required` 만 거는 데이터는 막지 않고, 로그·업그레이드·시스템 정보·AI 에이전트처럼
권한으로 막는 화면의 데이터만 같은 권한을 요구한다. 그리고 AI 채팅 권한(`use_ai_chat`)이 없는
역할(기본 표의 Guest·Kiosk)은 MCP 를 쓰지 못한다 — 목록은 비고, 호출은 사람이 읽는 거절을 낸다.
"""
import json
import os
import unittest
from unittest import mock

from aot.tests.test_mcp_tool_profiles import _AppFixture, _PREFIX

#: 읽기 도구 → 필요 권한 (웹 화면의 검사와 같다)
EXPECTED = {
    'analyze_system_failure': 'view_logs',
    'get_system_update_status': 'edit_settings',
    'get_storage_tier_status': 'view_stats',
    'list_ai_agents': 'edit_controllers',
}
FREE_READS = ('get_device_list', 'list_notices', 'list_plots', 'search_notes')


class ReadPermissionTest(_AppFixture):

    def _role(self, name, **flags):
        """역할 이름(기본 표) 또는 사용자 정의 역할로 RoleInfo 를 만든다."""
        from aot.databases.models import Role, User
        from aot.tools import mcp_auth
        row = Role.query.filter_by(name=_PREFIX + name).first()
        if row is None:
            row = Role(name=_PREFIX + name, **flags)
            self.db.session.add(row)
            self.db.session.commit()
        user = User(name=(_PREFIX + name + 'u').lower(), role_id=row.id, is_enabled=True)
        self.db.session.add(user)
        self.db.session.commit()
        return mcp_auth._role_for(user)

    def _call(self, role, tool, args=None):
        from aot.tools import tool_execution as te
        out = te._execute_tool(self.app, tool, args or {}, agent_id='user:proftest',
                               role=role, scope_user_uuid=getattr(role, 'user_id', None),
                               transport='mcp_http', tool_profile='configuration')
        return json.loads(out[0]['text'])

    def test_table_is_the_web_gate(self):
        from aot.tools import mcp_safety_gate as gate
        for tool, perm in EXPECTED.items():
            self.assertEqual(perm, gate.required_read_permission(tool))
        for tool in FREE_READS:
            self.assertIsNone(gate.required_read_permission(tool))

    def test_hidden_and_refused_follow_the_same_table(self):
        from aot.tools import mcp_safety_gate as gate
        from aot.tools import tool_execution as te
        # (역할, 읽을 수 없어야 하는 도구)
        expect_blocked = {
            'Admin': set(),
            'Editor': set(),
            'Monitor': {'get_system_update_status', 'list_ai_agents'},
        }
        for who, blocked in expect_blocked.items():
            role = self._role(who)
            hidden = te._hidden_tools(role)
            for tool in EXPECTED:
                self.assertEqual(tool in blocked, tool in hidden, (who, tool))
                refusal = gate.role_refusal(tool, role)
                self.assertEqual(tool in blocked, refusal is not None, (who, tool))
                if refusal:
                    self.assertEqual('insufficient_role', refusal['reason_code'])
            for tool in FREE_READS:
                self.assertNotIn(tool, hidden)
                self.assertIsNone(gate.role_refusal(tool, role))

    def test_custom_role_gets_exactly_what_its_flags_allow(self):
        from aot.tools import tool_execution as te
        role = self._role('Custom', view_logs=True, view_stats=False)
        hidden = te._hidden_tools(role)
        self.assertNotIn('analyze_system_failure', hidden)       # view_logs
        self.assertIn('get_storage_tier_status', hidden)         # view_stats 없음
        self.assertIn('get_system_update_status', hidden)        # edit_settings 없음
        # 제어 권한은 AI 사용을 함의한다 → MCP 를 쓸 수 있고, ai/agent 읽기도 열린다
        ctrl = self._role('CustomCtl', edit_controllers=True)
        self.assertNotIn('list_ai_agents', te._hidden_tools(ctrl))
        self.assertTrue(ctrl.can_use_ai_chat)

    def test_roles_without_ai_chat_cannot_use_mcp(self):
        from aot.tools import mcp_auth
        from aot.tools import tool_execution as te
        for who in ('Guest', 'Kiosk'):
            role = self._role(who)
            self.assertFalse(role.can_use_ai_chat, who)
            self.assertFalse(mcp_auth.role_can_use_mcp(role))
            self.assertEqual([], te._get_all_tools(self.app, role=role, profile='configuration'))
            self.assertEqual(mcp_auth.AI_USE_REFUSAL, te._server_instructions('configuration', role))
            body = self._call(role, 'get_device_list')
            self.assertEqual('refused', body['status'])
            self.assertEqual('insufficient_role', body['reason_code'])
            self.assertIn('AI', body['message'])

    def test_roles_with_ai_chat_still_work(self):
        from aot.tools import tool_execution as te
        for who in ('Admin', 'Editor', 'Monitor'):
            role = self._role(who)
            self.assertTrue(te._get_all_tools(self.app, role=role, profile='configuration'), who)
            body = self._call(role, 'get_device_list')
            self.assertNotEqual('insufficient_role', body.get('reason_code'), who)

    def test_domain_operation_follows_the_table(self):
        with mock.patch.dict(os.environ, {'AOT_MCP_SURFACE': ''}):
            monitor = self._role('Monitor')
            body = self._call(monitor, 'overview', {'op': 'update_status'})
            text = json.dumps(body)
            self.assertIn('insufficient_role', text)
            admin = self._role('Admin')
            body = self._call(admin, 'overview', {'op': 'update_status'})
            self.assertNotIn('insufficient_role', json.dumps(body))

    def test_write_refusal_names_the_permission_not_the_role(self):
        from aot.tools import mcp_safety_gate as gate
        role = self._role('Monitor')
        refusal = gate.role_refusal('operate_device', role)
        self.assertIn('control permission', refusal['message'])
        self.assertNotIn('Admin/Editor', refusal['message'])


if __name__ == '__main__':
    unittest.main()
