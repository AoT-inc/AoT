# coding=utf-8
"""MCP 판정 순서 — 역할 → 그룹 스코프 → 인자·모호성 (2026-11-04 전수 실측 S1~S3).

  1. 묶인 출력 삭제가 관리자·구성원에게도 막히던 것(웹 삭제 유틸이 로그인 사용자만 봤다).
  2. 입력 켜기·끄기가 "이미 그 상태" 성공을 역할 검사보다 먼저 돌려주던 것.
  3·4. 인자 오류·그룹 스코프 거절이 역할 거절보다 먼저 나오던 것.
  5. 결정 권한 없는 역할이 자기 도구 묶음 변경을 승인하지 못하던 것.
  6. 탭 삭제 승인 문구(reason)에 함께 지워지는 개수가 없던 것.
"""
import json
from datetime import datetime

from aot.aot_flask.access import write_scope
from aot.aot_flask.extensions import db
from aot.databases.models import MCPConfirmation, Output, Tab, UserGroupMember
from aot.tests import test_mcp_record_write_guard as rw
from aot.tools import mcp_safety_gate as gate
from aot.tools import tool_execution as te
from aot.tools.domain import dispatch

_PREFIX = rw._PREFIX
_MARK = 'perm-order-test'


class _Base(rw._Fixture):

    def _join_group(self, who):
        group = rw.UserGroup.query.filter_by(name=_PREFIX + 'Group').first()
        db.session.add(UserGroupMember(group_uuid=group.unique_id,
                                       user_uuid=self.user_uuids[who]))
        db.session.commit()
        self._clear_scope_cache()


class TestScopedOutputDelete(_Base):
    """1 — 삭제의 스코프 판정이 수정과 같은 사람(호출에 묶인 사람)을 본다."""

    def _delete(self, who):
        self._clear_scope_cache()
        with self.app.test_request_context('/'):
            with write_scope.acting_as(self.user_uuids[who], tool='delete_output'):
                from aot.tools.aot_data_tool_service import AoTDataToolService
                return AoTDataToolService.delete_output(output_id=self.output_id)

    def test_member_can_delete_a_grouped_output(self):
        self._scope_to_other_group()
        self._join_group('Editor')
        out = self._delete('Editor')
        self.assertEqual(out.get('status'), 'deleted', out)
        db.session.remove()
        self.assertIsNone(Output.query.filter_by(unique_id=self.output_id).first())

    def test_non_member_is_still_refused(self):
        self._scope_to_other_group()
        with self.assertRaises(write_scope.WriteScopeDenied):
            self._delete('Editor')
        db.session.remove()
        self.assertIsNotNone(Output.query.filter_by(unique_id=self.output_id).first())


class TestRoleFirst(_Base):
    """3·4 — 역할 없는 호출자는 스코프·인자 사유를 듣지 않는다."""

    def test_group_scope_does_not_outrank_the_role(self):
        self._scope_to_other_group()
        for who in ('Monitor', 'Guest'):
            with self.subTest(who=who):
                body = self._call('modify_output',
                                  {'output_id': self.output_id, 'name': 'x'},
                                  self._role(who), scope_user_uuid=self.user_uuids[who])
                self.assertEqual(body.get('reason_code'), 'insufficient_role', body)

    def test_readonly_key_gets_role_not_scope(self):
        self._scope_to_other_group()
        body = self._call('delete_output', {'output_id': self.output_id},
                          self._role('Editor', readonly=True),
                          scope_user_uuid=self.user_uuids['Editor'])
        self.assertEqual(body.get('reason_code'), 'insufficient_role', body)

    def test_bad_arguments_do_not_outrank_the_role(self):
        body = self._call('modify_output', {}, self._role('Monitor'),
                          scope_user_uuid=self.user_uuids['Monitor'])
        self.assertEqual(body.get('reason_code'), 'insufficient_role', body)

    def test_allowed_role_still_sees_scope_reason(self):
        self._scope_to_other_group()
        body = self._call('modify_output',
                          {'output_id': self.output_id, 'name': 'x'},
                          self._role('Editor'),
                          scope_user_uuid=self.user_uuids['Editor'])
        self.assertEqual(body.get('reason_code'), 'group_scope', body)

    def test_domain_op_is_refused_before_target_resolution(self):
        """2·3 — 틀(dispatch)이 대상을 풀고 "이미 그 상태" 를 답하기 전에 거절한다."""
        args = {'op': 'activate', 'target': 'anything'}
        for who, ro in (('Monitor', False), ('Guest', False), ('Editor', True)):
            with self.subTest(who=who, readonly=ro):
                refused = dispatch._role_refusal_first(
                    'configure', dict(args), {'role': self._role(who, readonly=ro)})
                self.assertIsNotNone(refused)
                self.assertEqual(json.loads(refused[0]['text'])['reason_code'],
                                 'insufficient_role')
        ok = dispatch._role_refusal_first(
            'configure', dict(args), {'role': self._role('Editor')})
        self.assertIsNone(ok)


