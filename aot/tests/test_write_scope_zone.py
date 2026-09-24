# coding=utf-8
"""구역(zone) 대상 쓰기의 그룹 스코프 — **쓰기 시점**에서, 입구마다.

정본 설계: `docs/design/access-scope-groups.md` §6-2a·§8-2

구역·부지·시설 외곽선·시설 구획 같은 지도 도형은 그 자신이 grant 단위가
아니다. 그래서 그 도형에 붙는 노트·일정은 탭·지도·시설의 그룹 제한을 전부
건너뛰었다(2026-09-23 재현 — `target_id` 로도, `target_name` 으로도). 결정:
**그 도형을 담은 시설, 없으면 그 지도의 스코프를 따른다**
(`scope.shape_resources` — 쓰기 시점 `write_scope.enforce` 와 앞 판정
`can_operate_uuid` 가 같은 함수를 쓴다).

여기서는 판정 함수 단위(`test_scope_groups.GeoShapeScopeTest`)가 아니라
**사람이 시킨 쓰기가 들어오는 입구마다** 실제 처리기까지 돌려 본다:
외부 MCP, 인앱 AI, 계획 실행기 워커, 예약 발화, 승인 후 재호출, 웹 화면.
"""
import json
import uuid
from unittest import mock

from aot.aot_flask.access import scope, write_scope
from aot.aot_flask.extensions import db
from aot.databases.models import (GeoFacility, GeoMap, GeoShape, GroupGrant,
                                  Notes, SchedulerJobMeta, UserGroup)
from aot.databases.models.user_group import (LEVEL_OPERATE,
                                             RESOURCE_GEO_FACILITY,
                                             RESOURCE_GEO_MAP)
from aot.tests.test_ai_requester_write_guard import _svc
from aot.tests.test_mcp_record_write_guard import _NOTE_MARK, _PREFIX
from aot.tests.test_write_scope_entry_points import _Entry, _sched_mod
from aot.tests.test_write_scope_enforcement import _sched, _svc_tools

_MARK = 'ws-zone-test'


def _square(cx, cy, half):
    return {'type': 'Polygon', 'coordinates': [[
        [cx - half, cy - half], [cx + half, cy - half],
        [cx + half, cy + half], [cx - half, cy + half],
        [cx - half, cy - half]]]}


def _invalidate_shape_caches():
    try:
        from aot.aot_flask.geo import shape_index
        shape_index.invalidate()
    except Exception:
        pass


class _Zone(_Entry):
    """고정물: 지도 하나 위에 시설 밖 구역 하나, 시설 외곽선·시설, 그 시설
    안의 구역 하나. 어느 도형에도 장치는 연결돼 있지 않다 — 판정은 오직
    담은 시설·지도로만 걸린다."""

    def setUp(self):
        super().setUp()
        tag = uuid.uuid4().hex[:6]
        self.map = str(uuid.uuid4())
        self.zone = str(uuid.uuid4())
        self.fac_shape = str(uuid.uuid4())
        self.fac = str(uuid.uuid4())
        self.fac_zone = str(uuid.uuid4())
        self.zone_name = _PREFIX + 'Zone' + tag
        self.fac_zone_name = _PREFIX + 'FacZone' + tag
        db.session.add(GeoMap(unique_id=self.map, name=_PREFIX + 'Map'))
        for uid, kind, name, cx, half in (
                (self.zone, 'zone', self.zone_name, -30, 1),
                (self.fac_shape, 'facility', _PREFIX + 'FacOutline' + tag, 30, 5),
                (self.fac_zone, 'zone', self.fac_zone_name, 30, 1)):
            db.session.add(GeoShape(
                unique_id=uid, geo_id=self.map, type=kind,
                feature={'type': 'Feature', 'properties': {'name': name},
                         'geometry': _square(cx, 0, half)}))
        db.session.add(GeoFacility(unique_id=self.fac, geo_id=self.map,
                                   shape_uuid=self.fac_shape,
                                   name=_PREFIX + 'Fac' + tag))
        db.session.commit()
        _invalidate_shape_caches()
        self.addCleanup(self._wipe_zone)

    def _wipe_zone(self):
        db.session.rollback()
        Notes.query.filter(Notes.note.like(_NOTE_MARK + '%')).delete(
            synchronize_session=False)
        SchedulerJobMeta.query.filter(SchedulerJobMeta.target_id.in_(
            [self.zone, self.fac_zone, self.fac_shape])).delete(
                synchronize_session=False)
        SchedulerJobMeta.query.filter(
            SchedulerJobMeta.reasoning.like('%' + _MARK + '%')).delete(
                synchronize_session=False)
        GeoFacility.query.filter_by(unique_id=self.fac).delete()
        GeoShape.query.filter(GeoShape.unique_id.in_(
            [self.zone, self.fac_shape, self.fac_zone])).delete(
                synchronize_session=False)
        GeoMap.query.filter_by(unique_id=self.map).delete()
        db.session.commit()
        _invalidate_shape_caches()

    # -- 도우미 ------------------------------------------------------------

    def _other_group(self):
        """아무도 속하지 않은 그룹(장치 탭도 함께 부여 — 스코프를 켠다)."""
        group = UserGroup.query.filter(UserGroup.name == _PREFIX + 'Group').first()
        if group is None:
            self._scope_to_other_group()
            group = UserGroup.query.filter(
                UserGroup.name == _PREFIX + 'Group').first()
        return group

    def _grant(self, rtype, ruuid):
        group = self._other_group()
        db.session.add(GroupGrant(group_uuid=group.unique_id, resource_type=rtype,
                                  resource_uuid=ruuid, level=LEVEL_OPERATE))
        db.session.commit()

    def _scope_map(self):
        self._grant(RESOURCE_GEO_MAP, self.map)

    def _scope_facility(self):
        self._grant(RESOURCE_GEO_FACILITY, self.fac)

    def _zone_notes(self):
        db.session.remove()
        return Notes.query.filter(Notes.note.like(_NOTE_MARK + '%'),
                                  Notes.target_id.in_(
                                      [self.zone, self.fac_zone])).count()

    def _zone_jobs(self):
        db.session.remove()
        return SchedulerJobMeta.query.filter(SchedulerJobMeta.target_id.in_(
            [self.zone, self.fac_zone])).count()

    def _note(self, **target):
        return self._note_args(**target)

    def _sched_args(self, **target):
        return _sched(content=_MARK, **target)


