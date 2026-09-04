# coding=utf-8
"""곡선 목표(DailyMultiPoint)의 **재배 주차 기준**을 한 곳으로 고정한다.

같은 구획·같은 날인데 제어가 쓰는 목표와 화면이 보여 주는 목표가 달랐다.
주차를 세 곳이 서로 다르게 셌기 때문이다:

  1. 제어  `_helpers_mixin._get_weeks_elapsed()` — 소수 주차
  2. 구획 모달 `coordinator_plot._resolve_curve_targets()` — `days // 7` 정수
  3. 일지  `plot_journal._with_curve_deltas()` — 2번을 따라 정수

거기에 더해 두 가지 결함이 겹쳐 있었다.

* **구획 모달이 `facility_tz=None` 을 넘겼다.** 하루 곡선의 시각이 UTC 로
  잡혀 한국이면 아홉 시간 밀린다. 2026-09-04 20:36 KST 김제 3-1 가을오이
  실측에서 제어 0.61 kPa vs 모달 1.09 kPa 였고, 그 차이 0.481 중 0.478 이
  이 폴백이었다(주차 차이는 0.003).
* **`DailyMultiPointMethod` 가 곡선을 `int(weeks_elapsed)` 로 캐시했다.**
  데몬이 핸들러를 사이클 사이에 붙들고 있으므로, 그 정수 층에서 **처음
  물어본 소수**의 곡선이 그 주 내내 재사용됐다 — 같은 순간의 목표가 데몬
  재시작 시점에 좌우됐다.

정본은 **소수 주차 + 현지 시간대**이고, 셋 다 `weeks_elapsed_at()` 하나를
쓴다. 곡선의 주차 보간(`_interp_weeks`)이 선형인 이상 내림은 그 설계를
계단으로 바꾼다 — 곡선을 걸어 둔 뜻이 주 경계마다 한 번씩만 반영된다.

전부 **순수 계산**이라 DB·Flask 컨텍스트 없이 돈다.
"""
import datetime
import json
import os
import sys
import unittest
from unittest import mock

import pytz

sys.path.insert(0, os.path.abspath(
    os.path.join(os.path.dirname(__file__), '..', '..')))

from aot.utils.method import (                               # noqa: E402
    DailyMultiPointMethod, local_noon, weeks_elapsed_at)

SEOUL = pytz.timezone('Asia/Seoul')

#: 김제 3-1 가을오이의 실제 곡선을 줄인 것 — 주차마다 값이 다르고(보간이
#: 살아 있어야 차이가 보인다) 하루 안에서도 크게 움직인다(시간대 폴백이
#: 살아 있으면 차이가 보인다).
CURVE = {
    'version': 3,
    'weeks': [0, 3, 6, 9],
    'points': [
        {'point_id': 0, 't_sec': 0,     'values': [0.30, 0.35, 0.40, 0.45],
         'curve': 'linear', 'is_endpoint': True},
        {'point_id': 1, 't_sec': 43200, 'values': [0.70, 0.90, 1.10, 1.10],
         'curve': 'linear'},
        {'point_id': 2, 't_sec': 86399, 'values': [0.30, 0.35, 0.40, 0.45],
         'curve': 'linear', 'is_endpoint': True},
    ],
}


def _handler(data=None):
    """DB 없이 `DailyMultiPointMethod` 하나."""
    m = DailyMultiPointMethod.__new__(DailyMultiPointMethod)
    m._data = json.loads(json.dumps(data or CURVE))
    m._resolved_cache = None
    m._resolved_week = None
    m.logger = None
    return m


# ─────────────────────────────────────────────────────────────────────────────
# 정본 함수
# ─────────────────────────────────────────────────────────────────────────────

