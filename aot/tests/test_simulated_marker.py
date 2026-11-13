# coding=utf-8
"""시뮬레이션 장치 표시(E8-2 1단계) — 드라이버·이름 접두로 판별해 응답에 표시만 한다.

라이브 DB를 쓰지 않는다(임시 sqlite). 평균·침묵·경보 계산은 건드리지 않는다.
"""
import os
import tempfile
import unittest
from datetime import datetime, timezone
from unittest import mock

from aot.tools.sim_marker import is_simulated, sim_fields


class TestIsSimulated(unittest.TestCase):

    def test_test_driver_is_confirmed(self):
        self.assertEqual((True, 'driver_test'),
                         is_simulated('input', 'TEST_SAVE_VALUE', '현장센서 3-1'))

    def test_virtual_output_is_not_asserted_simulated(self):
        for t in ('virtual_on_off_single', 'virtual_on_off_multi'):
            self.assertEqual((None, 'driver_virtual'),
                             is_simulated('output', t, '관수밸브'))
            self.assertEqual({'virtual': True}, sim_fields('output', t, '관수밸브'))

    def test_virtual_prefix_only_applies_to_outputs(self):
        self.assertEqual((None, None),
                         is_simulated('input', 'virtual_on_off_single', 'x'))

    def test_name_prefix_boundaries(self):
        for name in ('SIM 난방기', 'sim 가습기', 'Sim-01', '  SIM 현장센서 3-1',
                     'Simulator-01', 'SIM_김제'.replace('_', ' ')):
            self.assertEqual((True, 'name_prefix'),
                             is_simulated('input', 'MQTT_PAHO_JSON', name), name)
        for name in ('Similar', 'Simple', '미러-온습도01', 'MQTT JSON',
                     '난방기 SIM', 'ASIM 1', '', None):
            self.assertEqual((None, None),
                             is_simulated('input', 'MQTT_PAHO_JSON', name), name)

    def test_virtual_output_with_sim_name_gets_both(self):
        self.assertEqual(
            {'simulated': True, 'sim_basis': 'name_prefix', 'virtual': True},
            sim_fields('output', 'virtual_on_off_single', 'SIM 난방기'))

    def test_driver_beats_name(self):
        self.assertEqual({'simulated': True, 'sim_basis': 'driver_test'},
                         sim_fields('input', 'TEST_SAVE_VALUE', 'SIM x'))

    def test_ordinary_device_has_no_fields(self):
        self.assertEqual({}, sim_fields('input', 'MQTT_PAHO_JSON', '미러-온습도01'))
        self.assertEqual({}, sim_fields('output', 'on_off_gpio', '밸브'))


def _square(x0, y0, size):
    return {'type': 'Polygon', 'coordinates': [[
        [x0, y0], [x0 + size, y0], [x0 + size, y0 + size], [x0, y0 + size],
        [x0, y0]]]}


def _point(x, y):
    return {'type': 'Point', 'coordinates': [x, y]}


