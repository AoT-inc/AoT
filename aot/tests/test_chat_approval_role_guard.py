# coding=utf-8
"""채팅 제안 승인 실행의 역할·그룹 스코프 검사 — 2026-09-22 재현된 구멍.

배경: 직접 제어(`routes_general.output_mod`)는 `edit_controllers` 역할과
그룹 스코프를 본다. 그런데 AI 채팅이 제안한 행동을 승인해 실행하는
`POST /api/v1/ai/portal/chat/action` 은 대화 기록 소유자만 확인했다. E2E
스택에서 Monitor 계정이 자기 채팅 기록의 `control_output`·
`human_device_control` 제안을 승인해 가짜 출력 장치를 실제로 켰다.

`AIAgentService.execute_logged_action` 한 곳(단건·'all'·autonomy=auto 가 모두
지난다)에서 승인자를 보게 고쳤다. 여기서 그 계약을 고정한다:

  1. 기본 역할 중 `edit_controllers` 가 없는 Monitor·Guest·Kiosk 는 쓰기
     제안을 실행할 수 없다 — 단건도, 'all' 배치도. 실행층까지 가지 않는다.
  2. Admin·Editor 는 그대로 실행된다.
  3. 읽기 제안(예: knowledge_search)은 역할과 무관하게 막지 않는다.
  4. 레지스트리에 없는 도구 이름은 쓰기로 본다(모르면 닫는다).
  5. 편집 역할이라도 대상 장치의 그룹 밖이면 거부된다 — 대상이 도구 인자
     안에 있든, 이름으로 지목됐든.
  6. 사람이 없는(요청 컨텍스트 없는) 호출은 거부된다.
"""
import json
import unittest
import uuid
from unittest import mock

from aot.aot_flask.app import create_app
from aot.aot_flask.extensions import db
from aot.config import USER_ROLES
from aot.databases.models import (AIGlobalSettings, AIHistory, GroupGrant,
                                  Output, Role, User, UserGroup,
                                  UserGroupMember)
from aot.databases.models.ai import AIAgent
from aot.databases.models.user_group import LEVEL_OPERATE, RESOURCE_TAB
from aot.ai.services.ai_agent_service import AIAgentService

_PREFIX = 'ChatApproval'
_OUTPUT_NAME = 'ChatApprovalValve'
_ACTION = 'aot.ai.services.ai_agent_service.AIActionService.execute_action'
_OK = {'status': 'success', 'result': {'ok': True}}


