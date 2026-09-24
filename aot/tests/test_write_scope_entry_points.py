# coding=utf-8
"""사람이 시킨 쓰기가 들어오는 **입구마다** 신원이 묶이는가.

정본 설계: `docs/design/access-scope-groups.md` §6-2a

쓰기 시점 강제(`write_scope.enforce`)는 묶인 사람이 없으면 아무것도 하지
않는다 — 그래서 입구 하나가 신원을 묶지 않으면 그 입구로 들어온 쓰기는 전부
"사람이 없는 호출" 로 면제된다. 2026-09-23 재현된 입구:

  1. **예약 발화.** 사람(Editor)이 만든 `virtual_tool_call` 예약이 그룹 밖 조건
     함수를 고쳤다. 발화 재검사는 겉의 `target_id`(도구 이름)만 봤고, 발화는
     아무도 묶지 않았다. `/api/v1/scheduler/propose` 는 `edit_controllers` 만
     봤고, 승인은 아무것도 보지 않았다.
  2. **인앱 `mcp_tool_call` 의 `use_tool`.** 겉 이름으로 분류해 읽기로 보여
     역할 판정·신원 묶음이 빠졌다 — Monitor 가 `use_tool{create_note}` 로 노트를,
     익명 요청자가 `use_tool{add_schedule}` 로 일정을 만들었다.
  3. **외부 MCP 앞 판정의 예외** 가 쓰기를 통과시켰다(열린 쪽 실패).
  4. **승인 후 재호출** 은 부른 사람만 봤다 — 승인자는 보지 않았다.
  5. **웹 일정 편집·삭제** 라우트가 처리기를 곧바로 부르면서 묶지 않았다.
"""
import json
import uuid
from unittest import mock

import flask_login

from aot.aot_flask.access import scope, write_scope
from aot.aot_flask.extensions import db
from aot.databases.models import (Dashboard, GeoMap, GroupGrant,
                                  MCPConfirmation, SchedulerJobMeta, UserGroup)
from aot.databases.models.function import Conditional
from aot.databases.models.user_group import LEVEL_OPERATE, RESOURCE_GEO_MAP
from aot.tests.test_ai_requester_write_guard import _svc
from aot.tests.test_mcp_record_write_guard import _PREFIX
from aot.tests.test_write_scope_enforcement import _WS, _sched, _svc_tools
from aot.tools import mcp_safety_gate as gate
from aot.tools import tool_execution as te

_MARK = 'ws-entry-test'


def _sched_mod():
    from aot.ai.services import ai_scheduler_service
    return ai_scheduler_service


class _Entry(_WS):

    def setUp(self):
        super().setUp()
        self.addCleanup(self._wipe_jobs)

    def _wipe_jobs(self):
        db.session.rollback()
        SchedulerJobMeta.query.filter(
            SchedulerJobMeta.reasoning.like(_MARK + '%')).delete(
                synchronize_session=False)
        db.session.commit()

    def _mark_params(self, fid=None):
        return {'tool_name': 'modify_function_options',
                'arguments': {'function_id': fid or self.cond,
                              'params': {'ws_mark': 1}}}

    def _written(self):
        db.session.remove()
        row = Conditional.query.filter_by(unique_id=self.cond).first()
        return 'ws_mark' in (row.custom_options or '')

    def _job(self, owner=None, state='PENDING', params=None):
        meta = SchedulerJobMeta(
            action_type='virtual_tool_call', target_id='system_internal',
            params_json=json.dumps(params or self._mark_params()),
            user_id=self._user(owner).id if owner else None, state=state,
            reasoning=_MARK, proposed_by='HUMAN' if owner else 'AI')
        db.session.add(meta)
        db.session.commit()
        return meta.id

    def _fire(self, meta_id):
        S = _sched_mod()
        meta = SchedulerJobMeta.query.get(meta_id)
        with mock.patch.object(S, '_flask_app', self.app):
            res = S._execute_scheduled_action(
                meta.action_type, meta.target_id,
                json.loads(meta.params_json), meta_id=meta_id)
        db.session.remove()
        return res, SchedulerJobMeta.query.get(meta_id)

    def _view(self, who, view, *args, json_body=None, method='POST'):
        """`who` 로 로그인한 요청 안에서 뷰 함수를 곧바로 부른다."""
        self._clear_scope_cache()
        user = self._user(who)
        with self.app.test_request_context(method=method, json=json_body or {}):
            flask_login.login_user(user)
            out = view(*args)
        if isinstance(out, tuple):
            resp, code = out[0], out[1]
        else:
            resp, code = out, out.status_code
        return code, resp.get_json()


