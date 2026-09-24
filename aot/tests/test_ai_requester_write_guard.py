# coding=utf-8
"""인앱 AI 쓰기의 요청자 권한 — 워커 스레드·이름 대상·승인 면제 쓰기.

2026-09-23 검토에서 재현된 구멍 셋을 고정한다.

  1. **계획 실행기 워커 스레드.** 병렬 단계는 ThreadPoolExecutor 에서 돈다.
     예전에는 "사람이 있는가" 를 `has_request_context()` 로 판정해, 워커의
     단계가 백그라운드로 보여 역할·그룹 스코프 검사를 통째로 건너뛰었다
     (Monitor 가 계획 단계로 노트를 저장). 이제 요청자를 명시적 표지로
     들고 다닌다(`ai_request_context.bind_worker`).
  2. **이름으로 준 대상.** 그룹 스코프 판정은 인자의 uuid 만 훑는데,
     `create_note`·`add_schedule` 은 `target_name` 을 처리기가 나중에 푼다.
     id 로 주면 막히고 이름으로 주면 통과했다. 이제 판정 전에 처리기와 같은
     리졸버로 풀어 본다.
  3. **승인 면제 쓰기(config_only).** 인앱 채팅의 `add_schedule`·
     `modify_function_options`·`create_program` 같은 설정 편집은 승인 대상이
     아니어서 요청자 역할을 아무도 보지 않았다. 이제 외부 MCP 게이트와 같은
     기준이다 — 기록 쓰기는 `edit_settings`, 작기 운영(구획·작기 프로그램)은
     `edit_plots`, 나머지 쓰기는 `edit_controllers`.

사람이 없는 호출(요청자 표지가 없는 백그라운드 잡)은 지금처럼 면제다.
"""
from concurrent.futures import ThreadPoolExecutor
from unittest import mock

import flask_login

from aot.aot_flask.extensions import db
from aot.databases.models import Notes, UserGroup, UserGroupMember
from aot.tests.test_mcp_record_write_guard import _NOTE_MARK, _PREFIX, _Fixture
from aot.tools import tool_execution as te

_CONFIG_TOOLS = ('modify_function_options', 'add_schedule', 'create_program')


def _svc():
    from aot.ai.services.ai_action_service import AIActionService
    return AIActionService


class _Base(_Fixture):

    def _vparams(self, tool, args):
        return {'tool_name': tool, 'arguments': dict(args)}

    def _as_user(self, name, fn):
        """`name` 으로 로그인한 실제 요청 안에서 fn() 을 부른다."""
        self._clear_scope_cache()
        user = self._user(name)
        with self.app.test_request_context():
            flask_login.login_user(user)
            return fn()

    def _in_worker(self, name, action_type, params, target='system_internal'):
        """계획 실행기처럼: 요청 스레드에서 bind_worker 로 감싸 워커에서 실행."""
        from aot.ai import ai_request_context as ctx

        def _submit():
            with ThreadPoolExecutor(max_workers=1) as pool:
                return pool.submit(ctx.bind_worker(
                    _svc().execute_action), action_type, target,
                    dict(params)).result()
        return self._as_user(name, _submit)

    def _in_bare_worker(self, action_type, params, target='system_internal'):
        """사람이 없는 백그라운드 — 요청도 표지도 없다."""
        with ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(_svc().execute_action, action_type, target,
                               dict(params)).result()

    def _grant_group_to(self, name):
        group = UserGroup.query.filter(UserGroup.name == _PREFIX + 'Group').first()
        db.session.add(UserGroupMember(group_uuid=group.unique_id,
                                       user_uuid=self.user_uuids[name]))
        db.session.commit()

    @staticmethod
    def _fake_handlers(names):
        handlers = {n: mock.Mock(return_value={'status': 'success', 'ok': True})
                    for n in names}
        return handlers, mock.patch('aot.tools.tool_registry.build_tool_map',
                                    return_value=handlers)


# ---------------------------------------------------------------------------
# 1. 계획 실행기 워커 스레드
# ---------------------------------------------------------------------------

