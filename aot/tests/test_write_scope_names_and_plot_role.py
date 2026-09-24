# coding=utf-8
"""쓰기 판정의 후속 구멍 — 이름 별칭·중첩 인자·uuid 모양·작기 운영 권한.

2026-09-23 검토 프로브에서 재현된 것을 고정한다.

  1. **옛 이름 별칭.** `add_schedule` 처리기는 `target_name` 이 없으면
     `location`·`zone_name`·`place`·`entity_name` 을 이름으로 읽는데, 스코프
     판정은 `create_note` 의 별칭만 알았다. 이제 처리기와 판정이 같은 목록
     (`aot.tools.target_names`)을 읽고, 모든 쓰기 도구에 적용된다.
  2. **중첩 인자.** 옛 action_type `add_schedule` 은 인자를
     `{'target_id': …, 'params': {...}}` 로 싸서 보낸다. 판정은 맨 위와 목록
     항목만 풀어, 한 겹 싸는 것만으로 이름 대상이 빠져나갔다.
  3. **uuid 모양.** 판정은 정확히 36자인 문자열만 uuid 로 봤는데 처리기는
     `strip()` 해서 쓴다 — `' ' + uuid` 가 판정을 빠져나갔다.
  4. **작기 운영 권한.** 웹은 구획·단계·자원·작기 프로그램에 `edit_plots`
     (설정 편집이 함의)를 요구한다. AI 경로는 `edit_controllers` 를 요구해
     작기만 맡은 사람은 막히고 제어만 가진 사람은 열렸다.
  5. `abstract_plan`(로그 표지뿐)은 Monitor 에게 막히지 않는다.
"""
from unittest import mock

from aot.aot_flask.extensions import db
from aot.databases.models import Role, SchedulerJobMeta, User
from aot.tests.test_ai_requester_write_guard import _Base, _svc
from aot.tests.test_mcp_record_write_guard import _PREFIX
from aot.tools import mcp_auth
from aot.tools import mcp_safety_gate as gate
from aot.tools import tool_execution as te
from aot.tools import tool_registry as R
from aot.tools.target_names import TARGET_NAME_ALIASES

_VALVE = _PREFIX + 'Valve'


def _sched_args(**extra):
    args = {'date': '2030-01-02', 'time': '09:00', 'content': 'scope-followup'}
    args.update(extra)
    return args


class _SchedBase(_Base):

    def setUp(self):
        super().setUp()
        # 작기 운영만 맡은 역할 — 웹 구획 화면은 열리고 제어·설정은 안 된다.
        role = Role(name=_PREFIX + 'PlotOnly', edit_plots=True,
                    edit_settings=False, edit_controllers=False,
                    edit_users=False, use_ai_chat=True)
        db.session.add(role)
        db.session.commit()
        row = User(name=(_PREFIX + 'PlotOnly').lower(), role_id=role.id,
                   is_enabled=True)
        db.session.add(row)
        db.session.commit()
        self.user_uuids['PlotOnly'] = row.unique_id

    def tearDown(self):
        db.session.rollback()
        SchedulerJobMeta.query.filter(
            SchedulerJobMeta.target_id == self.output_id).delete(
                synchronize_session=False)
        db.session.commit()
        super().tearDown()

    def _sched_count(self):
        db.session.remove()
        return SchedulerJobMeta.query.filter(
            SchedulerJobMeta.target_id == self.output_id).count()


# ---------------------------------------------------------------------------
# 1. 옛 이름 별칭 — 처리기와 판정이 같은 목록
# ---------------------------------------------------------------------------

