# coding=utf-8
"""노트 고치기·지도 숨김, 구글 달력 가져오기 — 역할·그룹 스코프·CSRF.

정본 설계: `docs/design/access-scope-groups.md` §6-2a(후속 검토 2026-09-24)

1. `/notes/update/<id>`·`/notes/toggle_map_visibility` 는 로그인만 봤다 —
   Guest·Kiosk·Monitor 가 노트 이름·본문을 이력 없이 덮어쓰고 지도에서 숨겼다.
   CSRF 도 면제였다. 이제 웹 노트 고치기와 같은 `edit_settings`, 숨김은 대상
   스코프까지 보고, CSRF 토큰을 요구한다.
2. 구글 달력 가져오기는 신원을 묶지 않아 쓰기 시점 강제가 "사람이 없는 호출"
   로 면제했다. 이제 연결 주인으로 묶고 일정마다 판정한다 — 막힌 일정만
   건너뛴다. 다시 연결은 고치기 전·뒤 대상 둘 다 본다. 연결 시작과 "지금
   동기화" 는 편집자만.
"""
import json
from datetime import datetime
from unittest import mock

import flask_login

from aot.aot_flask.access import scope
from aot.aot_flask.extensions import db
from aot.databases.models import Notes, NoteTags, SchedulerJobMeta
from aot.databases.models.calendar_integration import (CalendarEventLink,
                                                       UserCalendarConnection)
from aot.tests.test_mcp_record_write_guard import _NOTE_MARK, _PREFIX
from aot.tests.test_write_scope_zone import _Zone

_MARK = 'cal-guard-test'
_VIEW_ONLY = ('Monitor', 'Guest', 'Kiosk')


# ---------------------------------------------------------------------------
# 1. 노트 고치기·지도 숨김
# ---------------------------------------------------------------------------