class TestPlannerWorkerThread(_Base):

    def test_monitor_note_in_worker_is_refused(self):
        res = self._in_worker('Monitor', 'virtual_tool_call',
                              self._vparams('create_note', self._note_args()))
        self.assertEqual(res.get('reason_code'), 'insufficient_role', res)
        self.assertEqual(self._notes(), 0)

    def test_editor_note_in_worker_is_allowed(self):
        res = self._in_worker('Editor', 'virtual_tool_call',
                              self._vparams('create_note', self._note_args()))
        self.assertEqual(res.get('status'), 'success', res)
        self.assertEqual(self._notes(), 1)

    def test_background_worker_without_requester_is_unchanged(self):
        res = self._in_bare_worker(
            'virtual_tool_call', self._vparams('create_note', self._note_args()))
        self.assertEqual(res.get('status'), 'success', res)
        self.assertEqual(self._notes(), 1)

    def test_group_scope_applies_in_worker(self):
        self._scope_to_other_group()
        res = self._in_worker('Editor', 'virtual_tool_call', self._vparams(
            'create_note', self._note_args(target_id=self.output_id,
                                           target_type='output')))
        self.assertEqual(res.get('reason_code'), 'group_scope', res)
        self.assertEqual(self._notes(), 0)

    def test_real_action_chain_refuses_monitor(self):
        """실제 `_execute_action_chain` — 단계가 워커 스레드에서 돈다."""
        from aot.ai.services.ai_planning_service import AIPlanningService
        for name, expect_notes in (('Monitor', 0), ('Editor', 1)):
            with self.subTest(role=name):
                Notes.query.filter(Notes.note.like(_NOTE_MARK + '%')).delete(
                    synchronize_session=False)
                db.session.commit()
                plan = {'steps': [{
                    'step_id': 1, 'action_type': 'virtual_tool_call',
                    'target_id': 'system_internal',
                    'params': self._vparams('create_note', self._note_args())}]}
                logs, pending, _outcomes = self._as_user(
                    name, lambda: AIPlanningService._execute_action_chain(
                        'auto', plan, {}))
                self.assertEqual(pending, [])
                self.assertEqual(self._notes(), expect_notes, logs)

    def test_worker_restores_previous_requester(self):
        from aot.ai import ai_request_context as ctx

        def _peek():
            return ctx.get_requester()

        def _run():
            with ThreadPoolExecutor(max_workers=1) as pool:
                bound = pool.submit(ctx.bind_worker(_peek)).result()
                after = pool.submit(_peek).result()
            return bound, after
        bound, after = self._as_user('Editor', _run)
        self.assertEqual(bound.user_uuid, self.user_uuids['Editor'])
        self.assertIsNone(after)
        self.assertNotIn(self.user_uuids['Editor'], repr(bound))

    def test_builtin_mcp_resolver_passes_requester_as_scope_identity(self):
        from aot.ai import ai_request_context as ctx
        from aot.ai.services.resolvers import mcp_tool_call_resolver as mod
        got = {}
        with mock.patch.object(mod, '_is_builtin_server', lambda sid: True), \
                mock.patch.object(te, 'execute_for_agent',
                                  lambda *a, **kw: got.update(kw) or
                                  {'status': 'success', 'result': {}}):
            prev = ctx.set_requester(ctx.Requester('someone'))
            try:
                mod.MCPToolCallResolver().execute(
                    'mcp_tool_call', 'srv', {'tool_name': 'create_note'}, None)
            finally:
                ctx.restore_requester(prev)
            self.assertEqual(got['scope_user_uuid'], 'someone')
            got.clear()
            mod.MCPToolCallResolver().execute(
                'mcp_tool_call', 'srv', {'tool_name': 'create_note'}, None)
            self.assertIsNone(got['scope_user_uuid'])   # 백그라운드

    def test_synthetic_request_is_not_a_person(self):
        """코드가 연 test_request_context(도구 실행) 안의 중첩 호출은 사람이 아니다."""
        from aot.ai import ai_request_context as ctx
        with self.app.test_request_context():
            ctx.mark_synthetic_request()
            self.assertIsNone(ctx.current_requester())
            res = _svc().execute_action(
                'virtual_tool_call', 'system_internal',
                self._vparams('create_note', self._note_args()))
        self.assertEqual(res.get('status'), 'success', res)


# ---------------------------------------------------------------------------
# 2. 이름(target_name)으로 준 대상의 그룹 스코프
# ---------------------------------------------------------------------------

