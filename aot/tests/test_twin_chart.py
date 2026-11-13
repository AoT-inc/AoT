# coding=utf-8
"""트윈 구획 그래프 묶음 조립기(`aot.utils.twin_chart.assemble`) — Influx·DB 를 건드리지 않고 읽어 온 값만 조립한다.

규칙: 유효한 발행만 곡선을 싣고(만료·숨김은 이유만, 마지막 값으로 채우지 않는다), 옛 발행의 잔재(`t0` 앞)는 버리며,
센서 칸 예측이 있으면 그 단위로, 센서 없는 구획은 뿌리층 단위로 싣는다. 날짜는 문자열 키.
"""
import calendar
import datetime
import unittest

from aot.twin import output as O
from aot.utils import twin_chart as C
from aot.utils import twin_read as R

P = 'plot-a'
DAY = 86400.0
M = O.FIELD_META
NOW = datetime.datetime(2026, 10, 25, 3, 0, tzinfo=datetime.timezone.utc).timestamp()   # KST 12:00
KST = 9 * 3600.0
T0 = datetime.datetime(2026, 10, 25, tzinfo=datetime.timezone.utc).timestamp() - KST     # 일 격자 점은 대지 현지 00:00 (KST 10-25 = 10-24 15:00Z)


def _meta(status=0, valid_h=36, obs_n=1.0):
    return {(P, M['status']): [(T0, float(status))], (P, M['valid_until']): [(T0, T0 + valid_h * 3600.0)],
            (P, M['obs_n']): [(T0, obs_n)], (P, M['rain_fc_days']): [(T0, 8.0)],
            (P, M['sync_rmse_theta_1d']): [(T0, 1.0)], (P, M['coverage_80']): [(T0, 0.9)]}


def _curves(days=8, sensor=True):
    out = {}
    for name, ch in C.CHART_CHANNELS.items():
        if name.startswith('theta_sensor') and not sensor:
            continue
        base = 30.0 if name.startswith('theta_sensor') else 20.0 if name.startswith('theta') else 0.2
        off = 1 if name.endswith('p90') else -1 if name.endswith('p10') else 0
        pts = [(T0 + k * DAY, base + k + off) for k in range(days)]
        out[(P, ch)] = [(T0 - DAY, 999.0)] + pts                 # 옛 발행 잔재
    return out


def _run(meta=None, curves=None, observed=None, forecast=None, back=7, ahead=7, now=NOW, **extra):
    view = {'inputs': {'theta': {'unique_id': 'dev1', 'channel': 2, 'unit': '%', 'provenance': 'measured'},
                       'rain': {'unique_id': 'dev2', 'channel': 0, 'unit': 'mm', 'provenance': 'measured'}},
            'options': {'rain': {'agg': 'daily_sum', 'scale': 1.0}}}
    return C.assemble(P, now, back, ahead, view=view, meta_rows=_meta() if meta is None else meta,
                      curve_rows=_curves() if curves is None else curves, observed=observed or {},
                      forecast=forecast, tz_offset_s=KST, tz_name='Asia/Seoul', names={'dev1': ('토양센서', 'x')}, **extra)


