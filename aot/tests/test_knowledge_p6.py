# coding=utf-8
"""
P6 unit tests — flag defaults, knowledge_chunk_confirmed_only redefinition,
semantic notes search integration (docs/design/ai-library-redesign.md §5, §6,
§9). In-memory sqlite, isolated app context — no live DB touched (see
feedback_never_test_against_live_db).
"""
import hashlib
import os
import sys
import unittest

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), os.path.pardir, os.path.pardir)))
os.environ["ALEMBIC_RUNNING"] = "1"

from flask import Flask
from flask_babel import Babel

from aot.aot_flask.extensions import db
from aot.databases.models import AIContextSource, AIGlobalSettings, AIKnowledgeChunk, Notes
from aot.ai.services import knowledge_search
from aot.ai.services import knowledge_shelve_service as shelve_svc


def _make_test_app():
    """See test_knowledge_library_p1.py::_make_test_app for the QueuePool/
    ':memory:' rationale."""
    app = Flask(__name__)
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['TESTING'] = True
    db.init_app(app)
    Babel(app)
    return app


class TestKnowledgeP6(unittest.TestCase):
    def setUp(self):
        self.app = _make_test_app()
        self.app_context = self.app.app_context()
        self.app_context.push()
        db.create_all()
        knowledge_search._library_sections = []
        knowledge_search._library_stamp = None
        knowledge_search._ext_authority_sections = []
        knowledge_search._ext_authority_stamp = None
        knowledge_search.reset_index()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.app_context.pop()
        knowledge_search._library_sections = []
        knowledge_search._library_stamp = None

    # -- §6: flags default ON for a fresh install -----------------------------

    def test_fresh_settings_row_defaults_knowledge_flags_on(self):
        s = AIGlobalSettings()
        db.session.add(s)
        db.session.commit()
        db.session.refresh(s)
        self.assertTrue(s.t3_knowledge_search_enabled)
        self.assertTrue(s.knowledge_digest_enabled)
        # Deliberately unchanged — an opt-in stricter mode, not on-by-default.
        self.assertFalse(s.knowledge_chunk_confirmed_only)

    # -- §9: knowledge_chunk_confirmed_only redefinition ----------------------

    def _make_source(self, name='Test Doc'):
        source = AIContextSource(
            facility_id='default', source_name=name, source_type='document',
            parameter_name=f'test.{name}',
        )
        source.save()
        return source

    def test_confirmed_only_excludes_unconfirmed_ai_curated_only(self):
        """Turning confirmed_only on must hide an unconfirmed (system_generated)
        ai_curated note but keep external_authority/user_provided rows AND a
        confirmed ai_curated row — the P6 fix for the old all-or-nothing
        semantics that made every review UI-less turn-on a one-way trip to
        an empty index."""
        AIGlobalSettings(id=1, knowledge_digest_enabled=True,
                          knowledge_chunk_confirmed_only=True).save()

        source = self._make_source()
        db.session.add(AIKnowledgeChunk(
            source_id=source.source_id, source_name=source.source_name,
            section_title='공식자료', digest_text='쥬키니테스트토큰 공식 내용',
            content_hash=hashlib.sha256(b'p6-official').hexdigest(),
            provenance='user_provided', content_kind='prose',
            tags='a', is_enabled=True,
        ))
        db.session.commit()

        r_unconfirmed = shelve_svc.shelve_knowledge(
            content='쥬키니테스트토큰 미확인 관찰', tags=['a'], heading='미확인 항목')
        self.assertEqual(r_unconfirmed['status'], 'created')

        from aot.ai.services import knowledge_promotion_service as promo_svc
        r_confirmed_src = shelve_svc.shelve_knowledge(
            content='쥬키니테스트토큰 확인된 관찰', tags=['a'], heading='확인된 항목')
        promo_svc.confirm_item(r_confirmed_src['chunk_id'])

        hits = [h for h in knowledge_search.search('쥬키니테스트토큰') if h['origin'] == 'library']
        headings = {h['heading'] for h in hits}
        self.assertIn('공식자료', headings)       # user_provided — always kept
        self.assertIn('확인된 항목', headings)     # ai_curated but confirmed — kept
        self.assertNotIn('미확인 항목', headings)  # ai_curated + system_generated — hidden

    def test_confirmed_only_off_includes_unconfirmed(self):
        AIGlobalSettings(id=1, knowledge_digest_enabled=True,
                          knowledge_chunk_confirmed_only=False).save()
        shelve_svc.shelve_knowledge(content='쥬키니테스트토큰 기본값 테스트', tags=['a'], heading='기본값 항목')
        hits = [h for h in knowledge_search.search('쥬키니테스트토큰') if h['origin'] == 'library']
        self.assertEqual(len(hits), 1)

    # -- §5 decision #2: semantic notes search integration --------------------

    def _enable_digest(self):
        AIGlobalSettings(id=1, knowledge_digest_enabled=True).save()

    def test_ai_semantic_note_surfaces_via_search_as_user_provided(self):
        self._enable_digest()
        note = Notes(
            name='배수 결정', note='쥬키니테스트토큰 — 우기엔 3번 존 배수로를 미리 열어둔다.',
            tags='drainage,zone-3', category='ai_semantic', target_id='zone-3-uuid',
        )
        note.save()

        hits = [h for h in knowledge_search.search('쥬키니테스트토큰') if h['origin'] == 'library']
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]['provenance'], 'user_provided')
        self.assertEqual(hits[0]['heading'], '배수 결정')

    def test_non_semantic_note_is_not_searched(self):
        """A routine note (category='general', e.g. 'replace valve battery')
        is NOT confirmed knowledge — only category='ai_semantic' notes are
        search candidates, matching get_global_decisions' own criteria."""
        self._enable_digest()
        Notes(name='일반 메모', note='쥬키니테스트토큰 — 일반 메모 내용',
              category='general').save()
        hits = [h for h in knowledge_search.search('쥬키니테스트토큰') if h['origin'] == 'library']
        self.assertEqual(len(hits), 0)

    def test_archived_or_disputed_semantic_note_excluded(self):
        self._enable_digest()
        Notes(name='보관됨', note='쥬키니테스트토큰 보관된 노트',
              category='ai_semantic', is_archived=True).save()
        Notes(name='반박됨', note='쥬키니테스트토큰 반박된 노트',
              category='ai_semantic', tags='incorrect').save()
        hits = [h for h in knowledge_search.search('쥬키니테스트토큰') if h['origin'] == 'library']
        self.assertEqual(len(hits), 0)

    def test_semantic_note_tag_scoping(self):
        self._enable_digest()
        Notes(name='태그 노트', note='쥬키니테스트토큰 태그 검증',
              category='ai_semantic', tags='tomato,zone-3').save()
        matched = [h for h in knowledge_search.search('쥬키니테스트토큰', tags=['tomato'])
                   if h['origin'] == 'library']
        self.assertEqual(len(matched), 1)
        unmatched = [h for h in knowledge_search.search('쥬키니테스트토큰', tags=['railway'])
                     if h['origin'] == 'library']
        self.assertEqual(len(unmatched), 0)

    # -- regression: manual search stays unaffected (plan's stated bar) ------

    def test_manual_search_unaffected_by_p6_changes(self):
        hits = knowledge_search.search('입력')
        self.assertTrue(any(h['origin'] == 'manual' for h in hits))

    # -- truncation-survival: manual_reference must be a FRONT context key ---
    # (verification finding 2026-07-19: a tail-appended manual_reference was
    # cut by base_ai's 100k hard-truncation on a 195k prompt and the model
    # answered "no data" about knowledge the library held)

    def test_inject_context_front_places_key_after_system_knowledge(self):
        from aot.ai.services.ai_agent_service import AIAgentService
        ctx = {'system_knowledge': 'SK', 'system_state': 's', 'capabilities': 'HUGE',
               'chat_history': ['h1']}
        out = AIAgentService._inject_context_front(ctx, 'manual_reference', 'MREF')
        self.assertEqual(list(out.keys())[:2], ['system_knowledge', 'manual_reference'])
        # chat_history list identity preserved — later .append()s must still land
        self.assertIs(out['chat_history'], ctx['chat_history'])
        self.assertEqual(set(out.keys()), set(ctx.keys()) | {'manual_reference'})

    def test_inject_context_front_without_system_knowledge(self):
        from aot.ai.services.ai_agent_service import AIAgentService
        ctx = {'system_state': 's', 'capabilities': 'HUGE'}
        out = AIAgentService._inject_context_front(ctx, 'manual_reference', 'MREF')
        self.assertEqual(list(out.keys())[0], 'manual_reference')

    # -- citation-trust disclosure guard (verification finding 2026-07-19:
    # -- flash-lite cited an unconfirmed shelved note as "확인되었습니다") ----

    _MREF_UNCONF = (
        "[Knowledge search: 'q' — 2 section(s)]\n\n"
        "### [AI 정리 — 미확인] 급수 밸브 압력 안정 시간  (AI 자율 비치 — 대화 2026-07-19)\n"
        "베리파이토큰 — 김제 포장 급수 밸브는 개방 후 압력 안정까지 약 45초 걸림."
        "\n\n---\n\n"
        "### 출력 설정  (Outputs.ko.md)\n출력 장치의 일반 설정 방법."
    )

    def test_disclosure_appended_when_answer_draws_on_unconfirmed(self):
        from aot.ai.services.ai_agent_service import AIAgentService
        insight = '김제 포장 급수 밸브는 개방 후 압력이 안정되기까지 약 45초가 소요되는 것으로 확인되었습니다.'
        out = AIAgentService._enforce_unconfirmed_disclosure(insight, self._MREF_UNCONF)
        self.assertNotEqual(out, insight)
        self.assertIn('미확인 메모', out)
        self.assertTrue(out.startswith(insight))  # appended, never rewrites the answer

    def test_disclosure_not_duplicated_when_model_already_disclosed(self):
        from aot.ai.services.ai_agent_service import AIAgentService
        insight = '미확인 메모 기준으로 약 45초입니다 (김제 포장 급수 밸브, 개방 후 압력 안정).'
        out = AIAgentService._enforce_unconfirmed_disclosure(insight, self._MREF_UNCONF)
        self.assertEqual(out, insight)

    def test_disclosure_skipped_when_answer_unrelated_to_unconfirmed(self):
        from aot.ai.services.ai_agent_service import AIAgentService
        insight = '출력 장치는 설정 메뉴에서 추가할 수 있습니다.'
        out = AIAgentService._enforce_unconfirmed_disclosure(insight, self._MREF_UNCONF)
        self.assertEqual(out, insight)

    def test_disclosure_skipped_when_no_unconfirmed_sections(self):
        from aot.ai.services.ai_agent_service import AIAgentService
        mref_confirmed = self._MREF_UNCONF.replace('[AI 정리 — 미확인]', '[AI 정리 — 확인됨]')
        insight = '김제 포장 급수 밸브는 개방 후 약 45초가 소요됩니다.'
        out = AIAgentService._enforce_unconfirmed_disclosure(insight, mref_confirmed)
        self.assertEqual(out, insight)

    def test_disclosure_distinctive_tokens_ignore_shared_manual_words(self):
        """Tokens appearing in BOTH the unconfirmed section and another
        grounding section must not count — an answer sourced from the
        authoritative/manual section alone shouldn't get the disclosure."""
        from aot.ai.services.ai_agent_service import AIAgentService
        mref = (
            "### [AI 정리 — 미확인] 관수 메모  (AI 자율 비치)\n"
            "관수 후 환기가 결로를 줄인다."
            "\n\n---\n\n"
            "### [권위] 관수 가이드  (RDA)\n"
            "관수 후 환기가 결로를 줄인다. 표준 지침이다."
        )
        insight = '관수 후 환기를 하면 결로가 줄어듭니다. 표준 지침입니다.'
        out = AIAgentService._enforce_unconfirmed_disclosure(insight, mref)
        self.assertEqual(out, insight)


if __name__ == '__main__':
    unittest.main()
