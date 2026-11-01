# coding=utf-8
"""예보 현장 보정 D4 — 관측 채널 해석: 위치(기상원 지정·상속)가 정하고, 출처 표시로 거르지 않는다.

진짜 sqlite 모델. 미러 센서(범용 MQTT 드라이버)·가상 표시 센서도 쓰고, 입력 모듈이 스스로 관측이 아니라고 밝힌
것(`data_origin: model`)만 뺀다. 사용자가 트윈 설정에서 직접 고른 기온·비 채널은 상속을 덮어쓴다.
"""
import unittest
from unittest import mock

from flask import Flask

from aot.aot_flask.extensions import db
from aot.databases.models import DeviceMeasurements, GeoMap, GeoShape, Input, Misc
from aot.utils import twin_config as TC
from aot.utils.fc_cal.sources import InfluxSources

CH = (('temperature', 'C', '기온'), ('humidity', 'percent', '습도'), ('radiation', 'W_m2', '일사'),
      ('speed', 'm_s', '풍속'), ('precipitation', 'mm_h', '강우'), ('temperature', 'C', '지온'))


class SourcesTest(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.config.update(SQLALCHEMY_DATABASE_URI='sqlite://', SQLALCHEMY_TRACK_MODIFICATIONS=False)
        db.init_app(self.app)
        self.ctx = self.app.app_context()
        self.ctx.push()
        db.create_all()
        db.session.add(Misc())
        GeoMap(unique_id='m1', name='지도', category='design').save()
        GeoShape(unique_id='site-1', geo_id='m1', type='site',
                 feature={'type': 'Feature', 'geometry': {'type': 'Polygon', 'coordinates': [[
                     [126.88, 35.86], [126.88, 35.87], [126.89, 35.87], [126.89, 35.86], [126.88, 35.86]]]},
                     'properties': {'name': 'A'}}).save()
        for dev, drv in (('wx-mirror', 'MQTT_PAHO_JSON'), ('wx-model', 'OPEN_METEO_WEATHER'),
                         ('wx-virtual', 'SIMULATED_STATION')):
            db.session.add(Input(unique_id=dev, device=drv, name=dev))
            for i, (m, u, n) in enumerate(CH):
                db.session.add(DeviceMeasurements(device_id=dev, channel=i, measurement=m, unit=u, name=n))
        db.session.commit()
        self.devs = ['wx-model', 'wx-mirror']
        for target, fn in (('aot.aot_flask.geo.device_membership.weather_device_ids',
                            lambda sid: (self.devs, 'bound')),
                           ('aot.utils.inputs.model_input_drivers', lambda: frozenset({'OPEN_METEO_WEATHER'})),
                           ('aot.utils.inputs.forecast_time_input_drivers', lambda: frozenset()),
                           ('aot.utils.inputs.input_driver_of',
                            lambda d: getattr(Input.query.filter_by(unique_id=d).first(), 'device', None))):
            p = mock.patch(target, side_effect=fn)
            p.start()
            self.addCleanup(p.stop)

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.ctx.pop()

    def test_mirror_station_is_used_and_model_input_is_skipped(self):
        specs, src = InfluxSources()._observation_specs('site-1')
        self.assertEqual(src, 'bound')
        self.assertEqual(set(specs), {'T', 'RH', 'SOL', 'WS', 'RAIN'})
        self.assertTrue(all(s['device_id'] == 'wx-mirror' for s in specs.values()))     # 모델 입력은 건너뛴다
        self.assertEqual(specs['T']['channel'], 0)                                       # 지온(채널 5)이 아니다
        self.assertEqual((specs['RAIN']['unit'], specs['RAIN']['driver']), ('mm_h', 'MQTT_PAHO_JSON'))

    def test_no_provenance_filtering_virtual_station_is_used(self):
        self.devs = ['wx-virtual']
        specs, _ = InfluxSources()._observation_specs('site-1')
        self.assertEqual(specs['T']['device_id'], 'wx-virtual')

    def test_twin_config_choice_overrides_inheritance(self):
        db.session.add(Input(unique_id='my-t', device='MQTT_PAHO_JSON', name='내 기온'))
        db.session.add(DeviceMeasurements(device_id='my-t', channel=3, measurement='temperature', unit='C',
                                          name='기온'))
        db.session.commit()
        TC.save('site', 'site-1', True,
                {'inputs': {'t_air': {'unique_id': 'my-t', 'unit': 'C', 'channel': 3, 'provenance': 'virtual'}}},
                set_enabled=True)
        specs, _ = InfluxSources()._observation_specs('site-1')
        self.assertEqual((specs['T']['device_id'], specs['T']['channel']), ('my-t', 3))
        self.assertEqual(specs['RH']['device_id'], 'wx-mirror')                          # 나머지는 상속 그대로

    def test_override_pointing_at_a_model_input_is_ignored(self):
        TC.save('site', 'site-1', True,
                {'inputs': {'t_air': {'unique_id': 'wx-model', 'unit': 'C', 'channel': 0, 'provenance': 'measured'}}},
                set_enabled=True)
        specs, _ = InfluxSources()._observation_specs('site-1')
        self.assertEqual(specs['T']['device_id'], 'wx-mirror')

    def test_no_weather_station_means_no_specs(self):
        self.devs = []
        specs, _ = InfluxSources()._observation_specs('site-1')
        self.assertEqual(specs, {})


if __name__ == '__main__':
    unittest.main()
