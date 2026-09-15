# coding=utf-8
"""기간별 출처를 실제로 쓰는 계산 — GDD·DLI·[환경] 계열.

`plot_sources` 가 출처를 옳게 조합해도 소비처가 옛 방식(지금 센서 하나로
기간 전체를 묻기)으로 부르면 소용없다. 같은 교체 흐름 — 물리 센서 A 를
떼고(8/20), API 센서 W 가 공백을 메우고, 물리 센서 B 를 단다(9/1) — 으로
세 계산이 날짜마다 알맞은 센서의 값을 쓰는지 **합계까지** 고정한다.

InfluxDB 는 없다. 조회 함수를 대역으로 잡고 "어느 장치에게 어느 기간을
물었는가" 와 그 결과를 접은 값을 본다.
"""
from datetime import date, datetime, timedelta

from aot.aot_flask.geo import plot_context, plot_journal, plot_sources
from aot.databases.models import DeviceMeasurements, Input
from aot.tests.geo.test_plot_sources import T1, T2, _Base, _Plot

_FMT = '%Y-%m-%dT%H:%M:%SZ'
TEMPS = {'phys-a': (30.0, 20.0), 'api-w': (24.0, 14.0), 'phys-b': (32.0, 22.0)}


class _CropPlot(_Plot):
    started_on = date(2026, 8, 1)
    ended_on = None


class _Program(object):
    photosynthesis = {'T_base': 10.0, 'gdd_daily': None, 'dli_target': None}


def _days(start_str, end_str):
    """[start, end) 에 걸친 날짜(UTC) — 대역 조회가 돌려줄 날짜들."""
    s = datetime.strptime(start_str, _FMT)
    e = datetime.strptime(end_str, _FMT) - timedelta(seconds=1)
    d, out = s.date(), []
    while d <= e.date():
        out.append(d)
        d += timedelta(days=1)
    return out


class _Flow(_Base):

    def setUp(self):
        super().setUp()
        for uid in ('phys-a', 'api-w', 'phys-b'):
            self._sensor(uid)
        for uid in ('api-w', 'phys-b'):
            DeviceMeasurements(device_id=uid, channel=1,
                               measurement='light', unit='W_m2').save()
        a = self._place('phys-a', 127.001, 35.001)
        self._remove(a, T1)
        self._place('api-w', 127.015, 35.015)
        self._place('phys-b', 127.001, 35.001, since=T2)

        # 시간대가 기계 설정에 따라 달라지면 날짜 경계가 흔들린다 — UTC 로 고정.
        import aot.utils.device_tz as device_tz
        self._orig_tz = device_tz.resolve_location_tz
        device_tz.resolve_location_tz = lambda *_a, **_k: 'UTC'

    def tearDown(self):
        import aot.utils.device_tz as device_tz
        device_tz.resolve_location_tz = self._orig_tz
        super().tearDown()


class TestGddFollowsTheReplacement(_Flow):

    def setUp(self):
        super().setUp()
        self.calls = []

        def fake(kind):
            def _extremes(device_id, channel, measure, start_ts, end_ts, tz,
                          bucket_sec):
                self.calls.append((kind, device_id))
                return {d: TEMPS[device_id] for d in _days(start_ts, end_ts)}
            return _extremes

        self._orig = (plot_context._daily_extremes,
                      plot_context._query_daily_extremes)
        plot_context._daily_extremes = fake('cached')
        plot_context._query_daily_extremes = fake('uncached')

    def tearDown(self):
        (plot_context._daily_extremes,
         plot_context._query_daily_extremes) = self._orig
        super().tearDown()

    def test_each_day_uses_the_sensor_that_was_there(self):
        out = plot_context.gdd_accumulated(_CropPlot(), _Program(),
                                           on=date(2026, 9, 11))
        # 8/1~8/19 A(15/일) · 8/20~8/31 W(9/일) · 9/1~9/10 B(17/일)
        self.assertEqual(out['days_counted'], 41)
        self.assertAlmostEqual(out['value'], 19 * 15 + 12 * 9 + 10 * 17)
        self.assertTrue(out['usable'])

    def test_cut_periods_bypass_the_daily_cache(self):
        """떼어낸 A·새로 단 B 는 기간이 잘려 있다 — 그 절반짜리 날이 캐시에
        남으면 다음 전체 조회에 섞인다. 기간 전체를 덮는 W 만 캐시를 쓴다."""
        plot_context.gdd_accumulated(_CropPlot(), _Program(),
                                     on=date(2026, 9, 11))
        self.assertEqual(sorted(self.calls),
                         [('cached', 'api-w'), ('uncached', 'phys-a'),
                          ('uncached', 'phys-b')])