# ---------------------------------------------------------------------------
# 1. 외부 MCP — 앞 판정과 쓰기 시점 둘 다
# ---------------------------------------------------------------------------

class TestExternalMcp(_Zone):

    def _real(self, tool, args, who='Editor'):
        body = self._call(tool, args, self._role(who),
                          scope_user_uuid=self.user_uuids[who])
        return body.get('call_state'), body.get('reason_code')

    def test_note_and_schedule_on_a_scoped_zone_are_refused_by_id_and_name(self):
        self._scope_map()
        cases = (('create_note', self._note(target_id=self.zone)),
                 ('create_note', self._note(target_name=self.zone_name)),
                 ('add_schedule', self._sched_args(target_id=self.zone)),
                 ('add_schedule', self._sched_args(target_name=self.zone_name)))
        for tool, args in cases:
            with self.subTest(tool=tool, args=sorted(args)):
                self.assertEqual(self._real(tool, args), ('refused', 'group_scope'))
        self.assertEqual(self._zone_notes(), 0)
        self.assertEqual(self._zone_jobs(), 0)

    def test_handlers_enforce_on_the_resolved_zone(self):
        """앞 판정을 건너뛰어도 처리기가 푼 구역으로 거부한다."""
        self._scope_map()
        S = _svc_tools()
        cases = (
            ('note by id', lambda: S.create_note(
                note=_NOTE_MARK + ' x', target_id=self.zone)),
            ('note by name', lambda: S.create_note(
                note=_NOTE_MARK + ' x', target_name=self.zone_name)),
            ('schedule by id', lambda: S.add_schedule_tool(
                **self._sched_args(target_id=self.zone))),
            ('schedule by name', lambda: S.add_schedule_tool(
                **self._sched_args(target_name=self.zone_name))),
        )
        for label, fn in cases:
            with self.subTest(handler=label):
                self.assertEqual(self._direct('Editor', fn)[0], 'denied')
        self.assertEqual(self._zone_notes(), 0)
        self.assertEqual(self._zone_jobs(), 0)

    def test_editing_a_schedule_onto_a_scoped_zone_is_refused(self):
        """다른 대상의 일정을 이름으로 구역에 옮기는 것도 새 대상에서 막힌다."""
        jid = self._make_job().id         # 관리자가 만든, 스코프 안 걸린 대상
        self._scope_map()
        # 원래 대상(장치 탭)은 Editor 에게 열어 두고, 새 대상(구역)만 막는다.
        GroupGrant.query.filter(GroupGrant.resource_type == 'tab').delete(
            synchronize_session=False)
        db.session.commit()
        outcome, _ = self._direct('Editor', lambda: _svc_tools().edit_schedule_tool(
            job_id=str(jid), target_name=self.zone_name))
        self.assertEqual(outcome, 'denied')
        db.session.remove()
        self.assertEqual(SchedulerJobMeta.query.get(jid).target_id,
                         self.output_id)

    def test_zone_inside_a_facility_follows_the_facility(self):
        """시설 안 구역 — 시설을 막으면 막히고, 지도만 막으면 막히지 않는다."""
        self._scope_facility()
        self.assertEqual(self._real('create_note', self._note(target_id=self.fac_zone)),
                         ('refused', 'group_scope'))
        self.assertEqual(self._real('create_note', self._note(target_id=self.zone)),
                         ('executed', None))
        GroupGrant.query.filter(
            GroupGrant.resource_type == RESOURCE_GEO_FACILITY).delete(
                synchronize_session=False)
        db.session.commit()
        self._scope_map()
        self.assertEqual(self._real('create_note', self._note(target_id=self.fac_zone)),
                         ('executed', None))
        self.assertEqual(self._real('create_note', self._note(target_id=self.zone)),
                         ('refused', 'group_scope'))

    def test_facility_outline_itself_follows_its_facility(self):
        self._scope_facility()
        self.assertEqual(
            self._real('create_note', self._note(target_id=self.fac_shape)),
            ('refused', 'group_scope'))

    def test_in_scope_admin_and_unscoped_install_are_unaffected(self):
        # 그룹을 쓰지 않는 설치 — 전과 같다.
        self.assertEqual(self._real('create_note', self._note(target_id=self.zone)),
                         ('executed', None))
        self._scope_map()
        # 모든 그룹 접근 역할(Admin).
        self.assertEqual(
            self._real('create_note', self._note(target_name=self.zone_name),
                       who='Admin'), ('executed', None))
        # 그 지도를 받은 그룹의 구성원.
        self._grant_group_to('Editor')
        self.assertEqual(self._real('create_note', self._note(target_id=self.zone)),
                         ('executed', None))
        self.assertEqual(
            self._real('create_note', self._note(target_name=self.zone_name)),
            ('executed', None))
        self.assertEqual(self._zone_notes(), 4)

    def test_approved_recall_judges_the_approver_on_the_zone(self):
        from datetime import datetime, timedelta
        from aot.databases.models import MCPConfirmation
        from aot.tools import mcp_safety_gate as gate
        self._scope_map()
        args = self._sched_args(target_id=self.zone)
        row = MCPConfirmation(unique_id=str(uuid.uuid4()), tool_name='add_schedule',
                              params_json=gate._canonical_params(args),
                              agent_id='user:test', status='approved',
                              user_id=self.user_uuids['Editor'])
        row.expires_at = datetime.utcnow() + timedelta(minutes=5)
        db.session.add(row)
        db.session.commit()
        body = self._call('add_schedule', dict(args, _confirmation_id=row.unique_id),
                          self._role('Admin'), scope_user_uuid=self.user_uuids['Admin'])
        self.assertEqual(body.get('reason_code'), 'group_scope', body)
        self.assertEqual(self._zone_jobs(), 0)


