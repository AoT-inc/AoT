# coding=utf-8
"""E4: get_anomalies 가시성 — comm_offline 목록, 위치 없음 표기, degraded 사유."""
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.abspath(os.path.join(
    os.path.dirname(__file__), os.path.pardir, os.path.pardir)))
os.environ.setdefault("ALEMBIC_RUNNING", "1")

from aot.tools.aot_data_tool_service import AoTDataToolService as S
from aot.tools.data_tools import measurement as M


def _inp(uid, name, period=600):
    i = MagicMock()
    i.unique_id, i.name, i.device, i.period = uid, name, 'th1x', period
    i.is_activated = True
    return i


class TestAnomaliesVisibility(unittest.TestCase):
    def _anomalies(self, offline):
        prov = MagicMock(return_value={
            'metrics': {'total_devices': 3, 'comm_offline_devices': len(offline)},
            'comm_offline_list': offline, 'timestamp': None})
        with patch('aot.tools.providers.get', return_value=prov), \
             patch.object(S, '_silent_devices_in_scope', return_value=None), \
             patch('aot.aot_flask.geo.device_membership.PlaceIndex') as pi:
            pi.return_value.device_paths.return_value = {'a': ['농장/육묘장']}
            return S.get_anomalies()

    def test_offline_devices_are_named_and_unplaced_is_stated(self):
        out = self._anomalies([{'device_id': 'a', 'name': 'A'},
                               {'device_id': 'p', 'name': '압력_1'}])
        rows = {r['name']: r for r in out['comm_offline_list']}
        self.assertEqual('p', rows['압력_1']['device_id'])
        self.assertIsNone(rows['압력_1']['place'])
        self.assertIn('not placed', rows['압력_1']['place_note'])
        self.assertNotIn('place_note', rows['A'])
        self.assertIn('silent_devices', out['metrics_definitions'])

    def test_freshness_marks_unplaced_and_explains_counting(self):
        devs = [_inp('p', '압력_1')]
        inp = MagicMock()
        inp.query.all.return_value = devs
        with patch.object(M, 'Input', inp), \
             patch.object(S, '_last_seen_seconds', return_value=(None, None, None)), \
             patch('aot.aot_flask.geo.device_membership.PlaceIndex') as pi:
            pi.return_value.device_paths.return_value = {}
            out = S.get_device_freshness()
        self.assertIn('not placed', out['no_data_devices'][0]['place_note'])
        self.assertIn('stale_count', out['counting'])


class TestDegradedReasons(unittest.TestCase):
    def test_reasons_name_axis_and_kinds(self):
        r = S._degraded_reasons({'modes': ['degraded'],
                                 'natural_axes': ['CO2_up'],
                                 'unmeasured': ['RH']})
        self.assertEqual('CO2_up', r[0]['axis'])
        self.assertIn('co2_injector', r[0]['reason'])
        self.assertEqual(['RH'], r[1]['variables'])

    def test_no_reasons_without_degraded_mode(self):
        self.assertIsNone(S._degraded_reasons({'modes': ['natural']}))

    def test_old_record_without_axes_still_explains(self):
        r = S._degraded_reasons({'modes': ['degraded']})
        self.assertIn('predates', r[0]['reason'])

    def test_overview_control_carries_reasons(self):
        cs = {'coordinators': [{'facility_place_id': 's1', 'facility_name': '육묘장',
                                'latest_cycle_summary': {
                                    'modes': ['degraded'],
                                    'degraded_reasons': [{'axis': 'T_up'}]}}]}
        idx = MagicMock()
        shape = MagicMock(unique_id='s1')
        with patch.object(S, 'get_control_state', return_value=cs):
            rows = S._overview_control(shape, idx, True)
        self.assertEqual('T_up', rows[0]['degraded_reasons'][0]['axis'])


DAY = 86400


def _verdict(silent, total, paths=None, ctrl=()):
    ids = ['s%d' % i for i in range(total)]
    rows = [(ids[i], 'n%d' % i, age) for i, age in enumerate(silent)]
    return S._silent_verdict(rows, ids, paths or {}, set(ctrl))


