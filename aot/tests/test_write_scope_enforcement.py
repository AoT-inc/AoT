# coding=utf-8
"""쓰기 시점 그룹 스코프 — **처리기가 실제로 쓸 대상**에서 묻는다.

정본 설계: `docs/design/access-scope-groups.md` §6-2a

검토 세 차례가 매번 새 우회를 찾은 이유는, 스코프 판정이 처리기보다 먼저
인자를 훑어 대상을 **짐작**했기 때문이다. 처리기는 대상을 이름·별칭·중첩
인자·다른 모델 종류로 푼다. 이제 경계는 처리기와 공용 리졸버가 쓸 행을 손에
쥔 자리의 `write_scope.enforce` 이고, 앞의 짐작 검사는 이른 거부다.

2026-09-23 재현된 우회(① ~ ④)와 결정 둘(⑤ 승인 권한, ⑥ 지도 편집 권한)을
고정한다. 각 우회는 **두 겹 모두** 확인한다 — 실행 경로 전체(앞 판정 포함)와,
앞 판정을 건너뛰고 처리기를 곧바로 묶어 부를 때(쓰기 시점 강제만).

끝의 `TestEveryWriteToolIsCovered` 는 레지스트리의 쓰기 도구 전부가 강제 자리를
지나거나 "스코프 대상 아님" 으로 이유와 함께 분류됐는지 본다 — 새 쓰기 도구가
분류 없이 들어오면 실패한다.
"""
import inspect
import json
import uuid
from unittest import mock

from aot.aot_flask.access import scope, write_scope
from aot.aot_flask.extensions import db
from aot.databases.models import (Dashboard, GeoShape, GroupGrant, Input,
                                  MCPConfirmation, Role, SchedulerJobMeta,
                                  User, UserGroup, Widget)
from aot.databases.models.function import Actions, Conditional, Trigger
from aot.databases.models.user_group import (LEVEL_OPERATE,
                                             RESOURCE_DASHBOARD)
from aot.tests.test_ai_requester_write_guard import _Base, _svc
from aot.tests.test_mcp_record_write_guard import _PREFIX
from aot.tools import mcp_safety_gate as gate
from aot.tools import tool_execution as te

V = _PREFIX + 'Valve'


def _svc_tools():
    from aot.tools.aot_data_tool_service import AoTDataToolService
    return AoTDataToolService


def _sched(**k):
    a = {'date': '2030-01-02', 'time': '09:00', 'content': 'ws-test'}
    a.update(k)
    return a


class _WS(_Base):
    """고정물: 다른 그룹에만 부여된 탭 안의 출력·입력·조건·시퀀스·단계,
    그 탭을 가리키는 일정, 다른 그룹 대시보드와 위젯, 장치에 연결된 도형."""

    def setUp(self):
        super().setUp()
        self.trig = str(uuid.uuid4())
        self.cond = str(uuid.uuid4())
        self.inp = str(uuid.uuid4())
        self.action = str(uuid.uuid4())
        self.dash = str(uuid.uuid4())
        self.widget = str(uuid.uuid4())
        self.shape = str(uuid.uuid4())
        db.session.add(Trigger(unique_id=self.trig, name=_PREFIX + 'Seq',
                               trigger_type='trigger_sequence', tab_id=self._tab))
        db.session.add(Conditional(unique_id=self.cond, name=_PREFIX + 'Cond',
                                   tab_id=self._tab, is_activated=False))
        db.session.add(Input(unique_id=self.inp, name=_PREFIX + 'Sensor',
                             tab_id=self._tab))
        db.session.add(Actions(unique_id=self.action, function_id=self.trig,
                               action_type='output_on_off',
                               custom_options=json.dumps({'output': self.output_id})))
        db.session.add(Dashboard(unique_id=self.dash, name=_PREFIX + 'Board'))
        db.session.add(Widget(unique_id=self.widget, name=_PREFIX + 'Widget',
                              tab_id=self.dash, graph_type='indicator'))
        db.session.add(GeoShape(unique_id=self.shape, geo_id='ws-map',
                                device_id=self.output_id, type='feature',
                                feature={'type': 'Feature', 'geometry': None,
                                         'properties': {}}))
        role = Role(name=_PREFIX + 'PlotOnly', edit_plots=True, edit_settings=False,
                    edit_controllers=False, edit_users=False, use_ai_chat=True)
        db.session.add(role)
        db.session.commit()
        row = User(name=(_PREFIX + 'PlotOnly').lower(), role_id=role.id,
                   is_enabled=True)
        db.session.add(row)
        db.session.commit()
        self.user_uuids['PlotOnly'] = row.unique_id

    def tearDown(self):
        db.session.rollback()
        for model, uid in ((Trigger, self.trig), (Conditional, self.cond),
                           (Input, self.inp), (Actions, self.action),
                           (Widget, self.widget), (Dashboard, self.dash),
                           (GeoShape, self.shape)):
            model.query.filter(model.unique_id == uid).delete(
                synchronize_session=False)
        Trigger.query.filter(Trigger.name.like(_PREFIX + '%')).delete(
            synchronize_session=False)
        SchedulerJobMeta.query.filter(
            SchedulerJobMeta.target_id == self.output_id).delete(
                synchronize_session=False)
        db.session.commit()
        super().tearDown()

    # -- 도우미 ------------------------------------------------------------

    def _scope_board_to_other_group(self):
        group = UserGroup.query.filter(UserGroup.name == _PREFIX + 'Group').first()
        db.session.add(GroupGrant(group_uuid=group.unique_id,
                                  resource_type=RESOURCE_DASHBOARD,
                                  resource_uuid=self.dash, level=LEVEL_OPERATE))
        db.session.commit()

    def _ext(self, tool, args, who='Editor'):
        """외부 MCP 경로 전체 — 처리기는 가짜(불렸는지만 본다)."""
        with mock.patch.object(te, '_dispatch_virtual_tool',
                               return_value={'status': 'success'}) as run:
            body = self._call(tool, args, self._role(who),
                              scope_user_uuid=self.user_uuids[who])
        return body.get('call_state'), body.get('reason_code'), run.called

    def _direct(self, who, fn):
        """앞 판정 없이 처리기를 곧바로 — `who` 로 묶고 부른다.

        Returns: ('denied', uuid) 또는 ('ran', 결과)."""
        self._clear_scope_cache()
        with self.app.test_request_context():
            with write_scope.acting_as(self.user_uuids[who], tool='test'):
                try:
                    return 'ran', fn()
                except write_scope.WriteScopeDenied as exc:
                    db.session.rollback()
                    return 'denied', exc.resource_uuid

    def _jobs(self):
        db.session.remove()
        return SchedulerJobMeta.query.filter(
            SchedulerJobMeta.target_id == self.output_id).count()

    def _cond_active(self):
        db.session.remove()
        return bool(Conditional.query.filter_by(unique_id=self.cond).first().is_activated)

    def _make_job(self):
        """관리자가(스코프 면제) 다른 그룹 출력에 일정을 하나 만든다 — 정수 id."""
        body = self._call('add_schedule', _sched(target_id=self.output_id),
                          self._role('Admin'), scope_user_uuid=self.user_uuids['Admin'])
        self.assertEqual(body.get('call_state'), 'executed', body)
        db.session.remove()
        meta = SchedulerJobMeta.query.filter(
            SchedulerJobMeta.target_id == self.output_id).first()
        return meta