# ---------------------------------------------------------------------------
# 2. 인앱 AI · 계획 실행기 워커 · 백그라운드
# ---------------------------------------------------------------------------

class TestInApp(_Zone):

    def test_in_app_request_is_refused_by_id_and_name(self):
        self._scope_map()
        for label, args in (('id', self._note(target_id=self.zone)),
                            ('name', self._note(target_name=self.zone_name))):
            with self.subTest(by=label):
                res = self._as_user('Editor', lambda: _svc().execute_action(
                    'virtual_tool_call', 'system_internal',
                    self._vparams('create_note', args)))
                self.assertEqual(res.get('reason_code'), 'group_scope', res)
        self.assertEqual(self._zone_notes(), 0)

    def test_legacy_note_action_is_refused(self):
        """옛 action_type('note') — `_resolve_target` 이 푼 대상에서 거부."""
        self._scope_map()
        res = self._as_user('Editor', lambda: _svc().execute_action(
            'note', self.zone, {'message': _NOTE_MARK + ' legacy'}))
        self.assertEqual(res.get('reason_code'), 'group_scope', res)
        db.session.remove()
        self.assertEqual(Notes.query.filter(
            Notes.target_id == self.zone).count(), 0)

    def test_planner_worker_is_refused(self):
        self._scope_map()
        res = self._in_worker('Editor', 'virtual_tool_call', self._vparams(
            'add_schedule', self._sched_args(target_name=self.zone_name)))
        self.assertEqual(res.get('reason_code'), 'group_scope', res)
        self.assertEqual(self._zone_jobs(), 0)

    def test_in_scope_worker_writes(self):
        self._scope_map()
        self._grant_group_to('Editor')
        res = self._in_worker('Editor', 'virtual_tool_call', self._vparams(
            'create_note', self._note(target_name=self.zone_name)))
        self.assertEqual(res.get('status'), 'success', res)
        self.assertEqual(self._zone_notes(), 1)

    def test_background_without_a_person_is_exempt(self):
        self._scope_map()
        res = self._in_bare_worker('virtual_tool_call', self._vparams(
            'create_note', self._note(target_id=self.zone)))
        self.assertEqual(res.get('status'), 'success', res)
        self.assertEqual(self._zone_notes(), 1)


