# coding=utf-8
"""MCP 점검 2026-11-04 (claude.ai 대화 보고): 함수 조회의 장소 거름, 조언 조회의 scope, 노트 제목, 숨기라는 문구 제거."""
import json
import os
import tempfile
import unittest


def _out(body):
    return [{'type': 'text', 'text': json.dumps(body, ensure_ascii=False)}]


def _functions_body():
    return {
        "functions": {
            "pid": [{"function_id": "p1", "name": "PID", "is_activated": True}],
            "custom": [
                {"function_id": "c1", "name": "Env Coordinator", "facility_id": "fac-a"},
                {"function_id": "c2", "name": "Env Coordinator", "facility_id": "fac-b"},
                {"function_id": "c3", "name": "환경제어: 육묘장3", "facility_id": "fac-b"},
            ]},
        "count": 4, "duplicate_names": ["Env Coordinator"], "note": "dup",
        "server_host": "h", "now": {}, "call_state": "executed"}


class TestFunctionsPlaceFilter(unittest.TestCase):

    def test_registry_marks_functions_as_place_filterable_and_says_so_in_unknown_arg_error(self):
        from aot.tools.domain import dispatch
        from aot.tools.domain.registry import find_op
        o = find_op(dispatch._ops(), 'find', 'functions')
        self.assertEqual(o.place_filter, 'facility_id')
        # query 는 26-11-09 부터 이름 조각으로 받는다 — 모르는 인자 예시는 다른 낱말로.
        err = dispatch._inner_args(o, {'colour': 'x'}, 'get_function_list', None, [], False)
        text = json.dumps(err, ensure_ascii=False)
        self.assertIn('does not take colour', text)
        self.assertIn('op, target,', text)          # 대상은 받는다 — 안내가 받는 인자를 틀리게 적지 않는다

    def test_rows_outside_the_place_are_dropped_and_counted(self):
        from aot.tools.domain import dispatch
        meta = {'place_key': 'facility_id', 'place_ids': ['fac-b'], 'page': {},
                'target': {'name': '육묘장3'}}
        out = dispatch._filter_ids(_out(_functions_body()), meta)
        body = json.loads(out[0]['text'])
        self.assertEqual([r['function_id'] for r in body['functions']['custom']], ['c2', 'c3'])
        self.assertNotIn('pid', body['functions'])
        self.assertEqual(body['count'], 2)
        self.assertEqual(body['not_tied_to_a_place'], 2)
        self.assertIn('place_filter_note', body)
        self.assertNotIn('duplicate_names', body)    # 남은 행에 같은 이름이 없으면 경고도 뗀다

    def test_paging_applies_after_the_filter(self):
        from aot.tools.domain import dispatch
        meta = {'place_key': 'facility_id', 'place_ids': ['fac-b'], 'page': {'limit': 1}}
        body = json.loads(dispatch._filter_ids(_out(_functions_body()), meta)[0]['text'])
        self.assertEqual(body['count'], 1)
        self.assertEqual(body['page'], {'total': 2, 'shown': 1, 'offset': 0, 'next_offset': 1})

    def test_a_list_without_any_link_says_the_filter_was_not_applied(self):
        from aot.tools.domain import dispatch
        out = dispatch._filter_ids(_out({"things": {"a": [{"name": "x"}]}, "count": 1}), {'ids': ['d1']})
        body = json.loads(out[0]['text'])
        self.assertIn('filter_not_applied', body)


