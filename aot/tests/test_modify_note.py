# coding=utf-8
"""노트 수정·보관 도구(modify_note)와 작성자 기록 (G6, 2026-10-13).

고정하는 계약:

  1. `create_note` 는 연결된 사용자를 `Notes.user_id` 에 남긴다(모르면 비움).
  2. `modify_note` 는 이름·본문·태그를 고치고, `archive=true|false` 로 보관·복원한다.
     완전 삭제는 하지 않는다.
  3. 본인이 쓴 노트(또는 작성자 기록이 없는, 사용자 요청으로 AI 가 만든 노트)는
     승인 없이, 남의 노트·작성자 불명 노트는 승인 대기로 간다.
  4. 권한은 기록 쓰기와 같다(edit_settings, 읽기 전용 키 거부).
  5. 바꾸기 전 이름·본문·태그가 감사 로그(before_json)에 남는다.
  6. 서랍 단계의 쓰기 도구로 등록된다.
"""
import json
import unittest

from aot.aot_flask.extensions import db
from aot.databases.models import AuditLog, MCPConfirmation, Notes
from aot.tests import test_mcp_record_write_guard as rw
from aot.tools import mcp_safety_gate as gate
from aot.tools import tool_registry as R

_MARK = rw._NOTE_MARK


class TestRegistration(unittest.TestCase):

    def test_modify_note_is_a_record_write_in_the_drawer(self):
        self.assertIn('modify_note', R.record_write_tools())
        self.assertIn('modify_note', R.write_tools())
        self.assertEqual(gate.classify_permission('modify_note'), 'write')
        self.assertEqual(gate.required_write_permission('modify_note'),
                         'edit_settings')
        self.assertEqual(R.tier_of('modify_note')[:2], ('record', 'drawer'))
        self.assertIn('modify_note', gate.CONDITIONAL_APPROVAL_TOOLS)

    def test_search_notes_points_at_it(self):
        desc = [p for p in R._MCP_TOOL_PAYLOADS
                if p['tool_name'] == 'search_notes'][0]['description']
        self.assertIn('modify_note', desc)


class _NoteFixture(rw._Fixture):

    def setUp(self):
        super().setUp()
        self._audit_targets = []

    def tearDown(self):
        try:
            db.session.rollback()
            if self._audit_targets:
                AuditLog.query.filter(
                    AuditLog.target_id.in_(self._audit_targets)).delete(
                    synchronize_session=False)
                db.session.commit()
        finally:
            super().tearDown()

    def _make(self, who='Editor', **extra):
        """who 가 create_note 로 만든 노트의 id."""
        body = self._call('create_note', self._note_args(**extra),
                          self._role(who),
                          scope_user_uuid=self.user_uuids[who])
        self.assertEqual(body.get('status'), 'created', body)
        self._audit_targets.append(body['note_id'])
        return body['note_id']

    def _row(self, note_id):
        db.session.remove()
        return Notes.query.filter_by(unique_id=note_id).first()

    def _modify(self, who, note_id, **args):
        return self._call('modify_note', dict(args, note_id=note_id),
                          self._role(who),
                          scope_user_uuid=self.user_uuids[who])

    def _audit_rows(self, note_id):
        db.session.remove()
        return AuditLog.query.filter_by(action='note.modify',
                                        target_id=note_id).all()


class TestAuthorRecorded(_NoteFixture):

    def test_create_note_records_the_connected_user(self):
        nid = self._make('Editor')
        self.assertEqual(self._row(nid).user_id, self._user('Editor').id)

    def test_create_note_without_a_known_user_leaves_it_empty(self):
        body = self._call('create_note', self._note_args(), self._role('Editor'))
        self._audit_targets.append(body['note_id'])
        self.assertIsNone(self._row(body['note_id']).user_id)


class TestModifyOwnNote(_NoteFixture):

    def test_edit_without_approval_and_audit_keeps_previous_values(self):
        nid = self._make('Editor', name='처음 이름')
        before = self._row(nid)
        old_note = before.note
        body = self._modify('Editor', nid, name='바뀐 이름',
                            note=_MARK + ' 바뀐 본문')
        self.assertEqual(body.get('call_state'), 'executed', body)
        self.assertEqual(body.get('status'), 'modified', body)
        self.assertEqual(sorted(body['changed']), ['name', 'note'])
        row = self._row(nid)
        self.assertEqual((row.name, row.note), ('바뀐 이름', _MARK + ' 바뀐 본문'))
        db.session.remove()
        self.assertEqual(self._mine_confirmations().count(), 0)
        self.assertEqual(self._last_audit().confirmation_status, 'not_required')
        rows = self._audit_rows(nid)
        self.assertEqual(len(rows), 1)
        prev = json.loads(rows[0].before_json)
        self.assertEqual((prev['name'], prev['note']), ('처음 이름', old_note))
        self.assertEqual(json.loads(rows[0].after_json)['name'], '바뀐 이름')

    def test_archive_and_restore(self):
        nid = self._make('Editor')
        body = self._modify('Editor', nid, archive=True)
        self.assertEqual(body.get('status'), 'archived', body)
        self.assertTrue(self._row(nid).is_archived)
        body = self._modify('Editor', nid, archive=False)
        self.assertEqual(body.get('status'), 'restored', body)
        self.assertFalse(self._row(nid).is_archived)
        self.assertEqual(len(self._audit_rows(nid)), 2)
        # 완전 삭제는 하지 않는다 — 행이 그대로 있다.
        self.assertIsNotNone(self._row(nid))

    def test_nothing_to_change_and_unknown_note_are_errors(self):
        nid = self._make('Editor')
        body = self._modify('Editor', nid)
        self.assertIn('nothing to change', json.dumps(body))
        body = self._modify('Editor', 'no-such-note', name='x')
        self.assertIn('not found', json.dumps(body))
        self.assertEqual(self._audit_rows(nid), [])

    def test_ai_note_without_recorded_author_goes_straight_through(self):
        """작성자 기록이 생기기 전의 사용자 요청 AI 노트."""
        nid = self._make('Editor')
        row = self._row(nid)
        row.user_id = None
        row.context_state = 'user_requested'
        db.session.commit()
        body = self._modify('Admin', nid, name='새 이름')
        self.assertEqual(body.get('status'), 'modified', body)