class TestNoteUpdateAndHide(_Zone):

    def _api(self):
        from aot.aot_flask import routes_notes_api
        return routes_notes_api

    def _make_note(self, target=None):
        n = Notes(name=_PREFIX, note=_NOTE_MARK + ' guard', target_id=target,
                  target_type='zone' if target else None)
        db.session.add(n)
        db.session.commit()
        return n.unique_id

    def _row(self, nid):
        db.session.remove()
        return Notes.query.filter_by(unique_id=nid).first()

    def _hidden(self, nid):
        tag = NoteTags.query.filter_by(name='map_hidden').first()
        row = self._row(nid)
        return bool(tag and tag.unique_id in (row.tags or '').split(','))

    def test_view_only_roles_cannot_rename_or_hide(self):
        R = self._api()
        nid = self._make_note()
        for who in _VIEW_ONLY:
            with self.subTest(who=who):
                code, _ = self._view(who, R.api_notes_update, nid,
                                     json_body={'name': 'hijack',
                                                'note': 'overwritten'})
                self.assertEqual(code, 403)
                code, _ = self._view(who, R.api_notes_toggle_map_visibility,
                                     json_body={'unique_id': nid,
                                                'visible': False})
                self.assertEqual(code, 403)
        row = self._row(nid)
        self.assertEqual(row.name, _PREFIX)
        self.assertTrue(row.note.startswith(_NOTE_MARK))
        self.assertFalse(self._hidden(nid))

    def test_editor_can_rename_and_hide(self):
        R = self._api()
        nid = self._make_note()
        code, body = self._view('Editor', R.api_notes_update, nid,
                                json_body={'name': _PREFIX + 'renamed'})
        self.assertEqual(code, 200, body)
        code, body = self._view('Editor', R.api_notes_toggle_map_visibility,
                                json_body={'unique_id': nid, 'visible': False})
        self.assertEqual(code, 200, body)
        self.assertEqual(self._row(nid).name, _PREFIX + 'renamed')
        self.assertTrue(self._hidden(nid))

    def test_hiding_a_note_on_an_out_of_scope_zone_is_refused(self):
        self._scope_map()
        R = self._api()
        nid = self._make_note(self.zone)
        code, body = self._view('Editor', R.api_notes_toggle_map_visibility,
                                json_body={'unique_id': nid, 'visible': False})
        self.assertEqual(code, 403)
        self.assertEqual(body.get('error'), scope.deny_message())
        self.assertFalse(self._hidden(nid))
        # 그룹에 들면 된다.
        self._grant_group_to('Editor')
        code, body = self._view('Editor', R.api_notes_toggle_map_visibility,
                                json_body={'unique_id': nid, 'visible': False})
        self.assertEqual(code, 200, body)
        self.assertTrue(self._hidden(nid))

    # -- CSRF ---------------------------------------------------------------

    def _client_as(self, who):
        client = self.app.test_client()
        self._clear_scope_cache()
        with client.session_transaction() as sess:
            sess['_user_id'] = self._user(who).get_id()
            sess['_fresh'] = True
        return client

    def _csrf_on(self):
        self.app.config['WTF_CSRF_ENABLED'] = True
        self.addCleanup(self.app.config.__setitem__, 'WTF_CSRF_ENABLED', False)

    def _token_for(self, client):
        from flask import session
        from flask_wtf.csrf import generate_csrf
        with self.app.test_request_context('/'):
            token = generate_csrf()
            raw = session['csrf_token']
        with client.session_transaction() as sess:
            sess['csrf_token'] = raw
        return token

    def test_routes_are_not_csrf_exempt(self):
        from aot.aot_flask.extensions import csrf
        exempt = getattr(csrf, '_exempt_views', set())
        for name in ('api_notes_update', 'api_notes_toggle_map_visibility'):
            self.assertNotIn('aot.aot_flask.routes_notes_api.' + name, exempt)

    def test_post_without_a_token_is_rejected_and_writes_nothing(self):
        self._csrf_on()
        nid = self._make_note()
        client = self._client_as('Editor')
        resp = client.post('/notes/update/' + nid,
                           json={'name': _PREFIX + 'csrf'})
        self.assertEqual(resp.status_code, 400)
        resp = client.post('/notes/toggle_map_visibility',
                           json={'unique_id': nid, 'visible': False})
        self.assertEqual(resp.status_code, 400)
        # 단순 폼 전송(교차 사이트가 보낼 수 있는 모양)도 막힌다 — 앱의 CSRF
        # 오류 처리기가 JSON 이 아닌 요청은 안내와 함께 되돌려 보낸다(302).
        resp = client.post('/notes/update/' + nid,
                           data={'name': _PREFIX + 'form'})
        self.assertIn(resp.status_code, (400, 302))
        self.assertEqual(self._row(nid).name, _PREFIX)
        self.assertFalse(self._hidden(nid))

    def test_post_with_the_header_token_goes_through(self):
        self._csrf_on()
        nid = self._make_note()
        client = self._client_as('Editor')
        token = self._token_for(client)
        resp = client.post('/notes/update/' + nid,
                           json={'name': _PREFIX + 'ok'},
                           headers={'X-CSRFToken': token})
        self.assertEqual(resp.status_code, 200, resp.get_data(as_text=True))
        self._clear_scope_cache()
        resp = client.post('/notes/toggle_map_visibility',
                           json={'unique_id': nid, 'visible': False},
                           headers={'X-CSRFToken': token})
        self.assertEqual(resp.status_code, 200, resp.get_data(as_text=True))
        self.assertEqual(self._row(nid).name, _PREFIX + 'ok')
        self.assertTrue(self._hidden(nid))


# ---------------------------------------------------------------------------
# 2. 구글 달력 가져오기
# ---------------------------------------------------------------------------

