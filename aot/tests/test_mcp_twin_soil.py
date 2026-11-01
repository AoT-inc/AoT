# coding=utf-8
"""트윈 토양 수분 조회(시범) — `measure.soil_forecast` → `get_plot(detail='twin_soil')` → `utils/twin_soil`.

고정하는 계약:
  1. 읽기 규칙은 지도 예측 제공자와 같다(`twin_read.usable`): 만료·계산 불가·발행 없음은 값을 채우지 않고
     이유만 말한다.
  2. 게이트는 트윈 플래그(`twin_config.ui_enabled`)이고, 시설 구획은 범위 밖이다.
  3. 새 도구·새 인자 이름이 없다 — operation 은 기존 `get_plot` 과 기존 이름 `detail` 을 쓴다.
  4. 응답은 날짜별 p10/p50/p90 과 사건 확률, 발행·유효 시각, 품질 머리말만 싣는다.
Influx·DB 없이 도는 결정론적 테스트다.
"""
import unittest
from types import SimpleNamespace
from unittest import mock

from aot.twin import output as O
from aot.utils import twin_read, twin_soil

NOW = 1_800_000_000.0
DAY = 86400.0
T0 = NOW - 3600.0
PID = 'plot-1'


def _plot(**kw):
    return SimpleNamespace(**dict(dict(unique_id=PID, name='콩 1구', subject='콩', facility_uuid=None), **kw))


def _rows(status=0, valid_until=NOW + 6 * 3600.0, days=3, with_curves=True):
    M, Q, E = O.FIELD_META, O.FIELD_DAILY_Q, O.FIELD_DAILY_EVENTS
    meta = {(PID, M['status']): [(T0, status)], (PID, M['valid_until']): [(T0, valid_until)],
            (PID, M['ensemble_size']): [(T0, 30)], (PID, M['obs_n']): [(T0, 2)],
            (PID, M['coverage_80']): [(T0, 0.8123)], (PID, M['horizon_d']): [(T0, 7)]}
    curves = {}
    if with_curves:
        for i in range(3):
            curves[(PID, Q['theta_root'] + i)] = [(NOW + d * DAY, 20.0 + 5 * i + d) for d in range(days)]
        curves[(PID, E['water_deficit'])] = [(NOW + d * DAY, 0.1 * d) for d in range(days)]
        curves[(PID, E['waterlogging'])] = [(NOW + d * DAY, 0.0) for d in range(days)]
    return meta, curves


def _run(meta, curves, plot=None, enabled=True):
    def fake_read(measurement, ids, channels, start, end):
        return meta if measurement == O.M_FLD_META else curves
    with mock.patch('aot.utils.twin_config.ui_enabled', return_value=enabled), \
            mock.patch('aot.utils.influx.read_twin_many', side_effect=fake_read), \
            mock.patch('aot.utils.device_tz.location_iso',
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