class TestNameAliases(_SchedBase):

    def test_handlers_and_scope_share_one_alias_list(self):
        from aot.tools.target_names import TARGET_NAME_KEYS
        self.assertEqual(TARGET_NAME_KEYS[0], 'target_name')
        self.assertEqual(set(TARGET_NAME_KEYS[1:]), set(TARGET_NAME_ALIASES))
        self.assertTrue({'location', 'zone_name', 'place', 'entity_name'}
                        <= set(TARGET_NAME_ALIASES))

    def test_external_add_schedule_by_alias_is_refused(self):
        self._scope_to_other_group()
        for key in TARGET_NAME_ALIASES:
            with self.subTest(alias=key):
                body = self._call('add_schedule', _sched_args(**{key: _VALVE}),
                                  self._role('Editor'),
                                  scope_user_uuid=self.user_uuids['Editor'])
                self.assertEqual(body.get('reason_code'), 'group_scope', body)
        self.assertEqual(self._sched_count(), 0)

    def test_external_alias_in_scope_still_attaches(self):
        """대조군 — 스코프가 없으면 별칭 그대로 그 장치에 붙는다."""
        body = self._call('add_schedule', _sched_args(location=_VALVE),
                          self._role('Editor'),
                          scope_user_uuid=self.user_uuids['Editor'])
        self.assertNotEqual(body.get('reason_code'), 'group_scope', body)
        self.assertEqual(self._sched_count(), 1)

    def test_in_app_add_schedule_by_alias_is_refused(self):
        self._scope_to_other_group()
        res = self._as_user('Editor', lambda: _svc().execute_action(
            'virtual_tool_call', 'system_internal',
            self._vparams('add_schedule', _sched_args(location=_VALVE))))
        self.assertEqual(res.get('reason_code'), 'group_scope', res)
        self.assertEqual(self._sched_count(), 0)

    def test_external_create_note_by_alias_is_refused(self):
        self._scope_to_other_group()
        body = self._call('create_note', self._note_args(place=_VALVE),
                          self._role('Editor'),
                          scope_user_uuid=self.user_uuids['Editor'])
        self.assertEqual(body.get('reason_code'), 'group_scope', body)
        self.assertEqual(self._notes(), 0)

    def test_external_device_name_in_device_id_is_refused(self):
        """장치 id 자리의 이름 — 처리기가 resolve_output 으로 푼다."""
        self._scope_to_other_group()
        with mock.patch.object(te, '_dispatch_virtual_tool') as run:
            body = self._call('schedule_device_control',
                              {'device_id': _VALVE, 'state': 'on',
                               'delay_seconds': 60},
                              self._role('Editor'),
                              scope_user_uuid=self.user_uuids['Editor'])
            run.assert_not_called()
        self.assertEqual(body.get('reason_code'), 'group_scope', body)


# ---------------------------------------------------------------------------
# 2. 중첩 인자 — 옛 action_type 의 한 겹
# ---------------------------------------------------------------------------

class TestNestedArguments(_SchedBase):

    def test_legacy_add_schedule_by_name_is_refused(self):
        self._scope_to_other_group()
        res = self._as_user('Editor', lambda: _svc().execute_action(
            'add_schedule', None, _sched_args(target_name=_VALVE)))
        self.assertEqual(res.get('reason_code'), 'group_scope', res)
        self.assertEqual(self._sched_count(), 0)

    def test_legacy_add_schedule_by_alias_is_refused(self):
        self._scope_to_other_group()
        res = self._as_user('Editor', lambda: _svc().execute_action(
            'add_schedule', None, _sched_args(zone_name=_VALVE)))
        self.assertEqual(res.get('reason_code'), 'group_scope', res)
        self.assertEqual(self._sched_count(), 0)

    def test_scope_arguments_resolves_nested_dicts(self):
        out = te.scope_arguments('add_schedule', {
            'target_id': None, 'params': {'wrap': {'target_name': _VALVE}}})
        self.assertIn(self.output_id, out.get(te.SCOPE_RESOLVED_KEY, []))


# ---------------------------------------------------------------------------
# 3. uuid 모양 — 공백·대소문자·붙인 값
# ---------------------------------------------------------------------------