# ---------------------------------------------------------------------------
# ① 함수 id 자리에 이름
# ---------------------------------------------------------------------------

class TestFunctionNameInIdSlot(_WS):

    _TOOLS = (('modify_sequence_schedule', {'start': '05:00'}, 'Seq'),
              ('configure_sequence_day',
               {'day': 0, 'slots': [{'devices': ['x'], 'minutes': 1}]}, 'Seq'),
              ('activate_function', {}, 'Cond'),
              ('deactivate_function', {}, 'Cond'))

    def test_external_refuses_by_name_and_by_uuid(self):
        self._scope_to_other_group()
        for tool, extra, kind in self._TOOLS:
            fid = {'Seq': self.trig, 'Cond': self.cond}[kind]
            for label, token in (('name', _PREFIX + kind), ('uuid', fid)):
                with self.subTest(tool=tool, by=label):
                    state, code, called = self._ext(tool, dict(extra, function_id=token))
                    self.assertEqual((state, code, called),
                                     ('refused', 'group_scope', False))

    def test_handlers_enforce_on_the_resolved_row(self):
        """앞 판정이 없어도 처리기가 찾은 행으로 거부한다."""
        self._scope_to_other_group()
        S = _svc_tools()
        cases = (
            ('modify_sequence_schedule', lambda: S.modify_sequence_schedule(
                function_id=_PREFIX + 'Seq', start='05:00')),
            ('configure_sequence_day', lambda: S.configure_sequence_day(
                function_id=_PREFIX + 'Seq', day=0,
                slots=[{'devices': [V], 'minutes': 1}])),
            ('activate_function', lambda: S.activate_function_tool(
                function_id=_PREFIX + 'Cond')),
            ('legacy activate', lambda: S._set_entity_activation(
                _PREFIX + 'Cond', True)),
            ('modify_function_options', lambda: S.modify_function_options(
                function_id=self.cond, params={'x': 1})),
            ('delete_function', lambda: S.delete_function(function_id=self.cond)),
        )
        for label, fn in cases:
            with self.subTest(handler=label):
                outcome, _ = self._direct('Editor', fn)
                self.assertEqual(outcome, 'denied')
        self.assertFalse(self._cond_active())

    def test_approver_scope_check_resolves_names(self):
        self._scope_to_other_group()
        ed = self._user('Editor')
        self.assertIsNotNone(gate._approval_scope_denial(
            'activate_function', {'function_id': _PREFIX + 'Cond'}, user=ed))

    def test_in_app_virtual_by_name_is_refused(self):
        self._scope_to_other_group()
        handlers, patch = self._fake_handlers(('modify_sequence_schedule',))
        with patch:
            r = self._as_user('Editor', lambda: _svc().execute_action(
                'virtual_tool_call', 'system_internal', self._vparams(
                    'modify_sequence_schedule',
                    {'function_id': _PREFIX + 'Seq', 'start': '05:00'})))
        self.assertEqual(r.get('reason_code'), 'group_scope', r)
        self.assertFalse(handlers['modify_sequence_schedule'].called)

    def test_legacy_activate_by_name_does_not_turn_it_on(self):
        self._scope_to_other_group()
        r = self._as_user('Editor', lambda: _svc().execute_action(
            'activate', _PREFIX + 'Cond', {}))
        self.assertEqual(r.get('reason_code'), 'group_scope', r)
        self.assertFalse(self._cond_active())

    def test_in_group_by_name_still_runs(self):
        self._scope_to_other_group()
        self._grant_group_to('Editor')
        state, code, called = self._ext('modify_sequence_schedule',
                                        {'function_id': _PREFIX + 'Seq',
                                         'start': '05:00'})
        self.assertEqual((state, called), ('executed', True), code)
        outcome, _ = self._direct('Editor', lambda: _svc_tools()
                                  .modify_sequence_schedule(
                                      function_id=_PREFIX + 'Seq', start='05:00'))
        self.assertEqual(outcome, 'ran')


