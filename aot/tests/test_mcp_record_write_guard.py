# coding=utf-8
"""기록 쓰기(노트·지식) 도구의 권한 — 읽기로 분류되던 구멍.

배경: `create_note`·`knowledge_shelve`·`submit_advice` 는 레지스트리에서
mutating 도 physical 도 아니어서 `classify_permission` 이 'read' 를 돌려줬다.
그래서 읽기 전용 API 키, Monitor·Guest 역할, 조언 전용 모드
(`AOT_MCP_WRITE_ENABLED=0`)에서도 MCP 로 노트와 지식을 저장할 수 있었고,
그룹 스코프도 보지 않았다. 웹은 노트 작성·지식 추가에 `edit_settings` 를
요구한다(`routes_notes_api.api_notes_create`, `routes_ai_library`).

여기서 고정하는 계약:

  1. 기록 쓰기(`record_write`)는 **쓰기**다 — `write_tools()` 에 들어가 역할·
     읽기 전용 키·그룹 스코프가 다른 쓰기와 똑같이 적용된다.
  2. 그러나 **승인 대상이 아니다** — 권한 있는 사용자는 지금처럼 바로 저장된다.
  3. 필요한 역할 권한은 웹과 같은 `edit_settings` 다.
  4. 조언 전용 모드는 기록 쓰기를 거부한다. `submit_advice` 만 예외다.
  5. `submit_advice` 는 읽기 전용 키에도 열려 있다(거부 안내가 조언 제출을
     권하므로). 다만 AI 채팅을 못 쓰는 역할(Guest·Kiosk)은 못 낸다.
  6. 읽기 전용 키의 tools/list 에는 쓰기 도구가 하나도 없다 — 승인 면제
     (config_only·record_write) 포함. `submit_advice` 는 보인다.
  7. 인앱 AI 도 같다 — 권한 없는 사람이 채팅으로 노트를 쓰지 못한다.
  8. 거부는 감사 로그에 call_state='refused' 로 남는다.
"""
import json
import os
import types
import unittest
import uuid
from unittest import mock

from aot.aot_flask.app import create_app
from aot.aot_flask.extensions import db
from aot.config import USER_ROLES
from aot.databases.models import (GroupGrant, MCPAuditLog, MCPConfirmation,
                                  Notes, Output, Role, User, UserGroup,
                                  UserGroupMember)
from aot.databases.models.user_group import LEVEL_OPERATE, RESOURCE_TAB
from aot.tools import mcp_auth
from aot.tools import mcp_safety_gate as gate
from aot.tools import providers
from aot.tools import tool_execution as te
from aot.tools import tool_registry as R

_PREFIX = 'RecWrite'
_NOTE_MARK = 'record-write-guard-test-note'


def _uuid():
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# 1. 레지스트리 분류 (DB 불필요)
# ---------------------------------------------------------------------------

class TestClassification(unittest.TestCase):

    def test_record_tools_are_writes_without_approval(self):
        rec = set(R.record_write_tools())
        self.assertTrue({'create_note', 'knowledge_shelve'} <= rec, rec)
        self.assertTrue(rec <= set(R.write_tools()))
        self.assertFalse(rec & set(R.approval_required_tools()))
        self.assertFalse(rec & set(R.virtual_approval_tools()))
        for name in ('create_note', 'knowledge_shelve'):
            self.assertEqual(gate.classify_permission(name), 'write', name)
            self.assertIn(name, gate.write_tools())

    def test_advice_persists_but_is_not_a_scoped_write(self):
        self.assertIn('submit_advice', R.advisory_write_tools())
        # 감사에는 쓰기로 남는다(행을 저장한다).
        self.assertEqual(gate.classify_permission('submit_advice'), 'write')
        # 그러나 읽기 전용 키·스코프 판정 대상인 쓰기 집합에는 없다.
        self.assertNotIn('submit_advice', gate.write_tools())
        self.assertNotIn('submit_advice', R.approval_required_tools())

    def test_in_app_chat_does_not_queue_notes_for_approval(self):
        from aot.ai.services.ai_action_service import AIActionService
        for name in ('create_note', 'knowledge_shelve', 'submit_advice'):
            self.assertFalse(AIActionService.requires_approval(name), name)

    def test_no_persisting_tool_is_left_classified_as_read(self):
        for name in ('create_note', 'knowledge_shelve', 'submit_advice'):
            self.assertNotEqual(gate.classify_permission(name), 'read', name)