class TestUuidShapes(_SchedBase):

    def _variants(self):
        u = self.output_id
        return (' ' + u, u + ' ', '\t' + u + '\n', u.upper(),
                u + ',' + '0' * 8 + '-0000-0000-0000-' + '0' * 12)

    def test_scan_finds_padded_and_joined_uuids(self):
        from aot.aot_flask.access.scope import _uuid_values
        for value in self._variants():
            with self.subTest(value=repr(value[:4])):
                self.assertIn(self.output_id, list(_uuid_values({'x': value})))

    def test_external_padded_target_id_is_refused(self):
        self._scope_to_other_group()
        for value in self._variants()[:4]:
            with self.subTest(value=repr(value[:4])):
                body = self._call('add_schedule', _sched_args(target_id=value),
                                  self._role('Editor'),
                                  scope_user_uuid=self.user_uuids['Editor'])
                self.assertEqual(body.get('reason_code'), 'group_scope', body)
        self.assertEqual(self._sched_count(), 0)

    def test_in_app_batch_item_with_whitespace_is_refused(self):
        self._scope_to_other_group()
        res = self._as_user('Editor', lambda: _svc().execute_action(
            'virtual_tool_call', 'system_internal', self._vparams(
                'add_schedule_batch', {
                    'date': '2030-01-05', 'content': 'scope-followup',
                    'entries': [{'target_id': ' ' + self.output_id,
                                 'time': '09:00'}]})))
        self.assertEqual(res.get('reason_code'), 'group_scope', res)
        self.assertEqual(self._sched_count(), 0)

    def test_external_batch_item_with_whitespace_is_refused(self):
        self._scope_to_other_group()
        body = self._call('add_schedule_batch', {
            'date': '2030-01-05', 'content': 'scope-followup',
            'entries': [{'target_id': self.output_id + ' ', 'time': '09:00'}]},
            self._role('Editor'), scope_user_uuid=self.user_uuids['Editor'])
        self.assertEqual(body.get('reason_code'), 'group_scope', body)
        self.assertEqual(self._sched_count(), 0)


# ---------------------------------------------------------------------------
# 4. 작기 운영 권한 — 웹과 같은 edit_plots
# ---------------------------------------------------------------------------

#: 이 목록이 바뀌면 새 space 쓰기 도구가 들어온 것이다 — 작기 운영인지 지도
#: 편집인지(`tool_registry._SPACE_NON_PLOT_WRITES`) 정하고 여기를 고칠 것.
_EXPECTED_PLOT_WRITES = frozenset({
    'add_plot_stage', 'apply_plot_resources', 'apply_plot_split',
    'confirm_plot_stage', 'copy_plot', 'create_plot', 'create_plot_journal',
    'create_program', 'delete_plot', 'delete_program', 'end_plot',
    'modify_plot', 'modify_program', 'remove_plot_stage',
    'reschedule_plot_stage', 'save_plot_schedule_as_program',
    'set_plot_stage_guidance', 'undo_plot_stage'})


