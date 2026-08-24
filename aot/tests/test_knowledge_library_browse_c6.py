# coding=utf-8
"""
C6 — 지식 저장소의 사람 쪽 면(browse + 직접 입력).

왜 이 계층이 따로 있는가. P5 리뷰 화면은 `provenance='ai_curated'` 만 보여준다
— "AI 가 뭘 썼는지 검사한다" 가 그 화면의 일이기 때문이다. 그런데 그것만으로는
운영자가 저장소에 무엇이 들어 있는지 볼 수 없고, **비어 있는 것과 고장난 것을
구분할 수 없다.** 그리고 자기가 이미 아는 사실을 넣으려면 AI 턴이나 외부 피드
등록을 거쳐야 했다 — 10년 농사지은 사람이 "북쪽 구획은 7월에 물이 찬다" 를
적으려고 AI 에게 부탁해야 하는 구조였다.

In-memory sqlite, 라이브 DB 미접촉(feedback_never_test_against_live_db).
"""
import os
import sys
import unittest

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), os.path.pardir, os.path.pardir)))
os.environ["ALEMBIC_RUNNING"] = "1"

from flask import Flask
from flask_babel import Babel

from aot.aot_flask.extensions import db
from aot.databases.models import AIKnowledgeChunk
from aot.ai.services import knowledge_library_service as lib
from aot.ai.services import knowledge_shelve_service as shelve_svc


def _make_test_app():
    app = Flask(__name__)
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['TESTING'] = True
    db.init_app(app)
    Babel(app)
    return app


