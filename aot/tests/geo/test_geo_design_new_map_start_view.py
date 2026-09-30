# coding=utf-8
"""새 지도는 클라이언트가 보낸 현재 화면이 아니라 GeoSetting 의 기본 시작
위치(default_lat/default_lng/zoom)에서 열려야 한다. 기존 지도는 저장된 화면을 유지."""
import os

os.environ.setdefault("ALEMBIC_RUNNING", "1")

import unittest

from flask import Flask

from aot.aot_flask.extensions import db
from aot.databases.models import GeoMap, GeoSetting
from aot.aot_flask.geo.geo_design import GeoDesignManager


class TestNewMapStartView(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite://'
        self.app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
        db.init_app(self.app)
        self.ctx = self.app.app_context()
        self.ctx.push()
        db.create_all()
        db.session.add(GeoSetting(default_lat=35.43, default_lng=126.70, zoom=16.0))
        db.session.commit()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.ctx.pop()

    def test_new_map_uses_configured_start_view(self):
        res, err = GeoDesignManager.save_design_map(
            {'name': 'n', 'state': {'center': {'lat': 37.5665, 'lng': 126.978}, 'zoom': 12}}, 'u')
        self.assertIsNone(err)
        state = GeoMap.query.filter_by(unique_id=res['uuid']).first().state_dict()
        self.assertEqual(state['center'], {'lat': 35.43, 'lng': 126.70})
        self.assertEqual(state['zoom'], 16.0)

    def test_existing_map_keeps_saved_view(self):
        res, _ = GeoDesignManager.save_design_map({'name': 'n', 'state': {}}, 'u')
        GeoDesignManager.save_design_map(
            {'map_uuid': res['uuid'], 'state': {'center': {'lat': 1.0, 'lng': 2.0}, 'zoom': 9}}, 'u')
        state = GeoMap.query.filter_by(unique_id=res['uuid']).first().state_dict()
        self.assertEqual(state['center'], {'lat': 1.0, 'lng': 2.0})
        self.assertEqual(state['zoom'], 9)


if __name__ == '__main__':
    unittest.main()
