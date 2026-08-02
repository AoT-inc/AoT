# coding=utf-8
"""Regression test for GeoDesignManager.delete_design_map atomicity.

Background (2026-07-26 incident, koat-macmini): deleting a design map only
called db.session.delete(geo_map) + commit(), relying on GeoMap.shapes' ORM
cascade("all, delete-orphan") to remove GeoShape rows. That cascade does not
know about GeoFacility (linked to GeoShape via shape_uuid, no cascade
declared) — deleting a GeoShape that has a linked GeoFacility makes
SQLAlchemy try to null out GeoFacility.shape_uuid before the delete, which
fails because shape_uuid is NOT NULL. The failure surfaced only after the
map/shape deletes had already reached the DB, leaving a half-deleted map:
geo_map and geo_shape rows gone, geo_facility rows orphaned. A live design
map ('김제') was destroyed this way and had to be restored from a two-week-
old backup.
"""
import os

os.environ.setdefault("ALEMBIC_RUNNING", "1")

import unittest

from flask import Flask

from aot.aot_flask.extensions import db
# Import triggers model registration onto db.metadata without going through
# create_app() (whose QueuePool engine options reject SQLite's in-memory
# StaticPool — see aot/aot_flask/app.py's pool_size/max_overflow/pool_timeout
# branch).
from aot.databases.models import GeoMap, GeoShape, GeoFacility, GeoFacilitySetpoint
from aot.aot_flask.geo.geo_design import GeoDesignManager


def _make_app():
    app = Flask(__name__)
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite://'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    db.init_app(app)
    return app


def _polygon_feature():
    return {
        'type': 'Feature',
        'geometry': {'type': 'Polygon', 'coordinates': [[[0, 0], [0, 1], [1, 1], [0, 0]]]},
    }


class TestGeoDesignMapDelete(unittest.TestCase):
    def setUp(self):
        self.app = _make_app()
        self.app_context = self.app.app_context()
        self.app_context.push()
        db.create_all()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.app_context.pop()

    def _build_map_with_facility(self, map_uuid='m1', shape_uuid='s1', facility_uuid='f1', extra_shape_uuid='s2'):
        GeoMap(unique_id=map_uuid, name='Test Map', category='design').save()

        GeoShape(unique_id=shape_uuid, geo_id=map_uuid, type='facility', feature=_polygon_feature()).save()
        # A second, unrelated shape confirms the whole map is swept, not just the linked one.
        GeoShape(unique_id=extra_shape_uuid, geo_id=map_uuid, type='zone', feature=_polygon_feature()).save()

        GeoFacility(unique_id=facility_uuid, shape_uuid=shape_uuid, geo_id=map_uuid,
                    name='Test Facility', render_mode='parametric').save()
        GeoFacilitySetpoint(facility_uuid=facility_uuid, source='manual').save()

        return map_uuid

    def test_delete_removes_map_shapes_facility_and_setpoint_atomically(self):
        """The exact repro of the incident: a design map whose outer shape has
        a linked GeoFacility (+ setpoint) must delete cleanly, not half-delete."""
        map_uuid = self._build_map_with_facility()

        result, error = GeoDesignManager.delete_design_map(map_uuid)

        self.assertIsNone(error, f"delete_design_map returned an error: {error}")
        self.assertEqual(result, {'ok': True})

        self.assertIsNone(GeoMap.query.filter_by(unique_id=map_uuid).first())
        self.assertEqual(GeoShape.query.filter_by(geo_id=map_uuid).count(), 0)
        self.assertEqual(GeoFacility.query.filter_by(geo_id=map_uuid).count(), 0)
        self.assertEqual(GeoFacilitySetpoint.query.filter_by(facility_uuid='f1').count(), 0)

    def test_delete_map_without_facility_still_works(self):
        map_uuid = 'm2'
        GeoMap(unique_id=map_uuid, name='Plain Map', category='design').save()
        GeoShape(unique_id='s3', geo_id=map_uuid, type='zone', feature=_polygon_feature()).save()

        result, error = GeoDesignManager.delete_design_map(map_uuid)

        self.assertIsNone(error)
        self.assertEqual(result, {'ok': True})
        self.assertIsNone(GeoMap.query.filter_by(unique_id=map_uuid).first())
        self.assertEqual(GeoShape.query.filter_by(geo_id=map_uuid).count(), 0)

    def test_delete_nonexistent_map_returns_not_found(self):
        result, error = GeoDesignManager.delete_design_map('does-not-exist')
        self.assertIsNone(result)
        self.assertEqual(error, "Map not found")

    def test_delete_does_not_touch_other_maps(self):
        """A second design map (and its own facility) must survive untouched."""
        target = self._build_map_with_facility(map_uuid='m1', shape_uuid='s1', facility_uuid='f1', extra_shape_uuid='s2')
        other = self._build_map_with_facility(map_uuid='m3', shape_uuid='s4', facility_uuid='f2', extra_shape_uuid='s5')

        result, error = GeoDesignManager.delete_design_map(target)

        self.assertIsNone(error)
        self.assertEqual(result, {'ok': True})
        self.assertIsNotNone(GeoMap.query.filter_by(unique_id=other).first())
        self.assertEqual(GeoShape.query.filter_by(geo_id=other).count(), 2)
        self.assertEqual(GeoFacility.query.filter_by(geo_id=other).count(), 1)
        self.assertEqual(GeoFacilitySetpoint.query.filter_by(facility_uuid='f2').count(), 1)


if __name__ == '__main__':
    unittest.main()
