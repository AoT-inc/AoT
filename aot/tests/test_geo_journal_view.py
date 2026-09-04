# coding=utf-8
"""일지(Journal) 2차 수정 회귀 — 집계 정확성·접기·묶기.

실사용 검토에서 나온 결함 일곱을 고정한다. 전부 **순수 계산**이라 DB·InfluxDB·
Flask 앱 컨텍스트 없이 돈다 — 그래야 설치가 깨져도 이 판정이 계속 나온다.

## 왜 이 파일이 필요한가

1차 구현은 샌드박스(`docker exec` 로 함수 직접 호출)로만 검증하고 "완료" 로
판정했는데, 그 방식이 못 잡는 것들이 실제 브라우저에서 줄줄이 나왔다. 그중
**숫자를 만드는 부분**(방향 통계·반올림·접기)은 틀려도 그럴듯한 값이 나와
사람 눈으로는 다시 못 잡는다 — 그래서 소스로 고정한다.
"""
import math
import io
import os
from datetime import date as _date
import sys
import unittest
from datetime import date

sys.path.insert(0, os.path.abspath(
    os.path.join(os.path.dirname(__file__), '..', '..')))

from aot.aot_flask.geo import plot_journal as PJ     # noqa: E402


class TestRounding(unittest.TestCase):
    """반올림 — 안 하면 float repr 이 그대로 화면에 찍힌다."""

    def test_rounds_to_two_decimals(self):
        self.assertEqual(PJ._round(71.26782390873016), 71.27)

    def test_none_stays_none(self):
        """`None`(값 없음)과 0 은 문서에서 전혀 다른 뜻이다."""
        self.assertIsNone(PJ._round(None))

    def test_zero_survives(self):
        """0 을 `or` 폴백으로 지우면 '값이 없다' 로 바뀐다."""
        self.assertEqual(PJ._round(0.0), 0.0)

    def test_garbage_becomes_none_not_crash(self):
        self.assertIsNone(PJ._round('abc'))

    def test_view_time_rounding_repairs_old_journals(self):
        """반올림 이전에 만들어진 일지도 열람 시점에 반올림돼야 한다.

        저장 시점에만 하면 옛 문서는 재생성 말고는 고칠 길이 없다.
        """
        raw = [{'measurement': 'humidity', 'unit': 'percent', 'sensor': 'a',
                'min': 51.86, 'max': 80.04, 'avg': 70.5536326960077,
                'delta': 5.5536326960077, 'samples': 24}]
        groups = PJ.group_env_rows(raw)
        row = groups[0]['sensors'][0]
        self.assertEqual(row['avg'], 70.55)
        self.assertEqual(row['delta'], 5.55)

    def test_view_time_rounding_does_not_mutate_the_snapshot(self):
        """원본은 저장된 스냅샷이다 — 제자리에서 고치면 JSON 컬럼이 더럽혀진다."""
        raw = [{'measurement': 'humidity', 'unit': 'percent', 'sensor': 'a',
                'min': 1.23456, 'max': 2.34567, 'avg': 1.98765, 'samples': 1}]
        PJ.group_env_rows(raw)
        self.assertEqual(raw[0]['avg'], 1.98765)


class TestCircularStats(unittest.TestCase):
    """방향(bearing) — 0 과 360 이 같은 지점이라 선형 통계가 틀린 답을 낸다."""

    def test_bearing_is_declared_circular(self):
        self.assertIn('bearing', PJ.CIRCULAR_UNITS)

    def test_circular_mean_crosses_north(self):
        """350도와 10도의 평균은 180도(선형)가 아니라 0도다.

        **이것이 이 수정의 핵심이다.** 주풍향이 0/360 경계에 걸치면 선형
        평균은 정반대 방향을 내놓는데, 숫자만 보면 알 방법이 없다.
        """
        vals = [350.0, 10.0]
        sx = sum(math.sin(math.radians(v)) for v in vals)
        cx = sum(math.cos(math.radians(v)) for v in vals)
        circular = math.degrees(math.atan2(sx, cx)) % 360.0
        linear = sum(vals) / len(vals)
        self.assertAlmostEqual(circular % 360, 0.0, places=6)
        self.assertAlmostEqual(linear, 180.0)      # 선형은 정반대를 가리킨다

    def test_group_summary_folds_direction_circularly(self):
        """센서를 가로질러 접을 때도 같은 규칙을 써야 한다.

        여기서만 산술로 접으면 대표 줄과 개별 행이 서로 어긋난 값을 말한다.
        """
        rows = [{'measurement': 'direction', 'unit': 'bearing', 'sensor': 'a',
                 'min': None, 'max': None, 'avg': 350.0, 'samples': 10,
                 'circular': True},
                {'measurement': 'direction', 'unit': 'bearing', 'sensor': 'b',
                 'min': None, 'max': None, 'avg': 10.0, 'samples': 10,
                 'circular': True}]
        summary = PJ.group_env_rows(rows)[0]['summary']
        self.assertTrue(summary['circular'])
        self.assertTrue(summary['avg'] < 1.0 or summary['avg'] > 359.0)

    def test_circular_rows_have_no_min_max(self):
        """min/max 는 원형 값에 정의되지 않는다 — 채우면 뜻이 있는 것처럼 보인다.

        실측에서 `min=2.0 / max=359.0` 이 "나침반을 한 바퀴 돌았다" 로 읽혔다.
        """
        rows = [{'measurement': 'direction', 'unit': 'bearing', 'sensor': 'a',
                 'min': None, 'max': None, 'avg': 240.0, 'samples': 5,
                 'circular': True},
                {'measurement': 'direction', 'unit': 'bearing', 'sensor': 'b',
                 'min': None, 'max': None, 'avg': 250.0, 'samples': 5,
                 'circular': True}]
        summary = PJ.group_env_rows(rows)[0]['summary']
        self.assertIsNone(summary['min'])
        self.assertIsNone(summary['max'])


class TestSensorGrouping(unittest.TestCase):
    """센서 묶기 — 시간축만 접고 센서축을 안 접으면 '요약' 이 되지 않는다."""

    @staticmethod
    def _humidity(sensor, avg, samples=24):
        return {'measurement': 'humidity', 'unit': 'percent', 'sensor': sensor,
                'min': avg - 10, 'max': avg + 10, 'avg': avg,
                'samples': samples}

    def test_single_sensor_is_not_folded(self):
        """하나뿐이면 접을 것이 없다 — 괜히 한 겹 더 만들지 않는다."""
        groups = PJ.group_env_rows([self._humidity('a', 70.0)])
        self.assertIsNone(groups[0]['summary'])

    def test_many_sensors_get_one_summary_row(self):
        rows = [self._humidity('s%d' % i, 70.0 + i) for i in range(7)]
        groups = PJ.group_env_rows(rows)
        self.assertEqual(len(groups), 1)
        self.assertEqual(groups[0]['summary']['sensor_count'], 7)

    def test_folding_never_drops_a_sensor(self):
        """§4-3 — 대표를 고르는 것이 아니라 접는 것이다. 값은 전부 남는다."""
        rows = [self._humidity('s%d' % i, 70.0 + i) for i in range(7)]
        groups = PJ.group_env_rows(rows)
        self.assertEqual(len(groups[0]['sensors']), 7)

    def test_summary_extremes_span_the_whole_group(self):
        rows = [self._humidity('a', 50.0), self._humidity('b', 90.0)]
        summary = PJ.group_env_rows(rows)[0]['summary']
        self.assertEqual(summary['min'], 40.0)     # 50-10
        self.assertEqual(summary['max'], 100.0)    # 90+10

    def test_average_is_weighted_by_samples(self):
        """반나절만 기록된 센서가 온종일 기록된 센서를 끌어당기면 안 된다."""
        rows = [self._humidity('full', 80.0, samples=24),
                self._humidity('sparse', 40.0, samples=1)]
        summary = PJ.group_env_rows(rows)[0]['summary']
        self.assertAlmostEqual(summary['avg'], (80.0 * 24 + 40.0) / 25, places=2)

    def test_low_coverage_warning_survives_folding(self):
        """접었다고 경고가 사라지면 접기가 사실을 가리는 장치가 된다."""
        rows = [self._humidity('a', 70.0), self._humidity('b', 71.0)]
        rows[1]['coverage_low'] = True
        summary = PJ.group_env_rows(rows)[0]['summary']
        self.assertTrue(summary['coverage_low'])

    def test_different_measurements_stay_separate(self):
        rows = [self._humidity('a', 70.0),
                {'measurement': 'temperature', 'unit': 'C', 'sensor': 'a',
                 'min': 20.0, 'max': 30.0, 'avg': 25.0, 'samples': 24}]
        groups = PJ.group_env_rows(rows)
        self.assertEqual({g['measurement'] for g in groups},
                         {'humidity', 'temperature'})


class TestEdgeGapCollapse(unittest.TestCase):
    """빈 구간 접기 — 앞뒤만 접고 **가운데는 그대로 둔다**."""

    @staticmethod
    def _bucket(key, empty=True):
        return {'key': key, 'date_label': key, 'env': [] if empty else [{'x': 1}],
                'control': [], 'notes': [], 'empty': empty}

    def test_leading_gap_collapses_to_one_entry(self):
        buckets = ([self._bucket('2026-07-%02d' % d) for d in range(1, 8)]
                   + [self._bucket('2026-07-08', empty=False)])
        out = PJ.collapse_edge_gaps(buckets)
        self.assertEqual(len(out), 2)
        self.assertEqual(out[0]['gap_count'], 7)

    def test_trailing_gap_collapses(self):
        buckets = ([self._bucket('2026-07-01', empty=False)]
                   + [self._bucket('2026-07-%02d' % d) for d in range(2, 6)])
        out = PJ.collapse_edge_gaps(buckets)
        self.assertEqual(len(out), 2)
        self.assertEqual(out[-1]['gap_count'], 4)

    def test_middle_gap_is_preserved(self):
        """값이 있다가 끊겼다가 다시 온 것은 **그 자체가 사실**이다.

        센서 고장·정전이 문서에서 사라지면 안 된다.
        """
        buckets = [self._bucket('2026-07-01', empty=False),
                   self._bucket('2026-07-02'),
                   self._bucket('2026-07-03'),
                   self._bucket('2026-07-04', empty=False)]
        out = PJ.collapse_edge_gaps(buckets)
        self.assertEqual(len(out), 4)
        self.assertTrue(all(b.get('gap_count') is None for b in out))

    def test_all_empty_collapses_to_one(self):
        buckets = [self._bucket('2026-07-%02d' % d) for d in range(1, 11)]
        out = PJ.collapse_edge_gaps(buckets)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]['gap_count'], 10)

    def test_no_gaps_changes_nothing(self):
        buckets = [self._bucket('2026-07-01', empty=False),
                   self._bucket('2026-07-02', empty=False)]
        self.assertEqual(len(PJ.collapse_edge_gaps(buckets)), 2)


class TestFoldBuckets(unittest.TestCase):
    """열람 단위 — 저장된 것보다 **굵게만** 볼 수 있다."""

    @staticmethod
    def _day(key, avg, hours):
        return {'key': key, 'date_label': key, 'empty': False, 'notes': [],
                'env': [{'device_id': 'd1', 'channel': 0, 'sensor': 's',
                         'measurement': 'temperature', 'unit': 'C',
                         'min': avg - 5, 'max': avg + 5, 'avg': avg,
                         'samples': 24, 'expected': 24}],
                'control': [{'output_id': 'o1', 'name': 'heater',
                             'hours': hours}]}

    def test_cannot_go_finer_than_stored(self):
        """주 단위로 저장된 문서에 일 단위를 요구해도 지어내지 않는다."""
        buckets = [self._day('2026-08-03', 20.0, 1.0)]
        out = PJ.fold_buckets(buckets, to='day', granularity='week')
        self.assertEqual(out, buckets)

    def test_same_granularity_is_a_no_op(self):
        buckets = [self._day('2026-08-03', 20.0, 1.0)]
        self.assertEqual(PJ.fold_buckets(buckets, to='day', granularity='day'),
                         buckets)

    def test_days_fold_into_months(self):
        buckets = [self._day('2026-08-%02d' % d, 20.0, 1.0)
                   for d in range(1, 32)]
        out = PJ.fold_buckets(buckets, to='month', granularity='day')
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]['date_label'], '2026-08')

    def test_runtime_is_summed_not_averaged(self):
        """가동시간은 누적량이다 — 평균 내면 '몇 시간 돌았나' 가 사라진다."""
        buckets = [self._day('2026-08-01', 20.0, 2.0),
                   self._day('2026-08-02', 22.0, 3.0)]
        out = PJ.fold_buckets(buckets, to='month', granularity='day')
        self.assertEqual(out[0]['control'][0]['hours'], 5.0)

    def test_extremes_are_exact_across_the_fold(self):
        """min/max 는 접어도 정확하다(결합적) — 근사가 아니다."""
        buckets = [self._day('2026-08-01', 10.0, 1.0),
                   self._day('2026-08-02', 30.0, 1.0)]
        out = PJ.fold_buckets(buckets, to='month', granularity='day')
        env = out[0]['env'][0]
        self.assertEqual(env['min'], 5.0)     # 10-5
        self.assertEqual(env['max'], 35.0)    # 30+5

    def test_notes_are_carried_over_not_dropped(self):
        buckets = [self._day('2026-08-01', 20.0, 1.0),
                   self._day('2026-08-02', 20.0, 1.0)]
        buckets[0]['notes'] = [{'body': 'a'}]
        buckets[1]['notes'] = [{'body': 'b'}]
        out = PJ.fold_buckets(buckets, to='month', granularity='day')
        self.assertEqual(len(out[0]['notes']), 2)

    def test_old_buckets_without_key_fall_back_to_the_label(self):
        """`key` 는 나중에 추가된 필드다 — 옛 문서도 접을 수 있어야 한다."""
        buckets = [{'date_label': '2026-08-01', 'empty': False, 'env': [],
                    'control': [], 'notes': []},
                   {'date_label': '2026-08-02', 'empty': False, 'env': [],
                    'control': [], 'notes': []}]
        out = PJ.fold_buckets(buckets, to='month', granularity='day')
        self.assertEqual(len(out), 1)

    def test_direction_folds_circularly_across_days(self):
        buckets = []
        for day, avg in (('2026-08-01', 350.0), ('2026-08-02', 10.0)):
            b = self._day(day, 20.0, 1.0)
            b['env'] = [{'device_id': 'w', 'channel': 3, 'sensor': 'w',
                         'measurement': 'direction', 'unit': 'bearing',
                         'min': None, 'max': None, 'avg': avg,
                         'samples': 24, 'expected': 24, 'circular': True}]
            buckets.append(b)
        out = PJ.fold_buckets(buckets, to='month', granularity='day')
        avg = out[0]['env'][0]['avg']
        self.assertTrue(avg < 1.0 or avg > 359.0, '선형으로 접혔다: %s' % avg)


class TestStorageGranularity(unittest.TestCase):
    """저장은 되도록 일 단위 — 접는 것은 되돌릴 수 있어도 편 것은 못 되돌린다."""

    def test_long_period_still_stores_daily(self):
        """예전에는 60일만 넘어도 무조건 주간이라 단위를 고를 수 없었다."""
        self.assertEqual(
            PJ.choose_granularity(date(2026, 1, 1), date(2026, 12, 31),
                                  rows=1000),
            'day')

    def test_falls_back_to_weekly_only_over_the_row_budget(self):
        self.assertEqual(
            PJ.choose_granularity(date(2026, 1, 1), date(2026, 12, 31),
                                  rows=PJ.MAX_JOURNAL_ROWS + 1),
            'week')

    def test_gate_and_builder_count_rows_the_same_way(self):
        """따로 세면 게이트를 통과해 놓고 다른 규모로 도는 일이 생긴다."""
        self.assertEqual(PJ._rows_for(10, 1, 3, 30),
                         PJ._rows_for(10, 1, 3, 30))

    def test_circular_channels_cost_more_than_plain_ones(self):
        """원형 채널만 원자료를 읽는다 — 같은 값으로 세면 예산이 거짓이 된다."""
        plain = PJ._rows_for(2, 0, 0, 30)
        circular = PJ._rows_for(2, 2, 0, 30)
        self.assertGreater(circular, plain)


class TestCaveats(unittest.TestCase):
    def test_forced_weekly_has_a_message(self):
        """일간을 못 고르는 이유를 문서가 말해야 한다 — 아니면 고장으로 읽힌다."""
        text = PJ.caveat_text('stored-weekly-too-large')
        self.assertNotEqual(text, 'stored-weekly-too-large')
        self.assertIn('weekly', text.lower())


if __name__ == '__main__':
    unittest.main(verbosity=2)


class TestConvertedChannelsAreReadable(unittest.TestCase):
    """환산(conversion) 채널을 건너뛰지 않는다 — 실측으로 잡은 결함.

    `return_measurement_info` 가 환산 채널의 `measurement` 를 비우는데, 예전에는
    그것을 "조회가 성립하지 않는다" 로 읽고 채널을 통째로 건너뛰었다. **그 전제가
    틀렸다** — `measure` 필터를 빼고 물으면 값이 그대로 나온다(실측: 미러-온습도01
    ch0 F→C 환산, 하루치 1,444포인트). 시스템 정본 `get_last_measurement` 도
    `None` 을 그대로 `measure=` 로 넘긴다.

    대가가 컸다: 육묘장 일지에서 **온도 8채널이 통째로 빠진 채** "10개 채널을
    읽지 못했다" 로만 표시됐다.
    """

    def test_channel_info_returns_four_values(self):
        """표시 이름과 조회 필터가 갈렸다 — 셋만 받으면 조용히 어긋난다."""
        import inspect
        src = inspect.getsource(PJ._channel_info)
        self.assertIn('return channel, unit, display, measurement', src)

    def test_query_uses_the_filter_not_the_display_name(self):
        """환산 채널은 표시 이름으로 물으면 0건이 나온다.

        `measure=measurement`(표시 이름)로 되돌아가면 결함이 그대로 재발한다.
        """
        import inspect
        src = inspect.getsource(PJ.daily_channel_stats)
        self.assertIn('measure=measure_filter', src)
        self.assertNotIn('measure=measurement', src)

    def test_circular_path_also_uses_the_filter(self):
        import inspect
        src = inspect.getsource(PJ._circular_channel_stats)
        self.assertIn('measure=measure_filter', src)


class TestMeasurementLabel(unittest.TestCase):
    """측정 이름의 정본은 `MEASUREMENTS` 하나다."""

    def test_unknown_key_falls_back_to_itself(self):
        self.assertEqual(PJ.measurement_label('no_such_measurement'),
                         'no_such_measurement')

    def test_empty_stays_empty(self):
        self.assertEqual(PJ.measurement_label(''), '')
        self.assertIsNone(PJ.measurement_label(None))

    def test_vpd_is_the_unified_name(self):
        """'Vapor Pressure Deficit' 로 되돌리면 화면마다 다시 갈라진다.

        지도 위젯이 철자 5가지를 'VPD' 로 되돌리는 정규화를 자기 안에 들고
        있던 것이 그 증상이었다.
        """
        from aot.config_devices_units import MEASUREMENTS
        name = MEASUREMENTS['vapor_pressure_deficit']['name']
        self.assertEqual(str(name), 'VPD')

    def test_measurement_key_is_not_renamed(self):
        """`meas` 는 InfluxDB 태그이자 DB 에 저장된 값이다 — 바꾸면 못 읽는다."""
        from aot.config_devices_units import MEASUREMENTS
        self.assertEqual(MEASUREMENTS['vapor_pressure_deficit']['meas'],
                         'vapor_pressure_deficit')

    def test_map_widget_and_journal_share_one_resolver_source(self):
        """둘이 같은 정본(`MEASUREMENTS`)을 읽어야 이름이 갈리지 않는다."""
        import inspect
        from aot.aot_flask.geo.widget import maps
        self.assertIn('MEASUREMENTS',
                      inspect.getsource(maps._measurement_display_name))
        self.assertIn('MEASUREMENTS',
                      inspect.getsource(PJ.measurement_label))

    def test_lazy_name_is_never_truth_tested(self):
        """`lazy_gettext` 를 참/거짓으로 보면 요청 컨텍스트 밖에서 터진다.

        `entry.get('name') or key` 같은 표현이 되살아나면 배경 스레드에서
        예외가 난다 — 그 자리는 예외를 삼키는 경우가 많아 조용히 빈다.
        """
        import inspect
        src = inspect.getsource(PJ.measurement_label)
        self.assertNotIn("entry.get('name') or", src)
        self.assertIn('if name is None', src)


class TestStageSections(unittest.TestCase):
    """단계 절 — 계획표가 아니라 **그 기간의 실제 기록**이어야 한다.

    예전에는 프로그램의 전 단계를 그대로 옮겨 놓기만 했다. 딸기 구획의 5일짜리
    일지에 단계 6개가 실렸는데 **다섯은 문서 기간과 무관한 미래**였고, 겹치는
    하나조차 지침과 목표만 있고 실제로 무슨 일이 있었는지는 없었다.
    """

    @staticmethod
    def _journal():
        def day(key, avg, hours, notes=None):
            return {'key': key, 'date_label': key, 'empty': False,
                    'notes': notes or [],
                    'env': [{'device_id': 'd1', 'channel': 0, 'sensor': 's1',
                             'measurement': 'humidity', 'unit': 'percent',
                             'min': avg - 5, 'max': avg + 5, 'avg': avg,
                             'samples': 24, 'expected': 24, 'target': 65.0,
                             'delta': avg - 65.0}],
                    'control': [{'output_id': 'o1', 'name': 'fan',
                                 'hours': hours}]}
        return {
            'target': {'type': 'plot'},
            'granularity': 'day',
            'stages': [
                {'key': 'a', 'name': '정식기', 'starts_on': '2026-08-01',
                 'ends_on': '2026-08-03', 'guidance': '심는다',
                 'targets': [{'label': 'Humidity', 'value': 65.0}]},
                {'key': 'b', 'name': '수확기', 'starts_on': '2026-12-01',
                 'ends_on': None, 'guidance': '딴다', 'targets': []},
            ],
            'buckets': [
                day('2026-08-01', 70.0, 1.0,
                    [{'time': '2026-08-01T09:00:00', 'title': '점검',
                      'body': '이상 없음',
                      'image_files': ['2026/08/a.jpg']}]),
                day('2026-08-02', 72.0, 2.0),
                day('2026-08-03', 74.0, 3.0),
            ],
        }

    def test_stage_in_period_gets_real_data(self):
        secs = PJ.stage_sections(self._journal())
        first = secs[0]
        self.assertTrue(first['in_period'])
        self.assertEqual(first['days'], 3)
        self.assertTrue(first['env_groups'])
        self.assertTrue(first['control'])

    def test_future_stage_is_marked_not_dropped(self):
        """지우면 '이 작기가 앞으로 어떻게 가는가' 를 문서가 말할 수 없다."""
        secs = PJ.stage_sections(self._journal())
        self.assertEqual(len(secs), 2)
        self.assertFalse(secs[1]['in_period'])
        self.assertEqual(secs[1]['days'], 0)

    def test_stage_range_is_clipped_to_the_journal_period(self):
        """단계가 문서보다 길어도 **문서가 담은 구간**만 말해야 한다.

        프로그램상 단계 끝이 12월이어도, 5일짜리 문서가 "12월까지" 라고 하면
        읽는 사람은 그 기간의 기록이 있다고 읽는다.
        """
        secs = PJ.stage_sections(self._journal())
        self.assertEqual(secs[0]['starts_on'], '2026-08-01')
        self.assertEqual(secs[0]['ends_on'], '2026-08-03')

    def test_runtime_is_summed_over_the_stage(self):
        secs = PJ.stage_sections(self._journal())
        self.assertEqual(secs[0]['control'][0]['hours'], 6.0)   # 1+2+3

    def test_notes_and_photos_are_attached_to_their_stage(self):
        secs = PJ.stage_sections(self._journal())
        self.assertEqual(len(secs[0]['notes']), 1)
        self.assertEqual(len(secs[0]['photos']), 1)
        self.assertEqual(secs[0]['photos'][0]['file'], '2026/08/a.jpg')

    def test_measured_value_sits_next_to_its_target(self):
        """목표만 있고 실측이 없으면 '단계에 아무 내용이 없다' 가 된다."""
        secs = PJ.stage_sections(self._journal())
        row = secs[0]['env_groups'][0]['sensors'][0]
        self.assertIsNotNone(row['avg'])
        self.assertEqual(row['target'], 65.0)

    def test_no_stages_returns_empty(self):
        """대지·구역은 단계가 없다 — 빈 절을 만들지 않는다."""
        self.assertEqual(PJ.stage_sections({'stages': [], 'buckets': []}), [])

    def test_collapsed_gap_buckets_are_not_assigned_to_a_stage(self):
        """접힌 빈 구간은 여러 날을 대표한다 — 시작일만으로 가르면 틀린다."""
        data = self._journal()
        data['buckets'].insert(0, {'key': '2026-07-01', 'date_label':
                                   '2026-07-01 ~ 2026-07-31', 'empty': True,
                                   'gap_count': 31, 'env': [], 'control': [],
                                   'notes': []})
        secs = PJ.stage_sections(data)
        self.assertEqual(secs[0]['days'], 3)

    def test_first_stage_targets_always_count_as_changed(self):
        secs = PJ.stage_sections(self._journal())
        self.assertTrue(secs[0]['targets_changed'])

    def test_identical_consecutive_targets_are_not_changed(self):
        """WP4-3 — 딸기 6단계가 전부 같은 목표(낮/야간 온도·습도·VPD 곡선)를
        반복했다. 이전 단계와 값·단위·when 이 전부 같으면 '바뀌지 않았다'."""
        data = self._journal()
        same = [{'key': 'rh', 'label': 'Humidity', 'value': 65.0,
                'unit': '%', 'when': None}]
        data['stages'] = [
            dict(data['stages'][0], key='a', targets=same),
            dict(data['stages'][0], key='b', starts_on='2026-08-04',
                ends_on='2026-08-06', targets=list(same)),
        ]
        secs = PJ.stage_sections(data)
        self.assertTrue(secs[0]['targets_changed'])
        self.assertFalse(secs[1]['targets_changed'])

    def test_a_changed_value_counts_as_changed(self):
        data = self._journal()
        data['stages'] = [
            dict(data['stages'][0], key='a',
                targets=[{'key': 'rh', 'label': 'Humidity', 'value': 65.0}]),
            dict(data['stages'][0], key='b', starts_on='2026-08-04',
                ends_on='2026-08-06',
                targets=[{'key': 'rh', 'label': 'Humidity', 'value': 70.0}]),
        ]
        secs = PJ.stage_sections(data)
        self.assertTrue(secs[1]['targets_changed'])

    def test_target_order_does_not_count_as_changed(self):
        """비교는 **값**이지 목록 순서가 아니다."""
        data = self._journal()
        a = [{'key': 'temp', 'label': 'Temp', 'value': 25.0},
            {'key': 'rh', 'label': 'Humidity', 'value': 65.0}]
        b = list(reversed(a))
        data['stages'] = [
            dict(data['stages'][0], key='a', targets=a),
            dict(data['stages'][0], key='b', starts_on='2026-08-04',
                ends_on='2026-08-06', targets=b),
        ]
        secs = PJ.stage_sections(data)
        self.assertFalse(secs[1]['targets_changed'])


class TestStageTimelineData(unittest.TestCase):
    """단계 절 머리의 기간 바(§WP4-3) — 반복되던 목표표 대신 막대 하나로
    "지금 전체 일정에서 어디인가" 를 먼저 보여준다."""

    def test_segments_carry_names_and_spans(self):
        stages = [
            {'key': 'a', 'name': '육묘', 'starts_on': '2026-08-01',
            'ends_on': '2026-08-05'},
            {'key': 'b', 'name': '정식', 'starts_on': '2026-08-06',
            'ends_on': '2026-08-20'},
        ]
        out = PJ.stage_timeline_data(stages)
        self.assertEqual(len(out['segments']), 2)
        self.assertEqual(out['segments'][0]['span'], 5)     # 8/1~8/5
        self.assertEqual(out['segments'][1]['span'], 15)    # 8/6~8/20
        self.assertEqual(out['segments'][0]['name'], '육묘')

    def test_open_ended_last_stage_gets_a_guess_not_zero(self):
        """`span` 이 0 이면 `AoTViz.timeline` 이 그 구간을 아예 안 그린다."""
        stages = [{'key': 'a', 'name': '수확', 'starts_on': '2026-08-01',
                  'ends_on': None}]
        out = PJ.stage_timeline_data(stages)
        self.assertGreater(out['segments'][0]['span'], 0)

    def test_empty_stages_returns_no_position(self):
        out = PJ.stage_timeline_data([])
        self.assertEqual(out['segments'], [])
        self.assertIsNone(out['positionPct'])


class TestStageHeadingVocabulary(unittest.TestCase):
    """재배 '단계' 를 시설의 '단'(측창 개폐 단수)과 같은 msgid 로 부르지 않는다."""

    def test_journal_uses_program_stages_msgid(self):
        """`_('Stages')` 는 시설 화면이 이미 쓰고 있어 한국어가 '단' 이다.

        같은 msgid 를 쓰면 재배 단계가 "단" 으로 나온다(실제로 그랬다).
        """
        import io as _io
        path = os.path.join(os.path.dirname(__file__), '..', 'aot_flask',
                            'templates', 'pages', 'geo', 'journal_view.html')
        html = _io.open(os.path.abspath(path), encoding='utf-8').read()
        self.assertIn("{{ _('Program stages') }}", html)
        # ⚠ **렌더 형태**로 본다. 그냥 `_('Stages')` 를 찾으면 "그 msgid 를 쓰지
        #   말라" 고 적어 둔 주석 자체가 걸린다(실제로 걸렸다) — 검사가 자기
        #   경고문을 위반으로 세면 아무도 그 경고를 못 적는다.
        self.assertNotIn("{{ _('Stages') }}", html)


class TestDiagnosticMeasurementFilter(unittest.TestCase):
    """진단 채널은 기본으로 뺀다 — 기르는 환경이 아니라 장비 상태다.

    실측(육묘장·설원6)에서 표의 절반이 전위·신호강도·신호대잡음비였다. 배터리가
    몇 볼트였는지는 장비를 관리할 때 쓰는 값이지, "무엇을 어떻게 길렀나" 를
    넘겨받는 사람이 볼 것이 아니다. 조회 비용도 그만큼 든다(온습도 센서 6채널
    중 3채널이라 **조회의 절반**).
    """

    class _DM(object):
        """`_channel_info` 가 보는 최소한의 모양."""
        def __init__(self, measurement, unit='C', channel=0):
            self.measurement = measurement
            self.unit = unit
            self.channel = channel
            self.conversion_id = None
            self.rescaled_unit = None
            self.rescaled_measurement = None
            self.device_id = 'dev'

    def test_the_three_the_user_named_are_diagnostic(self):
        for key in ('electrical_potential', 'rssi', 'snr'):
            self.assertIn(key, PJ.DIAGNOSTIC_MEASUREMENTS)

    def test_growing_values_are_never_diagnostic(self):
        """온도·습도·VPD 가 여기 들어가면 일지가 통째로 빈다."""
        for key in ('temperature', 'humidity', 'vapor_pressure_deficit',
                    'radiation', 'volumetric_water_content', 'direction'):
            self.assertNotIn(key, PJ.DIAGNOSTIC_MEASUREMENTS)

    def test_default_excludes_diagnostics_only(self):
        self.assertTrue(PJ._wanted_measurement(self._DM('temperature'), None))
        self.assertFalse(PJ._wanted_measurement(self._DM('rssi'), None))

    def test_unknown_measurement_defaults_to_included(self):
        """새 measurement 를 기본 제외로 하면 새 환경 값이 조용히 사라진다.

        없는 것과 안 실은 것은 문서에서 구별되지 않으므로, **보이는 쪽**이
        안전한 실패다.
        """
        self.assertTrue(
            PJ._wanted_measurement(self._DM('brand_new_measurement'), None))

    def test_explicit_selection_can_opt_diagnostics_back_in(self):
        """기본값일 뿐 금지가 아니다 — 장비 점검용 일지를 만들 수도 있다."""
        self.assertTrue(
            PJ._wanted_measurement(self._DM('rssi'), {'rssi', 'temperature'}))

    def test_explicit_selection_excludes_what_is_not_listed(self):
        self.assertFalse(
            PJ._wanted_measurement(self._DM('humidity'), {'temperature'}))

    def test_channel_with_no_usable_unit_is_never_included(self):
        dm = self._DM('temperature', unit=None)
        self.assertFalse(PJ._wanted_measurement(dm, None))
        self.assertFalse(PJ._wanted_measurement(dm, {'temperature'}))

    def test_scoped_selection_does_not_leak_across_scopes(self):
        """구획에 실내 센서와 기상대가 둘 다 있으면 이름만으로 걸러선 안 된다.

        실측(사용자 보고, 2026-09-03): 온도가 실내·기상 양쪽에 있는 구획에서
        기상 쪽 온도만 빼려고 체크를 풀면(`'outdoor:temperature'` 만 선택),
        이름(`temperature`)만으로 걸렀던 예전 판정은 실내 온도까지 함께
        뺐다. 스코프를 함께 봐야 한쪽만 정확히 걸러진다.
        """
        dm = self._DM('temperature')
        wanted = {'outdoor:temperature'}
        self.assertTrue(PJ._wanted_measurement(dm, wanted, scope='outdoor'))
        self.assertFalse(PJ._wanted_measurement(dm, wanted, scope='indoor'))

    def test_unscoped_selection_still_applies_to_every_scope(self):
        """평문 이름은 스코프를 가르지 않는 대상(zone/site, 한쪽뿐인 구획)의
        선택값이 예전과 같이 계속 동작하게 하는 하위호환이다."""
        dm = self._DM('temperature')
        wanted = {'temperature'}
        self.assertTrue(PJ._wanted_measurement(dm, wanted, scope='outdoor'))
        self.assertTrue(PJ._wanted_measurement(dm, wanted, scope='indoor'))
        self.assertTrue(PJ._wanted_measurement(dm, wanted, scope=None))

    def test_measurement_groups_split_scope_into_prefixed_keys(self):
        """실내·기상이 둘 다 있을 때만 가른다 — 한쪽뿐이면 평문 키 그대로다."""
        import inspect
        src = inspect.getsource(PJ.available_measurement_groups)
        self.assertIn("'%s:%s'", src)          # 스코프 접두 키 조립
        self.assertIn('split', src)

    def test_env_series_and_build_target_pass_scope_through(self):
        """`_wanted_measurement` 을 스코프 없이 부르는 자리가 되살아나면
        `test_scoped_selection_does_not_leak_across_scopes` 가 지키는 계약이
        조용히 다시 새게 된다 — 호출부에서도 함께 고정한다."""
        import inspect
        src = inspect.getsource(PJ.env_channel_series)
        self.assertIn('_wanted_measurement(dm, wanted, scope=scope)', src)
        src2 = inspect.getsource(PJ.build_journal_for_target)
        self.assertIn('_wanted_measurement(dm, wanted, scope=_scope)', src2)

    def test_caveat_names_what_was_left_out(self):
        """무엇을 뺐는지 문서가 말해야 한다 — 없는 것과 구별되지 않는다."""
        text = PJ.caveat_text('measurements-excluded:rssi,snr')
        self.assertNotIn('measurements-excluded', text)
        self.assertIn('rssi', text.lower() + ' ')   # 이름이 어떤 형태로든 실린다

    def test_gate_counts_only_what_will_be_queried(self):
        """게이트가 안 실을 채널까지 세면 통과할 요청이 거절된다."""
        import inspect
        src = inspect.getsource(PJ.count_channels_detail)
        self.assertIn('_wanted_measurement(dm, wanted)', src)

    def test_selection_reaches_the_query_layer(self):
        """화면에서 거르면 조회 비용은 그대로 든다 — 여기서 걸러야 한다."""
        import inspect
        src = inspect.getsource(PJ.env_channel_series)
        self.assertIn('_wanted_measurement', src)


