# coding=utf-8
"""입력 모듈 로드 캐시 (2026-10-26) — 모듈 전역 캐시가 인스턴스를 넘어 살아남는다.

`load_module_from_file` 은 부를 때마다 파일을 다시 실행해 새 모듈 객체를 만든다. 그래서 `gis_openweather._FORECAST_CACHE`
(좌표별 10분 캐시)가 한 번도 적중하지 못했고, 예보 한 번에 같은 OpenWeather 요청이 시간 칸마다 40번 나갔다(첫 조회 21~28초).
"""
import os
import tempfile
import time
import unittest
from unittest import mock

from aot.utils import modules


class LoadModuleCachedTest(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        modules._CACHED_MODULES.clear()
        self.addCleanup(modules._CACHED_MODULES.clear)
        self.path = os.path.join(self.tmp.name, 'gis_probe.py')

    def _write(self, body, bump=0):
        with open(self.path, 'w', encoding='utf-8') as fh:
            fh.write(body)
        t = time.time() + bump
        os.utime(self.path, (t, t))

    def test_the_same_file_gives_the_same_module_and_its_global_state_survives(self):
        self._write("CACHE = {}\n")
        a, status = modules.load_module_cached(self.path, 'inputs')
        self.assertEqual('success', status)
        a.CACHE['k'] = 1
        b, _ = modules.load_module_cached(self.path, 'inputs')
        self.assertIs(a, b)
        self.assertEqual({'k': 1}, b.CACHE)

    def test_the_plain_loader_still_makes_a_fresh_module_each_time(self):
        """다른 53곳이 쓰는 로더는 그대로다 — 부를 때마다 새 상태가 필요한 호출은 영향이 없다."""
        self._write("CACHE = {}\n")
        a, _ = modules.load_module_from_file(self.path, 'inputs')
        b, _ = modules.load_module_from_file(self.path, 'inputs')
        self.assertIsNot(a, b)
        self.assertIsNot(a.CACHE, b.CACHE)

    def test_an_edited_file_is_loaded_again_and_the_old_entry_is_dropped(self):
        self._write("VALUE = 1\n")
        a, _ = modules.load_module_cached(self.path, 'inputs')
        self._write("VALUE = 22\n", bump=5)                      # 사용자가 커스텀 모듈을 고쳤다
        b, _ = modules.load_module_cached(self.path, 'inputs')
        self.assertIsNot(a, b)
        self.assertEqual(22, b.VALUE)
        self.assertEqual(1, len(modules._CACHED_MODULES))        # 고친 파일의 옛 항목이 쌓이지 않는다

    def test_a_broken_file_is_not_cached_and_a_fixed_one_loads(self):
        self._write("def broken(:\n")
        with mock.patch.object(modules.logger, 'error'):
            mod, status = modules.load_module_cached(self.path, 'inputs')
        self.assertIsNone(mod)
        self.assertEqual({}, modules._CACHED_MODULES)
        self._write("OK = True\n", bump=5)
        mod, _ = modules.load_module_cached(self.path, 'inputs')
        self.assertTrue(mod.OK)

    def test_a_missing_file_falls_back_to_the_plain_loader_failure(self):
        with mock.patch.object(modules.logger, 'error'):
            mod, status = modules.load_module_cached(os.path.join(self.tmp.name, 'nope.py'), 'inputs')
        self.assertIsNone(mod)
        self.assertEqual({}, modules._CACHED_MODULES)


class GisLayerDefTest(unittest.TestCase):
    def setUp(self):
        # 정본은 `aot.inputs_gis.layer_instance`(아키텍처 4c-1) — 라우트는 같은 객체를 다시 내보낸다.
        from aot.inputs_gis import layer_instance as rgl
        self.rgl = rgl
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = os.path.join(self.tmp.name, 'gis_x.py')
        with open(self.path, 'w', encoding='utf-8') as fh:
            fh.write("X = 1\n")
        rgl._GIS_LAYER_DEFS.clear()
        self.addCleanup(rgl._GIS_LAYER_DEFS.clear)
        self.parses = []

        def parse():
            self.parses.append(1)
            return {'gis_x': {'file_path': self.path, 'custom_options': [{'id': 'o', 'default': [1]}]},
                    'gis_nofile': {}}
        patcher = mock.patch.object(rgl, 'parse_input_information', parse)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_the_route_module_re_exports_the_same_objects(self):
        from aot.aot_flask import routes_geo_layer
        from aot.aot_flask.utils import utils_geo
        self.assertIs(routes_geo_layer._GIS_LAYER_DEFS, self.rgl._GIS_LAYER_DEFS)
        self.assertIs(routes_geo_layer._gis_layer_def, self.rgl._gis_layer_def)
        self.assertIs(routes_geo_layer._load_gis_layer_instance, self.rgl._load_gis_layer_instance)
        self.assertIs(utils_geo.MockInputDev, self.rgl.MockInputDev)

    def test_the_definition_is_parsed_once_while_the_file_is_unchanged(self):
        first = self.rgl._gis_layer_def('gis_x')
        second = self.rgl._gis_layer_def('gis_x')
        self.assertEqual(first, second)
        self.assertEqual(1, len(self.parses))

    def test_an_edited_file_is_parsed_again(self):
        self.rgl._gis_layer_def('gis_x')
        with open(self.path, 'w', encoding='utf-8') as fh:
            fh.write("X = 22222\n")
        t = time.time() + 5
        os.utime(self.path, (t, t))
        self.rgl._gis_layer_def('gis_x')
        self.assertEqual(2, len(self.parses))

    def test_unknown_types_are_never_cached_so_new_custom_modules_show_up(self):
        for _ in range(2):
            self.assertEqual({}, self.rgl._gis_layer_def('gis_new'))
            self.assertEqual({}, self.rgl._gis_layer_def('gis_nofile'))
        self.assertEqual(4, len(self.parses))

    def test_callers_get_a_copy_so_one_instance_cannot_change_the_next(self):
        self.rgl._gis_layer_def('gis_x')
        mine = self.rgl._gis_layer_def('gis_x')
        mine['custom_options'][0]['default'].append(2)
        mine['file_path'] = 'changed'
        again = self.rgl._gis_layer_def('gis_x')
        self.assertEqual([1], again['custom_options'][0]['default'])
        self.assertEqual(self.path, again['file_path'])


class OpenWeatherInstancesShareTheirCacheTest(unittest.TestCase):
    """실제 gis_openweather 모듈로: 같은 레이어를 두 번 만들어도 모듈 전역 예보 캐시가 같은 사전이다."""

    @classmethod
    def setUpClass(cls):
        from flask import Flask
        from flask_babel import Babel
        from aot.aot_flask.extensions import db
        import aot.databases.models  # noqa: F401
        from aot.databases.models import GeoLayer
        cls._tmp = tempfile.TemporaryDirectory()
        app = Flask(__name__)
        app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(cls._tmp.name, 'gis.db')
        app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
        db.init_app(app)
        Babel(app)
        cls._ctx = app.app_context()
        cls._ctx.push()
        db.create_all()
        layer = GeoLayer(unique_id='L-ow', name='OW', type='gis_openweather', options='{"api_key": "k"}')
        db.session.add(layer)
        db.session.commit()

    @classmethod
    def tearDownClass(cls):
        from aot.aot_flask.extensions import db
        db.session.remove()
        cls._ctx.pop()
        cls._tmp.cleanup()

    def test_two_instances_use_one_forecast_cache_so_one_request_serves_every_time_cell(self):
        from aot.aot_flask.routes_geo_layer import _load_gis_layer_instance
        a = _load_gis_layer_instance('L-ow')
        b = _load_gis_layer_instance('L-ow')
        self.assertIsNotNone(a)
        self.assertIs(type(a), type(b))
        self.assertIs(type(a).__init__.__globals__['_FORECAST_CACHE'],
                      type(b).__init__.__globals__['_FORECAST_CACHE'])

    def test_a_sweep_over_forty_time_cells_asks_openweather_once(self):
        import requests
        from aot.aot_flask.routes_geo_layer import _load_gis_layer_instance
        now = time.time()
        items = [{'dt': int(now) + 3 * 3600 * i, 'main': {'temp': 10 + i}, 'wind': {'speed': 2},
                  'clouds': {'all': 10}} for i in range(1, 40)]
        resp = mock.Mock(status_code=200)
        resp.json.return_value = {'list': items}
        with mock.patch.object(requests, 'get', return_value=resp) as get:
            for i in range(40):
                inst = _load_gis_layer_instance('L-ow')
                inst.get_ambient_forecast(36.7, 129.1 + 0.0001, now + 3600 * (i + 1))
        self.assertEqual(1, get.call_count)


if __name__ == '__main__':
    unittest.main()
