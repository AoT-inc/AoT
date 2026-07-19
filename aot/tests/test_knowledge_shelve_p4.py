# coding=utf-8
"""
P4 unit tests — knowledge_shelve write verb (docs/design/ai-library-redesign.md
§4, §3.3). In-memory sqlite, isolated app context — no live DB touched (see
feedback_never_test_against_live_db).
"""
import os
import sys
import unittest
from datetime import datetime, timedelta

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), os.path.pardir, os.path.pardir)))
os.environ["ALEMBIC_RUNNING"] = "1"

from flask import Flask

from aot.aot_flask.extensions import db
from aot.databases.models import AIContextSource, AIGlobalSettings, AIKnowledgeChunk
from aot.ai.services import knowledge_shelve_service as shelve_svc
from aot.ai.services import knowledge_search


def _make_test_app():
    """See aot/tests/test_knowledge_library_p1.py::_make_test_app for why this
    doesn't use create_app() (pre-existing QueuePool/':memory:' incompatibility,
    unrelated to this change). Babel IS registered here (unlike that file) —
    this test imports aot_data_tool_service.py (the knowledge_shelve tool
    handler), which transitively imports config_translations.py, which calls
    lazy_gettext(...) at module level; without a registered Babel extension,
    stringifying that LazyString raises KeyError('babel') the first time
    anything imports that module inside a pushed app context."""
    from flask_babel import Babel
    app = Flask(__name__)
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['TESTING'] = True
    db.init_app(app)
    Babel(app)
    return app


