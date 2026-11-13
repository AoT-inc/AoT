# coding=utf-8
"""도구가 고른 날씨 장치가 시설 제어의 실외 정본과 다를 때만 control_outdoor 를 낸다.

김제: 제어는 기상청 KMA_weather_500 실측, 도구는 대지에 지정된 모델 기상원
'SIM 김제 기상대'. 값이 1~3°C 달라 '왜 창을 닫았나' 설명이 어긋나 보였다.
DB·Influx 없이 경계를 모두 패치한다.
"""
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.abspath(
    os.path.join(os.path.dirname(__file__), os.path.pardir, os.path.pardir)))
os.environ.setdefault("ALEMBIC_RUNNING", "1")

from aot.tools.aot_data_tool_service import AoTDataToolService as S

OUT = [{'input_uuid': 'kma', 'input_name': '기상청 KMA', 'name': 'f1',
        'sensor_priority': 'primary'}]
WEATHER = {'data': [{'device_name': 'SIM', 'measurement': 'temperature',
                     'readings': [{'t': '2026-10-13T10:00', 'v': 24.0}]}]}


# 현실 방향: 대지 ⊃ 시설. parent 맵으로 within(자식, 조상) 을 흉내 낸다.
PARENT = {'fac-shape-1': 'site-3', 'fac-shape-2': 'site-3', 'zone-31': 'site-3',
          'plot-in': 'fac-shape-1', 'site-3': None, 'site-1': None}


class _Idx(object):
    def within(self, a, b):
        while a is not None:
            if a == b:
                return True
            a = PARENT.get(a)
        return False


def _fac(uid, name, shape):
    f = MagicMock()
    f.unique_id, f.name, f.shape_uuid = uid, name, shape
    return f


def _run(place='site-3', chosen_id='sim', facs=None, integ=None, chans=None,
         weather=WEATHER, ro=None):
    sh = MagicMock()
    sh.unique_id = place
    if facs is None:
        facs = [_fac('fac-1', '육묘장3', 'fac-shape-1')]
    integ = integ or {'fac-1': OUT, 'fac-2': OUT}
    if chans is None:
        chans = [{'key': 'T', 'value': 21.34, 'unit': '°C',
                  'ts': '2026-10-13T10:00:00Z', 'valid': True}]
    ro = ro or (lambda outs: {'T_ext': 21.34, 'backup_keys': []})
    with patch('aot.databases.models.GeoFacility') as GF, \
         patch('aot.space.facility_sensors.read_outdoor_sensors',
               side_effect=ro), \
         patch('aot.space.device_membership.PlaceIndex',
               return_value=_Idx()), \
         patch('aot.space.facility_integration.get_facility_integration',
               side_effect=lambda u: ({'sensors_outdoor': integ.get(u, [])}, None)), \
         patch('aot.space.facility_sensors.read_fitting_sensors',
               return_value=[{'channels': chans}]):
        GF.query.all.return_value = facs
        return S._control_outdoor(sh, chosen_id, weather)


def _o(dev, name):
    return [{'input_uuid': dev, 'input_name': name, 'name': 'f',
             'sensor_priority': 'primary'}]


