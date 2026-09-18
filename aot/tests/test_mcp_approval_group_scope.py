# coding=utf-8
"""승인 경로의 그룹 스코프 검사 — 2026-09-18 발견된 구멍의 회귀 테스트.

정본 설계: `docs/design/access-scope-groups.md`

배경: 직접 제어 경로(`routes_general.output_mod`)는 역할 검사 뒤에 항상
`scope.can_operate_device()` 로 "이 장치를" 다룰 수 있는지도 본다. AI(MCP)
쓰기 요청의 승인 경로(`mcp_confirmation_approve`/`_batch_approve` →
`mcp_safety_gate.execute_approved`)는 2026-09-18에 역할 검사
(`edit_controllers`)만 추가됐을 뿐 그룹은 보지 않았다 — 그래서 편집자
역할이지만 다른 그룹 소속인 사람이 승인 화면에서 남의 그룹 장치의 물리 제어
요청(`operate_device`·`set_output_state`·`schedule_device_control`)을
승인하면 그대로 실행됐다.

`mcp_safety_gate._decide()` 가 승인 직전에 저장된 인자(수정됐으면 그 값)를
호출 시점 검사와 같은 정본인 `scope.can_operate_tool_call()`(값 기반 uuid
스캔 — 도구마다 인자 이름이 달라도 새지 않는다)에 넘겨 승인자 기준으로 보게
고쳤다. 여기서 그 계약을 고정한다:

  1. 편집자 역할이라도 대상 장치의 그룹 밖이면 물리 도구 승인은 403 급
     (`reason_code='group_scope_denied'`)으로 거부되고, `MCPConfirmation` 은
     `pending` 그대로 남는다(다른 승인자가 다시 볼 수 있게).
  2. 그룹 안이면(또는 스코프를 아예 안 쓰는 설치면) 정상 승인된다.
  3. `device_id` 가 이름이어도(uuid 가 아니어도) 실행층과 같은 해석
     (`resolve_output`)을 거쳐 판정한다.
  4. 승인자가 `modified_params` 로 대상 장치를 바꿔 승인하면, 원본이 아니라
     **바뀐** 장치 기준으로 판정한다.
  5. PHYSICAL_TOOLS 가 아닌 도구(예: 공지 작성)에 스코프 대상 uuid 가 없으면
     영향을 받지 않는다.
  6. 판정은 **명시적으로 넘겨받은 `user_id`** 로 한다 — 웹 승인 화면
     (`routes_mcp_api.py`)도 MCP `respond_to_confirmation` 도구
     (`tool_execution.py`)도 둘 다 `gate.approve(cid, user_id=...)`로 승인자를
     명시한다. 이 값을 무시하고 `flask_login.current_user` 에만 기대면, 실제
     로그인 세션이 없는 MCP 경로에서 익명 취급되어 그룹 소속과 무관하게
     항상 거부로 샌다(2026-09-18 자체 발견·수정).
  7. `user_id` 를 아예 안 넘기는 드문 호출자를 위한 폴백(`flask_login.
     current_user`)도 살아 있어야 한다.
  8. 새 게이트는 게이트 함수를 직접 부르는 것만으로는 부족하다 — 실제
     HTTP 라운드트립으로 403 을 봐야 한다("소스에 게이트가 있다는 것과 그
     게이트를 지난다는 것은 다르다").
"""
import unittest
import uuid

from aot.aot_flask.app import create_app
from aot.aot_flask.extensions import db
from aot.ai.services import mcp_safety_gate as gate
from aot.databases.models import (AuditLog, GroupGrant, MCPConfirmation,
                                  Output, Role, User, UserGroup,
                                  UserGroupMember)
from aot.databases.models.user_group import LEVEL_OPERATE, RESOURCE_TAB

_OUTPUT_NAME = 'ScopeApprovalValve'
_OTHER_OUTPUT_NAME = '다른밸브'


def _uuid():
    return str(uuid.uuid4())