class TestDownloadNaming(unittest.TestCase):
    """내려받은 파일은 **열어 보지 않고도** 골라낼 수 있어야 한다.

    예전에는 `journal-7944978c.md`(uuid 앞자리)였고 PDF 는 브라우저가
    `document.title`("AoT 설원6 - AoT 26.09.01")에서 따 갔다. 여러 작기를
    받으면 무엇이 무엇인지 알 수 없다.
    """

    class _Row(object):
        def __init__(self, title, start):
            self.title = title
            self.period_start = start

    def _stem(self, title, start=date(2026, 8, 26)):
        from aot.aot_flask import routes_geo_journal as R
        return R._download_stem(self._Row(title, start))

    def test_year_month_then_name(self):
        self.assertEqual(self._stem('설원6'), '202608_설원6')

    def test_month_comes_from_the_period_not_today(self):
        """같은 작기를 나중에 다시 뽑아도 같은 이름이어야 정렬이 맞는다."""
        self.assertTrue(self._stem('설원6', date(2026, 3, 1)).startswith('202603_'))

    def test_korean_is_kept(self):
        """로마자로 옮기면 사람이 못 알아본다 — 대상 이름이 한국어인 게 정상이다."""
        self.assertIn('육묘장', self._stem('육묘장 구획'))

    def test_path_separators_cannot_survive(self):
        """`/` 가 남으면 저장이 엉뚱한 경로로 가거나 실패한다."""
        stem = self._stem('a/b\\c:d*e?f"g<h>i|j')
        for bad in '/\\:*?"<>|':
            self.assertNotIn(bad, stem)

    def test_spaces_become_underscores(self):
        self.assertNotIn(' ', self._stem('  두   칸  '))

    def test_empty_title_still_yields_a_name(self):
        self.assertEqual(self._stem(''), '202608_journal')

    def test_disposition_carries_utf8_and_an_ascii_fallback(self):
        """HTTP 헤더는 latin-1 이라 한글을 그대로 실으면 깨지거나 죽는다."""
        from aot.aot_flask import routes_geo_journal as R
        header = R._disposition('202608_[관찰]_육묘장', 'md')
        self.assertIn("filename*=UTF-8''", header)
        self.assertIn('filename="', header)
        # 폴백은 ASCII 로만 이뤄져야 한다(헤더가 latin-1 이다).
        ascii_part = header.split('filename="')[1].split('"')[0]
        self.assertTrue(ascii_part.isascii())
        self.assertNotIn('__', ascii_part)      # 기호 자리가 접혀 있다

    def test_ascii_fallback_is_never_empty(self):
        """이름이 통째로 비-ASCII 면 폴백이 빈 문자열이 되어 헤더가 깨진다."""
        from aot.aot_flask import routes_geo_journal as R
        header = R._disposition('육묘장', 'json')
        ascii_part = header.split('filename="')[1].split('"')[0]
        self.assertTrue(ascii_part.replace('.json', ''))


class TestPrintLayout(unittest.TestCase):
    """출력물은 화면과 다른 물건이다 — 하이퍼링크는 종이에 아무것도 안 남긴다."""

    @staticmethod
    def _html():
        import io as _io
        path = os.path.join(os.path.dirname(__file__), '..', 'aot_flask',
                            'templates', 'pages', 'geo', 'journal_view.html')
        return _io.open(os.path.abspath(path), encoding='utf-8').read()

    def _print_css(self):
        """인쇄 블록(@media print)만 — 주석은 뺀다."""
        import re
        html = self._html()
        block = html[html.index('@media print'):html.index('</style>')]
        return re.sub(r'/\*.*?\*/', '', block, flags=re.S)

    def _screen_css(self):
        """화면용 선언부만 — 인쇄와 주석은 뺀다."""
        import re
        html = self._html()
        css = html[html.index('<style>'):html.index('@media print')]
        return re.sub(r'/\*.*?\*/', '', css, flags=re.S)

    def test_each_section_starts_on_a_new_page(self):
        """현황–단계–일자별 기록이 이어 붙으면 어디서 끝났는지 알 수 없다."""
        html = self._html()
        self.assertIn('.aot-journal-section { page-break-before: always; }', html)
        self.assertEqual(html.count('<section class="aot-journal-section">'), 3)

    def test_page_size_and_margins_are_fixed(self):
        """브라우저 기본 여백은 제각각이라 같은 문서가 사람마다 다르게 나온다."""
        self.assertIn('@page { size: A4;', self._html())

    def test_table_headers_repeat_across_pages(self):
        """표 머리가 넘어가면 그 표가 무슨 표인지 알 수 없어진다."""
        self.assertIn('display: table-header-group', self._html())

    def test_guide_page_replaces_the_bare_toc_in_print(self):
        """낱말 네 개로 한 장을 쓰던 자리다 — 인쇄에서는 안내가 대신한다."""
        html = self._html()
        self.assertIn('aot-journal-guide', html)
        # 목차와 **그 제목**까지 숨긴다 — 제목만 남으면 빈 절이 된다.
        for cls in ('.aot-journal-toc,', '.aot-journal-toc-title,',
                    '.aot-journal-gran { display: none !important; }'):
            self.assertIn(cls, html)

    def test_cover_leaves_slack_below_the_printable_height(self):
        """A4 의 인쇄 높이는 297 − 18 − 16 = 263mm 다. **딱 맞추면 안 된다** —
        mm→px 환산이 993.9 대 994.0 처럼 1px 어긋나기만 해도 상자가 넘쳐
        마지막 줄(생성 시각)이 다음 장으로 밀린다(실측 2026-09-04).
        반대로 너무 짧으면(예전 235mm) 그 줄이 페이지 중간에 뜬다."""
        import re
        html = self._html()
        m = re.search(r'\.aot-journal-cover \{[^}]*min-height:\s*(\d+)mm', html,
                      re.S)
        self.assertIsNotNone(m, '표지 min-height 를 찾지 못했다')
        mm = int(m.group(1))
        self.assertLess(mm, 263, '인쇄 높이와 같거나 크면 다음 장으로 밀린다')
        self.assertGreaterEqual(mm, 255, '너무 짧으면 생성 시각이 중간에 뜬다')

    def test_cover_centres_the_title_and_pins_the_footer(self):
        """고정 여백으로 밀면 종이·배율이 달라질 때마다 균형이 깨진다."""
        import re
        # ⚠ **인쇄 블록 안에서 찾는다.** 같은 선택자가 화면에도 있어(표지
        #   부제·생성 시각은 화면에서도 쓴다) 앞쪽 규칙을 집으면 엉뚱한 값을
        #   본다 — 처음에 그렇게 써서 검사가 헛돌았다.
        html = self._html()
        print_block = html[html.index('@media print'):html.index('</style>')]
        head = re.search(r'\.aot-journal-cover-head \{([^}]*)\}', print_block)
        self.assertIsNotNone(head)
        self.assertIn('margin-top: auto', head.group(1))
        self.assertIn('margin-bottom: auto', head.group(1))
        meta = re.search(r'\.aot-journal-cover-meta \{([^}]*)\}', print_block,
                         re.S)
        self.assertIsNotNone(meta)
        self.assertIn('margin-top: 0', meta.group(1))

    def test_map_comes_before_the_overview_facts(self):
        """그림을 먼저 보고 글을 읽는 것이 자연스럽다(지적 2026-09-04).
        제목은 `Map`("지도") — 이미 있는 msgid 를 쓴다."""
        html = self._html()
        head = html.index("id=\"journal-overview\"")
        mapi = html.index("{{ _('Map') }}", head)
        facts = html.index("{{ _('Details') }}", head)
        self.assertLess(mapi, facts, '지도가 사실 목록보다 아래에 있다')
        # 제목 없는 상자를 남기지 않는다 — 절 제목은 이제 지도가 받는다.
        self.assertIn("<h3 class=\"aot-modal-group-title\">{{ _('Details') }}</h3>",
                      html)
        self.assertNotIn("_('Location on the map')", html)

    def test_layer_panel_is_the_design_pages_own(self):
        """레이어 패널은 **편집 지도(`/geo/design`)의 것을 그대로 쓴다** —
        바탕(래스터·벡터·벡터 채널)과 오버레이를 고를 수 있어야 한다
        (지적 2026-09-04: "베이스, 오버레이 지도를 선택할 수 있어야").

        ⚠ 공용 `AoTMapCustomControls.createLayerControl` 은 이름만 비슷한
          **다른 물건**이다 — 장비·구조·경계 같은 내용 레이어를 켜고 끄는
          것이라 바탕 지도를 고를 수 없다. 그것을 붙였다가 되돌렸다.
        ⚠ 번들이 아니라 **원본 파일**을 싣는다 — `geo-design` 번들은 스코프에
          갇혀 `AoTGeoUI` 를 밖에서 못 쓴다."""
        html = self._html()
        self.assertIn("filename='js/geo/design/aot-geo-ui.js'", html)
        self.assertNotIn("filename='js/geo/aot-map-custom-controls.js'", html)
        # 패널이 자기 상자를 붙일 자리와, 편집 지도와 같은 도구 단추.
        self.assertIn('id="geo-design-wrapper"', html)
        self.assertIn('class="btn btn-white btn-circle" id="tool-layers"', html)

    def test_zoom_and_compass_sit_left_like_the_design_page(self):
        """확대/축소·나침반은 **왼쪽 묶음**이다 — 편집 지도와 같은 자리·같은
        마크업(지적 2026-09-04). maplibre 기본 컨트롤을 오른쪽 위에 그대로
        세우면 이 앱의 지도가 아닌 것이 된다.

        편집 지도가 하는 그대로: 네이티브 컨트롤은 **나침반만** 만들어
        (`showZoom: false`) 그 묶음 안으로 옮겨 붙이고, 확대/축소는 앱 단추가
        맡는다."""
        html = self._html()
        self.assertIn('class="map-tools-left"', html)
        for bid in ('tool-zoom-in', 'tool-zoom-out'):
            self.assertIn('id="%s"' % bid, html)
        js = self._map_js()
        self.assertIn('showCompass: true, showZoom: false', js)
        self.assertIn(".map-tools-left'", js)
        # 오른쪽 위에 기본 컨트롤을 세우지 않는다 — 옮겨 붙이기만 한다.
        self.assertNotIn('addControl(new maplibregl.NavigationControl', js)
        self.assertIn('navCtrl.onAdd(map)', js)

    @staticmethod
    def _map_js():
        import io as _io
        path = os.path.join(os.path.dirname(__file__), '..', 'aot_flask',
                            'static', 'js', 'geo', 'journal-map.js')
        return _io.open(os.path.abspath(path), encoding='utf-8').read()

    def test_document_wording_is_not_crop_only(self):
        """일지의 대상은 식생만이 아니다 — 축사·시설 구획도 이 문서를 낸다.
        그래서 화면에 나가는 문구에 **작물에만 통하는 말**을 쓰지 않는다
        (지적 2026-09-04: "작기 일정", "재배 프로그램", "재배 목표").

        ⚠ 예외는 **지표 이름 자체**뿐이다(`Growing degree days` = 적산온도).
          그것은 이 저장소가 지은 말이 아니라 그 측정값의 표준 이름이고,
          용어집의 GDD·DLI·VPD 설명(plot_journal.py)도 그 지표가 실제로 있을
          때만 나오므로 식물 어휘가 맞다."""
        import re
        html = self._html()
        ids = re.findall(r"_\(\s*'((?:[^'\\]|\\.)*)'", html)
        allowed = {'Growing degree days'}
        bad = []
        for msgid in ids:
            if msgid in allowed:
                continue
            low = msgid.lower()
            for word in ('growing', 'crop', 'harvest', 'sowing', 'cultivat'):
                if word in low:
                    bad.append((word, msgid[:60]))
        self.assertEqual(bad, [], '작물 전용 어휘가 문구에 남아 있다: %r' % bad)

    def test_guide_text_all_starts_at_one_left_rule(self):
        """안내 절(2쪽)에서 **왼쪽에서 시작하는 글자는 전부 같은 x** 다.

        절 제목은 공용 규칙이 `padding-left: 16px !important` 로 미는데, 이 절의
        나머지(소제목·목차·용어·설명·주의)는 저마다 0 이거나 4mm 여서 기준선이
        넷이었다(지적 2026-09-04). 제목을 끌어내리는 대신 나머지를 그 16px 에
        맞춘다 — 문서의 다른 절도 전부 그 선을 쓴다."""
        block = self._print_css()
        rule = block[block.index('.aot-journal-guide h3,'):]
        rule = rule[:rule.index('}')]
        for sel in ('.aot-journal-guide p', '.aot-journal-guide dl',
                    '.aot-journal-guide ul'):
            self.assertIn(sel, rule, '%s 가 기준선 규칙에서 빠졌다' % sel)
        self.assertIn('padding-left: 16px', rule)
        # 설명문을 들여쓰면 그 층만 다른 x 를 갖는다.
        dd = block[block.index('.aot-journal-guide dd {'):]
        dd = dd[:dd.index('}')]
        self.assertIn('margin: 0;', dd)
        self.assertNotIn('4mm', dd)
        # 글머리 기호가 붙으면 그 줄만 글자 시작이 밀린다.
        self.assertIn('.aot-journal-guide ul { list-style: none; }', block)
        # 인라인 여백을 다시 들이지 않는다.
        self.assertNotIn('style="padding-left:1.1rem;"', self._html())

    def test_pages_break_between_stages_not_inside_one(self):
        """같은 단계의 일/주/월이 장 경계에 갈리면서 정작 **다른 단계**와는 한
        장에 붙어 나왔다(지적 2026-09-04). 각 단계를 새 장에서 시작한다 —
        인접 선택자라 **앞에 단계가 있을 때만** 걸려, 첫 단계는 절 제목 바로
        뒤에 남는다."""
        block = self._print_css()
        self.assertIn('.aot-journal-stage + .aot-modal-group-title', block)
        rule = block[block.index('.aot-journal-stage + .aot-modal-group-title'):]
        rule = rule[:rule.index('}')]
        self.assertIn('page-break-before: always', rule)
        # 한 단계 안에서는 잘리지 말아야 할 최소 단위만 지킨다.
        self.assertIn('.aot-journal-stage { page-break-inside: auto; }', block)

    def test_stages_are_separated_on_screen(self):
        """단계는 상자가 아니라 제목이 나누는 묶음이라, 같은 꼴의 제목이
        줄줄이 이어지면 어디서 한 단계가 끝났는지 보이지 않는다."""
        css = self._screen_css()
        self.assertIn('.aot-journal-stage + .aot-modal-group-title', css)
        rule = css[css.index('.aot-journal-stage + .aot-modal-group-title'):]
        rule = rule[:rule.index('}')]
        self.assertIn('border-top', rule)
        self.assertIn('margin-top', rule)

    def test_no_hardcoded_page_numbers(self):
        """HTML/CSS 로는 실제 쪽 수를 셀 수 없다 — 상수를 박으면 거짓말이 된다."""
        html = self._html()
        self.assertNotIn("_('page 3')", html)

    def test_pdf_filename_is_restored_after_printing(self):
        """되돌리지 않으면 탭 제목이 파일명인 채로 남는다."""
        html = self._html()
        self.assertIn("afterprint", html)
        self.assertIn('_restoreTitle', html)


class TestOutdoorWeatherIsSeparate(unittest.TestCase):
    """기상(실외)은 실내 센서와 **겨루지도 섞이지도** 않는다.

    ## 겨루지 않는다

    `sensors_for_plot` 의 실내 체인은 배타적이다(구획 안 → 동 → 시설 → 구역,
    처음 비지 않은 데서 멈춘다). 일사·강우는 대지에 하나 있는 기상대가 재므로,
    구획 안에 온습도계가 있다는 이유로 빠지면 안 된다 — 실측에서
    `[관찰] 육묘장 구획` 이 같은 대지의 미러-기상대를 못 보고 있었다.

    ## 섞이지 않는다

    기상대도 온·습도를 낸다. 실내와 같은 그룹으로 접히면 구획의 온도와 외기가
    하나의 평균이 되는데, 그것이 이 저장소에 이미 실측으로 남은 실패(*공기 온도
    목표가 토양 센서 값과 비교된 건*)와 같은 모양이다.
    """

    @staticmethod
    def _row(sensor, measurement, avg, scope):
        return {'sensor': sensor, 'measurement': measurement, 'unit': 'C',
                'min': avg - 2, 'max': avg + 2, 'avg': avg, 'samples': 24,
                'scope': scope}

    def test_indoor_and_outdoor_never_share_a_group(self):
        rows = [self._row('실내1', 'temperature', 28.0, 'indoor'),
                self._row('실내2', 'temperature', 28.5, 'indoor'),
                self._row('기상대', 'temperature', 33.0, 'outdoor')]
        groups = PJ.group_env_rows(rows)
        scopes = sorted(g['scope'] for g in groups)
        self.assertEqual(scopes, ['indoor', 'outdoor'])
        indoor = [g for g in groups if g['scope'] == 'indoor'][0]
        self.assertEqual(indoor['summary']['sensor_count'], 2)   # 기상대 미포함

    def test_outdoor_value_does_not_move_the_indoor_average(self):
        """외기가 실내 평균을 끌어당기면 그 숫자는 아무 뜻도 없어진다."""
        rows = [self._row('실내1', 'temperature', 28.0, 'indoor'),
                self._row('실내2', 'temperature', 28.0, 'indoor'),
                self._row('기상대', 'temperature', 40.0, 'outdoor')]
        indoor = [g for g in PJ.group_env_rows(rows)
                  if g['scope'] == 'indoor'][0]
        self.assertEqual(indoor['summary']['avg'], 28.0)

    def test_missing_scope_defaults_to_indoor(self):
        """scope 를 안 실은 옛 일지도 예전처럼 보여야 한다."""
        rows = [{'sensor': 'a', 'measurement': 'temperature', 'unit': 'C',
                 'min': 1, 'max': 2, 'avg': 1.5, 'samples': 1}]
        self.assertEqual(PJ.group_env_rows(rows)[0]['scope'], 'indoor')

    def test_folding_keeps_scopes_apart(self):
        """접을 때 scope 를 키에서 빼면 실내·실외가 한 행으로 합쳐진다."""
        def day(key):
            return {'key': key, 'date_label': key, 'empty': False, 'notes': [],
                    'control': [],
                    'env': [dict(self._row('실내', 'temperature', 28.0, 'indoor'),
                                 device_id='in', channel=0, expected=24),
                            dict(self._row('기상대', 'temperature', 33.0, 'outdoor'),
                                 device_id='out', channel=0, expected=24)]}
        out = PJ.fold_buckets([day('2026-08-01'), day('2026-08-02')],
                              to='month', granularity='day')
        scopes = sorted(e.get('scope') for e in out[0]['env'])
        self.assertEqual(scopes, ['indoor', 'outdoor'])

    def test_weather_markers_are_things_a_plot_never_measures(self):
        """표식이 넓으면 엉뚱한 장치가 기상대로 잡히고 그 값 전부가 실외로 온다.

        `speed` 는 팬 회전수일 수 있고 `light` 는 실내 PAR 일 수 있어 뺐다.
        """
        from aot.aot_flask.geo import device_membership as M
        for key in ('radiation', 'precipitation', 'rain', 'snowfall'):
            self.assertIn(key, M.WEATHER_MARKER_MEASUREMENTS)
        for key in ('speed', 'light', 'temperature', 'humidity',
                    'vapor_pressure_deficit'):
            self.assertNotIn(key, M.WEATHER_MARKER_MEASUREMENTS)

    def test_resolver_reports_which_rule_it_used(self):
        """'사람이 지정' 과 '시스템이 추론' 은 화면이 구분해 말할 수 있어야 한다."""
        import inspect
        from aot.aot_flask.geo import device_membership as M
        src = inspect.getsource(M.weather_device_ids)
        self.assertIn("'bound'", src)
        self.assertIn("'inferred'", src)
        self.assertIn("'none'", src)

    def test_weather_is_added_not_a_fallback(self):
        """실내 체인의 폴백 자리에 끼우면 구획 안 센서가 있을 때 또 사라진다."""
        import inspect
        from aot.aot_flask.geo import plot_context
        src = inspect.getsource(plot_context.sensors_for_plot)
        # 실내 우선순위 체인에 from_weather 가 끼어 있으면 안 된다.
        chain = src.split("ids = (list(found.get('in_plot')")
        self.assertNotIn('from_weather', src.split('return {')[0])

    def test_journal_does_not_double_count_a_weather_device(self):
        """같은 장치가 실내·실외 양쪽에 잡히면 표에 두 번 나온다."""
        import inspect
        src = inspect.getsource(PJ._plot_sensor_ids)
        self.assertIn('- outdoor', src)


