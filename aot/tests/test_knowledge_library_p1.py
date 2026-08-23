# coding=utf-8
"""
P1-P3 unit tests — AI library redesign (docs/design/ai-library-redesign.md).

P1: §2 unified item schema defaults, §5 tag-based scoping (replacing the old
facility_id axis), ttl expiry.
P2: §6 provenance-differentiated citation tags in search_as_text().
P3: §7/§10 external-authority structured adapter — ext_smartfarm_setpoints /
ext_nongsaro_guides / ext_pest_alerts read directly (no shredding into
AIContextRecord, no reuse of the network-fetching get_setpoints()).

In-memory sqlite, isolated app context — no live DB touched (see
feedback_never_test_against_live_db).
"""
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), os.path.pardir, os.path.pardir)))
os.environ["ALEMBIC_RUNNING"] = "1"

from flask import Flask
from flask_babel import Babel

from aot.aot_flask.extensions import db
from aot.databases.models import (
    AIContextSource, AIGlobalSettings, AIKnowledgeChunk,
    ExtSmartfarmSetpoints, ExtNongsaroGuides, ExtPestAlerts,
)
from aot.ai.services import knowledge_search


def _make_test_app():
    """Bare Flask+SQLAlchemy app, deliberately NOT create_app(): the real
    factory (aot/aot_flask/app.py) unconditionally forces
    SQLALCHEMY_ENGINE_OPTIONS={'poolclass': QueuePool, 'pool_size': 5, ...}
    for the non-gunicorn branch, and QueuePool's pool_size/max_overflow/
    pool_timeout are invalid for a sqlite ':memory:' engine (which needs
    StaticPool) — this breaks create_app() for ANY in-memory sqlite test in
    this environment (confirmed pre-existing: aot/tests/test_ai_task_system.py
    fails identically, unrelated to this change). Building the minimal app
    here avoids that unrelated bug and needs nothing else from the factory
    for a model/service unit test."""
    app = Flask(__name__)
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['TESTING'] = True
    db.init_app(app)
    # `config_translations` 는 import 시점에 `lazy_gettext(...).format()` 을
    # 평가하므로 babel 이 없으면 KeyError 로 죽는다 — 그 모듈을 끌어오는 것은
    # `aot_data_tool_service` 이고, 도구 응답을 검증하는 테스트가 그것을 부른다.
    # 여기서 한 줄 붙여 두면 그 계열이 이 최소 앱에서도 돈다.
    Babel(app)
    return app


