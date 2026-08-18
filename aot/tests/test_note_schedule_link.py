# coding=utf-8
"""노트 구간 → 예정 링크 (계획서 Phase 2, 2026-08-18 재설계).

**분기를 쓰기 전이 아니라 쓴 뒤로 옮긴다.** 처음 만든 것은 "'언제' 가 비면
노트, 채우면 예정" 인 통합 폼이었는데, 그것도 결국 쓰기 **전에** 사용자에게
종류를 물었다(날짜 칸을 채울지 말지). 게다가 그 폼은 노트 패널과 다른 창이라
둘이 이어져 있다는 느낌도 주지 못했다.

지금은 진입점이 노트 하나다. 노트를 쓰고, 그 안의 한 구간을 골라 시각을 주면
링크가 생긴다. 분류 대신 **관계**가 남는다.

계획서: .local/reports/notes-schedule-notice-ia-20260818.md §4 Phase 2
정본 로직: aot/aot_flask/note_links.py
"""
import os
import unittest

_HERE = os.path.dirname(__file__)
_ROOT = os.path.join(_HERE, '..')


def _read(*parts):
    with open(os.path.join(_ROOT, *parts), encoding='utf-8') as fh:
        return fh.read()


def _fn(src, name):
    """함수 하나의 소스만 잘라 온다 (py/js/jsx 공용).

    파이썬은 `\\ndef `, JS 는 `\\n  function ` 에서 끊긴다 — 한쪽 구분자만
    쓰면 다른 언어에서는 **파일 끝까지**가 잡혀 어떤 검사든 무조건 통과한다.
    """
    for head in ('def %s' % name, 'function %s' % name):
        if head in src:
            body = src.split(head, 1)[1]
            break
    else:
        raise AssertionError('함수를 찾지 못했습니다: %s' % name)
    for sep in ('\ndef ', '\n  function ', '\nfunction '):
        body = body.split(sep, 1)[0]
    return body


class TestSchemaAndMigration(unittest.TestCase):

    def test_migration_is_the_head_and_the_constant_matches(self):
        """마이그레이션을 넣고 상수를 안 올리면 그 마이그레이션은 영원히
        실행되지 않는다 — 에러도 경고도 없이."""
        import subprocess
        import sys
        r = subprocess.run(
            [sys.executable,
             os.path.join(_ROOT, 'scripts', 'check_alembic_head.py'), '--quiet'],
            capture_output=True, cwd=os.path.join(_ROOT, '..'))
        self.assertEqual(r.returncode, 0,
                         (r.stdout + r.stderr).decode('utf-8', 'replace'))

    def test_no_foreign_keys(self):
        """일정 삭제 경로가 한 곳이 아니라, 그중 하나만 링크 정리를 빠뜨려도
        FK 가 그 삭제를 통째로 거부한다(장치 삭제 17경로로 이미 데었다).
        대신 읽을 때 걷는다."""
        src = _read('..', 'alembic_db', 'alembic', 'versions',
                    'p6_37_note_schedule_link_20260818.py')
        self.assertNotIn('ForeignKey', src)

    def test_links_to_job_by_uuid_not_int_id(self):
        """정수 id 는 재사용되고, `scheduler_audit_log.job_meta_id` 가 그
        정수를 NOT NULL 로 물고 있어 삭제 순서에 얽힌다."""
        model = _read('..', 'aot', 'databases', 'models',
                      'note_schedule_link.py')
        self.assertIn('job_uid', model)
        self.assertNotIn('job_meta_id', model)

    def test_snapshot_is_not_nullable(self):
        """재탐색의 근거가 이것뿐이라, 비면 그 링크는 영영 하이라이트를 잃는다."""
        model = _read('..', 'aot', 'databases', 'models',
                      'note_schedule_link.py')
        line = [l for l in model.splitlines() if 'text_snapshot' in l and 'Column' in l]
        self.assertTrue(line)
        self.assertIn('nullable=False', line[0])


