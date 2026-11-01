# coding=utf-8
"""Regression test — search_notes(target_name=<site>) 가 하위 zone/장치의
노트까지 반환해야 한다.

배경: `_resolve_note_target_ids` 는 site 로 해석되면
`_geo_shape_descendants(site_shape)` 로 하위 GeoShape 를 모아 후보
target_id 에 넣었지만, 각 descendant 의 `unique_id`(도형 자신의 id) 만
추가하고 `device_id`(그 마커가 가리키는 Input/Output 의 unique_id) 는
빠뜨렸다. 노트는 지도 마커가 아니라 장치 패널에서 작성되면
Output.unique_id 에 붙으므로, site 질의가 이 id 를 후보에 못 넣으면
실제로 존재하는 노트를 "없음"으로 답한다 — 밸브-펌프 작동순서 같은
운영 지침 노트가 이렇게 누락됐다.
"""
import os

os.environ.setdefault("ALEMBIC_RUNNING", "1")

import json
import unittest

from flask import Flask
from flask_babel import Babel

from aot.aot_flask.extensions import db
from aot.databases.models import GeoMap, GeoShape, Output, Notes
# Imported at module scope (collection time, before any app_context is
# pushed) — importing this deep inside a test after setUp() has an app
# context active hits flask_babel's get_babel() with no 'babel' extension
# registered on that ad-hoc test app and raises KeyError('babel').
from aot.tools.aot_data_tool_service import AoTDataToolService


def _make_app():
    app = Flask(__name__)
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite://'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    db.init_app(app)
    # 실제 앱처럼 번역을 붙여 둔다. 도구 계층은 이제 지도 모듈을 **쓸 때**
    # 불러오므로(계층 정리 뒤 모듈 수준 import 가 사라졌다), 그 import 가
    # 이 앱 컨텍스트 안에서 처음 일어나 번역 문구 표(config_translations)의
    # lazy_gettext 를 평가한다 — 번역이 없는 앱이면 KeyError('babel') 이다.
    # 위의 모듈 수준 import 만으로는 더 이상 막을 수 없다.
    Babel(app)
    return app


def _feature(name, geom_type, coords):
    return {
        'type': 'Feature',
        'geometry': {'type': geom_type, 'coordinates': coords},
        'properties': {'name': name},
    }


class TestSearchNotesSiteHierarchy(unittest.TestCase):
    def setUp(self):
        self.app = _make_app()
        self.app_context = self.app.app_context()
        self.app_context.push()
        db.create_all()

        GeoMap(unique_id='map-1', name='Test Map', category='design').save()

        # site '1포장' — a square polygon.
        self.site = GeoShape(
            unique_id='site-1', geo_id='map-1', type='site',
            feature=_feature('1포장', 'Polygon',
                              [[[0, 0], [0, 10], [10, 10], [10, 0], [0, 0]]]))
        self.site.save()

        # v142 — a device marker for an Output, spatially inside the site,
        # WITHOUT its own display name (mirrors the real report: some
        # markers carry no 'name' property, only device_id).
        self.output = Output(unique_id='out-v142', name='v142').save()
        self.marker = GeoShape(
            unique_id='marker-v142', geo_id='map-1', type='aot_device',
            device_id='out-v142',
            feature=_feature(None, 'Point', [5, 5]))
        self.marker.save()

        # A note written on the device panel — attaches to the OUTPUT's own
        # unique_id, not the marker shape's unique_id (the dual-identity
        # split this bug fell into).
        self.note = Notes(
            name='밸브 v142 (1포장)', note='1포장에 설치된 펌프가 함께 작동해야 함',
            target_id='out-v142', target_type='output', category='general')
        self.note.save()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.app_context.pop()

    def test_site_query_returns_descendant_device_note(self):
        result = AoTDataToolService.search_notes_tool(target_name='1포장', limit=10)

        self.assertEqual(result.get('status'), 'success')
        self.assertGreaterEqual(result.get('count', 0), 1)
        target_ids = {r['target_id'] for r in result['results']}
        self.assertIn('out-v142', target_ids)

    def test_resolve_note_target_ids_includes_descendant_device_id(self):
        ids, resolved_name = AoTDataToolService._resolve_note_target_ids('1포장')

        self.assertEqual(resolved_name, '1포장')
        self.assertIn('out-v142', ids)
        # The marker shape's own id is a candidate too (a note can attach to
        # the map identity as well as the device identity).
        self.assertIn('marker-v142', ids)


