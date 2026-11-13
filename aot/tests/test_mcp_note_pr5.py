# coding=utf-8
"""노트 재설계 PR 5 (2026-11-03) — 방금 쓴 노트를 바로 바로잡을 수 있어야 한다.

- `record.note` 한 op: 대상이 장소·장치면 새 노트, 노트 id 면 고치기(본문·제목·**옮기기**·숨기기).
- `remove.delete(kind=note)` → 안쪽 `delete_note`: **늘** 승인 대기, 승인 문구가 제목·붙은 곳·첫 줄을 되읽는다,
  승인 뒤 지우고 본문은 감사 로그에 남는다. 숨기기(archive)는 되돌릴 수 있다.
- `records.notes`: 노트 id 로 한 건, `archived` 로 숨긴 노트, 태그는 이름으로.
"""
import json
import unittest

from aot.aot_flask.extensions import db
import uuid

from aot.databases.models import AuditLog, MCPConfirmation, Notes, Output
from aot.tests.test_mcp_record_write_guard import _PREFIX
from aot.tests.test_modify_note import _MARK, _NoteFixture
from aot.tools import mcp_safety_gate as gate
from aot.tools import tool_registry as R


class RegistrationTest(unittest.TestCase):

    def test_delete_note_always_needs_approval_and_the_web_role(self):
        self.assertIn('delete_note', R.approval_required_tools())
        self.assertNotIn('delete_note', R.record_write_tools())
        self.assertNotIn('delete_note', gate.CONDITIONAL_APPROVAL_TOOLS)
        self.assertEqual(gate.classify_permission('delete_note'), 'write')
        self.assertEqual(gate.required_write_permission('delete_note'), 'edit_settings')
        self.assertIn('delete_note', gate.NOTE_DELETE_TOOLS)

    def test_note_tier_is_gone_and_its_inner_tool_is_not_in_the_mcp_catalog(self):
        from aot.tools.domain.registry_data import OPS
        ops = {(o.tool, o.op) for o in OPS}
        for old in (('record', 'note_add'), ('record', 'note_edit'), ('record', 'note_tier')):
            self.assertNotIn(old, ops)
        for new in (('record', 'note'), ('remove', 'delete')):
            self.assertIn(new, ops)
        self.assertNotIn(('remove', 'note_delete'), ops)         # 지우기는 remove.delete(kind=note) 한 op(PR 7)

    def test_cold_storage_ops_are_gone(self):
        # 냉동 보관(2026-11-04 사용자 결정으로 제거) — 서비스 본체는 남고 MCP 도구만 없다.
        from aot.tools.domain.registry_data import OPS
        ops = {(o.tool, o.op) for o in OPS}
        for gone in (('record', 'note_archive'), ('record', 'note_restore'), ('records', 'archives'),
                     ('records', 'archive_doc')):
            self.assertNotIn(gone, ops)
        names = {p['tool_name'] for p in R._MCP_TOOL_PAYLOADS}
        for old in ('archive_note', 'restore_note_from_archive', 'search_archives',
                    'get_archived_document', 'delete_archive', 'set_document_tier'):
            self.assertNotIn(old, names)


class DomainPlanTest(unittest.TestCase):

    def test_old_op_names_are_accepted(self):
        from aot.tools.domain import renames
        for old in ('note_add', 'note_edit'):
            _a, got = renames.resolve('record', {'op': old, 'target': 'z'})
            self.assertEqual('note', got['op=%s' % old])

    def test_the_note_op_writes_on_places_and_edits_a_note(self):
        from aot.tools.domain.registry_data import OPS
        o = {(x.tool, x.op): x for x in OPS}[('record', 'note')]
        self.assertEqual('modify_note', o.inner['note'])
        self.assertEqual('note_id', o.target_arg['note'])
        for kind in ('zone', 'site', 'device', 'plot', 'none'):
            self.assertEqual('create_note', o.inner[kind], kind)
        self.assertEqual((), o.required)       # text 는 새 노트일 때만 필요 — 안쪽이 검사한다

    def test_delete_op_maps_to_the_approved_delete_tool(self):
        from aot.tools.domain.registry_data import OPS
        o = {(x.tool, x.op): x for x in OPS}[('remove', 'delete')]
        self.assertEqual('delete_note', o.pick_by_arg.branches['note'].inner['note'])
        self.assertEqual({'note': 'delete_note'}, o.pick_by_arg.branches['note'].inner)

    def test_records_notes_reads_one_note_by_id_and_hidden_ones(self):
        from aot.tools.domain.registry_data import OPS
        o = {(x.tool, x.op): x for x in OPS}[('records', 'notes')]
        self.assertEqual('search_notes', o.inner['note'])
        self.assertEqual('note_id', o.target_arg['note'])
        self.assertIn('archived', o.shown)