# ---------------------------------------------------------------------------
# ② 일괄 항목이 한계를 넘으면
# ---------------------------------------------------------------------------

class TestBatchBeyondScanLimit(_WS):

    def _entries(self, n):
        ents = [{'target_name': 'ws-nowhere-%03d' % i, 'time': '09:00'}
                for i in range(n)]
        ents.append({'target_name': V, 'time': '10:00'})
        return ents

    def test_201_entries_are_refused_and_nothing_is_created(self):
        self._scope_to_other_group()
        before = self._jobs()
        body = self._call('add_schedule_batch',
                          {'date': '2030-01-06', 'content': 'ws',
                           'entries': self._entries(scope.SCAN_MAX_ITEMS)},
                          self._role('Editor'), scope_user_uuid=self.user_uuids['Editor'])
        self.assertEqual(body.get('call_state'), 'refused', body)
        self.assertEqual(self._jobs(), before)

    def test_handler_refuses_the_last_entry_even_without_the_precheck(self):
        self._scope_to_other_group()
        outcome, _ = self._direct('Editor', lambda: _svc_tools()
                                  .add_schedule_batch_tool(
                                      date='2030-01-06', content='ws',
                                      entries=self._entries(3)))
        self.assertEqual(outcome, 'denied')
        self.assertEqual(self._jobs(), 0)

    def test_limit_refusal_only_when_scoping_is_in_use(self):
        ed = self._user('Editor')
        big = {'entries': [{'x': i} for i in range(scope.SCAN_MAX_ITEMS + 1)]}
        self.assertEqual(scope.can_operate_tool_call('add_schedule_batch', big,
                                                     user=ed), (True, None))
        self._scope_to_other_group()
        self._clear_scope_cache()
        self.assertEqual(scope.can_operate_tool_call('add_schedule_batch', big,
                                                     user=ed),
                         (False, scope.SCAN_LIMIT))
        deep = {'a': {'b': {'c': {'d': {'e': {'f': {'g': {'h': {'i': {'j': 1}}}}}}}}}}
        self.assertTrue(scope.scan_limits_exceeded(deep))
        # 판정 사본에 덧붙인 풀린 id 목록은 호출자가 보낸 것이 아니라 세지 않는다.
        resolved = {te.SCOPE_RESOLVED_KEY: ['x%d' % i
                                            for i in range(scope.SCAN_MAX_ITEMS * 2)]}
        self.assertEqual(scope.can_operate_tool_call('add_schedule_batch', resolved,
                                                     user=ed), (True, None))


# ---------------------------------------------------------------------------
# ③ 인앱 {'arguments': {}, 'params': {...}}
# ---------------------------------------------------------------------------

class TestInAppArgumentShapes(_WS):

    def test_empty_arguments_with_params_is_checked(self):
        self._scope_to_other_group()
        before = self._jobs()
        r = self._as_user('Editor', lambda: _svc().execute_action(
            'virtual_tool_call', 'system_internal',
            {'tool_name': 'add_schedule', 'arguments': {},
             'params': _sched(target_id=self.output_id)}))
        self.assertEqual(r.get('reason_code'), 'group_scope', r)
        self.assertEqual(self._jobs(), before)

    def test_judge_and_executor_share_one_extractor(self):
        from aot.ai.services.ai_action_service import AIActionService
        from aot.tools.tool_call_args import extract_tool_call
        shapes = (
            {'tool_name': 'add_schedule', 'arguments': {}, 'params': {'a': 1}},
            {'tool_name': 'add_schedule', 'arguments': {'arguments': {'a': 1}}},
            {'tool_name': 'add_schedule', 'a': 1, 'page_context': {'x': 2}},
        )
        for p in shapes:
            with self.subTest(shape=sorted(p)):
                self.assertEqual(
                    AIActionService._action_tool_and_args(
                        'virtual_tool_call', 'system_internal', p),
                    extract_tool_call(p, 'system_internal'))
                self.assertEqual(extract_tool_call(p)[1], {'a': 1})


# ---------------------------------------------------------------------------
# ④ 일정 id·시퀀스 단계 id(자식 행)
# ---------------------------------------------------------------------------

