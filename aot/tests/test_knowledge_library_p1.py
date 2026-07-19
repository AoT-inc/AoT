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


if __name__ == '__main__':
    unittest.main()