class TestWeatherReadability(unittest.TestCase):
    """기상 값은 **사람이 쓸 수 있는 형태**로 낸다."""

    def test_prevailing_sector_not_a_mean_angle(self):
        """평균 각도는 쓸모가 없다 — 실측 241.5도가 아무것도 말해 주지 않았다."""
        import inspect
        src = inspect.getsource(PJ._circular_channel_stats)
        self.assertIn("'sector'", src)
        self.assertIn("'sector_pct'", src)

    def test_compass_covers_sixteen_points(self):
        self.assertEqual(len(PJ.COMPASS_16), 16)
        self.assertEqual(PJ.COMPASS_16[0], 'N')
        self.assertEqual(PJ.COMPASS_16[8], 'S')

    def test_compass_label_rejects_out_of_range(self):
        """범위를 벗어난 번호에 엉뚱한 방위를 돌려주면 조용히 틀린다."""
        self.assertIsNone(PJ.compass_label(16))
        self.assertIsNone(PJ.compass_label(-1))
        self.assertIsNone(PJ.compass_label(None))
        self.assertIsNone(PJ.compass_label('북'))

    def test_sector_index_maps_north_across_the_wrap(self):
        """359도와 1도는 **같은 북(0번)** 이어야 한다 — 경계에서 갈리면 안 된다."""
        import math
        def idx(ang):
            return int((ang + 11.25) % 360.0 // 22.5)
        self.assertEqual(idx(359.0), 0)
        self.assertEqual(idx(1.0), 0)
        self.assertEqual(idx(0.0), 0)
        # 남서(SW)는 225도 언저리 = 10번
        self.assertEqual(idx(225.0), 10)

    def test_outdoor_renames_only_in_weather_context(self):
        """`speed` 정의를 바꾸면 팬 회전수까지 '풍속' 이 된다 — 문맥에서만 바꾼다."""
        self.assertEqual(PJ.measurement_label('speed', 'indoor'),
                         PJ.measurement_label('speed'))
        self.assertNotEqual(PJ.measurement_label('speed', 'outdoor'),
                            PJ.measurement_label('speed', 'indoor'))

    def test_outdoor_rename_list_is_narrow(self):
        """온도·습도까지 바꾸면 실내와 다른 이름이 되어 대조가 안 된다."""
        self.assertEqual(set(PJ._OUTDOOR_LABELS), {'speed', 'direction'})


class TestSharedModalStyles(unittest.TestCase):
    """여백·제목 스타일을 **직접 만들지 않는다** — AoT 현대화 모달이 이미 준다.

    `.aot-modal-container` 는 `padding: 0 16px` 로 **좌우를 함께** 주고,
    `.aot-modal-section-title`/`.aot-modal-group-title` 에는 "박스 내부 레이블과
    정렬 통일 (16px)" 이라는 주석까지 붙어 있다. 같은 것을 이 파일에서 다시
    만들면 공용 값이 바뀔 때 이 화면만 어긋난다.
    """

    @staticmethod
    def _html(name='journal_view.html'):
        import io as _io
        path = os.path.join(os.path.dirname(__file__), '..', 'aot_flask',
                            'templates', 'pages', 'geo', name)
        return _io.open(os.path.abspath(path), encoding='utf-8').read()

    def test_no_private_inset_variable(self):
        """`--aot-journal-inset` 같은 자체 상수를 되살리지 말 것."""
        for name in ('journal_view.html', 'journal.html'):
            self.assertNotIn('--aot-journal-inset', self._html(name),
                             '%s 에 자체 여백 상수가 되살아났다' % name)

    def test_titles_use_the_shared_classes(self):
        html = self._html()
        self.assertIn('aot-modal-section-title', html)
        self.assertIn('aot-modal-group-title', html)

    def test_body_text_uses_the_shared_class(self):
        self.assertIn('aot-modal-body-text', self._html())

    def test_log_content_sits_in_a_container(self):
        """좌우 여백은 컨테이너에서 온다 — 직접 padding 을 주지 않는다."""
        html = self._html()
        self.assertIn('aot-journal-bucket', html)
        self.assertIn('aot-modal-container', html)


class TestDailyLogRelayout(unittest.TestCase):
    """일자별 기록 재조판 — WP4-2.

    노트(사람의 행위)가 반복되는 수치 표보다 먼저, 본문 크기로 나와야
    한다는 것이 실사용 검토의 핵심 지적이었다. 소스 검사로 순서·크기·
    인쇄 강제를 고정한다(렌더링에는 DB·Flask 컨텍스트가 필요해 이 파일의
    다른 클래스들과 같은 방식을 쓴다).
    """

    @staticmethod
    def _html():
        import io as _io
        path = os.path.join(os.path.dirname(__file__), '..', 'aot_flask',
                            'templates', 'pages', 'geo', 'journal_view.html')
        return _io.open(os.path.abspath(path), encoding='utf-8').read()

    def test_notes_come_before_the_measurement_table(self):
        html = self._html()
        notes_at = html.index('class="aot-modal-body-text aot-journal-notes-list"')
        table_at = html.index('<table class="table table-sm aot-journal-table">')
        self.assertLess(notes_at, table_at,
                        '노트가 측정값 표보다 먼저 나와야 한다')

    def test_notes_are_not_shrunk_with_small(self):
        """예전에는 `<ul class="small">` 로 노트를 각주 크기로 냈다."""
        self.assertNotIn('<ul class="small">', self._html())

    def test_table_is_shown_immediately_not_wrapped_in_details(self):
        """실사용 지적: 표를 통째로 `<details>` 로 접고 위에 작은 글씨
        요약만 뒀더니 **아무도 읽지 않았다.** 표는 표로 두고, 줄이는 것은
        행 단위로 한다."""
        html = self._html()
        self.assertNotIn('aot-journal-detail', html)
        self.assertNotIn('aot-journal-anomalies', html,
                         '작은 글씨 특이사항 요약은 표로 대체됐다')

    def test_extra_rows_are_hidden_on_screen_and_forced_in_print(self):
        """접는 것이 사실을 지우지 않는다 — 종이는 펼칠 수 없으므로 인쇄에는
        전부 나온다. `<details>` 와 달리 행은 **CSS 한 줄로** 강제되므로
        `beforeprint` 스크립트가 필요 없다."""
        html = self._html()
        self.assertIn('.aot-journal-row-extra { display: none; }', html)
        self.assertIn('.aot-journal-row-extra { display: table-row !important; }',
                      html)
        # 펼침 버튼만 숨기면 그 행이 빈 줄로 남는다.
        self.assertIn('.aot-journal-more-row { display: none !important; }', html)
        self.assertNotIn("addEventListener('beforeprint'", html)

    def test_extra_rows_have_an_in_table_toggle(self):
        html = self._html()
        self.assertIn('aot-journal-more', html)
        self.assertIn("_('Show %(n)s more', n=extra_count)", html)
        # 세는 단위는 measurement 그룹이지 행이 아니다(한 그룹이 여러 센서
        # 행을 낳는다).
        self.assertIn("rejectattr('primary')", html)

    def test_sub_row_needs_both_toggles_open(self):
        """한 행에 `.aot-journal-sub`(센서 펼침)와 `.aot-journal-row-extra`
        가 함께 걸릴 수 있다 — 나머지를 접은 채 센서만 펼치면 숨은 그룹의
        센서 행이 튀어나온다."""
        html = self._html()
        self.assertIn('.aot-journal-row-extra.aot-journal-sub.is-open'
                      ':not(.is-open-extra) { display: none; }', html)
        self.assertIn('.aot-journal-row-extra.aot-journal-sub.is-open-extra'
                      ':not(.is-open) { display: none; }', html)

    def test_table_more_handler_ignores_the_chart_more_button(self):
        """실측: 범위 도표의 "나머지 보기" 버튼도 같은 모양을 쓰는데, 표용
        처리기가 그것까지 집어가 `btn.dataset.less`(없음)로 **글자를
        지웠다**(펼친 뒤 버튼이 빈칸). 표 버튼만 `data-extra` 를 갖는다."""
        self.assertIn(".aot-journal-more[data-extra]", self._html())

    def test_group_toggle_handler_ignores_the_more_button(self):
        """"나머지 보기" 버튼도 `.aot-journal-toggle` 모양을 쓴다 —
        `data-group` 이 없으므로 센서 펼침 처리기가 집어 가면 안 된다."""
        self.assertIn(".aot-journal-toggle[data-group]", self._html())

    def test_delta_sign_is_explicit(self):
        """초과·미달을 부호로 구분한다 — 색을 늘리지 않는다(WP4-4)."""
        self.assertIn("'%+g'", self._html())

    def test_delta_sign_is_not_doubled_by_css(self):
        """실측(라이브 확인 중 발견): `%+g` 가 이미 부호를 내는데
        `.aot-journal-delta-pos::before { content: '+' }` 가 하나 더 붙여
        "+(Δ +1.94)" 처럼 두 번 나왔다."""
        self.assertNotIn("aot-journal-delta-pos::before", self._html())

    def test_single_sensor_row_uses_the_groups_label_not_its_own(self):
        """실측(라이브 확인 중 발견): 단일 센서 그룹(가장 흔한 경우 —
        `grp.summary` 가 없다)의 값 칸이 `e.measurement_label` 을 썼는데,
        그 필드는 `group_env_rows` 가 채널 이름만으로 미리 채운 캐시라
        "기상대" 접두(§WP2-1)가 없다 — "기상대 온도" 가 그냥 "온도" 로
        나왔다. `grp.measurement_label` 이어야 그 판정이 실린다."""
        html = self._html()
        self.assertNotIn('{% else %}{{ e.measurement_label or e.measurement }}',
                        html)
        self.assertIn('{% else %}{{ grp.measurement_label or grp.measurement }}',
                      html)

    def test_runtime_is_a_table_shown_immediately(self):
        """압축 한 줄에서는 물량·추정 표시가 죽는다 — 1~2행짜리 표라
        접을 이유가 없다."""
        html = self._html()
        self.assertNotIn('aot-journal-runtime-line', html)
        self.assertIn('aot-journal-table aot-journal-runtime', html)

    def test_ambiguous_row_fields_are_read_with_get_not_dot_access(self):
        """실측: 500 오류 — `row` 는 요약(summary)일 수도 개별 센서 행일
        수도 있는데 둘의 키 집합이 다르다(요약엔 `delta_min`/`delta_max`
        만, 개별 행엔 `delta` 만). 점 접근(`row.delta_min`)은 없는 키에서
        `Undefined` 를 내고, `Undefined is not none` 이 **참**이라 없는
        값을 있는 것처럼 읽어 서식화(`'%+g'|format`)하다 죽는다
        (`jinja2.exceptions.UndefinedError: 'dict object' has no
        attribute 'delta_min'`, 실제 브라우저 재현). `.get()` 이면
        없는 키가 진짜 `None` 으로 와 분기가 올바르게 넘어간다."""
        html = self._html()
        # `row` 를 그렇게 쓰는 곳은 이제 단계 요약 표 하나다.
        start = html.index('{% for grp in sec.env_groups %}')
        block = html[start:html.index('</table>', start)]
        for bad in ('row.target', 'row.delta_skipped', 'row.follows_curve',
                   'row.delta ', 'row.delta_min', 'row.delta_max',
                   'row.coverage_low', 'row.avg'):
            self.assertNotIn(bad, block,
                            '%r 이 특이사항 줄에서 점 접근으로 남아 있다 '
                            '— row 는 요약/개별 행 키 집합이 달라 '
                            '.get() 이어야 한다' % bad)


class TestPrimaryMeasurementSplit(unittest.TestCase):
    """일/주/월 표의 주요/나머지 가르기.

    **주요 = 결과 지표**(DLI·GDD·VPD)다. 실사용 결정(2026-09-04): "DLI, GDD,
    VPD 는 주요지표이기 때문에 각 층에서 다루는 게 낫다" — 그림(도표 상위)과
    표가 같은 기준을 쓴다.
    """

    @staticmethod
    def _rows(*specs):
        return [{'sensor': 's-%s-%s' % (m, s), 'measurement': m, 'unit': u,
                 'scope': s, 'min': 1, 'max': 3, 'avg': 2, 'samples': 24,
                 'expected': 24}
                for m, u, s in specs]

    def test_derived_indicators_are_the_primary_rows(self):
        groups = PJ.group_env_rows(self._rows(
            ('radiation', 'W_m2', 'outdoor'),
            ('dli', 'mol_m2_d', 'outdoor'),
            ('temperature', 'C', 'indoor'),
            ('humidity', 'percent', 'indoor'),
            ('vapor_pressure_deficit', 'kPa', 'indoor'),
        ))
        primary = {g['measurement'] for g in groups if g['primary']}
        self.assertEqual(primary, {'dli', 'vapor_pressure_deficit'})

    def test_gdd_counts_as_a_primary_row(self):
        groups = PJ.with_gdd_group(
            PJ.group_env_rows(self._rows(('temperature', 'C', 'indoor'))),
            {'gdd': 15.0})
        primary = {g['measurement'] for g in groups if g['primary']}
        self.assertEqual(primary, {'gdd'})

    def test_field_and_weather_station_of_one_indicator_stay_together(self):
        """둘을 갈라 한쪽만 즉시 보이면 "외기 대비 현장" 을 못 본다."""
        groups = PJ.group_env_rows(self._rows(
            ('vapor_pressure_deficit', 'kPa', 'indoor'),
            ('vapor_pressure_deficit', 'kPa', 'outdoor'),
            ('temperature', 'C', 'indoor'),
        ))
        same = [g['primary'] for g in groups
                if g['measurement'] == 'vapor_pressure_deficit']
        self.assertEqual(same, [True, True])

    def test_without_any_indicator_it_falls_back_to_the_old_rule(self):
        """노지 구획처럼 세 지표가 하나도 없으면 표가 통째로 접힌다 — 그때만
        광합성 우선순위 상위 N개로 돌아간다."""
        groups = PJ.group_env_rows(self._rows(
            ('temperature', 'C', 'outdoor'),
            ('humidity', 'percent', 'outdoor'),
            ('precipitation', 'mm', 'outdoor'),
            ('speed', 'm_s', 'outdoor'),
            ('pressure', 'hPa', 'outdoor'),
        ))
        primary = [g['measurement'] for g in groups if g['primary']]
        self.assertEqual(len(set(primary)), PJ.PRIMARY_MEASUREMENT_COUNT)
        self.assertNotIn('pressure', primary)

    def test_gdd_group_fills_every_key_the_table_touches(self):
        """없는 키에 점으로 접근하면 Jinja 가 `Undefined` 를 내는데
        `Undefined is not none` 이 참이라 방위 칸에서 "None" 이 찍힌다."""
        grp = PJ.gdd_display_group({'gdd': 12.5})
        row = grp['sensors'][0]
        for key in ('min', 'max', 'avg', 'sector', 'sector_pct', 'coverage_low',
                    'cover', 'usage', 'target', 'delta', 'delta_skipped',
                    'follows_curve', 'circular'):
            self.assertIn(key, row)
        self.assertEqual(row['avg'], 12.5)

    def test_no_gdd_no_group(self):
        self.assertIsNone(PJ.gdd_display_group({'gdd': None}))
        self.assertEqual(PJ.with_gdd_group([], {'gdd': None}), [])


class TestDerivedIndicatorsLeadTheCharts(unittest.TestCase):
    """도표는 **결과 지표**부터 — DLI · GDD(누적) · VPD.

    실사용 지적(2026-09-04): "Solar 는 하나의 데이터라면 DLI 는 데이터를
    활용한 결과 지표가 되는 것", "DLI 가 나왔으면 GDD 가 있어야지".
    """

    @staticmethod
    def _buckets():
        out = []
        for i in range(3):
            key = '2026-08-%02d' % (i + 1)
            rows = [{'device_id': 'd1', 'channel': 0, 'sensor': 's1',
                     'measurement': 'temperature', 'unit': 'C',
                     'min': 17.0, 'max': 25.0, 'avg': 21.0,
                     'samples': 24, 'expected': 24, 'scope': 'indoor'},
                    {'device_id': 'd2', 'channel': 0, 'sensor': 's2',
                     'measurement': 'radiation', 'unit': 'W_m2',
                     'min': 0.0, 'max': 800.0, 'avg': 200.0,
                     'samples': 24, 'expected': 24, 'scope': 'outdoor'},
                    {'device_id': 'd2', 'channel': 1, 'sensor': 's2',
                     'measurement': 'dli', 'unit': 'mol_m2_d',
                     'avg': 30.0 + i, 'samples': 24, 'expected': 24,
                     'scope': 'outdoor'},
                    {'device_id': 'd3', 'channel': 0, 'sensor': 's3',
                     'measurement': 'vapor_pressure_deficit', 'unit': 'kPa',
                     'min': 0.6, 'max': 1.4, 'avg': 0.9,
                     'samples': 24, 'expected': 24, 'scope': 'indoor'}]
            out.append({'key': key, 'date_label': key, 'empty': False,
                        'env': rows, 'control': [], 'notes': [], 'gdd': 15.0,
                        'env_groups': PJ.group_env_rows(rows)})
        return out

    def test_derived_flag_marks_dli_and_vpd(self):
        by = {s['measurement']: s for s in PJ.env_trend_series(self._buckets())}
        self.assertTrue(by['dli']['derived'])
        self.assertTrue(by['vapor_pressure_deficit']['derived'])
        self.assertFalse(by['radiation']['derived'])
        self.assertFalse(by['temperature']['derived'])

    def test_order_puts_dli_gdd_vpd_first(self):
        series = PJ.env_trend_series(self._buckets())
        gdd = PJ.gdd_trend_series(self._buckets(),
                                  {'gdd': {'total': 100.0, 'period': 45.0}})
        ordered = PJ.order_chart_series(series + [gdd])
        self.assertEqual([s['measurement'] for s in ordered[:3]],
                         ['dli', 'gdd', 'vapor_pressure_deficit'])

    def test_gdd_is_cumulative_from_the_season_start(self):
        """이 문서 안에서 0 부터 세면 "지금 몇 도" 라는 물음에 답하지 못한다."""
        s = PJ.gdd_trend_series(self._buckets(),
                                {'gdd': {'total': 100.0, 'period': 45.0}})
        self.assertEqual([p['avg'] for p in s['points']], [70.0, 85.0, 100.0])
        self.assertTrue(s['bars'])
        self.assertTrue(s['derived'])

    def test_explicit_baseline_wins(self):
        """단계 도표는 문서의 일부만 그린다 — 그 구간이 시작되는 시점의
        누적을 밖에서 받는다."""
        s = PJ.gdd_trend_series(self._buckets(), {'gdd': {}}, baseline=500.0)
        self.assertEqual(s['points'][0]['avg'], 515.0)

    def test_gdd_axis_starts_at_zero(self):
        s = PJ.gdd_trend_series(self._buckets(),
                                {'gdd': {'total': 100.0, 'period': 45.0}})
        self.assertEqual(s['scale']['lo'], 0)

    def test_unusable_gdd_draws_nothing(self):
        """못 쓰는 것과 0 은 전혀 다르다 — 0 은 "하나도 안 쌓였다" 다."""
        self.assertIsNone(PJ.gdd_trend_series(
            self._buckets(), {'gdd': {'usable': False, 'reason': 'no-t-base'}}))

    def test_no_gdd_in_buckets_draws_nothing(self):
        buckets = [dict(b, gdd=None) for b in self._buckets()]
        self.assertIsNone(PJ.gdd_trend_series(buckets, {'gdd': {}}))

    def test_the_tables_gdd_row_does_not_become_a_second_chart(self):
        """`with_gdd_group()` 이 표에 넣은 그룹이 계열 생성까지 흘러가면
        "일별 GDD" 와 "GDD (누적)" 두 도표가 나온다(실측). 그림에서 GDD 는
        누적이 정본이다."""
        buckets = [dict(b, env_groups=PJ.with_gdd_group(b['env_groups'], b))
                   for b in self._buckets()]
        self.assertNotIn('gdd',
                         [s['measurement'] for s in PJ.env_trend_series(buckets)])
        # 표에는 그대로 있다.
        self.assertIn('gdd',
                      [g['measurement'] for g in buckets[0]['env_groups']])


class TestMagnitudesAreBarsNotDots(unittest.TestCase):
    """**0 이 실제 0 인 측정값**은 바닥에서 올라오는 막대다.

    실사용 지적(2026-09-04): "Solar 는 이렇게 표현되는게 맞아?" — 일사는
    min/max 가 있다는 이유로 마커(빈 트랙 위의 점)로 빠져 있었다.
    """

    @staticmethod
    def _series(measurement, unit, with_range=True):
        rows = [{'device_id': 'd', 'channel': 0, 'sensor': 's',
                 'measurement': measurement, 'unit': unit, 'avg': 5.0,
                 'samples': 24, 'expected': 24, 'scope': 'outdoor'}]
        if with_range:
            rows[0]['min'] = 0.0
            rows[0]['max'] = 9.0
        buckets = [{'key': '2026-08-01', 'date_label': '2026-08-01',
                    'env': rows, 'control': [], 'notes': [],
                    'env_groups': PJ.group_env_rows(rows)}]
        return PJ.env_trend_series(buckets)[0]

    def test_solar_is_a_bar_even_though_it_has_min_max(self):
        self.assertTrue(self._series('radiation', 'W_m2')['bars'])

    def test_rain_is_a_bar(self):
        self.assertTrue(self._series('precipitation', 'mm')['bars'])

    def test_temperature_is_not(self):
        """0 °C 는 "없었다" 가 아니라 그냥 낮은 값이다."""
        self.assertFalse(self._series('temperature', 'C')['bars'])

    def test_humidity_is_not(self):
        self.assertFalse(self._series('humidity', 'percent')['bars'])

    def test_bar_axis_starts_at_zero(self):
        """20~60 축에 얹으면 20 인 날이 0 처럼 보인다."""
        self.assertEqual(self._series('radiation', 'W_m2')['scale']['lo'], 0)

    def test_a_series_without_min_max_is_still_a_bar(self):
        self.assertTrue(self._series('dli', 'mol_m2_d', with_range=False)['bars'])


class TestMidAxisGuide(unittest.TestCase):
    """세로 축 가운데 가이드 한 줄.

    실사용 지적(2026-09-04): "최소값·최대값만 표기하고 가이드선이 없어서
    그래프가 어느 정도 규모인지 짐작하기 어렵다."

    ⚠ **한 줄만** 긋는다. 같은 자리에서 격자로 깔았다가 "너무 산만하다" 는
      지적을 받은 적이 있다.
    """

    @staticmethod
    def _js():
        import io as _io
        path = os.path.join(os.path.dirname(__file__), '..', 'aot_flask',
                            'static', 'js', 'common', 'aot-dataviz.js')
        return _io.open(os.path.abspath(path), encoding='utf-8').read()

    @staticmethod
    def _css():
        import io as _io
        path = os.path.join(os.path.dirname(__file__), '..', 'aot_flask',
                            'static', 'css', 'components', 'aot-dataviz.css')
        return _io.open(os.path.abspath(path), encoding='utf-8').read()

    def _body(self):
        js = self._js()
        return js[js.index('function range(o) {'):js.index('global.AoTViz = {')]

    def test_only_one_guide(self):
        self.assertEqual(self._body().count('aot-viz-guide'), 1)

    def test_guide_sits_on_a_real_tick_not_the_arithmetic_middle(self):
        """축의 산술 중간(예: 22.5)은 사람이 읽는 숫자가 아니다."""
        body = self._body()
        self.assertIn('for (i = 1; i < ticks.length - 1; i++)', body)
        self.assertIn('Math.abs(ticks[i].v - want)', body)

    def test_guide_is_behind_the_bars(self):
        body = self._body()
        self.assertLess(body.index('vscale + guide'),
                        body.index('aot-viz-cols\">'))

    def test_guide_reuses_the_track_colour_token(self):
        """축의 일부이지 값이 아니다 — 트랙과 한 토큰에서 온다."""
        css = self._css()
        block = css[css.index('.aot-viz--range .aot-viz-guide {'):]
        block = block[:block.index('}')]
        self.assertIn('var(--aot-viz-track-bg)', block)
        self.assertNotIn('color-mix', block)
        track = css[css.index('.aot-viz-track {'):]
        track = track[:track.index('}')]
        self.assertIn('background: var(--aot-viz-track-bg)', track)

    def test_axis_shows_three_numbers(self):
        self.assertIn('is-mid', self._body())


class TestSimulationDefects2And4(unittest.TestCase):
    """다른 세션의 시뮬레이션 점검(2026-09-04)에서 온 결함 중 일지 안에서
    끝나는 것들. 출처: 김제 3-1 `3-1 가을오이` 구획.
    """

    @staticmethod
    def _html():
        import io as _io
        path = os.path.join(os.path.dirname(__file__), '..', 'aot_flask',
                            'templates', 'pages', 'geo', 'journal_view.html')
        return _io.open(os.path.abspath(path), encoding='utf-8').read()

    # ── 결함 2 ────────────────────────────────────────────────────────────
    def test_rain_has_a_measurement_definition(self):
        """Open-Meteo 입력(채널 5)이 `rain` 을 쓰는데 정의가 없어 모든
        로케일에서 영문 'rain' 이 그대로 나갔다. `precipitation` 으로 바꾸면
        기존 설치의 저장 데이터가 끊기므로 **따로 둔다**."""
        from aot.config_devices_units import MEASUREMENTS, UNITS
        self.assertIn('rain', MEASUREMENTS)
        self.assertIn('precipitation', MEASUREMENTS)
        for unit in MEASUREMENTS['rain']['units']:
            self.assertIn(unit, UNITS, '%s 는 UNITS 에 없는 단위다' % unit)

    def test_measurement_label_no_longer_falls_through_for_rain(self):
        self.assertNotEqual(PJ.measurement_label('rain'), 'rain')

    # ── 결함 4 ────────────────────────────────────────────────────────────
    def test_timeline_anchors_on_the_journal_period_not_today(self):
        """8월 일지를 9월에 열면 막대가 9월 단계를 가리켰다 — 문서와 무관한
        단계가 맨 위에서 강조된다."""
        stages = [
            {'key': 'a', 'name': '개화기', 'starts_on': '2026-08-01',
             'ends_on': '2026-08-31'},
            {'key': 'b', 'name': '수확기', 'starts_on': '2026-09-01',
             'ends_on': '2026-09-30'},
        ]
        out = PJ.stage_timeline_data(stages, tz_name='Asia/Seoul',
                                     on=_date(2026, 8, 20))
        current = [s['name'] for s in out['segments'] if s.get('current')]
        self.assertEqual(current, ['개화기'])

    def test_timeline_never_runs_past_today(self):
        """진행 중인 문서는 기간 끝이 미래다 — 그때는 오늘이 맞다."""
        stages = [{'key': 'a', 'name': '개화기', 'starts_on': '2020-01-01',
                   'ends_on': '2020-01-31'}]
        out = PJ.stage_timeline_data(stages, tz_name='Asia/Seoul',
                                     on=_date(2999, 1, 1))
        self.assertFalse(any(s.get('current') for s in out['segments']))

    def test_out_of_period_stages_are_collapsed(self):
        """`stage_sections()` docstring 이 이미 "화면이 접어 둔다" 고 약속한
        동작이다. 기간 밖 단계 다섯이 목표표를 달고 먼저 나오면 데이터가
        있는 한 단계가 그 사이에 묻힌다."""
        html = self._html()
        self.assertIn('<div class="aot-journal-plan">', html)
        self.assertIn('aot-journal-plan-toggle', html)
        self.assertIn('.aot-journal-plan { display: none;', html)

    def test_collapsed_plan_is_forced_open_in_print(self):
        """접는 것이 사실을 지우지 않는다 — 종이는 펼칠 수 없다."""
        self.assertIn('.aot-journal-chart-extra,\n    .aot-journal-plan { display: block !important; }',
                      self._html())

    def test_collapsed_blocks_do_not_use_the_hidden_attribute(self):
        """부트스트랩이 `[hidden] { display: none !important }` 를 걸어 두어
        인쇄에서 펴려는 규칙이 먹지 않는다 — PDF 에 접힌 도표·계획이 통째로
        빠졌다(실사용 지적 2026-09-04). 표의 나머지 행과 같은 클래스 토글로
        맞춘다."""
        html = self._html()
        self.assertNotIn('aot-journal-plan" hidden', html)
        self.assertNotIn('aot-journal-chart-extra" hidden', html)
        self.assertIn("classList.toggle('is-open-extra')", html)

    def test_note_with_the_same_title_and_body_prints_once(self):
        """빠른 메모는 한 줄을 제목과 본문 둘 다에 넣는다 — 그대로 이으면
        "빠른 메모 — 빠른 메모" 가 된다."""
        html = self._html()
        self.assertEqual(
            html.count("{% set n_body = n.body if n.body != n.title else '' %}"),
            2)
        self.assertNotIn('{% if n.title %}{{ n.title }}{% if n.body %} — {% endif %}'
                         '{% endif %}{{ n.body }}', html)


class TestTargetDrift(unittest.TestCase):
    """목표 이탈 요약 — **세기만 하고 판정하지 않는다.**

    시뮬레이션 점검(2026-09-04): 야간온도가 78일 중 78일 목표를 넘겼는데,
    시스템은 시점별 Δ 는 계산하면서 그것을 종합해 말하지 않았다.
    """

    @staticmethod
    def _buckets(deltas, when=None, label='Day temp'):
        out = []
        for i, d in enumerate(deltas):
            rows = [{'measurement': 'temperature', 'unit': 'C',
                     'scope': 'indoor', 'sensor': 's', 'avg': 25.0 + d,
                     'samples': 24, 'expected': 24, 'target': 25.0,
                     'target_label': label, 'when': when, 'delta': d}]
            out.append({'key': '2026-08-%02d' % (i + 1), 'env': rows,
                        'control': [], 'notes': []})
        return out

    def test_counts_one_way_deviation(self):
        rows = PJ.target_drift(self._buckets([1.0, 2.0, 3.0]))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['days'], 3)
        self.assertEqual(rows[0]['above'], 3)
        self.assertEqual(rows[0]['below'], 0)
        self.assertEqual(rows[0]['one_way'], 'above')
        self.assertEqual(rows[0]['mean'], 2.0)

    def test_one_way_is_arithmetic_not_a_threshold(self):
        """허용 범위가 데이터에 없고 그것은 의도된 선택이다 — 임계값을
        지어내지 않는다. 한 방향 100% 만 표시한다."""
        rows = PJ.target_drift(self._buckets([1.0, 2.0, -0.5]))
        self.assertIsNone(rows[0]['one_way'])
        self.assertEqual((rows[0]['above'], rows[0]['below']), (2, 1))

    def test_skipped_rows_are_not_counted(self):
        """곡선 목표·주야 목표처럼 Δ 가 없는 행을 분모에 넣으면 "이탈 안 함"
        으로 잘못 세어진다."""
        buckets = self._buckets([1.0, 2.0])
        buckets.append({'key': '2026-08-03', 'control': [], 'notes': [],
                        'env': [{'measurement': 'temperature', 'unit': 'C',
                                 'scope': 'indoor', 'sensor': 's',
                                 'target': 25.0, 'target_label': 'Day temp',
                                 'delta': None, 'delta_skipped': 'method'}]})
        self.assertEqual(PJ.target_drift(buckets)[0]['days'], 2)

    def test_day_and_night_are_separate_items(self):
        """같은 measurement 라도 주간·야간은 다른 목표 항목이다."""
        buckets = self._buckets([1.0], when='day', label='Day temp')
        buckets += self._buckets([-2.0], when='night', label='Night temp')
        rows = PJ.target_drift(buckets)
        self.assertEqual({r['when'] for r in rows}, {'day', 'night'})

    def test_label_is_translated(self):
        """목표 라벨은 번역 대상 msgid 다("Day temp" → "주간 온도")."""
        rows = PJ.target_drift(self._buckets([1.0]))
        self.assertEqual(rows[0]['label'], PJ._gettext_safe('Day temp'))

    def test_one_way_items_come_first(self):
        buckets = self._buckets([1.0, -1.0], when='day', label='Day temp')
        buckets += self._buckets([2.0, 3.0], when='night', label='Night temp')
        self.assertEqual(PJ.target_drift(buckets)[0]['when'], 'night')

    def test_reads_grouped_or_raw_rows(self):
        """단계 절은 보는 단위와 무관하게 날짜별 행으로 센다."""
        raw = self._buckets([1.0, 2.0])
        grouped = [dict(b, env_groups=PJ.group_env_rows(b['env'])) for b in raw]
        self.assertEqual(PJ.target_drift(raw)[0]['days'],
                         PJ.target_drift(grouped)[0]['days'])


class TestAmbiguousChannelNames(unittest.TestCase):
    """실사용 점검(2026-09-04): 표에 "Wind" 두 줄이 나란히 서고 어느 쪽이
    방향인지 알 수 없었다 — Open-Meteo 입력이 풍속(채널 3)과 풍향(채널 4)에
    **똑같이 `'Wind'`** 를 붙인다.
    """

    def test_colliding_channel_names_fall_back_to_the_measurement(self):
        rows = [{'measurement': 'speed', 'unit': 'm_s', 'scope': 'outdoor',
                 'sensor': 'w', 'channel_name': 'Wind', 'avg': 2.8,
                 'samples': 24},
                {'measurement': 'direction', 'unit': 'bearing',
                 'scope': 'outdoor', 'sensor': 'w', 'channel_name': 'Wind',
                 'avg': 180.0, 'circular': True, 'samples': 24}]
        labels = {g['measurement']: g['measurement_label']
                  for g in PJ.group_env_rows(rows)}
        self.assertNotEqual(labels['speed'], labels['direction'])
        self.assertEqual(labels['speed'], PJ._gettext_safe('Wind speed'))
        self.assertEqual(labels['direction'], PJ._gettext_safe('Wind direction'))

    def test_same_measurement_is_not_a_collision(self):
        """현장·기상대 온도가 둘 다 '온도' 인 것은 정상이고, 그 둘은 "기상대"
        접두가 이미 가른다 — 사용자가 붙인 이름을 빼앗지 않는다."""
        rows = [{'measurement': 'temperature', 'unit': 'C', 'scope': 'indoor',
                 'sensor': 'a', 'channel_name': '온도', 'avg': 28.0,
                 'samples': 24},
                {'measurement': 'temperature', 'unit': 'C', 'scope': 'outdoor',
                 'sensor': 'w', 'channel_name': '온도', 'avg': 27.0,
                 'samples': 24}]
        groups = PJ.group_env_rows(rows)
        for g in groups:
            self.assertIn('온도', g['measurement_label'])

    def test_unique_channel_name_is_kept(self):
        """자기가 '강우' 라 적어 둔 것을 '길이' 로 되돌리면 못 알아본다."""
        rows = [{'measurement': 'length', 'unit': 'mm', 'scope': 'outdoor',
                 'sensor': 'r', 'channel_name': '강우', 'avg': 3.0,
                 'samples': 24}]
        self.assertEqual(PJ.group_env_rows(rows)[0]['measurement_label'], '강우')


class TestSimulationDefects1And3(unittest.TestCase):
    """전달받은 시뮬레이션 결함 1·3 — 관측가능 판정과 단계 DLI 목표."""

    # ── 결함 1: 동의·파생 키 ─────────────────────────────────────────────
    def test_aliases_cover_the_split_vocabularies(self):
        """같은 값을 모듈마다 다른 키로 잰다 — 정확 일치로 물으면 멀쩡히
        재고 있는 값이 "센서 없음" 이 된다."""
        from aot.config_devices_units import measurement_aliases
        self.assertIn('light', measurement_aliases('radiation'))
        self.assertIn('radiation', measurement_aliases('light'))
        self.assertIn('rain', measurement_aliases('precipitation'))
        self.assertEqual(measurement_aliases('temperature'), ('temperature',))

    def test_dli_is_observable_through_its_source_channel(self):
        """DLI 는 채널이 아니라 일사의 하루 적산이다."""
        from aot.config_devices_units import measurement_aliases
        self.assertEqual(set(measurement_aliases('dli')),
                         {'radiation', 'light'})

    def test_weather_sensors_count_as_measured(self):
        """노지 구획은 일사·강우를 기상대가 재는 것이 정상인데, 목록에서
        빼 두면 그 목표가 영원히 "이 구획은 못 잼" 이 된다."""
        import inspect
        from aot.aot_flask.geo import plot_context
        src = inspect.getsource(plot_context.measurable_sources_for_plot)
        self.assertIn("found.get('from_weather')", src)
        # 합친 집합은 여전히 기상대를 포함한다(옛 호출부의 계약).
        self.assertIn("have['weather']",
                      inspect.getsource(plot_context.measurable_in_plot))

    def test_observability_uses_aliases(self):
        import inspect
        from aot.aot_flask.geo import plot_context
        src = inspect.getsource(plot_context.observability_for_plot)
        self.assertIn('measurement_aliases', src)
        self.assertNotIn("t['observable'] = m in have", src)

    def test_the_two_observability_paths_cannot_drift(self):
        """규칙을 두 벌 적어 두면 한쪽만 고쳐진다 — 실제로 그랬다.
        별칭 수정이 `_mark_observable` 에만 들어가, **일지가 저장하는** 판정
        (`stage_targets_full`)은 계속 정확 일치라 `radiation` 이 "센서 없음"
        으로 굳었다."""
        import inspect
        from aot.aot_flask.geo import plot_context
        for fn in (plot_context._mark_observable,
                   plot_context.stage_targets_full):
            src = inspect.getsource(fn)
            self.assertIn('observability_for_plot(plot)', src,
                          '%s 가 판정을 따로 적고 있다' % fn.__name__)
            self.assertNotIn('measurable_in_plot(plot)', src)

    def test_observability_says_where_it_is_measured(self):
        """기상대가 재는 것을 그냥 "잰다" 로만 두면 사용자는 구획 안에 그
        센서가 있는 줄로 읽는다."""
        import inspect
        from aot.aot_flask.geo import plot_context
        src = inspect.getsource(plot_context.observability_for_plot)
        self.assertIn("'weather'", src)
        self.assertIn("'plot'", src)
        for fn in (plot_context._mark_observable,
                   plot_context.stage_targets_full):
            self.assertIn("observed_by", inspect.getsource(fn))

    # ── 결함 3: 단계 DLI 목표 ────────────────────────────────────────────
    def test_daily_light_target_is_compared_against_the_dli_row(self):
        """프로그램은 원천 채널(`radiation`)로 선언한다 — 옳다. 일지가 그것을
        그대로 견주면 일사 행(W/m²)에 붙어 `daily-shape` 로 막힌다."""
        out = PJ.journal_target_view([
            {'key': 'dli', 'label': 'DLI', 'measurement': 'radiation',
             'shape': 'daily', 'value': 32.0, 'unit': 'mol/m²/d'}])
        self.assertEqual(out[0]['measurement'], 'dli')
        self.assertNotIn('shape', out[0])

    def test_other_targets_are_untouched(self):
        out = PJ.journal_target_view([
            {'key': 'temp_day', 'measurement': 'temperature',
             'shape': 'instant', 'when': 'day', 'value': 29.0}])
        self.assertEqual(out[0]['measurement'], 'temperature')
        self.assertEqual(out[0]['shape'], 'instant')

    def test_the_programs_own_declaration_is_not_modified(self):
        """프로그램의 선언은 프로그램의 것이고 이것은 일지의 해석이다."""
        src = [{'measurement': 'radiation', 'shape': 'daily', 'value': 32.0}]
        PJ.journal_target_view(src)
        self.assertEqual(src[0]['measurement'], 'radiation')
        self.assertEqual(src[0]['shape'], 'daily')

    def test_stage_target_wins_over_the_programme_default(self):
        """단계마다 채우는 이유가 그것이다."""
        rows = [{'measurement': 'dli', 'unit': 'mol_m2_d', 'scope': 'outdoor',
                 'avg': 40.0}]
        PJ.attach_targets(rows, PJ.journal_target_view(
            [{'label': 'DLI', 'measurement': 'radiation', 'shape': 'daily',
              'value': 32.0}]) + [{'measurement': 'dli', 'value': 22.0,
                                   'label': 'DLI', 'source': 'program'}])
        self.assertEqual(rows[0]['target'], 32.0)
        self.assertEqual(rows[0]['delta'], 8.0)

    # ── 주야 목표 둘 다 세기 ─────────────────────────────────────────────
    def test_both_day_and_night_targets_are_evaluated(self):
        """표는 대표 하나만 보이면 되지만, 세는 쪽이 첫 후보만 보면 **야간
        목표는 존재하지 않는 것이 된다**(야간온도 78일 중 78일 초과)."""
        rows = [{'measurement': 'temperature', 'unit': 'C', 'scope': 'indoor',
                 'avg': 26.0, 'avg_day': 30.0, 'avg_night': 24.0}]
        PJ.attach_targets(rows, [
            {'label': 'Day temp', 'measurement': 'temperature',
             'when': 'day', 'value': 29.0},
            {'label': 'Night temp', 'measurement': 'temperature',
             'when': 'night', 'value': 22.0}])
        evals = rows[0]['targets_eval']
        self.assertEqual([e['when'] for e in evals], ['day', 'night'])
        self.assertEqual([e['delta'] for e in evals], [1.0, 2.0])
        # 대표는 그대로다 — 표·CSV·MD 가 단수를 전제한다.
        self.assertEqual(rows[0]['target'], 29.0)
        self.assertEqual(rows[0]['delta'], 1.0)

    def test_drift_counts_the_night_target(self):
        buckets = []
        for i in range(3):
            rows = [{'measurement': 'temperature', 'unit': 'C',
                     'scope': 'indoor', 'avg': 26.0, 'avg_day': 30.0,
                     'avg_night': 24.0}]
            PJ.attach_targets(rows, [
                {'label': 'Day temp', 'measurement': 'temperature',
                 'when': 'day', 'value': 29.0},
                {'label': 'Night temp', 'measurement': 'temperature',
                 'when': 'night', 'value': 22.0}])
            buckets.append({'key': '2026-08-0%s' % (i + 1), 'env': rows,
                            'control': [], 'notes': []})
        by_when = {d['when']: d for d in PJ.target_drift(buckets)}
        self.assertIn('night', by_when)
        self.assertEqual(by_when['night']['above'], 3)
        self.assertEqual(by_when['night']['one_way'], 'above')

    def test_old_journals_fall_back_to_the_single_target(self):
        """옛 일지는 야간 목표의 Δ 가 애초에 저장되지 않았다 — 지어내지 않는다."""
        buckets = [{'key': '2026-08-01', 'control': [], 'notes': [],
                    'env': [{'measurement': 'temperature', 'unit': 'C',
                             'scope': 'indoor', 'target': 29.0, 'when': 'day',
                             'target_label': 'Day temp', 'delta': 1.0}]}]
        rows = PJ.target_drift(buckets)
        self.assertEqual([r['when'] for r in rows], ['day'])

    # ── "센서 없음" 재판정 ───────────────────────────────────────────────
    def test_no_sensor_line_is_rechecked_against_real_rows(self):
        """저장된 `observable` 은 생성 시점에 굳는데 판정 자체가 틀려 있었다 —
        값이 바로 위 표에 있는데 "센서 없음" 이 붙어 화면이 스스로를 부정했다."""
        targets = [{'label': 'DLI', 'measurement': 'radiation',
                    'shape': 'daily', 'value': 32.0, 'observable': False},
                   {'label': 'CO2', 'measurement': 'co2', 'value': 800.0,
                    'observable': False}]
        env = [{'measurement': 'light', 'unit': 'W_m2'},
               {'measurement': 'dli', 'unit': 'mol_m2_d'}]
        left = [t['label'] for t in PJ._unobservable_targets(targets, env)]
        self.assertEqual(left, ['CO2'])


class TestJournalViewNamesAreAlwaysBound(unittest.TestCase):
    """`render_template` 에 넘기는 이름은 **문서가 아직 안 만들어졌을 때도**
    있어야 한다.

    실측(2026-09-04): 생성 직후 첫 렌더는 `is_ready()` 가 거짓이라 계산
    블록을 통째로 지나치는데, 거기서만 만들던 `target_drift` 를 그대로
    넘겨 `UnboundLocalError` 로 500 이 났다. 새로고침하면 완료돼서 사라지는
    탓에 **일지가 만들어지는 순간에만 보이는** 오류였다.

    이 검사는 그 한 이름이 아니라 **그 부류**를 막는다.
    """

    @staticmethod
    def _view_fn():
        import ast
        import io as _io
        path = os.path.join(os.path.dirname(__file__), '..', 'aot_flask',
                            'routes_geo_journal.py')
        tree = ast.parse(_io.open(os.path.abspath(path), encoding='utf-8').read())
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == 'geo_journal_view':
                return node
        raise AssertionError('geo_journal_view 를 찾지 못했다')

    def test_every_render_kwarg_is_bound_on_the_not_ready_path(self):
        import ast
        fn = self._view_fn()

        # `render_template(...)` 의 키워드 인자 중 **맨 이름**인 것들.
        wanted = set()
        for node in ast.walk(fn):
            if (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id == 'render_template'):
                for kw in node.keywords:
                    if isinstance(kw.value, ast.Name):
                        wanted.add(kw.value.id)
        self.assertTrue(wanted, 'render_template 호출을 찾지 못했다')

        # `is_ready()` 분기 **밖에서** 대입되는 이름들.
        def _is_ready_branch(stmt):
            return (isinstance(stmt, ast.If)
                    and 'is_ready' in ast.dump(stmt.test))

        bound = {a.arg for a in fn.args.args}
        for stmt in fn.body:
            if _is_ready_branch(stmt):
                continue          # 이 안은 안 돌 수 있다
            for node in ast.walk(stmt):
                if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
                    bound.add(node.id)

        missing = sorted(n for n in wanted if n not in bound)
        self.assertEqual(
            missing, [],
            '%s 이(가) is_ready() 분기 안에서만 만들어진다 — 생성 직후 첫 '
            '렌더에서 UnboundLocalError 가 난다' % ', '.join(missing))

    def test_body_top_level_does_not_dot_into_a_missing_data(self):
        """매크로들과 함께 본문 맨 위로 올라온 `{% set %}` 은 "생성 중"
        가드보다 **먼저** 돈다 — 그때 `journal.data` 는 아직 `None` 이다
        (실측: `'None' has no attribute 'target'`)."""
        import io as _io
        path = os.path.join(os.path.dirname(__file__), '..', 'aot_flask',
                            'templates', 'pages', 'geo', 'journal_view.html')
        html = _io.open(os.path.abspath(path), encoding='utf-8').read()
        guard = html.index("{% if journal.status in ('pending', 'running') %}")
        head = html[:guard]
        import re
        for m in re.finditer(r'\{%-?\s*set\s+(\w+)\s*=(.*?)%\}', head, re.S):
            name, expr = m.group(1), m.group(2)
            if name == 'd' or 'd.' not in expr:
                continue
            self.assertIn('d and', expr,
                          '%s 가 가드보다 먼저 `d.` 를 점 접근한다' % name)


class TestDriftCountsDaysNotRows(unittest.TestCase):
    """"78일 중 78일" 은 **날짜**를 세는 말이다.

    실측(2026-09-04, MCP 응답): 같은 measurement 를 재는 센서가 둘인 구획
    에서 14일짜리 단계가 `days: 24` 로 나왔다 — 행마다 세고 있었다.
    """

    @staticmethod
    def _buckets(n=3, deltas=(10.0, 20.0)):
        out = []
        for i in range(n):
            rows = [{'measurement': 'humidity', 'unit': 'percent',
                     'scope': 'indoor', 'sensor': 's%s' % j, 'target': 70.0,
                     'target_label': 'Humidity', 'delta': d}
                    for j, d in enumerate(deltas)]
            out.append({'key': '2026-08-%02d' % (i + 1), 'env': rows,
                        'control': [], 'notes': []})
        return out

    def test_denominator_never_exceeds_the_bucket_count(self):
        rows = PJ.target_drift(self._buckets(n=3))
        self.assertEqual(rows[0]['days'], 3)

    def test_two_sensors_are_counted_separately_not_averaged(self):
        """평균으로 접으면 **어느 센서도 말하지 않은 숫자**가 된다 —
        실측(김제 3-1): 습도 +16.30 과 +2.37 이 +11.56 으로 나왔다."""
        rows = PJ.target_drift(self._buckets(n=3, deltas=(10.0, 20.0)))
        self.assertEqual(rows[0]['sensor_count'], 2)
        self.assertEqual([s['mean'] for s in rows[0]['sensors']], [10.0, 20.0])
        # 대표 줄은 지어낸 값이 아니라 **범위**다.
        self.assertEqual((rows[0]['mean'], rows[0]['mean_hi']), (10.0, 20.0))
        self.assertEqual((rows[0]['days'], rows[0]['days_hi']), (3, 3))

    def test_each_sensor_keeps_its_own_denominator(self):
        """분모는 그 센서가 실제로 잰 날 수다 — 센서를 합치면 "51일" 처럼
        아무도 그만큼 재지 않은 수가 된다."""
        buckets = self._buckets(n=3, deltas=(10.0, 20.0))
        # 마지막 날은 한 대만 쟀다.
        buckets[-1]['env'] = buckets[-1]['env'][:1]
        rows = PJ.target_drift(buckets)
        self.assertEqual([s['days'] for s in rows[0]['sensors']], [3, 2])
        self.assertEqual((rows[0]['days'], rows[0]['days_hi']), (2, 3))

    def test_a_day_is_still_counted_once_per_sensor(self):
        """같은 센서의 같은 날이 두 번 들어와도 분모가 부풀지 않는다."""
        buckets = self._buckets(n=2, deltas=(10.0,))
        buckets.append(dict(buckets[0]))          # 같은 key 를 한 번 더
        self.assertEqual(PJ.target_drift(buckets)[0]['sensors'][0]['days'], 2)

    def test_opposite_directions_are_not_cancelled(self):
        """한쪽은 초과, 다른 쪽은 미달 — 평균으로 접으면 그 사실이 사라진다.
        실측(김제 3-1, 51일): VPD 가 한 센서는 48일 중 42일 미달, 다른
        센서는 25일 중 15일 초과였는데 화면은 "40일 미달" 한 줄이었다."""
        rows = PJ.target_drift(self._buckets(n=2, deltas=(4.0, -6.0)))
        self.assertEqual(rows[0]['agree'], 'mixed')
        self.assertEqual([s['one_way'] for s in rows[0]['sensors']],
                         ['above', 'below'])
        # 전부가 같은 방향일 때만 한 방향 100% 다.
        self.assertIsNone(rows[0]['one_way'])

    def test_balanced_sensors_are_not_called_a_disagreement(self):
        """두 센서가 **똑같이 반반**이면 갈린 것이 아니다. 예전에는 우세한
        방향이 없다는 이유로 'mixed' 가 붙어, 화면이 없는 불일치를 말했다."""
        # 날짜를 겹치지 않게 — 한 센서의 하루에는 값이 하나뿐이다.
        buckets = self._buckets(n=2, deltas=(5.0, 5.0))
        later = self._buckets(n=2, deltas=(-5.0, -5.0))
        for i, b in enumerate(later):
            b['key'] = b['date_label'] = '2026-08-%02d' % (i + 3)
        buckets += later
        # 같은 두 센서가 각각 2일 초과·2일 미달 → 둘 다 반반
        rows = PJ.target_drift(buckets)
        self.assertEqual(rows[0]['sensor_count'], 2)
        self.assertEqual([s['above'] for s in rows[0]['sensors']], [2, 2])
        self.assertEqual([s['below'] for s in rows[0]['sensors']], [2, 2])
        self.assertIsNone(rows[0]['agree'])

    def test_one_leaning_and_one_balanced_is_not_a_disagreement(self):
        """한쪽만 기울고 다른 쪽이 반반인 것도 **맞서는** 것이 아니다."""
        buckets = self._buckets(n=2, deltas=(5.0, 5.0))
        later = self._buckets(n=1, deltas=(5.0, -5.0))
        for i, b in enumerate(later):
            b['key'] = b['date_label'] = '2026-08-%02d' % (i + 3)
        buckets += later
        rows = PJ.target_drift(buckets)
        # s0: 3일 전부 초과 / s1: 2일 초과 1일 미달 → 둘 다 above 쪽
        self.assertEqual(rows[0]['agree'], 'above')

    def test_opposite_leanings_are_still_mixed(self):
        rows = PJ.target_drift(self._buckets(n=2, deltas=(5.0, -5.0)))
        self.assertEqual(rows[0]['agree'], 'mixed')

    def test_one_way_survives_when_every_sensor_agrees(self):
        """"78일 중 78일" 은 센서별로 세어도 그대로 성립해야 한다 —
        야간온도는 두 센서가 같은 방향이었다."""
        rows = PJ.target_drift(self._buckets(n=3, deltas=(4.0, 6.0)))
        self.assertEqual(rows[0]['one_way'], 'above')
        self.assertEqual(rows[0]['agree'], 'above')