class PlanThroughTheDomainTest(_NoteFixture):
    """실제 해석: 노트 id 를 대상으로 주면 고치기·지우기·읽기로, 장소면 새 노트로 간다."""

    def _plan(self, tool, args):
        from aot.tools.domain import dispatch
        db.session.remove()
        return dispatch.plan(tool, dict(args))

    def test_a_note_id_edits_and_a_place_creates(self):
        nid = self._make('Editor')
        v = self._plan('record', {'op': 'note', 'target': nid, 'text': '고친 글', 'title': '고친 제목'})
        self.assertEqual(('call', 'modify_note'), v[:2], v)
        self.assertEqual(nid, v[2]['note_id'])
        self.assertEqual({'note': '고친 글', 'name': '고친 제목'},
                         {k: v[2][k] for k in ('note', 'name')})
        v = self._plan('record', {'op': 'note', 'target': self.output_id, 'text': '새 글'})
        self.assertEqual(('call', 'create_note'), v[:2], v)

    def test_a_note_id_can_move_hide_and_be_read(self):
        nid = self._make('Editor')
        v = self._plan('record', {'op': 'note', 'target': nid, 'target_name': '다른 곳', 'archive': True})
        self.assertEqual(('call', 'modify_note'), v[:2], v)
        self.assertEqual('다른 곳', v[2]['target_name'])
        v = self._plan('records', {'op': 'notes', 'target': nid})
        self.assertEqual(('call', 'search_notes'), v[:2], v)
        self.assertEqual(nid, v[2]['note_id'])

    def test_delete_goes_to_the_approved_tool_and_only_for_a_note(self):
        nid = self._make('Editor')
        v = self._plan('remove', {'op': 'delete', 'kind': 'note', 'target': nid})
        self.assertEqual(('call', 'delete_note'), v[:2], v)
        self.assertEqual(nid, v[2]['note_id'])
        v = self._plan('remove', {'op': 'note_delete', 'target': nid})           # 옛 이름
        self.assertEqual(('call', 'delete_note'), v[:2], v)
        v = self._plan('remove', {'op': 'delete', 'kind': 'note', 'target': self.output_id})
        self.assertNotEqual('call', v[0], v)               # 장치를 노트로 알아듣지 않는다


class DeleteNoteTest(_NoteFixture):

    def _delete(self, who, note_id, **extra):
        return self._call('delete_note', dict({'note_id': note_id}, **extra),
                          self._role(who), scope_user_uuid=self.user_uuids[who])

    def _approve(self, cid):
        row = MCPConfirmation.query.filter_by(unique_id=cid).first()
        row.status = 'approved'
        row.user_id = self.user_uuids['Admin']
        row.save()

    def test_even_my_own_note_waits_for_approval_and_nothing_is_deleted(self):
        nid = self._make('Editor', name='엉뚱한 곳 노트')
        body = self._delete('Editor', nid)
        self.assertEqual('pending_approval', body.get('status'), body)
        self.assertIsNotNone(self._row(nid))

    def test_the_approval_text_names_the_note_its_place_and_first_line(self):
        nid = self._make('Editor', name='점검 메모', target_id=self.output_id, target_type='output')
        row = self._row(nid)
        row.note = '첫 줄 내용\n둘째 줄'
        db.session.commit()
        text = gate.read_back_text('delete_note', {'note_id': nid, '_title': 'AI 가 쓴 제목'})
        self.assertIn('점검 메모', text)
        self.assertIn('첫 줄 내용', text)
        self.assertNotIn('둘째 줄', text)
        self.assertNotIn('AI 가 쓴 제목', text)
        self.assertIn('되돌릴 수 없습니다', text)
        place = gate._note_delete_readback(nid)
        self.assertNotIn('붙은 곳 없음', place)        # 붙은 곳 이름이 풀려 나온다

    def test_text_for_a_missing_note_says_nothing_will_be_deleted(self):
        self.assertIn('찾지 못했습니다', gate.read_back_text('delete_note', {'note_id': 'no-such'}))

    def test_approved_delete_runs_and_the_text_stays_in_the_audit_log(self):
        nid = self._make('Editor', name='지울 노트')
        body = self._delete('Editor', nid)
        self._approve(body['confirmation_id'])
        status, result = gate.execute_approved(body['confirmation_id'])
        self.assertEqual('executed', status, result)
        self.assertIsNone(self._row(nid))
        db.session.remove()
        rows = AuditLog.query.filter_by(action='note.delete', target_id=nid).all()
        self.assertEqual(1, len(rows))
        prev = json.loads(rows[0].before_json)
        self.assertEqual('지울 노트', prev['name'])
        self.assertIn(_MARK, prev['note'])

    def test_roles_without_edit_settings_and_read_only_keys_are_refused(self):
        nid = self._make('Editor')
        body = self._call('delete_note', {'note_id': nid}, self._role('Editor', readonly=True))
        self.assertEqual('insufficient_role', body.get('reason_code'), body)
        for who in ('Monitor', 'Guest', 'ControlOnly'):
            body = self._call('delete_note', {'note_id': nid}, self._role(who))
            self.assertEqual('insufficient_role', body.get('reason_code'), (who, body))
        self.assertIsNotNone(self._row(nid))

    def test_group_scope_applies_to_the_notes_target(self):
        nid = self._make('Editor', target_id=self.output_id, target_type='output')
        self._scope_to_other_group()
        body = self._delete('Editor', nid)
        self.assertIn(body.get('reason_code'), ('group_scope',), body)
        self.assertIsNotNone(self._row(nid))

    def test_hiding_is_reversible_and_deleting_is_not_hiding(self):
        nid = self._make('Editor')
        self._modify('Editor', nid, archive=True)
        self.assertTrue(self._row(nid).is_archived)
        self._modify('Editor', nid, archive=False)
        self.assertFalse(self._row(nid).is_archived)


