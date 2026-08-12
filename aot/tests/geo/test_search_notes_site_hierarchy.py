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

from aot.aot_flask.extensions import db
from aot.databases.models import GeoMap, GeoShape, Output, Notes
# Imported at module scope (collection time, before any app_context is
# pushed) — importing this deep inside a test after setUp() has an app
# context active hits flask_babel's get_babel() with no 'babel' extension
# registered on that ad-hoc test app and raises KeyError('babel').
from aot.ai.services.aot_data_tool_service import AoTDataToolService


def _make_app():
    app = Flask(__name__)
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite://'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    db.init_app(app)
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


if __name__ == '__main__':
    unittest.main()
