# coding=utf-8
"""새 장치의 위치는 행에 복사하지 않고 대지 기준으로 파생한다 — L2(2026-11-04).

이 파일의 앞 뜻(2026-09-25): 새 입력이 좌표 없이 만들어져 좌표가 필요한 입력
(Open-Meteo 등)이 활성화 때마다 실패했다 → 생성 때 기본 좌표를 행에 복사했다.
뒤 뜻(L2): 복사는 장치가 대지에서 떨어져 있어도 낡은 사본이 정본처럼 남는다.
행 좌표는 NULL 로 두고, 리졸버 `device_location.locate()` 가 배치가 없을 때
대지 기준(basis='site')으로 돌려준다. 드라이버(base_input)도 같은 길로 읽는다.
"""
import unittest
from types import SimpleNamespace

from aot.aot_flask.app import create_app
from aot.aot_flask.extensions import db
from aot.databases.models import GeoMap, GeoShape, Input, Misc

SITE_RING = [[126.60, 35.40], [126.80, 35.40], [126.80, 35.50],
             [126.60, 35.50], [126.60, 35.40]]


class NewDeviceSiteBasisTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        from aot.tests._live_db_guard import refuse_live_db
        refuse_live_db()
        cls.app = create_app()
        cls.app.config['TESTING'] = True
        cls.app_context = cls.app.app_context()
        cls.app_context.push()

    @classmethod
    def tearDownClass(cls):
        cls.app_context.pop()

    def setUp(self):
        self.created_inputs = []
        self.geo_map = GeoMap(name='L2 site basis test')
        db.session.add(self.geo_map)
        db.session.commit()
        self.site = GeoShape(
            geo_id=self.geo_map.unique_id, type='site',
            feature={'type': 'Feature', 'properties': {'name': 'site'},
                     'geometry': {'type': 'Polygon', 'coordinates': [SITE_RING]}})
        db.session.add(self.site)
        db.session.commit()
        if Misc.query.first() is None:
            db.session.add(Misc())
            db.session.commit()

    def tearDown(self):
        db.session.rollback()
        for uid in self.created_inputs:
            Input.query.filter(Input.unique_id == uid).delete()
        GeoShape.query.filter(GeoShape.geo_id == self.geo_map.unique_id).delete()
        db.session.delete(self.geo_map)
        db.session.commit()

    def _add_open_meteo_input(self):
        from aot.aot_flask.utils import utils_input
        from aot.utils.inputs import parse_input_information
        with self.app.test_request_context():
            dict_inputs = parse_input_information()
            key = next((k for k in dict_inputs if 'open_meteo' in k.lower()), None)
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
        return Input.query.filter(Input.unique_id == new_id).first()

    def test_new_input_row_has_no_coord_columns(self):
        # L4 S3c(p7_08): 장치 행은 위치 컬럼을 들지 않는다 — 좌표는 배치에서만.
        new_input = self._add_open_meteo_input()
        self.assertFalse(hasattr(new_input, 'latitude'))
        self.assertFalse(hasattr(new_input, 'longitude'))

    def test_new_input_locate_is_site_based(self):
        from aot.space.device_location import locate
        new_input = self._add_open_meteo_input()
        pl = locate('input', new_input.unique_id)
        self.assertEqual(pl.basis, 'site')
        self.assertEqual(pl.source, 'site')
        lat, lng = pl.point
        self.assertTrue(35.40 <= lat <= 35.50 and 126.60 <= lng <= 126.80)


if __name__ == '__main__':
    unittest.main()