# ---------------------------------------------------------------------------
# 공용 준비 — 기본 역할 표(USER_ROLES)를 그대로 복제한다
# ---------------------------------------------------------------------------

class _Fixture(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.app = create_app()
        cls.app.config['WTF_CSRF_ENABLED'] = False
        cls.app.config['TESTING'] = True
        cls.app_context = cls.app.app_context()
        cls.app_context.push()

    @classmethod
    def tearDownClass(cls):
        cls.app_context.pop()

    def setUp(self):
        self._env = mock.patch.dict(os.environ, {'AOT_MCP_WRITE_ENABLED': '1'})
        self._env.start()
        self._wipe()
        self._clear_scope_cache()
        self._tab = _uuid()

        roles = {}
        for spec in USER_ROLES:
            fields = {k: v for k, v in spec.items() if k not in ('id', 'name')}
            role = Role(name=_PREFIX + spec['name'], **fields)
            db.session.add(role)
            roles[spec['name']] = role
        # 웹 기준 대조용: 제어는 되지만 설정 편집은 안 되는 역할.
        custom = Role(name=_PREFIX + 'ControlOnly', edit_controllers=True,
                      edit_settings=False, edit_users=False,
                      use_ai_chat=True)
        db.session.add(custom)
        roles['ControlOnly'] = custom
        db.session.commit()

        users = {}
        for name, role in roles.items():
            row = User(name=(_PREFIX + name).lower(), role_id=role.id,
                       is_enabled=True)
            db.session.add(row)
            users[name] = row
        db.session.commit()
        self.user_uuids = {name: row.unique_id for name, row in users.items()}

        self.output_id = _uuid()
        db.session.add(Output(unique_id=self.output_id, name=_PREFIX + 'Valve',
                              output_type='virtual_on_off_single',
                              tab_id=self._tab))
        db.session.commit()

    def tearDown(self):
        try:
            self._wipe()
        finally:
            self._env.stop()
            self._clear_scope_cache()
            db.session.remove()

    def _wipe(self):
        db.session.rollback()
        GroupGrant.query.delete(synchronize_session=False)
        UserGroupMember.query.delete(synchronize_session=False)
        UserGroup.query.filter(UserGroup.name == _PREFIX + 'Group').delete(
            synchronize_session=False)
        Output.query.filter(Output.name == _PREFIX + 'Valve').delete(
            synchronize_session=False)
        Notes.query.filter(Notes.note.like(_NOTE_MARK + '%')).delete(
            synchronize_session=False)
        MCPAuditLog.query.delete(synchronize_session=False)
        MCPConfirmation.query.delete(synchronize_session=False)
        User.query.filter(User.name.like(_PREFIX.lower() + '%')).delete(
            synchronize_session=False)
        Role.query.filter(Role.name.like(_PREFIX + '%')).delete(
            synchronize_session=False)
        db.session.commit()

    @staticmethod
    def _clear_scope_cache():
        try:
            from flask import g, has_app_context
            if has_app_context():
                for name in ('_aot_scope_cache', '_login_user'):
                    if hasattr(g, name):
                        delattr(g, name)
        except Exception:
            pass

    def _user(self, name):
        db.session.remove()
        return User.query.filter(User.name == (_PREFIX + name).lower()).first()

    def _role(self, name, readonly=False):
        key_row = types.SimpleNamespace(is_readonly=True, name='ro',
                                        unique_id='ro-key') if readonly else None
        return mcp_auth._role_for(self._user(name), key_row)

    def _call(self, tool, args, role, scope_user_uuid=None):
        self._clear_scope_cache()
        out = te._execute_tool(self.app, tool, dict(args), agent_id='user:test',
                               role=role, scope_user_uuid=scope_user_uuid,
                               transport='mcp_http')
        return json.loads(out[0]['text'])

    def _note_args(self, **extra):
        args = {'note': _NOTE_MARK + ' ' + _uuid()[:8], 'name': _PREFIX}
        args.update(extra)
        return args

    @staticmethod
    def _shelve_args():
        return {'content': _NOTE_MARK + ' 지식', 'tags': 'test',
                'heading': '기록 쓰기 시험 지식'}

    def _notes(self):
        db.session.remove()
        return Notes.query.filter(Notes.note.like(_NOTE_MARK + '%')).count()

    def _last_audit(self):
        db.session.remove()
        return MCPAuditLog.query.order_by(MCPAuditLog.id.desc()).first()

    def _scope_to_other_group(self):
        """장치 탭을 아무도 속하지 않은 그룹에만 부여한다."""
        group = UserGroup(name=_PREFIX + 'Group')
        db.session.add(group)
        db.session.flush()
        db.session.add(GroupGrant(group_uuid=group.unique_id,
                                  resource_type=RESOURCE_TAB,
                                  resource_uuid=self._tab,
                                  level=LEVEL_OPERATE))
        db.session.commit()


# ---------------------------------------------------------------------------
# 2. 외부 MCP 실행 경로 (_execute_tool — stdio·HTTP·REST 공통)
# ---------------------------------------------------------------------------

class TestMcpRecordWrite(_Fixture):

    def test_readonly_key_cannot_write_records(self):
        role = self._role('Editor', readonly=True)
        with mock.patch.object(te, '_dispatch_virtual_tool') as run:
            for tool, args in (('create_note', self._note_args()),
                               ('knowledge_shelve', self._shelve_args())):
                with self.subTest(tool=tool):
                    body = self._call(tool, args, role)
                    self.assertEqual(body.get('status'), 'refused', body)
                    self.assertEqual(body.get('reason_code'), 'insufficient_role')
                    self.assertEqual(body.get('call_state'), 'refused')
                    row = self._last_audit()
                    self.assertEqual(row.tool_name, tool)
                    self.assertEqual(row.permission, 'write')
                    self.assertEqual(row.call_state, 'refused')
                    self.assertEqual(row.confirmation_status, 'rejected')
            run.assert_not_called()
        self.assertEqual(self._notes(), 0)

    def test_view_only_roles_cannot_write_records(self):
        with mock.patch.object(te, '_dispatch_virtual_tool') as run:
            for name in ('Monitor', 'Guest', 'Kiosk'):
                for tool, args in (('create_note', self._note_args()),
                                   ('knowledge_shelve', self._shelve_args())):
                    with self.subTest(role=name, tool=tool):
                        body = self._call(tool, args, self._role(name))
                        self.assertEqual(body.get('reason_code'),
                                         'insufficient_role', body)
            run.assert_not_called()

    def test_unauthenticated_caller_cannot_write_records(self):
        """인증을 끈 서버(role=None)는 조회 전용이다 — 문서가 그렇게 말한다."""
        body = self._call('create_note', self._note_args(), None)
        self.assertEqual(body.get('reason_code'), 'insufficient_role', body)
        self.assertEqual(self._notes(), 0)

    def test_permission_mirrors_web_edit_settings(self):
        """제어 권한만 있고 설정 편집이 없는 역할은 웹에서 노트를 못 쓴다 — MCP 도."""
        body = self._call('create_note', self._note_args(),
                          self._role('ControlOnly'))
        self.assertEqual(body.get('reason_code'), 'insufficient_role', body)
        self.assertEqual(self._notes(), 0)

    def test_authorized_user_saves_immediately_without_approval(self):
        for name in ('Admin', 'Editor'):
            with self.subTest(role=name):
                before = self._notes()
                body = self._call('create_note', self._note_args(),
                                  self._role(name))
                self.assertEqual(body.get('call_state'), 'executed', body)
                self.assertNotEqual(body.get('status'), 'pending_approval')
                self.assertEqual(self._notes(), before + 1)
                row = self._last_audit()
                self.assertEqual(row.permission, 'write')
                self.assertEqual(row.confirmation_status, 'not_required')
        db.session.remove()
        self.assertEqual(MCPConfirmation.query.count(), 0,
                         'record writes must not create approval requests')

    def test_group_scope_applies_to_record_writes(self):
        self._scope_to_other_group()
        body = self._call('create_note',
                          self._note_args(target_id=self.output_id,
                                          target_type='output'),
                          self._role('Editor'),
                          scope_user_uuid=self.user_uuids['Editor'])
        self.assertEqual(body.get('reason_code'), 'group_scope', body)
        self.assertEqual(body.get('call_state'), 'refused')
        self.assertEqual(self._last_audit().call_state, 'refused')
        self.assertEqual(self._notes(), 0)

    def test_advice_only_mode_refuses_records_but_not_advice(self):
        role = self._role('Editor')
        with mock.patch.dict(os.environ, {'AOT_MCP_WRITE_ENABLED': '0'}):
            for tool, args in (('create_note', self._note_args()),
                               ('knowledge_shelve', self._shelve_args())):
                with self.subTest(tool=tool):
                    body = self._call(tool, args, role)
                    self.assertEqual(body.get('reason_code'), 'write_disabled',
                                     body)
                    self.assertIn('submit_advice', body.get('message', ''))
                    self.assertEqual(self._last_audit().call_state, 'refused')
            with mock.patch.object(te, '_dispatch_virtual_tool',
                                   return_value={'status': 'success'}) as run:
                body = self._call('submit_advice', {'advice': 'x'}, role)
                self.assertEqual(body.get('call_state'), 'executed', body)
                run.assert_called_once()
        self.assertEqual(self._notes(), 0)

    def test_readonly_key_can_submit_advice(self):
        with mock.patch.object(te, '_dispatch_virtual_tool',
                               return_value={'status': 'success'}) as run:
            for name in ('Editor', 'Monitor'):
                with self.subTest(role=name):
                    body = self._call('submit_advice', {'advice': 'x'},
                                      self._role(name, readonly=True))
                    self.assertEqual(body.get('call_state'), 'executed', body)
            self.assertEqual(run.call_count, 2)
        row = self._last_audit()
        self.assertEqual(row.permission, 'write')
        self.assertEqual(row.confirmation_status, 'not_required')

    def test_roles_without_ai_chat_cannot_submit_advice(self):
        with mock.patch.object(te, '_dispatch_virtual_tool') as run:
            for name in ('Guest', 'Kiosk'):
                with self.subTest(role=name):
                    body = self._call('submit_advice', {'advice': 'x'},
                                      self._role(name))
                    self.assertEqual(body.get('reason_code'),
                                     'insufficient_role', body)
                    self.assertEqual(self._last_audit().call_state, 'refused')
            run.assert_not_called()

    def test_use_tool_wrapping_does_not_bypass(self):
        body = self._call('use_tool', {'tool_name': 'create_note',
                                       'arguments': self._note_args()},
                          self._role('Editor', readonly=True))
        self.assertEqual(body.get('reason_code'), 'insufficient_role', body)
        self.assertEqual(self._notes(), 0)


# ---------------------------------------------------------------------------
# 3. tools/list — 쓸 수 없는 도구는 광고하지 않는다
# ---------------------------------------------------------------------------

class TestToolListing(_Fixture):

    def _names(self, role):
        return {t['name'] for t in te._get_all_tools(self.app, role=role,
                                                     tiered=False)}

    def test_readonly_key_sees_no_write_tools(self):
        names = self._names(self._role('Editor', readonly=True))
        leaked = names & (set(gate.write_tools()) | {'respond_to_confirmation'})
        self.assertFalse(leaked, sorted(leaked))
        for n in ('add_schedule', 'create_note', 'knowledge_shelve'):
            self.assertNotIn(n, names)
        self.assertIn('submit_advice', names)
        self.assertIn('search_notes', names)

    def test_monitor_sees_no_record_writes(self):
        names = self._names(self._role('Monitor'))
        self.assertNotIn('create_note', names)
        self.assertNotIn('knowledge_shelve', names)
        self.assertIn('submit_advice', names)

    def test_guest_does_not_see_submit_advice(self):
        self.assertNotIn('submit_advice', self._names(self._role('Guest')))

    def test_editor_sees_record_writes(self):
        names = self._names(self._role('Editor'))
        for n in ('create_note', 'knowledge_shelve', 'submit_advice',
                  'add_schedule', 'operate_device', 'respond_to_confirmation'):
            self.assertIn(n, names)

    def test_control_only_role_sees_control_but_not_notes(self):
        names = self._names(self._role('ControlOnly'))
        self.assertIn('operate_device', names)
        self.assertNotIn('create_note', names)

    def test_drawer_does_not_leak_record_writes(self):
        role = self._role('Editor', readonly=True)
        with self.app.test_request_context():
            opened = te._open_drawer(self.app, {'drawer': 'record'}, role=role)
        names = {t['name'] for t in opened.get('tools', [])}
        self.assertNotIn('knowledge_shelve', names)
        self.assertIn('submit_advice', names)


# ---------------------------------------------------------------------------
# 4. 인앱 AI — 채팅으로 노트를 쓰는 경로
# ---------------------------------------------------------------------------

class TestInAppRecordWrite(_Fixture):

    def _run_as(self, name, action_type='virtual_tool_call', params=None):
        from aot.ai.services.ai_action_service import AIActionService
        import flask_login
        params = params if params is not None else {
            'tool_name': 'create_note', 'arguments': self._note_args()}
        self._clear_scope_cache()
        user = self._user(name)
        with self.app.test_request_context():
            flask_login.login_user(user)
            return AIActionService.execute_action(action_type, 'system_internal',
                                                  params)

    def test_view_only_role_cannot_write_notes_via_chat(self):
        for name in ('Monitor', 'ControlOnly'):
            with self.subTest(role=name):
                res = self._run_as(name)
                self.assertEqual(res.get('status'), 'error', res)
                self.assertEqual(res.get('reason_code'), 'insufficient_role')
        self.assertEqual(self._notes(), 0)

    def test_view_only_role_cannot_shelve_via_chat(self):
        shelve = mock.Mock(return_value={'status': 'success'})
        with mock.patch.dict(providers._REGISTRY, {'knowledge_shelve': shelve}):
            res = self._run_as('Monitor', params={
                'tool_name': 'knowledge_shelve',
                'arguments': self._shelve_args()})
        self.assertEqual(res.get('reason_code'), 'insufficient_role', res)
        shelve.assert_not_called()

    def test_legacy_note_action_is_guarded_too(self):
        res = self._run_as('Monitor', action_type='note',
                           params={'message': _NOTE_MARK + ' legacy'})
        self.assertEqual(res.get('reason_code'), 'insufficient_role', res)
        self.assertEqual(self._notes(), 0)

    def test_authorized_user_still_writes_immediately(self):
        for name in ('Admin', 'Editor'):
            with self.subTest(role=name):
                before = self._notes()
                res = self._run_as(name)
                self.assertEqual(res.get('status'), 'success', res)
                self.assertEqual(self._notes(), before + 1)

    def test_background_job_without_a_person_is_unchanged(self):
        """요청 컨텍스트가 없는 호출(백그라운드 AI 잡)은 사람이 없어 면제다 —
        그룹 스코프 §6-1 과 같은 근거."""
        from aot.ai.services.ai_action_service import AIActionService
        from flask import has_request_context
        self.assertFalse(has_request_context())
        res = AIActionService.execute_action(
            'virtual_tool_call', 'system_internal',
            {'tool_name': 'create_note', 'arguments': self._note_args()})
        self.assertEqual(res.get('status'), 'success', res)
        self.assertEqual(self._notes(), 1)

    def test_chat_proposal_approval_uses_the_same_rule(self):
        from aot.ai.services.ai_agent_service import AIAgentService
        import flask_login
        params = {'tool_name': 'create_note', 'arguments': self._note_args()}
        self.assertTrue(AIAgentService._approval_is_write(
            'virtual_tool_call', 'system_internal', params))
        for name, denied in (('Monitor', True), ('ControlOnly', True),
                             ('Editor', False), ('Admin', False)):
            with self.subTest(role=name):
                self._clear_scope_cache()
                user = self._user(name)
                with self.app.test_request_context():
                    flask_login.login_user(user)
                    reason = AIAgentService._approval_denial(
                        'virtual_tool_call', 'system_internal', params)
                self.assertEqual(bool(reason), denied, reason)


if __name__ == '__main__':
    unittest.main()