class LocalDates(unittest.TestCase):
    """곡선 날짜 키는 대지 **현지** 날짜다 — 일 격자 점이 현지 00:00 이라 UTC 날짜로 접으면 동쪽 시간대에서 하루 앞으로 밀린다.
    점마다 `timekit` 으로 현지 시각을 구하고 가장 가까운 자정으로 반올림한다(고정 오프셋·UTC 날짜 아님)."""

    @staticmethod
    def _grid(tz_name, first, n, pub_at=None):
        """엔진이 만드는 격자: 발행 시각 오프셋으로 `t0 = 오늘 * 86400 - tz`, 이후 24 시간씩(일광절약시간을 넘어도 그대로)."""
        import zoneinfo
        pub = pub_at or datetime.datetime(first.year, first.month, first.day, 12, tzinfo=datetime.timezone.utc)
        tz = pub.astimezone(zoneinfo.ZoneInfo(tz_name)).utcoffset().total_seconds()
        day = calendar.timegm(first.timetuple()) / DAY
        t0 = day * DAY - tz
        return [t0 + k * DAY for k in range(n)]

    def test_grid_date_for_zones_east_west_and_half_hour(self):
        for tz_name in ('Asia/Seoul', 'UTC', 'America/Los_Angeles', 'Pacific/Kiritimati', 'Etc/GMT+12', 'Asia/Kolkata',
                        'Australia/Sydney', 'America/Sao_Paulo', 'Asia/Kathmandu'):
            pts = self._grid(tz_name, datetime.date(2026, 11, 2), 3)
            self.assertEqual(['2026-11-02', '2026-11-03', '2026-11-04'], [R.grid_date(t, tz_name) for t in pts], tz_name)

    def test_kst_midnight_is_not_the_previous_utc_day(self):
        g = datetime.datetime(2026, 11, 1, 15, tzinfo=datetime.timezone.utc).timestamp()      # 한국 11-02 00:00
        self.assertEqual('2026-11-02', R.grid_date(g, 'Asia/Seoul'))

    def test_new_york_grid_across_the_dst_end_keeps_one_date_per_point(self):
        """2026-11-01 02:00 에 EDT→EST. 10-31 발행(EDT, -4) 격자는 11-02 점이 11-01 23:00 EST 에 놓인다 —
        점별 벽시계 날짜만 쓰면 11-01 이 두 번 나오고 11-02 가 빠진다."""
        pts = self._grid('America/New_York', datetime.date(2026, 10, 31), 4,
                         datetime.datetime(2026, 10, 31, 6, tzinfo=datetime.timezone.utc))
        self.assertEqual(['2026-10-31', '2026-11-01', '2026-11-02', '2026-11-03'],
                         [R.grid_date(t, 'America/New_York') for t in pts])
        wall = datetime.datetime.fromtimestamp(pts[2], datetime.timezone.utc).astimezone(
            __import__('zoneinfo').ZoneInfo('America/New_York'))
        self.assertEqual((11, 1, 23), (wall.month, wall.day, wall.hour))        # 이 격자가 실제로 자정이 아니다

    def test_dst_start_and_southern_hemisphere(self):
        pts = self._grid('America/New_York', datetime.date(2026, 3, 7), 4, datetime.datetime(2026, 3, 7, 6, tzinfo=datetime.timezone.utc))
        self.assertEqual(['2026-03-07', '2026-03-08', '2026-03-09', '2026-03-10'], [R.grid_date(t, 'America/New_York') for t in pts])
        pts = self._grid('Australia/Sydney', datetime.date(2026, 10, 3), 4, datetime.datetime(2026, 10, 3, 6, tzinfo=datetime.timezone.utc))
        self.assertEqual(['2026-10-03', '2026-10-04', '2026-10-05', '2026-10-06'], [R.grid_date(t, 'Australia/Sydney') for t in pts])   # 10-04 서머타임 시작
        pts = self._grid('Australia/Sydney', datetime.date(2026, 4, 3), 4, datetime.datetime(2026, 4, 3, 6, tzinfo=datetime.timezone.utc))
        self.assertEqual(['2026-04-03', '2026-04-04', '2026-04-05', '2026-04-06'], [R.grid_date(t, 'Australia/Sydney') for t in pts])   # 04-05 종료

    def test_curves_by_date_keys_follow_tz_for_base_post_and_scenario(self):
        rows = {(P, C.CHART_CHANNELS['theta_root_p50']): [(T0 - DAY, 1.0), (T0, 2.0), (T0 + DAY, 3.0)]}
        cur = C.curves_by_date(rows, P, T0, T0 - 2 * DAY, T0 + 2 * DAY, 'Asia/Seoul')
        self.assertEqual({'theta_root_p50': {'2026-10-25': 2.0, '2026-10-26': 3.0}}, cur)     # t0 앞 점은 버린다
        past = C.curves_by_date(rows, P, T0, T0 - 2 * DAY, T0, 'Asia/Seoul', keep_past=True)
        self.assertEqual({'2026-10-24': 1.0, '2026-10-25': 2.0}, past['theta_root_p50'])

    def test_assemble_puts_the_first_grid_point_on_today_and_not_yesterday(self):
        r = _run()
        self.assertEqual('2026-10-25', r['today'])
        self.assertEqual(30.0, r['theta']['p50']['2026-10-25'])                   # 격자 첫 점(k=0) = 오늘, 다음 날 점(31.0)이 아니다
        self.assertIn('2026-10-25', r['events']['water_deficit'])
        self.assertNotIn('2026-10-24', r['theta']['p50'])

    def test_new_york_dst_end_day_keeps_today_point_and_every_day(self):
        """전환일(11-01) 새벽 2 시 뒤에 읽으면 오프셋이 -4 → -5 라 창 시작이 발행 `t0` 보다 한 시간 늦다 — 오늘 점이 빠지면 안 된다."""
        pts = self._grid('America/New_York', datetime.date(2026, 11, 1), 4, datetime.datetime(2026, 11, 1, 5, tzinfo=datetime.timezone.utc))
        t0 = pts[0]                                        # 11-01 00:00 EDT (04:00Z), 읽는 때는 EST
        now = datetime.datetime(2026, 11, 1, 12, tzinfo=datetime.timezone.utc).timestamp()      # 현지 07:00 EST
        meta = {(P, M['status']): [(t0, 0.0)], (P, M['valid_until']): [(t0, t0 + 36 * 3600.0)], (P, M['obs_n']): [(t0, 1.0)]}
        curves = {(P, ch): [(t, 10.0 + k) for k, t in enumerate(pts)] for ch in (C.CHART_CHANNELS['theta_root_p10'],
                  C.CHART_CHANNELS['theta_root_p50'], C.CHART_CHANNELS['theta_root_p90'])}
        view = {'inputs': {}, 'options': {}}
        r = C.assemble(P, now, 0, 3, view=view, meta_rows=meta, curve_rows=curves, observed={}, forecast=None,
                       tz_offset_s=-5 * 3600.0, tz_name='America/New_York', names={})
        self.assertEqual('2026-11-01', r['today'])
        self.assertEqual({'2026-11-01': 10.0, '2026-11-02': 11.0, '2026-11-03': 12.0, '2026-11-04': 13.0}, r['theta']['p50'])