class TestTargetNameScope(_Base):

    def _schedule_args(self, **extra):
        args = {'date': '2030-01-02', 'time': '09:00', 'content': 'scope test'}
        args.update(extra)
        return args

    def test_note_by_name_out_of_scope_is_refused(self):
        self._scope_to_other_group()
        with mock.patch.object(te, '_dispatch_virtual_tool') as run:
            body = self._call('create_note',
                              self._note_args(target_name=_PREFIX + 'Valve'),
                              self._role('Editor'),
                              scope_user_uuid=self.user_uuids['Editor'])
            run.assert_not_called()
        self.assertEqual(body.get('reason_code'), 'group_scope', body)
        self.assertEqual(body.get('call_state'), 'refused')
        self.assertEqual(self._last_audit().call_state, 'refused')
        self.assertEqual(self._notes(), 0)

    def test_note_by_name_in_scope_is_allowed(self):
        self._scope_to_other_group()
        self._grant_group_to('Editor')
        body = self._call('create_note',
                          self._note_args(target_name=_PREFIX + 'Valve'),
                          self._role('Editor'),
                          scope_user_uuid=self.user_uuids['Editor'])
        self.assertEqual(body.get('call_state'), 'executed', body)
        db.session.remove()
        self.assertEqual(Notes.query.filter(
            Notes.target_id == self.output_id).count(), 1)

    def test_note_by_legacy_alias_is_resolved_too(self):
        self._scope_to_other_group()
        body = self._call('create_note',
                          self._note_args(location=_PREFIX + 'Valve'),
                          self._role('Editor'),
                          scope_user_uuid=self.user_uuids['Editor'])
        self.assertEqual(body.get('reason_code'), 'group_scope', body)

    def test_schedule_by_name_out_of_scope_is_refused(self):
        self._scope_to_other_group()
        with mock.patch.object(te, '_dispatch_virtual_tool') as run:
            body = self._call('add_schedule',
                              self._schedule_args(target_name=_PREFIX + 'Valve'),
                              self._role('Editor'),
                              scope_user_uuid=self.user_uuids['Editor'])
            run.assert_not_called()
        self.assertEqual(body.get('reason_code'), 'group_scope', body)
        self.assertEqual(self._last_audit().call_state, 'refused')

    def test_schedule_by_name_in_scope_is_allowed(self):
        self._scope_to_other_group()
        self._grant_group_to('Editor')
        with mock.patch.object(te, '_dispatch_virtual_tool',
                               return_value={'status': 'success'}) as run:
            body = self._call('add_schedule',
                              self._schedule_args(target_name=_PREFIX + 'Valve'),
                              self._role('Editor'),
                              scope_user_uuid=self.user_uuids['Editor'])
            run.assert_called_once()
        self.assertEqual(body.get('call_state'), 'executed', body)

    def test_schedule_batch_entry_names_are_checked(self):
        self._scope_to_other_group()
        with mock.patch.object(te, '_dispatch_virtual_tool') as run:
            body = self._call('add_schedule_batch', {
                'date': '2030-01-02',
                'entries': [{'target_name': _PREFIX + 'Valve', 'time': '09:00'}]},
                self._role('Editor'), scope_user_uuid=self.user_uuids['Editor'])
            run.assert_not_called()
        self.assertEqual(body.get('reason_code'), 'group_scope', body)

    def test_unknown_name_is_left_to_the_handler(self):
        args = self._note_args(target_name='no-such-place-xyz')
        self.assertEqual(te.scope_arguments('create_note', args), args)

    def test_read_tools_are_not_resolved(self):
        with mock.patch.object(te, '_resolve_name_for_scope') as res:
            te.scope_arguments('search_notes', {'target_name': _PREFIX + 'Valve'})
            res.assert_not_called()

    def test_in_app_note_by_name_out_of_scope_is_refused(self):
        self._scope_to_other_group()
        res = self._as_user('Editor', lambda: _svc().execute_action(
            'virtual_tool_call', 'system_internal', self._vparams(
                'create_note', self._note_args(target_name=_PREFIX + 'Valve'))))
        self.assertEqual(res.get('reason_code'), 'group_scope', res)
        self.assertEqual(self._notes(), 0)

    def test_chat_approval_checks_names_too(self):
        from aot.ai.services.ai_agent_service import AIAgentService
        self._scope_to_other_group()
        params = self._vparams('add_schedule',
                               self._schedule_args(target_name=_PREFIX + 'Valve'))
        reason = self._as_user('Editor', lambda: AIAgentService._approval_denial(
            'virtual_tool_call', 'system_internal', params))
        self.assertTrue(reason)


# ---------------------------------------------------------------------------
# 3. 승인 면제 쓰기(config_only)의 요청자 역할
# ---------------------------------------------------------------------------