class _Fixture(unittest.TestCase):
    """앱은 클래스당 한 번, 자원(역할·사용자·장치·그룹)은 테스트마다 새로."""

    @classmethod
    def setUpClass(cls):
        cls.app = create_app()
        # 실제 HTTP 라운드트립 테스트가 CSRF 토큰 없이 POST 한다 — 이 검사가
        # 보려는 것은 그룹 스코프 게이트지 CSRF 가 아니다.
        cls.app.config['WTF_CSRF_ENABLED'] = False
        cls.app.config['TESTING'] = True
        cls.app_context = cls.app.app_context()
        cls.app_context.push()

    @classmethod
    def tearDownClass(cls):
        cls.app_context.pop()

    def setUp(self):
        self._tab = _uuid()
        self._output_id = _uuid()
        self._wipe()
        self._clear_scope_cache()

        self.role = Role(name='ScopeApprovalEditor', edit_controllers=True,
                         edit_settings=False, bypass_group_scope=False)
        db.session.add(self.role)
        db.session.commit()

        self.alice = self._user('scope-approval-alice')  # 그룹 소속
        self.bob = self._user('scope-approval-bob')       # 그룹 밖(같은 역할)
        db.session.commit()

        self.output = Output(unique_id=self._output_id, name=_OUTPUT_NAME,
                             output_type='virtual_on_off_single',
                             tab_id=self._tab)
        db.session.add(self.output)
        db.session.commit()

        self.group = UserGroup(name='ScopeApprovalGroup')
        db.session.add(self.group)
        db.session.flush()
        db.session.add(UserGroupMember(group_uuid=self.group.unique_id,
                                       user_uuid=self.alice.unique_id))
        db.session.add(GroupGrant(group_uuid=self.group.unique_id,
                                  resource_type=RESOURCE_TAB,
                                  resource_uuid=self._tab, level=LEVEL_OPERATE))
        db.session.commit()

        self.client = self.app.test_client()

    def tearDown(self):
        try:
            self._wipe()
        finally:
            self._clear_scope_cache()
            # `.delete(synchronize_session=False)` 는 세션의 identity map 을
            # 건드리지 않고 SQL 만 지운다 — sqlite 는 지워진 정수 PK 를 다음
            # 테스트에서 곧바로 재사용하므로, 지우고 남은 옛 객체가 identity
            # map 에 남아 있으면 다음 테스트가 새로 만든(같은 PK) 행과
            # 충돌한다(`test_scope_groups.py` 의 같은 패턴 참고).
            db.session.remove()

    def _wipe(self):
        MCPConfirmation.query.filter(
            MCPConfirmation.tool_name.in_(
                ['operate_device', 'set_output_state',
                 'schedule_device_control', 'create_notice'])).delete(
            synchronize_session=False)
        GroupGrant.query.delete(synchronize_session=False)
        UserGroupMember.query.delete(synchronize_session=False)
        UserGroup.query.filter(UserGroup.name == 'ScopeApprovalGroup').delete(
            synchronize_session=False)
        Output.query.filter(Output.name.in_(
            [_OUTPUT_NAME, _OTHER_OUTPUT_NAME])).delete(
            synchronize_session=False)
        User.query.filter(User.name.in_(
            ['scope-approval-alice', 'scope-approval-bob'])).delete(
            synchronize_session=False)
        Role.query.filter(Role.name == 'ScopeApprovalEditor').delete(
            synchronize_session=False)
        db.session.commit()

    @staticmethod
    def _clear_scope_cache():
        """스코프 리졸버의 캐시(`flask.g`)를 비운다.

        `g` 는 요청 컨텍스트가 아니라 **앱 컨텍스트**에 매인다. 이 fixture는
        클래스 전체에서 앱 컨텍스트를 한 번만 푸시해 두므로(`setUpClass`),
        `has_request_context()` 로 가드하면 요청 컨텍스트 밖인 setUp/tearDown
        에서는 아무것도 안 지워진다 — sqlite 가 삭제된 정수 PK 를 다음 테스트
        에서 재사용하는 순간 그 id 로 캐시된 옛 판정이 다른 사람에게 그대로
        적용된다. `has_app_context()` 로 봐야 한다.
        """
        try:
            from flask import g, has_app_context
            if has_app_context() and hasattr(g, '_aot_scope_cache'):
                del g._aot_scope_cache
        except Exception:
            pass

    def _user(self, name):
        row = User(name=name, role_id=self.role.id, is_enabled=True)
        db.session.add(row)
        db.session.flush()
        return row

    def _confirmation(self, tool_name, params, expires_in=300):
        import json
        from datetime import datetime, timedelta
        row = MCPConfirmation(
            expires_at=datetime.utcnow() + timedelta(seconds=expires_in),
            tool_name=tool_name,
            params_json=json.dumps(params),
            agent_id='test-agent',
            status='pending')
        row.save()
        return row

    def _login(self, user):
        """이 사용자로 로그인한 세션을 준비한다(HTTP 테스트 전용)."""
        with self.client.session_transaction() as sess:
            sess['_user_id'] = user.get_id()
            sess['_fresh'] = True