class TestKnowledgeShelveP4(unittest.TestCase):
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
        shelve_svc._DAILY_QUOTA = 50  # restore in case a test lowered it

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.app_context.pop()
        knowledge_search._library_sections = []
        knowledge_search._library_stamp = None

    def _enable_digest(self):
        """knowledge_search._load_library_sections() no-ops (by design) unless
        this flag is on — the shelve() write itself doesn't depend on it, only
        the read-back-via-search assertions below need it."""
        AIGlobalSettings(id=1, knowledge_digest_enabled=True).save()

    # -- basic write + provenance/trust invariants ---------------------------

    def test_shelve_writes_ai_curated_low_trust(self):
        result = shelve_svc.shelve_knowledge(
            content='3번 존은 오후에 습도가 급상승하는 경향이 있다.',
            tags=['tomato', 'zone-3'],
            attribution='대화 2026-07-19',
        )
        self.assertEqual(result['status'], 'created')
        chunk = AIKnowledgeChunk.query.filter_by(unique_id=result['chunk_id']).first()
        self.assertEqual(chunk.provenance, 'ai_curated')
        self.assertEqual(chunk.context_state, 'system_generated')  # never grants trust at write time
        self.assertEqual(chunk.tags, 'tomato,zone-3')
        self.assertEqual(chunk.attribution, '대화 2026-07-19')

    def test_shelve_reuses_reserved_source_not_one_per_call(self):
        r1 = shelve_svc.shelve_knowledge(content='첫 번째 관찰', tags=['a'])
        r2 = shelve_svc.shelve_knowledge(content='두 번째 관찰', tags=['b'])
        c1 = AIKnowledgeChunk.query.filter_by(unique_id=r1['chunk_id']).first()
        c2 = AIKnowledgeChunk.query.filter_by(unique_id=r2['chunk_id']).first()
        self.assertEqual(c1.source_id, c2.source_id)
        self.assertEqual(AIContextSource.query.count(), 1)
        source = AIContextSource.query.first()
        # Must never get a scheduled sync job (ai_scheduler_service skips
        # interval_min <= 0) — this source is written to directly, never synced.
        self.assertEqual(source.sync_interval_min, 0)

    def test_shelve_requires_nonempty_tags(self):
        result = shelve_svc.shelve_knowledge(content='태그 없는 메모', tags=[])
        self.assertEqual(result['status'], 'rejected')
        self.assertEqual(AIKnowledgeChunk.query.count(), 0)

    def test_shelve_requires_nonempty_content(self):
        result = shelve_svc.shelve_knowledge(content='   ', tags=['a'])
        self.assertEqual(result['status'], 'rejected')

    # -- §3.3 governance: dedup / quota / contradiction flag ------------------

    def test_shelve_dedups_identical_content(self):
        r1 = shelve_svc.shelve_knowledge(content='동일한 내용입니다.', tags=['a'])
        r2 = shelve_svc.shelve_knowledge(content='동일한 내용입니다.', tags=['a'])
        self.assertEqual(r1['status'], 'created')
        self.assertEqual(r2['status'], 'duplicate')
        self.assertEqual(r2['chunk_id'], r1['chunk_id'])
        self.assertEqual(AIKnowledgeChunk.query.count(), 1)

    def test_shelve_quota_blocks_after_limit(self):
        shelve_svc._DAILY_QUOTA = 2
        r1 = shelve_svc.shelve_knowledge(content='메모 1', tags=['a'])
        r2 = shelve_svc.shelve_knowledge(content='메모 2', tags=['a'])
        r3 = shelve_svc.shelve_knowledge(content='메모 3', tags=['a'])
        self.assertEqual(r1['status'], 'created')
        self.assertEqual(r2['status'], 'created')
        self.assertEqual(r3['status'], 'quota_exceeded')
        self.assertEqual(AIKnowledgeChunk.query.count(), 2)

    def test_shelve_flags_heading_collision_with_peer_trust_item(self):
        """Two DIFFERENT ai_curated notes, same tags, same heading — must be
        flagged (surfaced for review) but NOT blocked (both are written)."""
        self._enable_digest()
        r1 = shelve_svc.shelve_knowledge(
            content='3번 존 습도는 오후 2시경 70%까지 오른다.',
            tags=['tomato', 'zone-3'], heading='3번 존 오후 습도',
        )
        r2 = shelve_svc.shelve_knowledge(
            content='3번 존 습도는 오후 4시경 85%까지 오른다.',
            tags=['tomato', 'zone-3'], heading='3번 존 오후 습도',
        )
        self.assertEqual(r1['status'], 'created')
        self.assertIsNone(r1['flagged_reason'])  # nothing to collide with yet
        self.assertEqual(r2['status'], 'created')
        self.assertIsNotNone(r2['flagged_reason'])
        chunk2 = AIKnowledgeChunk.query.filter_by(unique_id=r2['chunk_id']).first()
        self.assertIsNotNone(chunk2.flagged_reason)
        # Still searchable — flagging surfaces for review, doesn't exclude.
        hits = knowledge_search.search('3번 존 습도')
        self.assertEqual(len([h for h in hits if h['origin'] == 'library']), 2)

    def test_shelve_no_flag_when_covering_authoritative_topic(self):
        """A collision with external_authority/user_provided is NOT flagged
        here — citation-time preference (already built, P2) handles that
        case; flagging every ai_curated note that overlaps an authoritative
        one would just be noise (see module docstring)."""
        source = AIContextSource(
            facility_id='default', source_name='SOP', source_type='document',
            parameter_name='test.sop',
        )
        source.save()
        import hashlib
        authoritative = AIKnowledgeChunk(
            source_id=source.source_id, source_name=source.source_name,
            section_title='개화기 관리', digest_text='공식 가이드 내용',
            content_hash=hashlib.sha256(b'official').hexdigest(),
            provenance='user_provided', content_kind='prose',
            tags='tomato,flowering', is_enabled=True,
        )
        db.session.add(authoritative)
        db.session.commit()

        result = shelve_svc.shelve_knowledge(
            content='내가 관찰한 개화기 특징은 다르다.',
            tags=['tomato', 'flowering'], heading='개화기 관리',
        )
        self.assertEqual(result['status'], 'created')
        self.assertIsNone(result['flagged_reason'])

    # -- roundtrip: shelve -> search -> provenance-tagged injection ----------

    def test_shelve_then_search_surfaces_as_unconfirmed(self):
        self._enable_digest()
        shelve_svc.shelve_knowledge(
            content='쥬키니테스트토큰 — 온실 3동은 환기창을 늦게 열면 결로가 심해진다.',
            tags=['ventilation', 'zone-3'], heading='결로 관찰',
            attribution='대화 2026-07-19',
        )
        text = knowledge_search.search_as_text('쥬키니테스트토큰', tags=['ventilation'])
        self.assertIn('[AI 정리 — 미확인] 결로 관찰', text)
        self.assertIn('대화 2026-07-19', text)

    # -- tool wiring: the actual model-callable entry point, not just the ------
    # -- underlying service (§ tool_registry.py / aot_data_tool_service.py)   --

    def test_tool_registry_maps_to_handler_and_is_not_approval_gated(self):
        from aot.ai.services import tool_registry as R
        from aot.ai.services.aot_data_tool_service import AoTDataToolService

        tool_map = R.build_tool_map()
        self.assertIn('knowledge_shelve', tool_map)
        self.assertIs(tool_map['knowledge_shelve'], AoTDataToolService.knowledge_shelve)
        self.assertIn('knowledge_shelve', R.virtual_tool_registry())
        self.assertNotIn('knowledge_shelve', R.virtual_approval_tools())
        self.assertNotIn('knowledge_shelve', R.approval_required_tools())

    def test_handler_end_to_end_defaults_attribution_and_converts_ttl_hours(self):
        from aot.ai.services.aot_data_tool_service import AoTDataToolService

        result = AoTDataToolService.knowledge_shelve(
            content='총채벌레 발견 — 3동 남측', tags='pest,zone-3', ttl_hours=2,
        )
        self.assertEqual(result['status'], 'created')
        chunk = AIKnowledgeChunk.query.filter_by(unique_id=result['chunk_id']).first()
        self.assertIsNotNone(chunk.attribution)
        self.assertIn(str(datetime.utcnow().date()), chunk.attribution)  # server-clock default, not LLM-guessed
        self.assertIsNotNone(chunk.ttl)
        self.assertLess(chunk.ttl, datetime.utcnow() + timedelta(hours=3))
        self.assertGreater(chunk.ttl, datetime.utcnow() + timedelta(hours=1))

    def test_handler_rejects_missing_content_or_tags(self):
        from aot.ai.services.aot_data_tool_service import AoTDataToolService

        r1 = AoTDataToolService.knowledge_shelve(content=None, tags='a')
        self.assertIn('error', r1)
        r2 = AoTDataToolService.knowledge_shelve(content='x', tags=None)
        self.assertIn('error', r2)
        self.assertEqual(AIKnowledgeChunk.query.count(), 0)


if __name__ == '__main__':
    unittest.main()