class TestWeeksElapsedAt(unittest.TestCase):
    """`weeks_elapsed_at()` — 주차를 세는 곳은 여기 하나다."""

    def test_returns_fractional_not_floored(self):
        """소수 주차. 내림하면 곡선의 주차 보간이 계단이 된다."""
        started = datetime.date(2026, 7, 15)
        when = SEOUL.localize(datetime.datetime(2026, 9, 4, 20, 36))
        self.assertAlmostEqual(
            weeks_elapsed_at(started, when=when, tz=SEOUL), 51.86 / 7, places=2)

    def test_start_date_is_local_midnight_not_utc(self):
        """날짜만 있는 시작일은 **현지 자정**이다.

        UTC 자정으로 읽으면 한국에서 아홉 시간을 앞당긴다 — 농부는 UTC 로
        심지 않는다.
        """
        started = datetime.date(2026, 7, 15)
        when = SEOUL.localize(datetime.datetime(2026, 7, 22, 0, 0))
        self.assertAlmostEqual(weeks_elapsed_at(started, when=when, tz=SEOUL),
                               1.0, places=9)
        # 같은 순간을 UTC 자정 기준으로 읽으면 시작이 9시간 늦어져 그만큼
        # 덜 흐른 것이 된다(0.0536주).
        self.assertAlmostEqual(weeks_elapsed_at(started, when=when, tz=None),
                               1.0 - 9 / 168.0, places=6)

    def test_accepts_date_datetime_and_iso_string(self):
        when = SEOUL.localize(datetime.datetime(2026, 7, 29, 0, 0))
        expect = 2.0
        for started in (datetime.date(2026, 7, 15),
                        datetime.datetime(2026, 7, 15, 0, 0),
                        '2026-07-15',
                        SEOUL.localize(datetime.datetime(2026, 7, 15, 0, 0))):
            self.assertAlmostEqual(
                weeks_elapsed_at(started, when=when, tz=SEOUL), expect,
                places=9, msg=repr(started))

    def test_missing_start_is_none_not_zero(self):
        """'주차를 못 센다' 와 '0주차' 는 다르다 — 0 이면 곡선 첫 주를 그린다."""
        self.assertIsNone(weeks_elapsed_at(None))
        self.assertIsNone(weeks_elapsed_at(''))

    def test_before_start_clamps_to_zero(self):
        when = SEOUL.localize(datetime.datetime(2026, 7, 1, 0, 0))
        self.assertEqual(
            weeks_elapsed_at(datetime.date(2026, 7, 15), when=when, tz=SEOUL),
            0.0)

    def test_local_noon_represents_the_whole_day(self):
        """하루를 한 값으로 대표할 때는 정오다.

        자정을 쓰면 그날 전체가 전날 끝자락의 주차로 계산된다.
        """
        noon = local_noon(datetime.date(2026, 9, 4), SEOUL)
        self.assertEqual(noon.hour, 12)
        self.assertEqual(noon.utcoffset(), datetime.timedelta(hours=9))
        midnight_weeks = weeks_elapsed_at(
            datetime.date(2026, 7, 15),
            when=local_noon(datetime.date(2026, 9, 4), SEOUL)
            - datetime.timedelta(hours=12), tz=SEOUL)
        noon_weeks = weeks_elapsed_at(datetime.date(2026, 7, 15),
                                      when=noon, tz=SEOUL)
        self.assertAlmostEqual(noon_weeks - midnight_weeks, 0.5 / 7, places=9)


# ─────────────────────────────────────────────────────────────────────────────
# 곡선 캐시
# ─────────────────────────────────────────────────────────────────────────────