class TestPlotWritePermission(_SchedBase):

    def test_plot_write_set_is_derived_from_space_domain(self):
        self.assertEqual(R.plot_write_tools(), _EXPECTED_PLOT_WRITES)
        space_writes = {n for n in R.write_tools() if R.tier_of(n)[0] == 'space'}
        self.assertEqual(space_writes,
                         set(_EXPECTED_PLOT_WRITES) | R._SPACE_NON_PLOT_WRITES)
        self.assertFalse(R.plot_write_tools() & R.record_write_tools())

    def test_required_permission_table(self):
        self.assertEqual(gate.required_write_permission('create_plot'), 'edit_plots')
        self.assertEqual(gate.required_write_permission('modify_program'), 'edit_plots')
        self.assertEqual(gate.required_write_permission('create_note'), 'edit_settings')
        self.assertEqual(gate.required_write_permission('operate_device'),
                         'edit_controllers')
        # 지도 편집은 웹 지도 편집과 같은 설정 편집 권한(2026-09-23 결정).
        self.assertEqual(gate.required_write_permission('delete_geo_shape'),
                         'edit_settings')
        self.assertEqual(gate.required_write_permission('set_device_location'),
                         'edit_settings')

    def test_role_snapshot_mirrors_web_implication(self):
        self.assertTrue(mcp_auth.role_can_edit_plots(self._role('PlotOnly')))
        self.assertTrue(mcp_auth.role_can_edit_plots(self._role('Editor')))
        self.assertFalse(mcp_auth.role_can_edit_plots(self._role('ControlOnly')))
        self.assertFalse(mcp_auth.role_can_edit_plots(self._role('Monitor')))
        self.assertFalse(mcp_auth.role_can_edit_plots(
            self._role('Editor', readonly=True)))

    def test_web_permission_agrees(self):
        import flask_login
        from aot.aot_flask.utils.utils_general import user_has_permission
        for name, expect in (('PlotOnly', True), ('Editor', True),
                             ('ControlOnly', False), ('Monitor', False)):
            with self.subTest(role=name), self.app.test_request_context():
                flask_login.login_user(self._user(name))
                self.assertEqual(user_has_permission('edit_plots', silent=True),
                                 expect)

    def test_external_plot_write_follows_edit_plots(self):
        for name, allowed in (('PlotOnly', True), ('Editor', True),
                              ('ControlOnly', False), ('Monitor', False)):
            with self.subTest(role=name), \
                    mock.patch.object(te, '_dispatch_virtual_tool',
                                      return_value={'status': 'success'}) as run:
                # create_program 은 승인 면제라 통과하면 바로 실행된다.
                body = self._call('create_program', {'name': _PREFIX + 'Prog'},
                                  self._role(name),
                                  scope_user_uuid=self.user_uuids[name])
                if allowed:
                    self.assertNotEqual(body.get('reason_code'),
                                        'insufficient_role', body)
                    self.assertTrue(run.called, body)
                else:
                    self.assertEqual(body.get('reason_code'),
                                     'insufficient_role', body)
                    run.assert_not_called()

    def test_external_approval_plot_write_reaches_approval_queue(self):
        with mock.patch.object(te, '_dispatch_virtual_tool') as run:
            body = self._call('end_plot', {'plot_id': 'x'},
                              self._role('PlotOnly'),
                              scope_user_uuid=self.user_uuids['PlotOnly'])
            run.assert_not_called()
        self.assertNotEqual(body.get('reason_code'), 'insufficient_role', body)
        self.assertEqual(body.get('status'), 'pending_approval', body)

    def test_plot_only_key_cannot_control(self):
        body = self._call('delete_output', {'output_id': self.output_id},
                          self._role('PlotOnly'),
                          scope_user_uuid=self.user_uuids['PlotOnly'])
        self.assertEqual(body.get('reason_code'), 'insufficient_role', body)

    def test_tool_list_follows_the_same_split(self):
        plot_hidden = te._hidden_tools(self._role('PlotOnly'))
        self.assertFalse(plot_hidden & _EXPECTED_PLOT_WRITES)
        self.assertIn('operate_device', plot_hidden)
        ctrl_hidden = te._hidden_tools(self._role('ControlOnly'))
        self.assertTrue(_EXPECTED_PLOT_WRITES <= ctrl_hidden)
        self.assertNotIn('operate_device', ctrl_hidden)

    def test_in_app_plot_write_follows_edit_plots(self):
        handlers, patch = self._fake_handlers(('create_program',))
        with patch:
            for name, allowed in (('PlotOnly', True), ('ControlOnly', False),
                                  ('Monitor', False)):
                with self.subTest(role=name):
                    res = self._as_user(name, lambda: _svc().execute_action(
                        'virtual_tool_call', 'system_internal',
                        self._vparams('create_program', {'name': 'x'})))
                    if allowed:
                        self.assertNotEqual(res.get('reason_code'),
                                            'insufficient_role', res)
                    else:
                        self.assertEqual(res.get('reason_code'),
                                         'insufficient_role', res)
        self.assertEqual(handlers['create_program'].call_count, 1)

    def test_in_app_worker_plot_write_follows_edit_plots(self):
        handlers, patch = self._fake_handlers(('create_program',))
        with patch:
            ok = self._in_worker('PlotOnly', 'virtual_tool_call',
                                 self._vparams('create_program', {'name': 'x'}))
            no = self._in_worker('ControlOnly', 'virtual_tool_call',
                                 self._vparams('create_program', {'name': 'x'}))
        self.assertNotEqual(ok.get('reason_code'), 'insufficient_role', ok)
        self.assertEqual(no.get('reason_code'), 'insufficient_role', no)

    def test_chat_approval_plot_write_follows_edit_plots(self):
        from aot.ai.services.ai_agent_service import AIAgentService
        params = {'tool_name': 'create_program', 'arguments': {'name': 'x'}}
        for name, allowed in (('PlotOnly', True), ('ControlOnly', False)):
            with self.subTest(role=name):
                denial = self._as_user(name, lambda: AIAgentService._approval_denial(
                    'virtual_tool_call', 'system_internal', dict(params)))
                if allowed:
                    self.assertIsNone(denial)
                else:
                    self.assertIn('edit_plots', denial or '')


# ---------------------------------------------------------------------------
# 5. abstract_plan 은 읽기
# ---------------------------------------------------------------------------

class TestAbstractPlan(_SchedBase):

    def test_monitor_abstract_plan_is_not_refused(self):
        res = self._as_user('Monitor', lambda: _svc().execute_action(
            'abstract_plan', 'x', {'reasoning': 'marker'}))
        self.assertNotEqual(res.get('reason_code'), 'insufficient_role', res)
        self.assertEqual(res.get('status'), 'success', res)
