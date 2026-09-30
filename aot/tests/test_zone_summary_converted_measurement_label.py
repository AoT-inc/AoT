# coding=utf-8
"""get_zone_sensor_summary()가 단위 변환(Conversion)이 걸린 채널의 measurement
라벨을 비운다(2026-09-25 실사용 조사 재현).

실사용 조사(로컬 8084, MQTT 미러 온습도 센서): DeviceMeasurements.unit='F'에
표준 F→C Conversion(protected)이 걸린 온도 채널을 get_zone_sensor_summary로
조회하면 unit은 올바르게 'C'로 변환돼 나오는데 measurement가 null로 빈다.
같은 값을 get_sensor_detail/_read_series로 조회하면 measurement가 정상
("temperature")으로 나온다 — 두 도구가 같은 aot/utils/system_pi.py의
return_measurement_info()를 쓰는데, get_sensor_detail 쪽만
`measurement or m.measurement` 폴백을 갖고 있고 get_zone_sensor_summary는
없기 때문이다.

return_measurement_info()는 conversion_id가 걸린 채널에 대해 measurement를
항상 None으로 돌려준다(aot/utils/system_pi.py) — 이것 자체는 여러 호출부가
공유하는 기존 동작이라 바꾸지 않는다. 대신 get_zone_sensor_summary가 그
None을 DeviceMeasurements.measurement로 채우지 않고 그대로 내보내는 지점
(aot/tools/data_tools/measurement.py)이 이 테스트가 고정하는 결함이다.

부작용 확인: 한 장치에 변환이 걸린 채널이 둘 이상(예: 온도+풍속) 있으면
measurement가 둘 다 None이 되어 "같은 측정을 여러 채널이 쓴다" 오경고까지
함께 발생한다(aot/tools/data_tools/measurement.py의 seen 딕셔너리가
(device_id, measurement)를 키로 쓰기 때문) — 이것도 함께 재현·고정한다.

라이브 DB를 쓰지 않는다(임시 sqlite).
"""
import os
import tempfile
import unittest
from datetime import date, datetime, timezone
from unittest import mock


def _square(x0, y0, size):
    return {'type': 'Polygon', 'coordinates': [[
        [x0, y0], [x0 + size, y0], [x0 + size, y0 + size], [x0, y0 + size],
        [x0, y0]]]}


def _point(x, y):
    return {'type': 'Point', 'coordinates': [x, y]}