class TestResolvedCacheIsFractional(unittest.TestCase):
    """캐시 열쇠는 소수 주차 그대로다."""

    def _at(self, handler, weeks, hour=0):
        """기본은 자정이다 — 이 곡선의 자정 값은 네 주차가 모두 다르므로
        (0.30/0.35/0.40/0.45) 주차가 값을 움직이는지 실제로 보인다. 정오는
        6주차와 9주차 값이 같아(1.10/1.10) 주차 결함을 가린다."""
        ts = SEOUL.localize(
            datetime.datetime(2026, 9, 4, hour, 0)).timestamp()
        value, _ = handler.calculate_setpoint(
            ts, weeks_elapsed=weeks, facility_tz=SEOUL)
        return value

    def test_answer_does_not_depend_on_earlier_calls(self):
        """**이 파일이 있는 이유.**

        예전에는 `int(weeks_elapsed)` 로 캐시해, 같은 순간·같은 곡선인데도
        그 핸들러가 그 주에 처음 무엇을 물었는지에 따라 답이 달라졌다.
        데몬은 핸들러를 붙들고 있으므로 재시작 시점이 목표를 바꿨다.
        """
        answers = set()
        for first_ask in (7.0, 7.5, 7.99, 3.2, 9.0):
            h = _handler()
            self._at(h, first_ask)          # 먼저 딴 주차를 물어본다
            answers.add(round(self._at(h, 7.4088), 9))
        self.assertEqual(len(answers), 1, '호출 순서가 목표를 바꿨다: %s' % answers)

    def test_fresh_handler_agrees_with_reused_handler(self):
        reused = _handler()
        self._at(reused, 7.0)
        self.assertAlmostEqual(self._at(reused, 7.4088),
                               self._at(_handler(), 7.4088), places=9)

    def test_fraction_within_a_week_actually_moves_the_setpoint(self):
        """소수 주차가 값을 움직여야 보간이 살아 있는 것이다.

        자정 값은 6주 0.40 → 9주 0.45 이므로, 7.0 주와 7.9 주는 달라야 한다.
        내림하면 둘 다 7 주차가 되어 같은 값이 나온다.
        """
        h = _handler()
        self.assertNotAlmostEqual(self._at(h, 7.0), self._at(h, 7.9), places=3)

    def test_cache_still_hits_for_a_repeated_week(self):
        """일지는 하루 288 표본이 같은 주차를 공유한다 — 캐시가 그때 듣는다."""
        h = _handler()
        self._at(h, 7.4088)
        with mock.patch('aot.utils.method._resolve_v2_at') as spy:
            self._at(h, 7.4088)
        spy.assert_not_called()


# ─────────────────────────────────────────────────────────────────────────────
# 세 경로가 같은 기준을 쓰는가
# ─────────────────────────────────────────────────────────────────────────────

class _SpyHandler(object):
    """`calculate_setpoint` 이 무엇을 받았는지 기록하는 곡선."""

    def __init__(self):
        self.calls = []
        self._real = _handler()

    def calculate_setpoint(self, now, method_start_time=None,
                           weeks_elapsed=None, facility_tz=None):
        self.calls.append({'weeks_elapsed': weeks_elapsed,
                           'facility_tz': facility_tz})
        return self._real.calculate_setpoint(
            now, method_start_time=method_start_time,
            weeks_elapsed=weeks_elapsed, facility_tz=facility_tz)


class _FakePlot(object):
    unique_id = 'plot-1'
    program_uuid = 'prog-1'
    facility_uuid = None
    started_on = datetime.date(2026, 7, 15)