class TestChildRows(_WS):

    def test_schedule_by_job_id(self):
        self._scope_to_other_group()
        meta = self._make_job()
        jid = str(meta.id)
        for tool, args in (('delete_schedule', {'job_id': jid}),
                           ('edit_schedule', {'job_id': jid, 'time': '11:00'})):
            with self.subTest(tool=tool):
                self.assertEqual(self._ext(tool, args),
                                 ('refused', 'group_scope', False))
                self.assertIsNotNone(gate._approval_scope_denial(
                    tool, args, user=self._user('Editor')))
        S = _svc_tools()
        for label, fn in (('delete', lambda: S.delete_schedule_tool(job_id=jid)),
                          ('edit', lambda: S.edit_schedule_tool(job_id=jid,
                                                                time='11:00'))):
            with self.subTest(handler=label):
                self.assertEqual(self._direct('Editor', fn)[0], 'denied')
        db.session.remove()
        self.assertNotEqual(SchedulerJobMeta.query.get(meta.id).state, 'ARCHIVED')

    def test_sequence_step_by_action_id(self):
        self._scope_to_other_group()
        self.assertEqual(self._ext('modify_sequence_step',
                                   {'action_id': self.action, 'enabled': False}),
                         ('refused', 'group_scope', False))
        outcome, _ = self._direct('Editor', lambda: _svc_tools()
                                  .modify_sequence_step(action_id=self.action,
                                                        enabled=False))
        self.assertEqual(outcome, 'denied')


# ---------------------------------------------------------------------------
# ⑤ 승인 권한은 도구별
# ---------------------------------------------------------------------------

class TestApprovalPermissionPerTool(_WS):

    def _queue(self, tool, args):
        row = MCPConfirmation(unique_id=str(uuid.uuid4()), tool_name=tool,
                              params_json=json.dumps(args), agent_id='user:test',
                              status='pending')
        from datetime import datetime, timedelta
        row.expires_at = datetime.utcnow() + timedelta(minutes=5)
        db.session.add(row)
        db.session.commit()
        return row.unique_id

    def _status(self, cid):
        db.session.remove()
        return MCPConfirmation.query.filter_by(unique_id=cid).first().status

    def test_control_only_cannot_approve_a_plot_write(self):
        cid = self._queue('modify_plot', {'plot_id': str(uuid.uuid4()), 'name': 'x'})
        r = gate.approve(cid, user_id=self.user_uuids['ControlOnly'])
        self.assertEqual(r.get('reason_code'), 'insufficient_role', r)
        self.assertEqual(self._status(cid), 'pending')

    def test_plot_only_can_approve_a_plot_write_but_not_control(self):
        cid = self._queue('modify_plot', {'plot_id': str(uuid.uuid4()), 'name': 'x'})
        self.assertEqual(gate.approve(cid, user_id=self.user_uuids['PlotOnly'])
                         .get('status'), 'success')
        cid2 = self._queue('operate_device', {'device_id': 'x', 'state': 'on'})
        r = gate.approve(cid2, user_id=self.user_uuids['PlotOnly'])
        self.assertEqual(r.get('reason_code'), 'insufficient_role', r)
        self.assertEqual(gate.reject(cid2, user_id=self.user_uuids['PlotOnly'])
                         .get('reason_code'), 'insufficient_role')

    def test_monitor_cannot_decide_anything(self):
        cid = self._queue('modify_plot', {'plot_id': str(uuid.uuid4()), 'name': 'x'})
        r = gate.approve(cid, user_id=self.user_uuids['Monitor'])
        self.assertEqual(r.get('reason_code'), 'insufficient_role')

    def test_respond_to_confirmation_visibility_and_key_role(self):
        self.assertNotIn('respond_to_confirmation', te._hidden_tools(self._role('PlotOnly')))
        self.assertIn('respond_to_confirmation', te._hidden_tools(self._role('Monitor')))
        self.assertIn('respond_to_confirmation',
                      te._hidden_tools(self._role('Editor', readonly=True)))
        cid = self._queue('modify_plot', {'plot_id': str(uuid.uuid4()), 'name': 'x'})
        r = te._respond_to_confirmation({'decision': 'approve', 'confirmation_id': cid},
                                        'user:test', self._role('ControlOnly'))
        self.assertEqual(r.get('reason_code'), 'insufficient_role', r)
        r = te._respond_to_confirmation({'decision': 'approve', 'confirmation_id': cid},
                                        'user:test', self._role('PlotOnly'))
        self.assertEqual(r.get('status'), 'success', r)

    def test_list_marks_what_the_viewer_may_decide(self):
        self._queue('modify_plot', {'plot_id': str(uuid.uuid4()), 'name': 'x'})
        self._queue('operate_device', {'device_id': 'x', 'state': 'on'})
        role = Role.query.filter(Role.name == _PREFIX + 'PlotOnly').first()
        marks = {p['tool_name']: p['can_decide'] for p in gate.list_pending(viewer=role)}
        self.assertEqual(marks, {'modify_plot': True, 'operate_device': False})
        self.assertNotIn('can_decide', gate.list_pending()[0])

    def test_approved_execution_is_judged_by_the_approver_at_write_time(self):
        """승인 단계 짐작을 지나도 실행 시점에 승인자로 다시 묻는다."""
        self._scope_to_other_group()
        cid = self._queue('activate_function', {'function_id': _PREFIX + 'Cond'})
        row = MCPConfirmation.query.filter_by(unique_id=cid).first()
        row.status = 'approved'
        row.user_id = self.user_uuids['Editor']
        db.session.commit()
        with self.app.test_request_context():
            status, result = gate.execute_approved(cid)
        self.assertEqual(status, 'refused', result)
        self.assertEqual(result.get('reason_code'), 'group_scope_denied')
        self.assertFalse(self._cond_active())
        # 요청이 틀린 것이 아니라 이 승인자에게 권한이 없다 — 대기로 되돌려
        # 권한 있는 다른 사람이 결정할 수 있게 한다(승인자는 지운다).
        db.session.remove()
        row = MCPConfirmation.query.filter_by(unique_id=cid).first()
        self.assertEqual((row.status, row.user_id), ('pending', None))
        self.assertIn(cid, [p['confirmation_id'] for p in gate.list_pending()])
        self.assertEqual(gate.approve(cid, user_id=self.user_uuids['Admin'])
                         .get('status'), 'success')
        with self.app.test_request_context():
            status, _ = gate.execute_approved(cid)
        self.assertEqual(status, 'executed')
        self.assertTrue(self._cond_active())