def _uuid():
    return str(uuid.uuid4())


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
        self._wipe()
        self._clear_scope_cache()
        self._tab = _uuid()

        # 기본 역할 표(USER_ROLES)를 그대로 복제한다 — 표의 권한이 바뀌면 이
        # 검사도 따라간다.
        self.roles = {}
        for spec in USER_ROLES:
            fields = {k: v for k, v in spec.items() if k not in ('id', 'name')}
            role = Role(name=_PREFIX + spec['name'], **fields)
            db.session.add(role)
            self.roles[spec['name']] = role
        db.session.commit()

        self.users = {}
        for name, role in self.roles.items():
            row = User(name=(_PREFIX + name).lower(), role_id=role.id,
                       is_enabled=True)
            db.session.add(row)
            self.users[name] = row
        db.session.commit()
        # 요청이 끝나면 세션이 닫혀 ORM 객체가 분리된다 — 값만 들고 있는다.
        self.users = {name: (row.id, row.get_id())
                      for name, row in self.users.items()}

        self.output_id = _uuid()
        db.session.add(Output(unique_id=self.output_id, name=_OUTPUT_NAME,
                              output_type='virtual_on_off_single',
                              tab_id=self._tab))

        agent = AIAgent(name=_PREFIX + 'Agent')
        db.session.add(agent)

        settings = AIGlobalSettings.query.first()
        if settings is None:
            settings = AIGlobalSettings()
            db.session.add(settings)
        settings.ai_enabled = True
        settings.ai_running = True
        db.session.commit()
        self.agent_id = agent.unique_id

        self.client = self.app.test_client()

    def tearDown(self):
        try:
            self._wipe()
        finally:
            self._clear_scope_cache()
            db.session.remove()

    def _wipe(self):
        AIHistory.query.filter(AIHistory.goal == _PREFIX).delete(
            synchronize_session=False)
        AIAgent.query.filter(AIAgent.name == _PREFIX + 'Agent').delete(
            synchronize_session=False)
        GroupGrant.query.delete(synchronize_session=False)
        UserGroupMember.query.delete(synchronize_session=False)
        UserGroup.query.filter(UserGroup.name == _PREFIX + 'Group').delete(
            synchronize_session=False)
        Output.query.filter(Output.name == _OUTPUT_NAME).delete(
            synchronize_session=False)
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
                # 앱 컨텍스트를 클래스 전체에서 한 번만 푸시하므로 요청들이 같은
                # `g` 를 쓴다 — 로그인 사용자 캐시도 비워야 다음 요청이 새
                # 세션에서 사용자를 다시 읽는다.
                for name in ('_aot_scope_cache', '_login_user'):
                    if hasattr(g, name):
                        delattr(g, name)
        except Exception:
            pass

    def _history(self, user, actions):
        row = AIHistory(agent_id=self.agent_id, goal=_PREFIX,
                        user_id=user[0], message_type='ai',
                        actions_json=json.dumps(actions))
        db.session.add(row)
        db.session.commit()
        hid = row.unique_id
        db.session.remove()
        return hid

    def _post(self, user, history_id, action_index=0):
        self._clear_scope_cache()
        with self.client.session_transaction() as sess:
            sess['_user_id'] = user[1]
            sess['_fresh'] = True
        resp = self.client.post('/api/v1/ai/portal/chat/action',
                                json={'history_id': history_id,
                                      'action_index': action_index})
        self.assertEqual(resp.status_code, 200, resp.get_data(as_text=True))
        return resp.get_json()

    def _control(self):
        return {'action_type': 'control_output',
                'target_id': self.output_id,
                'params': {'state': 'on'}}

    def _operate_device(self, device):
        return {'action_type': 'mcp_tool_call', 'target_id': 'local-mcp',
                'params': {'tool_name': 'operate_device',
                           'arguments': {'device_id': device, 'state': 'on'}}}

    def _scope_to_admin_only_group(self):
        """장치 탭을 Editor 가 속하지 않은 그룹에만 부여한다."""
        group = UserGroup(name=_PREFIX + 'Group')
        db.session.add(group)
        db.session.flush()
        db.session.add(GroupGrant(group_uuid=group.unique_id,
                                  resource_type=RESOURCE_TAB,
                                  resource_uuid=self._tab,
                                  level=LEVEL_OPERATE))
        db.session.commit()


