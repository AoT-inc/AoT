# coding=utf-8
"""Regression tests for the facility-orphan guard in GeoOverlayManager.

Background: save_overlays' delta-sync delete and save_delta's db_id/node_id
delete paths all bulk-delete GeoShape rows via Query.delete(synchronize_
session=False), which bypasses SQLAlchemy's ORM relationship handling
entirely. Deleting a 'facility'-type shape through these generic paths (the
map editor's normal draw-delete tool routes here for every shape type,
including facility outlines — see aot-geo-design-v3.js's typesToSync/
draw:deleted handler) used to silently orphan the linked GeoFacility row
(dangling shape_uuid, no error) instead of cleaning it up the way the
dedicated DELETE /api/geo/facility/<uuid> endpoint does. These tests pin
GeoOverlayManager._cascade_delete_facilities_for_shapes, now called before
each of those three bulk shape deletes.
"""
import os

os.environ.setdefault("ALEMBIC_RUNNING", "1")

import unittest

from flask import Flask

from aot.aot_flask.extensions import db
from aot.databases.models import GeoMap, GeoShape, GeoFacility, GeoFacilitySetpoint
from aot.aot_flask.geo.geo_overlays import GeoOverlayManager


def _make_app():
    app = Flask(__name__)
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite://'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    db.init_app(app)
    return app


def _polygon_feature(props=None):
    return {
        'type': 'Feature',
        'geometry': {'type': 'Polygon', 'coordinates': [[[0, 0], [0, 1], [1, 1], [0, 0]]]},
        'properties': props or {},
    }


class TestGeoOverlaysFacilityCascade(unittest.TestCase):
    def setUp(self):
        self.app = _make_app()
        self.app_context = self.app.app_context()
        self.app_context.push()
        db.create_all()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.app_context.pop()

    def _build_facility(self, map_uuid='m1', shape_uuid='s1', facility_uuid='f1', with_bay=True):
        GeoMap.query.filter_by(unique_id=map_uuid).first() or \
            GeoMap(unique_id=map_uuid, name='Test Map', category='design').save()
        shape = GeoShape(unique_id=shape_uuid, geo_id=map_uuid, type='facility',
                          feature=_polygon_feature())
        shape.save()
        GeoFacility(unique_id=facility_uuid, shape_uuid=shape_uuid, geo_id=map_uuid,
                    name='Test Facility', render_mode='parametric').save()
        GeoFacilitySetpoint(facility_uuid=facility_uuid, source='manual').save()
        if with_bay:
            GeoShape(unique_id=shape_uuid + '-bay', geo_id=map_uuid, type='facility_bay',
                     parent_id=shape.id, feature=_polygon_feature()).save()
        return shape

    def _assert_fully_cleaned(self, map_uuid, facility_uuid, shape_uuid='s1'):
        self.assertEqual(GeoFacility.query.filter_by(unique_id=facility_uuid).count(), 0)
        self.assertEqual(GeoFacilitySetpoint.query.filter_by(facility_uuid=facility_uuid).count(), 0)
        self.assertEqual(GeoShape.query.filter_by(unique_id=shape_uuid).count(), 0)
        self.assertEqual(GeoShape.query.filter_by(unique_id=shape_uuid + '-bay').count(), 0)

    # --- save_overlays delta-sync path ---

    def test_save_overlays_delta_sync_cleans_up_facility(self):
        self._build_facility()
        result, error = GeoOverlayManager.save_overlays({
            'map_uuid': 'm1', 'type': 'facility', 'features': [], 'allow_empty': True,
        })
        self.assertIsNone(error)
        self.assertEqual(result['stats']['deleted'], 1)
        self._assert_fully_cleaned('m1', 'f1')

    def test_save_overlays_partial_payload_keeps_omitted_facility(self):
        # [I9] upsert-only: 페이로드에서 빠진 시설 도형은 삭제되지 않는다.
        # (과거에는 누락 = 삭제라서 f1 시설이 통째로 사라졌다. 삭제는
        # save_delta 의 명시 deletes[] 로만 간다 — 아래 db_id/node_id 테스트.)
        self._build_facility(map_uuid='m1', shape_uuid='s1', facility_uuid='f1')
        kept_shape = self._build_facility(map_uuid='m1', shape_uuid='s2', facility_uuid='f2', with_bay=False)

        kept_feat = kept_shape.feature
        kept_feat['properties']['db_id'] = kept_shape.id
        result, error = GeoOverlayManager.save_overlays({
            'map_uuid': 'm1', 'type': 'facility', 'features': [kept_feat],
        })
        self.assertIsNone(error)
        # f1 (payload 에서 누락) — 도형·시설 모두 생존해야 한다.
        self.assertEqual(GeoShape.query.filter_by(unique_id='s1').count(), 1)
        self.assertEqual(GeoFacility.query.filter_by(unique_id='f1').count(), 1)
        # f2 (payload 에 포함) 도 그대로.
        self.assertEqual(GeoFacility.query.filter_by(unique_id='f2').count(), 1)
        self.assertEqual(GeoShape.query.filter_by(unique_id='s2').count(), 1)

    # --- save_delta db_id path ---

    def test_save_delta_db_id_delete_cleans_up_facility(self):
        shape = self._build_facility()
        result, error = GeoOverlayManager.save_delta({
            'map_uuid': 'm1', 'deletes': [shape.id],
        })
        self.assertIsNone(error)
        self._assert_fully_cleaned('m1', 'f1')

    # --- save_delta node_id path ---

    def test_save_delta_node_id_delete_cleans_up_facility(self):
        shape = self._build_facility(with_bay=True)
        shape.feature = _polygon_feature({'node_id': 'facility-node-1'})
        shape.save()

        result, error = GeoOverlayManager.save_delta({
            'map_uuid': 'm1', 'deletes': ['facility-node-1'],
        })
        self.assertIsNone(error)
        self._assert_fully_cleaned('m1', 'f1')

    # --- Deleting a non-facility shape must not touch unrelated facilities ---

    def test_deleting_unrelated_shape_leaves_facility_intact(self):
        self._build_facility()
        other = GeoShape(unique_id='z1', geo_id='m1', type='zone', feature=_polygon_feature())
        other.save()

        result, error = GeoOverlayManager.save_delta({
            'map_uuid': 'm1', 'deletes': [other.id],
        })
        self.assertIsNone(error)
        self.assertEqual(GeoFacility.query.filter_by(unique_id='f1').count(), 1)
        self.assertEqual(GeoShape.query.filter_by(unique_id='s1').count(), 1)
        self.assertEqual(GeoShape.query.filter_by(unique_id='z1').count(), 0)


if __name__ == '__main__':
    unittest.main()
