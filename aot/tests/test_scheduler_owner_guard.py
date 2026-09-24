# coding=utf-8
"""예약 책임자와 옛 일정 API·승인 실행의 남은 구멍.

정본 설계: `docs/design/access-scope-groups.md` §6-2a

2026-09-23 검토에서 재현된 것:

  1. 옛 `/api/scheduler/job/<id>` PUT 은 고친 뒤 대상을 **장치 자리만** 이름에서
     풀어 물었다 — `function_id` 에 함수 **이름**을 주면 그룹 밖 함수로 바뀐
     초안이 200 으로 저장됐다. 승인된(PENDING) 예약도 고칠 수 있어 행과
     등록된 APScheduler 잡이 어긋났다.
  2. 옛 일괄 승인은 상태만 PENDING 으로 바꿨다(판정·책임자·등록 없음).
  3. `execute_approved` 는 대기 행·승인자 없는 행도 실행했고, 승인자 범위 밖이라
     대기로 되돌릴 때마다 유효시간을 새로 셌다(요청을 끝없이 살려 둘 수 있다).
  4. 책임자 계정을 지우면 그 예약이 말없이 면제됐다.
  5. 책임자 없는 예약 — 기록으로 채우고, 못 채운 것은 화면에 드러내 관리자가
     지정한다(지정 때 새 책임자로 판정).

재검증(같은 날)에서 고친 것: 채우기는 uuid 로만 잇고 기록된 사람으로 판정이
통과할 때만 쓴다(이름 매칭 제거), 꺼진 계정은 지워진 계정과 같게 본다(끄는
순간 풀기·지정 거부·후보 제외), 계정 삭제와 예약 풀기는 한 커밋, 자기 자신
삭제 가드(unique_id 끼리 비교).
"""
import json
import types
import uuid
from datetime import datetime, timedelta
from unittest import mock

import flask_login

from aot.aot_flask.extensions import db
from aot.databases.models import (AuditLog, MCPConfirmation, SchedulerJobMeta,
                                  User, UserGroupMember)
from aot.databases.models.scheduler import SchedulerAuditLog
from aot.tests.test_mcp_record_write_guard import _PREFIX
from aot.tests.test_write_scope_entry_points import _MARK, _Entry, _sched_mod
from aot.tools import mcp_safety_gate as gate


class _Owner(_Entry):

    def setUp(self):
        super().setUp()
        self.addCleanup(self._wipe_audit)

    def _wipe_audit(self):
        db.session.rollback()
        ids = [m.id for m in SchedulerJobMeta.query.filter(
            SchedulerJobMeta.reasoning.like(_MARK + '%')).all()]
        if ids:
            SchedulerAuditLog.query.filter(
                SchedulerAuditLog.job_meta_id.in_(ids)).delete(
                    synchronize_session=False)
        db.session.commit()

    def _legacy(self):
        from aot.aot_flask import routes_ai_api
        return routes_ai_api

    def _routes(self):
        from aot.aot_flask import routes_scheduler
        return routes_scheduler

    def _meta(self, jid):
        db.session.remove()
        return SchedulerJobMeta.query.get(jid)

    def _gone_user(self):
        """지워질 사람 — Editor 역할."""
        u = User(name=(_PREFIX + 'Gone').lower(),
                 role_id=self._user('Editor').role_id, is_enabled=True)
        db.session.add(u)
        db.session.commit()
        return types.SimpleNamespace(id=u.id, unique_id=u.unique_id, name=u.name)

    def _person(self, name, role='Admin', enabled=True):
        """시험 밖 이름의 계정 — 스스로 치운다."""
        u = User(name=name, role_id=self._user(role).role_id,
                 is_enabled=enabled)
        db.session.add(u)
        db.session.commit()
        uid = u.id
        self.addCleanup(self._drop_user, uid)
        return types.SimpleNamespace(id=u.id, unique_id=u.unique_id, name=u.name)

    @staticmethod
    def _candidates(ctx, jid):
        """화면이 그 예약의 지정 상자에 내놓는 후보 이름."""
        jobs = (ctx['drafts'] + ctx['active_jobs'] + ctx['completed_jobs'])
        job = [j for j in jobs if j.id == jid][0]
        return [u['name'] for u in job.owner_candidates]

    @staticmethod
    def _drop_user(uid):
        db.session.rollback()
        User.query.filter(User.id == uid).delete(synchronize_session=False)
        db.session.commit()

    def _page_context(self, who):
        """스케줄러 화면이 템플릿에 넘기는 값(렌더는 가짜 — 시험 DB 에는
        화면 설정 행이 없다)."""
        routes = self._routes()
        self._clear_scope_cache()
        with mock.patch.object(routes, 'render_template',
                               side_effect=lambda _t, **kw: kw):
            with self.app.test_request_context():
                flask_login.login_user(self._user(who))
                return routes.page_scheduler()