class TestZoneSummaryConvertedMeasurementLabel(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        from flask import Flask
        from flask_babel import Babel
        from aot.aot_flask.extensions import db
        import aot.databases.models  # noqa: F401
        from aot.databases.models import (Conversion, DeviceMeasurements,
                                          GeoMap, GeoShape, Input)

        cls._tmp = tempfile.TemporaryDirectory()
        app = Flask(__name__)
        app.config['SQLALCHEMY_DATABASE_URI'] = \
            'sqlite:///' + os.path.join(cls._tmp.name, 'conv.db')
        app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
        db.init_app(app)
        Babel(app)
        cls.flask_app = app
        cls._ctx = app.app_context()
        cls._ctx.push()
        db.create_all()

        db.session.add(GeoMap(unique_id='map-a', name='영양'))

        def shape(uid, typ, name, geom, device_id=None):
            db.session.add(GeoShape(
                unique_id=uid, geo_id='map-a', type=typ, device_id=device_id,
                feature={'type': 'Feature', 'properties': {'name': name},
                         'geometry': geom}))

        shape('zone-1', 'zone', '육묘장', _square(0.0, 0.0, 0.05))

        # 실사용과 동일한 모양: MQTT 입력 하나에 채널 둘, 둘 다 표준 protected
        # Conversion이 걸려 있다(온도 F→C, 풍속 mph→m_s).
        db.session.add(Input(unique_id='dev-1', name='미러-온습도01',
                             device='MQTT_PAHO_JSON', is_activated=True))
        shape('mk-dev-1', 'aot_device', '미러-온습도01', _point(0.001, 0.001),
              device_id='dev-1')

        db.session.add(Conversion(unique_id='conv-f2c', convert_unit_from='F',
                                  convert_unit_to='C', equation='(x-32)*5/9',
                                  protected=True))
        db.session.add(Conversion(unique_id='conv-mph2ms', convert_unit_from='mph',
                                  convert_unit_to='m_s', equation='x*0.44704',
                                  protected=True))
        db.session.add(DeviceMeasurements(
            device_id='dev-1', channel=0, measurement='temperature',
            unit='F', conversion_id='conv-f2c'))
        db.session.add(DeviceMeasurements(
            device_id='dev-1', channel=1, measurement='speed',
            unit='mph', conversion_id='conv-mph2ms'))
        db.session.commit()

    @classmethod
    def tearDownClass(cls):
        from aot.aot_flask.extensions import db
        db.session.remove()
        cls._ctx.pop()
        cls._tmp.cleanup()

    def setUp(self):
        from aot.aot_flask.geo import shape_index
        shape_index.invalidate()
        self.measure_args_seen = []

    @property
    def S(self):
        from aot.tools.aot_data_tool_service import AoTDataToolService
        return AoTDataToolService

    def _fake_read_influxdb_list(self, device_id, unit, channel, measure=None, **kw):
        # 표시용 라벨을 채우는 수정이 이 인자까지 채워 넘기면 실제
        # query_flux의 `if measure:` 필터가 걸려 버린다 — 변환된 채널의
        # Influx 포인트에는 애초에 "measure" 태그가 없으므로(쓰기 쪽도 같은
        # None을 받는다) 그러면 결과가 통째로 사라진다. 호출마다 실제로
        # 넘어온 값을 기록해 두고 아래에서 검증한다.
        self.measure_args_seen.append((channel, measure))
        now = datetime.now(timezone.utc)
        value = 25.9 if channel == 0 else 1.7
        return [(now, value)]

    def test_converted_channel_keeps_its_measurement_label(self):
        """온도(F→C 변환) 채널의 measurement가 null로 비면 안 된다."""
        with mock.patch('aot.utils.influx.read_influxdb_list',
                        side_effect=self._fake_read_influxdb_list):
            out = self.S.get_zone_sensor_summary(zone_ids=['육묘장'])

        self.assertEqual(1, out.get('count'), out)
        sensors = {r['channel']: r for r in out['zones'][0]['sensors']}
        self.assertEqual(2, len(sensors), out)

        temp = sensors[0]
        self.assertEqual('C', temp['unit'], '단위 변환 자체는 정상')
        self.assertEqual('temperature', temp['measurement'],
                         "변환이 걸린 채널의 measurement가 비었다 — "
                         "get_zone_sensor_summary가 DeviceMeasurements."
                         "measurement로 폴백하지 않는다.")

        speed = sensors[1]
        self.assertEqual('m_s', speed['unit'])
        self.assertEqual('speed', speed['measurement'])

        # 회귀 가드: 표시용 라벨을 채우는 폴백이 read_influxdb_list의
        # `measure=` 인자까지 덩달아 채우면 안 된다 — 변환된 채널의 Influx
        # 포인트에는 measure 태그 자체가 없어서, 채워 넘기면 query_flux가
        # 결과를 통째로 걸러 버린다(라벨은 채워지는데 값이 사라지는
        # 형태로 재발한다).
        self.assertTrue(self.measure_args_seen, '모킹이 호출되지 않았다')
        for channel, measure in self.measure_args_seen:
            self.assertIsNone(
                measure,
                f"channel {channel}: measure={measure!r}로 넘어감 — "
                "변환된 채널은 measure 필터 없이 조회해야 한다.")

    def test_no_false_same_measurement_warning(self):
        """measurement가 둘 다 None으로 비면 서로 다른 두 채널(온도·풍속)이
        '같은 측정을 여러 채널이 쓴다'는 오경고를 낸다 — 라벨이 채워지면
        사라져야 한다."""
        with mock.patch('aot.utils.influx.read_influxdb_list',
                        side_effect=self._fake_read_influxdb_list):
            out = self.S.get_zone_sensor_summary(zone_ids=['육묘장'])

        notes = ' '.join(out.get('_reading') or [])
        self.assertNotIn('같은 측정', notes)
        self.assertNotIn('more than one channel', notes, out)


if __name__ == '__main__':
    unittest.main()
