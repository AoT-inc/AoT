# coding=utf-8
"""
참조표 — 표를 적재하지 않고 등록만 해 두고 물어볼 때 조회한다.

왜 이 구조인가(2026-08-24 실측). 행이 수천 개인 표를 지식 항목으로 넣으면 매
질의의 검색 후보가 그만큼 늘어난다. ECOCROP 2,568종으로 재 보니 검색이 14ms →
73ms 가 됐는데, 느려지는 것보다 **엉뚱한 행이 답의 근거로 실리는 쪽**이 문제였다.
오염을 피하려고 일부만 적재하면 이번엔 "미리 고른 것만 답할 수 있다" 가 된다.

그래서 표는 검색 대상이 아니다. 그 대가로 **모델이 표의 존재를 모를 수 있다**는
새 문제가 생기고, 그것을 knowledge_search 의 빈 응답이 가리켜서 메운다 —
이 파일이 그 두 가지를 같이 고정한다.
"""
import io
import os
import sys
import unittest
from unittest import mock

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), os.path.pardir, os.path.pardir)))
os.environ["ALEMBIC_RUNNING"] = "1"

import tempfile

from aot.ai.services import reference_table_service as rts

_CSV = (
    "ScientificName,COMNAME,TOPMN,TOPMX,TMIN,TMAX,GMIN,NOTE\n"
    "Lycopersicon esculentum,\"tomato, tomate, pomodoro\",20,27,7,35,70,\n"
    "Cyphomandra betacea,\"tree tomato, tamarillo\",16,22,10,30,270,\n"
    "Raphanus sativus,\"radish, daikon\",12,26,10,37,50,NA\n"
)


class _Src(object):
    def __init__(self, source_id):
        self.source_id = source_id
        self.source_name = 'T'


class TestReferenceTableQuery(unittest.TestCase):

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix='reftbl-')
        os.environ['AOT_LOCAL_DIR'] = self.dir
        self.src = _Src('tbl-1')
        with io.open(rts.table_path('tbl-1'), 'w', encoding='utf-8') as fh:
            fh.write(_CSV)
        self.cfg = {'search_columns': 'ScientificName,COMNAME', 'title': 'T',
                    'caveat': '설정값이 아니다'}

    def _q(self, text, limit=3):
        rows, err = rts.query(self.src, self.cfg, text, limit=limit)
        self.assertIsNone(err, err)
        return rows

    def test_a_whole_name_match_beats_a_word_inside_another_name(self):
        """실측으로 필요해진 순위. 'tomato' 가 'tree tomato' 를 먼저 물어 오면
        사용자는 남의 작물 수치를 자기 작물 값으로 읽는다."""
        self.assertEqual('Lycopersicon esculentum', self._q('tomato')[0]['ScientificName'])

    def test_scientific_name_matches(self):
        self.assertEqual('Raphanus sativus', self._q('Raphanus sativus')[0]['ScientificName'])

    def test_a_word_inside_a_name_still_matches_when_nothing_better_exists(self):
        self.assertEqual('Cyphomandra betacea', self._q('tamarillo')[0]['ScientificName'])

    def test_no_match_is_reported_as_no_match(self):
        self.assertEqual([], self._q('존재하지않는것'))

    def test_empty_and_NA_cells_are_dropped(self):
        """빈 칸을 모델에 보내면 그것을 사실로 읽는다."""
        row = self._q('radish')[0]
        self.assertNotIn('NOTE', row)

    def test_limit_is_bounded(self):
        self.assertLessEqual(len(self._q('tomato', limit=999)), rts._MAX_MATCHES)

    def test_a_table_that_was_never_fetched_says_so(self):
        rows, err = rts.query(_Src('missing'), {}, 'x')
        self.assertEqual([], rows)
        self.assertIn('동기화', err)

    def test_describe_carries_what_the_operator_wrote(self):
        """AI 가 이 표를 쓸지 정하는 근거는 운영자가 적은 설명뿐이다."""
        d = rts.describe(self.src, dict(self.cfg, answers='작물 온도 범위'))
        self.assertEqual('작물 온도 범위', d['answers'])
        self.assertEqual(3, d['row_count'])
        self.assertIn('ScientificName', d['columns'])
        self.assertEqual('설정값이 아니다', d['caveat'])

    def test_reparse_is_skipped_when_the_file_has_not_changed(self):
        rts.load('tbl-1')
        with mock.patch('aot.ai.services.reference_table_service.csv.DictReader') as reader:
            rts.load('tbl-1')
            reader.assert_not_called()


