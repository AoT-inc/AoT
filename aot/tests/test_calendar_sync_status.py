# coding=utf-8
"""달력 동기화의 막힘 표시·취소 보류, 노트 태그 이름 바꾸기의 그룹 범위.

정본 설계: `docs/design/access-scope-groups.md` §6-2a(후속 결정 2026-09-24)

1. 가져오기가 막혀도 연결 상태가 'ok' 로 남아 화면에 아무것도 안 보였다 —
   이제 `no_permission`·`partial` 과 막힌 수·사유가 연결에 남는다.
2. 구글 쪽 취소가 그룹 범위로 막히면 링크를 지워 양쪽이 조용히 어긋났다 —
   이제 링크를 남기고(`sync_state`) 다음 동기화가 다시 판정한다.
3. 태그 이름 바꾸기는 그 태그를 단 모든 노트의 대상에 쓸 수 있어야 한다.
"""
import importlib.util
import os
import types
from datetime import datetime
from unittest import mock

import flask_login

from aot.aot_flask.extensions import db
from aot.databases.models import Notes, NoteTags
from aot.databases.models.calendar_integration import (CalendarEventLink,
                                                       UserCalendarConnection)
from aot.tests.test_mcp_record_write_guard import _NOTE_MARK, _PREFIX
from aot.tests.test_note_and_calendar_write_guard import _Calendar

_P6_76 = 'p6_76_calendar_sync_status_20260924'


class TestPullOutcomeRecording(_Calendar):

    def _sync(self, who, pull_result, enabled=True):
        """`sync_connection` 을 돌리되 구글·토큰은 흉내 낸다."""
        svc = self._svc()
        conn_id = self._conn(who)
        conn = UserCalendarConnection.query.get(conn_id)
        conn.push_enabled = False
        db.session.commit()
        self._clear_scope_cache()
        patches = [
            mock.patch.object(svc.google_oauth, 'is_configured',
                              return_value=True),
            mock.patch.object(svc, 'get_valid_access_token',
                              return_value='token'),
            mock.patch.object(svc, 'ensure_category_calendars',
                              return_value={'user': {'calendar_id': 'cal-user'}}),
        ]
        if pull_result is not None:
            patches.append(mock.patch.object(svc, 'pull_connection',
                                             return_value=pull_result))
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        svc.sync_connection(conn_id)
        db.session.remove()
        return UserCalendarConnection.query.get(conn_id)

    def test_view_only_owner_is_recorded_as_no_permission(self):
        conn = self._sync('Guest', None)
        self.assertEqual(conn.last_sync_status, 'no_permission')
        self.assertIsNone(conn.last_sync_refused)
        self.assertIsNotNone(conn.last_synced_at)

    def test_refused_events_are_recorded_as_partial_with_count_and_reason(self):
        conn = self._sync('Editor', {'refused': 3, 'imported': 1,
                                     'refused_reason': 'out of group'})
        self.assertEqual(conn.last_sync_status, 'partial')
        self.assertEqual(conn.last_sync_refused, 3)
        self.assertEqual(conn.last_sync_error, 'out of group')

    def test_a_clean_run_clears_the_earlier_warning(self):
        conn_id = self._conn('Editor')
        conn = UserCalendarConnection.query.get(conn_id)
        conn.last_sync_status = 'partial'
        conn.last_sync_refused = 2
        conn.last_sync_error = 'old'
        db.session.commit()
        self._svc()._record_pull_outcome(conn, {'imported': 1, 'refused': 0})
        self.assertEqual(conn.last_sync_status, 'ok')
        self.assertIsNone(conn.last_sync_refused)
        self.assertIsNone(conn.last_sync_error)

    def test_templates_compile(self):
        for name in ('settings/integrations.html', 'layout.html',
                     'layout_default.html'):
            self.app.jinja_env.get_template(name)

    def test_real_pull_reports_the_reason_of_a_refused_import(self):
        self._scope_map()
        conn_id = self._conn()
        stats = self._pull(conn_id, [self._event('ev-z',
                                                 location=self.zone_name)])
        self.assertEqual(stats.get('refused'), 1, stats)
        self.assertTrue(stats.get('refused_reason'), stats)


