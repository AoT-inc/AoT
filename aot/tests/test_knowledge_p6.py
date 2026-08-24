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

    # -- Korean inflection (measured 2026-08-24): whole-word containment let a
    # -- reworded answer quote an unconfirmed note with no disclosure at all ---

    # 제목에 어미 없는 형태를 넣지 않는다 — 제목이 '압력 안정'을 그대로 갖고
    # 있으면 통짜 토큰 비교로도 걸려서, 정작 재려는 어미 변화를 못 잰다.
    _MREF_PIPE = (
        "[Knowledge search: 'q' — 2 section(s)]\n\n"
        "### [AI 정리 — 미확인] 김제 포장 급수 메모  (AI 자율 비치 — 대화 2026-08-24)\n"
        "밸브 개방 후 관로 압력이 안정되기까지 약 45초 걸림."
        "\n\n---\n\n"
        "### 출력 설정  (Outputs.ko.md)\n출력 장치의 일반 설정 방법."
    )

    def test_disclosure_survives_korean_inflection(self):
        """같은 사실을 어미만 바꿔 말한 답변도 잡아야 한다.

        근거는 '압력이 … 안정되기까지', 답변은 '압력은 … 안정되는' — 사람이
        보기엔 같은 말인데 통짜 토큰 비교로는 '관로' 하나만 걸려서 발화
        문턱(고유 숫자 1 + 고유 단어 2)에 한 개 모자랐고, 미확인 메모를
        '확인되었습니다'로 인용한 답변이 고지 없이 나갔다."""
        from aot.ai.services.ai_agent_service import AIAgentService
        insight = '관로 압력은 약 45초 뒤 안정되는 것으로 확인되었습니다.'
        out = AIAgentService._enforce_unconfirmed_disclosure(insight, self._MREF_PIPE)
        self.assertNotEqual(out, insight)
        self.assertIn('미확인 메모', out)
        self.assertTrue(out.startswith(insight))

    def test_disclosure_survives_korean_compounding(self):
        """근거의 낱말을 답변이 붙여 써도 잡아야 한다 — 근거의 '밸브'가
        답변에선 '급수밸브'로 한 낱말이 된다. (반대 방향, 즉 근거가 합성어고
        답변이 띄어 쓴 경우는 어간을 앞 두 음절로 자르는 이상 뒷말이 남지
        않아 못 잡는다. 문서화된 한계.)"""
        from aot.ai.services.ai_agent_service import AIAgentService
        insight = '급수밸브를 개방하시고 45초 정도 기다리시면 관로가 안정됩니다.'
        out = AIAgentService._enforce_unconfirmed_disclosure(insight, self._MREF_PIPE)
        self.assertIn('미확인 메모', out)

    def test_disclosure_still_skipped_when_authoritative_section_covers_it(self):
        """어간 비교는 빼기(고유 판정)에도 똑같이 적용돼야 한다 — 권위 섹션이
        어미만 다르게 같은 말을 하고 있으면 그 단어는 '미확인 섹션에만 있는
        말'이 아니다. 이쪽이 느슨해지지 않으면 매칭만 느슨해져 오탐이 는다."""
        from aot.ai.services.ai_agent_service import AIAgentService
        mref = (
            "### [AI 정리 — 미확인] 관수 메모  (AI 자율 비치)\n"
            "관수 후 환기가 결로를 줄인다."
            "\n\n---\n\n"
            "### [권위] 관수 가이드  (RDA)\n"
            "관수를 한 뒤에 환기를 하면 결로가 줄어든다. 표준 지침이다."
        )
        insight = '관수하신 뒤에 환기를 해 주십시오. 결로가 줄어듭니다 (RDA 표준 지침).'
        out = AIAgentService._enforce_unconfirmed_disclosure(insight, mref)
        self.assertEqual(out, insight)

    def test_disclosure_skipped_when_only_grammar_words_overlap(self):
        """겹치는 것이 문법 형태소뿐이면 인용이 아니다. 어간을 두 음절로
        자르면 '때문에/경우에/따라서/있습니다' 같은 것들이 통째로 겹치므로,
        내용어가 하나도 안 겹치는 답변이 단어 문턱(5개)만으로 발화할 수 있다."""
        from aot.ai.services.ai_agent_service import AIAgentService
        mref = (
            "### [AI 정리 — 미확인] 저장고 메모  (AI 자율 비치)\n"
            "저장고 습도가 높기 때문에, 경우에 따라 제습을 위해 문을 열어 두는 것으로 되어 있습니다."
            "\n\n---\n\n"
            "### 출력 설정  (Outputs.ko.md)\n출력 장치의 일반 설정 방법."
        )
        insight = (
            '계량기 점검이 필요하기 때문에, 경우에 따라 교체를 위해 '
            '일정을 잡는 것으로 되어 있습니다.'
        )
        out = AIAgentService._enforce_unconfirmed_disclosure(insight, mref)
        self.assertEqual(out, insight)

    def test_disclosure_skipped_when_the_same_number_counts_something_else(self):
        """숫자는 무엇을 센 숫자인지까지 같아야 근거가 된다 — 메모의 '90%'와
        답변의 '90일'은 같은 사실이 아니다. 숫자 하나만으로 단어 문턱이
        2로 낮아지므로, 여기서 걸러 주지 않으면 어간 비교를 느슨하게 한
        대가를 오탐으로 치르게 된다."""
        from aot.ai.services.ai_agent_service import AIAgentService
        mref = (
            "### [AI 정리 — 미확인] 저장고 메모  (AI 자율 비치)\n"
            "저온 저장고 습도는 90% 근처로 유지한다."
            "\n\n---\n\n"
            "### 출력 설정  (Outputs.ko.md)\n출력 장치의 일반 설정 방법."
        )
        insight = '저온기 대비로 습도계 점검을 90일 안에 하시는 편이 좋겠습니다.'
        out = AIAgentService._enforce_unconfirmed_disclosure(insight, mref)
        self.assertEqual(out, insight)

    def test_disclosure_skipped_for_words_that_only_share_a_root(self):
        """조사·어미만 벗기고 낱말을 자르지는 않는다 — '관리기'와 '관리자',
        '급수전'과 '급수차'는 앞이 같을 뿐 다른 말이다. 앞 두 음절로 자르는
        방식이었다면 이 답변이 근거를 인용한 것으로 계산된다."""
        from aot.ai.services.ai_agent_service import AIAgentService
        mref = (
            "### [AI 정리 — 미확인] 점검 메모  (AI 자율 비치)\n"
            "관리기와 급수전 점검은 30일마다 한다."
            "\n\n---\n\n"
            "### 출력 설정  (Outputs.ko.md)\n출력 장치의 일반 설정 방법."
        )
        insight = '관리자 계정과 급수차 배차는 30일마다 확인하십시오.'
        out = AIAgentService._enforce_unconfirmed_disclosure(insight, mref)
        self.assertEqual(out, insight)

    def test_disclosure_ignores_shelving_metadata_in_the_header(self):
        """헤더 괄호(비치 경위·날짜)는 인용 대상이 아니다. 그 안의 날짜
        숫자는 미확인 블록에만 있으므로, 그냥 두면 '24일'을 말한 무관한
        답변이 고유 숫자 일치로 계산된다."""
        from aot.ai.services.ai_agent_service import AIAgentService
        insight = '자율 주행 대화 기록은 2026년 8월 24일 자로 정리해 두었습니다.'
        out = AIAgentService._enforce_unconfirmed_disclosure(insight, self._MREF_PIPE)
        self.assertEqual(out, insight)


if __name__ == '__main__':
    unittest.main()