# ---------------------------------------------------------------------------
# 3. 예약 — 만들기·발화
# ---------------------------------------------------------------------------

class TestScheduled(_Zone):

    def _note_job(self, owner, by_name=False):
        args = (self._note(target_name=self.zone_name) if by_name
                else self._note(target_id=self.zone))
        meta = SchedulerJobMeta(
            action_type='virtual_tool_call', target_id='system_internal',
            params_json=json.dumps({'tool_name': 'create_note', 'arguments': args}),
            user_id=self._user(owner).id if owner else None, state='PENDING',
            reasoning=_MARK, proposed_by='HUMAN' if owner else 'AI')
        db.session.add(meta)
        db.session.commit()
        return meta.id

    def test_fire_time_recheck_refuses_a_zone_job(self):
        self._scope_map()
        for by_name in (False, True):
            with self.subTest(by_name=by_name):
                res, meta = self._fire(self._note_job('Editor', by_name))
                self.assertEqual(res.get('call_state'), 'refused', res)
                self.assertEqual(meta.state, 'FAILED')
        self.assertEqual(self._zone_notes(), 0)

    def test_fire_binding_refuses_even_without_the_precheck(self):
        self._scope_map()
        with mock.patch.object(_sched_mod().AISchedulerService, '_scope_denies',
                               return_value=None):
            res, meta = self._fire(self._note_job('Editor'))
        self.assertEqual(res.get('reason_code'), 'group_scope', res)
        self.assertEqual(meta.state, 'FAILED')
        self.assertEqual(self._zone_notes(), 0)

    def test_in_scope_and_system_jobs_fire(self):
        self._scope_map()
        res, meta = self._fire(self._note_job(None))
        self.assertEqual(res.get('status'), 'success', res)
        self._grant_group_to('Editor')
        res, meta = self._fire(self._note_job('Editor'))
        self.assertEqual(res.get('status'), 'success', res)
        self.assertEqual(self._zone_notes(), 2)

    def test_human_task_owner_is_judged_on_the_zone(self):
        """사람 작업(action_type='human')의 대상 구역 — 책임자 판정
        (`_scope_denies` → `job_denial`)이 지도로 옮겨 본다."""
        self._scope_map()
        meta = SchedulerJobMeta(action_type='human', target_id=self.zone,
                                params_json='{}', reasoning=_MARK,
                                user_id=self._user('Editor').id)
        db.session.add(meta)
        db.session.commit()
        S = _sched_mod().AISchedulerService
        self.assertIsNotNone(S._scope_denies(meta.id, 'human', self.zone, {}))
        self._grant_group_to('Editor')
        self._clear_scope_cache()
        self.assertIsNone(S._scope_denies(meta.id, 'human', self.zone, {}))


# ---------------------------------------------------------------------------
# 4. 웹 화면 — 노트 API·지도/노트 예정·스케줄러
# ---------------------------------------------------------------------------