class MoveNoteTest(_NoteFixture):

    def setUp(self):
        super().setUp()
        self.inp = str(uuid.uuid4())           # 옮겨 갈 두 번째 장치
        db.session.add(Output(unique_id=self.inp, name=_PREFIX + 'Valve2',
                              output_type='virtual_on_off_single', tab_id=self._tab))
        db.session.commit()

    def tearDown(self):
        try:
            db.session.rollback()
            Output.query.filter(Output.name == _PREFIX + 'Valve2').delete(synchronize_session=False)
            db.session.commit()
        finally:
            super().tearDown()

    def test_a_note_written_on_the_wrong_place_moves_to_the_right_one(self):
        nid = self._make('Editor', target_id=self.output_id, target_type='output')
        body = self._modify('Editor', nid, target_id=self.inp)
        self.assertEqual('modified', body.get('status'), body)
        self.assertIn('target', body['changed'])
        row = self._row(nid)
        self.assertEqual(self.inp, row.target_id)
        before = json.loads(self._audit_rows(nid)[0].before_json)
        self.assertEqual(self.output_id, before['target_id'])       # 되돌릴 값이 남는다

    def test_an_unknown_place_changes_nothing(self):
        nid = self._make('Editor', target_id=self.output_id, target_type='output')
        body = self._modify('Editor', nid, target_name='이런 곳은 없다 zzz')
        self.assertEqual('target_not_found', body.get('error'), body)
        self.assertEqual(self.output_id, self._row(nid).target_id)
        self.assertEqual([], self._audit_rows(nid))

    def test_moving_into_a_place_outside_my_group_is_refused(self):
        nid = self._make('Editor', target_id=self.output_id, target_type='output')
        self._scope_to_other_group()
        body = self._modify('Editor', nid, target_id=self.inp)
        self.assertIsNotNone(body.get('reason_code') or body.get('error'), body)
        self.assertEqual(self.output_id, self._row(nid).target_id)

    def test_moving_to_where_it_already_is_is_not_a_change(self):
        nid = self._make('Editor', target_id=self.output_id, target_type='output')
        body = self._modify('Editor', nid, target_id=self.output_id)
        self.assertEqual([], body.get('changed'), body)


class ReadNotesTest(_NoteFixture):

    def _search(self, **args):
        from aot.tools.aot_data_tool_service import AoTDataToolService
        db.session.remove()
        return AoTDataToolService.search_notes_tool(**args)

    def test_one_note_by_id_even_when_hidden(self):
        nid = self._make('Editor')
        self._modify('Editor', nid, archive=True)
        got = self._search(note_id=nid)
        self.assertEqual(1, got['count'], got)
        self.assertTrue(got['results'][0]['archived'])

    def test_hidden_notes_only_when_asked(self):
        nid = self._make('Editor', target_id=self.output_id, target_type='output')
        self._modify('Editor', nid, archive=True)
        ids = lambda g: {r['note_id'] for r in g['results']}      # noqa: E731
        self.assertNotIn(nid, ids(self._search(target_id=self.output_id)))
        self.assertIn(nid, ids(self._search(target_id=self.output_id, archived='include')))
        only = self._search(target_id=self.output_id, archived='only')
        self.assertIn(nid, ids(only))
        self.assertTrue(all(r.get('archived') for r in only['results']))

    def test_tags_are_names_not_ids(self):
        from aot.databases.models import NoteTags
        tag = NoteTags(name='PR5태그시험')
        db.session.add(tag)
        db.session.commit()
        self.addCleanup(lambda: (NoteTags.query.filter_by(name='PR5태그시험').delete(),
                                 db.session.commit()))
        nid = self._make('Editor', tags=tag.unique_id)
        got = self._search(note_id=nid)
        self.assertIn('PR5태그시험', got['results'][0]['tags'])
        self.assertNotIn(tag.unique_id, got['results'][0]['tags'])


if __name__ == '__main__':
    unittest.main()
