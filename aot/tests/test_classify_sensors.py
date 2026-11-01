# coding=utf-8
"""센서 위치 유형 분류(`classify_sensors`) — 리허설 센서 위치 규칙 PR1.

개발 DB 의 영양 육묘장·김제 3포장을 모형으로 한다:
  · 시설 설비에 매인 온습도 = facility(역할 미설정도 facility)
  · 시설 폴리곤 밖의 대지 직속 마커 = open_field
  · 기상대(설비 outdoor·측정값 추론)·예보 모델 = outdoor
  · 구역 마커 = open_field, 기상원 없는 대지는 "실외 기준 없음"
  · 마커·설비 없이 참조로만 온 센서 = unplaced, 하위 Input 은 부모를 따른다
읽기 전용이며 환경 제어(env_coordinator)는 이 모듈을 import 하지 않는다.
"""
import ast
import os
import unittest
from types import SimpleNamespace
from unittest import mock

from aot.databases.models import GeoShape
from aot.tests.test_place_membership import _Base, _point, _poly
from aot.tests.test_place_members_split import FAC_SHAPE, _input

SITE2 = [[200, 0], [200, 100], [300, 100], [300, 0], [200, 0]]


def _marker(uid, dev, x, y):
    GeoShape(unique_id='mk-' + uid, geo_id='m1', type='aot_device',
             device_id=dev, channel_id='0', feature=_point(x, y)).save()


class _ClsBase(_Base):

    def setUp(self):
        super(_ClsBase, self).setUp()
        from aot.databases.models import GeoBinding, GeoFacility
        GeoShape(unique_id='fac-shape', geo_id='m1', type='facility',
                 feature=_poly(FAC_SHAPE, '육묘장3')).save()
        GeoFacility(unique_id='fac-1', shape_uuid='fac-shape', geo_id='m1',
                    name='육묘장3',
                    fittings=[
                        {'id': 'f-in', 'kind': 'sensor', 'input_id': 'fs-in',
                         'sensor_role': 'indoor'},
                        {'id': 'f-unset', 'kind': 'sensor',
                         'input_id': 'fs-unset'},
                        {'id': 'f-out', 'kind': 'sensor', 'input_id': 'fs-out',
                         'sensor_role': 'outdoor'},
                    ]).save()
        for fid, dev in (('f-in', 'fs-in'), ('f-unset', 'fs-unset'),
                         ('f-out', 'fs-out')):
            GeoBinding(spatial_kind='fitting', spatial_id='fac-1:' + fid,
                       role='sensor', device_kind='input',
                       device_id=dev).save()
        for uid, name, *meas in (
                ('fs-in', '미러-온습도01', 'temperature'),
                ('fs-unset', '미러-온습도03', 'temperature'),
                ('fs-out', '설비 외기', 'temperature'),
                ('fs-geo', '시설 안 마커', 'temperature'),
                ('open-site', '미러-온습도07', 'temperature'),
                ('zone-s', '구역 센서', 'temperature'),
                ('lonely', '참조 센서', 'temperature')):
            _input(uid, name, *meas)
        # 시설 아래에 놓인 마커 — 부모 맵은 site/zone 만 기하로 감싸므로 시설
        # 소속은 parent_id 로 표현된다(사슬 판정이 부모 맵을 쓰는 이유).
        fac = GeoShape.query.filter(GeoShape.unique_id == 'fac-shape').first()
        _marker('fs-geo', 'fs-geo', 75, 75)
        mk = GeoShape.query.filter(GeoShape.unique_id == 'mk-fs-geo').first()
        mk.parent_id = fac.id
        mk.save()
        _marker('open-site', 'open-site', 50, 80)  # 대지 직속, 시설 밖
        _marker('zone-s', 'zone-s', 20, 30)      # 구역 3-1
        # 1포장: 기상원 없는 별도 대지
        GeoShape(unique_id='site2', geo_id='m1', type='site',
                 feature=_poly(SITE2, '1포장')).save()
        _input('s2-sensor', '1포장 센서', 'temperature')
        _marker('s2', 's2-sensor', 250, 50)

    def _cls(self, ids, place_uid=None):
        from aot.aot_flask.geo import shape_index
        from aot.aot_flask.geo.device_membership import classify_sensors
        shape_index.invalidate()       # 도형 색인은 프로세스 캐시다
        with mock.patch('aot.utils.inputs.model_input_drivers',
                        return_value=set()):
            return classify_sensors(ids, place_uid)