class TestChartHeadMatchesTheTable(unittest.TestCase):
    """도표 머리줄의 숫자는 **바로 옆 표와 같은 값**이다.

    실측(2026-09-04): 파종·발아기 표가 DLI 평균 38.46 을 내는데 같은 블록의
    그래프 머리줄은 41.73 이었다 — 뒤쪽은 그 단계 **마지막 날** 값이었다.
    같은 이름의 숫자가 한 자리에 둘 있으면서 어느 쪽이 무엇인지 말하지
    않았다.
    """

    @staticmethod
    def _buckets():
        out = []
        for i, v in enumerate([10.0, 20.0, 60.0]):
            rows = [{'device_id': 'd', 'channel': 0, 'sensor': 's',
                     'measurement': 'humidity', 'unit': 'percent',
                     'min': v - 1, 'max': v + 1, 'avg': v,
                     'samples': 24, 'expected': 24, 'scope': 'indoor'}]
            out.append({'key': '2026-08-0%s' % (i + 1),
                        'date_label': '2026-08-0%s' % (i + 1), 'empty': False,
                        'env': rows, 'control': [], 'notes': [],
                        'env_groups': PJ.group_env_rows(rows)})
        return out

    def test_head_comes_from_the_summary_not_the_last_point(self):
        buckets = self._buckets()
        merged = PJ._merge_bucket_group(
            {'days': buckets, 'first': _date(2026, 8, 1),
             'last': _date(2026, 8, 3)}, 'all')
        groups = PJ.group_env_rows(merged.get('env') or [])
        series = PJ.env_trend_series(buckets, summary_groups=groups)[0]
        table_value = (groups[0].get('summary')
                       or groups[0]['sensors'][0])['avg']
        self.assertEqual(series['head_value'], table_value)
        self.assertNotEqual(series['head_value'], series['points'][-1]['avg'])

    def test_head_is_not_recomputed_in_the_browser(self):
        """점들을 평균 내면 표본 수 가중이 어긋나 다시 두 숫자가 된다."""
        html = self._html()
        self.assertIn('s.head_value != null', html)
        self.assertNotIn('function lastValue(', html)

    def test_cumulative_series_keeps_its_last_value(self):
        """누적 곡선의 평균은 뜻이 없다 — 끝 시점의 누적이 그 기간의 값이다."""
        buckets = [dict(b, gdd=15.0) for b in self._buckets()]
        s = PJ.gdd_trend_series(buckets, {'gdd': {'total': 45.0,
                                                  'period': 45.0}})
        self.assertEqual(s['head_kind'], 'last')
        self.assertEqual(s['head_value'], s['points'][-1]['avg'])

    def test_runtime_head_is_the_total(self):
        """가동시간은 합이다 — 마지막 값을 실으면 "이 기간에 얼마나 돌았나"
        라는 물음에 하루치로 답하게 된다."""
        buckets = []
        for i, h in enumerate([1.0, 2.0, 3.0]):
            buckets.append({'key': '2026-08-0%s' % (i + 1), 'env': [],
                            'notes': [],
                            'control': [{'output_id': 'o', 'name': 'v',
                                         'hours': h}]})
        s = PJ.control_trend_series(buckets)[0]
        self.assertEqual(s['head_kind'], 'sum')
        self.assertEqual(s['head_value'], 6.0)

    @staticmethod
    def _html():
        import io as _io
        path = os.path.join(os.path.dirname(__file__), '..', 'aot_flask',
                            'templates', 'pages', 'geo', 'journal_view.html')
        return _io.open(os.path.abspath(path), encoding='utf-8').read()

    def test_stage_charts_are_fed_the_stage_summary(self):
        """단계 도표의 머리줄은 그 단계 표와 같아야 한다."""
        import inspect
        src = inspect.getsource(PJ.stage_sections)
        self.assertIn("summary_groups=section['env_groups']", src)


class TestJournalFollowsTheAotSpacingAndTypeRules(unittest.TestCase):
    """레이아웃 규약 — 실사용 지적(2026-09-04)으로 되돌아온 것들.

    "페이지의 모든 텍스트는 좌우 여백이 AoT 스타일에서 지정하는 여백을
    가져야 한다", "컨테이너를 들여쓰는 것은 금지", "링크 문자색이 심각",
    "글자 크기·색 규칙이 없어 보인다".
    """

    @staticmethod
    def _html():
        import io as _io
        path = os.path.join(os.path.dirname(__file__), '..', 'aot_flask',
                            'templates', 'pages', 'geo', 'journal_view.html')
        return _io.open(os.path.abspath(path), encoding='utf-8').read()

    def _screen_css(self):
        """화면용 CSS 선언부만 — 인쇄(@media print)와 주석은 뺀다.

        인쇄는 `pt`·`mm` 로 따로 재는 자리라 화면 척도와 섞어 보면 안 된다.
        """
        import re
        html = self._html()
        css = html[html.index('<style>'):html.index('</style>')]
        css = css[:css.index('@media print')]
        return re.sub(r'/\*.*?\*/', '', css, flags=re.S)

    def test_no_ad_hoc_font_sizes(self):
        """자리마다 새 수치를 정하면 규칙이 없어 보이고, 실제로 없었다 —
        전역 척도(`--aot-font-size-*`)만 쓴다."""
        import re
        bad = [m.group(1).strip() for m
               in re.finditer(r'font-size:\s*([^;]+);', self._screen_css())
               if not m.group(1).strip().startswith('var(--aot-font-size')]
        self.assertEqual(bad, [])

    def test_no_opacity_used_as_a_colour(self):
        """`opacity` 로 회색을 흉내내면 같은 회색이 자리마다 다른 농도가
        된다. 색은 토큰으로만 정한다."""
        import re
        # 화면 블록에 `opacity` 선언이 남아 있으면 안 된다 — 상태 표시는
        # 프리미티브 쪽(`.aot-viz`)이 맡고, 이 파일의 글자색은 토큰이다.
        self.assertIsNone(re.search(r'opacity\s*:', self._screen_css()))

    def test_cover_gets_the_shared_left_margin(self):
        """표지만 0 이라 제목이 본문보다 왼쪽으로 튀어나와 있었다."""
        css = self._screen_css()
        block = css[css.index('.aot-journal-cover {'):]
        block = block[:block.index('}')]
        self.assertIn('16px', block)

    def test_containers_are_not_indented(self):
        """전역 스타일에 그런 규칙이 없고, 안쪽 컨테이너의 좌우 여백이
        바깥과 어긋난다."""
        css = self._screen_css()
        block = css[css.index('.aot-journal-stage-buckets {'):]
        block = block[:block.index('}')]
        self.assertNotIn('padding-left', block)
        self.assertNotIn('border-left', block)

    def test_toc_uses_the_shared_button(self):
        """목차 항목은 **앱의 공용 버튼**(`.btn.aot-pill-btn`)이다 —
        바로 위 내보내기 줄이 쓰는 것과 같은 것으로("구성: AoT btn 사용할 것",
        2026-09-04).

        이 검사는 예전에 정반대를 요구했다(맨 링크 + 글자색 토큰). 규칙 자체는
        그때도 지금도 하나다 — **모양을 새로 만들지 말고 있는 것을 쓸 것.**
        그때는 자체 알약을 만들었던 것이 문제였고, 지금은 전역 버튼을 그대로
        쓴다. 그래서 여기서 확인하는 것은 클래스가 공용이라는 것과, 이 목차에
        **자체 링크 스타일이 없다**는 것 둘이다."""
        html = self._html()
        self.assertIn('<nav class="aot-journal-toc">', html)
        for anchor in ('#journal-overview', '#journal-notes-mount'):
            self.assertIn('<a class="btn aot-pill-btn" href="%s">' % anchor, html)
        css = self._screen_css()
        # 자체 링크 색·밑줄을 다시 만들지 않는다(모양은 전역 규칙에서 받는다).
        self.assertNotIn('.aot-journal-toc a {', css)

    def test_drift_is_a_table_with_two_text_styles(self):
        """한 줄 안에 굵기 셋과 작은 글씨가 섞여 있었다 — 표로 바꾸고
        머리행·항목 이름만 강조, 나머지는 일반이다."""
        html = self._html()
        self.assertIn('class="table table-sm aot-journal-table aot-journal-drift"',
                      html)
        block = html[html.index('aot-journal-drift"'):]
        block = block[:block.index('</table>')]
        # 항목 이름만 머리칸이다 — 숫자 칸은 전부 일반 `<td>`.
        self.assertIn('<th scope="row">', block)
        self.assertIn('{{ it.label }}', block)
        # 값 칸에 강조·작은 글씨를 섞지 않는다.
        for banned in ('<strong>', 'text-muted', 'small'):
            self.assertNotIn(banned, block)

    def test_wide_tables_scroll_sideways(self):
        """열이 44px 까지 좁아지면 `943.0` 이 `943.` / `0` 으로 잘렸다 —
        숫자를 중간에서 자르는 것보다 미는 편이 낫다."""
        html = self._html()
        # 표마다 스크롤 상자가 하나씩.
        self.assertEqual(html.count('<table class="table table-sm aot-journal-table'),
                         html.count('<div class="aot-journal-table-scroll">'))
        css = self._screen_css()
        block = css[css.index('.aot-journal-table-scroll {'):]
        block = block[:block.index('}')]
        self.assertIn('overflow-x: auto', block)
        # 스크롤바는 보이지 않게 한다(앱 전역 규칙) — 동작은 그대로다.
        self.assertIn('scrollbar-width: none', block)

    def test_numbers_are_not_split_mid_digit(self):
        css = self._screen_css()
        self.assertIn('word-break: keep-all', css)

    def test_tables_use_one_kind_of_rule(self):
        """부트스트랩은 머리행 아래 2px, 나머지 1px 로 굵기가 둘이고,
        머리행 **위**에도 선을 하나 긋는다."""
        css = self._screen_css()
        block = css[css.index('.aot-journal-table thead th {'):]
        block = block[:block.index('}')]
        self.assertIn('border-top: 0', block)
        self.assertIn('border-bottom: 0', block)

    def test_containers_are_never_nested(self):
        """단계는 상자가 아니라 묶음이다 — 안에 요약·이탈·도표·날짜 상자가
        각각 들어가는데 바깥까지 상자면 좌우 여백이 두 번 겹친다.
        실측(2026-09-04): 단계 상자 안에 날짜 상자가 들어 깊이 2 였다."""
        html = self._html()
        # 단계 블록 자체는 컨테이너가 아니다.
        self.assertNotIn('class="aot-modal-container mb-3 aot-journal-stage"', html)
        self.assertIn('<div class="aot-journal-stage">', html)

    def test_closing_tags_are_in_order(self):
        """`</div>` 를 `</table>` **앞에** 넣었더니 브라우저가 요소를
        재배치해 날짜 상자가 서로 안으로 말려 들어갔다(실측: 깊이 32)."""
        import re
        html = self._html()
        self.assertIsNone(re.search(r'\n\s*</div>\n\s*</table>', html))

    def test_output_charts_get_the_same_gap(self):
        """장치 도표는 두 번째 목록에 들어가 그 첫 그림이
        `.aot-viz + .aot-viz`(32px) 에 걸리지 않는다 — 측정값 그림끼리는
        간격이 있는데 장치 그림만 위에 딱 붙었다."""
        css = self._screen_css()
        self.assertIn('.aot-journal-chart-list + .aot-journal-chart-list > .aot-viz:first-child',
                      css)

    def test_titles_sit_outside_their_container(self):
        """AoT 모달 규약 — 제목은 `padding-left:16px` 로 상자 안 라벨과 같은
        선에 선다. 상자 안에 넣으면 그 선이 어긋난다."""
        html = self._html()
        # 'Crop schedule' → 'Stage timeline': 작물에만 통하는 말을 제목에서
        # 뺐다(축사·시설 구획도 단계를 갖는다, 지적 2026-09-04).
        for title in ('Stage timeline', 'Measurement trends', 'Against target'):
            idx = html.index("_('%s')" % title)
            head = html[max(0, idx - 200):idx]
            self.assertIn('aot-modal-group-title', head,
                          '%s 제목이 공용 제목 클래스를 안 쓴다' % title)

    def test_stage_head_is_a_body_line_not_an_option_row(self):
        """옵션 행은 "이름 — 값" 쌍의 자리라 라벨에 상한이 걸려 있다 —
        서술문을 넣으면 말줄임으로 잘린다(실측)."""
        import re
        html = re.sub(r'\{#-?.*?-?#\}', '', self._html(), flags=re.S)
        idx = html.index('aot-journal-stage">')
        block = html[idx:idx + 400]
        self.assertNotIn('aot-modal-option-label', block)
        self.assertIn('aot-modal-body-text', block)


class TestValueTooltip(unittest.TestCase):
    """짚은 칸의 값을 그 자리에서 보인다(마우스·터치 공용).

    실사용 요청(2026-09-04): "그래프에 마우스 호버, 터치 시에 해당값을
    툴팁으로 표시할 것."
    """

    @staticmethod
    def _js():
        import io as _io
        path = os.path.join(os.path.dirname(__file__), '..', 'aot_flask',
                            'static', 'js', 'common', 'aot-dataviz.js')
        return _io.open(os.path.abspath(path), encoding='utf-8').read()

    @staticmethod
    def _css():
        import io as _io
        path = os.path.join(os.path.dirname(__file__), '..', 'aot_flask',
                            'static', 'css', 'components', 'aot-dataviz.css')
        return _io.open(os.path.abspath(path), encoding='utf-8').read()

    @staticmethod
    def _html():
        import io as _io
        path = os.path.join(os.path.dirname(__file__), '..', 'aot_flask',
                            'templates', 'pages', 'geo', 'journal_view.html')
        return _io.open(os.path.abspath(path), encoding='utf-8').read()

    def _body(self):
        js = self._js()
        return js[js.index('function range(o) {'):js.index('function tips(')]

    def test_native_title_is_not_used(self):
        """네이티브 `title` 은 **터치에서 아예 뜨지 않고** 데스크톱에서도 1 초
        넘게 걸린다 — 값을 확인하려고 짚는 동작에는 맞지 않는다."""
        body = self._body()
        self.assertIn("' data-tip=\"'", body)
        self.assertNotIn("' title=\"' + esc(p.", body)

    def test_one_pointer_handler_not_mouse_plus_touch(self):
        """mouse/touch 를 따로 걸면 터치 기기에서 둘 다 발화해 두 번 뜬다."""
        js = self._js()
        tips = js[js.index('function tips('):js.index('global.AoTViz = {')]
        self.assertIn("'pointermove'", tips)
        self.assertIn("'pointerdown'", tips)
        self.assertNotIn("'mousemove'", tips)
        self.assertNotIn("'touchstart'", tips)

    def test_binding_is_idempotent(self):
        """다시 그리지 않고 `tips()` 만 다시 부르면 핸들러가 쌓인다."""
        js = self._js()
        tips = js[js.index('function tips('):js.index('global.AoTViz = {')]
        self.assertIn("getAttribute('data-tips')", tips)

    def test_tip_lives_inside_its_own_plot(self):
        """도표 바깥(위)에 띄우면 **바로 위 도표의 제목 옆**에 떠서 어느
        그래프의 값인지 헷갈린다(실측)."""
        body = self._body()
        idx = body.index('aot-viz-tip')
        plot = body.index("'<div class=\"aot-viz-plot\">'")
        self.assertGreater(idx, plot)
        self.assertIn("'<div class=\"aot-viz-tip\" hidden></div></div>'", body)

    def test_exported(self):
        self.assertIn('tips: tips,', self._js())

    def test_tip_does_not_swallow_the_pointer(self):
        """풍선이 제 아래 칸을 가로채면 옆 칸으로 옮겨도 값이 안 바뀐다."""
        css = self._css()
        block = css[css.index('.aot-viz-tip {'):]
        block = block[:block.index('}')]
        self.assertIn('pointer-events: none', block)

    def test_tip_is_hidden_in_print(self):
        """짚어야 뜨는 것은 종이에서 뜻이 없다."""
        self.assertIn('@media print { .aot-viz-tip { display: none !important; } }',
                      self._css())

    def test_text_is_composed_by_the_caller_not_the_primitive(self):
        """`aot-dataviz.js` 는 문구를 만들지 않는다(msgid 가 갇힌다) —
        번역이 필요한 낱말은 템플릿에서 넘긴다."""
        html = self._html()
        self.assertIn("var TIP_AVG = {{ _('Avg') | tojson }};", html)
        js = self._js()
        tips = js[js.index('function tips('):js.index('global.AoTViz = {')]
        self.assertNotIn('Avg', tips)

    def test_empty_period_gets_no_tip(self):
        html = self._html()
        block = html[html.index('function tipText('):][:400]
        self.assertIn('if (p.avg == null && p.min == null) return null;', block)

    def test_wired_after_mounting(self):
        html = self._html()
        idx = html.index('mount.innerHTML = html;')
        self.assertIn('AoTViz.tips(mount);', html[idx:idx + 200])


class TestRangeIsOnlyABandBarTurnedOnItsSide(unittest.TestCase):
    """범위 도표는 **밴드 바를 세로로 돌린 것**이고, 그것뿐이다.

    이 자리에서 같은 실수를 네 번 했다(2026-09-04, 전부 실사용 지적):
      1. 축 눈금·목표를 전폭 **가로선**으로 → "너무 산만하다"
      2. 시키지 않은 **배경 면**을 깔았다 → "가독성이 떨어진다"
      3. **투명도**를 세 번 만들었다(`45%`·`55%`·`18%`)
      4. **구간(초록)을 마커 색으로** 칠하고 **라운드를 없앴다**

    아래 한 가지가 넷을 다 막는다: **이 블록은 색·배경·라운드를 선언하지
    않는다.** 축을 바꾸는 규칙만 둔다.
    """

    @staticmethod
    def _css():
        import io as _io
        path = os.path.join(os.path.dirname(__file__), '..', 'aot_flask',
                            'static', 'css', 'components', 'aot-dataviz.css')
        return _io.open(os.path.abspath(path), encoding='utf-8').read()

    @staticmethod
    def _js():
        import io as _io
        path = os.path.join(os.path.dirname(__file__), '..', 'aot_flask',
                            'static', 'js', 'common', 'aot-dataviz.js')
        return _io.open(os.path.abspath(path), encoding='utf-8').read()

    def _block(self):
        """범위 도표 CSS 블록 — 주석을 걷어낸 **선언부만**."""
        import re
        css = self._css()
        start = css.index('/* ── 범위 도표 (`.aot-viz--range`)')
        end = css.index('/* ── 눈금 라벨')
        return re.sub(r'/\*.*?\*/', '', css[start:end], flags=re.S)

    def _body(self):
        js = self._js()
        return js[js.index('function range(o) {'):js.index('global.AoTViz = {')]

    def test_declares_no_colour_or_background(self):
        block = self._block()
        for banned in ('background', 'color-mix', 'transparent', 'opacity',
                       'rgba('):
            self.assertNotIn(banned, block,
                             '%r 을 선언했다 — 색은 클래스가 이미 갖고 있다'
                             % banned)

    def test_the_only_colour_is_the_axis_label_text(self):
        block = self._block()
        self.assertEqual(block.count('color:'), 1)
        self.assertIn('color: var(--aot-color-text-secondary)', block)

    def test_round_ends_turn_with_the_bar(self):
        """가로 막대의 양 끝은 `높이/2` 로 둥글다 — 세우면 그 몫이 `폭/2` 다."""
        self.assertIn('border-radius: calc(var(--aot-viz-range-bar) / 2)',
                      self._block())

    def test_marker_keeps_the_band_bars_cap_correction(self):
        self.assertIn('var(--aot-viz-pos, 0)', self._block())
        self.assertIn('--aot-viz-pos:', self._body())

    def test_markup_nests_inside_the_track_like_the_band_bar(self):
        """형제로 빼면 `border-radius: inherit` 이 끊긴다."""
        self.assertIn('<div class=\"aot-viz-track\">', self._body())

    def test_bar_width_steps_down_with_density(self):
        body = self._body()
        self.assertIn('pts.length <= 24 ? 8 : (pts.length <= 60 ? 4 : 2)', body)
        self.assertIn('--aot-viz-range-bar:', body)
        self.assertIn('min(var(--aot-viz-range-bar), 100%)', self._block())

    def test_nothing_is_invented_between_the_three_roles(self):
        body = self._body()
        for invented in ('aot-viz-gline', 'aot-viz-tline', 'aot-viz-day',
                         'aot-viz-night', 'aot-viz-bar', 'aot-viz-field'):
            self.assertNotIn(invented, body)


class TestRangePrimitiveExists(unittest.TestCase):
    """`AoTViz.range` 가 프리미티브 파일에 있고 규약을 지키는가."""

    @staticmethod
    def _js():
        import io as _io
        path = os.path.join(os.path.dirname(__file__), '..', 'aot_flask',
                            'static', 'js', 'common', 'aot-dataviz.js')
        return _io.open(os.path.abspath(path), encoding='utf-8').read()

    def _body(self):
        js = self._js()
        return js[js.index('function range(o) {'):js.index('global.AoTViz = {')]

    def test_exported(self):
        self.assertIn('range: range,', self._js())

    def test_does_not_invent_tick_text(self):
        """눈금 글자는 서버가 만든다 — 여기서 만들면 msgid·서식이 갇힌다."""
        body = self._body()
        self.assertIn('esc(ticks[0].text)', body)
        self.assertIn('esc(ticks[ticks.length - 1].text)', body)
        self.assertNotIn('toLocaleString', body)

    def test_draws_only_what_the_snapshot_stores(self):
        """스냅샷에는 사분위도 표준편차도 없다."""
        body = self._body()
        for invented in ('quartile', 'median', 'stddev', 'p25', 'p75'):
            self.assertNotIn(invented, body)


class TestSinglePeriodUsesABandBar(unittest.TestCase):
    """실사용 지적(2026-09-04): "단독으로 배치되는 경우 가로폭만 잡아먹고
    불필요하게 공간 점유율이 높다. 모든 표현 방법이 동일할 필요는 없다."

    기간이 하나면 세로 범위 도표 대신 **납작한 가로 막대** 하나를 쓴다.
    다만 그 가로 막대가 밴드 바인지 불릿인지는 **계열의 성격**이 정한다
    (2026-09-04 추가) — `bars`(0 에서 쌓이는 값: 적산온도·DLI·가동시간 등)를
    밴드 바로 그리면 초록이 '목표 범위' 가 되고 세로선이 '값' 이 되어,
    지도 위젯이 같은 지표를 그리는 어휘와 **정반대**가 된다. 같은 값이
    화면마다 다르게 읽히는 것이 공간 절약보다 나쁘다.
    정본: docs/design/dataviz-primitives.md "범위형과 누적형".
    """

    @staticmethod
    def _html():
        import io as _io
        path = os.path.join(os.path.dirname(__file__), '..', 'aot_flask',
                            'templates', 'pages', 'geo', 'journal_view.html')
        return _io.open(os.path.abspath(path), encoding='utf-8').read()

    def test_env_series_with_one_point_uses_band(self):
        html = self._html()
        block = html[html.index('function envChart(s)'):][:2600]
        self.assertIn('pts.length === 1', block)
        self.assertIn('AoTViz.band({', block)

    def test_env_cumulative_series_with_one_point_uses_bullet(self):
        """범위형만 밴드 바다 — 누적형은 기간이 하나여도 불릿이다."""
        html = self._html()
        block = html[html.index('function envChart(s)'):][:2600]
        self.assertIn('s.bars', block)
        self.assertIn('AoTViz.bullet({', block)
        # 불릿 분기가 밴드 분기보다 **앞**에 있어야 누적형이 밴드로 새지 않는다.
        self.assertLess(block.index('AoTViz.bullet({'), block.index('AoTViz.band({'))

    def test_runtime_with_one_point_uses_bullet(self):
        """가동시간은 '0 에서 쌓인 양' 이라 축 위의 한 점이 아니다."""
        html = self._html()
        block = html[html.index('controlTrends.map'):][:1400]
        self.assertIn('pts.length === 1', block)
        self.assertIn('AoTViz.bullet({', block)
        self.assertNotIn('AoTViz.band({', block)

    def test_band_targets_become_the_ok_zone(self):
        html = self._html()
        block = html[html.index('function envChart(s)'):][:2600]
        self.assertIn('okMin:', block)
        self.assertIn('okMax:', block)

    def test_band_scale_text_comes_from_the_server(self):
        html = self._html()
        block = html[html.index('function envChart(s)'):][:2600]
        self.assertIn('sc.ticks[0].text', block)


class TestStageAbsorbsBuckets(unittest.TestCase):
    """단계가 그 기간의 일/주/월을 품는다.

    실사용 지적: 단계 절과 일자별 절이 따로 있어 "정식기에 무슨 일이
    있었나" 를 두 군데서 맞춰 읽어야 했다.
    """

    @staticmethod
    def _journal(buckets=None):
        def day(key):
            return {'key': key, 'date_label': key, 'empty': False, 'notes': [],
                    'env': [{'device_id': 'd1', 'channel': 0, 'sensor': 's1',
                             'measurement': 'humidity', 'unit': 'percent',
                             'min': 60, 'max': 70, 'avg': 65, 'samples': 24,
                             'expected': 24, 'scope': 'indoor'}],
                    'control': []}
        return {
            'target': {'type': 'plot',
                       'period': {'start': '2026-08-01', 'end': '2026-08-04'}},
            'granularity': 'day',
            'stages': [{'key': 'a', 'name': '정식기',
                        'starts_on': '2026-08-01', 'ends_on': '2026-08-04',
                        'targets': []}],
            'buckets': buckets if buckets is not None else [
                day('2026-08-01'), day('2026-08-02'),
                day('2026-08-03'), day('2026-08-04')],
        }

    def test_no_granularity_keeps_the_old_shape(self):
        """MD·ODT 내보내기가 인자 없이 같은 함수를 쓴다 — 기본값이 바뀌면
        그 경로들이 조용히 달라진다."""
        sec = PJ.stage_sections(self._journal())[0]
        self.assertEqual(sec['buckets'], [])

    def test_day_granularity_gives_one_bucket_per_day(self):
        sec = PJ.stage_sections(self._journal(),
                                granularity='day', stored='day')[0]
        self.assertEqual(len(sec['buckets']), sec['days'])
        self.assertTrue(all('env_groups' in b for b in sec['buckets']),
                        '화면이 쓰는 env_groups 가 붙어 있어야 한다')

    def test_week_granularity_folds_within_the_stage(self):
        """주 경계는 **단계마다** 다시 잡는다 — 문서 전체 기준으로 접으면
        한 버킷이 단계 경계를 걸쳐 소속을 지어내야 한다."""
        sec = PJ.stage_sections(self._journal(),
                                granularity='week', stored='day')[0]
        self.assertEqual(len(sec['buckets']), 1)
        self.assertTrue(sec['buckets'][0]['date_label'].startswith('2026-08-01'))

    def test_all_granularity_makes_no_bucket_list(self):
        """그 하나는 단계 요약과 같은 값이다 — 같은 표를 두 번 그리지 않는다."""
        sec = PJ.stage_sections(self._journal(),
                                granularity='all', stored='day')[0]
        self.assertEqual(sec['buckets'], [])

    def test_gap_buckets_are_listed_but_do_not_make_a_stage_current(self):
        """빈 구간을 목록에서 빼면 그 기간이 사라진 것처럼 보인다. 그렇다고
        빈 구간만 있는 단계가 '현재' 로 뒤바뀌어서도 안 된다."""
        gap = {'key': '2026-08-02', 'date_label': '2026-08-02 ~ 2026-08-04',
               'empty': True, 'gap_count': 3, 'env': [], 'control': [],
               'notes': []}
        data = self._journal(buckets=[gap])
        sec = PJ.stage_sections(data, granularity='day', stored='day')[0]
        self.assertFalse(sec['in_period'])
        self.assertEqual(sec['days'], 0)
        self.assertEqual(len(sec['buckets']), 1)
        self.assertTrue(sec['buckets'][0]['empty'])

    def test_stage_without_data_gets_no_buckets(self):
        data = self._journal()
        data['stages'].append({'key': 'z', 'name': '수확기',
                               'starts_on': '2026-12-01', 'ends_on': None,
                               'targets': []})
        secs = PJ.stage_sections(data, granularity='day', stored='day')
        self.assertEqual(secs[1]['buckets'], [])


class TestBucketBlockIsOneMacro(unittest.TestCase):
    """단계 절과 일자별 절이 **같은 조판**을 쓴다.

    예전에는 거의 같은 표가 두 벌 손으로 적혀 있어 한쪽만 고치는 일이 실제로
    있었다(기상대 접두·목표 열 게이트가 두 표에서 달랐다).
    """

    @staticmethod
    def _html():
        import io as _io
        path = os.path.join(os.path.dirname(__file__), '..', 'aot_flask',
                            'templates', 'pages', 'geo', 'journal_view.html')
        return _io.open(os.path.abspath(path), encoding='utf-8').read()

    def test_bucket_block_is_defined_once_and_used_twice(self):
        html = self._html()
        self.assertEqual(
            html.count('{% macro bucket_block(b, show_target, scope_id) %}'), 1)
        self.assertEqual(html.count('{{ bucket_block('), 2)

    def test_toggle_ids_are_scoped(self):
        """같은 버킷이 두 자리에 그려질 수 있다 — 접두가 없으면 한쪽을
        펼칠 때 다른 쪽도 열린다."""
        html = self._html()
        self.assertIn('data-group="{{ scope_id }}-{{ b.key }}-{{ gid }}"', html)
        self.assertIn('data-extra="{{ scope_id }}-{{ b.key }}"', html)

    def test_daily_section_is_skipped_when_stages_absorb_it(self):
        html = self._html()
        self.assertIn('{% if not stage_sections %}', html)
        # 목차도 그 분기를 따라간다 — 아래에서 확인한다.
        # 목차도 그 분기를 따라가야 한다 — 없는 자리로 보내는 링크는 눌러도
        # 아무 일이 없다.
        toc = html[html.index('<nav class="aot-journal-toc'):]
        toc = toc[:toc.index('</nav>')]
        self.assertIn(
            '{% else %}<a class="btn aot-pill-btn" href="#journal-log">', toc)

    def test_granularity_switcher_exists_once(self):
        """문서 전체에 하나 — 단계마다 두면 어느 것이 지금 보고 있는
        단위인지 알 수 없다.

        ⚠ 예전에는 단위 전환·이탈 요약·도표가 매크로 하나(`log_controls`)로
          묶여 있었다. 순서를 부르는 쪽이 정해야 해서 셋으로 갈랐다
          (단계 일정이 도표보다 위로 와야 한다 — 실사용 지적 2026-09-04).

        항목은 목차 줄과 같은 **공용 버튼**이다(`.btn.aot-pill-btn`) — 예전의
        `.aot-tag` 알약이 아니다(지적 2026-09-04)."""
        html = self._html()
        self.assertEqual(html.count('{% macro gran_switcher(anchor) %}'), 1)
        self.assertEqual(html.count('{{ gran_switcher('), 2)
        self.assertEqual(html.count('class="aot-journal-gran"'), 1)
        self.assertIn('class="btn aot-pill-btn {% if g == view_granularity %}'
                      'aot-pill-btn-primary{% endif %}"', html)

    def test_schedule_comes_before_the_charts(self):
        """문서를 여는 사람이 먼저 묻는 것은 "지금 어느 단계인가" 다."""
        html = self._html()
        stages = html.index('id="journal-stages"')
        timeline = html.index('journal-stage-timeline-mount', stages)
        charts = html.index('{{ trend_charts() }}', stages)
        self.assertLess(timeline, charts)

    def test_stage_notes_are_not_repeated_under_the_buckets(self):
        """버킷이 있으면 같은 노트가 날짜별로 이미 나와 있다."""
        html = self._html()
        self.assertIn('{% if sec.notes and not sec.buckets %}', html)
        self.assertIn('{% if sec.photos and not sec.buckets %}', html)

    def test_long_stages_may_break_across_printed_pages(self):
        """단계가 그 기간 전체를 품으므로 한 장에 가둘 수 없다 — `avoid` 로
        두면 브라우저가 뒷부분을 잘라 버린다."""
        html = self._html()
        self.assertIn('.aot-journal-stage { page-break-inside: auto; }', html)
        self.assertIn('.aot-journal-bucket { page-break-inside: avoid; }', html)


class TestStageRelayout(unittest.TestCase):
    """단계 절 재조판 — WP4-3."""

    @staticmethod
    def _html():
        import io as _io
        path = os.path.join(os.path.dirname(__file__), '..', 'aot_flask',
                            'templates', 'pages', 'geo', 'journal_view.html')
        return _io.open(os.path.abspath(path), encoding='utf-8').read()

    def test_timeline_bar_sits_above_the_stage_loop(self):
        html = self._html()
        timeline_at = html.index('journal-stage-timeline-mount')
        loop_at = html.index('{% for sec in stage_sections %}')
        self.assertLess(timeline_at, loop_at)

    def test_future_target_table_only_shows_when_it_changed(self):
        html = self._html()
        self.assertIn('sec.targets_changed', html)
        self.assertIn('Same targets as the previous stage.', html)

    def test_guidance_keeps_its_line_breaks(self):
        """예전에는 `\\n` 이 공백으로 접혀 문단 구분이 사라졌다."""
        html = self._html()
        self.assertIn('aot-journal-guidance', html)
        self.assertNotIn('class="small mb-2">{{ st.guidance }}</p>', html)


