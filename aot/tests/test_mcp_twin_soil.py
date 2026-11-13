# coding=utf-8
"""트윈 토양 수분 조회(시범) — `measure.soil_forecast` → `get_plot(detail='twin_soil')` → `utils/twin_soil`.

고정하는 계약:
  1. 읽기 규칙은 지도 예측 제공자와 같다(`twin_read.usable`): 만료·계산 불가·발행 없음은 값을 채우지 않고
     이유만 말한다.
  2. 게이트는 트윈 플래그(`twin_config.ui_enabled`)이고, 시설 구획은 범위 밖이다.
  3. 새 도구·새 인자 이름이 없다 — operation 은 기존 `get_plot` 과 기존 이름 `detail` 을 쓴다.
  4. 응답은 날짜별 p10/p50/p90 과 사건 확률, 발행·유효 시각, 품질 머리말만 싣는다.
  5. 값 기준은 지도 모달 트윈 탭과 하나다(`basis`) — 같은 발행이면 탭 그래프의 p10·p50·p90 과 같은 수.
  6. 믿을 만한가의 판정(`reference_only`·`cautions`)도 탭과 같은 함수(`twin_read.trust`) — 참고용이면 AI 가 단정하지 않게 `_reading`.
Influx·DB 없이 도는 결정론적 테스트다.
"""
import calendar
import datetime
import unittest
from types import SimpleNamespace
from unittest import mock

import pytz

from aot.twin import output as O
from aot.utils import twin_read, twin_soil

NOW = 1_800_000_000.0
DAY = 86400.0
T0 = NOW - 3600.0
PID = 'plot-1'


def _plot(**kw):
    return SimpleNamespace(**dict(dict(unique_id=PID, name='콩 1구', subject='콩', facility_uuid=None), **kw))


def _rows(status=0, valid_until=NOW + 6 * 3600.0, days=3, with_curves=True, t0=T0, c0=NOW):
    """`t0` = 발행 시각, `c0` = 일 격자 첫 점(기본은 NOW 부터 하루씩)."""
    M, Q, E = O.FIELD_META, O.FIELD_DAILY_Q, O.FIELD_DAILY_EVENTS
    T0 = t0
    meta = {(PID, M['status']): [(T0, status)], (PID, M['valid_until']): [(T0, valid_until)],
            (PID, M['ensemble_size']): [(T0, 30)], (PID, M['obs_n']): [(T0, 2)],
            (PID, M['coverage_80']): [(T0, 0.8123)], (PID, M['horizon_d']): [(T0, 7)]}
    curves = {}
    if with_curves:
        for i in range(3):
            curves[(PID, Q['theta_root'] + i)] = [(c0 + d * DAY, 20.0 + 5 * i + d) for d in range(days)]
        curves[(PID, E['water_deficit'])] = [(c0 + d * DAY, 0.1 * d) for d in range(days)]
        curves[(PID, E['waterlogging'])] = [(c0 + d * DAY, 0.0) for d in range(days)]
    return meta, curves