class TestPlotModalUsesSharedBasis(unittest.TestCase):
    """구획 모달(`_resolve_curve_targets`) — 소수 주차와 현지 시간대."""

    def _run(self):
        from aot.aot_flask.geo import coordinator_plot as CP
        spy = _SpyHandler()
        prog = mock.Mock(targets_methods={'vpd': 'curve-1'})
        with mock.patch('aot.databases.models.GeoProgram') as geo_program, \
                mock.patch('aot.utils.device_tz.resolve_location_tz',
                           return_value=SEOUL), \
                mock.patch('aot.utils.method.load_method_handler',
                           return_value=spy):
            geo_program.query.filter_by.return_value.first.return_value = prog
            out = CP._resolve_curve_targets(_FakePlot(), ['vpd'])
        return out, spy.calls[0]

    def test_passes_fractional_weeks(self):
        _, call = self._run()
        weeks = call['weeks_elapsed']
        self.assertIsNotNone(weeks)
        self.assertNotEqual(weeks, int(weeks),
                            '정수 주차를 넘기면 주차 보간이 계단이 된다')
        self.assertAlmostEqual(
            weeks,
            weeks_elapsed_at(_FakePlot.started_on, tz=SEOUL), places=3)

    def test_passes_the_plot_timezone_not_none(self):
        """`facility_tz=None` 이면 하루 곡선이 UTC 로 밀린다(한국 9시간)."""
        _, call = self._run()
        self.assertIsNotNone(call['facility_tz'],
                             'facility_tz=None 은 하루 곡선을 UTC 로 민다')
        self.assertEqual(str(call['facility_tz']), 'Asia/Seoul')

    def test_utc_fallback_is_a_large_error_not_a_rounding_one(self):
        """`facility_tz=None` 이 얼마나 틀리는지를 숫자로 고정한다.

        현장 실측(2026-09-04 20:36 KST, 김제 3-1 가을오이)에서 제어 0.61 vs
        모달 1.09 였다. 저녁 8시에 정오 목표를 보여 준 것이다 — 반올림
        오차가 아니라 곡선을 통째로 아홉 시간 민 결과다.
        """
        ts = SEOUL.localize(datetime.datetime(2026, 9, 4, 20, 36)).timestamp()
        weeks = weeks_elapsed_at(
            _FakePlot.started_on,
            when=SEOUL.localize(datetime.datetime(2026, 9, 4, 20, 36)),
            tz=SEOUL)
        local_value, _ = _handler().calculate_setpoint(
            ts, weeks_elapsed=weeks, facility_tz=SEOUL)
        utc_value, _ = _handler().calculate_setpoint(
            ts, weeks_elapsed=weeks, facility_tz=None)
        self.assertGreater(abs(utc_value - local_value), 0.3)
        # 저녁 8시의 목표는 정오 봉우리가 아니라 야간 쪽으로 내려가 있어야 한다.
        self.assertLess(local_value, 0.8)
        self.assertGreater(utc_value, 1.0)

    def test_no_start_date_yields_no_number_not_the_last_week(self):
        """주차를 못 세면 숫자를 내지 않는다.

        예전에는 `weeks_elapsed=None` 이 그대로 넘어가 `calculate_setpoint`
        이 1900-01-01 을 시작일로 잡고 **마지막 주차** 곡선을 돌려줬다 —
        목표라고 적히는 지어낸 숫자다. 일지도 같은 경우 그 행을 건너뛴다.
        """
        from aot.aot_flask.geo import coordinator_plot as CP

        class _NoStart(_FakePlot):
            started_on = None

        prog = mock.Mock(targets_methods={'vpd': 'curve-1'})
        with mock.patch('aot.databases.models.GeoProgram') as geo_program, \
                mock.patch('aot.utils.device_tz.resolve_location_tz',
                           return_value=SEOUL), \
                mock.patch('aot.utils.method.load_method_handler',
                           return_value=_handler()):
            geo_program.query.filter_by.return_value.first.return_value = prog
            out = CP._resolve_curve_targets(_NoStart(), ['vpd'])
        self.assertEqual(out, {})

    def test_returns_a_rounded_value_for_the_modal(self):
        out, _ = self._run()
        self.assertIsInstance(out.get('vpd'), float)
        self.assertEqual(out['vpd'], round(out['vpd'], 2))


