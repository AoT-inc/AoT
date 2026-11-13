# coding=utf-8
"""B6: 같은 이름의 환경제어 함수(Env Coordinator 둘)를 get_function_list 에서
시설로 구분할 수 있어야 한다. 임시 sqlite 만 쓴다."""
import json
import os
import tempfile
import unittest


class TestFunctionListFacility(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        from flask import Flask
        from flask_babel import Babel
        from aot.aot_flask.extensions import db
        import aot.databases.models  # noqa: F401
        from aot.databases.models import CustomController, GeoFacility

        cls._tmp = tempfile.TemporaryDirectory()
        app = Flask(__name__)
        app.config['SQLALCHEMY_DATABASE_URI'] = \
            'sqlite:///' + os.path.join(cls._tmp.name, 'fn.db')
        app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
        db.init_app(app)
        Babel(app)
        cls._ctx = app.app_context()
        cls._ctx.push()
        db.create_all()
        for uid, name in (('fac-a', '육묘장'), ('fac-b', '육묘장3')):
            db.session.add(GeoFacility(unique_id=uid, shape_uuid='s-' + uid,
                                       geo_id='m', name=name))
        for uid, fac in (('c1', 'fac-a'), ('c2', 'fac-b')):
            db.session.add(CustomController(
                unique_id=uid, name='Env Coordinator', device='env_coordinator',
                is_activated=True,
                custom_options=json.dumps({'geo_facility_id': fac})))
        db.session.add(CustomController(unique_id='c3', name='기타', device='x',
                                        is_activated=True))
        db.session.commit()

    @classmethod
    def tearDownClass(cls):
        from aot.aot_flask.extensions import db
        db.session.remove()
        cls._ctx.pop()
        cls._tmp.cleanup()

    def test_same_named_coordinators_are_told_apart_by_facility(self):
        from aot.tools.aot_data_tool_service import AoTDataToolService as S
        out = S.get_function_list()
        rows = {r['function_id']: r for r in out['functions']['custom']}
        self.assertEqual(rows['c1']['facility_name'], '육묘장')
        self.assertEqual(rows['c2']['facility_name'], '육묘장3')
        self.assertNotIn('facility_name', rows['c3'])
        self.assertEqual(out['duplicate_names'], ['Env Coordinator'])
        self.assertIn('facility_name', out['note'])

    def test_query_is_part_of_the_name_or_driver(self):
        # 실사용 26-11-07~09: find.functions 에 query='VPD' 가 거절됐다 — 이름 조각으로 받는다.
        from aot.tools.aot_data_tool_service import AoTDataToolService as S
        got = S.get_function_list(query='env coord')
        self.assertEqual({'c1', 'c2'}, {r['function_id'] for r in got['functions']['custom']})
        self.assertEqual(2, got['count'])
        self.assertEqual(['c1', 'c2'], sorted(r['function_id'] for r in
                                              S.get_function_list(query='ENV_COORDINATOR')['functions']['custom']))
        self.assertEqual(0, S.get_function_list(query='없는이름')['count'])


if __name__ == '__main__':
    unittest.main()