class TestKnowledgeLibraryP1(unittest.TestCase):
    def setUp(self):
        self.app = _make_test_app()
        self.app_context = self.app.app_context()
        self.app_context.push()
        db.create_all()
        # The module-level index caches in knowledge_search are process-global
        # (by design — see its docstring), so they must be reset per test or
        # one test's rows leak into the next test's fresh in-memory DB.
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
        knowledge_search._ext_authority_sections = []
        knowledge_search._ext_authority_stamp = None

    def _make_source(self, name='Test Doc'):
        source = AIContextSource(
            facility_id='default',
            source_name=name,
            source_type='document',
            parameter_name=f'test.{name}',
        )
        source.save()
        return source

    def _make_chunk(self, source, heading, content, tags=None, ttl=None, **kwargs):
        import hashlib
        chunk = AIKnowledgeChunk(
            source_id=source.source_id,
            source_name=source.source_name,
            section_title=heading,
            digest_text=content,
            raw_excerpt=content,
            content_hash=hashlib.sha256(content.encode('utf-8')).hexdigest(),
            is_enabled=True,
            tags=tags,
            ttl=ttl,
            **kwargs,
        )
        chunk.save()
        return chunk

    def _enable_digest(self):
        settings = AIGlobalSettings(id=1, knowledge_digest_enabled=True)
        settings.save()

    # -- §2: unified item schema defaults ------------------------------------

    def test_provenance_and_content_kind_default(self):
        source = self._make_source()
        chunk = self._make_chunk(source, 'h', 'content, no explicit provenance/kind')
        db.session.expire_all()
        reloaded = AIKnowledgeChunk.query.filter_by(unique_id=chunk.unique_id).first()
        self.assertEqual(reloaded.provenance, 'user_provided')
        self.assertEqual(reloaded.content_kind, 'prose')
        self.assertEqual(reloaded.context_state, 'system_generated')
        self.assertIsNone(reloaded.tags)
        self.assertIsNone(reloaded.entity_ref)

    def test_write_knowledge_chunks_stamps_provenance(self):
        """context_source_service._write_knowledge_chunks (the only current
        writer) must stamp provenance='user_provided' / content_kind='prose'
        / an attribution string, not leave them to bare column defaults."""
        from aot.ai.services.context_source_service import _write_knowledge_chunks
        source = self._make_source(name='Uploaded SOP')
        n = _write_knowledge_chunks(source, 'A' * 3000 + '\n\n' + 'B' * 3000)
        self.assertGreaterEqual(n, 1)
        rows = AIKnowledgeChunk.query.filter_by(source_id=source.source_id).all()
        self.assertTrue(rows)
        for row in rows:
            self.assertEqual(row.provenance, 'user_provided')
            self.assertEqual(row.content_kind, 'prose')
            self.assertIn('Uploaded SOP', row.attribution)

    # -- §5: tag-based scoping in knowledge_search ---------------------------

    def test_tag_filter_matches_and_excludes(self):
        """Assertions target origin=='library' hits specifically, not the raw
        result count — the always-global markdown manual can legitimately
        also score on a query term (e.g. a Korean 2-char stem incidentally
        matching an unrelated doc), and that's correct behavior (§5: the
        manual is never tag-scoped), not something this filter should hide."""
        self._enable_digest()
        source = self._make_source()
        self._make_chunk(source, '토마토 개화기 관리', '쥬키니테스트토큰 관련 재배 정보',
                          tags='tomato,flowering')
        self._make_chunk(source, '교량 점검', '레일웨이테스트토큰 관련 점검 정보',
                          tags='railway,bridge')

        def _lib_hits(hits):
            return [h for h in hits if h['origin'] == 'library']

        hits_match = _lib_hits(knowledge_search.search('쥬키니테스트토큰', tags=['tomato']))
        self.assertEqual(len(hits_match), 1)
        self.assertEqual(hits_match[0]['provenance'], 'user_provided')
        self.assertEqual(hits_match[0]['tags'], ['tomato', 'flowering'])

        hits_mismatch = _lib_hits(knowledge_search.search('쥬키니테스트토큰', tags=['railway']))
        self.assertEqual(len(hits_mismatch), 0)

        hits_other = _lib_hits(knowledge_search.search('레일웨이테스트토큰', tags=['railway']))
        self.assertEqual(len(hits_other), 1)
        self.assertEqual(hits_other[0]['tags'], ['railway', 'bridge'])

    def test_no_tags_param_is_farm_wide_default(self):
        """Omitting `tags` must behave exactly as before P1 (no narrowing) —
        existing callers (e.g. _manual_grounding) pass no tags and must keep
        seeing every enabled library item, unaffected by this filter."""
        self._enable_digest()
        source = self._make_source()
        self._make_chunk(source, '토마토 개화기 관리', '쥬키니테스트토큰 관련 정보',
                          tags='tomato,flowering')

        hits = [h for h in knowledge_search.search('쥬키니테스트토큰') if h['origin'] == 'library']
        self.assertEqual(len(hits), 1)

    def test_untagged_item_always_a_candidate(self):
        """An item with no tags hasn't been scoped by anyone — it must not be
        excluded by a tag filter it never claimed, same as the global manual."""
        self._enable_digest()
        source = self._make_source()
        self._make_chunk(source, '일반 정보', '쥬키니테스트토큰 관련 미태그 정보', tags=None)

        hits = [h for h in knowledge_search.search('쥬키니테스트토큰', tags=['tomato'])
                if h['origin'] == 'library']
        self.assertEqual(len(hits), 1)

    def test_expired_ttl_excluded_regardless_of_tags(self):
        self._enable_digest()
        source = self._make_source()
        past = datetime.utcnow() - timedelta(days=1)
        future = datetime.utcnow() + timedelta(days=1)
        self._make_chunk(source, '만료된 경보', '쥬키니테스트토큰 만료 정보',
                          tags='pest', ttl=past)
        self._make_chunk(source, '유효한 경보', '쥬키니테스트토큰 유효 정보',
                          tags='pest', ttl=future)

        hits = [h for h in knowledge_search.search('쥬키니테스트토큰', tags=['pest'])
                if h['origin'] == 'library']
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]['heading'], '유효한 경보')

    # -- §6: provenance-differentiated citation tags in search_as_text -------

    def test_search_as_text_tags_by_provenance(self):
        """search_as_text() must prefix each library block with a citation tag
        that matches its provenance, so the model-facing directive
        (_MANUAL_GROUNDING_DIRECTIVE) can tell an authoritative source from
        the AI's own unconfirmed note. No writer produces 'external_authority'
        /'data_derived' rows yet (P3/P4) — this exercises the formatting path
        directly against the schema so it's already correct once they do."""
        self._enable_digest()
        source = self._make_source()
        self._make_chunk(source, '권위 항목', '쥬키니테스트토큰 권위 정보',
                          tags='auth', provenance='external_authority',
                          attribution='RDA SmartFarm API')
        self._make_chunk(source, '미확인 항목', '쥬키니테스트토큰 미확인 정보',
                          tags='auth', provenance='ai_curated',
                          attribution='대화 2026-07-18')
        self._make_chunk(source, '일반 항목', '쥬키니테스트토큰 일반 정보',
                          tags='auth', provenance='user_provided')

        text = knowledge_search.search_as_text('쥬키니테스트토큰', tags=['auth'], top_k=10)
        self.assertIn('[권위] 권위 항목', text)
        self.assertIn('RDA SmartFarm API', text)
        self.assertIn('[AI 정리 — 미확인] 미확인 항목', text)
        self.assertIn('[Library] 일반 항목', text)

    # -- P3: external-authority structured adapter (§7/§10) ------------------

    def test_smartfarm_setpoint_returns_structured_answer_not_shredded(self):
        """The pre-P3 bug: this same row used to be shredded into 8 separate
        flat AIContextRecord strings ('smartfarm.tomato.flowering.opt_temp_min
        = "18 °C"'). Post-P3, a query must get back ONE coherent structured
        block with all the ranges together."""
        row = ExtSmartfarmSetpoints(
            crop_type='tomato', growth_stage='flowering',
            opt_temp_min=18, opt_temp_max=26,
            opt_humidity_min=60, opt_humidity_max=80,
            opt_co2_min=400, opt_co2_max=800,
        )
        db.session.add(row)
        db.session.commit()

        hits = knowledge_search.search('tomato flowering 설정값')
        lib_hits = [h for h in hits if h['origin'] == 'library']
        self.assertEqual(len(lib_hits), 1)
        hit = lib_hits[0]
        self.assertEqual(hit['provenance'], 'external_authority')
        self.assertEqual(hit['content_kind'], 'structured')
        self.assertEqual(hit['tags'], ['tomato', 'flowering'])
        self.assertIn('18', hit['content'])
        self.assertIn('26', hit['content'])
        self.assertIn('60', hit['content'])
        self.assertIn('80', hit['content'])
        # One block, not eight rows — the whole point of P3.
        self.assertEqual(hit['content'].count('°C'), 1)

    def test_smartfarm_tags_scope_by_crop_and_stage(self):
        db.session.add(ExtSmartfarmSetpoints(
            crop_type='tomato', growth_stage='flowering', opt_temp_min=18, opt_temp_max=26))
        db.session.add(ExtSmartfarmSetpoints(
            crop_type='lettuce', growth_stage='seedling', opt_temp_min=15, opt_temp_max=20))
        db.session.commit()

        tomato_hits = [h for h in knowledge_search.search('설정값', tags=['tomato'])
                       if h['origin'] == 'library']
        self.assertEqual(len(tomato_hits), 1)
        self.assertEqual(tomato_hits[0]['tags'], ['tomato', 'flowering'])

        lettuce_hits = [h for h in knowledge_search.search('설정값', tags=['lettuce'])
                         if h['origin'] == 'library']
        self.assertEqual(len(lettuce_hits), 1)
        self.assertEqual(lettuce_hits[0]['tags'], ['lettuce', 'seedling'])

    def test_nongsaro_guide_surfaces_as_prose(self):
        db.session.add(ExtNongsaroGuides(
            crop_type='tomato', guide_type='cultivation',
            title='토마토 재배 가이드', content='정식 후 20일간 관수를 자제한다.',
        ))
        db.session.commit()

        hits = [h for h in knowledge_search.search('토마토 재배 가이드')
                if h['origin'] == 'library']
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]['provenance'], 'external_authority')
        self.assertEqual(hits[0]['content_kind'], 'prose')
        self.assertIn('관수를 자제', hits[0]['content'])

    def test_pest_alert_excluded_past_six_hour_ttl(self):
        """013_DATA_SOURCES.yaml states a 6h TTL for EXT-KR-03 — a stale pest
        alert must not be injected as if it were current."""
        stale = ExtPestAlerts(
            crop_type='tomato', pest_code='TOMPEST01', pest_name='담배가루이',
            severity='high', region='전국', control_method='천적 방사',
        )
        stale.fetched_at = datetime.now(timezone.utc) - timedelta(hours=7)
        db.session.add(stale)
        db.session.commit()

        hits = [h for h in knowledge_search.search('담배가루이') if h['origin'] == 'library']
        self.assertEqual(len(hits), 0)

    def test_pest_alert_included_within_six_hour_ttl(self):
        fresh = ExtPestAlerts(
            crop_type='tomato', pest_code='TOMPEST02', pest_name='총채벌레',
            severity='medium', region='전국', control_method='끈끈이트랩 설치',
        )
        fresh.fetched_at = datetime.now(timezone.utc) - timedelta(hours=1)
        db.session.add(fresh)
        db.session.commit()

        hits = [h for h in knowledge_search.search('총채벌레') if h['origin'] == 'library']
        self.assertEqual(len(hits), 1)
        self.assertIn('끈끈이트랩', hits[0]['content'])

    # ── 빈 라이브러리를 정직하게 말한다 (2026-08-22) ────────────────────────
    #
    # 자료가 없는 설치에서 "Try different keywords" 는 **검색어가 틀렸다는 뜻으로
    # 읽힌다.** 모델은 키워드만 바꿔 가며 같은 빈손을 반복하다가, 라이브러리가
    # 비었다는 사실을 모른 채 자기 지식으로 넘어가고 그것을 출처처럼 적는다.

    def test_populated_flag_follows_the_chunks(self):
        self._enable_digest()
        self.assertFalse(knowledge_search.library_is_populated())
        self._make_chunk(self._make_source(), '딸기 육묘', '내용')
        self.assertTrue(knowledge_search.library_is_populated())

    def test_digest_switch_off_reads_as_empty(self):
        """스위치가 꺼져 있으면 청크가 있어도 검색에 실리지 않는다
        (`_load_library_sections` 가 곧바로 [] 를 돌려준다) — 사용자에게는
        자료가 없는 것과 같으므로 여기서도 '비었다' 로 답해야 한다."""
        self._make_chunk(self._make_source(), '딸기 육묘', '내용')
        self.assertFalse(knowledge_search.library_is_populated())

    def test_empty_library_is_said_even_when_the_manual_matched(self):
        """**빈 결과만 보고 판정하면 안 된다** — 검색은 저장소에 늘 있는 AoT
        매뉴얼도 함께 뒤지므로 도메인 질문에도 엉뚱한 매뉴얼 섹션이 느슨하게
        걸린다. 그러면 결과가 비지 않아 '자료 없음' 분기를 영영 안 탄다."""
        from aot.ai.services.aot_data_tool_service import AoTDataToolService as S

        res = S.knowledge_search_tool(query='상추 생육단계별 재배 관리')
        self.assertTrue(res.get('library_empty'), res)
        self.assertIn('EMPTY', res['result'])

    def test_populated_library_gets_no_empty_notice(self):
        from aot.ai.services.aot_data_tool_service import AoTDataToolService as S

        self._enable_digest()
        self._make_chunk(self._make_source(), '상추 육묘',
                         '본엽 3~4매에 정식한다.')
        res = S.knowledge_search_tool(query='상추 육묘')
        self.assertNotIn('library_empty', res)
        self.assertNotIn('EMPTY', res['result'])

    # ── 띄어쓰기 없는 문자도 검색된다 (2026-08-22) ──────────────────────────
    #
    # AoT 는 22개 언어로 출시되는데 그중 넷(ja·zh·zh_Hant·th)은 지식 라이브러리를
    # 아예 쓸 수 없었다. 문장 전체가 토큰 하나가 되고 그 하나가 Latin 취급으로
    # `\b` 단어경계 매칭을 받아 아무것도 못 찾았다 — 에러 없이 0건이라 아무도
    # 모른다(라이브러리가 비었다는 안내조차 안 뜬다, 자료는 실제로 있으므로).

    def test_space_separated_languages_tokenize_exactly_as_before(self):
        """bigram 도입이 **띄어쓰기 쓰는 언어를 건드리면 안 된다** — 한국어의
        어간 규칙과 영어 불용어 제거는 그대로여야 한다."""
        self.assertEqual(
            knowledge_search._tokenize('상추 생육단계별 재배관리'),
            ['상추', '생육단계별', '생육', '재배관리', '재배'])
        self.assertEqual(
            knowledge_search._tokenize('lettuce growth stage cultivation'),
            ['lettuce', 'growth', 'stage', 'cultivation'])
        # 'the'/'for' 는 불용어라 빠진다(예전과 같음).
        self.assertNotIn('the', knowledge_search._tokenize('the lettuce'))

    def test_korean_does_not_get_bigrams(self):
        """한국어에 bigram 을 물리면 '재배관리' 가 '배관'(수도 배관)까지 만들어
        엉뚱한 문서에 걸린다. 한국어는 띄어쓰기를 쓰므로 어간이면 충분하다."""
        self.assertNotIn('배관', knowledge_search._tokenize('재배관리'))

    def _find(self, query):
        return [h for h in knowledge_search.search(query) if h['origin'] == 'library']

    def test_japanese_document_is_findable(self):
        self._enable_digest()
        self._make_chunk(self._make_source(), 'レタスの栽培',
                         'レタスは生育ステージごとに栽培管理を変える。')
        self.assertEqual(len(self._find('レタスの生育ステージ別栽培管理')), 1)

    def test_chinese_document_is_findable(self):
        self._enable_digest()
        self._make_chunk(self._make_source(), '生菜栽培',
                         '生菜按生育阶段进行栽培管理。')
        self.assertEqual(len(self._find('生菜生育阶段栽培管理')), 1)

    def test_thai_document_is_findable(self):
        self._enable_digest()
        self._make_chunk(self._make_source(), 'การปลูกผักกาดหอม',
                         'ผักกาดหอมต้องจัดการการปลูกตามระยะการเจริญเติบโต')
        self.assertEqual(len(self._find('การปลูกผักกาดหอม')), 1)

    def test_bigram_count_is_capped(self):
        """긴 문장은 글자 수만큼 bigram 이 늘어난다 — 상한이 없으면 폭주한다."""
        toks = knowledge_search._tokenize('栽' * 500)
        self.assertLessEqual(len(toks), knowledge_search._MAX_QUERY_TOKENS)

    def test_unknown_state_does_not_claim_empty(self):
        """판정하지 못했을 때 '비었다' 고 단정하면 자료가 있는 설치에서 없는
        안내를 하게 된다 — 모르면 평소 문구가 낫다."""
        import aot.databases.models as _m

        real = _m.AIGlobalSettings.query
        try:
            type(_m.AIGlobalSettings).query = property(
                lambda self: (_ for _ in ()).throw(RuntimeError('DB 없음')))
            self.assertTrue(knowledge_search.library_is_populated())
        finally:
            type(_m.AIGlobalSettings).query = real


if __name__ == '__main__':
    unittest.main()