def _run(meta, curves, plot=None, enabled=True):
    def fake_read(measurement, ids, channels, start, end):
        return meta if measurement == O.M_FLD_META else curves
    with mock.patch('aot.utils.twin_config.ui_enabled', return_value=enabled), \
            mock.patch('aot.utils.influx.read_twin_many', side_effect=fake_read), \
            mock.patch('aot.utils.timekit.tz_of', return_value=pytz.utc), \
            mock.patch('aot.utils.timekit.iso_at',
                       side_effect=lambda t, pid, cache=None: '2027-01-%02dT00:00:00+09:00' % (1 + int((t - NOW) // DAY))
                       if t >= NOW - 1 else '2026-12-31T00:00:00+09:00'):
        return twin_soil.soil_moisture(plot or _plot(), now=NOW)


class SoilMoisture(unittest.TestCase):

    def test_usable_publication_gives_daily_quantiles_and_events(self):
        out = _run(*_rows())
        self.assertEqual('success', out['status'])
        self.assertEqual(3, len(out['days']))
        d0 = out['days'][0]
        self.assertEqual((20.0, 25.0, 30.0), (d0['p10'], d0['p50'], d0['p90']))
        self.assertEqual(0.1, out['days'][1]['p_dry'])
        self.assertEqual(0.81, out['quality']['coverage_80'])
        self.assertEqual(30, out['quality']['ensemble_size'])
        self.assertEqual('ok', out['twin_status'])
        self.assertIn('not a measurement', out['source'])

    def test_expired_publication_says_so_and_fills_nothing(self):
        out = _run(*_rows(valid_until=NOW - 1.0))
        self.assertEqual(('unavailable', 'expired'), (out['status'], out['reason']))
        self.assertNotIn('days', out)

    def test_not_computable_adds_the_setup_word(self):
        with mock.patch('aot.utils.twin_config.plot_diagnoses', return_value={PID: 'no_sensor'}):
            out = _run(*_rows(status=2))
        self.assertEqual('status_2', out['reason'])
        self.assertEqual('no_sensor', out['setup'])

    def test_no_publication(self):
        out = _run({}, {})
        self.assertEqual('no_publication', out['reason'])

    def test_switched_off_and_facility_plots_are_out(self):
        self.assertEqual('twin_disabled', _run(*_rows(), enabled=False)['reason'])
        self.assertEqual('facility_plot', _run(*_rows(), plot=_plot(facility_uuid='f1'))['reason'])

    def test_no_curve_in_window(self):
        out = _run(*_rows(with_curves=False))
        self.assertEqual(('unavailable', 'no_curve_in_window'), (out['status'], out['reason']))


# 8084 김제 3포장 '검정콩' 구획(949bbd35)의 실제 머리말: 뿌리층 p50 38.5 인데 센서 단위로는 16.0 (y = 0.651·θ − 8.83),
# 1일 오차 11.48 %p, 80% 구간 적중률 0.14 — 탭은 '참고용', MCP 는 예전에 '물 부족 걱정 없음' 이라 단정했다.
A_OBS, B_OBS = 0.651, -8.83


def _kimje_rows(days=3, sync_rmse=11.48, coverage=0.14, obs_n=2, sensor=True, t0=T0, c0=NOW):
    M, Q = O.FIELD_META, O.FIELD_DAILY_Q
    T0 = t0
    meta, curves = _rows(days=days, t0=t0, c0=c0)
    meta[(PID, M['sync_rmse_theta_1d'])] = [(T0, sync_rmse)]
    meta[(PID, M['coverage_80'])] = [(T0, coverage)]
    meta[(PID, M['obs_n'])] = [(T0, obs_n)]
    meta[(PID, M['obs_a'])] = [(T0, A_OBS)]
    meta[(PID, M['obs_b'])] = [(T0, B_OBS)]
    for i in range(3):                                           # 뿌리층 p10/p50/p90 = 36.5/38.5/40.5 (+하루 0.1)
        curves[(PID, Q['theta_root'] + i)] = [(c0 + d * DAY, 36.5 + 2 * i + 0.1 * d) for d in range(days)]
        if sensor:
            curves[(PID, Q['theta_sensor'] + i)] = [
                (c0 + d * DAY, A_OBS * (36.5 + 2 * i + 0.1 * d) + B_OBS) for d in range(days)]
    return meta, curves


def _tab(meta, curves, days=3, tz_s=0.0, now=NOW, tz_name='UTC'):
    """같은 행으로 지도 모달 트윈 탭의 그래프 묶음을 조립한다(`twin_chart.assemble`)."""
    from aot.utils import twin_chart as C
    view = {'inputs': {}, 'options': {}}
    return C.assemble(PID, now, 0, days - 1, view=view, meta_rows=meta, curve_rows=curves, observed={},
                      forecast=None, tz_offset_s=tz_s, tz_name=tz_name, names={})


def _grid(tz_name, first, n, pub_at):
    """엔진이 만드는 일 격자 — 발행 때 오프셋으로 `t0 = 오늘 * 86400 - tz`, 이후 24 시간씩(일광절약시간을 넘어도 그대로)."""
    import zoneinfo
    tz = pub_at.astimezone(zoneinfo.ZoneInfo(tz_name)).utcoffset().total_seconds()
    t0 = calendar.timegm(first.timetuple()) - tz
    return [t0 + k * DAY for k in range(n)]


def _offset_at(tz_name, now):
    import zoneinfo
    return datetime.datetime.fromtimestamp(now, zoneinfo.ZoneInfo(tz_name)).utcoffset().total_seconds()


def _run_local(meta, curves, tz_name, now):
    """`_run` 과 같되 구획의 시간대(`tz_of`)와 시각 라벨(`iso_at`)이 실제 시간대를 따른다."""
    import zoneinfo

    def fake_read(measurement, ids, channels, start, end):
        return meta if measurement == O.M_FLD_META else curves

    def local_iso(t, pid, cache=None):
        return datetime.datetime.fromtimestamp(t, zoneinfo.ZoneInfo(tz_name)).isoformat()
    with mock.patch('aot.utils.twin_config.ui_enabled', return_value=True), \
            mock.patch('aot.utils.influx.read_twin_many', side_effect=fake_read), \
            mock.patch('aot.utils.timekit.tz_of', return_value=pytz.timezone(tz_name)), \
            mock.patch('aot.utils.timekit.iso_at', side_effect=local_iso):
        return twin_soil.soil_moisture(_plot(), now=now)


class OneBasisWithTheTab(unittest.TestCase):

    def test_mcp_values_equal_the_tab_values_on_the_same_local_date(self):
        """일 격자 점은 대지 현지 00:00 이다(한국 11-02 = 11-01 15:00Z). 탭과 MCP 는 같은 **현지 날짜**에 같은 수를 내야 한다 —
        UTC 날짜로 접던 탭은 한국에서 값을 하루 앞 날짜에 붙였다. 동쪽·서쪽·반시간·날짜변경선 양끝·남반구를 본다."""
        for name in ('Asia/Seoul', 'UTC', 'America/Los_Angeles', 'Pacific/Kiritimati', 'Etc/GMT+12', 'Asia/Kolkata',
                     'Australia/Sydney'):
            with self.subTest(tz=name):
                pub = datetime.datetime(2026, 11, 2, 12, tzinfo=datetime.timezone.utc)
                g = _grid(name, datetime.date(2026, 11, 2), 3, pub)
                now = g[0] + 10 * 3600.0                          # 현지 오전 10 시
                meta, curves = _kimje_rows(t0=g[0], c0=g[0])
                out = _run_local(meta, curves, name, now)
                tab = _tab(meta, curves, tz_s=_offset_at(name, now), now=now, tz_name=name)
                self.assertEqual('2026-11-02', tab['today'])
                self.assertEqual(['2026-11-02', '2026-11-03', '2026-11-04'], sorted(tab['theta']['p50'])[:3])
                self.assertEqual(['2026-11-02', '2026-11-03', '2026-11-04'], [d['date'] for d in out['days']])
                for d in out['days']:
                    for p in ('p10', 'p50', 'p90'):
                        self.assertEqual(round(tab['theta'][p][d['date']], 1), d[p], (name, d['date'], p))
                self.assertAlmostEqual(A_OBS * 38.5 + B_OBS, tab['theta']['p50']['2026-11-02'], delta=0.1)   # 오늘 = 격자 첫 점

    def test_new_york_dst_end_grid_gives_one_date_per_day_in_both_places(self):
        """2026-11-01 02:00 EDT→EST. 10-31 발행 격자는 11-02 점이 11-01 23:00 EST 라, 점별 벽시계 날짜는 11-01 이 겹친다."""
        name = 'America/New_York'
        g = _grid(name, datetime.date(2026, 10, 31), 4, datetime.datetime(2026, 10, 31, 6, tzinfo=datetime.timezone.utc))
        meta, curves = _kimje_rows(days=4, t0=g[0], c0=g[0])
        out = _run_local(meta, curves, name, g[0] + 3600.0)       # 발행 직후 읽기(10-31)
        dates = [d['date'] for d in out['days']]
        self.assertEqual(['2026-10-31', '2026-11-01', '2026-11-02', '2026-11-03'], dates)
        tab = _tab(meta, curves, days=4, tz_s=_offset_at(name, g[0] + 3600.0), now=g[0] + 3600.0, tz_name=name)
        self.assertEqual(dates, sorted(tab['theta']['p50'])[:4])
        for d in out['days']:
            self.assertEqual(round(tab['theta']['p50'][d['date']], 1), d['p50'])

    def test_mcp_values_equal_the_tab_values_for_the_same_publication(self):
        meta, curves = _kimje_rows()
        out, tab = _run(meta, curves), _tab(meta, curves)
        self.assertEqual('sensor', tab['theta']['kind'])
        self.assertEqual(tab['theta']['kind'], out['basis'])
        self.assertAlmostEqual(A_OBS * 38.5 + B_OBS, out['days'][0]['p50'], delta=0.1)   # 38.5(뿌리층)가 아니라 약 16.2(센서 단위)
        self.assertLess(out['days'][0]['p50'], 20)

    def test_basis_is_root_when_the_plot_has_no_sensor_forecast_or_no_sensor(self):
        meta, curves = _kimje_rows(sensor=False)                 # 센서 단위 곡선 자체가 없다
        out = _run(meta, curves)
        self.assertEqual(('root', 38.5), (out['basis'], out['days'][0]['p50']))
        self.assertIn('root layer', out['unit'])
        meta, curves = _kimje_rows(obs_n=0)                      # 센서 없이 모델만 — 곡선이 있어도 뿌리층
        out, tab = _run(meta, curves), _tab(meta, curves)
        self.assertEqual((tab['theta']['kind'], out['basis']), ('root', 'root'))

    def test_sensor_basis_is_labelled_and_event_probabilities_stay_root_layer(self):
        out = _run(*_kimje_rows())
        self.assertIn("sensor", out['unit'])
        self.assertIn('model prediction', out['unit'])
        self.assertIn('root-layer', out['note'])
        self.assertEqual(0.1, out['days'][1]['p_dry'])
        self.assertIn('not a measurement', out['source'])


class ReferenceOnly(unittest.TestCase):

    def test_off_forecast_plot_is_reference_only_with_a_reading_rule(self):
        out = _run(*_kimje_rows())                               # 1일 오차 11.48 > 3, 적중률 0.14 < 0.6
        self.assertTrue(out['reference_only'])
        self.assertEqual(['error', 'coverage'], out['cautions'])
        self.assertEqual(1, len(out['_reading']))
        self.assertIn('do not state that water is sufficient or short', out['_reading'][0])

    def test_mcp_verdict_equals_the_tab_verdict(self):
        for kw in ({}, {'sync_rmse': 1.0, 'coverage': 0.9}, {'obs_n': 0}, {'sync_rmse': 3.0, 'coverage': 0.6}):
            meta, curves = _kimje_rows(**kw)
            out, tab = _run(meta, curves), _tab(meta, curves)
            self.assertEqual(tab['trust']['reference_only'], out['reference_only'], kw)
            self.assertEqual(tab['trust']['cautions'], out['cautions'], kw)

    def test_matching_plot_is_not_reference_only_and_carries_no_reading(self):
        out = _run(*_kimje_rows(sync_rmse=1.0, coverage=0.9))
        self.assertEqual((False, []), (out['reference_only'], out['cautions']))
        self.assertNotIn('_reading', out)

    def test_degraded_alone_is_listed_but_is_not_reference_only(self):
        meta, curves = _kimje_rows(sync_rmse=1.0, coverage=0.9)
        meta[(PID, O.FIELD_META['status'])] = [(T0, 1)]
        out = _run(meta, curves)
        self.assertEqual((['degraded'], False), (out['cautions'], out['reference_only']))
        self.assertNotIn('_reading', out)

    def test_thresholds_live_in_twin_read(self):
        from aot.utils import twin_read
        self.assertEqual((3.0, 0.6), (twin_read.SYNC_RMSE_MAX, twin_read.COVERAGE_80_MIN))
        self.assertEqual([], twin_read.trust({'sync_rmse_theta_1d': 3.0, 'coverage_80': 0.6}, True)['cautions'])   # 경계는 걸리지 않는다


class Wiring(unittest.TestCase):

    def test_op_uses_existing_inner_tool_and_arg_name(self):
        from aot.tools.domain.registry_data import OPS
        o = {(x.tool, x.op): x for x in OPS}[('measure', 'soil_forecast')]
        self.assertEqual({'plot': 'get_plot'}, o.inner)
        self.assertEqual({'plot': {'detail': 'twin_soil'}}, o.defaults_by_kind)
        self.assertEqual('read', o.effect)

    def test_hint_rewrite_still_maps_get_plot_to_detail_plot(self):
        from aot.tools.domain import dispatch
        self.assertEqual('detail.plot', dispatch._inner_to_op()['get_plot'])

    def test_reader_shares_the_map_providers_usable_rule(self):
        import os
        with open(twin_soil.__file__.replace('.pyc', '.py'), encoding='utf-8') as f:
            src = f.read()
        self.assertIn('twin_read.usable', src)
        self.assertIn('twin_read.plots_bundle', src)
        self.assertTrue(callable(twin_read.usable))


if __name__ == '__main__':
    unittest.main()