class TestApprovalGroupScope(_Fixture):
    """게이트 함수(`mcp_safety_gate.approve`)를 직접 부르는 단위 테스트.

    승인자 신원은 **명시적 `user_id`** 로 넘긴다 — 웹 라우트도 MCP
    `respond_to_confirmation` 도 실제로 그렇게 부른다(둘 다
    `flask_login.current_user`/세션에 기대지 않는다).
    """

    # -------------------------------------------------- 1. 남의 그룹 장치는 막힌다

    def test_out_of_group_editor_cannot_approve_physical_control(self):
        row = self._confirmation('operate_device',
                                 {'device_id': self._output_id, 'state': 'on'})
        result = gate.approve(row.unique_id, user_id=self.bob.unique_id)

        self.assertEqual(result.get('status'), 'error')
        self.assertEqual(result.get('reason_code'), 'group_scope_denied')

        refreshed = MCPConfirmation.query.filter_by(
            unique_id=row.unique_id).first()
        self.assertEqual(refreshed.status, 'pending',
                         '거부됐는데 상태가 바뀌었습니다 — 다른 승인자가 다시 볼 수 없습니다')

    def test_denial_is_audited(self):
        row = self._confirmation('operate_device',
                                 {'device_id': self._output_id, 'state': 'on'})
        gate.approve(row.unique_id, user_id=self.bob.unique_id)

        entry = (AuditLog.query.filter_by(target_id=self._output_id)
                .order_by(AuditLog.id.desc()).first())
        self.assertIsNotNone(entry, '스코프 거부가 감사 로그에 남지 않았습니다')
        self.assertEqual(entry.result, 'failure')
        self.assertEqual(entry.detail, 'denied by group scope')

    # -------------------------------------------------- 2. 그룹 안이면 정상 승인

    def test_in_group_editor_can_approve(self):
        row = self._confirmation('operate_device',
                                 {'device_id': self._output_id, 'state': 'on'})
        result = gate.approve(row.unique_id, user_id=self.alice.unique_id)

        self.assertEqual(result.get('status'), 'success')
        refreshed = MCPConfirmation.query.filter_by(
            unique_id=row.unique_id).first()
        self.assertEqual(refreshed.status, 'approved')

    def test_no_grants_at_all_means_anyone_can_approve(self):
        """미지정 = 전원 공개 — 이 구멍을 막는다고 그룹을 안 쓰는 설치까지
        막으면 안 된다."""
        GroupGrant.query.delete(synchronize_session=False)
        db.session.commit()
        row = self._confirmation('operate_device',
                                 {'device_id': self._output_id, 'state': 'on'})
        result = gate.approve(row.unique_id, user_id=self.bob.unique_id)
        self.assertEqual(result.get('status'), 'success')

    # -------------------------------------------------- 3. 이름으로 지목해도 같다

    def test_device_named_by_name_not_uuid_is_still_scoped(self):
        """`device_id` 는 uuid 뿐 아니라 이름도 받는다(실행층과 동일) — 이름을
        그대로 두면 uuid 모양 스캔에 안 걸려 통과해 버린다."""
        row = self._confirmation('operate_device',
                                 {'device_id': _OUTPUT_NAME, 'state': 'on'})
        result = gate.approve(row.unique_id, user_id=self.bob.unique_id)
        self.assertEqual(result.get('reason_code'), 'group_scope_denied')

    # -------------------------------------------------- 4. 나머지 두 물리 도구도 같다

    def test_schedule_device_control_is_scoped_too(self):
        row = self._confirmation(
            'schedule_device_control',
            {'device_id': self._output_id, 'state': 'on',
             'scheduled_time': '2099-01-01T00:00:00+00:00'})
        result = gate.approve(row.unique_id, user_id=self.bob.unique_id)
        self.assertEqual(result.get('reason_code'), 'group_scope_denied')

    def test_set_output_state_is_scoped_too(self):
        row = self._confirmation('set_output_state',
                                 {'device_id': self._output_id, 'state': 'on'})
        result = gate.approve(row.unique_id, user_id=self.bob.unique_id)
        self.assertEqual(result.get('reason_code'), 'group_scope_denied')

    # -------------------------------------------------- 5. 수정 후 승인은 바뀐 대상 기준

    def test_modified_params_are_scoped_by_the_new_target(self):
        """승인자가 대상을 다른 장치로 고쳐 승인하면, 원본이 아니라 **고친**
        장치 기준으로 판정해야 한다."""
        other_id = _uuid()
        other = Output(unique_id=other_id, name=_OTHER_OUTPUT_NAME,
                       output_type='virtual_on_off_single')  # 탭 없음 = 공개
        db.session.add(other)
        db.session.commit()

        row = self._confirmation(
            'operate_device', {'device_id': other_id, 'state': 'on'})
        # 원본 대상은 스코프 밖(탭 없음=공개)이라 통과해야 정상.
        result_before = gate.approve(row.unique_id, user_id=self.bob.unique_id)
        self.assertEqual(result_before.get('status'), 'success')

        row2 = self._confirmation(
            'operate_device', {'device_id': other_id, 'state': 'on'})
        result_after = gate.approve(
            row2.unique_id, user_id=self.bob.unique_id,
            modified_params={'device_id': self._output_id, 'state': 'on'})
        self.assertEqual(result_after.get('reason_code'),
                         'group_scope_denied',
                         '수정으로 바뀐 대상(그룹 밖 장치)을 기준으로 판정하지 않았습니다')

    # -------------------------------------------------- 6. 스코프 대상이 없는 도구는 영향 없음

    def test_tool_without_a_scoped_target_is_not_blocked(self):
        row = self._confirmation('create_notice', {'title': 'x'})
        result = gate.approve(row.unique_id, user_id=self.bob.unique_id)
        self.assertEqual(result.get('status'), 'success')

    # -------------------------------------------------- 7. 승인 즉시실행까지 막힌다

    def test_denied_approval_never_reaches_execution(self):
        """승인 자체가 거부되므로 `execute_approved()` 까지 가지 않는다 —
        route 는 `gate.approve()` 가 실패하면 `execute_approved()` 를 부르지
        않는다(`routes_mcp_api.mcp_confirmation_approve`)."""
        row = self._confirmation('operate_device',
                                 {'device_id': self._output_id, 'state': 'on'})
        result = gate.approve(row.unique_id, user_id=self.bob.unique_id)
        self.assertNotEqual(result.get('status'), 'success')
        refreshed = MCPConfirmation.query.filter_by(
            unique_id=row.unique_id).first()
        self.assertIsNone(refreshed.result_json,
                          '거부된 승인인데 실행 결과가 기록됐습니다')

    # -------------------------------------------------- 8. 로그인 세션 없는 MCP 경로(핵심 회귀)

    def test_explicit_user_id_is_honored_without_any_login_session(self):
        """`respond_to_confirmation`(MCP 도구) 경로를 재현한다: 실제 flask
        세션·`flask_login.current_user` 없이 `user_id` 만 명시적으로 넘긴다.

        `_decide()`가 이 값을 무시하고 `flask_login.current_user`(이 경로에선
        항상 익명)에만 기대면, 그룹 스코프가 켜진 설치에서 이 경로의 승인은
        승인자의 실제 그룹 소속과 무관하게 **항상** 거부된다 — 2026-09-18에
        이 수정 자체가 새로 만들 뻔한 회귀."""
        row = self._confirmation('operate_device',
                                 {'device_id': self._output_id, 'state': 'on'})
        with self.app.test_request_context():
            # flask_login.current_user 는 건드리지 않는다 — 로그인하지 않은
            # 요청 그대로(AnonymousUserMixin).
            result = gate.approve(row.unique_id, user_id=self.alice.unique_id)
        self.assertEqual(
            result.get('status'), 'success',
            '로그인 세션이 없다는 이유로 명시적 user_id(그룹 소속 정상)를 무시하고 거부했습니다')

    def test_explicit_user_id_still_denies_the_wrong_person(self):
        row = self._confirmation('operate_device',
                                 {'device_id': self._output_id, 'state': 'on'})
        with self.app.test_request_context():
            result = gate.approve(row.unique_id, user_id=self.bob.unique_id)
        self.assertEqual(result.get('reason_code'), 'group_scope_denied')

    # -------------------------------------------------- 9. user_id 를 안 넘기는 폴백

    def test_falls_back_to_current_user_when_no_user_id_given(self):
        """드문 호출자를 위한 폴백 — `user_id` 를 아예 안 넘기면
        `flask_login.current_user` 로 판정한다(웹 승인 화면·MCP 도구는 둘 다
        `user_id` 를 명시하므로 실제로는 거의 안 타는 경로)."""
        import flask_login
        row = self._confirmation('operate_device',
                                 {'device_id': self._output_id, 'state': 'on'})
        with self.app.test_request_context():
            flask_login.login_user(self.bob)
            try:
                result = gate.approve(row.unique_id)
            finally:
                flask_login.logout_user()
        self.assertEqual(result.get('reason_code'), 'group_scope_denied')