# ---------------------------------------------------------------------------
# 1. 옛 편집 API — 고친 뒤 편집자로 실제 도구 판정, 초안만
# ---------------------------------------------------------------------------

class TestLegacyEdit(_Owner):

    def _activate(self, fid):
        return json.dumps({'tool_name': 'activate_function',
                           'arguments': {'function_id': fid}})

    def _read_draft(self):
        return self._job(owner=None, state='DRAFT',
                         params={'tool_name': 'get_function_list',
                                 'arguments': {}})

    def test_function_given_by_name_is_judged(self):
        self._scope_to_other_group()
        for fid in (self.cond, _PREFIX + 'Cond'):
            with self.subTest(fid='uuid' if fid == self.cond else 'name'):
                jid = self._read_draft()
                pj = self._activate(fid)
                code, _ = self._view('Editor', self._legacy().update_scheduler_job,
                                     jid, method='PUT', json_body={'params_json': pj})
                self.assertEqual(code, 403)
                self.assertNotIn('activate_function',
                                 self._meta(jid).params_json)

    def test_in_scope_edit_is_saved(self):
        self._scope_to_other_group()
        self._grant_group_to('Editor')
        jid = self._read_draft()
        pj = self._activate(_PREFIX + 'Cond')
        code, _ = self._view('Editor', self._legacy().update_scheduler_job,
                             jid, method='PUT', json_body={'params_json': pj})
        self.assertEqual(code, 200)
        self.assertIn('activate_function', self._meta(jid).params_json)

    def test_only_drafts_are_edited_here(self):
        """승인된 예약은 등록된 잡과 어긋나므로 이 라우트로 고치지 않는다."""
        for state in ('PENDING', 'COMPLETED'):
            with self.subTest(state=state):
                jid = self._job(owner='Editor', state=state)
                before = self._meta(jid).params_json
                code, _ = self._view('Admin', self._legacy().update_scheduler_job,
                                     jid, method='PUT',
                                     json_body={'params_json': '{}',
                                                'reasoning': _MARK + ' x'})
                self.assertEqual(code, 409)
                meta = self._meta(jid)
                self.assertEqual(meta.params_json, before)
                self.assertEqual(meta.reasoning, _MARK)

    def test_params_must_be_an_object(self):
        jid = self._read_draft()
        for bad in ('not json', '[1, 2]'):
            code, _ = self._view('Admin', self._legacy().update_scheduler_job,
                                 jid, method='PUT', json_body={'params_json': bad})
            self.assertEqual(code, 400, bad)


# ---------------------------------------------------------------------------
# 2. 옛 일괄 승인 — 단건 승인과 같은 한 벌
# ---------------------------------------------------------------------------