class TestJsonMountsUseScriptTagsNotAttributes(unittest.TestCase):
    """추세·기간 바가 서버 데이터를 받는 방식 — WP3·WP4-2·WP4-3.

    실측: `data-x="{{ value | tojson }}"` 로 냈더니 JSON 안의 큰따옴표가
    속성 경계와 부딪혀 HTML 이 거기서 잘렸다(브라우저 콘솔:
    `SyntaxError: Expected property name or '}' in JSON`). `tojson` 은
    `<script>` 문맥에서 안전하도록 이미 "안전" 표시가 돼 있어 속성 문맥에서
    다시 이스케이프되지 않는다 — 속성이 아니라 `<script type=
    "application/json">` 태그에 실어야 한다.
    """

    @staticmethod
    def _html():
        import io as _io
        path = os.path.join(os.path.dirname(__file__), '..', 'aot_flask',
                            'templates', 'pages', 'geo', 'journal_view.html')
        return _io.open(os.path.abspath(path), encoding='utf-8').read()

    def test_no_tojson_inside_an_html_attribute(self):
        import re
        html = self._html()
        # 설명 주석({#- ... -#})에는 사람이 읽는 예시로 이 패턴이 등장한다
        # (바로 이 결함을 설명하는 주석 자체가 그렇다) — 실제 코드만 본다.
        code_only = re.sub(r'\{#-?.*?-?#\}', '', html, flags=re.S)
        self.assertIsNone(
            re.search(r'="\{\{[^}]*\|\s*tojson', code_only),
            'tojson 결과가 여전히 속성값 안에 있다')

    def test_trend_and_timeline_data_ride_in_script_tags(self):
        html = self._html()
        self.assertIn(
            '<script type="application/json" id="journal-trends-data">',
            html)
        self.assertIn(
            '<script type="application/json" '
            'id="journal-stage-timeline-data">', html)

    def test_js_reads_the_script_tag_not_a_dataset_attribute(self):
        """속성이 나르는 것은 **script 태그의 id 하나**여야 한다 — JSON 을
        속성에 실으면 큰따옴표가 속성 경계와 부딪혀 HTML 이 거기서 잘린다.

        도표 마운트는 단계마다 여러 개라 id 를 `data-src` 로 받지만, 그
        id 가 가리키는 곳은 여전히 `<script type="application/json">` 이다.
        """
        html = self._html()
        self.assertIn('getElementById(mount.dataset.src)', html)
        self.assertIn("getElementById('journal-stage-timeline-data')", html)
        self.assertIn('<script type="application/json" id="stage-trends-', html)
        self.assertNotIn('stageTimelineMount.dataset', html)


class TestOpenFormatExports(unittest.TestCase):
    """열린 형식 내보내기 — 표 계산(CSV)과 편집 가능한 문서(ODT)."""

    @staticmethod
    def _data():
        return {
            'target': {'type': 'plot', 'name': '설원6', 'kind': 'vegetation',
                       'tz_name': 'Asia/Seoul',
                       'period': {'start': '2026-08-01', 'end': '2026-08-02'}},
            'granularity': 'day', 'stages': [], 'caveats': [],
            'buckets': [{
                'key': '2026-08-01', 'date_label': '2026-08-01', 'empty': False,
                'env': [{'sensor': '온습도_6', 'measurement': 'humidity',
                         'unit': 'percent', 'min': 50.0, 'max': 80.0,
                         'avg': 65.0, 'samples': 24, 'expected': 24,
                         'scope': 'indoor'}],
                'control': [{'name': 'v321', 'hours': 1.5}],
                'notes': [{'time': '2026-08-01T09:00:00', 'title': '점검',
                           'body': '이상 없음'}],
            }],
        }

    def test_csv_headers_are_not_translated(self):
        """CSV 는 사람이 아니라 **다른 도구**가 읽는다 — 열 이름이 로케일마다
        바뀌면 그 도구의 수식이 깨진다."""
        text = PJ.render_plot_journal_csv(self._data())
        self.assertTrue(text.startswith('period,kind,scope,device,measurement'))

    def test_csv_carries_env_runtime_and_notes(self):
        """파일을 둘로 나누면 사람이 둘을 맞춰 보아야 하고, 대개 안 맞춘다."""
        text = PJ.render_plot_journal_csv(self._data())
        self.assertIn(',env,', text)
        self.assertIn(',runtime,', text)
        self.assertIn(',note,', text)

    def test_csv_has_a_water_column(self):
        """WP2-4 — HTML·MD·ODT 는 관수량 열을 내는데 CSV 만 없었다."""
        self.assertIn('water_l', PJ.render_plot_journal_csv(self._data()))

    def test_csv_water_amount_reaches_the_runtime_row(self):
        data = self._data()
        data['buckets'][0]['control'][0]['water'] = {
            'litres': 197.3, 'share': 1.0, 'estimated': True,
            'source': 'map-equipment'}
        rows = list(__import__('csv').reader(
            PJ.render_plot_journal_csv(data).splitlines()))
        runtime_row = next(r for r in rows if r and r[1] == 'runtime')
        self.assertIn('197.3', runtime_row)
        self.assertIn('yes', runtime_row)

    def test_csv_runtime_scope_is_not_a_fabricated_indoor(self):
        """제어 행에는 '실내/실외' 가 없다 — 밸브를 그렇게 분류할 근거가
        없는데도 예전에는 고정값 'indoor' 가 찍혀 있었다."""
        rows = list(__import__('csv').reader(
            PJ.render_plot_journal_csv(self._data()).splitlines()))
        runtime_row = next(r for r in rows if r and r[1] == 'runtime')
        self.assertNotEqual(runtime_row[2], 'indoor')

    def test_odt_is_a_valid_zip_with_mimetype_first_and_stored(self):
        """ODF 규격 — 첫 항목이자 무압축. 어기면 종류 판별이 깨진다."""
        import io as _io
        import zipfile
        blob = PJ.render_plot_journal_odt(self._data())
        z = zipfile.ZipFile(_io.BytesIO(blob))
        self.assertIsNone(z.testzip())
        self.assertEqual(z.namelist()[0], 'mimetype')
        self.assertEqual(z.getinfo('mimetype').compress_type,
                         zipfile.ZIP_STORED)
        self.assertEqual(z.read('mimetype').decode(),
                         'application/vnd.oasis.opendocument.text')

    def test_odt_xml_parts_parse(self):
        import io as _io
        import zipfile
        from xml.dom import minidom
        z = zipfile.ZipFile(_io.BytesIO(PJ.render_plot_journal_odt(self._data())))
        for name in ('content.xml', 'styles.xml', 'META-INF/manifest.xml'):
            minidom.parseString(z.read(name))      # 던지면 실패

    def test_odt_escapes_xml_special_characters(self):
        """이름의 `&` 하나로 **파일이 통째로 안 열린다**(ZIP 은 멀쩡한데 파서가 죽는다)."""
        import io as _io
        import zipfile
        from xml.dom import minidom
        data = self._data()
        data['target']['name'] = 'A & B <C>'
        z = zipfile.ZipFile(_io.BytesIO(PJ.render_plot_journal_odt(data)))
        minidom.parseString(z.read('content.xml'))
        self.assertIn('&amp;', z.read('content.xml').decode())

    def test_no_server_side_pdf(self):
        """PDF 는 브라우저 인쇄 경로가 담당한다 — 두 벌이면 문서가 갈린다."""
        import inspect
        src = inspect.getsource(PJ)
        self.assertNotIn('from reportlab', src)


class TestPlannedStagesKeepGuidance(unittest.TestCase):
    """아직 오지 않은 단계의 지침도 낸다 — 계획은 기록만큼 실재한다."""

    def test_planned_branch_renders_guidance_and_targets(self):
        import io as _io
        path = os.path.join(os.path.dirname(__file__), '..', 'aot_flask',
                            'templates', 'pages', 'geo', 'journal_view.html')
        html = _io.open(os.path.abspath(path), encoding='utf-8').read()
        planned = html.split('aot-journal-stage-planned')[-1]
        self.assertIn('st.guidance', planned)
        self.assertIn('st.targets', planned)


class TestReadingOrderAndNaming(unittest.TestCase):
    """표는 **읽는 순서**로 세우고, 이름은 사용자가 적은 것을 쓴다."""

    def test_photosynthesis_drivers_come_first(self):
        """이름순은 사람이 읽는 순서가 아니다 — 실측에서 광합성을 좌우하는
        일사가 `습도·길이·일사량·속도` 한가운데 파묻혔다."""
        self.assertLess(PJ.measurement_rank('radiation'),
                        PJ.measurement_rank('temperature'))
        self.assertLess(PJ.measurement_rank('temperature'),
                        PJ.measurement_rank('humidity'))
        self.assertLess(PJ.measurement_rank('humidity'),
                        PJ.measurement_rank('vapor_pressure_deficit'))

    def test_wind_pair_is_adjacent(self):
        """풍향과 풍속은 한 사건의 두 축이라 떨어지면 눈으로 다시 붙여야 한다."""
        i = PJ.MEASUREMENT_ORDER.index('direction')
        j = PJ.MEASUREMENT_ORDER.index('speed')
        self.assertEqual(abs(i - j), 1)

    def test_unknown_measurement_lands_between_not_at_the_end(self):
        """맨 뒤로 보내면 새 측정값이 늘 구석에 처박힌다."""
        rank = PJ.measurement_rank('brand_new')
        self.assertGreater(rank, PJ.measurement_rank('speed'))
        self.assertLess(rank, PJ.measurement_rank('pressure'))

    def test_rows_sort_by_importance_then_indoor_before_outdoor(self):
        """같은 측정값의 실내·실외는 **나란히** 놓여야 견줄 수 있다."""
        def row(meas, scope, sensor):
            return {'measurement': meas, 'unit': 'x', 'sensor': sensor,
                    'scope': scope, 'min': 1, 'max': 2, 'avg': 1.5,
                    'samples': 1, 'by_bucket': {}}
        series = [{'measurement': m, 'unit': 'x', 'sensor': s, 'scope': sc,
                   'by_bucket': {date(2026, 8, 1): {'min': 1, 'max': 2,
                                                    'avg': 1.5, 'samples': 1}}}
                  for m, sc, s in (('humidity', 'indoor', 'a'),
                                   ('radiation', 'outdoor', 'w'),
                                   ('temperature', 'outdoor', 'w'),
                                   ('temperature', 'indoor', 'a'))]
        out = PJ.env_rows_by_bucket(series, [date(2026, 8, 1)])
        got = [(r['measurement'], r['scope']) for r in out[date(2026, 8, 1)]]
        self.assertEqual(got, [('radiation', 'outdoor'),
                               ('temperature', 'indoor'),
                               ('temperature', 'outdoor'),
                               ('humidity', 'indoor')])

    def test_channel_name_beats_the_generic_label(self):
        """실측: 미러-기상대 ch5 는 `length`(길이)인데 사람이 '강우' 로 이름을
        붙여 두었다. 그 이름을 무시하면 자기가 적은 것을 못 알아본다."""
        rows = [{'measurement': 'length', 'unit': 'mm', 'sensor': '기상대',
                 'channel_name': '강우', 'min': 0, 'max': 1, 'avg': 0.5,
                 'samples': 1, 'scope': 'outdoor'}]
        groups = PJ.group_env_rows(rows)
        self.assertEqual(groups[0]['sensors'][0]['measurement_label'], '강우')
        self.assertEqual(groups[0]['measurement_label'], '강우')

    def test_group_of_many_falls_back_to_the_generic_label(self):
        """여럿이면 이름이 제각각일 수 있어 일반명을 쓴다."""
        rows = [{'measurement': 'humidity', 'unit': 'percent', 'sensor': 'a',
                 'channel_name': '위쪽 습도', 'min': 1, 'max': 2, 'avg': 1.5,
                 'samples': 1, 'scope': 'indoor'},
                {'measurement': 'humidity', 'unit': 'percent', 'sensor': 'b',
                 'channel_name': '아래쪽 습도', 'min': 1, 'max': 2, 'avg': 1.5,
                 'samples': 1, 'scope': 'indoor'}]
        label = PJ.group_env_rows(rows)[0]['measurement_label']
        self.assertNotIn('위쪽', label)

    def test_indoor_and_outdoor_share_one_table(self):
        """표를 나누면 **순서를 매길 수 없다** — 광합성 1순위인 일사가 실외
        전용이라, 나누면 실내 값 전부 아래로 밀린다."""
        import io as _io
        path = os.path.join(os.path.dirname(__file__), '..', 'aot_flask',
                            'templates', 'pages', 'geo', 'journal_view.html')
        html = _io.open(os.path.abspath(path), encoding='utf-8').read()
        self.assertNotIn('outdoor_groups', html)
        self.assertNotIn('st_outdoor', html)
        # 현장·기상대를 가르는 것은 **이름**이다("기상대 온도") — 예전에는
        # 행 왼쪽에 세로 막대(`is-outdoor`)를 함께 그었는데, 이름이 이미
        # 말하고 있어 뜻이 겹쳤다(실사용 지적 2026-09-04).
        self.assertNotIn('is-outdoor', html)

    def test_no_badge_appended_to_the_sensor_name(self):
        """"한 열에는 한 정보만" — 배지를 이어 붙이면 이름이 두 겹으로 읽힌다."""
        import io as _io
        path = os.path.join(os.path.dirname(__file__), '..', 'aot_flask',
                            'templates', 'pages', 'geo', 'journal_view.html')
        html = _io.open(os.path.abspath(path), encoding='utf-8').read()
        self.assertNotIn("""<span class="aot-tag">{{ _('Outdoor') }}</span>""", html)


class TestStageWhen(unittest.TestCase):
    """기간 밖이라고 전부 앞으로 올 일은 아니다."""

    @staticmethod
    def _journal(stage_start, stage_end):
        return {
            'target': {'type': 'plot',
                       'period': {'start': '2026-08-24', 'end': '2026-08-28'}},
            'granularity': 'day',
            'stages': [{'key': 's', 'name': '단계', 'starts_on': stage_start,
                        'ends_on': stage_end, 'targets': []}],
            'buckets': [{'key': '2026-08-24', 'date_label': '2026-08-24',
                         'empty': False, 'env': [], 'control': [], 'notes': []}],
        }

    def test_stage_that_ended_before_the_period_is_past_not_planned(self):
        """이미 한 일을 '예정' 이라 부르면 앞으로 할 일로 읽힌다(실측)."""
        sec = PJ.stage_sections(self._journal('2026-08-17', '2026-08-23'))[0]
        self.assertFalse(sec['in_period'])
        self.assertEqual(sec['when'], 'past')

    def test_future_stage_is_planned(self):
        sec = PJ.stage_sections(self._journal('2026-09-24', '2026-10-14'))[0]
        self.assertEqual(sec['when'], 'planned')

    def test_stage_in_period_is_current(self):
        sec = PJ.stage_sections(self._journal('2026-08-24', '2026-08-28'))[0]
        self.assertTrue(sec['in_period'])
        self.assertEqual(sec['when'], 'current')


class TestDayNightTargets(unittest.TestCase):
    """일장을 알면 **그동안 못 내던 주야 편차**가 성립한다.

    하루 전체 평균과 견주면 야간 12도 목표를 한낮 35.6도와 비교해 23.6도
    차이라는 허위 경보가 났다(실측, `plot_context._stage_targets` 주석).
    """

    def test_day_target_uses_the_daytime_average(self):
        target = {'value': 25.0, 'when': 'day', 'measurement': 'temperature'}
        delta, skipped = PJ.delta_for(target, avg=28.74,
                                      avg_day=31.97, avg_night=24.22)
        self.assertIsNone(skipped)
        self.assertAlmostEqual(delta, 6.97, places=2)

    def test_night_target_uses_the_nighttime_average(self):
        target = {'value': 12.0, 'when': 'night', 'measurement': 'temperature'}
        delta, _ = PJ.delta_for(target, avg=28.74,
                                avg_day=31.97, avg_night=24.22)
        self.assertAlmostEqual(delta, 12.22, places=2)

    def test_whole_day_average_is_never_used_for_a_phase_target(self):
        """이 대입이 되살아나면 그것이 바로 허위 경보를 내던 계산이다."""
        target = {'value': 12.0, 'when': 'night'}
        delta, _ = PJ.delta_for(target, avg=35.6,
                                avg_day=None, avg_night=13.0)
        self.assertAlmostEqual(delta, 1.0, places=2)   # 35.6 이 아니라 13.0 기준

    def test_missing_phase_average_falls_back_to_skipping(self):
        """그 시간대에 기록이 없으면 **숫자를 지어내지 않는다**."""
        target = {'value': 12.0, 'when': 'night'}
        delta, skipped = PJ.delta_for(target, avg=35.6,
                                      avg_day=35.6, avg_night=None)
        self.assertIsNone(delta)
        self.assertEqual(skipped, 'when')

    def test_plain_target_is_unaffected(self):
        target = {'value': 65.0, 'measurement': 'humidity'}
        delta, skipped = PJ.delta_for(target, avg=71.27)
        self.assertIsNone(skipped)
        self.assertAlmostEqual(delta, 6.27, places=2)


class TestSunTimes(unittest.TestCase):
    """일출·일몰은 UTC 로 온다 — 값은 맞는데 화면만 틀리는 실패가 쉽다."""

    def test_display_converts_to_the_target_timezone(self):
        """실측: 일출 20:59Z 는 05:59 KST 다. 그대로 찍으면 일출이 저녁이 된다."""
        import inspect
        src = inspect.getsource(PJ.build_journal_for_target)
        self.assertIn('to_tz(moment, tz)', src)

    def test_phase_split_compares_aware_datetimes(self):
        """밤낮 판정은 aware 끼리 비교하므로 **이미 옳다** — 표시를 따라
        고치면 멀쩡한 판정을 깨뜨린다."""
        import inspect
        src = inspect.getsource(PJ.daily_channel_stats)
        self.assertIn('sunrise <= local < sunset', src)

    def test_polar_day_is_not_forced_into_a_phase(self):
        """백야·극야에 억지로 밤낮을 가르면 하루가 통째로 한쪽에 몰린다."""
        import inspect
        src = inspect.getsource(PJ.sun_lookup)
        self.assertIn('times.sunrise and times.sunset', src)

    def test_extremes_are_not_split_by_phase(self):
        """min/max 는 그날의 극값이라 시간대를 나누면 '그날 최고' 가 사라진다."""
        import inspect
        src = inspect.getsource(PJ.daily_channel_stats)
        self.assertIn("if fn == 'mean':", src)


class TestGrowingDegreeDays(unittest.TestCase):
    """적산온도 — `plot_context.gdd_accumulated()` 가 정본이다.

    **두 번째 계산자를 만들지 않는다.** 여기서 하는 일은 그 결과를 일지의 두
    축(누적 · 이 기간)으로 나누고 버킷에 붙이는 것뿐이다.
    """

    def test_working_map_is_not_stored(self):
        """`by_day` 는 키가 `date` 객체라 **저장 자체가 실패한다**.

        실측: `keys must be str, int, float, bool or None, not datetime.date`
        로 UPDATE 가 통째로 죽고, 빌드는 끝났는데 행이 영영 'running' 으로
        남았다 — 오류가 화면 어디에도 안 나와 원인에 닿기 어려웠다.
        """
        import inspect
        src = inspect.getsource(PJ.build_journal_for_target)
        self.assertIn("if k != 'by_day'", src)

    def test_gdd_folds_as_a_sum_not_an_average(self):
        """이름 그대로 **쌓이는** 값이라 주간 버킷은 그 주의 총량이어야 한다."""
        def day(key, gdd):
            return {'key': key, 'date_label': key, 'empty': False,
                    'env': [], 'control': [], 'notes': [], 'gdd': gdd,
                    'daylight_h': 13.0}
        out = PJ.fold_buckets([day('2026-08-01', 10.0), day('2026-08-02', 12.0)],
                              to='month', granularity='day')
        self.assertEqual(out[0]['gdd'], 22.0)

    def test_daylight_folds_as_an_average(self):
        """일장은 합계가 뜻이 없다 — 그 구간이 평균 몇 시간 낮이었는가다."""
        def day(key):
            return {'key': key, 'date_label': key, 'empty': False,
                    'env': [], 'control': [], 'notes': [], 'gdd': 1.0,
                    'daylight_h': 13.0}
        out = PJ.fold_buckets([day('2026-08-01'), day('2026-08-02')],
                              to='month', granularity='day')
        self.assertEqual(out[0]['daylight_h'], 13.0)

    def test_unusable_gdd_reports_a_reason_not_a_zero(self):
        """0 은 '하나도 안 쌓였다' 로 읽힌다 — 못 쓰는 것과 전혀 다르다."""
        got = PJ.gdd_for_journal(None, date(2026, 8, 30))
        self.assertFalse(got['usable'])
        self.assertEqual(got['reason'], 'no-program')
        self.assertIsNone(got['total'])

    def test_template_shows_the_reason(self):
        import io as _io
        path = os.path.join(os.path.dirname(__file__), '..', 'aot_flask',
                            'templates', 'pages', 'geo', 'journal_view.html')
        html = _io.open(os.path.abspath(path), encoding='utf-8').read()
        self.assertIn("d.gdd.reason == 'no-program'", html)
        self.assertIn("d.gdd.reason == 'no-t-base'", html)


class TestDailyLightIntegral(unittest.TestCase):
    """DLI — **단위를 잘못 보면 값이 배로 틀리는데 숫자는 그럴듯하다.**"""

    def test_par_sensor_is_not_converted(self):
        """이미 PPFD 인 값에 W/m² 계수를 곱하면 두 배가 된다."""
        factor, assumed = PJ.ppfd_factor('umol_m2_s')
        self.assertEqual(factor, 1.0)
        self.assertFalse(assumed)

    def test_shortwave_is_converted_and_marked_as_assumed(self):
        """PAR 비율·태양광 가정이 들어간 값이라 '추정' 이라고 말해야 한다."""
        factor, assumed = PJ.ppfd_factor('W_m2')
        self.assertGreater(factor, 1.0)
        self.assertTrue(assumed)

    def test_unknown_unit_is_never_guessed(self):
        """그럴듯한 계수를 지어내면 DLI 가 나오고, 나오는 순간 사람은 믿는다."""
        self.assertEqual(PJ.ppfd_factor('bearing'), (None, None))
        self.assertEqual(PJ.ppfd_factor(''), (None, None))
        self.assertEqual(PJ.ppfd_factor(None), (None, None))

    def test_integration_uses_measured_hours_not_a_flat_day(self):
        """하루 평균 × 24 로 계산하면 기록이 없는 시간까지 빛이 있었던 것으로
        센다. 시간별 값을 그대로 적분한다."""
        import inspect
        src = inspect.getsource(PJ.daily_channel_stats)
        self.assertIn('3600.0 / 1e6', src)

    def test_dli_is_its_own_row_not_folded_into_radiation(self):
        """일사 행의 평균은 W/m²(순간값)이고 DLI 는 mol/m²/일(적산값)이다 —
        한 줄에 두면 목표·Δ 가 어느 쪽 것인지 알 수 없다."""
        import inspect
        src = inspect.getsource(PJ.env_rows_by_bucket)
        self.assertIn("'measurement': 'dli'", src)

    def test_dli_sits_next_to_radiation_in_reading_order(self):
        order = PJ.MEASUREMENT_ORDER
        self.assertLess(abs(order.index('dli') - order.index('radiation')), 3)

    def test_dli_target_is_not_marked_daily_shape(self):
        """`shape='daily'` 는 '적산 목표를 순간 평균과 빼지 말라' 는 뜻인데,
        DLI 는 이미 적산이라 차원이 맞는다 — 붙이면 멀쩡한 비교가 막힌다."""
        import inspect
        src = inspect.getsource(PJ.photosynthesis_targets)
        self.assertNotIn("'shape': 'daily'", src)

    def test_only_dli_is_treated_as_a_target(self):
        """`A_max`·`K_L`·`T_opt` 는 목표가 아니라 **모델 계수**다 — 목표로
        내보내면 화면이 못 지킨 목표를 잔뜩 보여준다.

        ⚠ **코드 본문만 본다.** 독스트링에는 그 이름들이 "왜 뺐는가" 로
          적혀 있어, 소스 전체를 훑으면 검사가 자기 설명문을 위반으로 센다.
        """
        import ast
        import inspect
        tree = ast.parse(inspect.getsource(PJ.photosynthesis_targets).strip())
        fn = tree.body[0]
        body = fn.body[1:] if ast.get_docstring(fn) else fn.body
        code = '\n'.join(ast.unparse(node) for node in body)
        for key in ('A_max', 'K_L', 'K_C', 'T_opt', 'T_sigma'):
            self.assertNotIn(key, code)
        self.assertIn('dli_target', code)

    def test_caveats_explain_what_the_number_is(self):
        for key in ('dli-estimated', 'dli-outdoor'):
            text = PJ.caveat_text(key)
            self.assertNotEqual(text, key)

    def test_dli_inherits_the_source_coverage(self):
        """비워 두면 기록이 반나절뿐인 날의 DLI 도 온전한 값처럼 보인다 —
        적산값이라 빠진 시간만큼 그대로 적게 나온다."""
        import inspect
        src = inspect.getsource(PJ.env_rows_by_bucket)
        self.assertIn("'coverage': _dli_coverage", src)


class TestIrrigationVolume(unittest.TestCase):
    """관수량 — 유량계가 없는 밸브도 **설계 도면**이 답을 갖고 있다."""

    def test_share_comes_from_the_canonical_deriver(self):
        """저장된 것은 `{"amount": 4}` 같은 절대값이고 비율은 **파생**이다.
        여기서 다시 나누면 동의 총량이 바뀔 때 두 값이 조용히 갈린다."""
        import inspect
        src = inspect.getsource(PJ._allocation_share)
        self.assertIn('allocation_view', src)

    def test_unknown_share_is_one_not_zero(self):
        """0 이면 물량이 통째로 0 이 되어 '관수를 안 했다' 로 읽힌다 —
        실제로는 몫을 안 적었을 뿐이다."""
        class _P(object):
            facility_uuid = None
        self.assertEqual(PJ._allocation_share(_P()), 1.0)

    def test_open_field_has_no_design_flow(self):
        """노지에는 배관 도면이라는 것이 없다."""
        class _P(object):
            facility_uuid = None
        self.assertEqual(PJ.irrigation_flow_for_plot(_P()), {})

    def test_volume_folds_as_a_sum(self):
        def day(key, litres):
            return {'key': key, 'date_label': key, 'empty': False,
                    'env': [], 'notes': [],
                    'control': [{'output_id': 'v1', 'name': 'v1', 'hours': 1.0,
                                 'seconds': 3600,
                                 'water': {'litres': litres, 'share': 1.0,
                                           'estimated': True}}]}
        out = PJ.fold_buckets([day('2026-08-01', 10.0), day('2026-08-02', 5.0)],
                              to='month', granularity='day')
        self.assertEqual(out[0]['control'][0]['water']['litres'], 15.0)

    def test_first_day_is_not_counted_twice(self):
        """누산기를 첫 행의 사본으로 시작하면 첫날이 두 번 세어진다.
        에러가 없고 숫자만 커져서 **표만 보고는 알 수 없다**(실측 15→25)."""
        def day(key, litres, seconds):
            return {'key': key, 'date_label': key, 'empty': False,
                    'env': [], 'notes': [],
                    'control': [{'output_id': 'v1', 'name': 'v1',
                                 'hours': seconds / 3600.0, 'seconds': seconds,
                                 'water': {'litres': litres, 'share': 1.0,
                                           'estimated': True}}]}
        src = [day('2026-08-01', 10.0, 60), day('2026-08-02', 5.0, 30)]
        out = PJ.fold_buckets(src, to='month', granularity='day')
        self.assertEqual(out[0]['control'][0]['seconds'], 90)
        # 원본은 접기에 오염되지 않는다(중첩 dict 얕은 복사 함정).
        self.assertEqual(src[0]['control'][0]['water']['litres'], 10.0)

    def test_caveat_separates_estimate_from_measurement(self):
        """유량계 실측과 섞여 보이면 사람은 둘을 같은 신뢰도로 읽는다."""
        text = PJ.caveat_text('water-estimated')
        self.assertNotEqual(text, 'water-estimated')
        self.assertIn('flow meter', text)


class TestRuntimeUnits(unittest.TestCase):
    """가동시간 단위 — 시간으로만 쓰면 **관수가 사라진다**.

    밸브는 분 단위로 도는 것이 정상이라 6초 가동이 `0.0 시간` 으로 반올림되는데
    물량은 43.6 L 로 찍힌다 — "0시간인데 물이 나왔다" 는 모순으로 읽힌다(실측).
    """

    def test_hours_for_long_runs(self):
        self.assertIn('21.74', PJ.runtime_text({'seconds': 78264}))

    def test_minutes_for_short_runs(self):
        got = PJ.runtime_text({'seconds': 600})
        self.assertTrue(got.startswith('10'), got)

    def test_seconds_for_very_short_runs(self):
        got = PJ.runtime_text({'seconds': 6})
        self.assertTrue(got.startswith('6'), got)

    def test_zero_is_still_zero(self):
        self.assertTrue(PJ.runtime_text({'seconds': 0}).startswith('0'))

    def test_garbage_does_not_crash(self):
        self.assertTrue(PJ.runtime_text({}).startswith('0'))
        self.assertTrue(PJ.runtime_text({'seconds': 'x'}).startswith('0'))


class TestWeekBoundaries(unittest.TestCase):
    """주 경계 — **기록 시작일**에 앵커한다.

    ISO 주(월요일 시작)로 자르면 "1주차" 가 며칠짜리인지 심은 요일에 좌우된다.
    쿠마모토 딸기가 실제로 그랬다: 시작일 2026-08-23 이 **일요일**이라 1주차가
    하루뿐이었고, 라벨이 `첫날+6일` 로 만들어져 "08-23 ~ 08-29" 라 적혔다.
    그 안에 2주차(08-24~08-30)가 통째로 들어가 겹쳐 보였고, 읽는 사람은
    **데이터가 빠진 것**으로 읽었다.
    """

    def _days(self, first, n):
        d = date(*[int(x) for x in first.split('-')])
        from datetime import timedelta
        return [{'key': (d + timedelta(days=i)).isoformat(),
                 'date_label': (d + timedelta(days=i)).isoformat(),
                 'empty': False, 'env': [], 'notes': [], 'control': []}
                for i in range(n)]

    def test_weeks_never_overlap(self):
        out = PJ.fold_buckets(self._days('2026-08-23', 13),
                              to='week', granularity='day')
        spans = [b['date_label'] for b in out]
        for a, b in zip(spans, spans[1:]):
            self.assertLess(a.split(' ~ ')[1], b.split(' ~ ')[0],
                            '%s 와 %s 가 겹친다' % (a, b))

    def test_first_week_is_a_full_week_even_if_it_starts_on_a_sunday(self):
        out = PJ.fold_buckets(self._days('2026-08-23', 13),
                              to='week', granularity='day')
        self.assertEqual(out[0]['date_label'], '2026-08-23 ~ 2026-08-29')

    def test_label_does_not_run_past_the_last_record(self):
        """`첫날+6일` 로 쓰면 하루짜리 구간도 7일이라 적는다."""
        out = PJ.fold_buckets(self._days('2026-08-23', 9),
                              to='week', granularity='day')
        self.assertEqual(out[-1]['date_label'], '2026-08-30 ~ 2026-08-31')

    def test_a_gap_does_not_shift_later_weeks(self):
        """빠진 날이 있어도 경계는 시작일이 정한다 — 목록 순서로 7개씩
        묶으면 결측 하나가 이후 모든 주를 밀어 버린다."""
        days = self._days('2026-08-23', 13)
        del days[3]                       # 08-26 이 통째로 없다
        out = PJ.fold_buckets(days, to='week', granularity='day')
        self.assertEqual(out[0]['date_label'], '2026-08-23 ~ 2026-08-29')
        self.assertEqual(out[1]['date_label'][:10], '2026-08-30')

    def test_months_stay_on_the_calendar(self):
        """달은 옮기지 않는다 — 사람이 기록을 찾을 때 쓰는 단위가 달력의 달이다."""
        out = PJ.fold_buckets(self._days('2026-08-23', 13),
                              to='month', granularity='day')
        self.assertEqual([b['date_label'] for b in out], ['2026-08', '2026-09'])


class TestCoverTransmittance(unittest.TestCase):
    """적산 광량은 **피복을 지난 빛**이다.

    실외 일사에서 낸 DLI 는 하늘이 준 빛이지 작물이 받은 빛이 아니다. 실측:
    실외 42.28 이 비닐 2중(투과율 0.78)을 지나 32.98 이 된다. 딸기 DLI 목표가
    17~20 대라 **판단이 갈리는 크기**다.
    """

    def _dli_day(self, key, value, tau=0.78):
        return {'key': key, 'date_label': key, 'empty': False,
                'notes': [], 'control': [],
                'env': [{'measurement': 'dli', 'unit': 'mol_m2_d',
                         'scope': 'indoor', 'avg': value * tau,
                         'min': None, 'max': None, 'samples': 24,
                         'expected': 24,
                         'cover': {'tau': tau, 'material': 'vinyl_double',
                                   'inner': None, 'layers': 1, 'shade': False,
                                   'outdoor': value}}]}

    def test_open_field_gets_no_factor(self):
        """노지에서는 실외 일사가 곧 작물이 받는 빛이다."""
        class _P(object):
            facility_uuid = None
        self.assertIsNone(PJ.cover_light_factor(_P()))

    def test_shade_screen_is_flagged_not_multiplied(self):
        """차광은 고정 물성이 아니라 **사람이 치고 걷는 것**이다. 항상 곱하면
        안 친 날의 빛을 과소평가한다 — 언제 쳤는지는 기록에 없다."""
        import inspect
        src = inspect.getsource(PJ.cover_light_factor)
        self.assertIn("'shade': bool(env.get('curtain_shade_enabled'))", src)
        self.assertNotIn('curtain_shade_transmittance', src)
        text = PJ.caveat_text('dli-shade-not-counted')
        self.assertNotEqual(text, 'dli-shade-not-counted')

    def test_caveat_names_the_material_not_just_the_number(self):
        text = PJ.caveat_text('dli-through-cover:vinyl_double:0.78')
        self.assertIn('0.78', text)
        self.assertNotIn('vinyl_double', text)   # 코드값이 그대로 새면 안 된다

    def test_folding_recomputes_the_basis(self):
        """`dict(members[0])` 이 첫날의 실외값을 안고 오므로, 다시 계산하지
        않으면 접는 순간 값과 근거가 어긋난다(실측: 28.89 옆에 '실외 0.0')."""
        out = PJ.fold_buckets(
            [self._dli_day('2026-08-30', 0.0),
             self._dli_day('2026-08-31', 40.0)],
            to='week', granularity='day')
        row = out[0]['env'][0]
        self.assertAlmostEqual(row['cover']['outdoor'] * row['cover']['tau'],
                               row['avg'], places=1)

    def test_only_one_dli_row_survives_the_correction(self):
        """행을 둘로 늘리면 목표(dli_target)가 양쪽에 붙어 Δ 가 어느 쪽
        것인지 알 수 없어진다."""
        out = PJ.fold_buckets([self._dli_day('2026-08-30', 40.0)],
                              to='week', granularity='day')
        self.assertEqual(
            len([r for r in out[0]['env'] if r['measurement'] == 'dli']), 1)


class TestGlossary(unittest.TestCase):
    """GDD·DLI·VPD 는 시설원예 바깥에서는 통하지 않는 말이다.

    문서를 받는 쪽이 인증기관이나 다음 사람이면 숫자만 있고 그 숫자가 무엇을
    세는 것인지 물어볼 데가 없다.
    """

    def _doc(self, measurements, gdd=None):
        return {'buckets': [{'env': [{'measurement': m} for m in measurements]}],
                'gdd': ({'total': gdd} if gdd is not None else None)}

    def test_terms_that_do_not_appear_are_not_explained(self):
        """용어집을 통째로 실으면 GDD 를 쓰지 않는 노지 일지에도 적산온도
        설명이 붙는다 — 길어진 안내는 읽히지 않는다."""
        self.assertEqual(PJ.glossary_terms(self._doc(['humidity'])), [])

    def test_each_term_appears_only_when_used(self):
        got = {g['term'] for g in PJ.glossary_terms(
            self._doc(['dli', 'humidity']))}
        self.assertEqual(len(got), 1)
        self.assertIn('DLI', list(got)[0])

    def test_gdd_comes_from_its_own_section_not_the_env_rows(self):
        """적산온도는 측정 채널이 아니라 파생값이라 env 행에 없다 — 거기서만
        찾으면 GDD 가 있는 문서에도 설명이 안 붙는다."""
        got = [g['term'] for g in PJ.glossary_terms(
            self._doc(['humidity'], gdd=139.8))]
        self.assertEqual(len(got), 1)
        self.assertIn('GDD', got[0])

    def test_explanations_avoid_the_jargon_they_explain(self):
        """'적산광량은 DLI 입니다' 는 설명이 아니다."""
        for g in PJ.glossary_terms(self._doc(['dli', 'vapor_pressure_deficit'],
                                             gdd=1.0)):
            body = g['text']
            self.assertNotIn('PPFD', body)
            self.assertNotIn('integral of PAR', body)
            self.assertGreater(len(body), 80)