class TestConfigOnlyWrites(_Base):

    def test_monitor_cannot_run_config_writes_directly(self):
        handlers, patch = self._fake_handlers(_CONFIG_TOOLS)
        with patch:
            for tool in _CONFIG_TOOLS:
                with self.subTest(tool=tool):
                    res = self._as_user('Monitor', lambda: _svc().execute_action(
                        'virtual_tool_call', 'system_internal',
                        self._vparams(tool, {'name': 'x'})))
                    self.assertEqual(res.get('reason_code'), 'insufficient_role', res)
                    # 작기 프로그램은 웹과 같은 edit_plots, 나머지는 edit_controllers.
                    _want = ('edit_plots' if tool == 'create_program'
                             else 'edit_controllers')
                    self.assertIn(_want, res.get('message', ''))
        for h in handlers.values():
            h.assert_not_called()

    def test_monitor_cannot_run_config_writes_in_worker(self):
        handlers, patch = self._fake_handlers(_CONFIG_TOOLS)
        with patch:
            for tool in _CONFIG_TOOLS:
                with self.subTest(tool=tool):
                    res = self._in_worker('Monitor', 'virtual_tool_call',
                                          self._vparams(tool, {'name': 'x'}))
                    self.assertEqual(res.get('reason_code'), 'insufficient_role', res)
        for h in handlers.values():
            h.assert_not_called()

    def test_editor_and_admin_unchanged(self):
        handlers, patch = self._fake_handlers(_CONFIG_TOOLS)
        with patch:
            for name in ('Editor', 'Admin'):
                for tool in _CONFIG_TOOLS:
                    with self.subTest(role=name, tool=tool):
                        res = self._as_user(name, lambda: _svc().execute_action(
                            'virtual_tool_call', 'system_internal',
                            self._vparams(tool, {'name': 'x'})))
                        self.assertEqual(res.get('status'), 'success', res)
                res = self._in_worker(name, 'virtual_tool_call',
                                      self._vparams('modify_function_options',
                                                    {'name': 'x'}))
                self.assertEqual(res.get('status'), 'success', res)

    def test_control_only_role_may_edit_config(self):
        """설정 편집 도구는 제어 권한(edit_controllers) 기준이다 — MCP 게이트와 같다."""
        handlers, patch = self._fake_handlers(('modify_function_options',))
        with patch:
            res = self._as_user('ControlOnly', lambda: _svc().execute_action(
                'virtual_tool_call', 'system_internal',
                self._vparams('modify_function_options', {'name': 'x'})))
        self.assertEqual(res.get('status'), 'success', res)

    def test_background_config_write_is_unchanged(self):
        handlers, patch = self._fake_handlers(('modify_function_options',))
        with patch:
            res = _svc().execute_action(
                'virtual_tool_call', 'system_internal',
                self._vparams('modify_function_options', {'name': 'x'}))
        self.assertEqual(res.get('status'), 'success', res)
        handlers['modify_function_options'].assert_called_once()

    def test_monitor_reads_still_work(self):
        handlers, patch = self._fake_handlers(('get_function_list',))
        with patch:
            res = self._as_user('Monitor', lambda: _svc().execute_action(
                'virtual_tool_call', 'system_internal',
                self._vparams('get_function_list', {})))
        self.assertEqual(res.get('status'), 'success', res)

    def test_monitor_legacy_write_action_type_is_refused(self):
        res = self._as_user('Monitor', lambda: _svc().execute_action(
            'pid', self.output_id, {'setting': 'setpoint', 'value': 1}))
        self.assertEqual(res.get('reason_code'), 'insufficient_role', res)


# ---------------------------------------------------------------------------
# 4. 분류 실패 시 닫힌다
# ---------------------------------------------------------------------------

class TestFailClosed(_Base):

    def test_registry_failure_still_refuses_monitor_note(self):
        from aot.tools import tool_registry as R
        with mock.patch.object(R, 'record_write_tools',
                               side_effect=RuntimeError('boom')):
            res = self._as_user('Monitor', lambda: _svc().execute_action(
                'virtual_tool_call', 'system_internal',
                self._vparams('create_note', self._note_args())))
        self.assertEqual(res.get('reason_code'), 'insufficient_role', res)
        self.assertEqual(self._notes(), 0)


# ---------------------------------------------------------------------------
# 5. 검토 재현 스크립트의 나머지 사례 — 인증 없는 조언 제출
# ---------------------------------------------------------------------------

class TestUnauthenticatedAdvice(_Base):

    def test_unauthenticated_caller_can_still_submit_advice(self):
        """인증을 끈 서버(role=None)도 조언은 낼 수 있다 — 문서의 계약."""
        with mock.patch.object(te, '_dispatch_virtual_tool',
                               return_value={'status': 'success'}) as run:
            body = self._call('submit_advice', {'title': 't', 'advice': 'a'}, None)
        self.assertEqual(body.get('call_state'), 'executed', body)
        run.assert_called_once()