# ---------------------------------------------------------------------------
# ⑥ 지도 편집은 edit_settings
# ---------------------------------------------------------------------------

class TestMapEditPermission(_WS):

    def test_control_only_cannot_edit_the_map(self):
        for tool, args in (('delete_geo_shape', {'shape_id': self.shape}),
                           ('set_device_location', {'device_id': self.output_id,
                                                    'lat': 1, 'lng': 2})):
            with self.subTest(tool=tool):
                self.assertEqual(self._ext(tool, args, who='ControlOnly'),
                                 ('refused', 'insufficient_role', False))
                self.assertIn(tool, te._hidden_tools(self._role('ControlOnly')))
                self.assertNotIn(tool, te._hidden_tools(self._role('Editor')))

    def test_in_app_requires_edit_settings(self):
        handlers, patch = self._fake_handlers(('delete_geo_shape',))
        with patch:
            r = self._as_user('ControlOnly', lambda: _svc().execute_action(
                'virtual_tool_call', 'system_internal',
                self._vparams('delete_geo_shape', {'shape_id': self.shape})))
        self.assertEqual(r.get('reason_code'), 'insufficient_role', r)
        self.assertFalse(handlers['delete_geo_shape'].called)

    def test_map_edits_enforce_on_the_linked_device(self):
        self._scope_to_other_group()
        S = _svc_tools()
        for label, fn in (
                ('delete_geo_shape', lambda: S.delete_geo_shape(shape_id=self.shape)),
                ('set_device_location', lambda: S.set_device_location(
                    device_id=self.output_id, lat=1, lng=2))):
            with self.subTest(handler=label):
                self.assertEqual(self._direct('Editor', fn)[0], 'denied')
        db.session.remove()
        self.assertIsNotNone(GeoShape.query.filter_by(unique_id=self.shape).first())


# ---------------------------------------------------------------------------
# 쓰기 시점 강제 — 처리기별
# ---------------------------------------------------------------------------

class TestHandlersEnforceAtWriteTime(_WS):
    """앞 판정을 건너뛰고 처리기를 부른다 — 처리기 스스로 막아야 한다."""

    def _cases(self):
        S = _svc_tools()
        return (
            ('add_schedule id', lambda: S.add_schedule_tool(**_sched(target_id=self.output_id))),
            ('add_schedule name', lambda: S.add_schedule_tool(**_sched(target_name=V))),
            ('schedule_device_control name', lambda: S.schedule_device_control_tool(
                device_id=V, state='on', delay_seconds=60)),
            ('operate_device name', lambda: S.operate_device_tool(device_id=V, state='on')),
            ('create_note target_id', lambda: S.create_note(
                note='ws', target_id=self.output_id)),
            ('create_sequence_function', lambda: S.create_sequence_function(
                name=_PREFIX + 'NewSeq', device_ids=[self.output_id])),
            ('modify_output', lambda: S.modify_output(output_id=self.output_id, name='x')),
            ('delete_output', lambda: S.delete_output(output_id=self.output_id)),
            ('modify_input', lambda: S.modify_input(input_id=self.inp, name='x')),
            ('delete_input', lambda: S.delete_input(input_id=self.inp)),
            ('rebind_device', lambda: S.rebind_device(
                old_device_id=self.output_id, new_device_id=self.inp)),
            ('modify_tab', lambda: S.modify_tab(tab_id=self._tab, name='x')),
            ('delete_tab', lambda: S.delete_tab(tab_id=self._tab)),
        )

    def test_out_of_scope_targets_are_refused(self):
        self._scope_to_other_group()
        for label, fn in self._cases():
            with self.subTest(handler=label):
                self.assertEqual(self._direct('Editor', fn)[0], 'denied')
        db.session.remove()
        self.assertEqual(self._jobs(), 0)
        self.assertIsNone(Trigger.query.filter(
            Trigger.name == _PREFIX + 'NewSeq').first())

    def test_widgets_follow_their_dashboard(self):
        self._scope_to_other_group()
        self._scope_board_to_other_group()
        S = _svc_tools()
        for label, fn in (
                ('create_widget', lambda: S.create_widget(tab_id=self.dash,
                                                          widget_type='indicator')),
                ('modify_widget', lambda: S.modify_widget(widget_id=self.widget, name='x')),
                ('delete_widget', lambda: S.delete_widget(widget_id=self.widget))):
            with self.subTest(handler=label):
                self.assertEqual(self._direct('Editor', fn)[0], 'denied')

    def test_admin_and_in_group_are_not_blocked(self):
        self._scope_to_other_group()
        S = _svc_tools()
        self.assertEqual(self._direct('Admin', lambda: S.add_schedule_tool(
            **_sched(target_id=self.output_id)))[0], 'ran')
        self._grant_group_to('Editor')
        self.assertEqual(self._direct('Editor', lambda: S.add_schedule_tool(
            **_sched(target_name=V)))[0], 'ran')

    def test_nothing_is_enforced_without_a_bound_principal(self):
        """사람이 없는 호출(백그라운드)은 지금처럼 면제다."""
        self._scope_to_other_group()
        with self.app.test_request_context():
            self.assertIsNone(write_scope.current())
            r = _svc_tools().add_schedule_tool(**_sched(target_id=self.output_id))
        self.assertTrue(r.get('job_id'), r)

    def test_denial_that_a_handler_swallows_is_still_reported(self):
        """처리기가 `except Exception` 으로 삼켜도 거부는 BaseException 이라
        빠져나가고, 실행층이 거부로 돌려준다."""
        self.assertFalse(issubclass(write_scope.WriteScopeDenied, Exception))
        self._scope_to_other_group()

        def _swallowing_handler(**kw):
            try:
                write_scope.enforce(self.output_id)
            except Exception:
                pass
            return {'status': 'success'}

        with mock.patch('aot.tools.tool_registry.build_tool_map',
                        return_value={'add_schedule': _swallowing_handler}):
            with mock.patch.object(te, '_scope_refusal', return_value=None):
                body = self._call('add_schedule', _sched(target_id=self.output_id),
                                  self._role('Editor'),
                                  scope_user_uuid=self.user_uuids['Editor'])
        self.assertEqual((body.get('call_state'), body.get('reason_code')),
                         ('refused', 'group_scope'), body)

    def test_worker_threads_carry_the_principal(self):
        from concurrent.futures import ThreadPoolExecutor
        from aot.ai import ai_request_context as ctx
        seen = []
        with write_scope.acting_as(self.user_uuids['Editor']):
            fn = ctx.bind_worker(lambda: seen.append(write_scope.current()))
            with ThreadPoolExecutor(max_workers=1) as pool:
                pool.submit(fn).result()
        self.assertIsNotNone(seen[0])
        self.assertEqual(seen[0].user_uuid, self.user_uuids['Editor'])
        self.assertIsNone(write_scope.current())


