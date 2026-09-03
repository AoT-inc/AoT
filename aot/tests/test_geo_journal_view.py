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
import os
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
        self.assertIn('.aot-journal-toc, .aot-journal-gran { display: none !important; }',
                      html)

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
        self.assertIn('is-outdoor', html)      # 행 표식으로만 갈린다

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

    def test_the_measurement_heading_can_say_weather_station(self):
        """실내 센서가 없는 구획이면 고르는 대상이 전부 기상대 채널이다."""
        src = self._hub()
        self.assertIn('journal-meas-title', src)

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