class TestHeldCancellation(_Calendar):

    def _link(self, jid):
        db.session.remove()
        return CalendarEventLink.query.filter_by(job_id=jid).first()

    def test_refused_cancel_keeps_the_link_and_marks_it(self):
        self._scope_map()
        conn = self._conn()
        jid = self._linked_job(conn, 'ev-held', self.zone)
        stats = self._pull(conn, [{'id': 'ev-held', 'status': 'cancelled'}])
        self.assertEqual((stats.get('refused'), stats.get('cancelled')), (1, 0))
        self.assertEqual(self._job(jid).state, 'PENDING')
        link = self._link(jid)
        self.assertIsNotNone(link)
        self.assertEqual(link.sync_state, 'cancel_refused')

    def test_next_sync_retries_and_still_counts_while_blocked(self):
        self._scope_map()
        conn = self._conn()
        jid = self._linked_job(conn, 'ev-held', self.zone)
        self._pull(conn, [{'id': 'ev-held', 'status': 'cancelled'}])
        # 증분 동기화는 취소를 다시 알려 주지 않는다 — 빈 결과.
        stats = self._pull(conn, [])
        self.assertEqual((stats.get('refused'), stats.get('cancelled')), (1, 0))
        self.assertEqual(self._link(jid).sync_state, 'cancel_refused')

    def test_retry_archives_once_the_owner_is_in_scope(self):
        self._scope_map()
        conn = self._conn()
        jid = self._linked_job(conn, 'ev-held', self.zone)
        self._pull(conn, [{'id': 'ev-held', 'status': 'cancelled'}])
        self._grant_group_to('Editor')
        stats = self._pull(conn, [])
        self.assertEqual((stats.get('refused'), stats.get('cancelled')), (0, 1),
                         stats)
        self.assertEqual(self._job(jid).state, 'ARCHIVED')
        self.assertIsNone(self._link(jid))

    def test_event_restored_in_google_clears_the_mark(self):
        self._scope_map()
        conn = self._conn()
        jid = self._linked_job(conn, 'ev-held', self.zone)
        self._pull(conn, [{'id': 'ev-held', 'status': 'cancelled'}])
        self._pull(conn, [self._event('ev-held', updated='2000-01-01T00:00:00Z')])
        self.assertIsNone(self._link(jid).sync_state)

    def test_push_leaves_a_held_link_alone(self):
        svc = self._svc()
        self._scope_map()
        conn_id = self._conn()
        jid = self._linked_job(conn_id, 'ev-held', self.zone, origin='aot')
        link = CalendarEventLink.query.filter_by(job_id=jid).first()
        link.sync_state = 'cancel_refused'
        job = SchedulerJobMeta_get(jid)
        job.source_type = None
        db.session.commit()
        conn = UserCalendarConnection.query.get(conn_id)
        with mock.patch.object(svc.google_calendar_api, 'update_event') as upd, \
                mock.patch.object(svc.google_calendar_api, 'insert_event') as ins, \
                mock.patch.object(svc.google_calendar_api, 'delete_event') as dele:
            svc.push_connection(conn, 'token', {'user': {'calendar_id': 'cal-user'},
                                                'device': {'calendar_id': 'c2'},
                                                'ai': {'calendar_id': 'c3'}})
        self.assertFalse(upd.called or ins.called or dele.called)


def SchedulerJobMeta_get(jid):
    from aot.databases.models import SchedulerJobMeta
    return SchedulerJobMeta.query.get(jid)


