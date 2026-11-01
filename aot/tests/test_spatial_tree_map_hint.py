# coding=utf-8
"""C4: 지도가 여럿인데 map 을 안 주면 get_spatial_tree 가 지도 목록과 map 지정
권고를 응답에 싣는다. 임시 sqlite 만 쓴다."""
import unittest

from flask import Flask

from aot.aot_flask.extensions import db
from aot.databases.models import GeoMap


class TestSpatialTreeMapHint(unittest.TestCase):

    def setUp(self):
        app = Flask(__name__)
        app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite://'
        app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
        db.init_app(app)
        self.ctx = app.app_context()
        self.ctx.push()
        db.create_all()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.ctx.pop()

    @property
    def S(self):
        from aot.tools.aot_data_tool_service import AoTDataToolService
        return AoTDataToolService

    def test_several_maps_without_map_arg_get_a_hint(self):
        db.session.add_all([GeoMap(unique_id='m1', name='김제'),
                            GeoMap(unique_id='m2', name='영양')])
        db.session.commit()
        out = {}
        self.S._add_map_hint(out, None)
        self.assertEqual(out['maps'], ['김제', '영양'])
        self.assertIn("map='<name>'", out['_map_hint'])

    def test_map_given_or_single_map_adds_nothing(self):
        db.session.add(GeoMap(unique_id='m1', name='김제'))
        db.session.commit()
        out = {}
        self.S._add_map_hint(out, None)
        self.assertEqual(out, {})
        db.session.add(GeoMap(unique_id='m2', name='영양'))
        db.session.commit()
        self.S._add_map_hint(out, '김제')
        self.assertEqual(out, {})


if __name__ == '__main__':
    unittest.main()
