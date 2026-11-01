# coding=utf-8
"""날씨 후보 선택(_pick_weather_input)의 제외·정렬·사유 표기 (E5 후속).

김제 1포장 get_place_overview 날씨 요약이 비었던 원인: 꺼진 Open-Meteo 가
'근처 날씨 후보' 로 뽑혔지만 값이 없었다. 후보에서 꺼진·상태 비정상·오래된
장치를 빼고, 실측을 모델보다 앞세우고, 이유를 응답에 싣는다.
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

MODEL_DRIVER = 'OPEN_METEO_FORECAST'
OBS_DRIVER = 'KMA_weather_500'


def _inp(uid, name, device=OBS_DRIVER, active=True, status='ok', period=600,
         max_age=None):
    i = MagicMock()
    i.unique_id, i.name, i.device = uid, name, device
    i.period, i.max_age_s = period, max_age
    i.is_activated = active
    i.device_status = status
    return i


def _shape():
    sh = MagicMock()
    sh.unique_id, sh.geo_id = 'shape-1', 'map-1'
    sh.feature = {'type': 'Feature', 'properties': {'name': '1포장'},
                  'geometry': {'type': 'Point', 'coordinates': [126.88, 35.86]}}
    return sh


HERE = (35.86, 126.88)


class TestWeatherPickFilter(unittest.TestCase):

    def _pick(self, cands, coords=None, site=(), site_kind='inferred',
              placed=(), ages=None):
        """ages: {id: 초 또는 None(값 없음) 또는 'err'(조회 실패)}"""
        from aot.utils import device_tz
        coords = dict({'shape-1': HERE}, **(coords or {}))
        ages = ages or {}

        def _age(uid, window_s=None, max_channels=None):
            a = ages.get(uid, 60)
            if a == 'err':
                raise RuntimeError('influx down')
            return a, None, None

        info = {}
        with patch.object(S, '_weather_inputs', return_value=cands), \
             patch('aot.aot_flask.geo.device_membership.place_members',
                   return_value=set(placed)), \
             patch('aot.aot_flask.geo.device_membership.site_for_geometry',
                   return_value=None), \
             patch('aot.aot_flask.geo.device_membership.weather_device_ids',
                   return_value=(list(site), site_kind)), \
             patch('aot.utils.inputs.model_input_drivers',
                   return_value={MODEL_DRIVER}), \
             patch.object(S, '_last_seen_seconds', side_effect=_age), \
             patch.object(device_tz, 'resolve_location_coords',
                          side_effect=lambda i: coords.get(i, (None, None))):
            chosen, scope, others = S._pick_weather_input(
                _shape(), '1포장', info=info)
        return chosen, scope, others, info

    def test_inactive_device_is_skipped_and_named(self):
        om = _inp('om', 'Open-Meteo', MODEL_DRIVER, active=False)
        kma = _inp('kma', '기상청')
        c, scope, _, info = self._pick(
            {'om': om, 'kma': kma},
            {'om': (35.87, 126.88), 'kma': (35.9, 126.9)})
        self.assertEqual('kma', c.unique_id)
        self.assertEqual([{'name': 'Open-Meteo', 'reason': 'inactive'}],
                         info['skipped'])
        self.assertEqual('nearest_observed', info['picked_because'])

    def test_stale_device_is_skipped(self):
        a = _inp('a', '낡은 기상대')
        b = _inp('b', '먼 기상대')
        c, _, _, info = self._pick(
            {'a': a, 'b': b}, {'a': (35.861, 126.88), 'b': (35.9, 126.88)},
            ages={'a': 99999})
        self.assertEqual('b', c.unique_id)
        self.assertEqual('stale', info['skipped'][0]['reason'])

    def test_no_value_in_window_counts_as_stale(self):
        a = _inp('a', '무소식')
        c, _, _, info = self._pick({'a': a}, {'a': (35.861, 126.88)},
                                   ages={'a': None})
        self.assertIsNone(c)
        self.assertEqual('stale', info['skipped'][0]['reason'])

    def test_freshness_lookup_failure_does_not_drop_the_candidate(self):
        a = _inp('a', '기상대')
        c, _, _, info = self._pick({'a': a}, {'a': (35.861, 126.88)},
                                   ages={'a': 'err'})
        self.assertEqual('a', c.unique_id)
        self.assertNotIn('skipped', info)

    def test_device_own_max_age_wins(self):
        a = _inp('a', '느린 노드', period=60, max_age=7200)
        c, _, _, _ = self._pick({'a': a}, {'a': (35.861, 126.88)},
                                ages={'a': 5000})
        self.assertEqual('a', c.unique_id)     # 주기 파생이면 오래됨, 장치값이 이김

    def test_device_status_device_is_skipped(self):
        for st in ('repair', 'removed', 'maintenance'):
            a = _inp('a', '고장', status=st)
            b = _inp('b', '정상')
            c, _, _, info = self._pick(
                {'a': a, 'b': b}, {'a': (35.861, 126.88), 'b': (35.9, 126.88)})
            self.assertEqual('b', c.unique_id, st)
            self.assertEqual('device_status', info['skipped'][0]['reason'])

    def test_observed_beats_model_even_when_model_is_closer(self):
        sim = _inp('sim', 'SIM 기상대', MODEL_DRIVER)
        kma = _inp('kma', '기상청')
        c, scope, _, info = self._pick(
            {'sim': sim, 'kma': kma},
            {'sim': (35.8601, 126.88), 'kma': (35.9, 126.9)})
        self.assertEqual('kma', c.unique_id)
        self.assertEqual('nearest_observed', info['picked_because'])

    def test_observed_in_zone_label(self):
        kma = _inp('kma', '기상청')
        c, scope, _, info = self._pick({'kma': kma}, placed=['kma'])
        self.assertEqual(('kma', 'in_zone'), (c.unique_id, scope))
        self.assertEqual('observed_in_zone', info['picked_because'])

    def test_same_class_keeps_nearest_first(self):
        a = _inp('a', 'A')
        b = _inp('b', 'B')
        c, _, others, _ = self._pick(
            {'a': a, 'b': b}, {'a': (35.95, 126.88), 'b': (35.87, 126.88)})
        self.assertEqual('b', c.unique_id)
        self.assertEqual(['a'], [o['device_id'] for o in others])

    def test_model_only(self):
        sim = _inp('sim', 'SIM 기상대', MODEL_DRIVER)
        c, _, _, info = self._pick({'sim': sim}, {'sim': (35.8601, 126.88)})
        self.assertEqual('sim', c.unique_id)
        self.assertEqual('model_only', info['picked_because'])

    def test_human_bound_site_source_stays_first(self):
        sim = _inp('sim', 'SIM 기상대', MODEL_DRIVER)
        kma = _inp('kma', '기상청')
        c, scope, _, info = self._pick(
            {'sim': sim, 'kma': kma},
            {'sim': (35.86, 126.88), 'kma': (35.9, 126.9)},
            site=['sim'], site_kind='bound')
        self.assertEqual(('sim', 'site'), (c.unique_id, scope))
        self.assertEqual('bound_site', info['picked_because'])

    def test_no_candidate_left(self):
        om = _inp('om', 'Open-Meteo', MODEL_DRIVER, active=False)
        c, scope, others, info = self._pick({'om': om}, {'om': (35.87, 126.88)})
        self.assertEqual((None, None, []), (c, scope, others))
        self.assertNotIn('picked_because', info)
        self.assertEqual('inactive', info['skipped'][0]['reason'])

    def test_skipped_capped_at_three_with_more(self):
        cands = {'o%d' % n: _inp('o%d' % n, 'off%d' % n, active=False)
                 for n in range(5)}
        coords = {k: (35.861, 126.88) for k in cands}
        _, _, _, info = self._pick(cands, coords)
        self.assertEqual(3, len(info['skipped']))
        self.assertEqual(2, info['skipped_more'])

    def test_skipped_absent_when_nothing_excluded(self):
        kma = _inp('kma', '기상청')
        _, _, _, info = self._pick({'kma': kma}, {'kma': (35.861, 126.88)})
        self.assertNotIn('skipped', info)
        self.assertNotIn('skipped_more', info)


class TestOverviewNoneMarker(unittest.TestCase):

    def test_source_none_when_everything_skipped(self):
        w = {'weather_source': 'nearby_sensor',
             'data': [{'device_name': '토양', 'measurement': 'temperature',
                       'readings': [{'t': 't', 'v': 1}]}],
             'weather_pick': {'skipped': [{'name': 'Open-Meteo',
                                           'reason': 'inactive'}]}}
        with patch.object(S, 'get_weather_tool', return_value=w):
            r = S._overview_weather(MagicMock())
        self.assertEqual('no_active_fresh_weather_device', r['source_none'])
        self.assertEqual('inactive', r['skipped'][0]['reason'])
        self.assertNotIn('temperature', r)

    def test_pick_info_is_copied_into_source(self):
        w = {'weather_source': 'weather_station',
             'weather_device': {'name': '기상청', 'device_id': 'k'},
             'weather_device_scope': 'nearby',
             'data': [{'device_name': '기상청', 'measurement': 'temperature',
                       'readings': [{'t': 't', 'v': 20.0}]}],
             'weather_pick': {'picked_because': 'nearest_observed',
                              'skipped': [{'name': 'Open-Meteo',
                                           'reason': 'inactive'}]}}
        with patch.object(S, 'get_weather_tool', return_value=w), \
             patch('aot.utils.device_tz.resolve_location_coords',
                   return_value=(None, None)):
            r = S._overview_weather(MagicMock())
        self.assertEqual('nearest_observed', r['source']['picked_because'])
        self.assertEqual('Open-Meteo', r['source']['skipped'][0]['name'])
        self.assertEqual(20.0, r['temperature'])


if __name__ == '__main__':
    unittest.main()