# ---------------------------------------------------------------------------
# 과잉 차단이 없는지 — 검토자가 본 정상 흐름
# ---------------------------------------------------------------------------

class TestAuthorizedFlowsUnchanged(_WS):

    def test_in_group_flows(self):
        self._scope_to_other_group()
        self._grant_group_to('Editor')
        before = self._jobs()
        body = self._call('add_schedule', _sched(target_id=self.output_id),
                          self._role('Editor'), scope_user_uuid=self.user_uuids['Editor'])
        self.assertEqual(body.get('call_state'), 'executed', body)
        body = self._call('add_schedule', _sched(target_name=V),
                          self._role('Editor'), scope_user_uuid=self.user_uuids['Editor'])
        self.assertEqual(body.get('call_state'), 'executed', body)
        self.assertEqual(self._jobs(), before + 2)
        for tool, args in (
                ('modify_function_options',
                 {'function_id': self.cond,
                  'params': {'measurement': self.output_id + ',' + str(uuid.uuid4())}}),
                ('create_note', self._note_args(note='rec-write x ' + self.output_id,
                                                target_id=self.output_id)),
                ('modify_sequence_schedule', {'function_id': _PREFIX + 'Seq',
                                              'start': '05:00'})):
            with self.subTest(tool=tool):
                self.assertEqual(self._ext(tool, args)[0], 'executed')

    def test_plot_writes_by_id_are_not_scope_refused(self):
        self._scope_to_other_group()
        for who in ('Editor', 'PlotOnly'):
            with self.subTest(who=who):
                state, code, _ = self._ext('modify_plot', {'plot_id': str(uuid.uuid4()),
                                                           'name': 'x'}, who=who)
                self.assertEqual(state, 'pending_approval', code)
        self.assertEqual(self._ext('create_program', {'name': 'x'}, who='PlotOnly')[0],
                         'executed')

    def test_background_in_app_is_exempt(self):
        self._scope_to_other_group()
        res = self._in_bare_worker('virtual_tool_call',
                                   self._vparams('add_schedule',
                                                 _sched(target_id=self.output_id)))
        self.assertEqual(res.get('status'), 'success', res)


# ---------------------------------------------------------------------------
# 레지스트리의 쓰기 도구 전부가 분류됐는가
# ---------------------------------------------------------------------------

#: 처리기(또는 그것이 부르는 공용 리졸버)가 `write_scope.enforce` 를 지나는 도구와
#: 그 자리를 알리는 이름. 이름은 처리기 소스에 있어야 하고, 그 이름의 리졸버
#: 소스에는 강제가 있어야 한다(`_ENFORCING_RESOLVERS`).
_ENFORCED = {
    'activate_function': '_set_function_activation',
    'deactivate_function': '_set_function_activation',
    'add_schedule': '_target_by_id',
    'add_schedule_batch': 'validate_schedule_batch',
    'edit_schedule': '_resolve_schedule_job',
    'delete_schedule': '_resolve_schedule_job',
    'schedule_device_control': 'resolve_output',
    'operate_device': 'resolve_output',
    'configure_sequence_day': 'write_scope.enforce',
    'modify_sequence_schedule': 'write_scope.enforce',
    'modify_sequence_step': 'write_scope.enforce',
    'modify_function_options': 'write_scope.enforce',
    'delete_function': 'write_scope.enforce',
    'create_sequence_function': 'write_scope.enforce',
    'modify_input': 'write_scope.enforce',
    'delete_input': 'write_scope.enforce',
    'modify_output': 'write_scope.enforce',
    'delete_output': 'write_scope.enforce',
    'create_widget': 'write_scope.enforce',
    'modify_widget': 'write_scope.enforce',
    'delete_widget': 'write_scope.enforce',
    'modify_tab': 'write_scope.enforce',
    'delete_tab': 'write_scope.enforce',
    'rebind_device': 'write_scope.enforce',
    'set_device_location': 'write_scope.enforce',
    'delete_geo_shape': 'write_scope.enforce',
    'create_note': 'write_scope.enforce',
    # 새 행이지만 인자 속 장치·지도·시설에 묶인다 — 그 값으로 묻는다.
    'create_function': 'write_scope.enforce',
    'create_plot': 'write_scope.enforce',
}