class TestChatApprovalRole(_Fixture):

    # -------------------------------------------- 1. 보기 전용 역할은 막힌다

    def test_view_only_roles_cannot_execute_proposals(self):
        for role in ('Monitor', 'Guest', 'Kiosk'):
            with self.subTest(role=role), mock.patch(
                    _ACTION, return_value=_OK) as run:
                hid = self._history(self.users[role],
                                    [self._control(),
                                     {'action_type': 'human_device_control',
                                      'target_id': self.output_id,
                                      'params': {'state': 'on'}},
                                     self._operate_device(self.output_id)])
                for idx in range(3):
                    body = self._post(self.users[role], hid, idx)
                    self.assertEqual(body.get('error_code'), 'permission_denied')
                run.assert_not_called()

    def test_view_only_roles_cannot_batch_execute(self):
        with mock.patch(_ACTION, return_value=_OK) as run:
            hid = self._history(self.users['Monitor'],
                                [self._control(),
                                 self._operate_device(self.output_id)])
            body = self._post(self.users['Monitor'], hid, 'all')
            self.assertEqual(body.get('executed'), 0)
            self.assertEqual(body.get('failed'), 2)
            run.assert_not_called()

    # -------------------------------------------- 2. 편집 역할은 그대로 된다

    def test_edit_roles_execute(self):
        for role in ('Admin', 'Editor'):
            with self.subTest(role=role), mock.patch(
                    _ACTION, return_value=_OK) as run:
                hid = self._history(self.users[role], [self._control()])
                body = self._post(self.users[role], hid)
                self.assertEqual(body.get('status'), 'success', body)
                run.assert_called_once()
                self.assertTrue(run.call_args.kwargs.get('_approved'))

    # -------------------------------------------- 3·4. 읽기와 모르는 도구

    def test_read_only_proposal_is_not_role_gated(self):
        with mock.patch(_ACTION, return_value=_OK) as run:
            hid = self._history(self.users['Monitor'],
                                [{'action_type': 'knowledge_search',
                                  'target_id': None,
                                  'params': {'query': 'x'}}])
            body = self._post(self.users['Monitor'], hid)
            self.assertEqual(body.get('status'), 'success', body)
            run.assert_called_once()

    def test_unknown_tool_counts_as_write(self):
        self.assertTrue(AIAgentService._approval_is_write(
            'mcp_tool_call', 'x', {'tool_name': 'no_such_tool_ever'}))
        self.assertTrue(AIAgentService._approval_is_write(
            'delete_device', 'x', {}))

    # -------------------------------------------- 5. 그룹 스코프

    def test_editor_outside_group_is_denied(self):
        self._scope_to_admin_only_group()
        for action in (self._control(),
                       self._operate_device(self.output_id),
                       self._operate_device(_OUTPUT_NAME)):   # 이름으로 지목
            with self.subTest(action=action), mock.patch(
                    _ACTION, return_value=_OK) as run:
                hid = self._history(self.users['Editor'], [action])
                body = self._post(self.users['Editor'], hid)
                self.assertEqual(body.get('error_code'), 'permission_denied')
                run.assert_not_called()

    def test_admin_bypasses_group_scope(self):
        self._scope_to_admin_only_group()
        with mock.patch(_ACTION, return_value=_OK) as run:
            hid = self._history(self.users['Admin'], [self._control()])
            body = self._post(self.users['Admin'], hid)
            self.assertEqual(body.get('status'), 'success', body)
            run.assert_called_once()

    # -------------------------------------------- 6. 사람이 없으면 거부

    def test_no_request_user_is_denied(self):
        with mock.patch(_ACTION, return_value=_OK) as run:
            hid = self._history(self.users['Admin'], [self._control()])
            result = AIAgentService.execute_logged_action(hid, 0)
            self.assertEqual(result.get('error_code'), 'permission_denied')
            run.assert_not_called()


class TestChatAccessRole(_Fixture):
    """채팅 자체(LLM 호출)의 역할 게이트 — 실행과는 별개 질문(p6_73).

    제품 결정(2026-09-22): Monitor 는 조회·질문용으로 채팅을 쓸 수 있지만
    Guest·Kiosk 는 막는다(호출 비용·데모 공개). `POST /api/v1/ai/portal/chat`
    이 본문을 읽기 전에 `use_ai_chat` 권한을 본다 — 막히면 메시지가 없어도
    403 이 먼저 난다. 통과 여부만 확인하면 되므로 본문을 비워 보낸다: 통과한
    역할은 그다음 "메시지가 필요합니다" 400 을 받는다(무거운 LLM 호출까지
    갈 필요가 없다) — 순서가 이렇다는 것 자체가 게이트를 지났다는 증거다.
    """

    def _post_chat(self, user):
        with self.client.session_transaction() as sess:
            sess['_user_id'] = user[1]
            sess['_fresh'] = True
        return self.client.post('/api/v1/ai/portal/chat', json={})

    def test_guest_and_kiosk_cannot_chat(self):
        for role in ('Guest', 'Kiosk'):
            with self.subTest(role=role):
                resp = self._post_chat(self.users[role])
                self.assertEqual(resp.status_code, 403)
                self.assertIn('use_ai_chat', resp.get_json().get('error', ''))

    def test_monitor_admin_editor_can_reach_chat(self):
        for role in ('Monitor', 'Admin', 'Editor'):
            with self.subTest(role=role):
                resp = self._post_chat(self.users[role])
                # 게이트를 지나 "메시지가 필요합니다" 로 떨어진다 — 403 이 아니다.
                self.assertEqual(resp.status_code, 400, resp.get_data(as_text=True))

    def test_use_ai_chat_matrix_matches_product_decision(self):
        """USER_ROLES 시드 자체가 결정과 어긋나지 않는지(회귀의 가장 앞단)."""
        expected = {'Admin': True, 'Editor': True, 'Monitor': True,
                   'Guest': False, 'Kiosk': False}
        seeded = {spec['name']: spec['use_ai_chat'] for spec in USER_ROLES}
        self.assertEqual(seeded, expected)


if __name__ == '__main__':
    unittest.main()