class TestSomeoneElsesNote(_NoteFixture):

    def test_other_users_note_waits_for_approval(self):
        nid = self._make('Admin', name='관리자 노트')
        body = self._modify('Editor', nid, name='남이 바꿈')
        self.assertEqual(body.get('status'), 'pending_approval', body)
        self.assertEqual(self._row(nid).name, '관리자 노트')
        self.assertEqual(self._last_audit().confirmation_status, 'pending')
        db.session.remove()
        self.assertEqual(self._mine_confirmations().count(), 1)

    def test_author_unknown_note_waits_for_approval(self):
        nid = self._make('Editor')
        row = self._row(nid)
        row.user_id = None
        row.context_state = 'system_generated'      # 웹·시스템이 만든 옛 노트
        db.session.commit()
        body = self._modify('Editor', nid, archive=True)
        self.assertEqual(body.get('status'), 'pending_approval', body)
        self.assertFalse(self._row(nid).is_archived)

    def test_other_users_ai_note_is_conservatively_queued(self):
        nid = self._make('Admin')           # context_state 는 user_requested
        self.assertEqual(self._row(nid).context_state, 'user_requested')
        body = self._modify('Editor', nid, name='x')
        self.assertEqual(body.get('status'), 'pending_approval', body)

    def test_approved_request_runs_and_audit_keeps_previous_values(self):
        nid = self._make('Admin', name='관리자 노트')
        body = self._modify('Editor', nid, name='승인 후 이름')
        cid = body['confirmation_id']
        row = MCPConfirmation.query.filter_by(unique_id=cid).first()
        row.status = 'approved'
        row.user_id = self.user_uuids['Admin']
        row.save()
        status, result = gate.execute_approved(cid)
        self.assertEqual(status, 'executed', result)
        self.assertEqual(self._row(nid).name, '승인 후 이름')
        prev = json.loads(self._audit_rows(nid)[0].before_json)
        self.assertEqual(prev['name'], '관리자 노트')

    def test_retry_with_approved_confirmation_id_executes(self):
        nid = self._make('Admin', name='관리자 노트')
        body = self._modify('Editor', nid, name='재호출 이름')
        cid = body['confirmation_id']
        row = MCPConfirmation.query.filter_by(unique_id=cid).first()
        row.status = 'approved'
        row.user_id = self.user_uuids['Admin']
        row.save()
        body = self._modify('Editor', nid, name='재호출 이름',
                            _confirmation_id=cid)
        self.assertEqual(body.get('status'), 'modified', body)
        self.assertEqual(self._last_audit().confirmation_status, 'approved')

    def test_handler_refuses_when_it_is_reached_without_the_gate(self):
        """인앱 AI 처럼 게이트를 거치지 않고 처리기에 닿아도 남의 노트는 안 고친다."""
        from aot.aot_flask.access import write_scope
        from aot.tools.aot_data_tool_service import AoTDataToolService
        nid = self._make('Admin', name='관리자 노트')
        with write_scope.acting_as(self.user_uuids['Editor'], tool='modify_note'):
            r = AoTDataToolService.modify_note(note_id=nid, name='몰래')
        self.assertEqual(r.get('error'), 'approval_required', r)
        self.assertEqual(self._row(nid).name, '관리자 노트')


class TestPermission(_NoteFixture):

    def test_readonly_key_and_view_roles_are_refused(self):
        nid = self._make('Editor')
        body = self._call('modify_note', {'note_id': nid, 'name': 'x'},
                          self._role('Editor', readonly=True))
        self.assertEqual(body.get('reason_code'), 'insufficient_role', body)
        for who in ('Monitor', 'Guest', 'ControlOnly'):
            body = self._call('modify_note', {'note_id': nid, 'name': 'x'},
                              self._role(who))
            self.assertEqual(body.get('reason_code'), 'insufficient_role', who)
        self.assertNotEqual(self._row(nid).name, 'x')

    def test_group_scope_applies_to_the_notes_target(self):
        nid = self._make('Editor', target_id=self.output_id,
                         target_type='output')
        self._scope_to_other_group()
        body = self._modify('Editor', nid, name='스코프 밖')
        self.assertEqual(body.get('reason_code'), 'group_scope', body)
        self.assertNotEqual(self._row(nid).name, '스코프 밖')


if __name__ == '__main__':
    unittest.main()