#: 공용 리졸버 → 그 소스에 있어야 할 강제 표지.
_ENFORCING_RESOLVERS = {
    '_set_function_activation': 'write_scope.enforce(mod)',
    '_target_by_id': 'write_scope.enforce(found[0])',
    '_resolve_note_target': 'write_scope.enforce(result[0])',
    '_resolve_schedule_job': 'write_scope.enforce(meta)',
    'validate_schedule_batch': '_target_by_id',
}

#: 스코프 대상이 아닌 쓰기 — 이유와 함께. 여기 있는 도구는 **그룹 스코프가 붙는
#: 자원(장치·탭·대시보드·위젯·지도·시설)을 고치지 않는다**. 인자에 그런 자원의
#: uuid 를 실으면 앞 판정이 여전히 거부한다.
_UNSCOPED = {
    # 새로 만드는 행 — 탭·대시보드 없이 생긴다(웹 추가와 같다).
    'create_input': 'new row, no tab',
    'create_output': 'new row, no tab',
    'create_tab': 'new tab',
    'create_ai_agent': 'AI settings, not a scoped resource',
    'modify_ai_agent': 'AI settings, not a scoped resource',
    'delete_ai_agent': 'AI settings, not a scoped resource',
    # GIS 입력(GeoLayer) — 전역 레이어, 스코프 종류가 아니다.
    'create_gis_input': 'global layer', 'modify_gis_input': 'global layer',
    'activate_gis_input': 'global layer', 'delete_gis_input': 'global layer',
    # 기록 — 대상 없는 기록(노트 대상은 create_note 가 강제한다).
    'knowledge_shelve': 'knowledge record', 'note': 'in-app log record',
    'create_notice': 'notice board', 'modify_notice': 'notice board',
    'delete_notice': 'notice board', 'archive_note': 'note archive',
    'restore_note_from_archive': 'note archive', 'delete_archive': 'note archive',
    'set_document_tier': 'library document', 'configure_library_source': 'library',
    # 작기 운영 — 구획·프로그램·단계는 웹에서도 그룹 스코프 밖이다.
    'add_plot_stage': 'plot', 'apply_plot_resources': 'plot',
    'apply_plot_split': 'plot', 'confirm_plot_stage': 'plot', 'copy_plot': 'plot',
    'create_plot_journal': 'plot', 'create_program': 'plot',
    'delete_plot': 'plot', 'delete_program': 'plot', 'end_plot': 'plot',
    'modify_plot': 'plot', 'modify_program': 'plot', 'remove_plot_stage': 'plot',
    'reschedule_plot_stage': 'plot', 'save_plot_schedule_as_program': 'plot',
    'set_plot_stage_guidance': 'plot', 'undo_plot_stage': 'plot',
    # 실행층 자체가 다룬다.
    'respond_to_confirmation': 'approval queue — per-tool role in gate._decide',
    'set_output_state': 'native engine — enforce(output) in aot_native_tool_engine',
}