# ---------------------------------------------------------------------------
# 1. 예약 — 발화·만들기·승인
# ---------------------------------------------------------------------------

class TestScheduledFiring(_Entry):

    def test_out_of_scope_tool_call_job_is_refused_at_fire(self):
        self._scope_to_other_group()
        res, meta = self._fire(self._job(owner='Editor'))
        self.assertEqual(res.get('call_state'), 'refused', res)
        self.assertFalse(self._written())
        self.assertEqual(meta.state, 'FAILED')
        self.assertIn('NOT EXECUTED', meta.execution_result)

    def test_write_time_binding_refuses_even_without_the_precheck(self):
        """앞 판정(`_scope_denies`)을 건너뛰어도 발화가 책임자로 묶여 있어
        처리기가 실제 대상에서 거부한다."""
        self._scope_to_other_group()
        S = _sched_mod()
        with mock.patch.object(S.AISchedulerService, '_scope_denies',
                               return_value=None):
            res, meta = self._fire(self._job(owner='Editor'))
        self.assertEqual(res.get('reason_code'), 'group_scope', res)
        self.assertFalse(self._written())
        self.assertEqual(meta.state, 'FAILED')

    def test_owner_role_is_checked_at_fire(self):
        res, _meta = self._fire(self._job(owner='Monitor'))
        self.assertEqual(res.get('call_state'), 'refused', res)
        self.assertIn('edit_controllers', res.get('message'))
        self.assertFalse(self._written())

    def test_in_scope_job_fires(self):
        self._scope_to_other_group()
        self._grant_group_to('Editor')
        res, meta = self._fire(self._job(owner='Editor'))
        self.assertEqual(res.get('status'), 'success', res)
        self.assertTrue(self._written())
        self.assertEqual(meta.state, 'COMPLETED')

    def test_system_job_is_unaffected(self):
        """책임자가 없는 시스템 예약(함수·데몬이 만든 것)은 지금처럼 면제다."""
        self._scope_to_other_group()
        res, meta = self._fire(self._job(owner=None))
        self.assertEqual(res.get('status'), 'success', res)
        self.assertTrue(self._written())
        self.assertEqual(meta.state, 'COMPLETED')

    def test_denial_never_escapes_into_the_scheduler_thread(self):
        from aot.ai.services.ai_action_service import AIActionService
        self._scope_to_other_group()
        self._grant_group_to('Editor')
        with mock.patch.object(AIActionService, 'execute_action',
                               side_effect=write_scope.WriteScopeDenied('x')):
            res, meta = self._fire(self._job(owner='Editor'))
        self.assertEqual(res.get('status'), 'error', res)
        self.assertEqual(meta.state, 'FAILED')
        self.assertIsNone(write_scope.current())

    def test_requester_is_restored_after_fire(self):
        from aot.ai import ai_request_context as ctx
        self._fire(self._job(owner='Editor'))
        self.assertIsNone(ctx.get_requester())
        self.assertIsNone(write_scope.current())

    def test_person_driven_schedule_gets_an_owner(self):
        """인앱 AI 가 사람 대신 건 예약(user_id 를 넘기지 않는 처리기)도
        책임자가 채워진다 — 시스템 예약으로 남아 재검사를 빠지지 않게."""
        self._scope_to_other_group()
        self._grant_group_to('Editor')
        before = {m.id for m in SchedulerJobMeta.query.all()}
        with mock.patch.object(_sched_mod(), 'get_scheduler'):
            outcome, got = self._direct('Editor', lambda: _svc_tools()
                                        .schedule_device_control_tool(
                                            device_id=self.output_id, state='on',
                                            delay_seconds=600))
        self.assertEqual(outcome, 'ran', got)
        db.session.remove()
        new = [m for m in SchedulerJobMeta.query.all() if m.id not in before]
        self.assertTrue(new, got)
        self.assertEqual({m.user_id for m in new}, {self._user('Editor').id})