class _Calendar(_Zone):

    def setUp(self):
        super().setUp()
        self._conns = []

    def tearDown(self):
        # 사용자 행보다 먼저 치운다(연결은 users.id 를 가리킨다).
        db.session.rollback()
        if self._conns:
            CalendarEventLink.query.filter(
                CalendarEventLink.connection_id.in_(self._conns)).delete(
                    synchronize_session=False)
            UserCalendarConnection.query.filter(
                UserCalendarConnection.id.in_(self._conns)).delete(
                    synchronize_session=False)
        SchedulerJobMeta.query.filter(
            SchedulerJobMeta.reasoning.like('%' + _MARK + '%')
            | SchedulerJobMeta.params_json.like('%' + _MARK + '%')).delete(
                synchronize_session=False)
        db.session.commit()
        super().tearDown()

    def _svc(self):
        from aot.ai.services import calendar_sync_service
        return calendar_sync_service

    def _conn(self, who='Editor'):
        conn = UserCalendarConnection(
            user_id=self._user(who).id, provider='google', is_active=True,
            push_enabled=False, pull_enabled=True,
            category_calendars={'user': {'calendar_id': 'cal-user'}})
        db.session.add(conn)
        db.session.commit()
        self._conns.append(conn.id)
        return conn.id

    @staticmethod
    def _event(eid, location=None, summary=None, updated='2030-01-02T00:00:00Z'):
        desc = ('장소: %s' % location) if location else ''
        return {'id': eid, 'status': 'confirmed', 'updated': updated,
                'summary': summary or (_MARK + ' task'), 'description': desc,
                'start': {'dateTime': '2030-01-03T09:00:00Z'},
                'end': {'dateTime': '2030-01-03T10:00:00Z'}}

    def _pull(self, conn_id, events):
        svc = self._svc()
        self._clear_scope_cache()
        with mock.patch.object(svc.google_calendar_api, 'list_events',
                               return_value=({'items': events,
                                              'nextSyncToken': 'tok'}, None)):
            conn = UserCalendarConnection.query.get(conn_id)
            return svc.pull_connection(conn, 'token', conn.category_calendars)

    def _jobs(self):
        db.session.remove()
        return SchedulerJobMeta.query.filter(
            SchedulerJobMeta.source_type == 'google_calendar',
            SchedulerJobMeta.params_json.like('%' + _MARK + '%')).all()

    def _linked_job(self, conn_id, eid, target_id, origin='google'):
        job = SchedulerJobMeta(
            source_type='google_calendar', action_type='human',
            target_id=target_id,
            params_json=json.dumps({'content': _MARK + ' before'}),
            schedule_time=datetime(2030, 1, 1, 9), proposed_by='HUMAN',
            reasoning=_MARK, state='PENDING', user_id=self._user('Editor').id)
        db.session.add(job)
        db.session.flush()
        db.session.add(CalendarEventLink(
            connection_id=conn_id, job_id=job.id, google_event_id=eid,
            google_calendar_id='cal-user', origin=origin,
            last_synced_at=datetime(2029, 1, 1)))
        db.session.commit()
        return job.id

    def _job(self, jid):
        db.session.remove()
        return SchedulerJobMeta.query.get(jid)