class TestRoleThenProfileFirst(_Base):
    """26-11-05 — 역할 → 도구 묶음 → 그 밖. 대상 풀기·별칭·help 도 역할 뒤, 묶음 밖은 인자 오류보다 앞."""

    def _first(self, tool, args, role, profile='configuration'):
        return dispatch._role_refusal_first(
            tool, dict(args), {'role': role, 'tool_profile': profile, 'transport': 'mcp_http'})

    def _code(self, refused):
        return None if refused is None else json.loads(refused[0]['text']).get('reason_code')

    def test_guest_and_kiosk_are_refused_on_resolve_aliases(self):
        for who in ('Guest', 'Kiosk'):
            for args in ({'op': 'aliases'}, {'op': 'resolve'}, {'op': 'resolve', 'target': 'x'}):
                with self.subTest(who=who, args=args):
                    self.assertEqual(self._code(self._first('find', args, self._role(who))),
                                     'insufficient_role')
        self.assertIsNone(self._first('find', {'op': 'aliases'}, self._role('Editor')))

    def test_help_refuses_roles_without_ai(self):
        for who in ('Guest', 'Kiosk'):
            with self.subTest(who=who):
                out = dispatch.run(None, 'help', {'op': 'op'}, role=self._role(who))
                self.assertEqual(json.loads(out[0]['text']).get('reason_code'), 'insufficient_role')

    def test_out_of_profile_beats_missing_arguments_and_already_so(self):
        role = self._role('Editor')
        for tool, args in (('configure', {'op': 'activate', 'target': 'anything', 'state': 'on'}),
                           ('find', {'op': 'tabs'}), ('detail', {'op': 'program'}),
                           ('detail', {'op': 'widget'}), ('find', {'op': 'device_types'})):
            with self.subTest(tool=tool, op=args['op']):
                self.assertEqual(self._code(self._first(tool, args, role, profile='operations')),
                                 'tool_profile')

    def test_role_still_outranks_profile(self):
        got = self._first('configure', {'op': 'activate', 'target': 'x'},
                          self._role('Monitor'), profile='operations')
        self.assertEqual(self._code(got), 'insufficient_role')

    def test_in_profile_call_passes_through(self):
        self.assertIsNone(self._first('configure', {'op': 'activate', 'target': 'x'},
                                      self._role('Editor')))


class TestOwnServiceDecision(_Base):
    """5 — 결정 권한 없는 역할도 자기 키의 도구 묶음 요청은 결정한다. 남의 것은 아니다."""

    def tearDown(self):
        db.session.rollback()
        MCPConfirmation.query.filter_by(title=_MARK).delete()
        db.session.commit()
        super().tearDown()

    def _pending(self, tool='set_tool_profile', agent=rw._AGENT):
        row = MCPConfirmation(
            expires_at=datetime(2100, 1, 1),
            tool_name=tool, params_json='{}', agent_id=agent, status='pending',
            title=_MARK)
        row.save()
        return row.unique_id

    def _reject(self, cid, who='Monitor'):
        self._clear_scope_cache()
        with self.app.test_request_context('/'):
            return te._respond_to_confirmation(
                {'decision': 'reject', 'confirmation_id': cid}, rw._AGENT,
                self._role(who))

    def test_monitor_decides_own_tool_profile_request(self):
        body = self._reject(self._pending())
        self.assertEqual(body.get('status'), 'success', body)

    def test_monitor_cannot_decide_someone_elses_request(self):
        body = self._reject(self._pending(agent='user:someone-else'))
        self.assertEqual(body.get('reason_code'), 'insufficient_role', body)

    def test_monitor_cannot_decide_a_non_service_request(self):
        body = self._reject(self._pending(tool='operate_device'))
        self.assertEqual(body.get('reason_code'), 'insufficient_role', body)

    def test_readonly_key_still_cannot(self):
        cid = self._pending()
        self._clear_scope_cache()
        with self.app.test_request_context('/'):
            body = te._respond_to_confirmation(
                {'decision': 'reject', 'confirmation_id': cid}, rw._AGENT,
                self._role('Monitor', readonly=True))
        self.assertEqual(body.get('reason_code'), 'insufficient_role', body)

    def test_tool_stays_listed_for_monitor_only_as_own_service(self):
        self.assertNotIn('respond_to_confirmation', te._hidden_tools(self._role('Monitor')))
        self.assertIn('respond_to_confirmation',
                      te._hidden_tools(self._role('Monitor', readonly=True)))


class TestTabDeleteBriefing(_Base):
    """6 — 승인 화면의 reason 에 함께 지워지는 항목 수."""

    def test_briefing_says_what_goes_with_the_tab(self):
        tab = Tab(unique_id=rw._uuid(), name=_PREFIX + 'Tab', page_type='output',
                  position=998)
        db.session.add(tab)
        db.session.add(Output(unique_id=rw._uuid(), name=_PREFIX + 'Valve2',
                              output_type='virtual_on_off_single', tab_id=tab.unique_id))
        db.session.commit()
        try:
            with self.app.test_request_context('/'):
                text = gate._build_human_briefing('delete_tab', {'tab_id': tab.unique_id})
            self.assertIn('함께 지워집니다', text)
            self.assertIn('1개', text)
        finally:
            Output.query.filter(Output.name == _PREFIX + 'Valve2').delete()
            Tab.query.filter_by(unique_id=tab.unique_id).delete()
            db.session.commit()