class TestSilentLevel(unittest.TestCase):
    def test_quarter_of_active_is_warning(self):
        v = _verdict([DAY, DAY], 8)           # 2/8 = 25%
        self.assertEqual('warning', v['silent_level'])
        self.assertIsNone(v.get('severity_hint'))

    def test_below_quarter_is_info(self):
        self.assertEqual('info', _verdict([DAY, DAY], 9)['silent_level'])

    def test_half_is_warning_with_high_hint(self):
        v = _verdict([DAY, DAY], 4)
        self.assertEqual(('warning', 'high'),
                         (v['silent_level'], v['severity_hint']))

    def test_single_silent_is_not_warning(self):
        self.assertEqual('info', _verdict([DAY], 2)['silent_level'])

    def test_dormant_split_and_excluded_from_ratio(self):
        v = _verdict([40 * DAY, None, DAY], 5)
        self.assertEqual(2, v['dormant_count'])
        self.assertEqual(1, v['recent_count'])
        self.assertEqual(3, len(v['dormant']) + 1)
        self.assertEqual(round(1 / 3, 3), v['ratio'])
        self.assertEqual('info', v['silent_level'])

    def test_dormant_only_is_none(self):
        v = _verdict([40 * DAY, None], 6)
        self.assertEqual('none', v['silent_level'])
        self.assertEqual(2, v['dormant_count'])

    def test_whole_zone_silent_is_warning(self):
        paths = {'s0': '농장/A', 's1': '농장/A', 's2': '농장/B', 's3': '농장/B',
                 's4': '농장/B', 's5': '농장/B', 's6': '농장/B', 's7': '농장/B',
                 's8': '농장/B', 's9': '농장/B', 's10': '농장/B', 's11': '농장/B'}
        v = _verdict([DAY, DAY], 12, paths)   # 2/12 < 25% 이지만 A 구역 전멸
        self.assertEqual('warning', v['silent_level'])
        self.assertIn('whole_place_silent', v['warning_reasons'])
        self.assertEqual('농장/A', v['by_place'][0]['place'])

    def test_one_control_input_silent_is_warning(self):
        v = _verdict([DAY], 20, ctrl=['s0'])
        self.assertEqual('warning', v['silent_level'])
        self.assertEqual('s0', v['control_inputs_silent'][0]['device_id'])

    def test_nothing_silent_is_none(self):
        self.assertIsNone(_verdict([], 5))


class TestSilentLevelInResponses(unittest.TestCase):
    def _run(self, silent, alert_level='none'):
        prov = MagicMock(return_value={'metrics': {}, 'alert_level': alert_level,
                                       'timestamp': None})
        with patch('aot.tools.providers.get', return_value=prov), \
             patch.object(S, '_silent_devices_in_scope', return_value=silent):
            return S.get_anomalies()

    def test_alert_level_unchanged_by_silence(self):
        v = _verdict([DAY, DAY], 4)
        out = self._run(v)
        self.assertEqual('none', out['alert_level'])
        self.assertFalse(out['anomaly_detected'])
        self.assertEqual('warning', out['silent_level'])
        self.assertEqual('high', out['severity_hint'])
        text = ' '.join(out['_reading'])
        self.assertIn('MUST', text)
        self.assertIn('ai_excluded', text)

    def test_silent_level_none_without_silence(self):
        self.assertEqual('none', self._run(None)['silent_level'])

    def test_response_size_stays_small(self):
        import json
        v = _verdict([DAY] * 60 + [None] * 60, 200)
        self.assertLess(len(json.dumps(self._run(v), ensure_ascii=False)), 9000)

    def _tree(self, a):
        shape = MagicMock(unique_id='z1', type='zone')
        with patch.object(S, 'get_anomalies', return_value=a):
            return S._overview_alert(shape)

    def test_spatial_tree_shows_silent_warning_only(self):
        w = self._tree({'alert_level': 'none', 'silent_level': 'warning',
                        'silent_devices': {'recent_count': 3, 'active_total': 8,
                                           'ratio': 0.375}})
        self.assertEqual('warning', w['silent_level'])
        self.assertNotIn('level', w)
        self.assertIsNone(self._tree({'alert_level': 'none',
                                      'silent_level': 'info'}))
        both = self._tree({'alert_level': 'high', 'anomalies': [{'type': 'x'}],
                           'silent_level': 'warning'})
        self.assertEqual('high', both['level'])