class TestLegacyBatchApprove(_Owner):

    def _batch(self, who, ids):
        with mock.patch.object(_sched_mod(), 'get_scheduler') as gs:
            code, body = self._view(who, self._legacy().batch_process_scheduler_jobs,
                                    json_body={'job_ids': ids, 'action': 'approve'})
        return code, body, gs.return_value.add_job

    def test_batch_approve_judges_registers_and_records_owner(self):
        self._scope_to_other_group()
        self._grant_group_to('Editor')
        jid = self._job(owner=None, state='DRAFT')
        code, body, add_job = self._batch('Editor', [jid])
        self.assertEqual(body.get('success'), [jid], body)
        self.assertTrue(add_job.called)
        meta = self._meta(jid)
        self.assertEqual(meta.state, 'PENDING')
        self.assertEqual(meta.user_id, self._user('Editor').id)

    def test_batch_approve_refuses_out_of_scope_target_by_name(self):
        self._scope_to_other_group()
        jid = self._job(owner=None, state='DRAFT', params={
            'tool_name': 'activate_function',
            'arguments': {'function_id': _PREFIX + 'Cond'}})
        code, body, add_job = self._batch('Editor', [jid])
        self.assertEqual(body.get('success'), [], body)
        self.assertFalse(add_job.called)
        meta = self._meta(jid)
        self.assertEqual((meta.state, meta.user_id), ('DRAFT', None))

    def test_batch_approve_of_non_draft_fails(self):
        jid = self._job(owner='Editor', state='PENDING')
        code, body, add_job = self._batch('Admin', [jid])
        self.assertEqual(body.get('success'), [], body)
        self.assertFalse(add_job.called)


# ---------------------------------------------------------------------------
# 3. 승인 실행 — 승인된 행·기록된 승인자만, 되돌림은 처음 마감까지
# ---------------------------------------------------------------------------

class TestExecuteApproved(_Owner):

    def _pending(self, created_ago=0):
        row = MCPConfirmation(unique_id=str(uuid.uuid4()),
                              tool_name='activate_function',
                              params_json=gate._canonical_params(
                                  {'function_id': self.cond}),
                              agent_id='ext-agent', status='pending')
        row.created_at = datetime.utcnow() - timedelta(seconds=created_ago)
        row.expires_at = row.created_at + timedelta(seconds=gate._CONFIRM_TTL_SEC)
        db.session.add(row)
        db.session.commit()
        return row.unique_id

    def _run(self, cid):
        self._clear_scope_cache()
        with self.app.test_request_context():
            return gate.execute_approved(cid)

    def _row(self, cid):
        db.session.remove()
        return MCPConfirmation.query.filter_by(unique_id=cid).first()

    def test_pending_row_is_not_run(self):
        cid = self._pending()
        status, res = self._run(cid)
        self.assertEqual(status, 'refused')
        self.assertEqual(res.get('reason_code'), 'not_approved')
        self.assertFalse(self._cond_active())
        self.assertEqual(self._row(cid).status, 'pending')

    def test_approved_row_without_approver_is_not_run(self):
        cid = self._pending()
        row = self._row(cid)
        row.status = 'approved'
        db.session.commit()
        status, res = self._run(cid)
        self.assertEqual((status, res.get('reason_code')), ('refused', 'not_approved'))
        self.assertFalse(self._cond_active())

    def test_approver_that_no_longer_exists_is_not_run(self):
        gone = self._gone_user()
        cid = self._pending()
        row = self._row(cid)
        row.status, row.user_id = 'approved', gone.unique_id
        db.session.commit()
        User.query.filter(User.id == gone.id).delete()
        db.session.commit()
        status, res = self._run(cid)
        self.assertEqual((status, res.get('reason_code')), ('refused', 'not_approved'))
        self.assertFalse(self._cond_active())

    def _approve_as_editor(self, cid):
        row = self._row(cid)
        row.status = 'approved'
        row.user_id = self.user_uuids['Editor']
        row.expires_at = datetime.utcnow() + timedelta(seconds=gate._APPROVED_TTL_SEC)
        db.session.commit()

    def test_return_to_queue_keeps_the_original_deadline(self):
        self._scope_to_other_group()
        cid = self._pending(created_ago=60)
        deadline = self._row(cid).created_at + timedelta(
            seconds=gate._CONFIRM_TTL_SEC)
        for _ in range(3):
            self._approve_as_editor(cid)
            status, res = self._run(cid)
            self.assertEqual(status, 'refused')
            self.assertTrue(res.get('returned_to_queue'))
            row = self._row(cid)
            self.assertEqual((row.status, row.user_id), ('pending', None))
            self.assertLess(abs((row.expires_at - deadline).total_seconds()), 1)
        self.assertFalse(self._cond_active())
        # 거부당한 승인자가 누구였는지 감사 기록에 남는다.
        logs = AuditLog.query.filter(
            AuditLog.action == 'mcp.approval_returned',
            AuditLog.target_id == cid).all()
        self.assertEqual(len(logs), 3)
        self.assertEqual({l.username for l in logs},
                         {self._user('Editor').name})

    def test_return_after_the_deadline_closes_the_request(self):
        self._scope_to_other_group()
        cid = self._pending(created_ago=gate._CONFIRM_TTL_SEC + 5)
        self._approve_as_editor(cid)
        status, res = self._run(cid)
        self.assertEqual(status, 'refused')
        self.assertFalse(res.get('returned_to_queue'))
        self.assertEqual(self._row(cid).status, 'expired')
        self.assertNotIn(cid, [p['confirmation_id'] for p in gate.list_pending()])