class TestStorageGranularity(unittest.TestCase):
    """저장 단위를 사람이 고른다 — 일간 · 주간 · 월간.

    굵게 고르면 저장 문서와 화면이 그만큼 작아진다(실측: 12일치가 일간
    102KB → 월간 28KB). **센서를 읽는 양은 줄지 않는다** — 어느 단위든
    시간별로 읽어 접기 때문이다. 화면 문구가 "빨라진다" 고 말하지 않는
    이유가 그것이다.
    """

    def test_a_coarser_request_always_wins(self):
        """굵은 쪽은 언제나 더 싸므로 거절할 이유가 없다."""
        self.assertEqual(PJ.choose_granularity(
            date(2026, 1, 1), date(2026, 1, 10), rows=1, requested='month'),
            'month')

    def test_daily_can_still_be_forced_down_by_the_budget(self):
        """일간 요청은 예산에 막힐 수 있다 — 그때는 접어서라도 문서를
        만드는 편이 거절하는 것보다 낫다."""
        self.assertEqual(PJ.choose_granularity(
            date(2026, 1, 1), date(2026, 12, 31),
            rows=PJ.MAX_JOURNAL_ROWS + 1, requested='day'), 'week')

    def test_no_request_keeps_the_old_behaviour(self):
        """아무것도 고르지 않은 사람의 결과가 달라지면 안 된다."""
        self.assertEqual(PJ.choose_granularity(
            date(2026, 1, 1), date(2026, 1, 10)), 'day')

    def test_month_labels_cover_every_month_in_the_period(self):
        keys = PJ.bucket_labels(date(2026, 1, 20), date(2026, 3, 2), 'month')
        self.assertEqual([k.isoformat() for k in keys],
                         ['2026-01-01', '2026-02-01', '2026-03-01'])

    def test_month_labels_do_not_skip_a_31_day_month(self):
        """`+31일` 로 넘기면 2월에서 3월을 건너뛴다."""
        keys = PJ.bucket_labels(date(2026, 1, 1), date(2026, 5, 1), 'month')
        self.assertEqual(len(keys), 5)

    def test_weekly_storage_still_anchors_on_the_iso_week(self):
        """저장 키는 `bucket_local_key` 가 정하고 그것은 ISO 주다 — 라벨만
        시작일에 앵커하면 키와 어긋나 버킷이 통째로 빈다. (열람의 접기는
        시작일 앵커이고, 그 둘은 다른 축이다.)"""
        keys = PJ.bucket_labels(date(2026, 8, 23), date(2026, 8, 31), 'week')
        self.assertEqual(keys[0].weekday(), 0)

    def test_month_coverage_denominator_follows_the_real_month(self):
        """30 으로 박으면 2월은 늘 100% 를 넘고 1월은 늘 모자란다."""
        from aot.utils.timekit import buckets_expected
        feb = buckets_expected(date(2026, 2, 1), 'month', 'Asia/Seoul', 3600)
        jan = buckets_expected(date(2026, 1, 1), 'month', 'Asia/Seoul', 3600)
        self.assertEqual((feb, jan), (28 * 24, 31 * 24))


class TestJournalHubScreen(unittest.TestCase):
    """저장된 일지 목록과 생성 화면 — 소스로 고정하는 것들."""

    def _hub(self):
        import io as _io
        path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'aot_flask', 'templates', 'pages', 'geo', 'journal.html')
        return _io.open(path, encoding='utf-8').read()

    def test_delete_says_delete_and_is_a_real_button(self):
        """× 는 시스템 전반에서 '닫기' 다. 게다가 20×24px 글리프가 행 전체
        링크 바로 옆에 있어, 폰에서 살짝 빗나간 탭이 삭제 대신 **일지로
        이동**했다 — 사용자에게는 "눌러도 삭제가 안 된다" 로 보인다."""
        src = self._hub()
        self.assertIn('aot-pill-btn aot-journal-row-del', src)
        self.assertIn(">{{ _('Delete') }}</button>", src)
        self.assertNotIn('&times;', src)

    def test_the_period_has_its_own_cell(self):
        """제목과 같은 칸에 흘려 두면 폰에서 날짜가 줄바꿈에 걸려 한 항목이
        서너 줄로 늘어진다."""
        src = self._hub()
        self.assertIn('aot-journal-cell-period', src)
        self.assertIn('grid-template-areas', src)

    def _js(self):
        import io as _io
        path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'aot_flask', 'static', 'js', 'geo', 'journal-page.js')
        return _io.open(path, encoding='utf-8').read()

    def test_the_measurement_heading_can_say_weather_station(self):
        """실내 센서가 없는 구획이면 고르는 대상이 전부 기상대 채널이고,
        실내와 기상이 둘 다 있으면 그 둘도 각자 자기 제목을 단다 —
        제목은 이제 그룹마다 JS 가 조립한다(`journal-meas-title` 이라는 고정
        id 는 그룹이 하나뿐이던 옛 구조의 흔적이라 더 없다)."""
        src = self._js()
        self.assertIn('Weather station measurements to include', src)
        self.assertIn('On-site sensor measurements to include', src)
        self.assertIn('Measurements to include', src)

    def test_the_unit_note_does_not_promise_speed(self):
        """굵은 단위는 문서를 줄이지 **읽는 양을 줄이지 않는다**(어느 단위든
        시간별로 읽어 접는다). 빠르다고 적으면 다음 사람이 그렇게 믿는다."""
        src = self._hub()
        self.assertIn("A coarser unit makes a smaller document", src)
        self.assertNotIn('faster', src.lower())


class TestJournalTableColumns(unittest.TestCase):
    """환경 표 — 측정값 · 목표 · 최소 · 최대 · 평균 · Δ.

    센서 이름 열은 없다. 표를 읽는 사람이 묻는 것은 "이 값이 얼마였나" 이지
    "어느 기계가 쟀나" 가 아니고, 이름 열은 폭을 가장 많이 먹으면서 대부분
    '미러-온습도01…07' 처럼 서로 구별되지 않는다. 여러 대가 든 행은 대수를
    눌러 펼치고 그때만 이름이 나온다 — 평균의 출처를 확인할 길은 남긴다
    (인증 문서로 나간다).
    """

    def _view(self):
        import io as _io
        path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'aot_flask', 'templates', 'pages', 'geo', 'journal_view.html')
        return _io.open(path, encoding='utf-8').read()

    def test_no_sensor_column_header(self):
        self.assertNotIn("<th>{{ _('Sensor') }}</th>", self._view())

    def test_target_comes_before_the_readings(self):
        """읽는 순서가 "얼마여야 하나 → 얼마였나" 다."""
        src = self._view()
        i = src.index("<th>{{ _('Measurement') }}</th>")
        block = src[i:i + 400]
        self.assertLess(block.index("_('Target')"), block.index("_('Min')"))
        self.assertLess(block.index("_('Avg')"), block.index('Δ'))

    def test_column_widths_declare_exactly_six_columns(self):
        """`table-layout: fixed` 는 선언한 폭만 쓴다 — 일곱 번째가 남아
        있으면 열 하나가 폭 없이 떠서 표끼리 어긋난다."""
        src = self._view()
        self.assertIn('td:nth-child(6) { width', src)
        self.assertNotIn('td:nth-child(7) { width', src)

    def test_expanded_rows_still_name_the_sensor(self):
        """이름을 통째로 없애면 '센서 2개' 를 펼쳐도 어느 것이 어느 것인지
        알 수 없다 — 그 행에서 달라지는 것이 센서다."""
        src = self._view()
        self.assertIn('{% if grp.summary %}{{ e.sensor }}', src)


class TestMissingValuesSayWhy(unittest.TestCase):
    """못 낸 값은 **빈칸으로 두지 않는다** — 빈칸은 고장으로 읽힌다.

    실측에서 적산온도는 구획 44개 중 36개가 비어 있었고(프로그램 없음 19 ·
    기준온도 없음 11 · 자료 부족 5 · 온도 센서 없음 1), 관수량은 노지 구획의
    밸브가 가동시간만 남긴 채 열이 통째로 비어 있었다. 계산은 둘 다 맞게
    돌고 있었고 없는 것은 **근거**였는데, 화면이 그 말을 하지 않아 "계산이
    되지 않는다" 는 보고가 왔다.
    """

    def _view(self):
        import io as _io
        return _io.open(os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'aot_flask', 'templates', 'pages', 'geo',
            'journal_view.html'), encoding='utf-8').read()

    def test_water_column_is_dropped_when_nothing_fills_it(self):
        """빈 열을 남기면 "계산이 안 된다" 로 읽힌다. 없는 이유는 안내가
        한 번 말한다."""
        src = self._view()
        self.assertEqual(src.count("selectattr('water')"), 2)   # 단계 절 + 일자별
        self.assertIn("{% if has_water %}<th>{{ _('Water') }}</th>{% endif %}",
                      src)

    def test_the_reason_is_written_down(self):
        text = PJ.caveat_text('water-no-flow-basis')
        self.assertNotEqual(text, 'water-no-flow-basis')
        self.assertIn('flow', text)

    def test_the_reason_does_not_claim_irrigation_happened(self):
        """어느 장치가 관수인지 판정하지 않는다 — Output 은 의미 분류가 없고
        (실측: 노지 밸브 `v331` 의 `kind` 가 None), 이름으로 맞히려 하면
        그런 이름에서 조용히 틀린다. 문장은 관수 여부가 아니라 **그 열에
        대한 사실**이어야 한다."""
        text = PJ.caveat_text('water-no-flow-basis')
        for word in ('watered', 'irrigated', 'irrigation ran'):
            self.assertNotIn(word, text)

    def test_no_name_based_irrigation_guessing_came_back(self):
        import inspect
        src = inspect.getsource(PJ)
        self.assertNotIn('IRRIGATION_OUTPUT_HINTS', src)

    def test_gdd_card_explains_itself(self):
        """카드가 이유를 말한다. `no-program` 은 빼는데, 프로그램 칸이 이미
        비어 있어 같은 말을 두 번 하게 된다."""
        import io as _io
        src = _io.open(os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'aot_flask', 'static', 'js', 'widgets', 'AoT_map',
            'aot-map-popup.js'), encoding='utf-8').read()
        self.assertIn("_gddReason === 'no-t-base'", src)
        self.assertIn("_gddReason === 'low-coverage'", src)
        self.assertIn("_gddReason !== 'no-program'", src)

    def test_low_coverage_still_shows_the_number(self):
        """값은 있다. 숨기면 사람은 고장으로 읽는다 — 오래된 값을 숨기지 않고
        흐리게 두는 규칙(측정값 신선도)과 같은 판단이다."""
        import io as _io
        src = _io.open(os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'aot_flask', 'static', 'js', 'widgets', 'AoT_map',
            'aot-map-popup.js'), encoding='utf-8').read()
        i = src.index("_gddReason === 'low-coverage'")
        self.assertIn('(opts.gdd || {}).value', src[i:i + 600])


class TestGddDayBoundary(unittest.TestCase):
    """적산온도의 "하루" 는 **현지 달력의 하루**다.

    예전에는 `group_sec=86400` 으로 InfluxDB 에 직접 하루를 시켰는데, 창은
    UTC 에폭에 정렬되므로 한국·일본에서는 그 하루가 현지 09:00~09:00 이었다.
    최고기온(오후)은 제자리에 들어가지만 **최저기온(새벽)이 전날 통에 들어가**
    짝이 어긋난다. 게다가 `aggregateWindow` 라벨이 구간의 오른쪽 경계인데
    빼지 않아 모든 날짜가 하루씩 밀려 있었다.
    """

    def _src(self):
        """⚠ **독스트링을 빼고 본다.** 그 함수의 설명이 바로 이 두 이름을
        "쓰지 않는다" 고 적고 있어, 문자열로 검사하면 자기 설명에 걸린다
        (같은 함정을 앞서 두 번 밟았다)."""
        import ast
        import inspect
        from aot.aot_flask.geo import plot_context
        tree = ast.parse(inspect.getsource(plot_context._daily_extremes))
        fn = tree.body[0]
        body = fn.body[1:] if (isinstance(fn.body[0], ast.Expr)
                               and isinstance(fn.body[0].value, ast.Constant)
                               and isinstance(fn.body[0].value.value, str)) else fn.body
        return '\n'.join(ast.unparse(n) for n in body)

    def test_influx_is_not_asked_for_a_whole_day(self):
        """`group_sec=86400` 은 UTC 에 정렬된 하루라 현지 하루가 아니다."""
        self.assertNotIn('group_sec=86400', self._src())

    def test_the_window_label_is_rewound(self):
        """라벨은 구간의 **오른쪽 경계**다 — 빼지 않으면 모든 날짜가 하루씩
        밀린다. `bucket_local_key` 가 그 뺄셈을 갖고 있다."""
        src = self._src()
        self.assertIn('bucket_local_key', src)
        self.assertNotIn('rec.get_time().date()', src)

    def test_the_period_is_cut_at_local_midnight(self):
        """UTC 자정으로 자르면 첫날의 새벽과 마지막 날의 저녁이 통째로 빠진다."""
        import inspect
        from aot.aot_flask.geo import plot_context
        src = inspect.getsource(plot_context.gdd_accumulated)
        self.assertIn('local_day_bounds_utc', src)
        self.assertNotIn("+ 'T00:00:00Z'", src)

    def test_bucket_size_looks_at_the_whole_period(self):
        """서머타임 전환이 끼면 오프셋이 둘이다 — 한쪽만 보면 나머지 절반에서
        현지 자정이 창 경계를 벗어난다."""
        import inspect
        from aot.aot_flask.geo import plot_context
        src = inspect.getsource(plot_context.gdd_accumulated)
        self.assertIn('bucket_seconds_for(tz, start, end)', src)

    def test_expected_days_and_counted_days_span_the_same_dates(self):
        """분모와 분자가 다른 날 집합을 세면 커버리지가 100% 를 넘는다
        (실측: 12/11 = 109.1%)."""
        import inspect
        from aot.aot_flask.geo import plot_context
        src = inspect.getsource(plot_context.gdd_accumulated)
        self.assertIn("info['days_expected'] = (last - start).days + 1", src)
        self.assertIn('day > last', src)

    def test_a_finished_season_counts_its_last_day(self):
        """오늘을 빼는 이유는 아직 안 끝났기 때문이다 — 끝난 작기의 마지막
        날은 온전한 하루라 그대로 센다."""
        import inspect
        from aot.aot_flask.geo import plot_context
        src = inspect.getsource(plot_context.gdd_accumulated)
        self.assertIn('if end >= today else end', src)


class TestOpenFieldIrrigation(unittest.TestCase):
    """노지 관수량 — **밸브의 담당 폴리곤**이 이미 답을 갖고 있다.

    지도에 놓인 출력은 `GeoShape(type='device')` 담당 폴리곤을 갖는다
    (`device_binding.SHAPE_TYPE_ROLES` 의 `'area'`). "이 밸브가 어디에 물을
    주는가" 는 그 도형이 답하므로, 노즐 임자를 정하는 별도의 지정을 만들
    이유가 없다.

    ⚠ **한때 구역 도형에 밸브를 매는 두 번째 판정자를 만들었다가 걷어냈다.**
      담당 폴리곤이 이미 있는데 구역 단위로 묶었더니 값이 틀렸다 — 나주
      배밭은 v11·v12 가 각각 절반(510,000 / 512,900 L/h)을 맡는데, 구역으로
      묶으면 2,205개가 통째로 한 밸브에 얹혀 918,750 L/h 가 됐다.
    """

    def _src(self, name):
        import inspect
        return inspect.getsource(getattr(PJ, name))

    def test_open_field_no_longer_gives_up(self):
        self.assertIn('_open_field_flow(plot)',
                      self._src('irrigation_flow_for_plot'))

    def test_the_valve_area_decides_the_owner(self):
        """담당 폴리곤이 정본이다 — 노즐 임자를 다시 정하지 않는다."""
        src = self._src('_open_field_flow')
        self.assertIn('_device_area_shapes(oid)', src)
        self.assertIn('region.intersection(poly)', src)

    def test_no_second_owner_rule_came_back(self):
        """구역↔밸브 지정을 되살리지 말 것 — 담당 폴리곤과 갈라지고,
        갈라지면 한쪽이 틀린 값을 낸다."""
        import inspect
        from aot.aot_flask.geo import device_binding
        self.assertFalse(hasattr(device_binding, 'set_zone_valve'))
        self.assertFalse(hasattr(device_binding, 'ZONE_IRRIGATION_ROLE'))
        self.assertNotIn('zone_id', self._src('_open_field_flow'))

    def test_markers_are_not_treated_as_coverage(self):
        """`aot_device`(점)는 위치일 뿐 담당 구역이 아니다."""
        self.assertIn("row.type != 'device'", self._src('_device_area_shapes'))

    def test_several_areas_for_one_valve_are_unioned(self):
        """한 밸브가 담당 도형을 여럿 가질 수 있다 — 합집합으로 모아야
        겹치는 노즐을 두 번 세지 않는다."""
        self.assertIn('region.union(area)', self._src('_open_field_flow'))

    def test_the_actuator_list_is_the_same_one_the_table_uses(self):
        """여기서 따로 찾으면 두 목록이 갈라져, 표에 있는 장치의 물량이
        비거나 없는 장치의 물량이 생긴다."""
        self.assertIn('plot_context.actuators_for_plot(plot)',
                      self._src('_open_field_flow'))

    def test_circle_sprinklers_use_their_stored_centre(self):
        """그리기 도구가 원으로 저장한 것은 기하가 아니라 center_lat/lng 에
        중심을 둔다 — 기하만 보면 그 노즐이 통째로 빠진다."""
        self.assertIn("props.get('center_lat')", self._src('_sprinkler_point'))

    def test_the_canonical_emitter_is_counted(self):
        """`sub_type='sprinkler'` 은 그리기 도중의 점 마커라 같은 자리에
        여러 벌이 쌓인다 — 실측(나주)에서 이미터 274개짜리 과수원에 마커가
        2,466개였고, 그것을 세는 바람에 일지가 513,630 L 를 냈다(사람이 셈한
        값은 19,180 L). 정본은 `sprinkler_coverage` 이고 그 규칙은
        `aot-geo-stats.js` 에 이미 적혀 있다(디자인 개요가 그것으로 센다)."""
        self.assertEqual(PJ._EMITTER_SUB_TYPE, 'sprinkler_coverage')
        self.assertIn('_EMITTER_SUB_TYPE', self._src('_map_sprinklers'))

    def test_the_ephemeral_marker_is_not_counted(self):
        src = self._src('_map_sprinklers')
        self.assertNotIn("== 'sprinkler'", src)

    def test_the_counting_rule_matches_the_design_panel(self):
        """두 번째 계수 규칙을 만들지 말 것 — 갈라지면 디자인 개요와 일지가
        서로 다른 수량을 말한다."""
        import io as _io
        path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'aot_flask', 'static', 'js', 'geo', 'design', 'aot-geo-stats.js')
        js = _io.open(path, encoding='utf-8').read()
        self.assertIn('sprinkler_coverage is the canonical emitter', js)
        self.assertIn("subType === 'sprinkler_coverage'", js)

    def test_legacy_emitters_fall_back_to_the_zone_default(self):
        """유량이 비어 있는 옛 이미터는 그 구역의 기본값으로 채운다 —
        디자인 개요가 하는 backfill 과 같다."""
        self.assertIn('gen_config_sprinkler',
                      self._src('_zone_emitter_defaults'))

    def test_the_document_says_which_basis_it_used(self):
        """나누는 방식이 아예 다르다(동의 몫 · 담당 폴리곤 ∩ 구획) — 한
        문장으로 뭉치면 어느 쪽으로 나눈 값인지 알 수 없다."""
        facility = PJ.caveat_text('water-estimated')
        field = PJ.caveat_text('water-estimated-map')
        self.assertNotEqual(facility, field)
        self.assertIn('sprinkler', field)

    def test_the_source_rides_along_with_the_volume(self):
        """물량 행이 근거를 들고 다니지 않으면 조립부가 알 길이 없어,
        시설용 문장이 노지 문서에 붙는다(실측으로 그랬다)."""
        self.assertIn("'source': flow.get('source')",
                      self._src('control_rows_by_bucket'))


class TestSilentOutputs(unittest.TestCase):
    """기록을 남기지 않은 장치는 **표에서 빠지고, 문서가 그것을 말한다.**

    나주 배 구획이 그랬다 — v11·v12 가 구획을 반씩 맡는데 v11 은 기록이
    2026-08-19 하루뿐이라 8/28~9/2 문서에서 통째로 빠졌다. 표만 보면 밸브가
    하나뿐인 것처럼 보이고, 나머지가 없는 것인지 고장인지 알 수 없다.
    """

    def _src(self, name):
        import inspect
        return inspect.getsource(getattr(PJ, name))

    def test_silent_devices_are_collected(self):
        src = self._src('control_rows_by_bucket')
        self.assertIn('silent.append(', src)
        self.assertIn('return out, errors, silent', src)

    def test_they_are_not_written_down_as_zero_hours(self):
        """안 돌았다는 것과 기록이 없다는 것은 다르다 — 0 으로 적으면
        "그 기간에 한 번도 안 켰다" 는 거짓 사실이 문서에 남는다."""
        text = PJ.caveat_text('outputs-no-record:v11')
        self.assertIn('v11', text)
        self.assertIn('zero hours', text)

    def test_several_names_are_listed(self):
        text = PJ.caveat_text('outputs-no-record:v11,v21')
        self.assertIn('v11', text)
        self.assertIn('v21', text)

    def test_the_caveat_only_fires_when_something_is_missing(self):
        src = self._src('build_journal_for_target')
        self.assertIn('if silent_outputs:', src)


class TestTargetColumns(unittest.TestCase):
    """목표·Δ 열은 **목표가 실제로 있을 때만** 낸다.

    구획이라는 이유만으로 켜면 프로그램이 없는 구획에서 두 열이 문서 내내
    빈다 — 빈 열은 "계산이 안 된다" 로 읽힌다(관수량 열과 같은 판단).
    실측: 나주 배 구획은 프로그램이 없어 10개 구간 전부가 빈 열 둘을 달고
    있었다.
    """

    def test_no_program_means_no_target_columns(self):
        doc = {'buckets': [{'env': [{'measurement': 'temperature',
                                     'target': None}]}]}
        self.assertFalse(PJ.has_any_target(doc))

    def test_a_plain_target_counts(self):
        doc = {'buckets': [{'env': [{'measurement': 'temperature',
                                     'target': 25.0}]}]}
        self.assertTrue(PJ.has_any_target(doc))

    def test_a_target_that_is_not_differenced_still_counts(self):
        """주야 목표·곡선 목표는 **있지만 견주지 않는** 것이다 — 그때 화면은
        "주야 목표" 라고 적어야 하고, 적을 자리가 없으면 그 사실이 사라진다."""
        for row in ({'delta_skipped': 'when'}, {'follows_curve': 'vpd'}):
            self.assertTrue(PJ.has_any_target({'buckets': [{'env': [row]}]}))

    def test_a_stage_target_is_enough_even_without_bucket_rows(self):
        """단계 안에 목표가 실제로 있으면 버킷에 없어도 열이 필요하다 —
        단계 절이 그 목표를 낸다."""
        self.assertTrue(PJ.has_any_target(
            {'buckets': [], 'stages': [{'targets': [
                {'key': 'temp_day', 'value': 25}]}]}))

    def test_empty_stage_targets_do_not_turn_on_the_columns(self):
        """단계가 있다는 사실만으로는 부족하다 — **그 단계 안에 목표가
        있어야** 한다. 예전에는 `bool(stages)` 만 봐서, 단계는 있지만 그
        안의 `targets` 가 전부 빈 리스트인 문서도 참이 났다 — 실측(대선/콩):
        6단계 전부 `targets: []` 인데 21개 구간 내내 빈 목표·Δ 열이 붙어
        있었다. 프로그램이 아예 없는 구획(빈 목표 열)과 같은 증상이 다른
        경로로 재발한 것이다."""
        self.assertFalse(PJ.has_any_target(
            {'buckets': [], 'stages': [{'targets': []}, {'targets': []}]}))
        self.assertFalse(PJ.has_any_target(
            {'buckets': [], 'stages': [{'key': 'stage_1', 'name': 'x'}]}))

    def test_the_template_asks_for_both(self):
        import io as _io
        src = _io.open(os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'aot_flask', 'templates', 'pages', 'geo',
            'journal_view.html'), encoding='utf-8').read()
        # 줄을 통째로 고정하지 않는다 — `d` 가 없는 순간(생성 직후 첫 렌더)을
        # 막는 가드가 나중에 붙었다. 고정할 것은 **두 조건이 모두 걸린다**는
        # 사실이다.
        line = next(l for l in src.splitlines() if 'set show_target' in l)
        self.assertIn("d.target.type == 'plot'", line)
        self.assertIn('has_targets', line)


class TestNearestSensorFallback(unittest.TestCase):
    """구획 안에 센서가 없으면 **같은 구역에서 가장 가까운 하나**를 쓴다.

    지도 위젯이 그렇게 한다(`routes_geo_plot` → `plot_context.nearest_devices`,
    scope 'nearest' 배지). 일지가 구역 센서를 전부 쓰면 한 구역에 든 구획들의
    문서가 서로 같아진다 — 실측으로 21개 구획이 그 상태였고 셋씩 같은 센서
    목록을 갖고 있었다.
    """

    def _src(self, name):
        import inspect
        return inspect.getsource(getattr(PJ, name))

    def test_the_zone_step_uses_the_shared_resolver(self):
        """판정을 새로 만들지 않는다 — 위젯이 쓰는 함수를 그대로 부른다."""
        src = self._src('_plot_sensor_ids')
        self.assertIn('plot_context.nearest_devices(', src)
        self.assertIn('limit=1', src)

    def test_the_nearer_steps_are_untouched(self):
        """구획 안·동·시설 센서가 있으면 그것이 그대로 이긴다 — 최근접은
        **구역으로 내려갈 때만** 끼어든다."""
        src = self._src('_plot_sensor_ids')
        i = src.index("get('from_facility')")
        j = src.index('nearest_devices(')
        self.assertLess(i, j)

    def test_a_plot_without_geometry_keeps_the_whole_zone(self):
        """시설 구획은 자기 기하가 없어 "가깝다" 를 말할 수 없다 — 그때
        빈 손으로 두면 센서가 통째로 사라진다."""
        self.assertIn('ids = zone_ids', self._src('_plot_sensor_ids'))

    def test_liveness_is_not_copied_from_the_widget(self):
        """위젯은 "지금 값을 안 주면 없는 것으로 친다"(stale)를 함께 쓰지만
        일지는 지나간 기간의 기록이다 — 오늘 죽은 센서가 그때는 값을 냈을 수
        있고, 오늘 상태로 과거 문서의 센서를 바꾸면 같은 기간의 일지가 만들
        때마다 달라진다."""
        import ast
        import inspect
        # ⚠ 주석을 빼고 본다 — 그 함수의 설명이 바로 "stale 규칙은 따르지
        #   않는다" 라고 적고 있어, 문자열로 검사하면 자기 설명에 걸린다.
        tree = ast.parse(inspect.getsource(PJ._plot_sensor_ids))
        self.assertNotIn('stale', ast.unparse(tree).lower())

    def test_the_distance_is_written_down(self):
        text = PJ.caveat_text('sensor-from-zone:36')
        self.assertIn('36', text)
        self.assertIn('zone', text)

    def test_the_document_does_not_call_it_a_reading_of_this_plot(self):
        """"가장 가까운 값" 과 "이 구획의 값" 은 다르다 — 인증 문서로 나간다."""
        text = PJ.caveat_text('sensor-from-zone:36')
        self.assertIn('not a reading of this plot', text)


class TestJournalMcpTools(unittest.TestCase):
    """MCP 로 LLM 에게 열린 일지 도구 3종.

    실측으로 드러난 것들을 고정한다 — 도구가 있다는 것과 쓸 수 있다는 것은
    다르다.
    """

    def _svc(self):
        import inspect
        from aot.ai.services.aot_data_tool_service import AoTDataToolService
        return AoTDataToolService, inspect

    def test_reading_a_long_journal_can_be_narrowed(self):
        """캡이 가장 큰 필드를 떨어뜨리는데 그것이 하필 `env`(측정값)라,
        **6일짜리 일지도 측정값 0개**로 나갔다(20,153토큰 → 2,168). 캡의
        안내는 "하나씩 물어봐라" 인데 좁힐 인자가 없었다."""
        S, inspect = self._svc()
        src = inspect.getsource(S.get_plot_journal)
        self.assertIn('granularity', src)
        self.assertIn('date_from', src)
        self.assertIn('PJ.fold_buckets(', src)

    def test_it_cannot_ask_for_finer_than_stored(self):
        """없는 정보를 지어내지 않는다 — 저장 단위가 무엇인지 말해 준다."""
        S, inspect = self._svc()
        self.assertIn('cannot ', inspect.getsource(S.get_plot_journal))

    def test_a_long_journal_says_how_to_narrow(self):
        """캡의 안내는 무엇으로 좁히는지 모른다 — 도구가 말해 준다.
        최상위 문자열이라 캡이 리스트 필드를 떨어뜨려도 남는다."""
        S, inspect = self._svc()
        self.assertIn("data['hint']", inspect.getsource(S.get_plot_journal))

    def test_listing_does_not_demand_a_target(self):
        """화면의 허브는 전체를 보여 주는데 도구만 못 봤다 — "저장된 일지
        보여줘" 에 답하려고 먼저 구획 uuid 를 알아내야 했다."""
        S, inspect = self._svc()
        src = inspect.getsource(S.list_plot_journals)
        self.assertIn('if target_type is not None', src)
        self.assertNotIn('return {"error": "target_id is required"}', src)

    def test_creating_waits_instead_of_forking(self):
        """MCP stdio 는 연결이 끊기면 프로세스가 죽는다 — 백그라운드 스레드를
        띄우면 시작하자마자 함께 죽고 행이 영영 'running' 으로 남는다
        (실측: 5분 뒤에도 버킷 0)."""
        S, inspect = self._svc()
        self.assertIn('wait=True', inspect.getsource(S.create_plot_journal))

    def test_creating_rereads_with_a_fresh_session(self):
        """빌드는 자기 app context 에서 따로 커밋한다 — 바깥 세션의 identity
        map 에는 아직 'pending' 인 옛 행이 남아, 다 만들어 놓고 "아직 만드는
        중" 이라고 답했다(실측)."""
        S, inspect = self._svc()
        self.assertIn('db.session.expire_all()',
                      inspect.getsource(S.create_plot_journal))

    def test_creating_uses_the_same_cost_gate_as_the_screen(self):
        """게이트가 따로 세면 통과해 놓고 다른 규모로 돈다."""
        S, inspect = self._svc()
        self.assertIn('PJ.estimate_journal_cost(',
                      inspect.getsource(S.create_plot_journal))

    def test_creating_needs_approval(self):
        """처음에는 "생성은 사람이 고르는 상호작용" 이라 열지 않았다. 열면서
        그 성질을 지키는 수단이 승인 게이트다 — 사람이 대상·기간을 보고
        승인해야 실제로 돈다."""
        from aot.ai.services import tool_registry as R
        self.assertIn('create_plot_journal', R.virtual_approval_tools())

    def test_creating_is_not_marked_physical(self):
        """아무것도 작동시키지 않는다 — 비싼 조회일 뿐이다."""
        from aot.ai.services import tool_registry as R
        t = next(t for t in R.TOOLS if t.name == 'create_plot_journal')
        self.assertTrue(t.mutating)
        self.assertFalse(getattr(t, 'physical', False))

    def test_the_background_path_still_exists_for_the_web(self):
        """웹은 요청을 막으면 안 된다 — 거기서는 스레드가 맞다."""
        import inspect
        self.assertIn('threading.Thread(target=_work',
                      inspect.getsource(PJ._run_journal_build))


class TestFoldPhaseAverages(unittest.TestCase):
    """접기(fold) 시 주간·야간 평균 — WP1-1.

    `_merge_bucket_group` 이 `dict(members[0])` 로 시작해 전체 평균(`avg`)은
    다시 표본 가중으로 구하면서 `avg_day`/`avg_night` 는 첫날 값을 그대로
    남겼다. 실측(대선/콩, 8/22~8/28 주간 접기): 강수 전체 평균(0.07)이
    주·야 평균(0.38 / 0.30) 둘보다 작게 나오는 — 산술적으로 있을 수 없는 —
    결과가 났다.
    """

    @staticmethod
    def _day(key, avg_day, samples, avg_night=None, avg=None):
        return {'key': key, 'date_label': key, 'empty': False, 'notes': [],
                'env': [{'device_id': 'w', 'channel': 3, 'sensor': 'weather',
                         'measurement': 'temperature', 'unit': 'C',
                         'scope': 'outdoor',
                         'min': avg_day - 1, 'max': avg_day + 1,
                         'avg': avg if avg is not None else avg_day,
                         'avg_day': avg_day, 'avg_night': avg_night,
                         'samples': samples, 'expected': samples}],
                'control': []}

    def test_avg_day_is_recomputed_not_copied_from_the_first_day(self):
        buckets = [self._day('2026-08-01', avg_day=10.0, samples=1),
                   self._day('2026-08-02', avg_day=30.0, samples=3)]
        out = PJ.fold_buckets(buckets, to='month', granularity='day')
        row = out[0]['env'][0]
        # 표본 가중 평균: (10*1 + 30*3) / 4 = 25.0. 예전 결함은 첫날 값
        # 10.0 을 그대로 남겼다.
        self.assertEqual(row['avg_day'], 25.0)
        self.assertNotEqual(row['avg_day'], 10.0)

    def test_avg_night_is_recomputed_the_same_way(self):
        buckets = [self._day('2026-08-01', avg_day=10.0, avg_night=10.0,
                             samples=1),
                   self._day('2026-08-02', avg_day=30.0, avg_night=30.0,
                             samples=3)]
        out = PJ.fold_buckets(buckets, to='month', granularity='day')
        self.assertEqual(out[0]['env'][0]['avg_night'], 25.0)

    def test_missing_phase_average_stays_none(self):
        """어느 날도 야간 자료가 없으면 접은 뒤에도 `None` 이어야 한다 —
        0 으로 지어내면 '야간에 0 이었다' 로 읽힌다."""
        buckets = [self._day('2026-08-01', avg_day=10.0, samples=1),
                   self._day('2026-08-02', avg_day=30.0, samples=3)]
        out = PJ.fold_buckets(buckets, to='month', granularity='day')
        self.assertIsNone(out[0]['env'][0]['avg_night'])

    def test_the_impossible_result_cannot_recur(self):
        """전체 평균은 주·야 평균 사이(또는 둘과 같음)에 있어야 한다 —
        실측에서 전체 평균이 둘 다보다 작게 나온 것이 이 결함의 증상이었다."""
        buckets = [self._day('2026-08-01', avg_day=5.0, avg_night=25.0,
                             avg=15.0, samples=10),
                   self._day('2026-08-02', avg_day=5.0, avg_night=25.0,
                             avg=15.0, samples=10)]
        out = PJ.fold_buckets(buckets, to='month', granularity='day')
        row = out[0]['env'][0]
        lo, hi = min(row['avg_day'], row['avg_night']), \
            max(row['avg_day'], row['avg_night'])
        self.assertTrue(lo - 1e-9 <= row['avg'] <= hi + 1e-9,
                        'avg=%s not within [%s, %s]' % (row['avg'], lo, hi))

    def test_delta_is_also_sample_weighted_now(self):
        """부수 결함 — Δ 도 `avg` 와 같은 가중치로 접어야 한다. 단순 평균이면
        표본이 하루뿐인 날과 온종일인 날이 같은 무게를 갖는다."""
        def day(key, delta, samples):
            return {'key': key, 'date_label': key, 'empty': False,
                    'notes': [], 'control': [],
                    'env': [{'device_id': 'w', 'channel': 0, 'sensor': 's',
                             'measurement': 'temperature', 'unit': 'C',
                             'scope': 'indoor', 'min': 0, 'max': 0, 'avg': 0,
                             'delta': delta, 'samples': samples,
                             'expected': samples}]}
        buckets = [day('2026-08-01', 10.0, 1), day('2026-08-02', 30.0, 3)]
        out = PJ.fold_buckets(buckets, to='month', granularity='day')
        self.assertEqual(out[0]['env'][0]['delta'], 25.0)