class TestTagRenameScope(_Calendar):

    def setUp(self):
        super().setUp()
        self.tag = NoteTags(name=_PREFIX + 'tag' + self.zone[:6])
        db.session.add(self.tag)
        db.session.commit()
        self.addCleanup(self._drop_tag)

    def _drop_tag(self):
        db.session.rollback()
        NoteTags.query.filter_by(unique_id=self.tag.unique_id).delete()
        db.session.commit()

    def _note_with_tag(self, target):
        db.session.add(Notes(name=_PREFIX, note=_NOTE_MARK + ' tag',
                             target_id=target, tags=self.tag.unique_id))
        db.session.commit()

    def _rename(self, who, new):
        from aot.aot_flask.utils import utils_notes
        form = types.SimpleNamespace(
            tag_unique_id=types.SimpleNamespace(data=self.tag.unique_id),
            rename=types.SimpleNamespace(data=new))
        self._clear_scope_cache()
        with self.app.test_request_context('/notes', method='POST'):
            flask_login.login_user(self._user(who))
            utils_notes.tag_rename(form)
        db.session.remove()
        return NoteTags.query.filter_by(unique_id=self.tag.unique_id).first().name

    def test_rename_is_refused_when_any_tagged_note_is_out_of_scope(self):
        self._scope_map()
        self._note_with_tag(self.zone)
        self._note_with_tag(None)
        old = self.tag.name
        self.assertEqual(self._rename('Editor', 'renamed_x'), old)

    def test_rename_passes_in_scope_and_for_untargeted_tags(self):
        self._scope_map()
        self._note_with_tag(None)
        self.assertEqual(self._rename('Editor', 'renamed_a'), 'renamed_a')
        self._note_with_tag(self.zone)
        self._grant_group_to('Editor')
        self.assertEqual(self._rename('Editor', 'renamed_b'), 'renamed_b')

    def test_rename_is_unchanged_on_an_install_without_groups(self):
        self._note_with_tag(self.zone)
        self.assertEqual(self._rename('Editor', 'renamed_c'), 'renamed_c')


# ---------------------------------------------------------------------------
# 마이그레이션 p6_76
# ---------------------------------------------------------------------------

def _load_p6_76():
    here = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(here, '..', '..', 'alembic_db', 'alembic', 'versions',
                        _P6_76 + '.py')
    spec = importlib.util.spec_from_file_location(_P6_76, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _run(mod, fn, engine):
    from alembic.operations import Operations
    from alembic.runtime.migration import MigrationContext
    with engine.begin() as conn:
        with Operations.context(MigrationContext.configure(conn)):
            getattr(mod, fn)()


def test_p6_76_is_the_head_the_app_expects():
    from aot.config import ALEMBIC_VERSION
    mod = _load_p6_76()
    assert mod.revision == ALEMBIC_VERSION == _P6_76
    assert mod.down_revision == 'p6_75_api_key_tool_profile_20260924'


def test_p6_76_upgrade_downgrade_is_idempotent(tmp_path):
    import sqlalchemy as sa
    engine = sa.create_engine('sqlite:///%s' % (tmp_path / 'mig.db'))
    with engine.begin() as conn:
        conn.execute(sa.text(
            "CREATE TABLE user_calendar_connection (id INTEGER PRIMARY KEY, "
            "last_sync_status VARCHAR(16))"))
        conn.execute(sa.text(
            "CREATE TABLE calendar_event_link (id INTEGER PRIMARY KEY, "
            "origin VARCHAR(8))"))
        conn.execute(sa.text(
            "INSERT INTO user_calendar_connection (last_sync_status) "
            "VALUES ('ok')"))

    def cols(table):
        return {c['name'] for c in sa.inspect(engine).get_columns(table)}

    mod = _load_p6_76()
    _run(mod, 'upgrade', engine)
    _run(mod, 'upgrade', engine)        # 두 번 돌려도 같다
    assert 'last_sync_refused' in cols('user_calendar_connection')
    assert 'sync_state' in cols('calendar_event_link')
    with engine.connect() as conn:
        row = conn.execute(sa.text(
            "SELECT last_sync_status, last_sync_refused "
            "FROM user_calendar_connection")).one()
    assert tuple(row) == ('ok', None)
    _run(mod, 'downgrade', engine)
    _run(mod, 'downgrade', engine)
    assert 'last_sync_refused' not in cols('user_calendar_connection')
    assert 'sync_state' not in cols('calendar_event_link')


# ---------------------------------------------------------------------------
# 화면 — 템플릿이 컴파일되고 새 상태를 그린다
# ---------------------------------------------------------------------------