class TestSchedulerRoutes(_Entry):

    def _routes(self):
        from aot.aot_flask import routes_scheduler
        return routes_scheduler

    def _propose_body(self):
        return {'action_type': 'virtual_tool_call', 'target_id': 'system_internal',
                'params': self._mark_params(), 'reasoning': _MARK}

    def _count(self):
        db.session.remove()
        return SchedulerJobMeta.query.filter(
            SchedulerJobMeta.reasoning.like(_MARK + '%')).count()

    def test_propose_checks_the_inner_tool_scope(self):
        self._scope_to_other_group()
        with mock.patch.object(_sched_mod(), 'get_scheduler'):
            code, body = self._view('Editor', self._routes().api_propose_job,
                                    json_body=self._propose_body())
        self.assertEqual(code, 403, body)
        self.assertEqual(self._count(), 0)

    def test_propose_in_scope_is_accepted(self):
        self._scope_to_other_group()
        self._grant_group_to('Editor')
        with mock.patch.object(_sched_mod(), 'get_scheduler'):
            code, body = self._view('Editor', self._routes().api_propose_job,
                                    json_body=self._propose_body())
        self.assertEqual(code, 201, body)
        self.assertEqual(self._count(), 1)

    def test_approve_checks_the_approver(self):
        self._scope_to_other_group()
        jid = self._job(owner=None, state='DRAFT')
        with mock.patch.object(_sched_mod(), 'get_scheduler') as gs:
            code, body = self._view('Editor', self._routes().api_approve_job, jid)
            self.assertEqual(code, 403, body)
            self.assertFalse(gs.return_value.add_job.called)
            db.session.remove()
            meta = SchedulerJobMeta.query.get(jid)
            self.assertEqual((meta.state, meta.user_id), ('DRAFT', None))
            # 권한 있는 다른 사람은 그대로 승인할 수 있고, 책임자가 된다.
            code, body = self._view('Admin', self._routes().api_approve_job, jid)
            self.assertEqual(code, 200, body)
            self.assertTrue(gs.return_value.add_job.called)
        db.session.remove()
        meta = SchedulerJobMeta.query.get(jid)
        self.assertEqual((meta.state, meta.user_id),
                         ('PENDING', self._user('Admin').id))

    def test_approved_ai_draft_fires_as_its_approver(self):
        """AI 초안을 승인한 사람이 책임자가 되고, 발화는 그 사람으로 판정된다
        — 승인 뒤 그룹에서 빠지면 발화가 거부된다."""
        self._scope_to_other_group()
        self._grant_group_to('Editor')
        jid = self._job(owner=None, state='DRAFT')
        with mock.patch.object(_sched_mod(), 'get_scheduler'):
            code, _ = self._view('Editor', self._routes().api_approve_job, jid)
        self.assertEqual(code, 200)
        from aot.databases.models import UserGroupMember
        UserGroupMember.query.delete(synchronize_session=False)
        db.session.commit()
        res, _meta = self._fire(jid)
        self.assertEqual(res.get('call_state'), 'refused', res)
        self.assertFalse(self._written())

    def test_web_edit_and_delete_bind_the_signed_in_user(self):
        self._scope_to_other_group()
        meta = self._make_job()
        R = self._routes()
        code, _ = self._view('Editor', R.api_delete_job, meta.id, method='DELETE')
        self.assertEqual(code, 403)
        code, _ = self._view('Editor', R.api_update_job, meta.id, method='PUT',
                             json_body={'time': '11:00'})
        self.assertEqual(code, 403)
        code, _ = self._view('Editor', R.api_reject_job, meta.id)
        self.assertEqual(code, 403)
        db.session.remove()
        self.assertNotEqual(SchedulerJobMeta.query.get(meta.id).state, 'ARCHIVED')

    def test_legacy_job_api_requires_role_and_scope(self):
        from aot.aot_flask import routes_ai_api as A
        self._scope_to_other_group()
        jid = self._job(owner=None, state='DRAFT')
        code, _ = self._view('Monitor', A.update_scheduler_job, jid, method='PUT',
                             json_body={'params_json': '{}'})
        self.assertEqual(code, 403)
        code, _ = self._view('Editor', A.update_scheduler_job, jid, method='PUT',
                             json_body={'reasoning': _MARK + ' x'})
        self.assertEqual(code, 403)
        code, _ = self._view('Editor', A.delete_scheduler_job, jid, method='DELETE')
        self.assertEqual(code, 403)
        code, body = self._view('Editor', A.batch_process_scheduler_jobs,
                                json_body={'job_ids': [jid], 'action': 'approve'})
        self.assertEqual(body.get('success'), [], body)
        db.session.remove()
        self.assertEqual(SchedulerJobMeta.query.get(jid).state, 'DRAFT')


