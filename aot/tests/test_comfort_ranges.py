# coding=utf-8
"""게이지 녹색(okMin/okMax)의 정본: 장치 → 그 장치가 놓인 시설 코디네이터의 적정 밴드.

고정하는 계약(사용자 결정 2026-11-06, '범위 있는 것만 녹색'):
  1. 값은 코디네이터가 마지막 사이클에 계산한 `stage_guide`(단계 값을 낮·밤·하드 임계까지
     거친 범위) 그대로다 — 화면이 다시 계산하지 않는다.
  2. 범위가 분명한 **온도·습도만** 낸다. vpd·co2 는 단일 목표라 여기서 내지 않는다.
  3. 코디네이터가 없거나(노지) 스냅샷이 비었으면 빈 dict — 녹색을 지어내지 않는다.
"""
import unittest
from unittest import mock

from aot.aot_flask.geo import coordinator_plot as cp


def _patch(fac='fac-1', guide=None):
    """_facility_of_device → fac, 코디네이터 → 더미, stage_guide → guide 로 묶어 패치한다.

    노지 폴백(`_plot_limit_ranges`)은 빈 dict 로 묶어 코디네이터 경로만 본다 —
    코디네이터가 밴드를 못 내면 폴백이 DB 를 긁는데, 이 단위 테스트는 그 경로를
    따로 본다( PlotLimitRangesTest)."""
    return (
        mock.patch.object(cp, '_facility_of_device', return_value=fac),
        mock.patch.object(cp, 'facility_env_coordinator',
                          return_value=(object() if fac else None)),
        mock.patch.object(cp, '_live_summary',
                          return_value={'stage_guide': guide} if guide is not None else {}),
        mock.patch.object(cp, '_plot_limit_ranges', return_value={}),
    )


class ComfortRangesTest(unittest.TestCase):

    def _run(self, fac='fac-1', guide=None):
        a, b, c, d = _patch(fac, guide)
        with a, b, c, d:
            return cp.comfort_ranges_for_device('dev-1')

    def test_temperature_and_humidity_from_stage_guide(self):
        out = self._run(guide={'T_min': 22.0, 'T_max': 28.0,
                               'RH_min': 55.0, 'RH_max': 75.0})
        self.assertEqual((22.0, 28.0), out['temperature'])
        self.assertEqual((55.0, 75.0), out['relative_humidity'])

    def test_missing_humidity_yields_temperature_only(self):
        out = self._run(guide={'T_min': 22.0, 'T_max': 28.0,
                               'RH_min': None, 'RH_max': None})
        self.assertEqual({'temperature': (22.0, 28.0)}, out)

    def test_degenerate_range_is_dropped(self):
        out = self._run(guide={'T_min': 24.0, 'T_max': 24.0,
                               'RH_min': 60.0, 'RH_max': 50.0})   # hi<=lo 둘 다 버린다
        self.assertEqual({}, out)

    def test_no_facility_means_empty(self):
        self.assertEqual({}, self._run(fac=None,
                                       guide={'T_min': 22.0, 'T_max': 28.0}))

    def test_empty_snapshot_means_empty(self):
        self.assertEqual({}, self._run(guide=None))     # 코디네이터가 한 번도 안 돌았다


class CoordinatorFirstTest(unittest.TestCase):
    """두 경로의 순서: 코디네이터가 밴드를 내면 그걸 쓰고 노지 폴백은 건드리지 않는다.
    코디네이터가 비면 폴백으로 내려간다."""

    def test_coordinator_band_short_circuits_fallback(self):
        fb = mock.Mock(return_value={'temperature': (1.0, 2.0)})
        with mock.patch.object(cp, '_coordinator_comfort_ranges',
                               return_value={'temperature': (20.0, 25.0)}), \
             mock.patch.object(cp, '_plot_limit_ranges', fb):
            out = cp.comfort_ranges_for_device('dev-1')
        self.assertEqual({'temperature': (20.0, 25.0)}, out)
        fb.assert_not_called()

    def test_empty_coordinator_falls_through_to_plot_limits(self):
        with mock.patch.object(cp, '_coordinator_comfort_ranges', return_value={}), \
             mock.patch.object(cp, '_plot_limit_ranges',
                               return_value={'temperature': (18.0, 26.0)}):
            out = cp.comfort_ranges_for_device('dev-1')
        self.assertEqual({'temperature': (18.0, 26.0)}, out)


