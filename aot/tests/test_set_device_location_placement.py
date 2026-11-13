# coding=utf-8
"""set_device_location 은 장치 행 컬럼이 아니라 place_device(마커 + 바인딩)로 쓴다 — L2."""
import unittest
from unittest import mock

from aot.aot_flask.app import create_app
from aot.aot_flask.extensions import db
from aot.databases.models import (CustomController, GeoMap, GeoSetting, GeoShape,
                                  Input, PID, Trigger)



def _markers(map_uuid, device_id):
    """바인딩 기준(L4)으로 이 지도의 이 장치 마커들."""
    from aot.space.device_binding import marker_shapes
    return marker_shapes(device_id, map_uuid)


class SetDeviceLocationPlacementTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        from aot.tests._live_db_guard import refuse_live_db
        refuse_live_db()
        cls.app = create_app()
        cls.app.config['TESTING'] = True
        cls.ctx = cls.app.app_context()
        cls.ctx.push()

    @classmethod
    def tearDownClass(cls):
        cls.ctx.pop()

    def setUp(self):
        self.map = GeoMap(name='L2 set_device_location')
        self.dev = Input(name='L2 dev', device='X', interface='I2C')
        db.session.add_all([self.map, self.dev])
        db.session.commit()

    def tearDown(self):
        db.session.rollback()
        GeoShape.query.filter(GeoShape.geo_id == self.map.unique_id).delete()
        db.session.delete(self.map)
        db.session.delete(self.dev)
        db.session.commit()

    def _call(self, **kw):
        from aot.tools.aot_data_tool_service import AoTDataToolService as S
        with mock.patch('aot.aot_flask.access.write_scope.enforce'):
            return S.set_device_location(device_id=self.dev.unique_id, **kw)

    def test_places_marker_and_does_not_write_columns(self):
        r = self._call(lat=35.5, lng=126.7, map_id=self.map.unique_id)
        self.assertEqual(r.get('status'), 'placed', r)
        self.assertEqual(r['map_id'], self.map.unique_id)
        self.assertIn('location_basis', r)
        self.assertIn('source', r)
        db.session.refresh(self.dev)
        # L4 S3c(p7_08): 장치 행에 위치 컬럼이 없다 — 배치만이 정본.
        self.assertFalse(hasattr(self.dev, 'latitude'))
        self.assertFalse(hasattr(self.dev, 'longitude'))
        self.assertTrue(_markers(self.map.unique_id, self.dev.unique_id))

    def test_unknown_map_is_an_error(self):
        r = self._call(lat=1, lng=2, map_id='no-such-map')
        self.assertIn('error', r)

    def test_out_of_range_is_an_error(self):
        r = self._call(lat=95, lng=2, map_id=self.map.unique_id)
        self.assertIn('error', r)

    def test_non_input_kinds_are_placed_with_geo_vocabulary(self):
        for model, kw in ((PID, {}), (Trigger, {'trigger_type': 'trigger_sunrise_sunset'}),
                          (CustomController, {'device': 'x'})):
            obj = model(name='L2 probe', **kw)
            db.session.add(obj)
            db.session.commit()
            try:
                from aot.tools.aot_data_tool_service import AoTDataToolService as S
                with mock.patch('aot.aot_flask.access.write_scope.enforce'):
                    r = S.set_device_location(device_id=obj.unique_id, lat=35.5,
                                              lng=126.7, map_id=self.map.unique_id)
                self.assertEqual(r.get('status'), 'placed', (model.__name__, r))
                self.assertFalse(hasattr(obj, 'latitude'))
            finally:
                for m in _markers(self.map.unique_id, obj.unique_id):
                    db.session.delete(m)
                db.session.flush()
                db.session.delete(obj)
                db.session.commit()

    def test_second_call_moves_the_existing_marker(self):
        self._call(lat=35.5, lng=126.7, map_id=self.map.unique_id)
        self._call(lat=35.6, lng=126.8, map_id=self.map.unique_id)
        self.assertEqual(
            len(_markers(self.map.unique_id, self.dev.unique_id)), 1)

    def test_moving_to_another_map_leaves_no_marker_on_the_old_one(self):
        other = GeoMap(name='L2 other')
        db.session.add(other)
        db.session.commit()
        try:
            self._call(lat=35.5, lng=126.7, map_id=self.map.unique_id)
            self._call(lat=35.5, lng=126.7, map_id=other.unique_id)
            old = len(_markers(self.map.unique_id, self.dev.unique_id))
            new = len(_markers(other.unique_id, self.dev.unique_id))
            self.assertEqual((old, new), (0, 1))
        finally:
            GeoShape.query.filter_by(geo_id=other.unique_id).delete()
            db.session.delete(other)
            db.session.commit()

    def test_map_scope_denied(self):
        from aot.aot_flask.access import scope
        with mock.patch.object(scope, 'can_operate', return_value=False):
            r = self._call(lat=35.5, lng=126.7, map_id=self.map.unique_id)
        self.assertIn('error', r)
        self.assertEqual(
            len(_markers(self.map.unique_id, self.dev.unique_id)), 0)

    def test_several_maps_and_no_map_id_is_an_error(self):
        other = GeoMap(name='L2 other2')
        db.session.add(other)
        db.session.commit()
        try:
            n_maps = GeoMap.query.count()
            r = self._call(lat=35.5, lng=126.7)
            if n_maps > 1:
                self.assertIn('error', r)
        finally:
            db.session.delete(other)
            db.session.commit()

    def test_option_forms_have_no_location_fields(self):
        from aot.aot_flask.forms import (forms_conditional, forms_custom_controller,
                                         forms_function, forms_input, forms_output,
                                         forms_pid, forms_trigger)
        for cls in (forms_input.InputMod, forms_output.OutputMod, forms_pid.PIDModBase,
                    forms_function.FunctionMod, forms_conditional.Conditional,
                    forms_trigger.Trigger, forms_custom_controller.CustomController):
            for f in ('latitude', 'longitude', 'location_source'):
                self.assertFalse(hasattr(cls, f), (cls.__name__, f))

    def test_geosetting_default_start_is_none(self):
        self.assertIsNone(GeoSetting.default_lat.default)   # 서울 컬럼 기본값 없음
        self.assertIsNone(GeoSetting.default_lng.default)


if __name__ == '__main__':
    unittest.main()