# ---------------------------------------------------------------------------
# 2. 인앱 mcp_tool_call 의 use_tool
# ---------------------------------------------------------------------------

class TestInAppUseTool(_Entry):

    def _mcp(self, who, tool, args):
        from aot.ai.services.resolvers import mcp_tool_call_resolver as mcpres
        params = {'tool_name': tool, 'arguments': args}

        def fn():
            return _svc().execute_action('mcp_tool_call', 'srv-x', params)
        with mock.patch.object(mcpres, '_is_builtin_server', lambda sid: True):
            if who is None:
                self._clear_scope_cache()
                with self.app.test_request_context():
                    return fn()
            return self._as_user(who, fn)

    def _use(self, tool, args):
        return {'tool_name': tool, 'arguments': args}

    def test_monitor_cannot_write_through_use_tool(self):
        n0, j0 = self._notes(), self._jobs()
        r = self._mcp('Monitor', 'use_tool', self._use('create_note', self._note_args()))
        self.assertEqual(r.get('reason_code'), 'insufficient_role', r)
        r = self._mcp('Monitor', 'use_tool',
                      self._use('add_schedule', _sched(target_id=self.output_id)))
        self.assertEqual(r.get('reason_code'), 'insufficient_role', r)
        self.assertEqual((self._notes(), self._jobs()), (n0, j0))

    def test_anonymous_requester_is_refused(self):
        self._scope_to_other_group()
        j0 = self._jobs()
        r = self._mcp(None, 'use_tool',
                      self._use('add_schedule', _sched(target_id=self.output_id)))
        self.assertEqual(r.get('reason_code'), 'insufficient_role', r)
        self.assertEqual(self._jobs(), j0)

    def test_editor_in_and_out_of_scope(self):
        self._scope_to_other_group()
        j0 = self._jobs()
        r = self._mcp('Editor', 'use_tool',
                      self._use('add_schedule', _sched(target_id=self.output_id)))
        self.assertEqual(r.get('status'), 'error', r)
        self.assertEqual(self._jobs(), j0)
        self._grant_group_to('Editor')
        r = self._mcp('Editor', 'use_tool',
                      self._use('add_schedule', _sched(target_id=self.output_id)))
        self.assertEqual(r.get('status'), 'success', r)
        self.assertEqual(self._jobs(), j0 + 1)

    def test_unwrap_is_bounded_and_fails_closed(self):
        from aot.ai.services.ai_action_service import AIActionService
        from aot.tools.tool_call_args import USE_TOOL_MAX_DEPTH, unwrap_use_tool
        inner = {'tool_name': 'create_note', 'arguments': {'note': 'x'}}
        nested = inner
        for _ in range(2):
            nested = {'tool_name': 'use_tool', 'arguments': nested}
        self.assertEqual(unwrap_use_tool('use_tool', nested),
                         ('create_note', {'note': 'x'}))
        deep = inner
        for _ in range(USE_TOOL_MAX_DEPTH + 1):
            deep = {'tool_name': 'use_tool', 'arguments': deep}
        tool, _args = unwrap_use_tool('use_tool', deep)
        self.assertEqual(tool, 'use_tool')
        self.assertTrue(AIActionService._is_write_action('mcp_tool_call', tool))
        # 메타 키(_confirmation_id 등)는 실행층처럼 안쪽으로 넘긴다.
        self.assertEqual(unwrap_use_tool('use_tool', dict(inner, _reason='r'))[1],
                         {'note': 'x', '_reason': 'r'})

    def test_chat_approval_judges_the_inner_tool(self):
        from aot.ai.services.ai_agent_service import AIAgentService
        params = {'tool_name': 'use_tool',
                  'arguments': self._use('create_note', self._note_args())}
        self.assertTrue(AIAgentService._approval_is_write('mcp_tool_call', 'srv', params))
        r = self._as_user('Monitor', lambda: AIAgentService._approval_denial(
            'mcp_tool_call', 'srv', params))
        self.assertIn('edit_settings', r or '')