class TestOutdoorTargetAttachment(unittest.TestCase):
    """기상대 값에 재배 목표를 붙이지 않는다 — WP1-4.

    "실내/실외" 가 아니라 **현장 센서 vs 기상대 센서** 로 가른다(노지에는
    실내가 없다). 실측(설원6/딸기): 기상대 습도 평균 87.83% 옆에 재배 목표
    65%·Δ 22.83 이 그대로 붙어 있었다.
    """

    def test_field_sensor_gets_the_target(self):
        rows = [{'measurement': 'humidity', 'scope': 'indoor', 'avg': 70.0}]
        targets = [{'measurement': 'humidity', 'value': 65.0,
                   'label': 'Humidity'}]
        PJ.attach_targets(rows, targets)
        self.assertEqual(rows[0]['target'], 65.0)

    def test_weather_station_is_skipped_when_a_field_sensor_exists(self):
        rows = [{'measurement': 'humidity', 'scope': 'indoor', 'avg': 70.0},
               {'measurement': 'humidity', 'scope': 'outdoor', 'avg': 90.0}]
        targets = [{'measurement': 'humidity', 'value': 65.0,
                   'label': 'Humidity'}]
        PJ.attach_targets(rows, targets)
        outdoor = next(r for r in rows if r['scope'] == 'outdoor')
        self.assertIsNone(outdoor['target'])
        self.assertIsNone(outdoor['delta'])

    def test_weather_station_alone_still_gets_the_target(self):
        """노지처럼 기상대뿐인 구획(예: 대선/콩)에서는 기상대가 곧 재배
        환경이다 — 현장 센서가 없으면 그대로 붙인다."""
        rows = [{'measurement': 'humidity', 'scope': 'outdoor', 'avg': 90.0}]
        targets = [{'measurement': 'humidity', 'value': 65.0,
                   'label': 'Humidity'}]
        PJ.attach_targets(rows, targets)
        self.assertEqual(rows[0]['target'], 65.0)

    def test_view_time_defense_hides_targets_baked_into_old_journals(self):
        """생성 시점 결함으로 이미 저장된 옛 일지도 열람 시 가려야 한다 —
        재생성 전까지 계속 열리는 문서라 방어가 없으면 그대로 남는다."""
        rows = [{'measurement': 'humidity', 'unit': 'percent',
                'scope': 'indoor', 'sensor': 'a', 'avg': 70.0,
                'target': 65.0, 'delta': 5.0, 'samples': 24},
               {'measurement': 'humidity', 'unit': 'percent',
                'scope': 'outdoor', 'sensor': 'w', 'avg': 90.0,
                'target': 65.0, 'delta': 25.0, 'samples': 24}]
        groups = PJ.group_env_rows(rows)
        outdoor = next(g for g in groups if g['scope'] == 'outdoor')
        indoor = next(g for g in groups if g['scope'] == 'indoor')
        self.assertIsNone(outdoor['sensors'][0]['target'])
        self.assertIsNone(outdoor['sensors'][0]['delta'])
        self.assertEqual(indoor['sensors'][0]['target'], 65.0)


class TestFoldCoverageDenominator(unittest.TestCase):
    """커버리지 분모 — WP1-5.

    `expected = sum(r.get('expected') ...)` 는 그 채널이 **있었던 날만**
    더한다 — 채널이 하루 통째로 안 잡힌 날은 분모에서도 사라져 커버리지가
    실제보다 좋게 나온다. 실측(대선 8/15 주): 7일 중 5일만 데이터인데
    `coverage 0.858`(실제 61%에 가까움)로 나왔다.
    """

    @staticmethod
    def _day(key, include):
        env = []
        if include:
            env.append({'device_id': 'w', 'channel': 5, 'sensor': 'weather',
                        'measurement': 'precipitation', 'unit': 'none',
                        'scope': 'outdoor', 'min': 0, 'max': 1, 'avg': 0.1,
                        'samples': 24, 'expected': 24})
        return {'key': key, 'date_label': key, 'empty': not include,
                'env': env, 'control': [], 'notes': []}

    def test_missing_days_count_against_coverage(self):
        # 7일 중 이틀(3·4일)은 이 채널이 통째로 빠졌다.
        buckets = [self._day('2026-08-%02d' % d, d not in (3, 4))
                  for d in range(1, 8)]
        out = PJ.fold_buckets(buckets, to='all', granularity='day')
        row = out[0]['env'][0]
        self.assertEqual(row['samples'], 5 * 24)
        # 예전 결함: expected = 5*24 = 120 (있었던 날만). 고친 뒤에는
        # 7일 전체 = 168 이어야 한다.
        self.assertEqual(row['expected'], 7 * 24)
        self.assertAlmostEqual(row['coverage'], (5 * 24) / (7 * 24), places=3)

    def test_no_gap_leaves_coverage_unchanged(self):
        buckets = [self._day('2026-08-%02d' % d, True) for d in range(1, 8)]
        out = PJ.fold_buckets(buckets, to='all', granularity='day')
        row = out[0]['env'][0]
        self.assertEqual(row['expected'], 7 * 24)
        self.assertEqual(row['coverage'], 1.0)


class TestGddFutureEndDate(unittest.TestCase):
    """진행 중인 작기의 적산온도 — WP1-3.

    `gdd_accumulated` 는 `on`(없으면 `date.today()`)을 자신의 "오늘" 로
    삼아 `days_expected` 를 그 날까지만 센다. 일지의 **미래 종료일**을
    그대로 넘기면 그 함수의 "오늘" 자체가 미래로 밀려, 아직 오지 않은
    날까지 기대일수에 들어간다 — 실측(설원6/딸기, 종료일 2026-12-22):
    `days_expected=118` vs `days_counted=9` → `coverage_pct=7.6%` →
    `usable=False`. 작기 도중에 일지를 뽑는 것이 정상 사용인데 이 경로로는
    GDD 가 항상 죽는다.
    """

    def test_future_end_date_is_clamped_to_today(self):
        from datetime import timedelta
        from unittest import mock

        captured = {}

        def fake_gdd_accumulated(plot, program, on=None, with_series=False):
            captured['on'] = on
            return {'usable': True, 'reason': None, 't_base': 5.0,
                    'value': 10.0, 'days_counted': 1, 'days_expected': 1,
                    'coverage_pct': 100.0, 'series': [(on, 10.0)]}

        fake_plot = type('P', (), {'unique_id': None,
                                   'program_uuid': 'prog-x'})()
        fake_program = object()
        future_end = date.today() + timedelta(days=365)

        with mock.patch.object(PJ.plot_context, 'gdd_accumulated',
                              side_effect=fake_gdd_accumulated), \
             mock.patch('aot.databases.models.GeoProgram') as MockProgram:
            MockProgram.query.filter_by.return_value.first.return_value = \
                fake_program
            PJ.gdd_for_journal(fake_plot, future_end)

        self.assertLessEqual(captured['on'], date.today())
        self.assertLess(captured['on'], future_end)

    def test_past_end_date_is_not_touched(self):
        from unittest import mock

        captured = {}

        def fake_gdd_accumulated(plot, program, on=None, with_series=False):
            captured['on'] = on
            return {'usable': True, 'reason': None, 't_base': 5.0,
                    'value': 10.0, 'days_counted': 1, 'days_expected': 1,
                    'coverage_pct': 100.0, 'series': [(on, 10.0)]}

        fake_plot = type('P', (), {'unique_id': None,
                                   'program_uuid': 'prog-x'})()
        past_end = date(2020, 1, 1)

        with mock.patch.object(PJ.plot_context, 'gdd_accumulated',
                              side_effect=fake_gdd_accumulated), \
             mock.patch('aot.databases.models.GeoProgram') as MockProgram:
            MockProgram.query.filter_by.return_value.first.return_value = \
                object()
            PJ.gdd_for_journal(fake_plot, past_end)

        self.assertEqual(captured['on'], past_end)


class TestFieldSensorVsWeatherStationLabel(unittest.TestCase):
    """표의 측정값 이름 — WP2-1.

    "실내/실외" 가 아니라 **현장 센서 vs 기상대 센서** 로 가른다(노지에는
    실내가 없다). 좌측 색 막대만으로는 구별이 안 된다는 것이 실사용
    검토에서 나왔다 — "온도" 두 행이 나란히 있는데 어느 쪽이 기상대인지
    표에 없었다.
    """

    def test_weather_station_gets_a_qualifier_when_a_field_sensor_exists(self):
        rows = [{'measurement': 'temperature', 'unit': 'C', 'scope': 'indoor',
                'sensor': '온습도_6', 'avg': 28.0, 'samples': 24},
               {'measurement': 'temperature', 'unit': 'C', 'scope': 'outdoor',
                'sensor': '기상청', 'avg': 27.0, 'samples': 24}]
        groups = PJ.group_env_rows(rows)
        outdoor = next(g for g in groups if g['scope'] == 'outdoor')
        indoor = next(g for g in groups if g['scope'] == 'indoor')
        self.assertIn('Weather station', outdoor['measurement_label'])
        self.assertNotIn('Weather station', indoor['measurement_label'])

    def test_weather_only_target_keeps_the_plain_name(self):
        """기상대뿐인 구획(노지)에서는 헷갈릴 짝이 없다 — 덧붙일 이유가
        없다."""
        rows = [{'measurement': 'temperature', 'unit': 'C', 'scope': 'outdoor',
                'sensor': '기상청', 'avg': 27.0, 'samples': 24}]
        groups = PJ.group_env_rows(rows)
        self.assertNotIn('Weather station', groups[0]['measurement_label'])

    def test_qualifier_wraps_the_users_own_channel_name_too(self):
        """단일 센서라 채널 이름을 그대로 쓰는 경우에도 기상대 쪽은
        구별돼야 한다 — 채널 이름이 서로 같을 수 있다(둘 다 '온도')."""
        rows = [{'measurement': 'temperature', 'unit': 'C', 'scope': 'indoor',
                'sensor': 'a', 'channel_name': '온도', 'avg': 28.0,
                'samples': 24},
               {'measurement': 'temperature', 'unit': 'C', 'scope': 'outdoor',
                'sensor': 'w', 'channel_name': '온도', 'avg': 27.0,
                'samples': 24}]
        groups = PJ.group_env_rows(rows)
        outdoor = next(g for g in groups if g['scope'] == 'outdoor')
        self.assertIn('Weather station', outdoor['measurement_label'])
        self.assertIn('온도', outdoor['measurement_label'])


class TestUnitLabel(unittest.TestCase):
    """단위 사람화 — WP2-2.

    실측: 표에 `28.74 C`·`71.27 percent`·`0.19 none`·`0.26 m_s` 처럼
    DeviceMeasurements 원문 단위 키가 그대로 나갔다. `UNITS`(정본)에 이미
    `°C`·`%`·(빈 문자열)·`m/s` 가 있는데 그것을 쓰지 않고 있었다.
    """

    def test_celsius_becomes_the_degree_symbol(self):
        self.assertEqual(PJ.unit_label('C'), '°C')

    def test_percent_becomes_the_percent_sign(self):
        self.assertEqual(PJ.unit_label('percent'), '%')

    def test_none_unit_becomes_empty_not_the_word_none(self):
        """`0.19 none` 처럼 없는 단위를 글자로 박지 않는다."""
        self.assertEqual(PJ.unit_label('none'), '')

    def test_m_s_becomes_a_slash(self):
        self.assertEqual(PJ.unit_label('m_s'), 'm/s')

    def test_unknown_unit_falls_back_to_itself(self):
        """모르는 단위는 지어내지 않는다 — 원문 키 그대로."""
        self.assertEqual(PJ.unit_label('a-made-up-unit'), 'a-made-up-unit')

    def test_empty_stays_empty(self):
        self.assertEqual(PJ.unit_label(None), '')
        self.assertEqual(PJ.unit_label(''), '')

    def test_dli_unit_is_not_in_the_canonical_table(self):
        """DLI 는 일지가 직접 적분해 만드는 파생값이라 `DeviceMeasurements`
        정의(UNITS)에 없다 — 그래도 지어내지 않고 로컬 오버라이드로 낸다."""
        self.assertEqual(PJ.unit_label('mol_m2_d'), 'mol/m²/d')


class TestDisplayAvg(unittest.TestCase):
    """MD·ODT 내보내기의 평균값 표시 — WP2-2·2-3.

    HTML 과 같은 두 규칙을 공유한다: 방위는 각도가 아니라 최다 풍향으로,
    단위는 원문 키가 아니라 사람이 읽는 기호로.
    """

    def test_plain_value_gets_a_human_unit(self):
        self.assertEqual(PJ._display_avg({'avg': 28.74, 'unit': 'C'}),
                         '28.74 °C')

    def test_direction_shows_the_compass_name_not_the_angle(self):
        text = PJ._display_avg({'avg': 74.68, 'unit': 'bearing',
                                'sector': 2, 'sector_pct': 21})
        self.assertNotIn('74.68', text)
        self.assertIn('21%', text)

    def test_none_avg_is_blank(self):
        self.assertEqual(PJ._display_avg({'avg': None, 'unit': 'C'}), '')


class TestMarkdownExportIsTranslatable(unittest.TestCase):
    """Markdown 내보내기의 헤더·문구 — WP2-5.

    실측: `## Overview`·`## Program stages`·`## Log`·표 머리(Sensor/
    Measurement/...)·`(ongoing)`·`— planned`·사진 안내문이 영어로 고정돼
    있었다. HTML(§10)은 뷰어 언어로 나가는데 MD 만 굳어 있었다 — 여기서는
    요청 컨텍스트가 없어(순수 유닛 테스트) `_gettext_safe` 가 전부 원문
    (영어)으로 떨어지지만, **문구가 하드코딩이 아니라 함수를 거쳐 나오는지**
    는 소스 검사로 고정한다. 실제 번역은 `test_geo_journal_view.py` 밖의
    ko/ja `.po` 항목이 담당한다.
    """

    @staticmethod
    def _data():
        return {
            'target': {'type': 'plot', 'name': '설원6', 'kind': 'vegetation',
                      'tz_name': 'Asia/Seoul',
                      'period': {'start': '2026-08-01', 'end': '2026-08-02',
                                'ongoing': True}},
            'granularity': 'day', 'stages': [], 'caveats': [
                'daily-average-is-mean-of-hourly-means'],
            'buckets': [{
                'key': '2026-08-01', 'date_label': '2026-08-01', 'empty': False,
                'env': [{'sensor': '온습도_6', 'measurement': 'humidity',
                        'unit': 'percent', 'min': 50.0, 'max': 80.0,
                        'avg': 65.0, 'samples': 24, 'expected': 24,
                        'scope': 'indoor'},
                       {'sensor': '기상청', 'measurement': 'direction',
                        'unit': 'bearing', 'circular': True, 'sector': 3,
                        'sector_pct': 25, 'avg': 111.0, 'samples': 24,
                        'expected': 24, 'scope': 'outdoor'}],
                'control': [{'name': 'v321', 'hours': 1.5}],
                'notes': [],
            }, {
                'key': '2026-08-02', 'date_label': '2026-08-02',
                'empty': True, 'gap_count': 1,
            }],
        }

    def test_renders_without_crashing(self):
        text = PJ.render_plot_journal_markdown(self._data())
        self.assertIsInstance(text, str)
        self.assertGreater(len(text), 0)

    def test_the_literal_english_headings_are_gone(self):
        """헤더가 문자열 리터럴로 박혀 있지 않고 `_gettext_safe` 를 거쳐야
        번역이 걸린다 — 소스에서 하드코딩 재발을 잡는다."""
        import inspect
        src = inspect.getsource(PJ.render_plot_journal_markdown)
        for literal in ("'## Overview'", "'## Program stages'", "'## Log'",
                       "'| Sensor | Measurement", "' (ongoing)'",
                       "'— planned'", "'_Generated: %s_'"):
            self.assertNotIn(literal, src,
                            '%r 이 여전히 하드코딩돼 있다' % literal)

    def test_direction_shows_compass_not_a_bare_angle(self):
        """WP2-3 — MD 도 방위로 말해야 한다(HTML 과 같은 규칙)."""
        text = PJ.render_plot_journal_markdown(self._data())
        self.assertNotIn('111.0', text)

    def test_no_data_gap_message_survives(self):
        text = PJ.render_plot_journal_markdown(self._data())
        self.assertIn('No data recorded', text)

    def test_ongoing_period_is_marked(self):
        text = PJ.render_plot_journal_markdown(self._data())
        self.assertIn('ongoing', text)


class TestWaterPartialCoverageCaveat(unittest.TestCase):
    """일부 장치만 관수량이 비는 이유 — WP2-7.

    실측(대선/콩): v331 은 관수량이 나오는데 v332 는 문서 내내 빈칸이었고,
    왜 비는지 표 어디에도 없었다. **`kind`(밸브가 관수인지)는 채울 수
    없다** — Output 은 통신 방식만 알 뿐 의미 분류가 없다는 것이 이
    저장소가 이미 확인한 사실이다(`_area_actuators`·`actuators_for_plot`
    주석 — "그 장치가 물을 주는지 빛을 주는지 시스템은 모른다"). 그래서
    장치를 판정하는 대신 **이 열 자체의 한계**를 말한다.
    """

    def test_caveat_text_explains_the_blank_is_not_zero_water(self):
        text = PJ.caveat_text('water-partial-coverage')
        self.assertNotEqual(text, 'water-partial-coverage')
        self.assertIn('water', text.lower())

    def test_caveat_fires_only_when_some_but_not_all_devices_have_water(self):
        import inspect
        src = inspect.getsource(PJ.build_journal_for_target)
        self.assertIn("caveats.append('water-partial-coverage')", src)
        self.assertIn('_without_water', src)


class TestPrecipitationIsNotSummed(unittest.TestCase):
    """강수는 **합계를 내지 않는다** — 그리고 그 이유를 문서가 말한다.

    실측(기상청 입력 플러그인 `kma_weather_500.py`, 채널 6 = `rn_15m`):
    "직전 15분 누적 강수량" 을 **5분마다** 다시 적는다(원자료 3시간에
    36점). 창이 겹치므로 그대로 더하면 같은 비를 약 세 번 세고, 3으로
    나누면 그것은 기록이 아니라 지어낸 계수다 — 이 파일의 DLI 환산 규칙
    ("모르는 단위는 환산하지 않는다")과 같은 판단이다. 그래서 합계 대신
    **왜 합계가 없는지와 각 열이 무엇인지**를 낸다.
    """

    def test_caveat_text_says_why_there_is_no_total(self):
        text = PJ.caveat_text('precipitation-not-summed')
        self.assertNotEqual(text, 'precipitation-not-summed')
        self.assertIn('total', text.lower())
        self.assertIn('overlap', text.lower())

    def test_caveat_fires_when_a_precipitation_channel_is_present(self):
        import inspect
        src = inspect.getsource(PJ.build_journal_for_target)
        self.assertIn("caveats.append('precipitation-not-summed')", src)
        self.assertIn("e.get('measurement') == 'precipitation'", src)

    def test_no_summing_helper_was_introduced_for_rain(self):
        """합계를 내는 코드가 생기면 이 판단이 조용히 뒤집힌다 — 겹치는
        창을 더하는 것이라 값이 그럴듯하게 틀린다."""
        import inspect
        src = inspect.getsource(PJ)
        self.assertNotIn('precipitation_total', src)
        self.assertNotIn("group_fn='sum'", src)


class TestMcpJournalCarriesLabelsAndSentences(unittest.TestCase):
    """MCP 로 읽는 쪽도 화면이 아는 것을 알아야 한다.

    저장 스냅샷은 `unit` 을 원문 키(`C`·`m_s`·`none`)로, `caveats` 를 키
    문자열로 들고 있다. 화면은 열람 시점에 기호·문장으로 바꿔 내는데 AI
    에게는 그 둘이 없어 "0.26 m_s" 를 그대로 옮기거나
    `measurements-excluded:rssi,snr` 를 스스로 해독해야 했다(실사용 점검).
    """

    @staticmethod
    def _src():
        import inspect
        from aot.ai.services.aot_data_tool_service import AoTDataToolService
        return inspect.getsource(AoTDataToolService.get_plot_journal)

    def test_units_map_is_added(self):
        src = self._src()
        self.assertIn("data['units'] = units", src)
        self.assertIn('PJ.unit_label(raw_unit)', src)

    def test_caveat_sentences_are_added(self):
        src = self._src()
        self.assertIn("data['caveat_texts']", src)
        self.assertIn('PJ.caveat_text(k)', src)

    def test_units_map_is_built_from_units_actually_used(self):
        """행마다 라벨을 끼우면 응답이 커져 캡이 `env` 를 먼저 버린다 —
        문서에 실제로 쓰인 단위만 작은 대응표로 낸다."""
        src = self._src()
        self.assertIn("for env_row in (bucket.get('env') or [])", src)
        self.assertNotIn("env_row['unit_label']", src)

    def test_judgment_material_is_added(self):
        """단위·문장까지가 "화면이 아는 것" 이었다. 화면은 그 위에서
        **판단 재료**를 더 만드는데(무엇이 결과 지표인지, 목표에서 어느
        쪽으로 얼마나 벗어났는지, 단계마다 얼마나 쌓았는지) 그것이 전부
        열람 시점 계산이라 AI 가 받는 응답에는 없었다."""
        src = self._src()
        self.assertIn("data['target_drift'] = drift", src)
        self.assertIn("data['derived_measurements']", src)
        self.assertIn("data['stage_summaries'] = summaries", src)

    def test_drift_is_counted_before_folding(self):
        """접힌 버킷으로 세면 "78일 중 78일" 의 분모가 보는 단위에 따라
        달라진다."""
        src = self._src()
        self.assertIn('raw_buckets = list(buckets)', src)
        self.assertIn('drift_source = [b for b in raw_buckets', src)

    def test_stage_summary_stays_small(self):
        """이 도구는 이미 캡에 걸려 `env` 를 먼저 버린다 — 길이가 기간에
        비례하는 필드를 더하지 않는다(버킷·측정값 행을 싣지 않는다)."""
        src = self._src()
        start = src.index('summaries.append({')
        block = src[start:src.index('})', start)]
        for heavy in ("'buckets'", "'env_groups'", "'trends'", "'control'"):
            self.assertNotIn(heavy, block)

    def test_current_is_not_reported_for_every_overlapping_stage(self):
        """`stage_sections` 의 `when` 은 기간과 겹치면 `'current'` 다 —
        읽는 쪽에는 "지금 진행 중" 으로 읽히는데 겹치는 단계가 다섯이면
        다섯이 '현재' 가 된다."""
        src = self._src()
        self.assertIn("'in_period' if sec.get('in_period')", src)


class TestEnvTrendSeries(unittest.TestCase):
    """일자별 기록 절 머리의 추세 요약 — WP4-2.

    `view_buckets`(라우트가 `group_env_rows()` 를 붙여 만든 것)에서
    측정값×scope 그룹별 시계열을 뽑는다. `AoTViz.trend`(WP3)에 그대로
    넘길 데이터 준비 단계라, DB 없이 순수 계산만으로 검증한다.
    """

    @staticmethod
    def _bucket(key, env_rows):
        groups = PJ.group_env_rows(env_rows)
        return {'key': key, 'date_label': key, 'env_groups': groups}

    def test_builds_one_series_per_measurement_and_scope(self):
        buckets = [
            self._bucket('d1', [
                {'measurement': 'temperature', 'unit': 'C', 'scope': 'indoor',
                'sensor': 'a', 'min': 20, 'max': 30, 'avg': 25, 'samples': 24},
                {'measurement': 'temperature', 'unit': 'C', 'scope': 'outdoor',
                'sensor': 'w', 'min': 18, 'max': 28, 'avg': 23, 'samples': 24}]),
            self._bucket('d2', [
                {'measurement': 'temperature', 'unit': 'C', 'scope': 'indoor',
                'sensor': 'a', 'min': 21, 'max': 31, 'avg': 26, 'samples': 24},
                {'measurement': 'temperature', 'unit': 'C', 'scope': 'outdoor',
                'sensor': 'w', 'min': 19, 'max': 29, 'avg': 24, 'samples': 24}]),
        ]
        out = PJ.env_trend_series(buckets)
        self.assertEqual(len(out), 2)
        scopes = {s['scope'] for s in out}
        self.assertEqual(scopes, {'indoor', 'outdoor'})
        indoor = next(s for s in out if s['scope'] == 'indoor')
        self.assertEqual([p['avg'] for p in indoor['points']], [25, 26])

    def test_circular_measurements_are_excluded(self):
        """방위를 선형 축에 얹으면 359 도와 0 도가 정반대 끝에 선다."""
        buckets = [self._bucket('d1', [
            {'measurement': 'direction', 'unit': 'bearing', 'scope': 'outdoor',
            'sensor': 'w', 'avg': 10, 'circular': True, 'sector': 0,
            'samples': 24}])]
        out = PJ.env_trend_series(buckets)
        self.assertEqual(out, [])

    def test_missing_bucket_leaves_a_gap_not_a_shift(self):
        """어떤 날 그 채널이 통째로 없으면 자리를 **비워야** 한다 — 건너뛰면
        뒤 점들이 앞으로 당겨져 날짜 간격이 실제와 달라진다."""
        buckets = [
            self._bucket('d1', [
                {'measurement': 'humidity', 'unit': 'percent', 'scope': 'indoor',
                'sensor': 'a', 'min': 50, 'max': 60, 'avg': 55, 'samples': 24}]),
            self._bucket('d2', []),   # 이 날은 이 채널이 통째로 빠졌다
            self._bucket('d3', [
                {'measurement': 'humidity', 'unit': 'percent', 'scope': 'indoor',
                'sensor': 'a', 'min': 52, 'max': 62, 'avg': 57, 'samples': 24}]),
        ]
        out = PJ.env_trend_series(buckets)
        self.assertEqual(len(out), 1)
        points = out[0]['points']
        self.assertEqual(len(points), 3)
        self.assertIsNone(points[1]['avg'])
        self.assertEqual(points[0]['avg'], 55)
        self.assertEqual(points[2]['avg'], 57)

    def test_target_uses_the_latest_bucket_not_the_first(self):
        """단계 전환으로 목표가 바뀌면 **구간 끝의 목표**를 쓴다 — 표의 Δ
        와 같은 규칙이다."""
        buckets = [
            self._bucket('d1', [
                {'measurement': 'temperature', 'unit': 'C', 'scope': 'indoor',
                'sensor': 'a', 'avg': 25, 'target': 22, 'samples': 24}]),
            self._bucket('d2', [
                {'measurement': 'temperature', 'unit': 'C', 'scope': 'indoor',
                'sensor': 'a', 'avg': 26, 'target': 28, 'samples': 24}]),
        ]
        out = PJ.env_trend_series(buckets)
        self.assertEqual(out[0]['target'], 28)

    def test_empty_input_returns_empty_list(self):
        self.assertEqual(PJ.env_trend_series([]), [])
        self.assertEqual(PJ.env_trend_series(None), [])


class TestControlTrendSeries(unittest.TestCase):
    """장치별 가동시간 시계열 — WP4-2. min/max 는 없다(하루에 값 하나)."""

    def test_one_series_per_device(self):
        buckets = [
            {'key': 'd1', 'control': [{'output_id': 'o1', 'name': 'v331',
                                       'hours': 2.0}]},
            {'key': 'd2', 'control': [{'output_id': 'o1', 'name': 'v331',
                                       'hours': 1.5},
                                      {'output_id': 'o2', 'name': 'v332',
                                       'hours': 3.0}]},
        ]
        out = PJ.control_trend_series(buckets)
        self.assertEqual(len(out), 2)
        v331 = next(s for s in out if s['output_id'] == 'o1')
        self.assertEqual([p['avg'] for p in v331['points']], [2.0, 1.5])

    def test_device_missing_a_day_gets_a_gap(self):
        buckets = [
            {'key': 'd1', 'control': [{'output_id': 'o1', 'name': 'v331',
                                       'hours': 2.0}]},
            {'key': 'd2', 'control': []},
        ]
        out = PJ.control_trend_series(buckets)
        self.assertIsNone(out[0]['points'][1]['avg'])

    def test_empty_input_returns_empty_list(self):
        self.assertEqual(PJ.control_trend_series([]), [])
        self.assertEqual(PJ.control_trend_series(None), [])


class TestCumulativeAndRangeReadDifferently(unittest.TestCase):
    """범위형(밴드)과 누적형(불릿)은 **마커 모양**으로 갈린다 (2026-09-04).

    실사용 지적: "GDD, DLI: 목표값 = now, 현재값 = band 사용. 나머지 측정값:
    반대로 설정 됨." 한 카드에 둘이 나란히 서면 세로선과 초록이 줄마다 반대
    뜻이 되는데 화면에 단서가 없었다.

    가르는 축은 **모양 하나**다 — 색은 실외 시인성 때문에 늘리지 않고, 채움은
    on/off 밴드가 `okMin: 0` 으로 왼쪽 끝부터 채워 이미 겹치며, 원은 조작
    손잡이의 모양이라 쓰지 않는다.
    정본: docs/design/dataviz-primitives.md "범위형과 누적형".
    """

    @staticmethod
    def _css():
        import io as _io
        path = os.path.join(os.path.dirname(__file__), '..', 'aot_flask',
                            'static', 'css', 'components', 'aot-dataviz.css')
        return _io.open(os.path.abspath(path), encoding='utf-8').read()

    @staticmethod
    def _js():
        import io as _io
        path = os.path.join(os.path.dirname(__file__), '..', 'aot_flask',
                            'static', 'js', 'common', 'aot-dataviz.js')
        return _io.open(os.path.abspath(path), encoding='utf-8').read()

    def _flag_rule(self):
        css = self._css()
        start = css.index('.aot-viz-target::before {')
        return css[start:css.index('}', start)]

    # ⚠ 깃발 캡(.aot-viz-target::before) 검사는 제거했다 — 그 표현을
    #    되돌렸기 때문이다(2026-09-04). "깃발이 있으면 의미가 다르다는 거야?
    #    잘 모르겠는데", "그저 now 위에 붙인 것뿐인 것 같아 보여". 모양은
    #    배워야 아는 기호라 종류를 스스로 설명하지 못한다.
    #    아래 범위 도표 검사는 **다른 결함**을 잡는 것이라 남는다: 한 트랙
    #    안에서 같은 초록이 '목표대' 와 '쌓인 양' 두 뜻으로 서던 것.

    def test_no_shape_is_bolted_onto_the_marker(self):
        """되돌린 표현이 조용히 되살아나지 않게 고정한다."""
        css = self._css()
        self.assertNotIn('.aot-viz-target::before', css)
        self.assertNotIn('--aot-viz-flag', css)

    # ── 그 기간의 진폭(최저~최고) ──────────────────────────────────────
    #
    # 평균 하나만 찍던 때는 "그날 얼마나 튀었나" 를 짚어야만 알 수 있었다.
    # 하루 평균은 낮과 밤을 섞은 값이라 34도까지 오른 날과 종일 25도인 날이
    # 같은 자리에 선다.

    def test_range_draws_the_period_spread(self):
        body = self._range_body()
        self.assertIn('aot-viz-span', body)
        self.assertIn('p.min', body)
        self.assertIn('p.max', body)

    def test_spread_replaces_the_average_marker(self):
        """셋(최저·평균·최고)을 한 칸에 세우지 않는다 — 칸이 좁다."""
        body = self._range_body()
        span_at = body.index('aot-viz-span')
        # 진폭 분기 **뒤**에 오는 else 안에서만 평균 마커를 그린다.
        self.assertLess(span_at, body.index('aot-viz-now'))

    def test_spread_draws_even_when_the_period_has_one_value(self):
        """폭이 0 이어도 그린다 — 최소 두께는 CSS 가 준다."""
        body = self._range_body()
        self.assertIn('최소 두께는 CSS 가 준다', body)
        css = self._css()
        self.assertIn('min-width: var(--aot-viz-track-h)', css)
        self.assertIn('min-height: var(--aot-viz-range-bar)', css)

    def test_spread_is_the_measured_green(self):
        """초록 = 실측. 최저~최고도 값이므로 구간 색(--aot-viz-zone)을 쓴다.

        예전에는 마커 색 2px 가는 선이었다 — 목표를 **초록 면**으로 그리던
        때라 굵으면 그것을 덮었기 때문이다. 목표가 선이 되면서 그 제약이
        사라졌다(2026-09-04).
        """
        css = self._css()
        start = css.index('.aot-viz-span {')
        rule = css[start:css.index('}', start)]
        self.assertIn('background: var(--aot-viz-zone)', rule)
        for banned in ('color-mix', 'rgba(', 'opacity'):
            self.assertNotIn(banned, rule)

    def test_spread_fills_the_track_thickness(self):
        """트랙 두께를 꽉 채운다 — 가로는 위아래 끝, 세로는 좌우 끝."""
        css = self._css()
        start = css.index('.aot-viz-span {')
        rule = css[start:css.index('}', start)]
        self.assertIn('top: 0; bottom: 0', rule)
        # ⚠ 가운데 맞춤 이동이 남아 있으면 반 폭만큼 밀린다(실측 지적).
        self.assertNotIn('translateX(-50%)', rule)
        self.assertIn('.aot-viz--range .aot-viz-span', css)

    def test_target_is_a_track_sized_line_on_top(self):
        """목표는 트랙 크기의 직각선이고 **맨 위**에 선다.

        실측(초록)이 트랙 두께를 꽉 채우므로, 겹치는 자리에서 목표가 그 아래로
        들어가면 "넘었는지" 를 볼 수 없다.
        """
        css = self._css()
        start = css.index('.aot-viz-target {')
        rule = css[start:css.index('}', start)]
        self.assertIn('top: 0; bottom: 0', rule)   # 트랙 높이만큼
        self.assertIn('z-index', rule)
        self.assertIn('var(--aot-viz-mark,', rule)
        # 세로에서는 축이 바뀐다.
        vstart = css.index('.aot-viz--range .aot-viz-target {')
        vrule = css[vstart:css.index('}', vstart)]
        self.assertIn('left: 0; right: 0', vrule)

    def test_band_draws_targets_as_lines_not_a_zone(self):
        """밴드 바도 같은 규칙 — okMin/okMax 는 선 둘이 된다."""
        js = self._js()
        body = js[js.index('function band(o) {'):js.index('function bullet(o) {')]
        self.assertIn('aot-viz-target', body)
        self.assertIn('aot-viz-span', body)

    def test_the_only_green_zone_left_is_the_on_off_duty_row(self):
        """예외는 하나뿐이다 — on/off 장치의 가동시간 줄(`okZone`).

        거기서 초록은 목표가 아니라 **평소 가동시간**이고 왼쪽 끝에서 자라며
        길이 자체가 뜻이라, 다른 줄처럼 선 둘로 옮길 수 없다. 손잡이가 다른
        자리로 번지면 한 화면에 두 어휘가 다시 선다.
        """
        js = self._js()
        body = js[js.index('function band(o) {'):js.index('function bullet(o) {')]
        # 초록 면은 `okZone` 분기 안에서만 그려진다.
        gate = body.index('if (o.okZone) {')
        self.assertLess(gate, body.index('aot-viz-ok'))
        self.assertEqual(body.count('aot-viz-ok'), 1)

        popup = io.open(os.path.join(
            os.path.dirname(__file__), '..', 'aot_flask', 'static', 'js',
            'widgets', 'AoT_map', 'aot-map-popup.js'), encoding='utf-8').read()
        self.assertEqual(popup.count('okZone: true'), 1,
                         'okZone 은 on/off 가동시간 줄 하나에만 쓴다')

    def _range_body(self):
        js = self._js()
        return js[js.index('function range(o) {'):js.index('global.AoTViz = {')]

    def test_range_bars_mark_the_goal_instead_of_shading_it(self):
        """누적형 열에 초록 면을 깔면 초록이 '목표대' 와 '쌓인 양' 두 뜻이 된다."""
        body = self._range_body()
        self.assertIn('if (bars) {', body)
        self.assertIn('aot-viz-target', body)
        goal = body[body.index('if (bars) {'):]
        self.assertNotIn('aot-viz-ok', goal[:goal.index('} else if')])

    def test_range_goal_sits_on_top_of_the_bar(self):
        """먼저 깔면 목표를 넘은 막대가 그 위를 덮어 넘었는지 알 수 없다."""
        body = self._range_body()
        self.assertLess(body.index('aot-viz-fill'), body.index('col += goalHtml'))