class TestWebRoutes(_Zone):

    def _notes_api(self):
        from aot.aot_flask import routes_notes_api
        return routes_notes_api

    def _make_note(self, target):
        n = Notes(name=_PREFIX, note=_NOTE_MARK + ' web', target_id=target,
                  target_type='zone')
        db.session.add(n)
        db.session.commit()
        return n.unique_id

    def test_note_create_update_delete_follow_the_zone(self):
        self._scope_map()
        R = self._notes_api()
        code, body = self._view('Editor', R.api_notes_create, json_body={
            'target_id': self.zone, 'target_type': 'zone',
            'note': _NOTE_MARK + ' web'})
        self.assertEqual(code, 403, body)
        self.assertEqual(body.get('error'), scope.deny_message())
        nid = self._make_note(self.zone)
        code, _ = self._view('Editor', R.api_notes_update, nid,
                             json_body={'name': 'changed'})
        self.assertEqual(code, 403)
        code, _ = self._view('Editor', R.api_notes_delete, nid, method='DELETE')
        self.assertEqual(code, 403)
        db.session.remove()
        row = Notes.query.filter_by(unique_id=nid).first()
        self.assertIsNotNone(row)
        self.assertEqual(row.name, _PREFIX)

    def test_note_routes_pass_in_scope_admin_and_untargeted(self):
        self._scope_map()
        R = self._notes_api()
        code, body = self._view('Admin', R.api_notes_create, json_body={
            'target_id': self.zone, 'note': _NOTE_MARK + ' admin'})
        self.assertEqual(code, 200, body)
        code, body = self._view('Editor', R.api_notes_create, json_body={
            'note': _NOTE_MARK + ' floating'})
        self.assertEqual(code, 200, body)
        self._grant_group_to('Editor')
        code, body = self._view('Editor', R.api_notes_create, json_body={
            'target_id': self.zone, 'note': _NOTE_MARK + ' member'})
        self.assertEqual(code, 200, body)
        nid = self._make_note(self.zone)
        code, _ = self._view('Editor', R.api_notes_update, nid,
                             json_body={'name': 'changed'})
        self.assertEqual(code, 200)
        code, _ = self._view('Editor', R.api_notes_delete, nid, method='DELETE')
        self.assertEqual(code, 200)

    def test_map_and_note_schedule_gateway(self):
        """`/api/geo/schedule`·`/notes/<id>/schedule` 의 단일 게이트웨이."""
        from aot.aot_flask.routes_geo_schedule import _create_human_schedule
        self._scope_facility()

        def _mk(who, target):
            self._clear_scope_cache()
            import flask_login
            with self.app.test_request_context(method='POST'):
                flask_login.login_user(self._user(who))
                out = _create_human_schedule(
                    target, 'zone', 'z', '2030-01-02', '09:00', _MARK, '')
            resp, code = out if isinstance(out, tuple) else (out, out.status_code)
            return code, resp.get_json()

        code, body = _mk('Editor', self.fac_zone)
        self.assertEqual(code, 403, body)
        self.assertEqual(body.get('message'), scope.deny_message())
        # 대상 없는 예정·시설 밖 구역(지도는 스코프 없음)은 통과한다.
        with mock.patch.object(_sched_mod(), 'get_scheduler'):
            self.assertEqual(_mk('Editor', 'none')[0], 200)
            self.assertEqual(_mk('Editor', self.zone)[0], 200)
            self.assertEqual(_mk('Admin', self.fac_zone)[0], 200)
        db.session.remove()
        self.assertEqual(SchedulerJobMeta.query.filter_by(
            target_id=self.fac_zone).count(), 1)

    def test_scheduler_propose_and_edit_follow_the_zone(self):
        from aot.aot_flask import routes_scheduler as RS
        self._scope_map()
        with mock.patch.object(_sched_mod(), 'get_scheduler'):
            code, body = self._view('Editor', RS.api_propose_job, json_body={
                'action_type': 'human', 'target_id': self.zone,
                'params': {'content': _MARK}, 'reasoning': _MARK})
        self.assertEqual(code, 403, body)
        self.assertEqual(self._zone_jobs(), 0)
        jid = self._make_job().id
        GroupGrant.query.filter(GroupGrant.resource_type == 'tab').delete(
            synchronize_session=False)
        db.session.commit()
        code, _ = self._view('Editor', RS.api_update_job, jid, method='PUT',
                             json_body={'target_name': self.zone_name})
        self.assertEqual(code, 403)
        db.session.remove()
        self.assertEqual(SchedulerJobMeta.query.get(jid).target_id,
                         self.output_id)

    def test_note_link_cancel_of_a_zone_job(self):
        """노트 구간 링크를 끊으면서 예정까지 지우는 길도 그 예정의 대상으로
        판정한다."""
        from aot.databases.models import NoteScheduleLink
        body = self._call('add_schedule', self._sched_args(target_id=self.zone),
                          self._role('Admin'), scope_user_uuid=self.user_uuids['Admin'])
        self.assertEqual(body.get('call_state'), 'executed', body)
        db.session.remove()
        job_uid = SchedulerJobMeta.query.filter_by(target_id=self.zone).first().unique_id
        link = NoteScheduleLink(note_id=str(uuid.uuid4()), job_uid=job_uid,
                                start_offset=0, end_offset=1, text_snapshot='x')
        db.session.add(link)
        db.session.commit()
        link_id = link.unique_id
        self.addCleanup(lambda: (NoteScheduleLink.query.filter_by(
            unique_id=link_id).delete(), db.session.commit()))
        self._scope_map()
        code, _ = self._view('Editor', self._notes_api().api_note_link_delete,
                             link_id, json_body={'cancel_job': True})
        self.assertEqual(code, 403)
        db.session.remove()
        self.assertEqual(SchedulerJobMeta.query.filter_by(
            unique_id=job_uid).count(), 1)
        self._grant_group_to('Editor')
        code, _ = self._view('Editor', self._notes_api().api_note_link_delete,
                             link_id, json_body={'cancel_job': True})
        self.assertEqual(code, 200)
        db.session.remove()
        self.assertEqual(SchedulerJobMeta.query.filter_by(
            unique_id=job_uid).count(), 0)

    def test_scheduler_edit_and_delete_of_a_zone_job(self):
        from aot.aot_flask import routes_scheduler as RS
        body = self._call('add_schedule', self._sched_args(target_id=self.zone),
                          self._role('Admin'), scope_user_uuid=self.user_uuids['Admin'])
        self.assertEqual(body.get('call_state'), 'executed', body)
        db.session.remove()
        jid = SchedulerJobMeta.query.filter_by(target_id=self.zone).first().id
        self._scope_map()
        code, _ = self._view('Editor', RS.api_update_job, jid, method='PUT',
                             json_body={'time': '11:00'})
        self.assertEqual(code, 403)
        code, _ = self._view('Editor', RS.api_delete_job, jid, method='DELETE')
        self.assertEqual(code, 403)
        db.session.remove()
        self.assertNotEqual(SchedulerJobMeta.query.get(jid).state, 'ARCHIVED')