# ---------------------------------------------------------------------------
# 4·5. 책임자 — 계정 삭제, 채우기, 지정
# ---------------------------------------------------------------------------

class TestOwnerDeletion(_Owner):

    def _del(self, who, target_uuid):
        from aot.aot_flask.utils import utils_settings
        form = types.SimpleNamespace(user_id=types.SimpleNamespace(
            data=target_uuid))
        with self.app.test_request_context():
            flask_login.login_user(self._user(who))
            return utils_settings.user_del(form)

    def _owned_by(self, person):
        jid = self._job(owner=None, state='PENDING')
        meta = self._meta(jid)
        meta.user_id = person.id
        db.session.commit()
        return jid

    def test_deleting_the_owner_marks_the_job_ownerless_and_it_keeps_running(self):
        self._scope_to_other_group()
        gone = self._gone_user()
        jid = self._owned_by(gone)
        msgs = self._del('Admin', gone.unique_id)
        self.assertFalse(msgs['error'], msgs)
        self.assertIsNone(User.query.filter(User.id == gone.id).first())
        meta = self._meta(jid)
        self.assertIsNone(meta.user_id)
        self.assertTrue(SchedulerAuditLog.query.filter(
            SchedulerAuditLog.job_meta_id == jid,
            SchedulerAuditLog.decision == 'OWNER_REMOVED').first())
        # 현장 예약을 세우지 않는다 — 책임자 없는 예약으로 계속 돈다.
        res, meta = self._fire(jid)
        self.assertEqual(res.get('status'), 'success', res)
        self.assertTrue(self._written())

    def test_failed_delete_leaves_the_jobs_owned(self):
        """풀기와 삭제는 한 커밋 — 삭제가 실패하면 예약도 풀리지 않는다."""
        gone = self._gone_user()
        jid = self._owned_by(gone)
        with mock.patch.object(db.session, 'delete',
                               side_effect=RuntimeError('injected')):
            msgs = self._del('Admin', gone.unique_id)
        self.assertTrue(msgs['error'], msgs)
        db.session.remove()
        self.assertIsNotNone(User.query.filter(User.id == gone.id).first())
        self.assertEqual(self._meta(jid).user_id, gone.id)
        self.assertFalse(SchedulerAuditLog.query.filter(
            SchedulerAuditLog.job_meta_id == jid,
            SchedulerAuditLog.decision == 'OWNER_REMOVED').first())

    def test_user_cannot_delete_themself(self):
        # 관리자가 둘이어야 "마지막 관리자" 가드가 먼저 막지 않는다.
        self._person(_PREFIX.lower() + 'admin2', role='Admin')
        admin = self._user('Admin')
        msgs = self._del('Admin', admin.unique_id)
        self.assertTrue(msgs['error'], msgs)
        db.session.remove()
        self.assertIsNotNone(User.query.filter(
            User.unique_id == self.user_uuids['Admin']).first())