class TestDliPrefersThePlotSensor(_Flow):

    def _dli(self, on, values):
        def fake_sum(device_id, channel, unit, factor, start_str, end_str):
            return values[device_id]

        orig = plot_context._light_channel_sum
        plot_context._light_channel_sum = fake_sum
        try:
            return plot_context.dli_accumulated(_CropPlot(), None, on=on)
        finally:
            plot_context._light_channel_sum = orig

    def test_the_plot_sensor_wins_once_it_is_installed(self):
        out = self._dli(date(2026, 9, 5),
                        {'phys-b': (5.0, 8), 'api-w': (3.0, 10)})
        self.assertAlmostEqual(out['value'], 5.0)

    def test_the_zone_sensor_fills_the_gap_before_installation(self):
        out = self._dli(date(2026, 8, 25), {'api-w': (3.0, 10)})
        self.assertAlmostEqual(out['value'], 3.0)

    def test_a_silent_plot_sensor_hands_over_to_the_zone(self):
        """밤의 0 과 달리 표본이 0 이면 그 센서는 그날 값을 안 낸 것이다."""
        out = self._dli(date(2026, 9, 5),
                        {'phys-b': (0.0, 0), 'api-w': (3.0, 10)})
        self.assertAlmostEqual(out['value'], 3.0)


class TestEnvSeriesFollowsTheReplacement(_Flow):

    def setUp(self):
        super().setUp()
        self.asked = []

        def fake_daily(dm_row, start_str, end_str, tz, granularity='day',
                       bucket_sec=3600, sun_fn=None,
                       stats=('min', 'max', 'mean')):
            self.asked.append((dm_row.device_id, start_str, end_str))
            tmax, tmin = TEMPS[dm_row.device_id]
            return {'device_id': dm_row.device_id, 'channel': dm_row.channel,
                    'unit': 'C', 'measurement': 'temperature',
                    'by_bucket': {d: {'min': tmin, 'max': tmax,
                                      'avg': (tmax + tmin) / 2, 'samples': 24}
                                  for d in _days(start_str, end_str)},
                    'dli_assumed': None}

        self._orig = plot_journal.daily_channel_stats
        plot_journal.daily_channel_stats = fake_daily

    def tearDown(self):
        plot_journal.daily_channel_stats = self._orig
        super().tearDown()

    def _rows(self):
        found = plot_sources.resolve(_CropPlot(), datetime(2026, 8, 1),
                                     datetime(2026, 9, 11))
        series, errors = plot_journal.env_channel_series(
            [], '2026-08-01T00:00:00Z', '2026-09-11T00:00:00Z', 'UTC',
            measurements=['temperature'],
            sources=found['indoor'] + found['outdoor'])
        self.assertEqual(errors, [])
        labels = [date(2026, 8, 10), date(2026, 8, 25), date(2026, 9, 5)]
        return series, plot_journal.env_rows_by_bucket(series, labels)

    def test_each_day_shows_the_sensor_that_was_there(self):
        _series, out = self._rows()
        self.assertEqual([r['device_id'] for r in out[date(2026, 8, 10)]],
                         ['phys-a'])
        self.assertEqual([r['device_id'] for r in out[date(2026, 8, 25)]],
                         ['api-w'])
        self.assertEqual([r['device_id'] for r in out[date(2026, 9, 5)]],
                         ['phys-b'])

    def test_a_removed_sensor_is_only_asked_about_its_own_period(self):
        """떼어낸 A 에게 뗀 뒤의 기간을 물으면 다른 자리의 값이 섞인다."""
        self._rows()
        a = [(s, e) for dev, s, e in self.asked if dev == 'phys-a']
        self.assertEqual(a, [('2026-08-01T00:00:00Z', '2026-08-20T00:00:00Z')])

    def test_a_deleted_device_still_appears_for_its_past(self):
        """장치를 지워도 제거 표시된 측정 정의로 그 기간의 값을 부른다."""
        Input.query.filter_by(unique_id='phys-a').first().delete()
        for dm in DeviceMeasurements.query.filter_by(device_id='phys-a').all():
            dm.delete()
        _series, out = self._rows()
        self.assertEqual([r['device_id'] for r in out[date(2026, 8, 10)]],
                         ['phys-a'])