class TestControlOutdoor(unittest.TestCase):

    def test_same_device_has_no_field(self):
        self.assertIsNone(_run(chosen_id='kma'))

    def test_site_containing_facility_reports_control_value(self):
        r = _run()
        self.assertEqual('기상청 KMA', r['name'])
        self.assertEqual(21.3, r['value'])
        self.assertEqual('°C', r['unit'])
        self.assertEqual(2.7, r['differs_by'])
        self.assertNotIn('control_outdoor_more', r)

    def test_place_inside_facility_still_works(self):
        self.assertEqual('기상청 KMA', _run(place='plot-in')['name'])

    def test_no_recent_value(self):
        r = _run(ro=lambda o: {'T_ext': None, 'backup_keys': []})
        self.assertEqual({'name': '기상청 KMA', 'rank': 'main', 'value': None,
                          'note': 'no_recent_value'}, r)

    def test_zone_and_facilityless_site_omitted(self):
        self.assertIsNone(_run(place='zone-31'))
        self.assertIsNone(_run(place='site-1'))

    def test_facility_without_outdoor_fitting_skipped(self):
        self.assertIsNone(_run(integ={'fac-1': []}))

    def test_two_facilities_same_canon_single(self):
        facs = [_fac('fac-1', 'A', 'fac-shape-1'), _fac('fac-2', 'B', 'fac-shape-2')]
        r = _run(facs=facs)
        self.assertNotIn('control_outdoor_more', r)
        self.assertIsNone(_run(facs=facs, chosen_id='kma'))

    def test_two_facilities_different_canon(self):
        facs = [_fac('fac-2', 'B', 'fac-shape-2'), _fac('fac-1', 'A', 'fac-shape-1')]
        integ = {'fac-1': _o('kma', '기상청'), 'fac-2': _o('eco', '에코윗')}
        r = _run(facs=facs, integ=integ)
        self.assertEqual(('기상청', 'A'), (r['name'], r['facility']))
        self.assertEqual([{'facility': 'B', 'name': '에코윗', 'rank': 'main'}],
                         r['control_outdoor_more'])
        self.assertIsNone(_run(facs=facs, integ=integ, chosen_id='eco'))

    def test_main_fresh_wins_over_backup(self):
        integ = {'fac-1': _o('kma', '기상청') + [
            {'input_uuid': 'om', 'input_name': 'OM', 'name': 'g',
             'sensor_priority': 'backup'}]}
        r = _run(integ=integ)
        self.assertEqual(('기상청', 'main'), (r['name'], r['rank']))
        self.assertIsNone(_run(integ=integ, chosen_id='kma'))
        # 백업 장치를 고른 도구는 정본(메인)과 다르다.
        self.assertEqual('기상청', _run(integ=integ, chosen_id='om')['name'])

    def test_all_main_down_uses_backup(self):
        integ = {'fac-1': _o('kma', '기상청') + [
            {'input_uuid': 'om', 'input_name': 'OM', 'name': 'g',
             'sensor_priority': 'backup'}]}
        r = _run(integ=integ, chosen_id='sim',
                 ro=lambda o: {'T_ext': 19.5, 'backup_keys': ['T']})
        self.assertEqual(('OM', 'backup', 19.5), (r['name'], r['rank'], r['value']))
        self.assertIsNone(_run(integ=integ, chosen_id='om',
                               ro=lambda o: {'T_ext': 19.5, 'backup_keys': ['T']}))

    def test_more_sorted_main_before_backup(self):
        facs = [_fac('fac-1', 'A', 'fac-shape-1'), _fac('fac-2', 'B', 'fac-shape-2')]
        integ = {'fac-1': _o('kma', '기상청'), 'fac-2': _o('eco', '에코윗')}

        def ro(outs):   # A 시설은 메인이 끊겨 백업 값, B 는 메인
            return ({'T_ext': 19.0, 'backup_keys': ['T']}
                    if outs[0]['input_uuid'] == 'kma'
                    else {'T_ext': 22.0, 'backup_keys': []})
        r = _run(facs=facs, integ=integ, ro=ro)
        self.assertEqual(('에코윗', 'main', 'B'), (r['name'], r['rank'], r['facility']))
        self.assertEqual([{'facility': 'A', 'name': '기상청', 'rank': 'backup'}],
                         r['control_outdoor_more'])

    def test_overview_forwards_field(self):
        shape = MagicMock()
        w = {'weather_source': 'weather_station',
             'weather_device': {'name': 'SIM', 'device_id': 'sim'},
             'data': [{'device_name': 'SIM', 'measurement': 'temperature',
                       'readings': [{'t': 't', 'v': 24.0}]}],
             'control_outdoor': {'name': '기상청 KMA', 'value': 21.3}}
        with patch.object(S, 'get_weather_tool', return_value=w), \
             patch.object(S, '_overview_weather_source',
                          return_value={'name': 'SIM'}):
            out = S._overview_weather(shape)
        self.assertEqual({'name': '기상청 KMA', 'value': 21.3},
                         out['source']['control_outdoor'])
        w.pop('control_outdoor')
        with patch.object(S, 'get_weather_tool', return_value=w), \
             patch.object(S, '_overview_weather_source',
                          return_value={'name': 'SIM'}):
            out = S._overview_weather(shape)
        self.assertNotIn('control_outdoor', out['source'])


if __name__ == '__main__':
    unittest.main()