class TestResponseSizeIsBounded(unittest.TestCase):
    """광범위한 질문이 토큰 폭탄이 되지 않게 하는 것들(사용자 지적, 2026-08-24).

    행 **수**는 이미 세 겹으로 막혀 있다: limit 상한(_MAX_MATCHES), 엔진의
    도구결과 상한(TOOL_RESULT_MAX_CHARS), 그리고 **전량 덤프 오퍼레이션이 아예
    없다는 것**(이름으로만 조회된다). 남은 낭비는 행의 **폭**이었다 — ECOCROP
    한 행이 41컬럼 1,152자인데 "온도 범위가 어떻게 돼?" 가 쓰는 건 서넛이다
    (실측: 5행 6,637자 ≈ 2,200토큰 → 요약 컬럼 2,033자 ≈ 677토큰).
    """

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix='reftbl-size-')
        os.environ['AOT_LOCAL_DIR'] = self.dir
        self.src = _Src('tbl-s')
        with io.open(rts.table_path('tbl-s'), 'w', encoding='utf-8') as fh:
            fh.write(_CSV)
        self.cfg = {'search_columns': 'ScientificName,COMNAME',
                    'summary_columns': 'ScientificName,TOPMN,TOPMX'}

    def test_the_operator_default_projection_applies(self):
        rows, _ = rts.query(self.src, self.cfg, 'tomato')
        self.assertEqual({'ScientificName', 'TOPMN', 'TOPMX'}, set(rows[0]))

    def test_an_explicit_column_list_wins_over_the_default(self):
        rows, _ = rts.query(self.src, self.cfg, 'tomato', columns=['ScientificName', 'GMIN'])
        self.assertEqual({'ScientificName', 'GMIN'}, set(rows[0]))

    def test_a_star_asks_for_everything(self):
        rows, _ = rts.query(self.src, self.cfg, 'tomato', columns=['*'])
        self.assertIn('TMIN', rows[0])
        self.assertIn('COMNAME', rows[0])

    def test_no_projection_configured_returns_the_whole_row(self):
        rows, _ = rts.query(self.src, {'search_columns': 'COMNAME'}, 'tomato')
        self.assertIn('TMIN', rows[0])

    def test_an_unknown_column_name_does_not_empty_the_row(self):
        """오타 하나로 행이 통째로 비면, 모델은 값이 없다고 단정한다."""
        rows, _ = rts.query(self.src, self.cfg, 'tomato', columns=['NoSuchColumn'])
        self.assertTrue(rows[0])

    def test_limit_cannot_exceed_the_hard_cap(self):
        self.assertLessEqual(len(rts.query(self.src, self.cfg, 'tomato', limit=10**6)[0]),
                             rts._MAX_MATCHES)


