# coding=utf-8
"""트윈 구획 묶음 조립기(`aot.utils.twin_read`) — 읽는 쪽 규칙을 서버에서 적용한다(계약 §7-4).

머리말을 먼저 보고 유효할 때만 곡선을 싣는다. 만료·숨김(status ≥ 2)은 이유만, 옛 발행이 남긴
`t0` 앞 점은 버린다(§6.1 덮어쓰기 규칙 — 과거 구간은 마지막 발행의 잔재).
"""
import unittest

from aot.twin import output as O
from aot.utils import twin_read as R

P, Q = 'plot-a', 'plot-b'
DAY = 86400.0
M = O.FIELD_META


def _rows(pid, t0, status=1, valid_h=36, days=8, old=True):
    meta = {(pid, M['status']): [(t0 - DAY, 1.0), (t0, float(status))],
            (pid, M['valid_until']): [(t0 - DAY, t0 + 12 * 3600), (t0, t0 + valid_h * 3600)],
            (pid, M['sync_rmse_theta_1d']): [(t0, 1.1)], (pid, M['coverage_80']): [(t0, 0.9)]}
    curve = {}
    for name, ch in R.CURVE_CHANNELS.items():
        base = 20.0 if name.startswith('theta') else 0.2
        pts = [(t0 + k * DAY, base + k + (1 if name.endswith('p90') else -1 if name.endswith('p10') else 0))
               for k in range(days)]
        if old:
            pts = [(t0 - DAY, 999.0)] + pts          # 옛 발행의 잔재
        curve[(pid, ch)] = pts
    return meta, curve


class SharedRulesTest(unittest.TestCase):
    """탭(`twin_chart`)과 MCP(`twin_soil`)가 같이 쓰는 값 기준·신뢰 판정."""

    def test_basis_is_sensor_unless_sensorless_or_no_sensor_curve(self):
        self.assertEqual('sensor', R.theta_basis(True, False))
        self.assertEqual('root', R.theta_basis(True, True))
        self.assertEqual('root', R.theta_basis(False, False))

    def test_sensorless_means_zero_observations_and_unknown_is_not_sensorless(self):
        self.assertTrue(R.sensorless({'obs_n': 0.0}))
        self.assertFalse(R.sensorless({'obs_n': 2.0}))
        self.assertFalse(R.sensorless({}))                       # 옛 발행(칸 없음)
        self.assertFalse(R.sensorless(None))

    def test_trust_thresholds_and_order(self):
        t = R.trust({'status': 1.0, 'obs_n': 0.0, 'sync_rmse_theta_1d': 11.48, 'coverage_80': 0.14}, True)
        self.assertEqual(['degraded', 'sensorless', 'error', 'coverage'], t['cautions'])
        self.assertTrue(t['reference_only'])
        self.assertEqual({'cautions': ['error'], 'reference_only': True}, R.trust({'sync_rmse_theta_1d': 3.01}, True))
        self.assertEqual({'cautions': [], 'reference_only': False}, R.trust({'sync_rmse_theta_1d': 3.0, 'coverage_80': 0.6}, True))
        self.assertEqual({'cautions': [], 'reference_only': False}, R.trust(None, True))
        self.assertEqual({'cautions': ['coverage'], 'reference_only': False}, R.trust({'coverage_80': 0.1}, False))

    def test_map_bundle_stays_small_and_soil_extra_adds_only_sensor_p10_p90(self):
        meta, curve = _rows(P, 1792422000.0)
        for name, ch in R.SOIL_EXTRA_CHANNELS.items():
            curve[(P, ch)] = [(1792422000.0 + k * DAY, 10.0 + k) for k in range(8)]
        args = ([P], meta, curve, 1792422000.0 + 9 * 3600, 1792422000.0 - DAY, 1792422000.0 + 8 * DAY)
        [plain] = R.plots_bundle(*args)
        [wide] = R.plots_bundle(*args, extra=R.SOIL_EXTRA_CHANNELS)
        self.assertFalse(set(R.SOIL_EXTRA_CHANNELS) & set(plain))
        self.assertEqual(set(R.SOIL_EXTRA_CHANNELS), set(wide) - set(plain))
        self.assertEqual(wide['theta_sensor_p10'][0], 10.0)


class PlotsBundleTest(unittest.TestCase):
    t0 = 1792422000.0
    now = t0 + 9 * 3600

    def test_usable_publication_curve_from_t0(self):
        meta, curve = _rows(P, self.t0)
        [rec] = R.plots_bundle([P], meta, curve, self.now, self.t0 - DAY, self.t0 + 8 * DAY)
        self.assertTrue(rec['usable'], rec['reason'])
        self.assertEqual(rec['meta']['t0'], self.t0)
        self.assertEqual(rec['meta']['valid_until'], self.t0 + 36 * 3600)   # 최신 t0 의 값
        self.assertEqual(rec['days'][0], self.t0)                          # 옛 잔재(t0 − 1 일) 없음
        self.assertEqual(len(rec['days']), 8)
        self.assertEqual(rec['theta_root_p50'][:2], [20.0, 21.0])
        self.assertTrue(all(a <= b <= c for a, b, c in zip(rec['theta_root_p10'], rec['theta_root_p50'],
                                                           rec['theta_root_p90'])))

    def test_expired_and_hidden_carry_reason_only(self):
        m1, c1 = _rows(P, self.t0, valid_h=1)
        m2, c2 = _rows(Q, self.t0, status=2, valid_h=0)
        meta, curve = {**m1, **m2}, {**c1, **c2}
        recs = {r['plot_uuid']: r for r in R.plots_bundle([P, Q, 'none'], meta, curve, self.now,
                                                          self.t0, self.t0 + 8 * DAY)}
        self.assertEqual((recs[P]['usable'], recs[P]['reason']), (False, 'expired'))
        self.assertEqual((recs[Q]['usable'], recs[Q]['reason']), (False, 'status_2'))
        self.assertEqual((recs['none']['usable'], recs['none']['reason']), (False, 'no_publication'))
        self.assertNotIn('days', recs[P])

    def test_window_cut(self):
        meta, curve = _rows(P, self.t0)
        [rec] = R.plots_bundle([P], meta, curve, self.now, self.t0 + 2 * DAY, self.t0 + 4 * DAY)
        self.assertEqual(rec['days'], [self.t0 + 2 * DAY, self.t0 + 3 * DAY, self.t0 + 4 * DAY])
        # 창이 낮(09 시)에 시작해도 그날(00 시 점)은 들어온다 — 지도의 '지금'이 오늘을 칠해야 한다
        [rec] = R.plots_bundle([P], meta, curve, self.now, self.now, self.t0 + 2 * DAY)
        self.assertEqual(rec['days'], [self.t0, self.t0 + DAY, self.t0 + 2 * DAY])
        [rec] = R.plots_bundle([P], meta, curve, self.now, self.t0 + 20 * DAY, self.t0 + 21 * DAY)
        self.assertEqual((rec['usable'], rec['reason']), (False, 'no_curve_in_window'))


if __name__ == '__main__':
    unittest.main()