class Trust(unittest.TestCase):
    """믿을 만한가의 판정은 서버가 내려 보낸다(`trust`) — 문턱 정본은 `twin_read`."""

    def test_matching_publication_has_no_cautions(self):
        self.assertEqual({'cautions': [], 'reference_only': False}, _run()['trust'])

    def test_off_forecast_is_reference_only(self):
        meta = _meta()
        meta[(P, M['sync_rmse_theta_1d'])] = [(T0, 11.48)]
        meta[(P, M['coverage_80'])] = [(T0, 0.14)]
        self.assertEqual({'cautions': ['error', 'coverage'], 'reference_only': True}, _run(meta)['trust'])

    def test_sensorless_and_degraded(self):
        self.assertEqual({'cautions': ['sensorless'], 'reference_only': True}, _run(_meta(obs_n=0.0))['trust'])
        self.assertEqual({'cautions': ['degraded'], 'reference_only': False}, _run(_meta(status=1))['trust'])

    def test_unusable_publication_is_never_reference_only(self):
        r = _run(_meta(status=0, valid_h=-1))                      # 만료
        self.assertFalse(r['trust']['reference_only'])

    def test_no_publication(self):
        self.assertEqual({'cautions': [], 'reference_only': False}, _run({})['trust'])


class Assemble(unittest.TestCase):
    def test_days_axis_is_local_dates(self):
        r = _run()
        self.assertEqual(r['today'], '2026-10-25')
        self.assertEqual(r['days'][0], '2026-10-18')
        self.assertEqual(r['days'][-1], '2026-11-01')
        self.assertEqual(len(r['days']), 15)

    def test_valid_publication_carries_curves_without_stale_points(self):
        r = _run()
        self.assertTrue(r['state']['usable'])
        th = r['theta']
        self.assertEqual(th['kind'], 'sensor')                    # 센서 칸 예측이 있으면 그 단위
        self.assertEqual(th['p50']['2026-10-25'], 30.0)
        self.assertEqual(th['p10']['2026-10-25'], 29.0)
        self.assertNotIn('2026-10-24', th['p50'])                 # t0 앞 잔재(999)는 없다
        self.assertEqual(r['events']['water_deficit']['2026-10-26'], 1.2)

    def test_sensorless_uses_root_units_and_flags(self):
        r = _run(meta=_meta(obs_n=0.0), curves=_curves(sensor=False))
        self.assertTrue(r['state']['sensorless'])
        self.assertEqual(r['theta']['kind'], 'root')
        self.assertEqual(r['theta']['p50']['2026-10-25'], 20.0)

    def test_expired_publication_has_reason_and_no_curves(self):
        r = _run(meta=_meta(valid_h=1), now=NOW + 3 * 3600.0)     # t0+1h 에 만료, 지금은 t0+6h
        self.assertFalse(r['state']['usable'])
        self.assertEqual(r['state']['reason'], 'expired')
        self.assertEqual(r['theta']['p50'], {})
        self.assertEqual(r['events'], {})

    def test_unsynced_status_is_hidden(self):
        r = _run(meta=_meta(status=2))
        self.assertFalse(r['state']['usable'])
        self.assertEqual(r['state']['reason'], 'status_2')

    def test_no_publication(self):
        r = _run(meta={})
        self.assertEqual(r['state']['reason'], 'no_publication')
        self.assertIsNone(r['meta'])

    def test_observed_rain_and_temp_fold_to_local_days(self):
        d0 = datetime.datetime(2026, 10, 23, tzinfo=datetime.timezone.utc).timestamp()   # 현지 10-23 09:00
        rain = [(d0 + 3600.0, 4.0), (d0 + 7200.0, 6.0)]                                   # daily_sum → 10 mm
        temp = [(d0 - KST + h * 3600.0, 10.0 + h * 0.2) for h in range(24)]              # 현지 10-23 하루 24시간
        r = _run(observed={'rain': rain, 't_air': temp})
        self.assertEqual(r['rain']['obs'].get('2026-10-23'), 10.0)
        self.assertEqual(r['temp']['obs']['2026-10-23'][:2], [10.0, 14.6])      # (최저, 최고, 평균)

    def test_theta_points_are_hourly_means(self):
        pts = [(NOW - 7200.0 + 60.0, 20.0), (NOW - 7200.0 + 1800.0, 22.0), (NOW - 3600.0, 25.0)]
        r = _run(observed={'theta': pts})
        self.assertEqual(len(r['theta']['obs']), 2)
        self.assertEqual(r['theta']['obs'][0][1], 21.0)

    def test_forecast_daily_rows_fill_future_only(self):
        fc = {'available': True, 'source': {'name': '예보', 'input_id': 'f1'}, 'source_basis': 'designated',
              'daily': [{'date': '2026-10-24', 'precip_mm': 9.0},
                        {'date': '2026-10-26', 'precip_mm': 5.0, 'et0_mm': 3.1, 'temp_min_c': 4.0, 'temp_max_c': 15.5}]}
        r = _run(forecast=fc)
        self.assertEqual(r['rain']['fc'], {'2026-10-26': 5.0})
        self.assertEqual(r['temp']['fc']['2026-10-26'], [4.0, 15.5])
        self.assertEqual(r['sources']['forecast']['name'], '예보')

    def test_forecast_unavailable_records_reason(self):
        r = _run(forecast={'available': False, 'reason': 'none_designated'})
        self.assertEqual(r['sources']['forecast'], {'reason': 'none_designated'})

    def test_sources_label_the_series(self):
        r = _run()
        self.assertNotIn('provenance', r['sources']['theta'])       # 출처 표시 구분은 걷었다
        self.assertIn('토양센서', r['sources']['theta']['name'])

    def test_refs_absent_when_publication_has_no_baseline(self):
        self.assertIsNone(_run()['refs'])

    def _with_refs(self, a=1.0, b=0.0, sensor_coef=True):
        m = _meta()
        m[(P, M['theta_fc'])] = [(T0, 30.0)]
        m[(P, M['theta_wp'])] = [(T0, 12.0)]
        m[(P, M['theta_thr'])] = [(T0, 19.2)]
        if sensor_coef:
            m[(P, M['obs_a'])] = [(T0, a)]
            m[(P, M['obs_b'])] = [(T0, b)]
        return m

    def test_refs_in_root_units_when_sensorless(self):
        m = self._with_refs()
        m[(P, M['obs_n'])] = [(T0, 0.0)]
        r = _run(meta=m, curves=_curves(sensor=False))
        self.assertEqual(r['refs'], {'fc': 30.0, 'wp': 12.0, 'thr': 19.2})

    def test_refs_follow_curve_units_through_observation_equation(self):
        r = _run(meta=self._with_refs(a=0.8, b=2.0))             # 센서 단위 곡선 → y = a·θ + b
        self.assertEqual(r['theta']['kind'], 'sensor')
        self.assertEqual(r['refs'], {'fc': 26.0, 'wp': 11.6, 'thr': 17.36})

    def test_refs_dropped_when_units_cannot_be_matched(self):
        self.assertIsNone(_run(meta=self._with_refs(sensor_coef=False))['refs'])   # 센서 단위인데 계수가 없다
        self.assertIsNone(_run(meta=self._with_refs(a=0.0))['refs'])

    def test_refs_dropped_when_converted_values_make_no_sense(self):
        # 실측 3포장: 센서 계수로 옮긴 위조점·문턱이 음수 — 틀린 선을 그리느니 안 그린다
        self.assertIsNone(_run(meta=self._with_refs(a=0.5, b=-12.0))['refs'])
        self.assertIsNone(_run(meta=self._with_refs(a=1.0, b=-20.0))['refs'])

    def test_refs_not_sent_for_hidden_publication(self):
        m = self._with_refs()
        m[(P, M['status'])] = [(T0, 2.0)]
        self.assertIsNone(_run(meta=m)['refs'])

    def test_forecast_calibration_flag_is_carried(self):
        fc = {'available': True, 'source': {'name': '예보'}, 'daily': [], 'calibrated': True}
        self.assertTrue(_run(forecast=fc)['sources']['forecast']['calibrated'])
        fc2 = {'available': True, 'source': {'name': '예보'}, 'daily': []}
        self.assertFalse(_run(forecast=fc2)['sources']['forecast']['calibrated'])


