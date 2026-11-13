# coding=utf-8
"""장소 좌표 조회 — resolve_target·get_place_overview 확장, 키 없는 get_address."""
import os
import tempfile
import unittest
from unittest.mock import patch


def _square(x0, y0, size):
    return {'type': 'Polygon', 'coordinates': [[
        [x0, y0], [x0 + size, y0], [x0 + size, y0 + size], [x0, y0 + size], [x0, y0]]]}


class TestPlaceCoords(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        from flask import Flask
        from flask_babel import Babel
        from aot.aot_flask.extensions import db
        import aot.databases.models  # noqa: F401
        from aot.databases.models import GeoMap, GeoShape

        cls._tmp = tempfile.TemporaryDirectory()
        app = Flask(__name__)
        app.config['SQLALCHEMY_DATABASE_URI'] = \
            'sqlite:///' + os.path.join(cls._tmp.name, 'coords.db')
        app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
        db.init_app(app)
        Babel(app)
        cls._ctx = app.app_context()
        cls._ctx.push()
        db.create_all()
        db.session.add(GeoMap(unique_id='map-a', name='영양'))

        def shape(uid, typ, name, geom):
            db.session.add(GeoShape(
                unique_id=uid, geo_id='map-a', type=typ,
                feature={'type': 'Feature', 'properties': {'name': name},
                         'geometry': geom}))
        shape('site-1', 'site', '좌표부지', _square(128.0, 36.0, 0.01))
        shape('site-nogeo', 'site', '도형없는부지', {'type': 'Polygon', 'coordinates': []})
        db.session.commit()

    @classmethod
    def tearDownClass(cls):
        from aot.aot_flask.extensions import db
        db.session.remove()
        cls._ctx.pop()
        cls._tmp.cleanup()

    def _svc(self):
        from aot.tools.aot_data_tool_service import AoTDataToolService
        return AoTDataToolService

    def test_place_geo_full(self):
        g = self._svc()._place_geo('site', 'site-1')
        self.assertAlmostEqual(g['center'][0], 36.004, delta=0.01)
        self.assertEqual(len(g['bbox']), 4)
        self.assertEqual(g['bbox'][:2], [36.0, 128.0])
        self.assertGreater(g['area_m2'], 0)

    def test_place_geo_list_only_center(self):
        g = self._svc()._place_geo('site', 'site-1', full=False)
        self.assertEqual(list(g), ['center'])

    def test_place_geo_missing(self):
        s = self._svc()
        self.assertEqual(s._place_geo('site', 'site-nogeo'), {})
        self.assertEqual(s._place_geo('site', 'nope'), {})
        self.assertEqual(s._place_geo('plot', 'site-1'), {})

    def test_resolve_target_has_coords(self):
        r = self._svc().resolve_target_tool('좌표부지')
        self.assertEqual(r['status'], 'success')
        self.assertIn('center', r)
        self.assertIn('bbox', r)
        self.assertIn('area_m2', r)

    def test_resolve_target_no_shape_omits(self):
        r = self._svc().resolve_target_tool('도형없는부지')
        for k in ('center', 'bbox', 'area_m2'):
            self.assertNotIn(k, r)

    def test_overview_single_and_list(self):
        s = self._svc()
        one = s.get_place_overview(place='좌표부지')
        self.assertIn('bbox', one['place'])
        self.assertIn('center', one['place'])
        none = s.get_place_overview(place='도형없는부지')
        self.assertNotIn('center', none['place'])
        self.assertIn('geo', none['place'])
        farm = s.get_place_overview()
        rows = {r['place']['name']: r['place'] for r in farm['sites']}
        self.assertIn('center', rows['좌표부지'])
        self.assertNotIn('bbox', rows['좌표부지'])
        self.assertNotIn('area_m2', rows['좌표부지'])

    def _weather_src(self, wd, coords, scope='site'):
        from aot.databases.models import GeoShape
        S = self._svc()
        shape = GeoShape.query.filter_by(unique_id='site-1').first()
        w = {'weather_device_scope': scope, 'weather_device': wd,
             'data': [{'device_name': 'OWM', 'measurement': 'temperature',
                       'readings': [{'t': 't1', 'v': 24.0}]}]}
        with patch.object(S, 'get_weather_tool', return_value=w), \
                patch('aot.utils.device_tz.resolve_location_coords',
                      side_effect=lambda i: coords.get(i, (None, None))), \
                patch('aot.space.device_membership.weather_device_ids',
                      return_value=(['d1'], 'bound')):
            return S._overview_weather(shape)

    def test_weather_source_vocab_with_coords(self):
        wd = {'name': 'OWM', 'device_id': 'd1', 'driver': 'OPEN_METEO'}
        r = self._weather_src(dict(wd, data_origin='model'),
                              {'d1': (37.2384, 127.5442), 'site-1': (36.0, 128.0)})
        src = r['source']
        self.assertEqual(src['kind'], 'model')
        self.assertEqual(src['data_origin'], 'model')
        self.assertEqual(src['scope'], 'site')
        self.assertEqual(src['placement_source'], 'weather_bound')
        self.assertEqual((src['lat'], src['lng']), (37.2384, 127.5442))
        self.assertGreater(src['distance_km'], 100)
        self.assertNotIn('coords', src)
        self.assertEqual(r['temperature'], 24.0)

    def test_weather_source_without_coords(self):
        r = self._weather_src({'name': 'KMA', 'device_id': 'd1'}, {},
                              scope='named')
        src = r['source']
        self.assertEqual(src['kind'], 'device')
        self.assertEqual(src['data_origin'], 'observed')
        self.assertEqual(src['coords'], 'unknown')
        for k in ('lat', 'lng', 'distance_km', 'placement_source'):
            self.assertNotIn(k, src)

    def test_get_address_without_key_keeps_coords(self):
        s = self._svc()
        from aot.aot_flask.geo import geo_lookup
        nokey = {'status': 'error', 'code': 'no_key', 'error': 'API Key Missing'}
        with patch.object(geo_lookup, 'find_address', return_value=nokey):
            r = s.get_address(target_id='site-1')
        self.assertEqual(r['status'], 'partial')
        self.assertEqual(r['address'], 'unavailable')
        self.assertEqual(r['reason'], 'no_key')
        self.assertAlmostEqual(r['lat'], 36.004, delta=0.01)
        self.assertIn('lng', r)
        with patch.object(geo_lookup, 'find_address', return_value=nokey):
            r2 = s.get_address(lat=37.5, lng=127.0)
        self.assertEqual((r2['lat'], r2['lng']), (37.5, 127.0))

    def test_get_address_goes_through_gate(self):
        s = self._svc()
        from aot.aot_flask.geo import geo_lookup
        ok = {'status': 'ok', 'provider': {'id': 'x', 'type': 'gis_osm'}, 'address': 'A St', 'type': 'road'}
        with patch.object(geo_lookup, 'find_address', return_value=ok) as m:
            r = s.get_address(lat=37.5, lng=127.0)
        m.assert_called_once_with(37.5, 127.0, provider=None)
        self.assertEqual((r['status'], r['address'], r['provider']), ('ok', 'A St', 'gis_osm'))


if __name__ == '__main__':
    unittest.main()