class TestKnowledgeBrowseC6(unittest.TestCase):
    def setUp(self):
        self.app = _make_test_app()
        self.ctx = self.app.app_context()
        self.ctx.push()
        db.create_all()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.ctx.pop()

    # -- 직접 입력 --------------------------------------------------------

    def test_hand_entered_knowledge_is_trusted_because_a_person_wrote_it(self):
        """§3.1: 사용자가 확정한 사실은 높은 신뢰. 시스템에서 쓰기 시점에
        신뢰를 주는 유일한 경로이고, 내용이 권위 있어 보여서가 아니라 사람이
        직접 썼기 때문에 준다."""
        r = lib.add_user_knowledge(content='북쪽 구획은 7월에 물이 찬다.', tags='배수,북쪽구획')
        self.assertTrue(r['success'])
        row = AIKnowledgeChunk.query.filter_by(unique_id=r['chunk_id']).first()
        self.assertEqual('user_provided', row.provenance)
        self.assertEqual('user_confirmed', row.context_state)

    def test_hand_entry_still_requires_tags(self):
        r = lib.add_user_knowledge(content='내용은 있다', tags='')
        self.assertFalse(r['success'])

    def test_hand_entry_refuses_duplicate_content(self):
        lib.add_user_knowledge(content='같은 글', tags='a')
        r = lib.add_user_knowledge(content='같은 글', tags='b')
        self.assertFalse(r['success'])
        self.assertIn('chunk_id', r)

    def test_hand_entry_and_ai_shelf_get_separate_source_rows(self):
        """소스 목록은 사람이 '이 지식이 어디서 왔나' 를 한눈에 보는 자리다 —
        둘을 한 행에 합치면 그 구분이 사라진다."""
        lib.add_user_knowledge(content='사람이 쓴 것', tags='x')
        shelve_svc.shelve_knowledge(content='AI 가 쓴 것', tags='x')
        names = {r.source_name for r in AIKnowledgeChunk.query.all()}
        self.assertEqual(2, len(names), names)

    # -- 열람 -------------------------------------------------------------

    def _seed(self):
        lib.add_user_knowledge(content='가을무는 파종 후 80일에 수확한다.', tags='무,가을무',
                                heading='가을무 수확')
        shelve_svc.shelve_knowledge(content='밸브는 45초 뒤 안정된다.', tags='밸브',
                                     heading='밸브 안정화')

    def test_browse_returns_every_provenance_not_just_ai_curated(self):
        """리뷰 화면이 못 하던 바로 그 일이다."""
        self._seed()
        provs = {i['provenance'] for i in lib.browse()['items']}
        self.assertEqual({'user_provided', 'ai_curated'}, provs)

    def test_tag_filter_does_not_match_a_longer_tag_that_starts_the_same(self):
        """태그가 한 컬럼에 쉼표로 이어 붙어 있어 LIKE 로 찾는다 — '무' 가
        '무름병' 에 걸리면 필터가 거짓말을 한다."""
        lib.add_user_knowledge(content='무 이야기', tags='무')
        lib.add_user_knowledge(content='무름병 이야기', tags='무름병')
        items = lib.browse(tag='무')['items']
        self.assertEqual(1, len(items))
        self.assertIn('무 이야기', items[0]['content'])

    def test_text_query_matches_heading_and_body(self):
        self._seed()
        self.assertEqual(1, len(lib.browse(query='가을무')['items']))
        self.assertEqual(1, len(lib.browse(query='45초')['items']))
        self.assertEqual(0, len(lib.browse(query='존재하지않는말')['items']))

    def test_disabled_items_are_hidden_unless_asked_for(self):
        self._seed()
        cid = lib.browse()['items'][0]['chunk_id']
        lib.set_enabled(cid, False)
        self.assertEqual(1, lib.browse()['total'])
        self.assertEqual(2, lib.browse(include_disabled=True)['total'])

    def test_set_enabled_keeps_the_row(self):
        """치우는 것이지 지우는 것이 아니다 — 되돌릴 수 있어야 한다."""
        self._seed()
        cid = lib.browse()['items'][0]['chunk_id']
        lib.set_enabled(cid, False)
        self.assertIsNotNone(AIKnowledgeChunk.query.filter_by(unique_id=cid).first())
        self.assertTrue(lib.set_enabled(cid, True)['is_enabled'])

    def test_tag_counts_and_summary_reflect_only_enabled_items(self):
        self._seed()
        self.assertEqual(2, lib.summary()['total'])
        cid = lib.browse()['items'][0]['chunk_id']
        lib.set_enabled(cid, False)
        self.assertEqual(1, lib.summary()['total'])
        self.assertTrue(all(t['count'] >= 1 for t in lib.tag_counts()))

    def test_browse_paginates(self):
        for i in range(5):
            lib.add_user_knowledge(content='항목 %d' % i, tags='t')
        first = lib.browse(page=1, page_size=2)
        self.assertEqual(2, len(first['items']))
        self.assertEqual(5, first['total'])
        self.assertTrue(first['has_more'])
        self.assertFalse(lib.browse(page=3, page_size=2)['has_more'])

    def test_source_url_is_validated_on_the_hand_entry_path_too(self):
        r = lib.add_user_knowledge(content='주소 검사', tags='t', source_url='javascript:alert(1)')
        row = AIKnowledgeChunk.query.filter_by(unique_id=r['chunk_id']).first()
        self.assertIsNone(row.source_url)


    # -- 관측성 (C7) ------------------------------------------------------

    def test_summary_reports_human_labels_not_raw_provenance_keys(self):
        """항목 목록은 provenance_label 을 쓰는데 요약줄만 원시 키를 내보내고
        있었다(브라우저 실측: "ai_curated: 2 · user_provided: 1"). 같은 화면에서
        같은 것을 두 이름으로 부르면 안 된다."""
        self._seed()
        keys = set(lib.summary()['by_provenance'])
        self.assertNotIn('ai_curated', keys)
        self.assertNotIn('user_provided', keys)
        self.assertEqual({'AI 정리', '사용자'}, keys)

    def test_usage_stats_counts_reviewed_retired_and_never_retrieved(self):
        """'무엇이 들어 있나' 만으로는 다음에 무엇을 채울지 정할 수 없다."""
        from aot.ai.services import knowledge_promotion_service as promo
        self._seed()
        st = lib.usage_stats()
        self.assertEqual(2, st['total'])
        self.assertEqual(2, st['never_retrieved'])
        self.assertEqual(1, st['ai_curated_total'])
        self.assertEqual(0, st['ai_curated_reviewed'])

        ai_item = [i for i in lib.browse()['items'] if i['provenance'] == 'ai_curated'][0]
        promo.confirm_item(ai_item['chunk_id'])
        self.assertEqual(1, lib.usage_stats()['ai_curated_reviewed'])

    def test_usage_stats_reports_retrieval_not_citation(self):
        """reuse_count 는 검색에 걸린 횟수다 — 화면 문구가 그것을 '인용' 이라
        말하면 거짓말이 된다. 값의 출처를 여기 고정해 둔다."""
        from aot.ai.services import knowledge_promotion_service as promo
        self._seed()
        cid = lib.browse(provenance='ai_curated')['items'][0]['chunk_id']
        promo.note_reuse([cid])
        st = lib.usage_stats()
        self.assertEqual(1, st['total'] - st['never_retrieved'])
        self.assertEqual(1, st['top_retrieved'][0]['reuse_count'])

    def test_usage_stats_counts_items_carrying_a_source_link(self):
        """출처가 없는 항목은 확인할 수 없고, 확인할 수 없으면 승격도 없다 —
        그 비율이 라이브러리의 건강 지표다."""
        lib.add_user_knowledge(content='주소 있음', tags='t', source_url='https://example.org/a')
        lib.add_user_knowledge(content='주소 없음', tags='t')
        self.assertEqual(1, lib.usage_stats()['with_source_url'])

if __name__ == '__main__':
    unittest.main()
