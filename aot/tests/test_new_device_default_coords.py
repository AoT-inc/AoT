# coding=utf-8
"""새 입력·출력·기능의 기본 좌표는 geo 기본 시작 위치에서 온다 — 2026-09-25.

`Misc.map_latitude/map_longitude` 는 지금 어느 UI 경로도 채우지 않아 실제
설치에서 NULL 이다. 예전에는 새 장치가 그 값을 복사해 좌표 없이 만들어졌고,
좌표가 필요한 입력(Open-Meteo 등)은 활성화 때마다 "Latitude/Longitude
required" 로 실패했다. geo 화면이 지도를 여는 `GeoSetting.default_lat/lng`
를 먼저 쓰고, 그것이 없을 때만 Misc 값을 쓴다.
"""
import unittest
from types import SimpleNamespace

from aot.aot_flask.app import create_app
from aot.aot_flask.extensions import db
from aot.databases.models import Input, Misc
from aot.databases.models.geo import GeoSetting
from aot.utils.device_tz import default_device_coords


class DefaultDeviceCoordsTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.app = create_app()
        cls.app.config['TESTING'] = True
        cls.app_context = cls.app.app_context()
        cls.app_context.push()

    @classmethod
    def tearDownClass(cls):
        cls.app_context.pop()

    def setUp(self):
        self._orig_geo = [(g.id, g.default_lat, g.default_lng)
                          for g in GeoSetting.query.all()]
        self._created_geo = False
        if not self._orig_geo:
            db.session.add(GeoSetting())
            db.session.commit()
            self._created_geo = True
        self.misc = Misc.query.first()
        self._created_misc = self.misc is None
        if self._created_misc:
            self.misc = Misc()
            db.session.add(self.misc)
            db.session.commit()
        self._orig_misc = (self.misc.map_latitude, self.misc.map_longitude)
        self.created_inputs = []

    def tearDown(self):
        db.session.rollback()
        for uid in self.created_inputs:
            Input.query.filter(Input.unique_id == uid).delete()
        if self._created_misc:
            db.session.delete(self.misc)
        else:
            self.misc.map_latitude, self.misc.map_longitude = self._orig_misc
        if self._created_geo:
            GeoSetting.query.delete()
        else:
            for gid, lat, lng in self._orig_geo:
                g = GeoSetting.query.get(gid)
                g.default_lat, g.default_lng = lat, lng
        db.session.commit()

    def _set_geo(self, lat, lng):
        g = GeoSetting.query.first()
        g.default_lat, g.default_lng = lat, lng
        db.session.commit()

    def _set_misc(self, lat, lng):
        self.misc.map_latitude, self.misc.map_longitude = lat, lng
        db.session.commit()

    def test_geo_default_used_when_misc_is_null(self):
        self._set_geo(35.43, 126.70)
        self._set_misc(None, None)
        self.assertEqual(default_device_coords(self.misc), (35.43, 126.70))

    def test_geo_default_wins_over_misc(self):
        self._set_geo(35.43, 126.70)
        self._set_misc(10.0, 20.0)
        self.assertEqual(default_device_coords(self.misc), (35.43, 126.70))

    def test_misc_used_when_geo_default_missing(self):
        self._set_geo(None, None)
        self._set_misc(10.0, 20.0)
        self.assertEqual(default_device_coords(self.misc), (10.0, 20.0))

    def test_none_when_neither_is_set(self):
        self._set_geo(None, None)
        self._set_misc(None, None)
        self.assertEqual(default_device_coords(self.misc), (None, None))

    def test_new_input_gets_geo_default_coords(self):
        from aot.aot_flask.utils import utils_input
        from aot.utils.inputs import parse_input_information

        self._set_geo(35.43, 126.70)
        self._set_misc(None, None)
        with self.app.test_request_context():
            dict_inputs = parse_input_information()
            key = next((k for k in dict_inputs
                        if 'open_meteo' in k.lower()), None)
            if key is None:
                self.skipTest('Open-Meteo 입력 모듈 없음')
            interface = (dict_inputs[key].get('interfaces') or ['Mycodo'])[0]
            form = SimpleNamespace(
                input_type=SimpleNamespace(data='{},{}'.format(key, interface)),
                validate=lambda: True)
            messages, _dep, _unmet, _msg, new_id = utils_input.input_add(form)
        if new_id:
            self.created_inputs.append(new_id)
        self.assertTrue(new_id, messages)
        new_input = Input.query.filter(Input.unique_id == new_id).first()
        self.assertEqual((new_input.latitude, new_input.longitude),
                         (35.43, 126.70))


if __name__ == '__main__':
    unittest.main()