class TestApprovalGroupScopeHTTP(unittest.TestCase):
    """실제 HTTP 라운드트립으로 403 을 본다.

    소스에 게이트가 있다는 것과 그 게이트를 실제로 지난다는 것은 다르다 —
    같은 URL 을 다른 곳이 느슨하게 다시 등록했거나, 라우트가 게이트의
    반환값을 무시하는 경우가 그 차이를 만든다. 게이트 함수를 직접 부르는
    `TestApprovalGroupScope` 만으로는 이 배선을 검증하지 못한다.

    `_Fixture` 를 쓰지 않는다 — 그쪽은 클래스 전체에서 앱 컨텍스트를 한 번만
    푸시해 두는데, `test_client()` 로 실제 요청을 보내는 동안 그 컨텍스트가
    여전히 스택에 남아 있으면 Flask 가 "이미 이 앱의 컨텍스트가 있다"고 보고
    요청 자신의 앱 컨텍스트를 새로 만들지 않는다. 그 결과 요청 중간의
    `db.session.commit()`(예: 거부 시의 감사 로그)이 세션을 만료시키고, 다음
    테스트의 `setUp`이 그 뒤로 `db.session.remove()` 까지 하고 나면 이전
    컨텍스트에 물려 있던 객체가 어중간하게 detach 된다. 그래서 여기서는 DB
    준비/정리에만 짧게 `app_context()` 를 열고, 요청을 보내는 동안은 컨텍스트를
    스택에 남기지 않아 Flask 가 매 요청마다 스스로 깨끗한 컨텍스트를 만들게
    한다 — 실제 gunicorn 하에서 요청이 도착하는 방식과 같다.
    """

    @classmethod
    def setUpClass(cls):
        cls.app = create_app()
        cls.app.config['WTF_CSRF_ENABLED'] = False
        cls.app.config['TESTING'] = True
        cls.client = cls.app.test_client()

    def setUp(self):
        with self.app.app_context():
            db.create_all()
            self._wipe()

            self.role = Role(name='ScopeApprovalEditor',
                             edit_controllers=True, edit_settings=False,
                             bypass_group_scope=False)
            db.session.add(self.role)
            db.session.commit()

            alice = User(name='scope-approval-alice', role_id=self.role.id,
                        is_enabled=True)
            bob = User(name='scope-approval-bob', role_id=self.role.id,
                      is_enabled=True)
            db.session.add(alice)
            db.session.add(bob)
            db.session.commit()
            # 요청이 끝나면 이 객체들은 detach 된다 — 로그인에 필요한 값만
            # 문자열로 미리 뽑아 둔다.
            self.alice_login_id = alice.get_id()
            self.bob_login_id = bob.get_id()

            self._tab = _uuid()
            self._output_id = _uuid()
            output = Output(unique_id=self._output_id, name=_OUTPUT_NAME,
                            output_type='virtual_on_off_single',
                            tab_id=self._tab)
            db.session.add(output)
            db.session.commit()

            group = UserGroup(name='ScopeApprovalGroup')
            db.session.add(group)
            db.session.flush()
            db.session.add(UserGroupMember(group_uuid=group.unique_id,
                                           user_uuid=alice.unique_id))
            db.session.add(GroupGrant(group_uuid=group.unique_id,
                                      resource_type=RESOURCE_TAB,
                                      resource_uuid=self._tab,
                                      level=LEVEL_OPERATE))
            db.session.commit()
            self._clear_scope_cache()

    def tearDown(self):
        with self.app.app_context():
            try:
                self._wipe()
            finally:
                self._clear_scope_cache()
                db.session.remove()

    def _wipe(self):
        MCPConfirmation.query.filter(
            MCPConfirmation.tool_name == 'operate_device').delete(
            synchronize_session=False)
        GroupGrant.query.delete(synchronize_session=False)
        UserGroupMember.query.delete(synchronize_session=False)
        UserGroup.query.filter(UserGroup.name == 'ScopeApprovalGroup').delete(
            synchronize_session=False)
        Output.query.filter(Output.name == _OUTPUT_NAME).delete(
            synchronize_session=False)
        User.query.filter(User.name.in_(
            ['scope-approval-alice', 'scope-approval-bob'])).delete(
            synchronize_session=False)
        Role.query.filter(Role.name == 'ScopeApprovalEditor').delete(
            synchronize_session=False)
        db.session.commit()

    @staticmethod
    def _clear_scope_cache():
        try:
            from flask import g, has_app_context
            if has_app_context() and hasattr(g, '_aot_scope_cache'):
                del g._aot_scope_cache
        except Exception:
            pass

    def _confirmation(self):
        import json
        from datetime import datetime, timedelta
        row = MCPConfirmation(
            expires_at=datetime.utcnow() + timedelta(seconds=300),
            tool_name='operate_device',
            params_json=json.dumps({'device_id': self._output_id,
                                    'state': 'on'}),
            agent_id='test-agent',
            status='pending')
        row.save()
        return row.unique_id

    def _login(self, login_id):
        with self.client.session_transaction() as sess:
            sess['_user_id'] = login_id
            sess['_fresh'] = True

    def test_http_approve_is_403_for_out_of_group_editor(self):
        with self.app.app_context():
            confirmation_id = self._confirmation()
        self._login(self.bob_login_id)

        resp = self.client.post(
            '/api/v1/mcp/confirmations/{}/approve'.format(confirmation_id),
            content_type='application/json', data='{}')

        self.assertEqual(resp.status_code, 403,
                         '그룹 밖 승인이 HTTP {} 로 받아들여졌습니다'.format(
                             resp.status_code))
        body = resp.get_json()
        self.assertEqual(body.get('reason_code'), 'group_scope_denied')

        with self.app.app_context():
            refreshed = MCPConfirmation.query.filter_by(
                unique_id=confirmation_id).first()
            self.assertEqual(refreshed.status, 'pending')

    def test_http_approve_succeeds_for_in_group_editor(self):
        with self.app.app_context():
            confirmation_id = self._confirmation()
        self._login(self.alice_login_id)

        resp = self.client.post(
            '/api/v1/mcp/confirmations/{}/approve'.format(confirmation_id),
            content_type='application/json', data='{}')

        self.assertEqual(resp.status_code, 200,
                         '그룹 안 승인이 HTTP {} 로 거부됐습니다: {}'.format(
                             resp.status_code, resp.get_data(as_text=True)))
        self.assertEqual(resp.get_json().get('status'), 'success')


if __name__ == '__main__':
    unittest.main()