if __name__ == '__main__':
    unittest.main()


class LineageAndVariants(unittest.TestCase):
    """D7 — 계보·분석 이력(`post`)·시나리오 곡선(`scenario`)."""

    def _lineage_meta(self, rev=2.0):
        m = _meta()
        m[(P, M['fc_issue_epoch'])] = [(T0, T0 - 600.0)]
        m[(P, M['fc_cal_rev'])] = [(T0, rev)]
        m[(P, M['obs_origin'])] = [(T0, 2.0)]
        return m

    def test_lineage_is_carried_from_the_header(self):
        r = _run(meta=self._lineage_meta())
        self.assertEqual(r['lineage'], {'calibrated': True, 'cal_rev': 2, 'fc_issue_epoch': T0 - 600.0,
                                        'origin': 2, 't0': T0})
        self.assertFalse(_run(meta=self._lineage_meta(rev=0.0))['lineage']['calibrated'])

    def test_lineage_is_unknown_without_the_columns(self):
        lin = _run()['lineage']
        self.assertIsNone(lin['calibrated'])
        self.assertIsNone(lin['origin'])

    def test_baseline_src_names_the_header(self):
        m = _meta()
        for k, v in (('theta_fc', 30.0), ('theta_wp', 12.0), ('theta_thr', 20.0)):
            m[(P, M[k])] = [(T0, v)]
        r = _run(meta=m, curves=_curves(sensor=False))
        self.assertEqual(r['baseline_src'], 'header')
        self.assertIsNone(_run()['baseline_src'])

    def test_no_post_or_scenario_unless_asked(self):
        r = _run()
        self.assertNotIn('post', r)
        self.assertNotIn('scenario', r)

    def test_post_keeps_the_past_before_t0_and_nothing_after(self):
        q = O.FIELD_DAILY_Q['theta_root']
        post = {(P, q + i): [(T0 - 3 * DAY, 10.0 + i), (T0 - DAY, 11.0 + i), (T0 + DAY, 99.0)] for i in range(3)}
        r = _run(post_rows=post)
        self.assertEqual(r['post']['theta']['kind'], 'root')
        self.assertEqual(r['post']['theta']['p50'], {'2026-10-22': 11.0, '2026-10-24': 12.0})
        self.assertNotIn('2026-10-26', r['post']['theta']['p50'])            # t0 이후는 예측의 몫
        self.assertEqual(r['post']['theta']['p10']['2026-10-24'], 11.0)
        self.assertEqual(set(r['theta']['p50']), {d for d in r['theta']['p50']})   # 기본 예측은 그대로

    def test_scenario_curves_have_the_baseline_shape(self):
        scn = {k: [(t, v + 5.0) for t, v in rows] for k, rows in _curves().items()}
        r = _run(scenario_rows=scn, scenario_id='ab12cd34')
        sc = r['scenario']
        self.assertEqual(sc['id'], 'ab12cd34')
        self.assertEqual(sc['theta']['kind'], r['theta']['kind'])
        self.assertEqual(sc['theta']['p50']['2026-10-25'], r['theta']['p50']['2026-10-25'] + 5.0)
        self.assertNotIn('2026-10-24', sc['theta']['p50'])                    # 시나리오도 t0 앞 잔재는 버린다
        self.assertIn('water_deficit', sc['events'])

    def test_scenario_hidden_when_the_baseline_publication_is_unusable(self):
        r = _run(meta=_meta(valid_h=-1), scenario_rows=_curves(), scenario_id='ab12cd34')
        self.assertNotIn('scenario', r)