class TestClassifySensors(_ClsBase):

    def test_fitting_bound_is_facility_even_without_role(self):
        r = self._cls(['fs-in', 'fs-unset'], 'site')
        for d in ('fs-in', 'fs-unset'):
            self.assertEqual(r[d].kind, 'facility', d)
            self.assertEqual(r[d].source, 'fitting_role')
            self.assertEqual(r[d].facility_uid, 'fac-shape')

    def test_marker_under_facility_is_facility_by_geometry(self):
        p = self._cls(['fs-geo'])['fs-geo']
        self.assertEqual((p.kind, p.source), ('facility', 'geometry'))

    def test_site_marker_outside_facility_is_open_field(self):
        p = self._cls(['open-site'])['open-site']
        self.assertEqual((p.kind, p.source, p.place_uid, p.facility_uid),
                         ('open_field', 'geometry', 'site', None))

    def test_zone_marker_is_open_field_in_the_zone(self):
        p = self._cls(['zone-s'])['zone-s']
        self.assertEqual((p.kind, p.place_uid), ('open_field', 'zone-a'))

    def test_fitting_outdoor_role_is_outdoor(self):
        p = self._cls(['fs-out'])['fs-out']
        self.assertEqual((p.kind, p.source), ('outdoor', 'fitting_role'))
        self.assertIsNone(p.conflict)

    def test_inferred_and_bound_weather_station(self):
        from aot.databases.models import GeoBinding
        _input('wx', '기상대', 'temperature', 'radiation')
        _marker('wx', 'wx', 55, 85)
        p = self._cls(['wx'], 'zone-a')['wx']      # 구역으로 물어도 대지 기상대
        self.assertEqual((p.kind, p.source), ('outdoor', 'weather_inferred'))
        self.assertEqual(self._cls(['wx'])['wx'].kind, 'outdoor')
        _input('wx2', '지정 기상대', 'temperature')
        GeoBinding(spatial_kind='weather', spatial_id='site', role='weather',
                   device_kind='input', device_id='wx2').save()
        self.assertEqual(self._cls(['wx2'], 'site')['wx2'].source,
                         'weather_bound')

    def test_forecast_model_device_is_outdoor(self):
        from aot.databases.models import Input
        from aot.aot_flask.geo import shape_index
        from aot.aot_flask.geo.device_membership import classify_sensors
        shape_index.invalidate()
        Input(unique_id='fc', name='SIM 기상대', device='OPEN_METEO').save()
        with mock.patch('aot.utils.inputs.model_input_drivers',
                        return_value={'OPEN_METEO'}):
            p = classify_sensors(['fc'], 'site')['fc']
        self.assertEqual(p.kind, 'outdoor')

    def test_site_without_weather_has_no_outdoor_reference(self):
        r = self._cls(['s2-sensor'], 'site2')
        self.assertEqual(r['s2-sensor'].kind, 'open_field')
        # 다른 대지(3포장)의 기상대를 빌리지 않는다.
        _input('wx', '기상대', 'temperature', 'radiation')
        _marker('wx', 'wx', 55, 85)
        self.assertEqual(self._cls(['s2-sensor', 'wx'])['s2-sensor'].kind,
                         'open_field')

    def test_unplaced_and_child_follows_parent(self):
        from aot.databases.models import Input
        self.assertEqual(self._cls(['lonely'], 'site')['lonely'].kind,
                         'unplaced')
        Input(unique_id='child', name='하위 채널', device='X',
              parent_device_id='fs-in').save()
        Input(unique_id='orphan', name='고아', device='X',
              parent_device_id='lonely').save()
        r = self._cls(['child', 'orphan'])
        self.assertEqual(r['child'].kind, 'facility')
        self.assertEqual(r['orphan'].kind, 'unplaced')

    def test_conflict_when_fitting_role_disagrees(self):
        """설비는 실내(시설)로 두었는데 기상원으로 걸리면 경고만 낸다."""
        from aot.databases.models import GeoBinding
        GeoBinding(spatial_kind='weather', spatial_id='site', role='weather',
                   device_kind='input', device_id='fs-in').save()
        p = self._cls(['fs-in'], 'site')['fs-in']
        self.assertEqual(p.kind, 'outdoor')
        self.assertIn('fitting_role=facility', p.conflict)

    def test_split_contract_is_unchanged(self):
        from aot.aot_flask.geo.device_membership import place_members_split
        _input('wx', '기상대', 'temperature', 'radiation')
        _marker('wx', 'wx', 55, 85)
        from aot.aot_flask.geo import shape_index
        shape_index.invalidate()
        sp = place_members_split('site')
        self.assertEqual(sp['outdoor'], {'wx'})
        self.assertEqual(sp['source'], 'inferred')
        self.assertEqual(set(sp), {'indoor', 'outdoor', 'source',
                                   'weather_place', 'members'})

    def test_summary_items_carry_placement(self):
        from datetime import datetime, timezone
        from aot.tools.aot_data_tool_service import AoTDataToolService as S
        from aot.aot_flask.geo import shape_index
        shape_index.invalidate()
        now = datetime.now(timezone.utc)
        with mock.patch('aot.utils.influx.read_influxdb_list',
                        side_effect=lambda *a, **k: [(now, 20.0)]):
            out = S.get_zone_sensor_summary(zone_ids=['site'], detail=True)
        items = {d['device_id']: d for z in out['zones']
                 for d in z['sensors']}
        self.assertEqual(items['fs-in']['placement'], 'facility')
        self.assertEqual(items['fs-in']['placement_source'], 'fitting_role')
        self.assertEqual(items['open-site']['placement'], 'open_field')
        self.assertEqual(items['fs-in']['location'], 'indoor')   # 기존 키 불변


