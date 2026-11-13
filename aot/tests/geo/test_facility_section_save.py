# coding=utf-8
"""시설 저장 재수화·부분 저장(S2) — `merge_section`, `PATCH /api/geo/facility/<uuid>`, `include`.

계약:
- `POST /api/geo/facility` 는 그대로다. `include` 를 주면 응답에 `facility`(GET 본문)와
  `integration` 이 더 실린다. 주지 않으면 응답 키가 늘지 않는다.
- `PATCH` 는 한 묶음만 바꾸고 나머지(치수·외피·구역 총량·다경간 구역 도형·장치 연결)는 그대로 둔다.
- `GET /api/geo/facility/choices` 는 페이지가 Jinja 로 받던 센서 선택지와 같은 다섯 키를 낸다.
"""
import os

os.environ.setdefault("ALEMBIC_RUNNING", "1")

import unittest
from unittest import mock

from flask import Flask

from aot.aot_flask.extensions import db
from aot.space import facility_io as FIO
from aot.space.facility_io import FacilityManager
from aot.databases.models import GeoFacility, GeoMap, GeoShape

OUTER = {'type': 'Polygon', 'coordinates': [[[127.0, 36.0], [127.001, 36.0], [127.001, 36.001],
                                              [127.0, 36.001], [127.0, 36.0]]]}
HALF_A = {'type': 'Polygon', 'coordinates': [[[127.0, 36.0], [127.0005, 36.0], [127.0005, 36.001],
                                               [127.0, 36.001], [127.0, 36.0]]]}
HALF_B = {'type': 'Polygon', 'coordinates': [[[127.0005, 36.0], [127.001, 36.0], [127.001, 36.001],
                                               [127.0005, 36.001], [127.0005, 36.0]]]}


def _unwrap(fn):
    while hasattr(fn, '__wrapped__'):
        fn = fn.__wrapped__
    return fn


def _status(rv):
    if isinstance(rv, tuple):
        return rv[1]
    return getattr(rv, 'status_code', 200)


def _json(rv):
    resp = rv[0] if isinstance(rv, tuple) else rv
    return resp.get_json()


class TestMergeSection(unittest.TestCase):
    """DB 없이 — 페이로드 병합 규칙만."""

    BASE = {
        'facility_uuid': 'f1', 'geo_id': 'm1', 'name': '온실', 'structure': 'single', 'bay_count': 1,
        'geometry_3d': {'span_width_m': 8, 'length_m': 40, 'center_lng': 127.0, 'center_lat': 36.0,
                        'orientation_deg': 10},
        'envelope': {'side_vent': True}, 'fittings': [{'id': 'a', 'kind': 'fan'}],
        'view_options': {'category_visibility': {'fan': True}, 'sensor_ranges': {'t': [1]}},
        'weather_bindings': [], 'groups': {},
    }

    def test_unknown_section_is_refused(self):
        payload, err = FIO.merge_section(self.BASE, 'roof', {})
        self.assertIsNone(payload)
        self.assertIn('Unknown section', err)

    def test_key_outside_the_section_is_refused_not_dropped(self):
        payload, err = FIO.merge_section(self.BASE, 'connections', {'groups': {}, 'name': 'x'})
        self.assertIsNone(payload)
        self.assertIn('name', err)

    def test_fittings_list_replaces_only_fittings(self):
        payload, err = FIO.merge_section(self.BASE, 'fittings', [{'id': 'b', 'kind': 'sensor'}])
        self.assertIsNone(err)
        self.assertEqual(payload['fittings'], [{'id': 'b', 'kind': 'sensor'}])
        self.assertEqual(payload['envelope'], {'side_vent': True})
        self.assertEqual(payload['geometry_3d'], self.BASE['geometry_3d'])
        self.assertEqual(self.BASE['fittings'], [{'id': 'a', 'kind': 'fan'}], '원본은 건드리지 않는다')

    def test_envelope_dict_is_the_envelope(self):
        payload, _ = FIO.merge_section(self.BASE, 'envelope', {'roof_vent': True})
        self.assertEqual(payload['envelope'], {'roof_vent': True})
        payload, _ = FIO.merge_section(self.BASE, 'envelope', {'envelope': {'curtain': 1}})
        self.assertEqual(payload['envelope'], {'curtain': 1})

    def test_spec_dimensions_keep_the_position(self):
        payload, _ = FIO.merge_section(self.BASE, 'spec', {'geometry_3d': {'span_width_m': 9}})
        g = payload['geometry_3d']
        self.assertEqual(g['span_width_m'], 9)
        self.assertEqual((g['center_lng'], g['center_lat'], g['orientation_deg']), (127.0, 36.0, 10))
        self.assertEqual(g['length_m'], 40)

    def test_connections_label_colors_keep_the_display_filter(self):
        payload, _ = FIO.merge_section(self.BASE, 'connections',
                                       {'view_options': {'sensor_ranges': {'t': [2]}}})
        self.assertEqual(payload['view_options'],
                         {'category_visibility': {'fan': True}, 'sensor_ranges': {'t': [2]}})

    def test_non_object_data_is_refused(self):
        _, err = FIO.merge_section(self.BASE, 'spec', ['x'])
        self.assertIn('object', err)


