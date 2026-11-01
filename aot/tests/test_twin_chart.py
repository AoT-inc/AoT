# coding=utf-8
"""트윈 구획 그래프 묶음 조립기(`aot.utils.twin_chart.assemble`) — Influx·DB 를 건드리지 않고 읽어 온 값만 조립한다.

규칙: 유효한 발행만 곡선을 싣고(만료·숨김은 이유만, 마지막 값으로 채우지 않는다), 옛 발행의 잔재(`t0` 앞)는 버리며,
센서 칸 예측이 있으면 그 단위로, 센서 없는 구획은 뿌리층 단위로 싣는다. 날짜는 문자열 키.
"""
import datetime
import unittest

from aot.twin import output as O
from aot.utils import twin_chart as C

P = 'plot-a'
DAY = 86400.0
M = O.FIELD_META
NOW = datetime.datetime(2026, 10, 25, 3, 0, tzinfo=datetime.timezone.utc).timestamp()   # KST 12:00
T0 = datetime.datetime(2026, 10, 25, tzinfo=datetime.timezone.utc).timestamp()
KST = 9 * 3600.0


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
                      forecast=forecast, tz_s=KST, tz_name='Asia/Seoul', names={'dev1': ('토양센서', 'x')}, **extra)


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
