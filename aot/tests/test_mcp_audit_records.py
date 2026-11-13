# coding=utf-8
"""records 조회 도구 인자·안내문 정리(2026-10-28 MCP 점검 D).

- 옛 안쪽 도구 이름(knowledge_search·get_device_detail …)이 안내문에 남아 AI 가 못 부르던 것
- records.journals 가 이름만 주면 target_type 을 요구하던 것
- records.data_source 는 target 이 아니라 source_id 를 받는다는 것을 스키마가 말한다
- 지식 검색 결과 끝의 조회 출처 안내를 줄인 것(명령형 문구는 그대로)
"""
import os

os.environ.setdefault("ALEMBIC_RUNNING", "1")

import unittest
from unittest import mock

from flask import Flask
from flask_babel import Babel

from aot.aot_flask.extensions import db
from aot.tools.aot_data_tool_service import AoTDataToolService


class OldToolNamesAreRenamedTest(unittest.TestCase):

    def test_free_text_and_lists_carry_domain_names(self):
        from aot.tools.domain import dispatch
        dispatch._INNER_TO_OP.clear()                 # 앞선 시험이 바꾼 명부로 채운 캐시 제거
        body = {'result': 'see get_device_detail(device_id=1), then knowledge_search',
                'how_to_proceed': ['1. get_spatial_tree', '2. search_schedule'],
                'name': '온습도_5'}
        dispatch._domain_hints(body)
        self.assertEqual('see detail.device(device_id=1), then records.knowledge', body['result'])
        self.assertEqual(['1. find.tree', '2. records.schedule'], body['how_to_proceed'])
        self.assertEqual('온습도_5', body['name'])

    def test_rows_and_targets_are_data_and_stay_as_they_are(self):
        from aot.tools.domain import dispatch
        body = {'results': [{'name': 'get_plot'}], 'target': {'name': 'get_plot'}}
        dispatch._domain_hints(body)
        self.assertEqual('get_plot', body['results'][0]['name'])
        self.assertEqual('get_plot', body['target']['name'])

    def test_plain_words_without_underscore_are_not_touched(self):
        from aot.tools.domain import dispatch
        body = {'note': 'the nearest zone, resolve it first'}
        dispatch._domain_hints(body)
        self.assertEqual('the nearest zone, resolve it first', body['note'])


class RegistryTest(unittest.TestCase):

    def _op(self, tool, op):
        from aot.tools.domain.registry import find_op
        from aot.tools.domain.registry_data import OPS
        return find_op(OPS, tool, op)

    def test_journals_name_alone_sets_target_type_from_the_resolved_kind(self):
        o = self._op('records', 'journals')
        self.assertEqual({'plot': {'target_type': 'plot'}, 'zone': {'target_type': 'zone'},
                          'site': {'target_type': 'site'}}, o.defaults_by_kind)

    def test_data_source_asks_for_source_id_not_target(self):
        o = self._op('records', 'data_source')
        self.assertIn('source_id', o.required)
        self.assertIn('not target', o.extra_args['source_id'])


class KnowledgePointerIsShortTest(unittest.TestCase):
    _BRIEF = [{'title': 'FAO ECOCROP', 'call': "query_reference_table(table_id='t1', query=…)",
               'answers': '식물 종의 생육 온도·연강수량·토양 pH·재배 고도 한계·생육 일수, 학명과 통용명. 길게 이어지는 설명 ' * 3,
               'name_language': '영어 통용명'}]

    def test_pointer_keeps_the_command_and_drops_the_long_answers_paragraph(self):
        from aot.tools.aot_data_tool_service import AoTDataToolService as T
        with mock.patch.object(T, '_registered_lookup_briefs', return_value=self._BRIEF), \
             mock.patch('aot.ai.services.knowledge_search.search_as_text', return_value='본문'), \
             mock.patch('aot.ai.services.knowledge_search.library_is_populated', return_value=True):
            out = T.knowledge_search_tool(query='x')['result']
        self.assertIn('call one DIRECTLY', out)
        self.assertIn('Do NOT say the information is unavailable', out)
        self.assertIn('translate the user', out)
        self.assertNotIn('길게 이어지는 설명 길게', out)
        self.assertLess(len(out), 600)


class RecentNotesWithoutFiltersTest(unittest.TestCase):
    """query·대상을 모두 안 주면 오류가 아니라 가장 최근 노트다."""

    def setUp(self):
        app = Flask(__name__)
        app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite://'
        app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
        db.init_app(app)
        Babel(app)
        self.ctx = app.app_context()
        self.ctx.push()
        db.create_all()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.ctx.pop()

    def test_no_arguments_lists_the_latest_notes(self):
        out = AoTDataToolService.search_notes_tool()
        self.assertNotIn('error', out, out)
        self.assertEqual(0, out.get('count'))

    def test_the_empty_message_does_not_say_query_none(self):
        out = AoTDataToolService.search_notes_tool()
        self.assertNotIn('None', out.get('message', ''))


if __name__ == '__main__':
    unittest.main()