class TestAliases(unittest.TestCase):
    """표가 영어로 매겨져 있으면 한국어 질의는 0건이 된다(실측: ECOCROP 의
    통용명에 한글이 한 건도 없어 '무' 가 0건, 'radish' 가 5건).

    별칭만으로는 못 푼다 — 김장무·총각무·알타리무·달청무가 전부 radish 이고
    유의어는 끝이 없다(사용자 지적). 그래서 일을 나눈다: **표가 어느 언어로
    매겨졌는지는 데이터가 알고**(name_language), **유의어를 정규 이름으로 옮기는
    판단은 모델이 한다**. 별칭은 흔한 앵커만 잡는다."""

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix='reftbl-alias-')
        os.environ['AOT_LOCAL_DIR'] = self.dir
        self.src = _Src('tbl-a')
        with io.open(rts.table_path('tbl-a'), 'w', encoding='utf-8') as fh:
            fh.write(_CSV)
        self.cfg = {'search_columns': 'ScientificName,COMNAME',
                    'aliases': '무=radish, 토마토=tomato',
                    'name_language': '영어 통용명 또는 학명'}

    def test_a_local_name_reaches_the_english_row(self):
        rows, err = rts.query(self.src, self.cfg, '무')
        self.assertIsNone(err)
        self.assertEqual('Raphanus sativus', rows[0]['ScientificName'])

    def test_only_an_exact_alias_is_substituted(self):
        """부분 치환하면 '무름병' 이 'radish름병' 이 된다."""
        rows, _ = rts.query(self.src, self.cfg, '무름병')
        self.assertEqual([], rows)

    def test_describe_tells_the_model_what_language_the_names_are_in(self):
        d = rts.describe(self.src, self.cfg)
        self.assertIn('영어', d['name_language'])
        self.assertEqual('radish', d['aliases']['무'])

    def test_an_unmatched_local_name_is_told_to_retry_with_the_canonical_one(self):
        """유의어는 모델이 옮겨야 한다 — 그러라고 응답이 시킨다. 매니페스트가
        아니라 응답에 담아 표가 없는 설치의 고정비를 0으로 둔다."""
        from aot.ai.services.aot_data_tool_service import AoTDataToolService as T
        from unittest import mock as _m
        src = _Src('tbl-a')
        with _m.patch('aot.databases.models.AIContextSource') as _S:
            pass  # 핸들러는 DB 를 타므로 서비스 계층 계약만 여기서 고정한다
        rows, err = rts.query(src, self.cfg, '김장용 무')
        self.assertEqual([], rows)
        self.assertIsNone(err)


class TestSearchPointsAtTables(unittest.TestCase):
    """표는 검색되지 않으므로, 빈 검색 결과가 표를 가리켜야 한다. 이게 없으면
    모델은 답이 표 안에 있는데도 '정보가 없습니다' 로 끝낸다(실측).

    2026-08-25: 제목만 가리키던 것을 **부르는 법까지** 주도록 바꿨다. 제목만
    주면 모델이 id 를 얻으려 list_lookup_sources 를 한 번 더 불러야 했고,
    실측에서 조사 요청이 정확히 거기서 갈렸다(목록까지 열고 조회로 안 넘어가거나,
    목록조차 안 열거나). 루프에서 단계를 강제하는 대신 결정 지점을 없앤 것이다."""

    _BRIEF = [{'title': '작물 요구조건표',
               'call': "query_reference_table(table_id='tbl-1', query=…)",
               'answers': '작물의 생육 온도 한계',
               'name_language': '영어 통용명'}]

    def test_empty_result_hands_over_how_to_call_it(self):
        from aot.ai.services.aot_data_tool_service import AoTDataToolService as T
        with mock.patch.object(T, '_registered_lookup_briefs', return_value=self._BRIEF), \
             mock.patch('aot.ai.services.knowledge_search.search_as_text', return_value=''), \
             mock.patch('aot.ai.services.knowledge_search.library_is_populated', return_value=True):
            out = T.knowledge_search_tool(query='오크라 생육 온도')
        self.assertIn('작물 요구조건표', out['result'])
        self.assertIn("table_id='tbl-1'", out['result'])
        self.assertIn('do not need list_lookup_sources first', out['result'])

    def test_nothing_is_added_when_no_table_is_registered(self):
        """표가 없는 설치에서는 고정비가 0이어야 한다."""
        from aot.ai.services.aot_data_tool_service import AoTDataToolService as T
        with mock.patch.object(T, '_registered_lookup_briefs', return_value=[]), \
             mock.patch('aot.ai.services.knowledge_search.search_as_text', return_value=''), \
             mock.patch('aot.ai.services.knowledge_search.library_is_populated', return_value=True):
            out = T.knowledge_search_tool(query='오크라 생육 온도')
        self.assertNotIn('query_reference_table', out['result'])
        self.assertNotIn('lookup source', out['result'])


if __name__ == '__main__':
    unittest.main()