# ---------------------------------------------------------------------------
# 3. 외부 MCP 앞 판정 — 판정이 깨지면 쓰기는 거부
# ---------------------------------------------------------------------------

class TestScopeRefusalFailsClosed(_Entry):

    def test_write_is_refused_when_the_check_breaks(self):
        self._scope_to_other_group()
        with mock.patch.object(scope, 'can_operate_tool_call',
                               side_effect=RuntimeError('boom')):
            self.assertEqual(te._scope_refusal('add_schedule', {},
                                               self.user_uuids['Editor']),
                             te.SCOPE_CHECK_FAILED)
            self.assertIsNone(te._scope_refusal('get_output_state', {},
                                                self.user_uuids['Editor']))
            with mock.patch.object(te, '_dispatch_virtual_tool') as run:
                body = self._call('add_schedule', _sched(target_id=self.output_id),
                                  self._role('Editor'),
                                  scope_user_uuid=self.user_uuids['Editor'])
        self.assertEqual((body.get('call_state'), body.get('reason_code')),
                         ('refused', 'group_scope'), body)
        self.assertFalse(run.called)


# ---------------------------------------------------------------------------
# 3b. 옵션·인자 값 속의 장치·지도
# ---------------------------------------------------------------------------

class TestOptionValues(_Entry):

    def setUp(self):
        super().setUp()
        # 탭 없는 조건 함수·대시보드 — 대상 자체는 허용된다.
        self.free_cond = str(uuid.uuid4())
        self.free_dash = str(uuid.uuid4())
        db.session.add(Conditional(unique_id=self.free_cond, name=_PREFIX + 'Free',
                                   is_activated=False))
        db.session.add(Dashboard(unique_id=self.free_dash, name=_PREFIX + 'Free'))
        db.session.commit()
        self.addCleanup(self._wipe_free)

    def _wipe_free(self):
        db.session.rollback()
        Conditional.query.filter_by(unique_id=self.free_cond).delete()
        from aot.databases.models import Widget
        Widget.query.filter_by(tab_id=self.free_dash).delete()
        Dashboard.query.filter_by(unique_id=self.free_dash).delete()
        GeoMap.query.filter(GeoMap.name == _PREFIX + 'Map').delete()
        db.session.commit()

    def test_function_options_pointing_at_a_foreign_device(self):
        self._scope_to_other_group()
        S = _svc_tools()
        ref = self.output_id + ',' + str(uuid.uuid4())
        self.assertEqual(self._direct('Editor', lambda: S.modify_function_options(
            function_id=self.free_cond, params={'measurement': ref}))[0], 'denied')
        self.assertEqual(self._direct('Editor', lambda: S.modify_function_options(
            function_id=self.free_cond, params={'period': 30}))[0], 'ran')

    def test_widget_options_pointing_at_a_foreign_device(self):
        self._scope_to_other_group()
        S = _svc_tools()
        self.assertEqual(self._direct('Editor', lambda: S.create_widget(
            tab_id=self.free_dash, widget_type='indicator',
            options={'measurement': self.output_id}))[0], 'denied')

    def test_plot_on_a_foreign_map(self):
        self._scope_to_other_group()
        gmap = str(uuid.uuid4())
        db.session.add(GeoMap(unique_id=gmap, name=_PREFIX + 'Map'))
        group = UserGroup.query.filter(UserGroup.name == _PREFIX + 'Group').first()
        db.session.add(GroupGrant(group_uuid=group.unique_id,
                                  resource_type=RESOURCE_GEO_MAP,
                                  resource_uuid=gmap, level=LEVEL_OPERATE))
        db.session.commit()
        self.assertEqual(self._direct('Editor', lambda: _svc_tools().create_plot(
            map_id=gmap, geometry={'type': 'Polygon', 'coordinates': [
                [[0, 0], [0, 1], [1, 1], [1, 0], [0, 0]]]}))[0], 'denied')


# ---------------------------------------------------------------------------
# 4. 승인 후 재호출 — 부른 사람과 승인한 사람 둘 다
# ---------------------------------------------------------------------------