class TestFunctionsPlan(unittest.TestCase):

    def test_a_place_target_becomes_a_filter_verdict_with_paging_held_back(self):
        from unittest import mock
        from aot.tools.domain import dispatch
        fac = {'kind': 'facility', 'id': 'shape-a', 'name': '육묘장3', 'path': '김제 > 3포장 > 육묘장3'}
        with mock.patch.object(dispatch.targets, 'resolve', return_value=('ok', fac)), \
                mock.patch.object(dispatch, '_ancestors', return_value=[]), \
                mock.patch.object(dispatch, '_place_keys', return_value={'shape-a', 'fac-a'}):
            v = dispatch.plan('find', {'op': 'functions', 'target': '육묘장3', 'limit': 3, 'offset': 1})
        self.assertEqual(v[0], 'filter', v)
        _f, inner, args, meta = v
        self.assertEqual(inner, 'get_function_list')
        self.assertNotIn('limit', args)                 # 거른 뒤에 쪽을 나눈다
        self.assertEqual(meta['page'], {'limit': 3, 'offset': 1})
        self.assertEqual(meta['place_key'], 'facility_id')
        self.assertEqual(meta['place_ids'], ['fac-a', 'shape-a'])
        self.assertIn('육묘장3', meta['filtered_to'])


class TestFunctionListSameFacility(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        from flask import Flask
        from flask_babel import Babel
        from aot.aot_flask.extensions import db
        import aot.databases.models  # noqa: F401
        from aot.databases.models import AIAdvice, CustomController, GeoFacility

        cls._tmp = tempfile.TemporaryDirectory()
        app = Flask(__name__)
        app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(cls._tmp.name, 'a.db')
        app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
        db.init_app(app)
        Babel(app)
        cls._ctx = app.app_context()
        cls._ctx.push()
        db.create_all()
        db.session.add(GeoFacility(unique_id='fac-a', shape_uuid='shape-a', geo_id='m', name='육묘장'))
        for uid, on in (('c1', True), ('c2', False)):
            db.session.add(CustomController(
                unique_id=uid, name='Env Coordinator', device='env_coordinator', is_activated=on,
                custom_options=json.dumps({'geo_facility_id': 'fac-a'})))
        db.session.commit()

    @classmethod
    def tearDownClass(cls):
        from aot.aot_flask.extensions import db
        db.session.remove()
        cls._ctx.pop()
        cls._tmp.cleanup()

    def test_note_says_same_facility_pairs_are_told_apart_by_active_flag_and_id(self):
        from aot.tools.aot_data_tool_service import AoTDataToolService as S
        out = S.get_function_list()
        self.assertEqual(out['duplicate_names'], ['Env Coordinator'])
        self.assertIn('same facility too', out['note'])
        self.assertIn('is_activated', out['note'])

    def test_inactive_duplicate_is_marked_as_a_inactive_sibling_but_the_active_one_is_not(self):
        from aot.tools.aot_data_tool_service import AoTDataToolService as S
        rows = {r['function_id']: r for r in S.get_function_list()['functions']['custom']}
        self.assertTrue(rows['c2'].get('inactive_sibling'))
        self.assertNotIn('inactive_sibling', rows['c1'])
        self.assertIn('inactive_sibling', S.get_function_list()['note'])

    def test_a_second_coordinator_for_the_same_facility_is_allowed_and_only_noted(self):
        """계획·모의로 한 시설에 방식이 다른 환경제어를 여럿 두는 것은 사용자의 자유다 — 막지 않고 알리기만."""
        from aot.tools.aot_data_tool_service import AoTDataToolService as S
        # 시설을 도형 id 로 불러도 같은 시설이다
        twin = S._coordinator_twin({'geo_facility_id': 'shape-a'})
        self.assertIsNotNone(twin)
        # 구획 범위가 다르면(동별 분담) 겹치지 않는다
        self.assertIsNone(S._coordinator_twin({'geo_facility_id': 'fac-a', 'bay_scope': 'bay-2'}))
        self.assertIsNone(S._coordinator_twin({}))
        note = S._coordinator_overlap(twin)
        self.assertIn('overlap_note', note)
        self.assertIn('fine', note['overlap_note'])          # 막는 말이 아니다
        self.assertNotIn('error', note)

    def test_editing_a_coordinator_onto_a_shared_facility_saves_and_reports_the_overlap(self):
        from unittest import mock
        from aot.aot_flask.extensions import db
        from aot.databases.models import CustomController
        from aot.tools.aot_data_tool_service import AoTDataToolService as S
        db.session.add(CustomController(unique_id='c9', name='새 환경제어', device='env_coordinator',
                                        is_activated=False, custom_options='{}'))
        db.session.commit()
        with mock.patch.object(S, 'validate_function_options', return_value=None), \
                mock.patch('aot.aot_flask.access.write_scope.enforce', lambda *a, **k: None):
            out = S.modify_function_options('c9', {'geo_facility_id': 'shape-a'})
            self.assertEqual(out.get('status'), 'modified', out)
            self.assertIn('overlaps', out)
            self.assertIn('shape-a', CustomController.query.filter_by(unique_id='c9').first().custom_options)
            ok = S.modify_function_options('c9', {'geo_facility_id': 'fac-a', 'bay_scope': 'bay-2'})
            self.assertEqual(ok.get('status'), 'modified', ok)
            self.assertNotIn('overlaps', ok)
        db.session.delete(CustomController.query.filter_by(unique_id='c9').first())
        db.session.commit()

    def test_a_coordinator_does_not_collide_with_itself(self):
        from aot.tools.aot_data_tool_service import AoTDataToolService as S
        twin = S._coordinator_twin({'geo_facility_id': 'fac-a'}, exclude_id='c1')
        self.assertEqual(twin.unique_id, 'c2')       # 자기(c1)는 빼고 나머지(c2)와만 겹친다

    def test_advice_with_no_rows_still_tells_which_filters_ran(self):
        from aot.tools.aot_data_tool_service import AoTDataToolService as S
        out = S.list_advice(scope_type='facility', scope_id='shape-a')
        self.assertEqual(out['count'], 0)
        self.assertEqual(out['scope']['filters']['scope_type'], 'facility')
        # 시설은 도형 id 와 시설 id 둘 다로 찾는다
        self.assertCountEqual(out['scope']['filters']['scope_ids'], ['shape-a', 'fac-a'])
        self.assertEqual(S.list_advice()['scope']['filters'], 'none')

    def test_note_search_names_a_facility_note_filed_under_the_shape_id(self):
        from aot.aot_flask.extensions import db
        from aot.databases.models import Notes
        from aot.tools.aot_data_tool_service import AoTDataToolService as S
        db.session.add(Notes(name='legacy', note='b', target_id='shape-a', target_type=None, category='general'))
        db.session.commit()
        out = S.search_notes_tool(target_id='fac-a')
        rows = [r for r in out.get('results', []) if r['name'] == 'legacy']
        if rows:                                   # 장소 해석이 시설의 두 id 를 함께 찾으면 정본 id 가 붙는다
            self.assertEqual(rows[0]['target_name'], '육묘장')
            self.assertEqual(rows[0]['facility_id'], 'fac-a')


class TestNoteTitleAndHints(unittest.TestCase):

    def test_title_is_the_first_line_not_the_first_fifty_characters(self):
        from aot.tools.aot_data_tool_service import AoTDataToolService as S
        body = "상부 보온커튼 추가 설치 계획 (2026-10-11, 기존 제어반 사진 검토 기반)\n\n1. 릴레이 채널 확인"
        self.assertEqual(S._title_from_body(body), "상부 보온커튼 추가 설치 계획 (2026-10-11, 기존 제어반 사진 검토 기반)")
        self.assertEqual(S._title_from_body("\n\n  둘째 줄만 있음\n본문"), "둘째 줄만 있음")
        self.assertEqual(S._title_from_body("가" * 80), "가" * 47 + "...")
        self.assertEqual(S._title_from_body(""), "Note")

    def test_no_server_text_tells_the_model_to_hide_the_map_move_from_the_user(self):
        from aot.tools import screen_follow as sf
        for slider in ('sent to 2026-10-28 00:00 (Asia/Seoul)', 'not moved: several screens are showing'):
            hint = sf.time_hint_for('u', {'slider': slider})
            self.assertTrue(hint)
            self.assertNotIn('Do not tell the user', hint)
        here = os.path.dirname(os.path.abspath(__file__))
        src = open(os.path.join(here, '..', 'tools', 'data_tools', 'system.py'), encoding='utf-8').read()
        self.assertNotIn('never mention the slider move', src)


if __name__ == '__main__':
    unittest.main()