class TestAxisIsNotSetByOneBadDay(unittest.TestCase):
    """튄 값 하나가 한 주를 납작하게 만들지 않는다 (2026-09-04).

    실측: 쿠마모토 온실에서 09-01 에 온도 54.9 °C 가 한 번 찍혔고(다른 날은
    32~33), 그 값에서 계산된 VPD 가 10.97 kPa 였다. 축이 그것까지 담느라
    0~15 로 늘어나 나머지 엿새의 막대가 전부 바닥에 깔렸다.
    """

    @staticmethod
    def _series(day_maxes, targets=(), lo=22.0):
        """일별 (min, avg, max) → value_scale 입력 모양."""
        vals, groups = [], []
        for m in day_maxes:
            g = [lo, (lo + m) / 2.0, m]
            vals += g
            groups.append(g)
        return vals, groups, list(targets)

    def test_one_spike_does_not_set_the_axis(self):
        vals, groups, keep = self._series([32.5, 33.5, 32.5, 54.9, 42.2, 32.7, 29.9])
        sc = PJ.value_scale(vals, keep=keep, groups=groups)
        self.assertLess(sc['hi'], 54.9,
                        '튄 하루가 축의 끝을 정하고 있다')
        # 그래도 나머지는 담아야 한다.
        self.assertGreaterEqual(sc['hi'], 42.2)

    def test_a_wide_but_consistent_spread_is_kept(self):
        """넓은 것과 튄 것은 다르다 — 매일 넓으면 그것이 그 계열의 모양이다."""
        vals, groups, keep = self._series([30, 45, 32, 48, 35, 44, 31])
        sc = PJ.value_scale(vals, keep=keep, groups=groups)
        self.assertGreaterEqual(sc['hi'], 48)

    def test_a_skewed_series_is_not_trimmed(self):
        """⚠ 분위수(IQR) 울타리로 하지 말 것 — 쏠린 계열의 정상값이 잘린다.

        실측 반례: 청자5호 VPD 는 대부분 0 근처인데 2.9 kPa 가 정상으로 나온다.
        3·IQR 울타리로도 그것이 잘렸다.
        """
        vals, groups, keep = self._series(
            [0.2, 0.3, 0.25, 2.3, 0.4, 2.9, 0.35], lo=0.0)
        sc = PJ.value_scale(vals, keep=keep, groups=groups)
        self.assertGreaterEqual(sc['hi'], 2.9,
                                '쏠린 분포의 정상값이 축 밖으로 밀렸다')

    def test_targets_are_never_trimmed(self):
        """목표만 그림 밖으로 나가면 "한참 못 미쳤다" 가 "목표가 없다" 로 보인다."""
        vals, groups, _ = self._series([30, 31, 30, 55, 32, 30, 29])
        sc = PJ.value_scale(vals, keep=[12.0, 25.0], groups=groups)
        self.assertLessEqual(sc['lo'], 12.0)

    def test_a_short_period_is_not_second_guessed(self):
        """셋 중 하나를 빼는 것은 표본이 아니라 취향이다."""
        vals, groups, keep = self._series([30, 31, 60])
        sc = PJ.value_scale(vals, keep=keep, groups=groups)
        self.assertGreaterEqual(sc['hi'], 60)

    def test_nice_step_rounds_to_the_nearest_not_up(self):
        """올림은 간격을 두 배로 키우고, 그만큼 축의 양 끝도 밖으로 민다.

        실측: 온도 12~42 구간에서 대충 간격 10.07 이 20 으로 올라가 축이
        0~60 이 됐다(데이터가 화면의 3분의 1).
        """
        self.assertEqual(PJ._nice_step(10.07), 10.0)
        self.assertEqual(PJ._nice_step(1.9), 2.0)
        self.assertEqual(PJ._nice_step(0.11), 0.1)


class TestTooltipStaysOnTouch(unittest.TestCase):
    """손을 떼도 값 풍선이 남는다 (2026-09-04).

    사용자 지적: *"스마트폰에서 터치하면 툴팁으로 값을 보여주는데, 터치를 떼면
    바로 사라져서 불편함."* 손가락은 값 위에 머무를 수 없다 — 짚은 순간 그
    자리를 가리고, 떼면 볼 것이 사라진다.
    """

    @staticmethod
    def _tips_body():
        import io as _io
        path = os.path.join(os.path.dirname(__file__), '..', 'aot_flask',
                            'static', 'js', 'common', 'aot-dataviz.js')
        js = _io.open(os.path.abspath(path), encoding='utf-8').read()
        return js[js.index('function tips(root)'):js.index('global.AoTViz = {')]

    def test_pointerleave_closes_only_for_the_mouse(self):
        """터치도 손을 떼면 `pointerleave` 가 온다 — 그것이 그 증상의 원인이었다."""
        body = self._tips_body()
        i = body.index("addEventListener('pointerleave'")
        rule = body[i:i + 200]
        self.assertIn('isMouse', rule,
                      'pointerleave 를 포인터 종류와 무관하게 닫고 있다')

    def test_a_touch_outside_closes_it(self):
        """머무는 대신, 다른 곳을 짚으면 닫힌다 — 영영 남지는 않는다."""
        body = self._tips_body()
        self.assertIn('_bindTipDismiss', body)

    def test_the_document_listener_is_bound_once(self):
        """도표마다 걸면 일지 한 장(범위 도표 19개)에 리스너가 19개 쌓인다."""
        import io as _io
        path = os.path.join(os.path.dirname(__file__), '..', 'aot_flask',
                            'static', 'js', 'common', 'aot-dataviz.js')
        js = _io.open(os.path.abspath(path), encoding='utf-8').read()
        self.assertIn('_tipDismissBound', js)
        # 문서 단위 배선은 한 곳에서만 한다.
        self.assertEqual(js.count("global.document.addEventListener('pointerdown'"), 1)


class TestModalCardsSurviveAPaneWipe(unittest.TestCase):
    """모달을 오래 열어 두면 카드가 사라지던 것 (2026-09-04).

    사용자 지적: *"모달창을 오래 열어두면 현재 컨테이너가 사라져버려."*

    [현재]·[구획]·[기록] 카드는 `/overview` 가 만드는 HTML 에 없고, 각자
    나중에 `pane` 에 얹는다. 그런데 `_loadOverview` 는 내용이 달라지면
    `pane.innerHTML = ovHtml` 로 **판을 통째로 갈아엎는다** — 그때 세 카드가
    함께 지워진다.

    세 카드는 "지난번에 만든 문자열" 과 견줘 같으면 건너뛰는데, 판이 갈린 것을
    모르면 **영영 다시 그리지 않는다.** 값이 그대로인 동안에는 계속 사라진 채로
    남는다.
    """

    @staticmethod
    def _js():
        import io as _io
        path = os.path.join(os.path.dirname(__file__), '..', 'aot_flask',
                            'static', 'js', 'widgets', 'AoT_map',
                            'aot-map-widget-vector.js')
        return _io.open(os.path.abspath(path), encoding='utf-8').read()

    def test_every_overlaid_card_uses_the_shared_guard(self):
        """카드마다 손으로 캐시를 비우게 하면 카드가 늘 때 잊는다."""
        js = self._js()
        for key in ('_aotEnvNowHtml', '_aotPlotsHtml', '_aotRecordHtml'):
            self.assertIn("_cardFresh(pane, '%s'" % key, js)
            self.assertIn("_cardMark(pane, '%s'" % key, js)
            # 옛 방식(문자열만 비교)이 남아 있으면 그 카드만 조용히 사라진다.
            self.assertNotIn('pane.%s === html' % key, js)

    def test_the_wipe_site_bumps_the_generation(self):
        js = self._js()
        i = js.index('pane.innerHTML = ovHtml;')
        self.assertIn('_paneWiped(pane)', js[i:i + 1200])

    def test_freshness_also_checks_the_card_is_still_attached(self):
        """세대만 보면 `_paneWiped` 를 안 부르는 새 경로가 생기는 날 재발한다.

        마지막 관문은 **DOM 을 직접 보는 것**이다.
        """
        js = self._js()
        body = js[js.index('function _cardFresh('):]
        body = body[:body.index('function _cardMark(')]
        self.assertIn('isConnected', body)
        self.assertIn('pane.contains', body)


class TestGeoDataDoesItsOwnConditionalRequests(unittest.TestCase):
    """폴링 응답의 조건부 요청을 **브라우저 캐시에 맡기지 않는다** (2026-09-04).

    `/api/geo/devices` 는 서버가 ETag 를 붙인다(`utils_http.json_conditional`
    — 폴링 사이에 66~125KB 가 바이트까지 같아서 도입한 것이다). 그런데
    `AoTGeoData` 는 `fetch(url)` 을 그냥 불러 브라우저 HTTP 캐시에 맡기고
    있었다. 이 저장소가 금지하는 형태다:

        "cache:'no-store' 로 부를 것. 안 그러면 브라우저 HTTP 캐시가 조건부
         요청을 가로채 200(캐시본)으로 둔갑시켜, 본문을 도로 파싱한다."

    그래서 아끼는 것이 하나도 없었다. `AoTFacilityRuntime` 은 같은 자리를 이미
    제대로 하고 있었고(그 모듈이 정본이다), 여기만 빠져 있었다.
    """

    @staticmethod
    def _src(name):
        import io as _io
        path = os.path.join(os.path.dirname(__file__), '..', 'aot_flask',
                            'static', 'js', 'widgets', 'AoT_map', name)
        return _io.open(os.path.abspath(path), encoding='utf-8').read()

    def test_polling_fetches_bypass_the_browser_cache(self):
        for name in ('aot-geo-data.js', 'aot-facility-runtime.js'):
            src = self._src(name)
            self.assertIn("cache: 'no-store'", src, name)
            # 조건 없는 맨 fetch 가 남아 있으면 그 경로만 조용히 옛 동작이다.
            self.assertNotIn('fetch(url)\n', src, name)

    def test_the_validator_travels_with_us_not_the_browser(self):
        src = self._src('aot-geo-data.js')
        self.assertIn("'If-None-Match'", src)
        self.assertIn('r.status === 304', src)

    def test_force_is_never_conditional(self):
        """force 는 "권위 있는 최신 스냅샷" 요구다(제어 명령 직후).

        조건부로 보내면 304 가 돌아와 캐시본을 쓰게 되어 그 요구를 배신한다.
        """
        src = self._src('aot-geo-data.js')
        self.assertIn("if (!force && prev && prev.etag)", src)

    def test_a_304_without_a_copy_drops_the_validator(self):
        """검증자만 남으면 갱신이 영영 빈다 — 스스로 풀리게 둔다."""
        src = self._src('aot-geo-data.js')
        i = src.index('r.status === 304')
        self.assertIn('delete _cache[url].etag', src[i:i + 900])

class TestCurvePhaseDeltas(unittest.TestCase):
    """곡선 목표(Method)의 주야 Δ — 열람 시점 계산.

    곡선을 걸면 목표도 Δ도 사라지고 곡선 이름만 남았다. 운영 중인 프로그램
    넷이 전부 VPD 에 곡선을 걸고 있어, **정교하게 설정한 구획일수록 일지가
    그것을 검증하지 못했다**(2026-09-04 검증 세션). 하루 안에서 크게 변하는
    곡선을 일평균 하나로 접으면 밤의 이탈과 낮의 이탈이 서로를 지우므로,
    일출·일몰로 갈라 `avg_day`/`avg_night` 와 견준다.
    """

    #: 하루치 곡선 — 새벽 0.4, 정오 1.0(288칸 = 5분 간격).
    @staticmethod
    def _profile(low=0.4, high=1.0):
        out = []
        for i in range(288):
            sec = i * PJ.CURVE_SAMPLE_SEC + PJ.CURVE_SAMPLE_SEC // 2
            out.append(high if 6 * 3600 <= sec < 18 * 3600 else low)
        return out

    def test_day_and_night_means_split_at_sun(self):
        day, night = PJ._phase_means(self._profile(), 6 * 3600, 18 * 3600)
        self.assertAlmostEqual(day, 1.0)
        self.assertAlmostEqual(night, 0.4)

    def test_a_flat_curve_is_the_same_number_in_both_phases(self):
        day, night = PJ._phase_means([0.8] * 288, 6 * 3600, 18 * 3600)
        self.assertAlmostEqual(day, 0.8)
        self.assertAlmostEqual(night, 0.8)

    def test_gaps_in_the_curve_do_not_become_zero(self):
        """평가가 안 되는 칸은 **빼고** 센다 — 0 으로 채우면 목표가 내려간다."""
        profile = [None] * 144 + [1.0] * 144
        day, _night = PJ._phase_means(profile, 12 * 3600, 24 * 3600)
        self.assertEqual(day, 1.0)

    def test_sun_window_needs_both_ends(self):
        self.assertIsNone(PJ._sun_window({'sunrise': '05:50'}))
        self.assertIsNone(PJ._sun_window({}))
        self.assertEqual(
            PJ._sun_window({'sunrise': '05:50', 'sunset': '19:10'}),
            (5 * 3600 + 50 * 60, 19 * 3600 + 10 * 60))

    def test_polar_day_is_not_split(self):
        """일출·일몰이 뒤집혔거나 없는 날은 가르지 않는다 — 억지로 가르면
        하루가 통째로 한쪽에 몰린다(`sun_lookup` 과 같은 판단)."""
        self.assertIsNone(
            PJ._sun_window({'sunrise': '19:10', 'sunset': '05:50'}))

    # ── 붙이기 ──────────────────────────────────────────────────────────

    @staticmethod
    def _doc(avg_day=0.75, avg_night=0.51):
        return {
            'granularity': 'day',
            'target': {'tz_name': 'Asia/Seoul'},
            'stages': [{'key': 's1', 'starts_on': '2026-07-15',
                        'ends_on': '2026-09-15',
                        'targets': [{'key': 'vpd', 'label': 'VPD',
                                     'measurement': 'vapor_pressure_deficit',
                                     'unit': 'kPa', 'shape': 'instant',
                                     'source': 'method', 'value': None,
                                     'observable': True,
                                     'method_uuid': 'm-1',
                                     'method_name': '오이 VPD'}]}],
            'buckets': [{'key': '2026-08-21', 'date_label': '2026-08-21',
                         'sunrise': '06:00', 'sunset': '18:00',
                         'empty': False, 'notes': [], 'control': [],
                         'env': [{'device_id': 'd1', 'channel': 0,
                                  'sensor': '온습도_5', 'unit': 'kPa',
                                  'measurement': 'vapor_pressure_deficit',
                                  'min': 0.4, 'max': 1.5, 'avg': 0.65,
                                  'avg_day': avg_day, 'avg_night': avg_night,
                                  'samples': 24, 'expected': 24,
                                  'target': None, 'delta': None,
                                  'delta_skipped': 'method',
                                  'follows_curve': '오이 VPD'}]}],
        }

    def _attach(self, doc, profile=None):
        """`load_method_handler` 를 세워 두고 붙인다 — DB 없이 돈다."""
        import aot.utils.method as M
        real = M.load_method_handler
        prof = self._profile() if profile is None else profile
        M.load_method_handler = lambda *a, **k: object()
        real_profile = PJ._curve_profile
        PJ._curve_profile = lambda *a, **k: prof
        try:
            return PJ.with_curve_deltas(doc)
        finally:
            M.load_method_handler = real
            PJ._curve_profile = real_profile

    def test_delta_comes_back_for_a_curve_target(self):
        doc = self._doc()
        out = self._attach(doc)
        phases = out['buckets'][0]['env'][0]['target_phases']
        self.assertEqual(phases['day'], {'target': 1.0, 'delta': -0.25})
        self.assertEqual(phases['night'], {'target': 0.4, 'delta': 0.11})

    def test_other_targets_on_the_same_row_survive(self):
        """한 행에는 그 measurement 의 후보가 전부 실려 있다(온도라면 주간·
        야간 둘). 곡선 것으로 통째로 덮으면 **곡선이 아닌 목표가 이탈 요약에서
        사라진다** — 곡선을 `temp_day` 에만 걸고 `temp_night` 는 고정값으로 둔
        프로그램에서 야간온도 이탈이 통째로 없어졌다(2026-09-04 검토)."""
        doc = self._doc()
        row = doc['buckets'][0]['env'][0]
        row['measurement'] = 'temperature'
        row['avg_day'], row['avg_night'] = 28.0, 23.0
        row['targets_eval'] = [
            {'label': 'Day temp', 'when': 'day', 'value': None,
             'delta': None, 'delta_skipped': 'method'},
            {'label': 'Night temp', 'when': 'night', 'value': 18.0,
             'delta': 5.0, 'delta_skipped': None}]
        t = doc['stages'][0]['targets'][0]
        t.update({'key': 'temp_day', 'label': 'Day temp', 'when': 'day',
                  'measurement': 'temperature'})
        out = self._attach(doc)
        evals = out['buckets'][0]['env'][0]['targets_eval']
        labels = [(e['label'], e['when']) for e in evals]
        self.assertIn(('Night temp', 'night'), labels)     # 남아 있어야 한다
        self.assertIn(('Day temp', 'day'), labels)         # 곡선 자리는 갈렸다
        # 곡선 목표의 옛 자리(값 없는 'method')는 사라진다 — 갈아 끼운 것이다.
        self.assertNotIn('method', [e.get('delta_skipped') for e in evals])
        drift = {(d['label'], d['when'])
                 for d in PJ.target_drift(out['buckets'])}
        self.assertIn(('Night temp', 'night'), drift)

    def test_a_curve_that_is_not_the_first_candidate_still_gets_deltas(self):
        """`attach_targets` 는 후보 중 **첫 것**을 대표로 삼는다. 곡선이
        `temp_night` 에 걸리고 `temp_day` 가 고정값이면 대표가 고정값이라,
        대표만 보고 거르면 그 배치에서 곡선 Δ 복원이 조용히 안 돈다."""
        doc = self._doc()
        row = doc['buckets'][0]['env'][0]
        row['measurement'] = 'temperature'
        row['avg_day'], row['avg_night'] = 28.0, 23.0
        row['target'], row['delta'] = 22.0, 6.0
        row['delta_skipped'], row['follows_curve'] = None, None
        row['targets_eval'] = [
            {'label': 'Day temp', 'when': 'day', 'value': 22.0,
             'delta': 6.0, 'delta_skipped': None},
            {'label': 'Night temp', 'when': 'night', 'value': None,
             'delta': None, 'delta_skipped': 'method'}]
        t = doc['stages'][0]['targets'][0]
        t.update({'key': 'temp_night', 'label': 'Night temp', 'when': 'night',
                  'measurement': 'temperature'})
        out = self._attach(doc)
        phases = out['buckets'][0]['env'][0]['target_phases']
        self.assertIn('night', phases)
        self.assertNotIn('day', phases)                    # 야간 전용 곡선이다
        drift = {(d['label'], d['when'])
                 for d in PJ.target_drift(out['buckets'])}
        self.assertEqual(drift, {('Day temp', 'day'), ('Night temp', 'night')})

    def test_a_row_with_no_target_at_all_is_left_alone(self):
        """같은 값을 현장 센서도 재서 목표에서 빠진 기상대 행 — 빠진 데는
        이유가 있다. 곡선이 있다고 그 행에 목표를 도로 붙이면 안 된다."""
        doc = self._doc()
        row = doc['buckets'][0]['env'][0]
        row['scope'] = 'outdoor'
        row['target'] = row['delta'] = row['delta_skipped'] = None
        row.pop('follows_curve', None)
        row.pop('targets_eval', None)
        self.assertIs(self._attach(doc), doc)

    def test_the_stored_snapshot_is_not_touched(self):
        """저장본을 고치면 JSON·MCP 내보내기가 오염되고 스냅샷 계약(§1)이 깨진다."""
        doc = self._doc()
        self._attach(doc)
        row = doc['buckets'][0]['env'][0]
        self.assertNotIn('target_phases', row)
        self.assertEqual(row['delta_skipped'], 'method')

    def test_the_curve_name_survives(self):
        """숫자만 남기면 어느 곡선의 목표인지 되짚을 수 없다."""
        out = self._attach(self._doc())
        row = out['buckets'][0]['env'][0]
        self.assertEqual(row['follows_curve'], '오이 VPD')
        self.assertEqual(row['delta_skipped'], 'curve-phase')

    def test_a_phase_without_a_reading_keeps_the_target(self):
        """실측이 없는 쪽의 목표까지 지우면 '그 시간대엔 목표가 없다' 로 읽힌다."""
        out = self._attach(self._doc(avg_night=None))
        phases = out['buckets'][0]['env'][0]['target_phases']
        self.assertEqual(phases['night'], {'target': 0.4})
        self.assertNotIn('delta', phases['night'])

    def test_cumulative_targets_are_left_alone(self):
        """적산 목표(DLI)를 순간값 평균과 빼면 차원이 다른 뺄셈이다."""
        doc = self._doc()
        doc['stages'][0]['targets'][0]['shape'] = 'daily'
        self.assertIs(self._attach(doc), doc)

    def test_unobservable_targets_are_left_alone(self):
        """센서가 없으면 곡선이 있어도 견줄 것이 없다."""
        doc = self._doc()
        doc['stages'][0]['targets'][0]['observable'] = False
        self.assertIs(self._attach(doc), doc)

    def test_a_night_only_curve_says_nothing_about_the_day(self):
        doc = self._doc()
        doc['stages'][0]['targets'][0]['when'] = 'night'
        out = self._attach(doc)
        phases = out['buckets'][0]['env'][0]['target_phases']
        self.assertNotIn('day', phases)
        self.assertIn('night', phases)

    def test_no_sun_no_split(self):
        doc = self._doc()
        doc['buckets'][0].pop('sunrise')
        self.assertIs(self._attach(doc), doc)

    def test_the_curve_start_survives_the_fallback_call(self):
        """주차 인자를 안 받는 곡선 종류(사인·베지어 등)는 `method_start_time`
        으로 경과를 센다. 폴백에서 그것을 떨구면 `AbstractMethod` 가
        1900-01-01 을 시작으로 잡아 **엉뚱한 지점의 곡선 값**을 목표로 적는다 —
        건너뛰는 것보다 나쁜 실패다."""
        import inspect
        src = inspect.getsource(PJ._curve_profile)
        # 폴백 호출에도 시작 시각이 들어가야 한다.
        self.assertNotIn('calculate_setpoint(stamp)', src)
        self.assertEqual(src.count('method_start_time=start_dt'), 2)

    def test_the_crop_start_is_what_is_handed_down(self):
        """넘기는 시작 시각은 버킷의 자정이 아니라 **재배 시작일**이다."""
        import inspect
        src = inspect.getsource(PJ._with_curve_deltas)
        self.assertIn('start_dt=datetime.combine(started, dtime.min)', src)

    def test_a_dead_curve_does_not_break_the_page(self):
        """곡선이 지워진 것은 일지를 통째로 못 볼 이유가 아니다."""
        import aot.utils.method as M
        doc = self._doc()
        real = M.load_method_handler
        M.load_method_handler = lambda *a, **k: None
        try:
            self.assertIs(PJ.with_curve_deltas(doc), doc)
        finally:
            M.load_method_handler = real

    # ── 접기 ────────────────────────────────────────────────────────────

    def test_folding_keeps_the_spread_of_the_deltas(self):
        """범위를 빼면 접기가 이탈의 폭을 감춘다."""
        boxes = [{'day': {'target': 0.7, 'delta': -0.5}},
                 {'day': {'target': 0.9, 'delta': 0.3}}]
        merged = PJ._merge_phases(boxes)
        self.assertEqual(merged['day']['target'], 0.8)
        self.assertTrue(merged['day']['target_varies'])
        self.assertEqual((merged['day']['delta_min'],
                          merged['day']['delta_max']), (-0.5, 0.3))

    def test_folding_does_not_carry_the_first_day_forward(self):
        """`dict(members[0])` 이 첫날의 목표를 그 구간 전체의 것으로 말했다."""
        doc = self._doc()
        second = {k: (dict(v) if isinstance(v, dict) else v)
                  for k, v in doc['buckets'][0].items()}
        second['key'] = second['date_label'] = '2026-08-22'
        second['env'] = [dict(doc['buckets'][0]['env'][0])]
        doc['buckets'].append(second)
        out = self._attach(doc)
        out['buckets'][0]['env'][0]['target_phases']['day']['target'] = 9.9
        folded = PJ.fold_buckets(out['buckets'], to='week', granularity='day')
        self.assertEqual(folded[0]['env'][0]['target_phases']['day']['target'],
                         5.45)          # (9.9 + 1.0) / 2 — 첫날만이 아니다

    def test_two_sensors_missing_in_opposite_directions_keep_both_signs(self):
        """같은 구획의 두 센서가 같은 목표를 반대로 벗어난다(캐노피 안팎).
        평균 하나로 접으면 그 사실이 사라진다."""
        rows = [{'measurement': 'vapor_pressure_deficit', 'unit': 'kPa',
                 'sensor': 'a', 'avg': 0.2, 'samples': 24,
                 'target_phases': {'day': {'target': 0.8, 'delta': -0.6}}},
                {'measurement': 'vapor_pressure_deficit', 'unit': 'kPa',
                 'sensor': 'b', 'avg': 1.2, 'samples': 24,
                 'target_phases': {'day': {'target': 0.8, 'delta': 0.4}}}]
        summary = PJ.group_env_rows(rows)[0]['summary']
        self.assertEqual(summary['target_phases']['day']['delta_min'], -0.6)
        self.assertEqual(summary['target_phases']['day']['delta_max'], 0.4)

    # ── 표시 ────────────────────────────────────────────────────────────

    def test_text_names_the_phase(self):
        """숫자 둘만 나란히 두면 어느 쪽이 낮인지 알 수 없다."""
        phases = {'day': {'target': 0.79, 'delta': -0.64},
                  'night': {'target': 0.45, 'delta': -0.3}}
        self.assertEqual(PJ.phase_target_text(phases),
                         'Daytime 0.79 · Nighttime 0.45')
        # 부호는 항상 붙는다 — 화면의 다른 Δ 칸과 같은 규칙(`'%+g'`).
        self.assertEqual(PJ.phase_delta_text(phases),
                         'Daytime -0.64 · Nighttime -0.3')

    def test_text_shows_a_range_when_the_fold_has_one(self):
        phases = {'day': {'delta': -0.1, 'delta_min': -0.5, 'delta_max': 0.3}}
        self.assertEqual(PJ.phase_delta_text(phases), 'Daytime -0.5 ~ +0.3')

    def test_empty_is_empty_not_a_stray_separator(self):
        self.assertEqual(PJ.phase_target_text(None), '')
        self.assertEqual(PJ.phase_delta_text({}), '')


class TestDeviceNotesReachThePlotJournal(unittest.TestCase):
    """구획 일지가 그 장치의 값은 싣고 **그 장치에 붙은 기록은 빼던** 것.

    좌표가 있는 노트만 구획에 걸렸다(`_anchor_of` 의 plot 분기). UI 로 만든
    노트는 대개 좌표가 채워지지만, 좌표 없는 장치 노트는 조용히 빠졌다 —
    실측(로컬, 2026-09-04): "센서 측정부 오류로 수리 중"(온습도_7·_8)이 그
    센서를 쓰는 구획 넷 어디에도 안 나왔다. 그 문서에는 그 센서의 값이
    그대로 실려 있는데, 그것을 읽는 데 필요한 맥락만 없었다.
    """

    class _Plot(object):
        unique_id = 'plot-1'

        def __init__(self, own_geometry=True):
            self._own = own_geometry

        def has_own_geometry(self):
            return self._own

    class _Note(object):
        def __init__(self, target_id=None, target_type=None,
                     lat=None, lng=None):
            self.unique_id = 'note-1'
            self.target_id = target_id
            self.target_type = target_type
            self.gps_lat = lat
            self.gps_lng = lng

    def _scope(self, plot=None, device_ids=None):
        """`geometry_of` 를 세워 두고 scope 를 만든다 — DB 없이 돈다."""
        from aot.aot_flask.geo import plot_context
        real = plot_context.geometry_of
        plot_context.geometry_of = lambda *a, **k: {
            'type': 'Polygon',
            'coordinates': [[[0, 0], [0, 1], [1, 1], [1, 0], [0, 0]]]}
        try:
            return PJ.note_scope_for_target(
                'plot', plot or self._Plot(), device_ids=device_ids)
        finally:
            plot_context.geometry_of = real

    def test_a_note_on_the_plots_own_device_is_included(self):
        scope = self._scope(device_ids={'input-7'})
        note = self._Note(target_id='input-7', target_type='device')
        self.assertEqual(PJ._anchor_of(note, scope), 'descendant')

    def test_a_note_on_someone_elses_device_is_not(self):
        """넘겨받은 집합 밖의 장치까지 끌어오면 두 번째 판정 기준이 된다."""
        scope = self._scope(device_ids={'input-7'})
        note = self._Note(target_id='input-9', target_type='device')
        self.assertIsNone(PJ._anchor_of(note, scope))

    def test_coordinates_still_work_on_their_own(self):
        """장치 집합을 안 넘겨도 예전처럼 좌표로 걸린다."""
        scope = self._scope()
        note = self._Note(lat=0.5, lng=0.5)
        self.assertEqual(PJ._anchor_of(note, scope), 'position')

    def test_attachment_beats_coordinates(self):
        """붙어 있는 쪽이 좌표보다 세다 — `_anchor_of` 의 기존 규칙."""
        scope = self._scope(device_ids={'output-1'})
        note = self._Note(target_id='output-1', target_type='output',
                          lat=0.5, lng=0.5)
        self.assertEqual(PJ._anchor_of(note, scope), 'descendant')

    def test_facility_plots_get_device_notes_even_without_geometry(self):
        """시설 구획은 좌표 판정을 아예 건너뛴다(파생 기하라 못 쓴다) —
        그래서 예전에는 구획에 직접 붙인 노트 말고는 아무것도 없었다."""
        scope = self._scope(plot=self._Plot(own_geometry=False),
                            device_ids={'input-7'})
        self.assertEqual(scope['gps_skipped'],
                         'facility-plot-derived-geometry')
        note = self._Note(target_id='input-7', target_type='device')
        self.assertEqual(PJ._anchor_of(note, scope), 'descendant')

    def test_the_journal_hands_over_its_own_devices(self):
        """넘기는 집합은 **이 문서가 이미 자기 것이라고 말한 장치**다 —
        센서 표와 가동시간이 나온 그 목록. 따로 만들면 둘이 갈린다."""
        import inspect
        src = inspect.getsource(PJ.build_journal_for_target)
        self.assertIn("note_device_ids = set(sensor_ids or [])", src)
        self.assertIn("device_ids=note_device_ids", src)

    def test_the_device_name_rides_along(self):
        """이름이 없으면 "센서 고장" 이 어느 센서 이야기인지 알 수 없다 —
        같은 항목을 재는 센서가 둘인 구획이 흔하다."""
        import inspect
        src = inspect.getsource(PJ.notes_for_target)
        self.assertIn("'anchor_name'", src)

    def test_a_deleted_device_does_not_get_an_invented_name(self):
        note = self._Note(target_id='gone', target_type='device')
        self.assertIsNone(PJ._attached_device_name(note))

    def test_notes_that_are_not_on_devices_are_left_alone(self):
        """구역·대지 노트에 장치 이름을 붙이면 거짓이 된다."""
        note = self._Note(target_id='zone-1', target_type='zone')
        self.assertIsNone(PJ._attached_device_name(note))


class TestCurveDeltasReachTheMcpPath(unittest.TestCase):
    """화면에만 열람 시점 복원이 걸려 있었다 — 같은 일지·같은 날인데
    `get_plot_journal` 은 `target: null, delta: null, delta_skipped: 'method'`
    를 그대로 내보냈고 `target_drift` 에도 VPD 가 없었다(2026-09-04 실측).
    MCP 는 AI 가 읽는 경로라, 화면에는 보이는 답을 AI 만 못 내게 된다."""

    def test_the_handler_runs_the_same_view_time_calculation(self):
        import inspect
        from aot.ai.services.aot_data_tool_service import (
            AoTDataToolService as S)
        src = inspect.getsource(S.get_plot_journal)
        self.assertIn('PJ.with_curve_deltas(row.data)', src)

    def test_it_runs_before_folding_and_counting(self):
        """접기·기간 필터·이탈 세기가 전부 그 결과를 봐야 한다 — 뒤에 두면
        `target_drift` 는 여전히 곡선 행을 분모에서 뺀다."""
        import inspect
        from aot.ai.services.aot_data_tool_service import (
            AoTDataToolService as S)
        src = inspect.getsource(S.get_plot_journal)
        self.assertLess(src.index('with_curve_deltas'),
                        src.index('PJ.target_drift('))
        self.assertLess(src.index('with_curve_deltas'),
                        src.index('PJ.fold_buckets('))


class TestExcludedMeasurementsSayWhy(unittest.TestCase):
    """빠진 것을 전부 "장치 진단 값" 이라 불렀다. 실제로 빠진 것의 대부분은
    **만들 때 고르지 않은 채널**이고, 진짜 진단값은 전위·RSSI·SNR 뿐이다 —
    "온도는 장치 진단 값" 이라고 적으면 사용자는 자기가 재고 있는 값이
    진단용으로 취급돼 빠졌다고 읽는다(실사용 지적 2026-09-04)."""

    def test_diagnostics_and_unselected_are_split(self):
        import inspect
        src = inspect.getsource(PJ.build_journal_for_target)
        self.assertIn('measurements-excluded-diagnostic:', src)
        self.assertIn('measurements-excluded-chosen:', src)
        self.assertIn('name in DIAGNOSTIC_MEASUREMENTS', src)

    def test_the_diagnostic_sentence_only_names_diagnostics(self):
        text = str(PJ.caveat_text(
            'measurements-excluded-diagnostic:rssi,snr'))
        self.assertIn('diagnostic', text.lower())

    def test_the_unselected_sentence_does_not_call_them_diagnostics(self):
        text = str(PJ.caveat_text(
            'measurements-excluded-chosen:outdoor:temperature'))
        self.assertNotIn('diagnostic', text.lower())
        self.assertIn('select', text.lower())

    def test_it_says_which_sensor_the_missing_value_belonged_to(self):
        """"온도를 뺐다" 만으로는 현장 온도가 빠진 줄로 읽힌다."""
        text = str(PJ.caveat_text(
            'measurements-excluded-chosen:outdoor:temperature'))
        self.assertIn(str(PJ._gettext_safe('Weather Station')), text)

    def test_old_journals_stop_calling_them_diagnostics_too(self):
        """옛 일지의 키에는 이유가 갈라져 있지 않다. 문장은 열람 시점에
        만들어지므로, 이유를 말하지 않는 쪽으로 바꾸면 옛 일지도 함께 고쳐진다."""
        text = str(PJ.caveat_text(
            'measurements-excluded:temperature,humidity'))
        self.assertNotIn('diagnostic', text.lower())