def test_assemble_dates_follow_the_plot_tz_across_dst():
    """차트의 오늘·창 경계·관측 접기는 구획 시간대로 점마다 푼다 — 뉴욕 서머타임 시작 다음 날 새벽."""
    import datetime as dt
    from aot.utils import twin_chart as TC
    from aot.utils.timekit import wall_to_utc
    NY = 'America/New_York'
    now = wall_to_utc(dt.datetime(2027, 3, 14, 0, 30), NY).timestamp()      # EST 00:30 (아직 02:00 전)
    assert TC._local_day_n(now, NY) == (dt.date(2027, 3, 14) - dt.date(1970, 1, 1)).days
    mid0 = TC._local_midnight(TC._local_day_n(now, NY), NY)
    mid1 = TC._local_midnight(TC._local_day_n(now, NY) + 1, NY)
    assert mid0 == wall_to_utc(dt.datetime(2027, 3, 14, 0, 0), NY).timestamp()
    assert mid1 - mid0 == 23 * 3600.0                                       # 서머타임 시작일은 23 시간
    # 지금의 오프셋(-5h) 하나로 만들었다면 3/15 자정이 24 시간 뒤 = 3/15 01:00 EDT 로 어긋난다
    assert mid1 == wall_to_utc(dt.datetime(2027, 3, 15, 0, 0), NY).timestamp()