class _DB(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.config.update(SQLALCHEMY_DATABASE_URI='sqlite://', SQLALCHEMY_TRACK_MODIFICATIONS=False,
                               TESTING=True, SECRET_KEY='t')
        db.init_app(self.app)
        from flask_babel import Babel
        Babel(self.app)
        self.ctx = self.app.app_context()
        self.ctx.push()
        db.create_all()
        m = GeoMap()
        m.unique_id = 'm1'
        m.name = '지도'
        db.session.add(m)
        db.session.commit()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.ctx.pop()

    def save(self, **kw):
        p = {'geo_id': 'm1', 'name': '시설', 'outer_geometry': OUTER, 'structure': 'single', 'bay_count': 1,
             'geometry_3d': {'span_width_m': 8, 'eave_height_m': 3, 'ridge_height_m': 5, 'length_m': 40,
                             'center_lng': 127.0005, 'center_lat': 36.0005, 'orientation_deg': 0},
             'envelope': {'side_vent': True},
             'fittings': [{'id': 'F1', 'kind': 'fan', 'position': {'x': 1, 'y': 1, 'z': 1}}],
             'weather_bindings': [], 'groups': {'g1': {'type': 'multi_stage'}},
             'view_options': {'category_visibility': {'fan': False}}}
        p.update(kw)
        res, err = FacilityManager.save_facility(p)
        self.assertIsNone(err)
        return res


class TestSaveSection(_DB):
    def test_fittings_patch_keeps_everything_else(self):
        uuid = self.save()['facility_uuid']
        res, err = FacilityManager.save_section(
            uuid, 'fittings', [{'id': 'F2', 'kind': 'sensor', 'position': {'x': 2, 'y': 0, 'z': 2}}])
        self.assertIsNone(err)
        self.assertTrue(res['ok'])
        f = GeoFacility.query.filter_by(unique_id=uuid).first()
        self.assertEqual([x['id'] for x in f.fittings], ['F2'])
        self.assertEqual(f.envelope, {'side_vent': True})
        self.assertEqual(f.geometry_3d['span_width_m'], 8)
        self.assertEqual(f.name, '시설')
        self.assertEqual(f.groups, {'g1': {'type': 'multi_stage'}})
        self.assertEqual(f.view_options['category_visibility'], {'fan': False})

    def test_connections_patch_keeps_fittings_and_shape(self):
        uuid = self.save()['facility_uuid']
        shape_before = GeoShape.query.filter_by(type='facility').first().feature['geometry']
        _, err = FacilityManager.save_section(uuid, 'connections', {'groups': {}})
        self.assertIsNone(err)
        f = GeoFacility.query.filter_by(unique_id=uuid).first()
        self.assertEqual(f.groups, {})
        self.assertEqual([x['id'] for x in f.fittings], ['F1'])
        self.assertEqual(GeoShape.query.filter_by(type='facility').first().feature['geometry'], shape_before)

    def test_zone_capacity_survives_a_patch(self):
        uuid = self.save(structure='connected', bay_count=2,
                         bays=[{'id': 'z1', 'bay_start': 1, 'bay_end': 2, 'name': '전체',
                                'capacity': {'unit': 'bed', 'total': 12}}])['facility_uuid']
        _, err = FacilityManager.save_section(uuid, 'fittings', [])
        self.assertIsNone(err)
        bays = GeoFacility.query.filter_by(unique_id=uuid).first().bays
        self.assertEqual(len(bays), 1)
        self.assertEqual((bays[0]['bay_start'], bays[0]['bay_end']), (1, 2))
        self.assertEqual(bays[0]['capacity'], {'unit': 'bed', 'total': 12})

    def test_connected_bay_polygons_are_rebuilt_from_stored_shapes(self):
        uuid = self.save(structure='connected', bay_count=2,
                         bays=[{'id': 'b1', 'geometry': HALF_A, 'name': '1동'},
                               {'id': 'b2', 'geometry': HALF_B, 'name': '2동'}])['facility_uuid']
        _, err = FacilityManager.save_section(uuid, 'envelope', {'side_vent': False})
        self.assertIsNone(err)
        shapes = GeoShape.query.filter_by(type='facility_bay').all()
        self.assertEqual(sorted(s.feature['properties']['name'] for s in shapes), ['1동', '2동'])
        self.assertIn(HALF_A, [s.feature['geometry'] for s in shapes])
        f = GeoFacility.query.filter_by(unique_id=uuid).first()
        self.assertEqual(f.envelope, {'side_vent': False})
        self.assertEqual([b['id'] for b in f.bays], ['b1', 'b2'])

    def test_spec_rename_reaches_the_outline(self):
        uuid = self.save()['facility_uuid']
        FacilityManager.save_section(uuid, 'spec', {'name': '새 이름'})
        self.assertEqual(GeoShape.query.filter_by(type='facility').first().feature['properties']['name'],
                         '새 이름')

    def test_position_patch_keeps_parent_site_unless_sent(self):
        site = GeoShape(type='site', geo_id='m1', feature={'type': 'Feature', 'geometry': OUTER,
                                                            'properties': {'name': '대지'}})
        db.session.add(site)
        db.session.commit()
        uuid = self.save(site_shape_uuid=site.unique_id)['facility_uuid']
        FacilityManager.save_section(uuid, 'fittings', [])
        fac_shape = GeoShape.query.filter_by(type='facility').first()
        self.assertEqual(fac_shape.parent_id, site.id)
        FacilityManager.save_section(uuid, 'position', {'site_shape_uuid': ''})
        self.assertIsNone(GeoShape.query.filter_by(type='facility').first().parent_id)

    def test_unknown_facility(self):
        res, err = FacilityManager.save_section('nope', 'fittings', [])
        self.assertIsNone(res)
        self.assertIn('not found', err.lower())


class TestRoutes(_DB):
    def _call(self, view_name, path, method, body=None, allowed=True, **kw):
        from aot.aot_flask import routes_geo_facility as R
        from aot.aot_flask.utils import utils_general
        view = _unwrap(getattr(R, view_name))
        user = mock.Mock(id=1)
        with mock.patch.object(utils_general, 'user_has_permission', return_value=allowed), \
                mock.patch.object(R, 'current_user', user), \
                mock.patch('aot.space.facility_integration.get_facility_integration',
                           return_value=({'facility': {'name': 'x'}, 'actuators': []}, None)):
            with self.app.test_request_context(path, method=method, json=body):
                return view(**kw)

    def _post_body(self):
        return {'geo_id': 'm1', 'name': '시설', 'outer_geometry': OUTER, 'structure': 'single',
                'bay_count': 1, 'geometry_3d': {'span_width_m': 8, 'length_m': 40},
                'fittings': [{'id': 'F1', 'kind': 'fan'}]}

    def test_post_without_include_keeps_the_old_response(self):
        rv = self._call('api_facility_save', '/api/geo/facility', 'POST', self._post_body())
        j = _json(rv)
        self.assertTrue(j['ok'])
        self.assertNotIn('facility', j)
        self.assertNotIn('integration', j)

    def test_post_include_query_carries_facility_and_integration(self):
        rv = self._call('api_facility_save', '/api/geo/facility?include=facility,integration', 'POST',
                        self._post_body())
        j = _json(rv)
        self.assertEqual(j['facility']['unique_id'], j['facility_uuid'])
        self.assertEqual([f['id'] for f in j['facility']['fittings']], ['F1'])
        self.assertIn('outer_feature', j['facility'], 'GET 과 같은 본문(도형 포함)')
        self.assertEqual(j['integration']['ok'], True)
        self.assertEqual(j['integration']['facility'], {'name': 'x'})

    def test_post_include_in_body_is_not_stored(self):
        body = dict(self._post_body(), include=['facility'])
        j = _json(self._call('api_facility_save', '/api/geo/facility', 'POST', body))
        self.assertIn('facility', j)
        self.assertNotIn('integration', j)

    def test_patch_saves_one_section_and_rehydrates(self):
        uuid = self.save()['facility_uuid']
        rv = self._call('api_facility_save_section', '/api/geo/facility/%s?include=facility' % uuid, 'PATCH',
                        {'section': 'fittings', 'data': [{'id': 'F9', 'kind': 'fan'}]},
                        facility_uuid=uuid)
        self.assertEqual(_status(rv), 200)
        j = _json(rv)
        self.assertTrue(j['ok'])
        self.assertEqual(j['facility_uuid'], uuid)
        self.assertEqual([f['id'] for f in j['facility']['fittings']], ['F9'])
        self.assertEqual(j['facility']['envelope'], {'side_vent': True})

    def test_patch_needs_edit_settings(self):
        uuid = self.save()['facility_uuid']
        rv = self._call('api_facility_save_section', '/api/geo/facility/' + uuid, 'PATCH',
                        {'section': 'fittings', 'data': []}, allowed=False, facility_uuid=uuid)
        self.assertEqual(_status(rv), 403)
        self.assertEqual([x['id'] for x in GeoFacility.query.first().fittings], ['F1'])

    def test_patch_bad_requests(self):
        uuid = self.save()['facility_uuid']
        self.assertEqual(_status(self._call('api_facility_save_section', '/x', 'PATCH',
                                            {'data': []}, facility_uuid=uuid)), 400)
        self.assertEqual(_status(self._call('api_facility_save_section', '/x', 'PATCH',
                                            {'section': 'fittings'}, facility_uuid=uuid)), 400)
        self.assertEqual(_status(self._call('api_facility_save_section', '/x', 'PATCH',
                                            {'section': 'roof', 'data': {}}, facility_uuid=uuid)), 400)
        self.assertEqual(_status(self._call('api_facility_save_section', '/x', 'PATCH',
                                            {'section': 'fittings', 'data': []}, facility_uuid='nope')), 404)

    def test_choices_has_the_page_keys(self):
        rv = self._call('api_facility_choices', '/api/geo/facility/choices', 'GET')
        j = _json(rv)
        self.assertTrue(j['ok'])
        for k in ('choices_input', 'choices_function', 'meas_id_slug', 'input_devices', 'function_devices'):
            self.assertIn(k, j)
        self.assertEqual(_status(self._call('api_facility_choices', '/x', 'GET', allowed=False)), 403)

    def test_patch_route_is_registered_once(self):
        from aot.aot_flask import routes_geo
        app = Flask('reg')
        app.register_blueprint(routes_geo.blueprint)
        rules = [(str(r), sorted(r.methods - {'HEAD', 'OPTIONS'})) for r in app.url_map.iter_rules()
                 if str(r) in ('/api/geo/facility/<facility_uuid>', '/api/geo/facility/choices')]
        self.assertIn(('/api/geo/facility/<facility_uuid>', ['PATCH']), rules)
        self.assertIn(('/api/geo/facility/choices', ['GET']), rules)
        adapter = app.url_map.bind('localhost')
        self.assertEqual(adapter.match('/api/geo/facility/choices', method='GET')[0],
                         'routes_geo.api_facility_choices')


if __name__ == '__main__':
    unittest.main()
