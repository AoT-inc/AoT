# coding=utf-8
"""시설 모형 확장 F2 — `geo_facility.layout` 칸: 마이그레이션 왕복, 표본 검증, 직렬화, 저장·거부."""
import copy
import importlib.util
import json
import os

os.environ.setdefault("ALEMBIC_RUNNING", "1")

import unittest
from pathlib import Path

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from flask import Flask

from aot.aot_flask.extensions import db
from aot.space import facility_layout as FL
from aot.space.facility_io import FacilityManager, TERRAIN_SAMPLE_STEP_M
from aot.databases.models import GeoFacility, GeoMap

ROOT = Path(__file__).resolve().parents[2]
SAMPLES = json.loads((ROOT / 'tests' / 'fixtures' / 'facility_layout_samples.json').read_text(encoding='utf-8'))['samples']
MIGRATION = ROOT.parent / 'alembic_db' / 'alembic' / 'versions' / 'p7_01_facility_layout_20261102.py'

OUTER = {'type': 'Polygon', 'coordinates': [[[127.0, 36.0], [127.001, 36.0], [127.001, 36.001], [127.0, 36.001], [127.0, 36.0]]]}


def _sample(key):
    return copy.deepcopy(next(s['layout'] for s in SAMPLES if s['key'] == key))


def _load_migration():
    spec = importlib.util.spec_from_file_location('p7_01_facility_layout', str(MIGRATION))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestSamples(unittest.TestCase):
    def test_three_samples_exist_and_validate(self):
        self.assertEqual({s['key'] for s in SAMPLES},
                         {'two_story_nursery', 'l_shaped_connected', 'stepped_building'})
        for s in SAMPLES:
            self.assertEqual(FL.validate_layout(s['layout']), [], s['key'])
            c = FL.compile_layout(s['layout'])
            self.assertEqual(c['warnings'], [], s['key'])
            self.assertGreater(c['totals']['volume_m3'], 0)

    def test_samples_cover_the_three_shapes(self):
        two = _sample('two_story_nursery')
        self.assertEqual(len(two['levels']), 2)
        ell = _sample('l_shaped_connected')
        self.assertEqual(len(ell['levels']), 1)
        self.assertEqual(len(ell['blocks']), 2)
        self.assertEqual(ell['boundaries'][0]['type'], 'open')
        step = _sample('stepped_building')
        outlines = {len(b['outline']) for b in step['blocks']}
        self.assertGreater(len(outlines), 1, '층마다 평면이 달라야 한다')


class TestMigration(unittest.TestCase):
    def setUp(self):
        self.engine = sa.create_engine('sqlite://')
        with self.engine.begin() as c:
            c.execute(sa.text('CREATE TABLE geo_facility (id INTEGER PRIMARY KEY, name VARCHAR(128))'))
            c.execute(sa.text("INSERT INTO geo_facility (id, name) VALUES (1, '기존')"))
        self.mig = _load_migration()

    def _cols(self, conn):
        return {c['name'] for c in sa.inspect(conn).get_columns('geo_facility')}

    def _run(self, fn):
        with self.engine.begin() as conn:
            ctx = MigrationContext.configure(conn)
            with Operations.context(ctx):
                fn()

    def test_revision_chain(self):
        self.assertEqual(self.mig.revision, 'p7_01_facility_layout_20261102')
        self.assertEqual(self.mig.down_revision, 'p7_00_target_alias_20261028')

    def test_upgrade_adds_nullable_column_and_keeps_rows(self):
        self._run(self.mig.upgrade)
        with self.engine.connect() as conn:
            self.assertIn('layout', self._cols(conn))
            row = conn.execute(sa.text('SELECT id, name, layout FROM geo_facility')).fetchone()
        self.assertEqual((row[0], row[1], row[2]), (1, '기존', None), '기존 행은 변환하지 않는다')

    def test_upgrade_is_idempotent_and_downgrade_round_trips(self):
        self._run(self.mig.upgrade)
        self._run(self.mig.upgrade)          # 재실행 안전
        with self.engine.begin() as conn:
            conn.execute(sa.text("UPDATE geo_facility SET layout = '{\"schema\": 1}' WHERE id = 1"))
        self._run(self.mig.downgrade)
        with self.engine.connect() as conn:
            self.assertNotIn('layout', self._cols(conn))
            self.assertEqual(conn.execute(sa.text('SELECT name FROM geo_facility')).scalar(), '기존')
        self._run(self.mig.downgrade)        # 이미 없어도 안전
        self._run(self.mig.upgrade)
        with self.engine.connect() as conn:
            self.assertIn('layout', self._cols(conn))


