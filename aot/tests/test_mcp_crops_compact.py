# coding=utf-8
"""`overview.crops` 의 기본형 — 구역·작물·경과일수만 (2026-10-27 음성 점검).

고정하는 계약:
  1. 기본(`detail=False`, 도메인 틀이 넣는다)은 구획마다 place·crop·days·id 뿐이다 — 단계 지침·
     종료 점검·프로그램 이름은 빠진다(구획 31건에 10.9KB 였다).
  2. 안쪽 도구를 `detail` 없이 부르는 옛 호출은 예전 모양 그대로다.
  3. 시작 전 구획은 days 대신 starts, 종료된 구획은 ended_on 을 남긴다.
  4. 센서를 청한 목록은 접지 않는다.
DB 없이 도는 결정론적 테스트다.
"""
import unittest

from aot.tools.data_tools import crop_compact as cc


def _plot(**kw):
    base = {'unique_id': 'u1', 'kind': 'vegetation', 'subject': '콩 1구', 'variety': '유색',
            'zone_name': '3-1', 'zone_kind': 'zone', 'area_m2': 994.7, 'started_on': '2026-06-15',
            'days_since_planted': 135, 'planned': False, 'active': True, 'program_name': '콩',
            'stage': {'name': '종실비대', 'guidance': '과습 주의'}, 'end_check': {'state': 'x'}}
    base.update(kw)
    return base


class Compact(unittest.TestCase):

    def test_plot_keeps_only_place_crop_days_id(self):
        row = cc.compact_plot(_plot(place='3포장 > 3-1'))
        self.assertEqual({'place': '3포장 > 3-1', 'crop': '콩 1구', 'variety': '유색', 'days': 135, 'id': 'u1'}, row)

    def test_planned_and_ended_plots_say_so(self):
        planned = cc.compact_plot(_plot(planned=True, days_since_planted=None, started_on='2026-12-01'))
        self.assertEqual((True, '2026-12-01'), (planned['planned'], planned['starts']))
        self.assertNotIn('days', planned)
        self.assertEqual('2026-09-01', cc.compact_plot(_plot(ended_on='2026-09-01'))['ended_on'])

    def test_bay_plot_place_is_facility_and_bay(self):
        row = cc.compact_plot(_plot(zone_name='3포장', facility_name='육묘장3', bay_name='1동'))
        self.assertEqual('육묘장3 > 1동', row['place'])

    def test_list_response(self):
        out = {'count': 1, 'plots': [_plot()], 'truncated': True, 'summary': 'WARNING', '_reading': ['long'],
               'note': 'n'}
        res = cc.compact_list(out)
        self.assertEqual(['place', 'crop', 'variety', 'days', 'id'], list(res['plots'][0]))
        self.assertTrue(res['truncated'])
        self.assertEqual('WARNING', res['summary'])
        self.assertNotEqual(['long'], res['_reading'])

    def test_status_response_drops_the_long_notes(self):
        out = {'status': 'success', 'count': 1, 'plot_count': 1, 'plot_detail': 'x' * 300,
               'facilities': [{'facility_name': '육묘장', 'crop': '토마토', 'stage': '결실기',
                               'facility_id': 'f1', 'controlled_by': 'c', 'optimal_ranges': {'a': 1}}],
               'open_field_plots': [_plot()], 'facility_bay_plot_note': 'y' * 300}
        res = cc.compact_status(out)
        self.assertNotIn('plot_detail', res)
        self.assertNotIn('facility_bay_plot_note', res)
        self.assertEqual({'facility': '육묘장', 'crop': '토마토', 'stage': '결실기', 'id': 'f1'}, res['facilities'][0])
        self.assertEqual(1, res['plot_count'])

    def test_errors_pass_through(self):
        err = {'status': 'error', 'message': 'x'}
        self.assertIs(err, cc.compact_status(err))
        self.assertEqual({'error': 'x'}, cc.compact_list({'error': 'x'}))

    def test_only_explicit_false_compacts(self):
        self.assertTrue(cc.wants_compact(False))
        self.assertFalse(cc.wants_compact(None))
        self.assertFalse(cc.wants_compact(True))


class Wiring(unittest.TestCase):

    def test_crops_op_defaults_to_compact_for_every_inner_tool(self):
        from aot.tools.domain.registry_data import OPS
        o = {(x.tool, x.op): x for x in OPS}[('overview', 'crops')]
        self.assertIn('detail', o.extra_args)
        self.assertEqual(set(o.inner), set(o.defaults_by_kind))
        self.assertTrue(all(v == {'detail': False} for v in o.defaults_by_kind.values()))


if __name__ == '__main__':
    unittest.main()