class TestRelocateAndOrphan(unittest.TestCase):
    """편집으로 offset 이 어긋나도 링크는 살아야 한다."""

    def _mod(self):
        import importlib
        return importlib.import_module('aot.aot_flask.note_links')

    def _link(self, text, start, end):
        class L(object):
            pass
        l = L()
        l.text_snapshot, l.start_offset, l.end_offset = text, start, end
        return l

    def test_exact_position_still_matches(self):
        m = self._mod()
        body = 'abc 방제 def'
        self.assertEqual(m.relocate(self._link('방제', 4, 6), body), (4, 6))

    def test_shifted_text_is_found_again(self):
        """앞을 길게 고치면 offset 이 밀린다 — 그때가 재탐색이 필요한 때다."""
        m = self._mod()
        body = '아주 긴 앞머리를 새로 썼다. 방제 def'
        span = m.relocate(self._link('방제', 4, 6), body)
        self.assertEqual(body[span[0]:span[1]], '방제')

    def test_deleted_text_returns_none(self):
        """못 찾으면 하이라이트만 포기한다 — 링크를 지우지 않는다."""
        m = self._mod()
        self.assertIsNone(m.relocate(self._link('방제', 4, 6), 'abc def'))

    def test_first_match_only(self):
        """같은 문장이 여러 번 나오면 어느 것이 그 약속인지 알 방법이 없다.
        추측해서 옮기면 사용자는 옮겨진 자리를 사실로 읽는다."""
        m = self._mod()
        body = '방제 ... 방제'
        self.assertEqual(m.relocate(self._link('방제', 99, 101), body), (0, 2))

    def test_no_fuzzy_matching(self):
        """부분 일치·유사도로 넓히면 비슷한 문장이 여럿인 노트에서 엉뚱한
        구간에 하이라이트가 붙는데, 그건 링크가 끊긴 것보다 나쁘다."""
        src = _read('aot_flask', 'note_links.py')
        for banned in ('difflib', 'SequenceMatcher', 'ratio(', 'startswith('):
            self.assertNotIn(banned, src)


class TestServerContract(unittest.TestCase):

    def setUp(self):
        self.src = _read('aot_flask', 'routes_notes_api.py')

    def test_routes_exist(self):
        for route in ("/notes/<note_id>/schedule", "/notes/<note_id>/links",
                      "/notes/link/<link_id>", "/notes/<note_id>/orphaned"):
            self.assertIn("'%s'" % route, self.src)

    def test_content_is_the_selection_not_a_new_field(self):
        """내용을 다시 물으면 노트와 예정이 또 서로 다른 글이 된다."""
        body = _fn(self.src, 'api_note_schedule')
        self.assertNotIn("data.get('content')", body)
        self.assertIn("data.get('text')", body)

    def test_offsets_from_the_client_are_verified(self):
        """그 사이 다른 창에서 노트가 바뀌었을 수 있다."""
        body = _fn(self.src, 'api_note_schedule')
        self.assertIn('body[start:end] == text', body)
        self.assertIn('body.find(text)', body)

    def test_target_is_inherited_from_the_note(self):
        """노트가 구획에 붙어 있으면 예정도 같은 구획에 붙는다 — 사용자가
        장소를 다시 고를 일이 없다."""
        body = _fn(self.src, 'api_note_schedule')
        self.assertIn('note.target_id', body)

    def test_a_note_without_a_target_can_still_be_scheduled(self):
        """'어디' 를 안 적었다는 이유로 '언제' 를 못 적게 하면 안 된다."""
        body = _fn(self.src, 'api_note_schedule')
        self.assertIn("'none'", body)

    def test_schedule_creation_is_shared_not_duplicated(self):
        body = _fn(self.src, 'api_note_schedule')
        self.assertIn('_create_human_schedule', body)
        rg = _read('aot_flask', 'routes_geo.py')
        self.assertEqual(rg.count('AISchedulerService.propose_job('), 1)

    def test_unlink_keeps_the_schedule_by_default(self):
        """이미 잡힌 약속이 글 편집으로 조용히 사라지면 안 된다."""
        body = _fn(_read('aot_flask', 'note_links.py'), 'unlink')
        self.assertIn('cancel_job=False', body)

    def test_cancelling_clears_the_audit_log_first(self):
        """`scheduler_audit_log.job_meta_id` 가 NOT NULL 이라 그냥 지우면
        IntegrityError 로 통째로 실패한다(실제로 겪었다)."""
        body = _fn(_read('aot_flask', 'note_links.py'), 'unlink')
        self.assertLess(body.index('SchedulerAuditLog'), body.index('delete(job)'))

    def test_links_come_with_the_note_list(self):
        """따로 부르면 노트 수만큼 왕복이 생기고, 목록이 먼저 그려진 뒤
        하이라이트가 뒤늦게 얹혀 글이 한 번 튄다."""
        body = _fn(self.src, 'api_notes_target_get')
        self.assertIn('links_for_notes', body)
        self.assertIn("'links'", body)

    def test_batch_not_per_note(self):
        nl = _read('aot_flask', 'note_links.py')
        self.assertIn('def links_for_notes', nl)
        self.assertIn('.in_(list(by_uid))', nl)