class TestFacilityNoteIdentity(unittest.TestCase):
    """시설은 정체성이 둘이다(GeoFacility.unique_id / 그 도형 GeoShape.unique_id).
    웹은 노트를 시설 id 에, 예전 MCP 는 도형 id 에 붙여 같은 시설의 노트가
    둘로 갈라졌다(육묘장3, 2026-10). 읽기는 두 id 모두를, 쓰기는 시설 id 로."""

    FAC = 'fac-uid-1'
    SHP = 'shape-uid-1'

    def setUp(self):
        from aot.databases.models import GeoFacility
        self.app = _make_app()
        self.app.config['LOGIN_DISABLED'] = True
        self.app.secret_key = 'test'
        from flask_login import LoginManager
        lm = LoginManager(self.app)
        lm.user_loader(lambda _uid: None)
        from aot.aot_flask.geo import shape_index
        shape_index.invalidate()  # 프로세스 캐시(30s)가 앞 테스트의 도형을 들고 있다
        self.app_context = self.app.app_context()
        self.app_context.push()
        db.create_all()
        GeoMap(unique_id='map-1', name='Test Map', category='design').save()
        GeoShape(unique_id=self.SHP, geo_id='map-1', type='facility',
                 feature=_feature('육묘장3', 'Polygon',
                                  [[[0, 0], [0, 10], [10, 10], [10, 0], [0, 0]]])).save()
        GeoFacility(unique_id=self.FAC, shape_uuid=self.SHP, geo_id='map-1',
                    name='육묘장3').save()
        Notes(name='웹 노트', note='w', target_id=self.FAC,
              target_type='GeoFacility', category='general').save()
        Notes(name='옛 MCP 노트', note='m', target_id=self.SHP,
              target_type='facility', category='general').save()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.app_context.pop()
        from aot.aot_flask.geo import shape_index
        shape_index.invalidate()

    def _mcp_names(self, **kw):
        r = AoTDataToolService.search_notes_tool(limit=10, **kw)
        return {x['name'] for x in r.get('results', [])}

    def test_mcp_read_by_either_id_sees_both(self):
        both = {'웹 노트', '옛 MCP 노트'}
        self.assertEqual(self._mcp_names(target_id=self.FAC), both)
        self.assertEqual(self._mcp_names(target_id=self.SHP), both)
        self.assertEqual(self._mcp_names(target_name='육묘장3'), both)

    def test_web_read_by_either_id_sees_both(self):
        from aot.aot_flask import routes_notes_api as api
        fn = getattr(api.api_notes_target_get, '__wrapped__',
                     api.api_notes_target_get)
        both = {'웹 노트', '옛 MCP 노트'}
        for tid in (self.FAC, self.SHP):
            with self.app.test_request_context('/?descendants=1'):
                resp = fn(tid)
                data = resp[0].get_json() if isinstance(resp, tuple) else resp.get_json()
            rows = data if isinstance(data, list) else (
                data.get('notes') or data.get('results') or [])
            self.assertEqual({x['note'] for x in rows}, {'w', 'm'}, tid)

    def test_mcp_write_attaches_to_facility_id(self):
        for kw in ({'target_name': '육묘장3'}, {'target_id': self.SHP},
                   {'target_id': self.FAC}):
            r = AoTDataToolService.create_note(name='n', note='x', **kw)
            self.assertIn('note_id', r, r)
            n = Notes.query.filter_by(unique_id=r['note_id']).first()
            self.assertEqual(n.target_id, self.FAC, kw)
            self.assertEqual(n.target_type, 'GeoFacility', kw)

    def test_web_create_normalizes_shape_id_to_facility(self):
        from aot.aot_flask import routes_notes_api as api
        fn = getattr(api.api_notes_create, '__wrapped__', api.api_notes_create)
        from unittest import mock
        for tid, tt in ((self.SHP, 'facility'), (self.FAC, 'GeoFacility')):
            with mock.patch.object(api.utils_general, 'user_has_permission',
                                   return_value=True), \
                    self.app.test_request_context(
                    '/', method='POST',
                    json={'note': 'z', 'target_id': tid, 'target_type': tt,
                          'gps_lat': 1, 'gps_lng': 1}):
                fn()
        rows = Notes.query.filter_by(note='z').all()
        self.assertEqual(len(rows), 2)
        for n in rows:
            self.assertEqual((n.target_id, n.target_type),
                             (self.FAC, 'GeoFacility'))


if __name__ == '__main__':
    unittest.main()