class TestEveryWriteToolIsCovered(_WS):

    def test_every_write_tool_is_classified(self):
        writes = set(gate.write_tools())
        classified = set(_ENFORCED) | set(_UNSCOPED)
        self.assertEqual(sorted(writes - classified), [],
                         'new write tool: route it through write_scope.enforce '
                         '(or a resolver that does) and add it to _ENFORCED, or '
                         'say why it is not scoped in _UNSCOPED')
        self.assertEqual(sorted(classified - writes), [], 'stale classification')
        self.assertFalse(set(_ENFORCED) & set(_UNSCOPED))

    def test_enforced_handlers_reach_the_enforcement_point(self):
        from aot.tools.tool_registry import build_tool_map
        S = _svc_tools()
        tool_map = build_tool_map()
        for tool, marker in sorted(_ENFORCED.items()):
            with self.subTest(tool=tool):
                src = inspect.getsource(tool_map[tool])
                self.assertIn(marker, src)
        for name, marker in _ENFORCING_RESOLVERS.items():
            with self.subTest(resolver=name):
                self.assertIn(marker, inspect.getsource(getattr(S, name)))
        from aot.services.resolvers import device_resolver
        self.assertIn('write_scope.enforce(row)',
                      inspect.getsource(device_resolver._found))
        from aot.tools import aot_native_tool_engine
        self.assertIn('write_scope.enforce(output)',
                      inspect.getsource(aot_native_tool_engine))

    def _behaviour_cases(self):
        """도구 → 처리기 인자(그룹 밖 대상). `_ENFORCED` 와 키가 같아야 한다."""
        from aot.databases.models import GeoMap
        from aot.databases.models.user_group import RESOURCE_GEO_MAP
        gmap = str(uuid.uuid4())
        db.session.add(GeoMap(unique_id=gmap, name=_PREFIX + 'Map'))
        group = UserGroup.query.filter(UserGroup.name == _PREFIX + 'Group').first()
        db.session.add(GroupGrant(group_uuid=group.unique_id,
                                  resource_type=RESOURCE_GEO_MAP,
                                  resource_uuid=gmap, level=LEVEL_OPERATE))
        db.session.commit()
        self.addCleanup(lambda: (GeoMap.query.filter_by(unique_id=gmap).delete(),
                                 db.session.commit()))
        jid = str(self._make_job().id)
        seq = _PREFIX + 'Seq'
        return {
            'activate_function': {'function_id': _PREFIX + 'Cond'},
            'deactivate_function': {'function_id': self.cond},
            'add_schedule': _sched(target_id=self.output_id),
            'add_schedule_batch': {'date': '2030-01-06', 'content': 'ws',
                                   'entries': [{'target_name': V, 'time': '10:00'}]},
            'edit_schedule': {'job_id': jid, 'time': '11:00'},
            'delete_schedule': {'job_id': jid},
            'schedule_device_control': {'device_id': V, 'state': 'on',
                                        'delay_seconds': 60},
            'operate_device': {'device_id': V, 'state': 'on'},
            'configure_sequence_day': {'function_id': seq, 'day': 0,
                                       'slots': [{'devices': [V], 'minutes': 1}]},
            'modify_sequence_schedule': {'function_id': seq, 'start': '05:00'},
            'modify_sequence_step': {'action_id': self.action, 'enabled': False},
            'modify_function_options': {'function_id': self.cond, 'params': {'x': 1}},
            'delete_function': {'function_id': self.cond},
            'create_sequence_function': {'name': _PREFIX + 'NewSeq',
                                         'device_ids': [self.output_id]},
            'modify_input': {'input_id': self.inp, 'name': 'x'},
            'delete_input': {'input_id': self.inp},
            'modify_output': {'output_id': self.output_id, 'name': 'x'},
            'delete_output': {'output_id': self.output_id},
            'create_widget': {'tab_id': self.dash, 'widget_type': 'indicator'},
            'modify_widget': {'widget_id': self.widget, 'name': 'x'},
            'delete_widget': {'widget_id': self.widget},
            'modify_tab': {'tab_id': self._tab, 'name': 'x'},
            'delete_tab': {'tab_id': self._tab},
            'rebind_device': {'old_device_id': self.output_id,
                              'new_device_id': self.inp},
            'set_device_location': {'device_id': self.output_id, 'lat': 1, 'lng': 2},
            'delete_geo_shape': {'shape_id': self.shape},
            'create_note': {'note': 'ws', 'target_id': self.output_id},
            'create_function': {'function_type': 'conditional_conditional',
                                'params': {'measurement': self.output_id + ','
                                           + str(uuid.uuid4())}},
            'create_plot': {'map_id': gmap, 'geometry': {
                'type': 'Polygon',
                'coordinates': [[[0, 0], [0, 1], [1, 1], [1, 0], [0, 0]]]}},
        }

    def test_every_enforced_tool_refuses_an_out_of_scope_target(self):
        """분류만이 아니라 **행동**으로 — `_ENFORCED` 의 도구 전부를 앞 판정
        없이 처리기로 곧바로 부르고(Editor 로 묶어) 그룹 밖 대상이면 거부되는지
        본다. `_ENFORCED` 에 도구를 넣으면 여기에도 사례가 있어야 통과한다."""
        from aot.tools.tool_registry import build_tool_map
        self._scope_to_other_group()
        self._scope_board_to_other_group()
        cases = self._behaviour_cases()
        self.assertEqual(sorted(cases), sorted(_ENFORCED))
        tool_map = build_tool_map()
        for tool, args in sorted(cases.items()):
            with self.subTest(tool=tool):
                outcome, got = self._direct(
                    'Editor', lambda: tool_map[tool](**dict(args)))
                self.assertEqual(outcome, 'denied', got)
        # 거부된 만들기는 아무것도 남기지 않는다.
        db.session.remove()
        self.assertIsNone(Trigger.query.filter(
            Trigger.name == _PREFIX + 'NewSeq').first())

    def test_execution_layers_bind_the_principal(self):
        from aot.ai.services.ai_action_service import AIActionService
        self.assertIn('write_scope.acting_as(', inspect.getsource(te._run_gated_tool))
        self.assertIn('write_scope.acting_as(', inspect.getsource(gate.execute_approved))
        self.assertIn('write_scope.bind(', inspect.getsource(AIActionService.execute_action))
        self.assertIn('write_scope.also_acting_as(', inspect.getsource(te._run_gated_tool))
        from aot.ai.services import ai_scheduler_service as sched
        self.assertIn('_ws.acting_as(',
                      inspect.getsource(sched._execute_scheduled_action))
        from aot.aot_flask import routes_scheduler
        for view in (routes_scheduler.api_update_job, routes_scheduler.api_delete_job,
                     routes_scheduler.api_reject_job):
            self.assertIn('write_scope.acting_as_current_user(',
                          inspect.getsource(view))