class TestOwnerDisabled(_Owner):
    """꺼진 계정 = 지워진 계정. 끄는 순간 예약을 풀고, 예약은 계속 돈다."""

    def _mod(self, who, target, enabled):
        from aot.aot_flask.utils import utils_settings
        d = lambda v: types.SimpleNamespace(data=v)  # noqa: E731
        form = types.SimpleNamespace(
            user_id=d(target.unique_id), email=d(target.email),
            full_name=d(target.full_name or ''), code=d(''),
            password_new=d(''), password_repeat=d(''),
            role_id=d(target.role_id), is_enabled=d(enabled),
            theme=d(target.theme))
        with self.app.test_request_context():
            flask_login.login_user(self._user(who))
            return utils_settings.user_mod(form)

    def test_disabling_the_owner_releases_and_the_job_keeps_running(self):
        self._scope_to_other_group()
        person = self._person(_PREFIX.lower() + 'off', role='Editor')
        jid = self._job(owner=None, state='PENDING')
        meta = self._meta(jid)
        meta.user_id = person.id
        db.session.commit()
        msgs, _ = self._mod('Admin', User.query.get(person.id), False)
        self.assertFalse(msgs['error'], msgs)
        self.assertFalse(User.query.get(person.id).is_enabled)
        self.assertIsNone(self._meta(jid).user_id)
        log = SchedulerAuditLog.query.filter(
            SchedulerAuditLog.job_meta_id == jid,
            SchedulerAuditLog.decision == 'OWNER_REMOVED').first()
        self.assertIn('disabled', log.feedback)
        res, meta = self._fire(jid)
        self.assertEqual(res.get('status'), 'success', res)
        self.assertTrue(self._written())

    def test_disabled_owner_is_not_judged_as_owner(self):
        """풀리기 전의 행(이 규칙 이전에 꺼진 계정)도 그 사람으로 돌지 않는다."""
        S = _sched_mod().AISchedulerService
        person = self._person(_PREFIX.lower() + 'off2', role='Editor',
                              enabled=False)
        jid = self._job(owner=None, state='PENDING')
        meta = self._meta(jid)
        meta.user_id = person.id
        db.session.commit()
        self.assertIsNone(S.job_owner_uuid(jid))
        out = S.backfill_job_owners()
        self.assertGreaterEqual(out['released'], 1)
        self.assertIsNone(self._meta(jid).user_id)

    def test_disabled_person_cannot_be_assigned_or_picked(self):
        person = self._person(_PREFIX.lower() + 'off3', role='Admin',
                              enabled=False)
        jid = self._job(owner=None, state='PENDING')
        code, body = self._view('Admin', self._routes().api_assign_job_owner,
                                jid, json_body={'user_id': person.unique_id})
        self.assertEqual(code, 409, body)
        self.assertIn('disabled', body.get('error', ''))
        self.assertIsNone(self._meta(jid).user_id)
        admin = self._page_context('Admin')
        self.assertNotIn(person.name, self._candidates(admin, jid))