# ---------------------------------------------------------------------------
# 5. 판정 규칙 — 쓰기 시점과 앞 판정이 같은 답을 낸다
# ---------------------------------------------------------------------------

class TestSameJudgement(_Zone):

    def test_enforce_and_precheck_agree(self):
        self._scope_facility()
        editor = self._user('Editor')
        for target, expect_allowed in ((self.zone, True), (self.fac_zone, False),
                                       (self.fac_shape, False), (self.fac, False),
                                       (self.map, True)):
            with self.subTest(target=target == self.fac_zone and 'fac_zone'
                              or target == self.zone and 'zone' or 'other'):
                self._clear_scope_cache()
                with self.app.test_request_context():
                    pre = scope.can_operate_uuid(target, user=editor)
                outcome, _ = self._direct('Editor',
                                          lambda: write_scope.enforce(target))
                self.assertEqual(pre, expect_allowed)
                self.assertEqual(outcome == 'ran', expect_allowed)

    def test_shape_linked_to_a_device_needs_both(self):
        """장치가 연결된 도형은 장치(탭)와 담은 지도 **둘 다** 통과해야 한다."""
        marker = str(uuid.uuid4())
        db.session.add(GeoShape(unique_id=marker, geo_id=self.map, type='aot_device',
                                device_id=self.output_id,
                                feature={'type': 'Feature', 'properties': {},
                                         'geometry': {'type': 'Point',
                                                      'coordinates': [-30, 0]}}))
        db.session.commit()
        self.addCleanup(lambda: (GeoShape.query.filter_by(unique_id=marker).delete(),
                                 db.session.commit()))
        self._scope_map()
        self._grant_group_to('Editor')      # 탭·지도 둘 다 받은 그룹
        self.assertEqual(self._direct('Editor', lambda: write_scope.enforce(marker))[0],
                         'ran')
        GroupGrant.query.filter(GroupGrant.resource_type == 'tab').delete(
            synchronize_session=False)
        from aot.databases.models import UserGroupMember
        UserGroupMember.query.delete(synchronize_session=False)
        db.session.commit()                 # 이제 지도만 막혀 있다
        self.assertEqual(self._direct('Editor', lambda: write_scope.enforce(marker))[0],
                         'denied')