class TestChannelMedium(unittest.TestCase):

    def _dm(self, **kw):
        base = dict(name='', measurement='temperature', measurement_type=None)
        base.update(kw)
        return SimpleNamespace(unique_id='x', conversion_id=None, unit='C',
                               channel=0, **base)

    def test_soil_by_name_or_measurement(self):
        from aot.aot_flask.geo.device_membership import channel_medium
        self.assertEqual(channel_medium(self._dm(name='토양 온도')), 'soil')
        self.assertEqual(channel_medium(self._dm(name='Soil temp')), 'soil')
        self.assertEqual(channel_medium(self._dm(name='地温')), 'soil')
        self.assertEqual(channel_medium(
            self._dm(measurement='volumetric_water_content')), 'soil')
        self.assertEqual(channel_medium(self._dm(name='대기 온도')), 'air')


class TestEnvIsolation(unittest.TestCase):
    """환경제어 회귀 가드: 새 분류가 제어 입력으로 새어 들어가지 않는다."""

    def test_env_control_does_not_import_placement(self):
        root = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
        paths = [os.path.join(root, 'functions', 'custom_functions',
                              'env_coordinator.py')]
        for base in ('env_coordinator_impl',):
            d = os.path.join(root, 'functions', 'custom_functions', base)
            paths += [os.path.join(d, f) for f in os.listdir(d)
                      if f.endswith('.py')]
        d = os.path.join(root, 'functions', 'utils', 'env_control')
        for dp, _, fs in os.walk(d):
            if os.sep + 'tests' in dp:
                continue
            paths += [os.path.join(dp, f) for f in fs if f.endswith('.py')]
        self.assertGreater(len(paths), 3)
        bad = []
        for p in paths:
            tree = ast.parse(open(p, encoding='utf-8').read())
            for n in ast.walk(tree):
                mods = []
                if isinstance(n, ast.ImportFrom):
                    mods = [n.module or ''] + [a.name for a in n.names]
                elif isinstance(n, ast.Import):
                    mods = [a.name for a in n.names]
                if any('device_membership' in m or m == 'classify_sensors'
                       for m in mods):
                    bad.append(os.path.relpath(p, root))
        self.assertEqual(bad, [])


if __name__ == '__main__':
    unittest.main()