class TestBackfill(_Owner):

    def _row(self, **cols):
        jid = self._job(owner=None, state='PENDING')
        meta = self._meta(jid)
        meta.decided_by = cols.get('decided_by', 'AI')
        meta.proposed_by = cols.get('proposed_by', 'AI')
        meta.last_edited_by = cols.get('last_edited_by')
        if 'user_id' in cols:
            meta.user_id = cols['user_id']
        db.session.commit()
        return jid

    def test_backfill_maps_only_existing_people_by_uuid_and_is_idempotent(self):
        S = _sched_mod().AISchedulerService
        editor = self._user('Editor')
        admin = self._user('Admin')
        gone = self._gone_user()
        gone_uuid, gone_id = gone.unique_id, gone.id
        User.query.filter(User.id == gone_id).delete()
        db.session.commit()

        by_name = self._row(decided_by=editor.name.upper(),
                            proposed_by=editor.name)
        by_uuid = self._row(decided_by='HUMAN', proposed_by=admin.unique_id)
        by_edit = self._row(decided_by='HUMAN', proposed_by='HUMAN',
                            last_edited_by=editor.unique_id)
        ai_only = self._row(decided_by='AI', proposed_by='AI',
                            last_edited_by='AI')
        deleted = self._row(decided_by=gone_uuid, proposed_by='SYSTEM')
        dangling = self._row(user_id=gone_id)

        first = S.backfill_job_owners()
        self.assertGreaterEqual(first['assigned'], 2)
        self.assertGreaterEqual(first['released'], 1)
        owners = {jid: self._meta(jid).user_id for jid in
                  (by_name, by_uuid, by_edit, ai_only, deleted, dangling)}
        self.assertIsNone(owners[by_name])      # 이름으로는 잇지 않는다
        self.assertEqual(owners[by_uuid], admin.id)
        self.assertEqual(owners[by_edit], editor.id)
        self.assertIsNone(owners[ai_only])
        self.assertIsNone(owners[deleted])
        self.assertIsNone(owners[dangling])
        self.assertTrue(SchedulerAuditLog.query.filter(
            SchedulerAuditLog.job_meta_id == dangling,
            SchedulerAuditLog.decision == 'OWNER_REMOVED').first())

        second = S.backfill_job_owners()
        self.assertEqual((second['assigned'], second['released']), (0, 0))
        self.assertEqual({jid: self._meta(jid).user_id for jid in owners}, owners)

    def test_accounts_named_like_labels_are_never_matched(self):
        """누군가 계정 이름을 'HUMAN'·'CALENDAR' 로 바꿔도 예약을 가져가지 못한다."""
        S = _sched_mod().AISchedulerService
        human = self._person('HUMAN')
        calendar = self._person('CALENDAR')
        jids = [self._row(decided_by='HUMAN', proposed_by='CALENDAR',
                          last_edited_by='human'),
                self._row(decided_by='calendar', proposed_by='Human')]
        S.backfill_job_owners()
        for jid in jids:
            self.assertIsNone(self._meta(jid).user_id)
        self.assertFalse(SchedulerJobMeta.query.filter(
            SchedulerJobMeta.user_id.in_([human.id, calendar.id])).count())

    def test_recorded_person_who_would_be_refused_is_not_assigned(self):
        """기록된 사람으로 판정이 막히면 책임자 없음으로 두고, 다음 칸의 다른
        사람으로 넘어가지도 않는다."""
        S = _sched_mod().AISchedulerService
        jid = self._row(decided_by=self.user_uuids['Monitor'],
                        proposed_by=self.user_uuids['Admin'])
        out = S.backfill_job_owners()
        self.assertGreaterEqual(out['denied'], 1)
        self.assertIsNone(self._meta(jid).user_id)
        self.assertFalse(SchedulerAuditLog.query.filter(
            SchedulerAuditLog.job_meta_id == jid,
            SchedulerAuditLog.decision == 'OWNER_BACKFILL').first())

    def test_ownerless_job_still_fires(self):
        self._scope_to_other_group()
        jid = self._row()
        _sched_mod().AISchedulerService.backfill_job_owners()
        self.assertIsNone(self._meta(jid).user_id)
        res, meta = self._fire(jid)
        self.assertEqual(res.get('status'), 'success', res)
        self.assertTrue(self._written())


