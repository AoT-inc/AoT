# coding=utf-8
"""구획 그래프 2단계 서버 조립 — 장치 레인(`build_lanes`)과 시나리오 목록(`scenario_items`).

규칙: 레인 단위는 효과 채널(합친 값 `dev=all`)이고 장치별은 `devices` 로 펼친다. 과거 근거 4값은 나쁜 쪽이 뒤로 가고 앞날은 `plan`.
모델이 없는 장치는 계열이 없어도 레인(또는 장치 줄)을 남겨 '미반영' 을 말한다. 시설과 노지는 같은 함수를 쓴다.
"""
import types
import unittest

from aot.utils import twin_chart as C

T = 1793000000.0


def _row(effect, basis, dev, pts):
    return [(t, v, {'effect': effect, 'basis': basis, 'dev': dev, 'scenario': 'x'}) for t, v in pts]


def _dev(i, kind=None, channel=None, status='unknown', applied=True, excluded=False):
    return {'id': i, 'name': 'name-' + i, 'kind': kind, 'channel': channel, 'status': status, 'applied': applied,
            'excluded': excluded}


class LaneStatus(unittest.TestCase):
    def test_all_modeled(self):
        self.assertEqual(C.lane_status(['modeled', 'modeled']), 'modeled')

    def test_mixed_is_partial(self):
        self.assertEqual(C.lane_status(['modeled', 'unmodeled']), 'partial')
        self.assertEqual(C.lane_status(['partial', 'unknown']), 'partial')

    def test_none_modeled(self):
        self.assertEqual(C.lane_status(['unmodeled', 'unknown']), 'unmodeled')
        self.assertEqual(C.lane_status(['unknown']), 'unknown')

    def test_no_devices_is_unknown_not_modeled(self):
        self.assertIsNone(C.lane_status([]))


class Facility(unittest.TestCase):
    """시설 — 켜진 시설이 없어 실데이터로는 못 보는 길이라 여기서 확인한다."""

    def setUp(self):
        self.base = (_row('vent', 'actual', 'all', [(T, 40.0), (T + 3600, 60.0)]) +
                     _row('vent', 'command', 'all', [(T + 7200, 55.0)]) +
                     _row('vent', 'plan', 'all', [(T + 10800, 50.0)]) +
                     _row('vent', 'actual', 'v1', [(T, 30.0)]) + _row('vent', 'actual', 'v2', [(T, 50.0)]) +
                     _row('heat', 'duty_log', 'all', [(T, 10.0)]))
        self.scn = _row('vent', 'plan', 'all', [(T + 10800, 20.0)]) + _row('vent', 'plan', 'v1', [(T + 10800, 20.0)])
        self.roster = [_dev('v1', 'window', 'vent', 'modeled'), _dev('v2', 'window', 'vent', 'modeled'),
                       _dev('h1', 'heater', 'heat', 'modeled'), _dev('f1', 'fogger', 'fog', 'unmodeled'),
                       _dev('x1', None, None, 'unknown')]

    def lane(self, lanes, effect):
        return [x for x in lanes if x['effect'] == effect][0]

    def test_lane_is_effect_channel_with_merged_values(self):
        lanes = C.build_lanes('facility', self.base, None, self.roster)
        vent = self.lane(lanes, 'vent')
        self.assertEqual(vent['unit'], '%')
        self.assertEqual(vent['agg'], 'mean')
        self.assertEqual([p['basis'] for p in vent['past']], ['actual', 'command'])        # 근거 4값은 좋은 쪽부터
        self.assertEqual(vent['past'][0]['points'], [[T, 40.0], [T + 3600, 60.0]])
        self.assertEqual(vent['base_plan'], [[T + 10800, 50.0]])
        self.assertIsNone(vent['scn_plan'])
        self.assertEqual(vent['status'], 'modeled')

    def test_devices_expand_with_their_own_series(self):
        vent = self.lane(C.build_lanes('facility', self.base, self.scn, self.roster), 'vent')
        self.assertEqual([d['id'] for d in vent['devices']], ['v1', 'v2'])
        self.assertEqual(vent['devices'][0]['past'][0]['points'], [[T, 30.0]])
        self.assertEqual(vent['devices'][0]['scn_plan'], [[T + 10800, 20.0]])
        self.assertEqual(vent['devices'][1]['scn_plan'], [])        # 가정이 안 닿은 장치는 비어 있다(합친 값만 움직였다)
        self.assertEqual(vent['scn_plan'], [[T + 10800, 20.0]])
        self.assertEqual(vent['device_count'], 2)

    def test_unmodeled_device_stays_visible_without_series(self):
        lanes = C.build_lanes('facility', self.base, None, self.roster)
        fog = self.lane(lanes, 'fog')
        self.assertEqual(fog['status'], 'unmodeled')              # 계열이 없어도 레인을 남긴다 — 조용히 빼지 않는다
        self.assertEqual(fog['past'], [])
        self.assertEqual(fog['devices'][0]['name'], 'name-f1')

    def test_unknown_kind_devices_gather_in_effectless_lane(self):
        lanes = C.build_lanes('facility', self.base, None, self.roster)
        none = self.lane(lanes, None)
        self.assertEqual(none['status'], 'unknown')
        self.assertEqual([d['id'] for d in none['devices']], ['x1'])

    def test_partial_when_some_devices_modeled(self):
        roster = [_dev('v1', 'window', 'vent', 'modeled'), _dev('v2', 'window', 'vent', 'unmodeled')]
        self.assertEqual(self.lane(C.build_lanes('facility', self.base, None, roster), 'vent')['status'], 'partial')

    def test_excluded_devices_are_left_out(self):
        roster = [_dev('v1', 'window', 'vent', 'modeled'), _dev('v2', 'window', 'vent', 'unmodeled', excluded=True)]
        vent = self.lane(C.build_lanes('facility', self.base, None, roster), 'vent')
        self.assertEqual(vent['status'], 'modeled')
        self.assertEqual(vent['device_count'], 1)