class TestJournalUsesSharedBasis(unittest.TestCase):
    """일지(`_with_curve_deltas`) — 그날 현지 정오의 소수 주차."""

    def _journal(self, day):
        return {
            'target': {'tz_name': 'Asia/Seoul'},
            'stages': [{'starts_on': '2026-07-15', 'targets': [
                {'source': 'method', 'method_uuid': 'curve-1',
                 'measurement': 'vapor_pressure_deficit'}]}],
            'buckets': [{'key': day, 'sunrise': '06:00', 'sunset': '19:00',
                         'env': [{'measurement': 'vapor_pressure_deficit',
                                  'delta_skipped': 'method',
                                  'avg_day': 1.0, 'avg_night': 0.5}]}],
        }

    def _run(self, day):
        from aot.aot_flask.geo import plot_journal as PJ
        spy = _SpyHandler()
        with mock.patch('aot.utils.method.load_method_handler',
                        return_value=spy):
            out = PJ.with_curve_deltas(self._journal(day))
        return out, spy.calls

    def test_passes_fractional_weeks_at_local_noon(self):
        _, calls = self._run('2026-09-04')
        self.assertTrue(calls)
        expected = weeks_elapsed_at(
            datetime.date(2026, 7, 15),
            when=local_noon(datetime.date(2026, 9, 4), SEOUL), tz=SEOUL)
        for call in calls:
            self.assertAlmostEqual(call['weeks_elapsed'], expected, places=9)
            self.assertIsNotNone(call['facility_tz'])

    def test_two_days_in_the_same_week_get_different_targets(self):
        """**정수 주차가 지웠던 것.**

        같은 정수 주 안의 이틀은 예전에는 글자 그대로 같은 목표를 받았다.
        곡선이 주차마다 움직이도록 만들어졌으므로 달라야 한다.
        """
        def target(day):
            out, _ = self._run(day)
            row = out['buckets'][0]['env'][0]
            return row['target_phases']['day']['target']
        self.assertNotEqual(target('2026-08-31'), target('2026-09-04'))

    def test_marks_the_row_as_compared_by_phase(self):
        out, _ = self._run('2026-09-04')
        row = out['buckets'][0]['env'][0]
        self.assertEqual(row['delta_skipped'], 'curve-phase')
        self.assertIn('day', row['target_phases'])
        self.assertIn('night', row['target_phases'])

    def test_missing_start_leaves_the_journal_untouched(self):
        """주차를 못 세는 것은 문서를 못 열 이유가 아니다."""
        from aot.aot_flask.geo import plot_journal as PJ
        data = self._journal('2026-09-04')
        data['stages'][0]['starts_on'] = None
        self.assertIs(PJ.with_curve_deltas(data), data)


class TestThreePathsAgree(unittest.TestCase):
    """제어·구획 모달·일지가 같은 날 같은 곡선에 같은 주차를 쓴다."""

    def test_control_and_modal_agree_at_the_same_instant(self):
        """구획 모달은 '지금' 을 본다 — 제어와 같은 순간, 같은 주차."""
        from aot.aot_flask.geo import coordinator_plot as CP
        spy = _SpyHandler()
        prog = mock.Mock(targets_methods={'vpd': 'curve-1'})
        with mock.patch('aot.databases.models.GeoProgram') as geo_program, \
                mock.patch('aot.utils.device_tz.resolve_location_tz',
                           return_value=SEOUL), \
                mock.patch('aot.utils.method.load_method_handler',
                           return_value=spy):
            geo_program.query.filter_by.return_value.first.return_value = prog
            CP._resolve_curve_targets(_FakePlot(), ['vpd'])
        # 제어(`_get_weeks_elapsed`)가 세는 것과 같은 식이다.
        control = weeks_elapsed_at(_FakePlot.started_on, tz=SEOUL)
        self.assertAlmostEqual(spy.calls[0]['weeks_elapsed'], control, places=4)

    def test_journal_noon_sits_inside_that_days_control_range(self):
        """일지의 그날 주차는 그날 제어가 쓴 주차 범위 안에 있다.

        제어는 하루 동안 1/7 주만큼 흐르고, 일지는 그 하루를 한 값으로
        대표한다 — 그 값은 자정과 다음 자정 사이여야 한다.
        """
        started = datetime.date(2026, 7, 15)
        day = datetime.date(2026, 9, 4)
        noon = weeks_elapsed_at(started, when=local_noon(day, SEOUL), tz=SEOUL)
        begin = weeks_elapsed_at(
            started, when=SEOUL.localize(datetime.datetime(2026, 9, 4, 0, 0)),
            tz=SEOUL)
        end = weeks_elapsed_at(
            started, when=SEOUL.localize(datetime.datetime(2026, 9, 5, 0, 0)),
            tz=SEOUL)
        self.assertLess(begin, noon)
        self.assertLess(noon, end)
        self.assertAlmostEqual(noon, (begin + end) / 2, places=9)


if __name__ == '__main__':
    unittest.main()