class TestCalendarImportScope(_Calendar):

    def test_import_into_an_out_of_scope_zone_is_skipped_not_failed(self):
        self._scope_map()
        conn = self._conn()
        stats = self._pull(conn, [
            self._event('ev-zone', location=self.zone_name),
            self._event('ev-free', summary=_MARK + ' floating')])
        self.assertEqual(stats.get('refused'), 1, stats)
        self.assertEqual(stats.get('imported'), 1, stats)
        jobs = self._jobs()
        self.assertEqual([j.target_id for j in jobs], ['none'])
        self.assertEqual(jobs[0].user_id, self._user('Editor').id)

    def test_import_into_the_zone_works_once_in_the_group(self):
        self._scope_map()
        self._grant_group_to('Editor')
        conn = self._conn()
        stats = self._pull(conn, [self._event('ev-zone',
                                              location=self.zone_name)])
        self.assertEqual((stats.get('refused'), stats.get('imported')), (0, 1),
                         stats)
        self.assertEqual([j.target_id for j in self._jobs()], [self.zone])

    def test_import_is_bound_to_the_owner(self):
        from aot.ai import ai_request_context as ctx
        from aot.aot_flask.access import write_scope
        svc = self._svc()
        seen = []
        real = svc._process_pulled_event

        def spy(*a, **kw):
            p = write_scope.current()
            rq = ctx.get_requester()
            seen.append((p.user_uuid if p else None,
                         rq.user_uuid if rq else None))
            return real(*a, **kw)

        conn = self._conn()
        with mock.patch.object(svc, '_process_pulled_event', side_effect=spy):
            self._pull(conn, [self._event('ev-bound')])
        uid = self.user_uuids['Editor']
        self.assertEqual(seen, [(uid, uid)])
        self.assertIsNone(write_scope.current())
        self.assertIsNone(ctx.get_requester())

    def test_view_only_owner_imports_nothing(self):
        for who in _VIEW_ONLY:
            with self.subTest(who=who):
                conn = self._conn(who)
                stats = self._pull(conn, [self._event('ev-' + who)])
                self.assertEqual(stats.get('skipped'), 'permission')
        self.assertEqual(self._jobs(), [])

    def test_relink_onto_an_out_of_scope_zone_is_refused(self):
        self._scope_map()
        conn = self._conn()
        jid = self._linked_job(conn, 'ev-relink', 'none')
        stats = self._pull(conn, [self._event('ev-relink',
                                              location=self.zone_name,
                                              summary=_MARK + ' after')])
        self.assertEqual(stats.get('refused'), 1, stats)
        job = self._job(jid)
        self.assertEqual(job.target_id, 'none')
        self.assertIn('before', json.loads(job.params_json)['content'])
        self.assertEqual(job.schedule_time, datetime(2030, 1, 1, 9))

    def test_editing_a_job_already_on_an_out_of_scope_zone_is_refused(self):
        """고친 뒤 대상만 보면 지나가는 편집 — 그룹 밖 예약의 시각·내용."""
        self._scope_map()
        conn = self._conn()
        jid = self._linked_job(conn, 'ev-old', self.zone)
        stats = self._pull(conn, [self._event('ev-old',
                                              summary=_MARK + ' after')])
        self.assertEqual(stats.get('refused'), 1, stats)
        job = self._job(jid)
        self.assertEqual(job.schedule_time, datetime(2030, 1, 1, 9))
        self.assertIn('before', json.loads(job.params_json)['content'])

    def test_cancelling_an_out_of_scope_job_does_not_archive_it(self):
        self._scope_map()
        conn = self._conn()
        jid = self._linked_job(conn, 'ev-cancel', self.zone)
        stats = self._pull(conn, [{'id': 'ev-cancel', 'status': 'cancelled'}])
        self.assertEqual((stats.get('refused'), stats.get('cancelled')), (1, 0))
        self.assertEqual(self._job(jid).state, 'PENDING')

    def test_in_scope_relink_and_cancel_still_work(self):
        self._scope_map()
        self._grant_group_to('Editor')
        conn = self._conn()
        jid = self._linked_job(conn, 'ev-ok', 'none')
        stats = self._pull(conn, [self._event('ev-ok', location=self.zone_name,
                                              summary=_MARK + ' after')])
        self.assertEqual((stats.get('refused'), stats.get('updated')), (0, 1),
                         stats)
        self.assertEqual(self._job(jid).target_id, self.zone)
        stats = self._pull(conn, [{'id': 'ev-ok', 'status': 'cancelled'}])
        self.assertEqual(stats.get('cancelled'), 1, stats)


class TestCalendarRoutes(_Calendar):

    def _routes(self):
        from aot.aot_flask import routes_integrations
        return routes_integrations

    def _start(self, who):
        R = self._routes()
        with mock.patch.object(R.google_oauth, 'is_configured',
                               return_value=True), \
                mock.patch.object(R.google_oauth, 'build_consent_url',
                                  return_value='https://consent.invalid/x') as b:
            self._clear_scope_cache()
            with self.app.test_request_context('/oauth/google/start'):
                flask_login.login_user(self._user(who))
                resp = R.oauth_google_start()
        return resp, b.called

    def test_connect_is_editor_only(self):
        for who in _VIEW_ONLY:
            with self.subTest(who=who):
                resp, built = self._start(who)
                self.assertFalse(built)
                self.assertNotIn('consent.invalid', resp.location)
        resp, built = self._start('Editor')
        self.assertTrue(built)
        self.assertEqual(resp.location, 'https://consent.invalid/x')

    def _sync_now(self, who):
        from flask import get_flashed_messages
        R = self._routes()
        from aot.ai.services import calendar_sync_service as svc
        with mock.patch.object(svc, 'sync_connection',
                               return_value={'pull': {'refused': 2}}) as run:
            self._clear_scope_cache()
            with self.app.test_request_context(
                    '/settings/integrations/sync', method='POST'):
                flask_login.login_user(self._user(who))
                R.oauth_google_sync_now()
                flashed = get_flashed_messages(with_categories=True)
        return run.called, flashed

    def test_sync_now_is_editor_only_and_reports_skipped_events(self):
        for who in _VIEW_ONLY:
            with self.subTest(who=who):
                self._conn(who)
                called, _ = self._sync_now(who)
                self.assertFalse(called)
        self._conn('Editor')
        called, flashed = self._sync_now('Editor')
        self.assertTrue(called)
        self.assertIn('warning', [c for c, _m in flashed])