class TestAssignOwner(_Owner):

    def _assign(self, who, jid, owner):
        return self._view(who, self._routes().api_assign_job_owner, jid,
                          json_body={'user_id': self.user_uuids[owner]})

    def test_only_user_managers_can_assign(self):
        jid = self._job(owner=None, state='PENDING')
        code, _ = self._assign('Editor', jid, 'Editor')
        self.assertEqual(code, 403)
        self.assertIsNone(self._meta(jid).user_id)

    def test_new_owner_must_pass_role_and_scope(self):
        self._scope_to_other_group()
        jid = self._job(owner=None, state='PENDING')
        code, body = self._assign('Admin', jid, 'Editor')
        self.assertEqual(code, 403, body)
        code, body = self._assign('Admin', jid, 'Monitor')
        self.assertEqual(code, 403, body)
        self.assertIsNone(self._meta(jid).user_id)

    def test_assign_records_and_owner_is_judged_at_fire(self):
        self._scope_to_other_group()
        self._grant_group_to('Editor')
        jid = self._job(owner=None, state='PENDING')
        code, body = self._assign('Admin', jid, 'Editor')
        self.assertEqual(code, 200, body)
        self.assertEqual(self._meta(jid).user_id, self._user('Editor').id)
        self.assertTrue(SchedulerAuditLog.query.filter(
            SchedulerAuditLog.job_meta_id == jid,
            SchedulerAuditLog.decision == 'OWNER_ASSIGNED').first())
        self.assertTrue(AuditLog.query.filter(
            AuditLog.action == 'schedule.owner_assign',
            AuditLog.target_id == str(jid)).first())
        # 이미 책임자가 있으면 이 동작으로 바꾸지 않는다.
        code, _ = self._assign('Admin', jid, 'Admin')
        self.assertEqual(code, 409)
        # 지정 뒤로는 발화마다 그 사람으로 판정한다.
        UserGroupMember.query.delete(synchronize_session=False)
        db.session.commit()
        res, meta = self._fire(jid)
        self.assertEqual(res.get('call_state'), 'refused', res)
        self.assertFalse(self._written())

    def test_scheduler_page_shows_ownerless_and_offers_assignment_to_admins(self):
        jid = self._job(owner=None, state='PENDING')
        admin = self._page_context('Admin')
        job = [j for j in admin['active_jobs'] if j.id == jid][0]
        self.assertIsNone(job.display_owner)
        self.assertTrue(admin['can_assign_owner'])
        self.assertIn(self._user('Editor').name, self._candidates(admin, jid))
        editor = self._page_context('Editor')
        self.assertFalse(editor['can_assign_owner'])
        self.assertEqual(self._candidates(editor, jid), [])
        # 템플릿이 새 값으로 문법 오류 없이 읽힌다.
        self.app.jinja_env.get_template('pages/ai/scheduler.html')