class PlotLimitRangesTest(unittest.TestCase):
    """노지(코디네이터 없음) 폴백: 참조 구획의 단계 한계(`program_limits`) 온도만.

    고정하는 계약:
      1. 온도는 주·야 두 경계(min, max)로만 — 경계가 하나뿐이면 범위가 아니다.
      2. 습도는 값 하나뿐이라 방향 미선언 → 내지 않는다.
      3. 참조 구획이 여럿인데 온도 한계가 갈리면 빈 dict(정직). 모두 같으면 그 하나.
      4. 참조 구획이 없으면 빈 dict.
    """

    def _run(self, plots, limits_by_plot):
        """plots = [표식…], limits_by_plot = program_limits 가 그 표식마다 낼 dict."""
        with mock.patch.object(cp, '_plots_referencing_device', return_value=plots), \
             mock.patch.object(cp, 'program_limits',
                               side_effect=lambda p, on=None: limits_by_plot[p]):
            return cp._plot_limit_ranges('dev-1')

    def test_single_plot_temperature_range(self):
        out = self._run(['p1'], {'p1': {'temperature': [18.0, 26.0]}})
        self.assertEqual({'temperature': (18.0, 26.0)}, out)

    def test_single_boundary_is_not_a_range(self):
        out = self._run(['p1'], {'p1': {'temperature': [18.0]}})   # 주/야 중 하나만
        self.assertEqual({}, out)

    def test_humidity_single_value_gets_no_band(self):
        out = self._run(['p1'], {'p1': {'humidity': [60.0]}})
        self.assertEqual({}, out)

    def test_agreeing_plots_yield_the_band(self):
        out = self._run(['p1', 'p2'], {'p1': {'temperature': [18.0, 26.0]},
                                       'p2': {'temperature': [18.0, 26.0]}})
        self.assertEqual({'temperature': (18.0, 26.0)}, out)

    def test_conflicting_plots_yield_nothing(self):
        out = self._run(['p1', 'p2'], {'p1': {'temperature': [18.0, 26.0]},
                                       'p2': {'temperature': [15.0, 22.0]}})
        self.assertEqual({}, out)

    def test_no_referencing_plot_means_empty(self):
        self.assertEqual({}, self._run([], {}))

    def test_blank_device_id_means_empty(self):
        self.assertEqual({}, cp._plot_limit_ranges(''))


class PlotsReferencingDeviceTest(unittest.TestCase):
    """장치↔구획 결속은 `sensors_for_plot` 의 실내 체인으로만 — 실외 기상은 제외."""

    def _patch(self, sensors_by_plot, plots=('p1',)):
        return (
            mock.patch('aot.space.plot_context.active_plots',
                       return_value=list(plots)),
            mock.patch('aot.space.plot_context.sensors_for_plot',
                       side_effect=lambda p, *a, **k: sensors_by_plot.get(p, {})),
        )

    def test_indoor_chain_members_match(self):
        for key in ('in_plot', 'in_bay', 'from_facility', 'from_zone'):
            a, b = self._patch({'p1': {key: ['dev-1']}})
            with a, b:
                self.assertEqual(['p1'], cp._plots_referencing_device('dev-1'),
                                 'should match via %s' % key)

    def test_weather_only_is_not_a_member(self):
        a, b = self._patch({'p1': {'from_weather': ['dev-1']}})
        with a, b:
            self.assertEqual([], cp._plots_referencing_device('dev-1'))

    def test_unrelated_device_not_matched(self):
        a, b = self._patch({'p1': {'in_plot': ['dev-9']}})
        with a, b:
            self.assertEqual([], cp._plots_referencing_device('dev-1'))




class ProgramSpokenTest(unittest.TestCase):
    """구획 프로그램이 정한 항목 → 지도 기본 밴드를 덧그리지 않을 측정 이름(값이든 곡선이든)."""

    def test_values_and_curves_both_count(self):
        with mock.patch.object(cp, '_plots_referencing_device', return_value=['p1', 'p2']), \
             mock.patch.object(cp, '_stage_values', side_effect=[
                 ({'temp_day': 24, 'rh': 70}, {}), ({}, {'vpd': 'curve'})]):
            out = cp.program_spoken_measurements('dev-1')
        self.assertEqual({'temperature', 'relative_humidity', 'vapor_pressure_deficit'}, out)

    def test_no_plot_means_nothing_spoken(self):
        with mock.patch.object(cp, '_plots_referencing_device', return_value=[]):
            self.assertEqual(set(), cp.program_spoken_measurements('dev-1'))

    def test_unrelated_keys_ignored(self):
        with mock.patch.object(cp, '_plots_referencing_device', return_value=['p1']), \
             mock.patch.object(cp, '_stage_values', return_value=({'co2': 800, 'dli': 14}, {})):
            self.assertEqual(set(), cp.program_spoken_measurements('dev-1'))


if __name__ == '__main__':
    unittest.main()