class TestSimulatedInResponses(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        from flask import Flask
        from flask_babel import Babel
        from aot.aot_flask.extensions import db
        import aot.databases.models  # noqa: F401
        from aot.databases.models import (DeviceMeasurements, GeoMap, GeoShape,
                                          Input, Output)

        cls._tmp = tempfile.TemporaryDirectory()
        app = Flask(__name__)
        app.config['SQLALCHEMY_DATABASE_URI'] = \
            'sqlite:///' + os.path.join(cls._tmp.name, 'sim.db')
        app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
        db.init_app(app)
        Babel(app)
        cls._ctx = app.app_context()
        cls._ctx.push()
        db.create_all()

        db.session.add(GeoMap(unique_id='map-a', name='김제'))

        def shape(uid, typ, name, geom, device_id=None):
            db.session.add(bound_shape(
                unique_id=uid, geo_id='map-a', type=typ, device_id=device_id,
                feature={'type': 'Feature', 'properties': {'name': name},
                         'geometry': geom}))

        shape('zone-1', 'zone', '시험구역', _square(0.0, 0.0, 0.05))

        def sensor(uid, name, driver, x):
            db.session.add(Input(unique_id=uid, name=name, device=driver,
                                 is_activated=True))
            shape('mk-' + uid, 'aot_device', name, _point(x, x), device_id=uid)
            db.session.add(DeviceMeasurements(
                device_id=uid, channel=0, measurement='temperature', unit='C'))

        sensor('in-sim', '현장센서 3-1', 'TEST_SAVE_VALUE', 0.001)
        sensor('in-name', 'SIM 김제 기상대', 'OPEN_METEO_FORECAST', 0.002)
        sensor('in-real', '미러-온습도01', 'MQTT_PAHO_JSON', 0.003)
        db.session.add(Output(unique_id='out-sim', name='SIM 난방기',
                              output_type='virtual_on_off_single'))
        db.session.add(Output(unique_id='out-virt', name='관수밸브',
                              output_type='virtual_on_off_single'))
        db.session.add(Output(unique_id='out-real', name='환풍기',
                              output_type='on_off_gpio'))
        db.session.commit()

    @classmethod
    def tearDownClass(cls):
        from aot.aot_flask.extensions import db
        db.session.remove()
        cls._ctx.pop()
        cls._tmp.cleanup()

    def setUp(self):
        from aot.space import shape_index
        shape_index.invalidate()

    @property
    def S(self):
        from aot.tools.aot_data_tool_service import AoTDataToolService
        return AoTDataToolService

    def _by_id(self, results):
        return {r['id']: r for r in results}

    def test_device_list(self):
        r = self._by_id(self.S.get_device_list_tool()['results'])
        self.assertEqual('driver_test', r['in-sim']['sim_basis'])
        self.assertTrue(r['in-sim']['simulated'])
        self.assertEqual('name_prefix', r['in-name']['sim_basis'])
        self.assertEqual('name_prefix', r['out-sim']['sim_basis'])
        self.assertTrue(r['out-sim']['virtual'])
        self.assertEqual({'virtual': True},
                         {k: v for k, v in r['out-virt'].items()
                          if k in ('simulated', 'sim_basis', 'virtual')})
        for uid in ('in-real', 'out-real'):
            for k in ('simulated', 'sim_basis', 'virtual'):
                self.assertNotIn(k, r[uid])

    def test_search_devices(self):
        r = self._by_id(self.S.search_devices(query='SIM')['results'])
        self.assertIn('in-name', r)
        self.assertTrue(r['in-name']['simulated'])
        r = self._by_id(self.S.search_devices(query='미러')['results'])
        self.assertNotIn('simulated', r['in-real'])

    def test_device_detail(self):
        d = self.S.get_device_detail('in-sim')
        what = d.get('what') or d
        self.assertTrue(what['simulated'], d)
        self.assertEqual('driver_test', what['sim_basis'])
        d = self.S.get_device_detail('in-real')
        self.assertNotIn('simulated', d.get('what') or d)

    def test_zone_summary_marks_but_keeps_in_the_data(self):
        now = datetime(2026, 10, 9, 0, 0, tzinfo=timezone.utc)
        with mock.patch('aot.utils.influx.read_influxdb_list',
                        return_value=[(now, 20.0)]):
            out = self.S.get_zone_sensor_summary(zone_ids=['시험구역'], detail=True)
        devs = {d['device_id']: d for d in out['zones'][0]['sensors']}
        self.assertTrue(devs['in-sim']['simulated'])
        self.assertEqual('driver_test', devs['in-sim']['sim_basis'])
        self.assertNotIn('simulated', devs['in-real'])
        # 표시만 한다 — 센서 목록에서 빼지 않는다.

    def test_screen_marker_set(self):
        got = self.S._screen_sim_devices(['in-sim', 'in-name', 'in-real'])
        self.assertEqual({'in-sim', 'in-name'}, got)

    def test_overview_weather_source_marks_sim(self):
        shape = mock.Mock(unique_id='zone-1', type='zone')
        w = {'weather_device': {'name': 'SIM 김제 기상대', 'device_id': 'in-name',
                                'driver': 'OPEN_METEO_FORECAST'},
             'weather_device_scope': 'unplaced'}
        src = self.S._overview_weather_source(shape, w, 'SIM 김제 기상대')
        self.assertTrue(src['simulated'])
        self.assertEqual('name_prefix', src['sim_basis'])
        w['weather_device'] = {'name': '기상청', 'device_id': 'x',
                               'driver': 'MQTT_PAHO_JSON'}
        self.assertNotIn('simulated',
                         self.S._overview_weather_source(shape, w, '기상청'))


if __name__ == '__main__':
    unittest.main()
from aot.tests.geo._legacy_marker import bound_shape