class TestOneDoorInTheUI(unittest.TestCase):

    def test_old_unified_form_is_withdrawn(self):
        """그 폼도 결국 **쓰기 전에** 종류를 물었다(날짜 칸을 채울지 말지)."""
        rg = _read('aot_flask', 'routes_geo.py')
        self.assertNotIn("'/api/geo/record'", rg)
        popup = _read('aot_flask', 'static', 'js', 'widgets', 'AoT_map',
                      'aot-map-popup.js')
        for gone in ('_recordFormHtml', 'wireRecordAdd', 'aot-ov-record-open'):
            self.assertNotIn(gone, popup)
        veg = _read('aot_flask', 'static', 'js', 'widgets', 'AoT_map',
                    'aot-map-vegetation.js')
        self.assertNotIn('wireRecordAdd', veg)

    def test_map_modal_still_shows_both_in_one_block(self):
        """UI 가 갈라져 보이던 것이 원래 문제였다 — 읽기는 계속 한 블록이다."""
        popup = _read('aot_flask', 'static', 'js', 'widgets', 'AoT_map',
                      'aot-map-popup.js')
        body = _fn(popup, 'buildRecordBlock')
        self.assertIn("_t('Coming up')", body)
        self.assertIn('window.AoTNotesBlock.html(', body)

    def test_selection_offsets_use_range_not_node_walking(self):
        """본문이 <mark> 로 쪼개져 텍스트 노드가 여럿이다 — 노드를 손으로
        세면 하이라이트가 하나 늘 때마다 계산이 어긋난다."""
        js = _read('aot_flask', 'static', 'apps', 'notes-widget', 'src',
                   'components', 'NotesList.jsx')
        body = _fn(js, 'selectionOffsets')
        self.assertIn('pre.selectNodeContents(rootEl)', body)
        self.assertIn('pre.toString().length', body)

    def test_selection_is_read_on_mouseup_not_selectionchange(self):
        """selectionchange 로 읽으면 드래그 도중 매 프레임 발화해 바가 깜빡인다."""
        js = _read('aot_flask', 'static', 'apps', 'notes-widget', 'src',
                   'components', 'NotesList.jsx')
        self.assertIn('onMouseUp={readSelection}', js)
        # 주석에는 그 단어가 나온다(왜 안 쓰는지 적어 두었다) — 코드 줄만 본다.
        code = [l for l in js.splitlines() if not l.strip().startswith('//')]
        self.assertNotIn('selectionchange', '\n'.join(code))

    def test_orphans_are_shown_not_hidden(self):
        """숨기면 아무도 취소하지 못하는 약속이 남는다."""
        js = _read('aot_flask', 'static', 'apps', 'notes-widget', 'src',
                   'components', 'LinkedSchedule.jsx')
        self.assertIn('orphaned', js)
        self.assertIn('Unlink only', js)
        self.assertIn('Cancel the schedule', js)

    def test_the_widget_bundle_was_rebuilt(self):
        """소스만 고치고 산출물을 빼면 배포된 앱은 계속 옛 코드를 실행한다."""
        built = _read('aot_flask', 'static', 'js', 'notes', 'notes-widget.js')
        self.assertIn('Schedule this', built)
        self.assertIn('/schedule', built)


class TestDeletionAndEditPaths(unittest.TestCase):
    """노트가 사라지거나 구간이 지워질 때."""

    def test_every_note_deletion_path_drops_links(self):
        """노트가 없으면 링크는 아무 데서도 안 읽히는 채 DB 에 영원히 남는다 —
        `links_for_notes` 가 노트 기준으로 읽으므로, 읽을 때 걷는 자가 치유도
        그 행에는 닿지 못한다. **삭제 경로를 새로 만들면 여기도 늘릴 것.**"""
        paths = [
            (('aot_flask', 'routes_notes_api.py'), 'api_notes_delete'),
            (('aot_flask', 'utils', 'utils_notes.py'), 'note_del'),
        ]
        for parts, fn in paths:
            body = _fn(_read(*parts), fn)
            self.assertIn('drop_for_note', body, '%s 가 링크를 안 걷는다' % fn)

    def test_deleting_a_note_does_not_cancel_its_schedules(self):
        """노트를 지우는 것과 약속을 취소하는 것은 다른 결정이고, 사람은 앞의
        것만 말했다."""
        body = _fn(_read('aot_flask', 'note_links.py'), 'drop_for_note')
        self.assertNotIn('SchedulerJobMeta', body)

    def test_edit_asks_before_saving_not_after(self):
        """저장 뒤 물으면 사용자는 이미 없어진 글을 보며 무엇을 지웠는지
        기억해내야 한다."""
        js = _read('aot_flask', 'static', 'js', 'tools',
                   'note-orphaned-links.js')
        body = _fn(js, 'init')
        # 제출을 일단 막고 → 판정을 부르고 → 그 응답 안에서만 저장한다.
        self.assertLess(body.index('e.preventDefault()'), body.index('/orphaned'))
        self.assertLess(body.index('/orphaned'), body.index('submitNow(); return;'))

    def test_edit_offers_both_choices(self):
        """묻지 않고 취소하면 잡아둔 약속이 사라지고, 묻지 않고 남기면 본문에
        없는 약속이 조용히 남는다."""
        tpl = _read('aot_flask', 'templates', 'tools', 'note_edit.html')
        self.assertIn('note_orphaned_keep', tpl)
        self.assertIn('note_orphaned_cancel', tpl)
        js = _read('aot_flask', 'static', 'js', 'tools',
                   'note-orphaned-links.js')
        self.assertIn('dropLinks(false', js)
        self.assertIn('dropLinks(true', js)

    def test_a_failed_check_does_not_block_saving(self):
        """이 확인은 편의이지 안전장치가 아니다 — 판정 요청이 실패했다고
        사람의 글 저장을 막으면 고칠 수 없는 화면이 된다."""
        js = _read('aot_flask', 'static', 'js', 'tools',
                   'note-orphaned-links.js')
        self.assertIn('.catch(function () { submitNow(); })', js)

    def test_the_dialog_uses_the_shared_modal_shell(self):
        """새 모달은 .aot-option-modal + aot-modal-* 골격을 쓴다."""
        tpl = _read('aot_flask', 'templates', 'tools', 'note_edit.html')
        self.assertIn('aot-option-modal', tpl)
        self.assertIn('aot-modal-dialog', tpl)


