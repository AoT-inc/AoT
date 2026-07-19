# coding=utf-8
"""
P5 unit tests — knowledge_promotion_service (docs/design/ai-library-redesign.md
§3.2, §8). In-memory sqlite, isolated app context — no live DB touched (see
feedback_never_test_against_live_db).
"""
import hashlib
import os
import sys
import unittest

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), os.path.pardir, os.path.pardir)))
os.environ["ALEMBIC_RUNNING"] = "1"

from flask import Flask

from aot.aot_flask.extensions import db
from aot.databases.models import AIContextSource, AIGlobalSettings, AIKnowledgeChunk
from aot.ai.services import knowledge_shelve_service as shelve_svc
from aot.ai.services import knowledge_promotion_service as promo_svc
from aot.ai.services import knowledge_search


def _make_test_app():
    """See test_knowledge_library_p1.py::_make_test_app for the QueuePool/
    ':memory:' rationale; Babel is registered as in test_knowledge_shelve_p4.py
    since this file also imports service modules that pull in translations."""
    from flask_babel import Babel
    app = Flask(__name__)
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['TESTING'] = True
    db.init_app(app)
    Babel(app)
    return app


class TestKnowledgePromotionP5(unittest.TestCase):
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
        promo_svc._REUSE_PROMOTION_THRESHOLD = 5

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.app_context.pop()
        knowledge_search._library_sections = []
        knowledge_search._library_stamp = None

    def _enable_digest(self):
        AIGlobalSettings(id=1, knowledge_digest_enabled=True).save()

    def _shelve(self, content='내용', tags='a', heading='제목'):
        r = shelve_svc.shelve_knowledge(content=content, tags=tags, heading=heading)
        self.assertEqual(r['status'], 'created')
        return r['chunk_id']

    # -- human-driven transitions ---------------------------------------------

    def test_confirm_promotes_to_user_confirmed(self):
        cid = self._shelve()
        result = promo_svc.confirm_item(cid)
        self.assertTrue(result['success'])
        chunk = AIKnowledgeChunk.query.filter_by(unique_id=cid).first()
        self.assertEqual(chunk.context_state, 'user_confirmed')
        self.assertTrue(chunk.is_enabled)

    def test_edit_updates_content_and_confirms(self):
        cid = self._shelve(content='원래 내용', heading='원래 제목', tags='a')
        result = promo_svc.edit_item(cid, content='수정된 내용', heading='수정된 제목')
        self.assertTrue(result['success'])
        chunk = AIKnowledgeChunk.query.filter_by(unique_id=cid).first()
        self.assertEqual(chunk.digest_text, '수정된 내용')
        self.assertEqual(chunk.section_title, '수정된 제목')
        self.assertEqual(chunk.context_state, 'user_confirmed')  # §3.2: edit implies confirm

    def test_edit_rejects_empty_tags(self):
        cid = self._shelve()
        result = promo_svc.edit_item(cid, tags=[])
        self.assertFalse(result['success'])
        chunk = AIKnowledgeChunk.query.filter_by(unique_id=cid).first()
        self.assertEqual(chunk.context_state, 'system_generated')  # unchanged

    def test_retire_excludes_from_search_but_keeps_row(self):
        self._enable_digest()
        cid = self._shelve(content='쥬키니테스트토큰 은퇴 예정 항목', tags='pest')
        self.assertEqual(
            len([h for h in knowledge_search.search('쥬키니테스트토큰') if h['origin'] == 'library']), 1
        )

        result = promo_svc.retire_item(cid)
        self.assertTrue(result['success'])
        chunk = AIKnowledgeChunk.query.filter_by(unique_id=cid).first()
        self.assertEqual(chunk.context_state, 'retired')
        self.assertFalse(chunk.is_enabled)
        self.assertIsNotNone(chunk)  # row preserved, not deleted

        # invalidate the process cache (is_enabled changed, updated_at bumped)
        self.assertEqual(
            len([h for h in knowledge_search.search('쥬키니테스트토큰') if h['origin'] == 'library']), 0
        )

    def test_reactivate_undoes_retire_without_granting_confirmed_trust(self):
        cid = self._shelve()
        promo_svc.retire_item(cid)
        result = promo_svc.reactivate_item(cid)
        self.assertTrue(result['success'])
        chunk = AIKnowledgeChunk.query.filter_by(unique_id=cid).first()
        self.assertEqual(chunk.context_state, 'system_generated')
        self.assertTrue(chunk.is_enabled)

    def test_transitions_only_touch_ai_curated_items(self):
        """confirm/edit/retire must not silently promote a non-ai_curated
        (e.g. external_authority) row even if someone passes its chunk_id."""
        source = AIContextSource(
            facility_id='default', source_name='RDA', source_type='rest_api',
            parameter_name='test.rda',
        )
        source.save()
        authoritative = AIKnowledgeChunk(
            source_id=source.source_id, source_name=source.source_name,
            section_title='공식자료', digest_text='공식 내용',
            content_hash=hashlib.sha256(b'official-p5').hexdigest(),
            provenance='external_authority', content_kind='prose',
            tags='a', is_enabled=True, context_state='corroborated',
        )
        db.session.add(authoritative)
        db.session.commit()

        result = promo_svc.confirm_item(authoritative.unique_id)
        self.assertFalse(result['success'])

    # -- list_review_items + advisory authoritative-match badge --------------

    def test_list_review_items_returns_only_ai_curated(self):
        cid = self._shelve()
        source = AIContextSource(
            facility_id='default', source_name='RDA', source_type='rest_api',
            parameter_name='test.rda2',
        )
        source.save()
        db.session.add(AIKnowledgeChunk(
            source_id=source.source_id, source_name=source.source_name,
            section_title='공식자료', digest_text='공식 내용',
            content_hash=hashlib.sha256(b'official-p5-2').hexdigest(),
            provenance='external_authority', content_kind='prose',
            tags='x', is_enabled=True,
        ))
        db.session.commit()

        items = promo_svc.list_review_items()
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]['chunk_id'], cid)

    def test_list_review_items_flags_advisory_authoritative_match(self):
        """Same tag + same heading as an authoritative item -> advisory badge,
        but NOT auto-promoted (still system_generated) — see module docstring
        on why this stays a human decision."""
        source = AIContextSource(
            facility_id='default', source_name='SmartFarm', source_type='rest_api',
            parameter_name='test.sf',
        )
        source.save()
        db.session.add(AIKnowledgeChunk(
            source_id=source.source_id, source_name='RDA SmartFarm (EXT-KR-01)',
            section_title='개화기 관리', digest_text='공식 설정값',
            content_hash=hashlib.sha256(b'official-p5-3').hexdigest(),
            provenance='external_authority', content_kind='structured',
            tags='tomato,flowering', is_enabled=True,
        ))
        db.session.commit()

        cid = self._shelve(content='내가 본 개화기 특징', heading='개화기 관리', tags='tomato,flowering')
        items = {i['chunk_id']: i for i in promo_svc.list_review_items()}
        self.assertEqual(items[cid]['authoritative_match'], 'RDA SmartFarm (EXT-KR-01)')
        self.assertEqual(items[cid]['context_state'], 'system_generated')  # NOT auto-promoted

    def test_list_review_items_no_match_when_no_authoritative_overlap(self):
        cid = self._shelve(heading='아무도 다루지 않은 주제', tags='a')
        items = {i['chunk_id']: i for i in promo_svc.list_review_items()}
        self.assertIsNone(items[cid]['authoritative_match'])

    # -- reuse-based auto-corroboration (fully automatic path) ---------------

    def test_reuse_below_threshold_does_not_promote(self):
        self._enable_digest()
        cid = self._shelve(content='쥬키니테스트토큰 재사용 테스트', tags='a')
        for _ in range(3):
            knowledge_search.search('쥬키니테스트토큰')
        chunk = AIKnowledgeChunk.query.filter_by(unique_id=cid).first()
        self.assertEqual(chunk.reuse_count, 3)
        self.assertEqual(chunk.context_state, 'system_generated')

    def test_reuse_at_threshold_auto_promotes_to_corroborated(self):
        self._enable_digest()
        promo_svc._REUSE_PROMOTION_THRESHOLD = 3
        cid = self._shelve(content='쥬키니테스트토큰 승격 테스트', tags='a')
        for _ in range(3):
            knowledge_search.search('쥬키니테스트토큰')
        chunk = AIKnowledgeChunk.query.filter_by(unique_id=cid).first()
        self.assertGreaterEqual(chunk.reuse_count, 3)
        self.assertEqual(chunk.context_state, 'corroborated')

    def test_reuse_count_increment_does_not_bust_library_cache(self):
        """The whole point of the raw-SQL increment: reuse bookkeeping must
        NOT invalidate knowledge_search's process cache on every hit (that
        would defeat the cache entirely for any install with active
        ai_curated content) — only an actual state change should."""
        self._enable_digest()
        self._shelve(content='쥬키니테스트토큰 캐시 테스트', tags='a')
        knowledge_search.search('쥬키니테스트토큰')  # populates the cache + stamp
        stamp_after_first = knowledge_search._library_stamp

        knowledge_search.search('쥬키니테스트토큰')  # a second hit — reuse_count bumps
        stamp_after_second = knowledge_search._library_stamp
        self.assertEqual(stamp_after_first, stamp_after_second)

    def test_confirmed_item_is_not_further_reuse_tracked(self):
        """note_reuse only touches system_generated rows — a user_confirmed
        item already has full trust and shouldn't be reuse-counted at all."""
        self._enable_digest()
        cid = self._shelve(content='쥬키니테스트토큰 이미확인', tags='a')
        promo_svc.confirm_item(cid)
        for _ in range(10):
            knowledge_search.search('쥬키니테스트토큰')
        chunk = AIKnowledgeChunk.query.filter_by(unique_id=cid).first()
        self.assertEqual(chunk.reuse_count, 0)
        self.assertEqual(chunk.context_state, 'user_confirmed')

    # -- citation tag must track trust_state, not just provenance ------------
    # (regression: a confirm()/auto-corroborate must change how the item is
    # cited — provenance alone is immutable and the wrong thing to key off)

    def test_confirmed_ai_curated_item_cites_as_confirmed_not_unconfirmed(self):
        self._enable_digest()
        cid = self._shelve(content='쥬키니테스트토큰 인용태그 확인', tags='a', heading='인용 테스트')
        promo_svc.confirm_item(cid)
        text = knowledge_search.search_as_text('쥬키니테스트토큰')
        self.assertIn('[AI 정리 — 확인됨] 인용 테스트', text)
        self.assertNotIn('[AI 정리 — 미확인] 인용 테스트', text)

    def test_corroborated_ai_curated_item_cites_as_corroborated(self):
        self._enable_digest()
        promo_svc._REUSE_PROMOTION_THRESHOLD = 2
        cid = self._shelve(content='쥬키니테스트토큰 교차검증 인용', tags='a', heading='교차검증 테스트')
        for _ in range(2):
            knowledge_search.search('쥬키니테스트토큰')
        chunk = AIKnowledgeChunk.query.filter_by(unique_id=cid).first()
        self.assertEqual(chunk.context_state, 'corroborated')

        text = knowledge_search.search_as_text('쥬키니테스트토큰')
        self.assertIn('[AI 정리 — 교차검증됨] 교차검증 테스트', text)


if __name__ == '__main__':
    unittest.main()