class TestRecallAfterApproval(_Entry):

    def _approved(self, tool, args, approver):
        from datetime import datetime, timedelta
        row = MCPConfirmation(unique_id=str(uuid.uuid4()), tool_name=tool,
                              params_json=gate._canonical_params(args),
                              agent_id='user:test', status='approved',
                              user_id=self.user_uuids[approver])
        row.expires_at = datetime.utcnow() + timedelta(minutes=5)
        db.session.add(row)
        db.session.commit()
        return row.unique_id

    def test_out_of_scope_approver_blocks_the_recall(self):
        self._scope_to_other_group()
        args = {'function_id': _PREFIX + 'Cond'}
        cid = self._approved('activate_function', args, approver='Editor')
        body = self._call('activate_function', dict(args, _confirmation_id=cid),
                          self._role('Admin'), scope_user_uuid=self.user_uuids['Admin'])
        self.assertEqual((body.get('call_state'), body.get('reason_code')),
                         ('refused', 'group_scope'), body)
        self.assertFalse(self._cond_active())

    def test_approver_is_the_only_person_on_a_background_recall(self):
        self._scope_to_other_group()
        args = {'function_id': _PREFIX + 'Cond'}
        cid = self._approved('activate_function', args, approver='Editor')
        body = self._call('activate_function', dict(args, _confirmation_id=cid),
                          self._role('Admin'), scope_user_uuid=None)
        self.assertEqual(body.get('reason_code'), 'group_scope', body)
        self.assertFalse(self._cond_active())

    def test_co_principal_is_removed_afterwards(self):
        with write_scope.acting_as(self.user_uuids['Admin']) as p:
            with write_scope.also_acting_as(self.user_uuids['Editor']):
                self.assertEqual(len(p.co), 1)
            self.assertEqual(p.co, [])
        with write_scope.also_acting_as(self.user_uuids['Editor']) as p:
            self.assertEqual(p.user_uuid, self.user_uuids['Editor'])
        self.assertIsNone(write_scope.current())

    def test_denial_probe_does_not_record(self):
        """기록하지 않는 판정은 `_denial` 하나다(`check()` 는 없앴다 — 쓰는
        곳이 없었고, 거부를 묶음에 기록해 뒤의 결과를 거부로 뒤집었다)."""
        self.assertFalse(hasattr(write_scope, 'check'))
        self._scope_to_other_group()
        self._clear_scope_cache()
        with self.app.test_request_context():
            with write_scope.acting_as(self.user_uuids['Editor']) as p:
                self.assertIsNot(write_scope._denial(p, self.output_id),
                                 write_scope._ALLOWED)
                self.assertEqual(p.denied, [])


# ---------------------------------------------------------------------------
# 5. 웹 구획 — 단계 자원 함수 켜기
# ---------------------------------------------------------------------------

class TestPlotResourcesRoute(_Entry):
    """`/api/geo/plot/<id>/resources` 는 처리기(`_set_function_activation`)를
    곧바로 부른다 — 로그인한 사람으로 묶고, 켜기 **전에 전부** 묻는다."""

    def _stage(self):
        return {'state': 'running', 'resources': [
            {'role': 'irrigation', 'found': True,
             'functions': [{'id': self.cond, 'name': 'c', 'active': False}]}]}

    def _apply(self, who):
        from aot.aot_flask import routes_geo_plot
        from aot.aot_flask.geo import plot_context, plot_io
        fake_plot = mock.Mock()
        with mock.patch.object(plot_io, 'GeoPlot') as gp, \
                mock.patch.object(plot_context, 'stage_of',
                                  return_value=self._stage()), \
                mock.patch('aot.tools.aot_data_tool_service.AoTDataToolService.'
                           '_set_function_activation',
                           return_value={'status': 'success'}) as act:
            gp.query.filter_by.return_value.first.return_value = fake_plot
            code, body = self._view(who, routes_geo_plot.api_plot_resources_apply,
                                    'plot-x')
        return code, body, act

    def test_out_of_scope_function_is_not_turned_on(self):
        self._scope_to_other_group()
        code, body, act = self._apply('Editor')
        self.assertEqual(code, 403, body)
        self.assertFalse(act.called)

    def test_in_scope_function_is_turned_on(self):
        self._scope_to_other_group()
        self._grant_group_to('Editor')
        code, body, act = self._apply('Editor')
        self.assertEqual(code, 200, body)
        self.assertTrue(act.called)