class TestMapPinsOnlyForNotesWithoutTheirOwnShape(unittest.TestCase):
    """지도에 **자기 표시가 이미 있는** 대상의 노트는 핀을 만들지 않는다.

    구획·시설·구역·대지는 도형으로 그려져 있고 그 도형을 눌러 노트를 본다.
    거기에 핀을 하나 더 얹으면 같은 자리를 두 번 가리키면서 지도만 어지럽히고,
    사용자가 만들지 않은 표시라 지울 방법도 마땅치 않다.

    2026-08-18 실제로 겪었다 — 구획 노트를 하나 쓰자 지도에 핀이 돋았다.
    (`api_notes_create` 의 좌표 백필은 08-13 부터 있었고, 구획 노트를 처음
    만든 날 드러났다.)
    """

    def setUp(self):
        self.src = _read('aot_flask', 'routes_notes_api.py')

    def test_geo_endpoint_filters_by_target_type(self):
        body = _fn(self.src, 'api_notes_geo_get')
        self.assertIn('_PIN_TARGET_TYPES', body)
        self.assertIn('Notes.target_type', body)

    def test_it_is_a_whitelist_not_a_blacklist(self):
        """새 대상 종류가 생길 때 기본값이 "핀 없음" 이어야 한다. 블랙리스트면
        종류를 추가할 때마다 여기 넣는 것을 기억해야 하고, 빠뜨리면 그 종류만
        조용히 핀이 돋는다 — 지금 planting 이 그랬다."""
        block = self.src.split('_PIN_TARGET_TYPES = (', 1)[1].split(')', 1)[0]
        self.assertIn('map_location', block)
        for shaped in ('planting', 'facility', 'GeoFacility', 'zone', 'site',
                       'GeoShape', 'device'):
            self.assertNotIn("'%s'" % shaped, block)

    def test_targetless_notes_still_get_a_pin(self):
        """가리킬 도형이 없으므로 핀이 그 노트의 유일한 위치 표현이다."""
        body = _fn(self.src, 'api_notes_geo_get')
        self.assertIn('Notes.target_type.is_(None)', body)

    def test_coordinates_are_still_stored(self):
        """좌표의 목적은 표시가 아니라 **대상이 사라져도 자리는 남기는 것**이다
        (구획은 몇 달 뒤 종료되지만 그 자리를 다시 물을 일이 있다).
        그래서 저장이 아니라 노출에서 가른다 — 백필을 지우면 안 된다."""
        self.assertIn('def resolve_target_gps', self.src)
        body = _fn(self.src, 'resolve_target_gps')
        self.assertIn('planting', body)
        self.assertIn('representative_point', body)
        create = _fn(self.src, 'api_notes_create')
        self.assertIn('resolve_target_gps(', create)


class TestVocabularyStaysDomainNeutral(unittest.TestCase):
    """이 소프트웨어는 농업 현장만 아니라 공원·도로·철도에도 쓴다."""

    BANNED = ('재배', '파종', '농작업', '농장', '작물')

    def test_new_korean_strings(self):
        po = _read('aot_flask', 'translations', 'ko', 'LC_MESSAGES',
                   'messages.po')
        for msgid in ('Schedule this', 'This text is no longer in the note',
                      'Unlink only', 'Cancel the schedule'):
            parts = po.split('msgid "%s"' % msgid, 1)
            self.assertEqual(len(parts), 2, '번역 없음: %s' % msgid)
            msgstr = parts[1].split('msgstr ', 1)[1].split('\n\n', 1)[0]
            for w in self.BANNED:
                self.assertNotIn(w, msgstr, '%r 에 농업 한정 어휘 %r' % (msgid, w))


if __name__ == '__main__':
    unittest.main()