class TestOwnerMustBeAbleToCreate(_Owner):
    """책임자는 그 예약을 만들 수 있었던 사람이어야 한다.

    2026-09-23 화면 검증에서 지정 상자에 권한이 낮은 계정까지 나왔다.
    안쪽 도구가 읽기인 예약은 `job_denial` 이 누구에게나 통과시켜
    Guest·Kiosk·Monitor 도 책임자로 세울 수 있었다. 만드는 입구의 권한을
    그대로 요구한다 — 사람 작업을 포함해 모두 제어 편집(편집자 이상).
    """

    _REFUSED = ('Guest', 'Monitor', 'Kiosk')

    def _human_job(self):
        meta = SchedulerJobMeta(
            action_type='human', target_id=str(uuid.uuid4()),
            params_json=json.dumps({'content': 'check', 'worker': '',
                                    'tags': 'human_work'}),
            user_id=None, state='PENDING', reasoning=_MARK, proposed_by='AI')
        db.session.add(meta)
        db.session.commit()
        return meta.id

    def _assign(self, jid, owner_uuid):
        return self._view('Admin', self._routes().api_assign_job_owner, jid,
                          json_body={'user_id': owner_uuid})

    def _settings_only(self):
        from aot.databases.models import Role
        role = Role(name=_PREFIX + 'SettingsOnly', edit_settings=True,
                    edit_controllers=False, edit_users=False,
                    edit_plots=False, use_ai_chat=False)
        db.session.add(role)
        db.session.commit()
        u = User(name=(_PREFIX + 'SettingsOnly').lower(), role_id=role.id,
                 is_enabled=True)
        db.session.add(u)
        db.session.commit()
        return types.SimpleNamespace(id=u.id, unique_id=u.unique_id,
                                     name=u.name)

    def test_viewer_roles_are_refused_for_human_and_device_jobs(self):
        for kind, make in (('human', self._human_job), ('device', self._job)):
            for who in self._REFUSED:
                with self.subTest(kind=kind, who=who):
                    jid = make()
                    code, body = self._assign(jid, self.user_uuids[who])
                    self.assertEqual(code, 403, body)
                    self.assertIn('requires', body.get('error', ''))
                    self.assertIsNone(self._meta(jid).user_id)
                    self.assertFalse(SchedulerAuditLog.query.filter(
                        SchedulerAuditLog.job_meta_id == jid,
                        SchedulerAuditLog.decision == 'OWNER_ASSIGNED').first())

    def test_editor_is_allowed_for_human_and_device_jobs(self):
        for kind, make in (('human', self._human_job), ('device', self._job)):
            with self.subTest(kind=kind):
                jid = make()
                code, body = self._assign(jid, self.user_uuids['Editor'])
                self.assertEqual(code, 200, body)
                self.assertEqual(self._meta(jid).user_id,
                                 self._user('Editor').id)

    def _read_job(self):
        """안쪽 도구가 읽기인 예약 — `job_denial` 은 누구에게나 통과시킨다."""
        return self._job(params={'tool_name': 'get_function_list',
                                 'arguments': {}})

    def test_read_level_inner_tool_still_needs_create_permission(self):
        S = _sched_mod().AISchedulerService
        jid = self._read_job()
        meta = self._meta(jid)
        for who in self._REFUSED:
            with self.subTest(who=who):
                # 판정만으로는 막히지 않는다 — 그래서 만드는 권한을 따로 본다.
                self.assertIsNone(S.job_denial(
                    self._user(who), meta.action_type, meta.target_id,
                    json.loads(meta.params_json)))
                code, body = self._assign(jid, self.user_uuids[who])
                self.assertEqual(code, 403, body)
                self.assertIn('requires edit_controllers', body.get('error', ''))
                self.assertIsNone(self._meta(jid).user_id)

    def test_settings_only_person_is_neither_listed_nor_assigned(self):
        """설정 편집만 있는 사람 — 사람 작업도 편집자 이상만 만들 수 있으므로
        (2026-09-23 결정) 어느 예약의 책임자 후보에도 나오지 않고 지정도
        거부된다."""
        person = self._settings_only()
        human = self._human_job()
        device = self._job()
        admin = self._page_context('Admin')
        self.assertNotIn(person.name, self._candidates(admin, human))
        self.assertNotIn(person.name, self._candidates(admin, device))
        for jid in (human, device):
            code, body = self._assign(jid, person.unique_id)
            self.assertEqual(code, 403, body)
            self.assertIsNone(self._meta(jid).user_id)

    def test_picker_lists_only_people_who_could_create_the_job(self):
        human = self._human_job()
        device = self._job()
        read = self._read_job()
        admin = self._page_context('Admin')
        for jid in (human, device, read):
            names = self._candidates(admin, jid)
            with self.subTest(job=jid):
                for who in self._REFUSED:
                    self.assertNotIn(self._user(who).name, names)
                for who in ('Admin', 'Editor', 'ControlOnly'):
                    self.assertIn(self._user(who).name, names)

    def test_backfill_does_not_make_a_viewer_the_owner(self):
        S = _sched_mod().AISchedulerService
        jids = {}
        for who in self._REFUSED + ('Editor',):
            jid = self._human_job()
            meta = self._meta(jid)
            meta.proposed_by = self.user_uuids[who]
            db.session.commit()
            jids[who] = jid
        out = S.backfill_job_owners()
        self.assertGreaterEqual(out['denied'], len(self._REFUSED))
        for who in self._REFUSED:
            self.assertIsNone(self._meta(jids[who]).user_id, who)
        self.assertEqual(self._meta(jids['Editor']).user_id,
                         self._user('Editor').id)