class Field(unittest.TestCase):
    def test_irrigation_is_millimetres_summed_per_day(self):
        scn = _row('irrigation_mm', 'plan', 'all', [(T, 6.667), (T + 3600, 6.667)])
        lane = C.build_lanes('field', [], scn, [_dev('o1', None, None, 'unknown')])[0]
        self.assertEqual((lane['effect'], lane['unit'], lane['agg']), ('irrigation_mm', 'mm', 'sum'))
        self.assertEqual(lane['scn_plan'], [[T, 6.667], [T + 3600, 6.667]])
        self.assertEqual(lane['base_plan'], [])        # 노지 기본 예측은 관수를 모른다(E3 전)

    def test_field_outputs_are_unmodeled_while_baseline_ignores_irrigation(self):
        """노지 출력은 `applied=False` — 역할을 골라 목록표가 modeled 라 해도 기본 예측이 안 쓰므로 미반영이다."""
        roster = [_dev('o1', 'valve', 'irrigation_mm', 'modeled', applied=False),
                  _dev('o2', 'valve', 'irrigation_mm', 'partial', applied=False)]
        lane = C.build_lanes('field', [], None, roster)[0]
        self.assertEqual(lane['effect'], 'irrigation_mm')
        self.assertEqual(lane['status'], 'unmodeled')
        self.assertEqual([d['status'] for d in lane['devices']], ['unmodeled', 'unmodeled'])

    def test_eight_valves_without_role_are_counted_not_dropped(self):
        roster = [_dev('o%d' % i) for i in range(8)]
        lanes = C.build_lanes('field', [], None, roster)
        self.assertEqual(len(lanes), 1)
        self.assertIsNone(lanes[0]['effect'])
        self.assertEqual(lanes[0]['device_count'], 8)
        self.assertEqual(lanes[0]['status'], 'unknown')

    def test_header_count_stands_in_when_roster_is_unreadable(self):
        lanes = C.build_lanes('field', [], None, None, {'effects_unmodeled': 8.0})
        self.assertEqual(len(lanes), 1)
        self.assertEqual((lanes[0]['effect'], lanes[0]['status'], lanes[0]['device_count']), (None, 'unmodeled', 8))

    def test_nothing_to_say_gives_no_lane(self):
        self.assertEqual(C.build_lanes('field', [], None, [], {'effects_unmodeled': 0.0}), [])
        self.assertEqual(C.build_lanes('field', [], None, None, None), [])


class ScenarioItems(unittest.TestCase):
    def _row(self, sid, status='done', base_run='r1', effects=None, overrides=None):
        eff = effects if effects is not None else []
        r = types.SimpleNamespace(
            id=sid, target_kind='field', target_id='plot-a', label='물 20 mm', created_at=T, requested_at=T,
            finished_at=T, status=status, pinned=0, expires_at=T + 30 * 86400, base_run=base_run, base_mode='hold',
            future_input_mode='whatif', model_rev=1, cal_rev=0, fc_issue_epoch=None, weather_src=None, obs_origin=1,
            fail_reason='이유' if status == 'failed' else None, schema_version=1)
        r.overrides_dict = lambda: overrides or {'actuators': [{'channel': 'irrigation_mm', 't0': T, 't1': T + 10800,
                                                                'value': 20, 'unit': 'mm'}], 'weather': [], 'supply': []}
        r.effects_list = lambda: eff
        return r

    def test_stale_only_when_done_and_baseline_moved(self):
        rows = [self._row('a'), self._row('b', base_run='r2'), self._row('c', status='queued')]
        out = C.scenario_items(rows, {'r1': T, 'r2': T - 86400}, T)
        by = {x['id']: x for x in out}
        self.assertFalse(by['a']['stale'])
        self.assertTrue(by['b']['stale'])
        self.assertFalse(by['c']['stale'])

    def test_unknown_current_run_is_not_called_stale(self):
        out = C.scenario_items([self._row('a')], {'r1': T}, None)
        self.assertFalse(out[0]['stale'])

    def test_effect_counts_and_plan_summary(self):
        eff = [{'status': 'unknown'}, {'status': 'unknown'}, {'status': 'modeled'}, {'status': 'weird'}]
        item = C.scenario_items([self._row('a', effects=eff)], {'r1': T}, T)[0]
        self.assertEqual(item['effects'], {'modeled': 1, 'partial': 0, 'unmodeled': 0, 'unknown': 3})
        self.assertEqual(item['actuators'][0]['value'], 20)
        self.assertEqual(item['future_input_mode'], 'whatif')

    def test_failed_carries_reason(self):
        item = C.scenario_items([self._row('a', status='failed')], {}, T)[0]
        self.assertEqual(item['fail_reason'], '이유')


if __name__ == '__main__':
    unittest.main()