class TestSaveAndRead(unittest.TestCase):
    def setUp(self):
        app = Flask(__name__)
        app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite://'
        app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
        db.init_app(app)
        self.ctx = app.app_context()
        self.ctx.push()
        db.create_all()
        GeoMap(unique_id='m1', name='지도', category='design').save()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.ctx.pop()

    def _save(self, **extra):
        payload = {'geo_id': 'm1', 'name': '시설', 'outer_geometry': OUTER, 'structure': 'single',
                   'bay_count': 1, 'geometry_3d': {'span_width_m': 7, 'eave_height_m': 2,
                                                   'ridge_height_m': 4, 'length_m': 30}}
        payload.update(extra)
        return FacilityManager.save_facility(payload)

    def _update(self, uuid, **extra):
        payload = {'geo_id': 'm1', 'facility_uuid': uuid, 'name': '시설', 'structure': 'single',
                   'bay_count': 1, 'geometry_3d': {'span_width_m': 7, 'eave_height_m': 2,
                                                   'ridge_height_m': 4, 'length_m': 30}}
        payload.update(extra)
        return FacilityManager.save_facility(payload)

    def test_existing_facility_has_no_layout(self):
        res, err = self._save()
        self.assertIsNone(err)
        got, err = FacilityManager.get_facility(res['facility_uuid'])
        self.assertIsNone(err)
        self.assertIsNone(got['layout'])
        self.assertIsNone(GeoFacility.query.first().layout)

    def test_valid_layout_is_saved_and_serialized(self):
        lay = _sample('two_story_nursery')
        res, err = self._save(layout=lay)
        self.assertIsNone(err)
        got, _ = FacilityManager.get_facility(res['facility_uuid'])
        self.assertEqual(got['layout'], lay)

    def test_invalid_layout_is_rejected_and_nothing_is_written(self):
        bad = _sample('two_story_nursery')
        bad['blocks'][0]['level_id'] = 'nope'
        res, err = self._save(layout=bad)
        self.assertIsNone(res)
        self.assertIn('Invalid layout', err)
        self.assertIn('unknown_level', err)
        self.assertEqual(GeoFacility.query.count(), 0)

    def test_non_object_layout_is_rejected(self):
        res, err = self._save(layout=[1, 2])
        self.assertIsNone(res)
        self.assertIn('not_object', err)

    def test_invalid_layout_on_update_keeps_the_stored_one(self):
        lay = _sample('l_shaped_connected')
        res, _ = self._save(layout=lay)
        bad = copy.deepcopy(lay)
        bad['schema'] = 99
        res2, err = self._update(res['facility_uuid'], layout=bad)
        self.assertIsNone(res2)
        self.assertIn('bad_schema', err)
        self.assertEqual(GeoFacility.query.first().layout, lay)

    def test_save_without_layout_key_keeps_the_stored_layout(self):
        # 편집 화면은 아직 모형을 고치지 않는다(F3). 키 없는 저장이 모형을 지우면 안 된다.
        lay = _sample('stepped_building')
        res, _ = self._save(layout=lay)
        res2, err = self._update(res['facility_uuid'], name='이름만 바꿈')
        self.assertIsNone(err)
        self.assertEqual(GeoFacility.query.first().layout, lay)

    def test_null_layout_clears_it(self):
        res, _ = self._save(layout=_sample('l_shaped_connected'))
        res2, err = self._update(res['facility_uuid'], layout=None)
        self.assertIsNone(err)
        self.assertIsNone(GeoFacility.query.first().layout)
        got, _ = FacilityManager.get_facility(res['facility_uuid'])
        self.assertIsNone(got['layout'])

    def test_terrain_samples_use_the_stored_layout(self):
        lay = _sample('l_shaped_connected')
        res, _ = self._save(layout=lay)
        got, _ = FacilityManager.get_facility(res['facility_uuid'])
        pts = got.get('terrain_samples')
        self.assertTrue(pts, 'terrain_samples 가 비었다')
        xs = [p[0] for p in pts]
        zs = [p[1] for p in pts]
        # ㄱ자(24 x 30)의 꼭짓점이 들어 있다 — 옛 7 x 30 직사각형에서는 나올 수 없다
        self.assertEqual((min(xs), max(xs), min(zs), max(zs)), (0.0, 24.0, 0.0, 30.0))
        self.assertIn([24.0, 12.0], pts)

    def test_terrain_samples_without_layout_are_unchanged(self):
        res, _ = self._save()
        got, _ = FacilityManager.get_facility(res['facility_uuid'])
        legacy = FL.footprint_points(FL.layout_from_legacy(got), TERRAIN_SAMPLE_STEP_M)
        self.assertEqual(got['terrain_samples'], legacy)

    def test_clone_carries_the_layout(self):
        lay = _sample('two_story_nursery')
        res, _ = self._save(layout=lay)
        clone, err = FacilityManager.clone_facility(res['facility_uuid'])
        self.assertIsNone(err)
        got, _ = FacilityManager.get_facility(clone['facility_uuid'])
        self.assertEqual(got['layout'], lay)


if __name__ == '__main__':
    unittest.main()
