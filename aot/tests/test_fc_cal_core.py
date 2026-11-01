# coding=utf-8
"""예보 현장 보정 — 순수 계산부 시험: 짝짓기·방법·전진 검증·채택 규칙 (D4).

합성 편차 하네스: 알려진 편차를 심은 가짜 예보·관측으로 계수가 편차를 되찾는지, 전진 검증이 개선을 알아보고
(편차가 없으면 채택하지 않고), 미래 정보가 새지 않는지 본다. DB·Influx 는 쓰지 않는다.
"""
import math
import random
import unittest
from datetime import datetime, timezone

from aot.utils.fc_cal import common as C
from aot.utils.fc_cal import methods as M
from aot.utils.fc_cal import pairing as P
from aot.utils.fc_cal import validate as V

T0 = datetime(2026, 9, 1, tzinfo=timezone.utc).timestamp()      # 2026-09-01 00:00 UTC (월요일 아님은 상관없다)
NOW = T0 + 41 * 86400.0


def ctx(tz='UTC', lat=35.8, lon=127.1):
    return C.Ctx(tz, lat, lon)


def _truth_temp(t):
    h = (t % 86400) / 3600.0
    return 18.0 + 7.0 * math.sin((h - 9.0) / 24.0 * 2 * math.pi)


def synth_temp(days=40, bias_day=2.0, bias_night=0.5, noise=1.0, seed=1, leads=(1, 8, 15, 30), kind=C.KIND_H):
    rng = random.Random(seed)
    out = []
    for d in range(days):
        for h in range(24):
            t = T0 + d * 86400.0 + h * 3600.0
            truth = _truth_temp(t)
            for lead in leads:
                b = bias_day if 6 <= h < 18 else bias_night
                out.append(C.Pair(t, lead, truth + b + rng.gauss(0, noise), truth + rng.gauss(0, 0.2), None))
    return out


class BandsAndStrata(unittest.TestCase):
    def test_band_edges(self):
        self.assertEqual([C.band_of('h', x) for x in (0, 5, 6, 11, 12, 23, 24, 48)],
                         ['0-6', '0-6', '6-12', '6-12', '12-24', '12-24', '24-48', '24-48'])
        self.assertEqual([C.band_of('d', x) for x in range(8)], ['0', '1', '2-3', '2-3', '4-7', '4-7', '4-7', '4-7'])

    def test_stratum_keys_fine_to_coarse(self):
        c = ctx('Asia/Seoul')
        keys = c.stratum('h', T0 + 3 * 3600)                  # 12:00 KST 9월 → 낮, 가을
        self.assertEqual(keys, ['day|SON', 'day', ''])
        self.assertEqual(c.stratum('d', T0), ['SON', ''])


class Physics(unittest.TestCase):
    def test_dew_point_roundtrip(self):
        td = C.dew_point_c(20.0, 60.0)
        self.assertAlmostEqual(td, 12.0, delta=0.2)
        self.assertAlmostEqual(C.rh_from_dew(20.0, td), 60.0, delta=0.1)
        self.assertEqual(C.rh_from_dew(10.0, 25.0), 100.0)          # 이슬점이 기온보다 높으면 100 제한

    def test_clear_sky_zero_at_night_and_peaks_at_noon(self):
        noon = datetime(2026, 6, 21, 3, 0, tzinfo=timezone.utc).timestamp()        # 서울 정오 무렵
        self.assertGreater(C.clear_sky_ghi(37.5, 127.0, noon), 800.0)
        self.assertEqual(C.clear_sky_ghi(37.5, 127.0, noon + 12 * 3600), 0.0)


class Pairing(unittest.TestCase):
    def test_inst_needs_both_windows(self):
        self.assertEqual(P.inst_at({3600.0: 10.0, 7200.0: 14.0}, 3600.0), 12.0)
        self.assertIsNone(P.inst_at({3600.0: 10.0}, 3600.0))

    def test_hourly_pairs_instant_vs_window(self):
        obs = {3600.0: 10.0, 7200.0: 14.0}
        t = P.hourly_pairs('T', [(3600.0, 6, 11.0)], obs)
        self.assertEqual((t[0].fc, t[0].ob, t[0].lead), (11.0, 12.0, 6))
        r = P.hourly_pairs('RAIN', [(7200.0, 3, 0.4)], {7200.0: 0.5}, aux_fc={(7200.0, 3): 0.7})
        self.assertEqual((r[0].ob, r[0].aux), (0.5, 0.7))

    def test_daily_from_hourly_local_days_and_coverage(self):
        c = ctx('Asia/Seoul')
        # KST 하루(9/1) = UTC 8/31 15:00 ~ 9/1 15:00 — 창 끝 시각 8/31 16:00 ~ 9/1 15:00 UTC 가 이 날이다
        start = datetime(2026, 8, 31, 16, tzinfo=timezone.utc).timestamp()
        full = {start + h * 3600.0: float(h) for h in range(24)}
        got = P.daily_from_hourly(full, max, c)
        self.assertEqual(got, {datetime(2026, 9, 1, tzinfo=timezone.utc).timestamp(): 23.0})
        partial = {k: v for k, v in list(full.items())[:10]}
        self.assertEqual(P.daily_from_hourly(partial, max, c), {})


class Additive(unittest.TestCase):
    def test_recovers_day_night_bias(self):
        pairs = synth_temp()
        m = M.method_for('h', 'T')
        model = m.fit(pairs, NOW, C.Params(), ctx())
        self.assertAlmostEqual(model['strata']['day']['b'], -2.0, delta=0.3)       # 보정 = 관측 - 예보
        self.assertAlmostEqual(model['strata']['night']['b'], -0.5, delta=0.3)
        pr = pairs[100]
        self.assertLess(abs(m.apply(model, pr, ctx()) - pr.ob), abs(pr.fc - pr.ob) + 1.5)

    def test_too_few_samples_gives_no_model(self):
        self.assertIsNone(M.method_for('h', 'T').fit(synth_temp(days=1, leads=(1,))[:10], NOW, C.Params(), ctx()))

    def test_shrinks_toward_zero_with_few_samples(self):
        few = [C.Pair(T0 + i * 3600.0, 1, 20.0, 22.0, None) for i in range(31)]
        b = M.method_for('h', 'T').fit(few, T0 + 40 * 3600.0, C.Params(), ctx())['strata']['']['b']
        self.assertTrue(0.0 < b < 2.0)                         # 편차 +2 의 일부만 따라간다


class OtherMethods(unittest.TestCase):
    def test_dew_point_bias_and_rh_rebuild(self):
        rng = random.Random(3)
        pairs = []
        for i in range(24 * 30):
            t = T0 + i * 3600.0
            temp = _truth_temp(t)
            td_true = temp - 8.0
            rh_true = C.rh_from_dew(temp, td_true)
            fc_rh = C.rh_from_dew(temp + 0.3, td_true - 2.0 + rng.gauss(0, 0.5))         # 이슬점 -2 °C 낮은 예보
            pairs.append(C.Pair(t, 6, fc_rh, rh_true, (temp + 0.3, temp)))
        m = M.method_for('h', 'RH')
        model = m.fit(pairs, NOW, C.Params(), ctx())
        self.assertAlmostEqual(model['strata']['']['b'], 2.0, delta=0.4)
        pr = pairs[200]
        self.assertLess(abs(m.apply(model, pr, ctx()) - pr.ob), abs(pr.fc - pr.ob))
        self.assertTrue(0.0 <= m.apply(model, pr, ctx(), t_cal=pr.aux[1]) <= 100.0)

    def test_wind_ratio_clamped(self):
        rng = random.Random(4)
        pairs = [C.Pair(T0 + i * 3600.0, 6, 3.0 + rng.random(), (3.0 + rng.random()) * 1.4, None)
                 for i in range(24 * 20)]
        model = M.method_for('h', 'WS').fit(pairs, NOW, C.Params(), ctx())
        r = math.exp(model['strata']['']['g'])
        self.assertTrue(1.1 < r <= 2.0)
        huge = [C.Pair(T0 + i * 3600.0, 6, 1.0, 9.0, None) for i in range(24 * 20)]
        g = M.method_for('h', 'WS').fit(huge, NOW, C.Params(), ctx())['strata']['']['g']
        self.assertLessEqual(math.exp(g), 2.0 + 1e-9)

    def test_solar_ratio_daytime_only_and_capped_by_clear_sky(self):
        c = ctx()
        pairs = []
        for i in range(24 * 25):
            t = T0 + i * 3600.0
            cs = C.clear_sky_ghi(c.lat, c.lon, t - 1800.0)
            pairs.append(C.Pair(t, 6, 0.6 * cs, 0.5 * cs, None))                  # 예보가 20 % 과대
        m = M.method_for('h', 'SOL')
        model = m.fit(pairs, NOW, C.Params(), c)
        self.assertAlmostEqual(math.exp(model['strata']['']['g']), 0.5 / 0.6, delta=0.06)
        noon = next(p for p in pairs if C.clear_sky_ghi(c.lat, c.lon, p.t - 1800.0) > 500)
        self.assertLess(m.apply(model, noon, c), noon.fc)
        night = next(p for p in pairs if C.clear_sky_ghi(c.lat, c.lon, p.t - 1800.0) == 0.0)
        self.assertEqual(m.apply(model, night, c), 0.0)
        self.assertFalse(m.eligible(night, c))

    def test_solar_without_position_has_no_model(self):
        pairs = [C.Pair(T0 + i * 3600.0, 6, 100.0, 80.0, None) for i in range(100)]
        self.assertIsNone(M.method_for('h', 'SOL').fit(pairs, NOW, C.Params(), C.Ctx('UTC', None, None)))


def synth_rain(days=50, seed=5, drizzle=True):
    """예보: 비 오는 날 양 2 배 과대 + 안 오는 날에도 가끔 이슬비 예보(오경보). 관측: 하루 몇 시간만 비."""
    rng = random.Random(seed)
    out = []
    for d in range(days):
        wet_day = rng.random() < 0.3
        for h in range(24):
            t = T0 + d * 86400.0 + h * 3600.0
            raining = wet_day and 10 <= h < 15
            ob = rng.uniform(1.0, 3.0) if raining else 0.0
            fc = ob * 2.0 + rng.uniform(0, 0.3) if raining else 0.0
            pop = 0.9 if raining else 0.05
            if drizzle and not raining and rng.random() < 0.08:
                fc, pop = rng.uniform(0.1, 0.3), 0.15
            out.append(C.Pair(t, 6, fc, ob, pop))
    return out


class Rain(unittest.TestCase):
    def test_fit_cuts_false_alarms_and_scales_amount(self):
        pairs = synth_rain()
        m = M.method_for('h', 'RAIN')
        model = m.fit(pairs, NOW, C.Params(), ctx())
        self.assertIsNotNone(model)
        drizzle = C.Pair(T0, 6, 0.2, 0.0, 0.15)
        self.assertEqual(m.apply(model, drizzle, ctx()), 0.0)              # 오경보 이슬비는 0
        heavy = C.Pair(T0, 6, 4.0, 0.0, 0.9)
        self.assertLess(m.apply(model, heavy, ctx()), 4.0)                  # 과대 양을 줄인다
        dry = C.Pair(T0, 6, 0.0, 0.0, 0.0)
        self.assertEqual(m.apply(model, dry, ctx()), 0.0)                   # 없던 비를 만들지 않는다

    def test_no_events_no_model(self):
        dry = [C.Pair(T0 + i * 3600.0, 6, 0.0, 0.0, 0.0) for i in range(200)]
        self.assertIsNone(M.method_for('h', 'RAIN').fit(dry, NOW, C.Params(), ctx()))

    def test_ratio_when_few_wet_pairs(self):
        pairs = [C.Pair(T0 + i * 3600.0, 6, 2.0 if i % 20 == 0 else 0.0, 1.0 if i % 20 == 0 else 0.0, 0.5)
                 for i in range(400)]
        model = M.method_for('h', 'RAIN').fit(pairs, NOW, C.Params(), ctx())
        self.assertIn('ratio', model['amt'])
        self.assertTrue(0.5 <= model['amt']['ratio'] <= 1.0)


class ForwardValidation(unittest.TestCase):
    def _run(self, pairs, params=None, var='T'):
        p = params or C.Params()
        m = M.method_for('h', var)
        v = V.forward_validate(m, pairs, NOW, p, ctx())
        return v, V.summarize(v, 'h', var, p, seed=1)

    def test_biased_forecast_is_adopted(self):
        _v, s = self._run(synth_temp())
        self.assertGreater(s['metrics']['skill'], 0.3)
        self.assertGreater(s['ci_lo'], 0.0)
        self.assertLess(s['metrics']['mae_cal'], s['metrics']['mae_raw'])
        status, why = V.decide(s, None, None, NOW, C.Params(), 'h')
        self.assertEqual((status, why), (C.ST_ADOPTED, 'pass'))

    def test_unbiased_forecast_is_not_adopted(self):
        _v, s = self._run(synth_temp(bias_day=0.0, bias_night=0.0, seed=7))
        status, _why = V.decide(s, None, None, NOW, C.Params(), 'h')
        self.assertEqual(status, C.ST_CANDIDATE)

    def test_short_history_has_few_samples(self):
        _v, s = self._run(synth_temp(days=9))
        status, why = V.decide(s, None, None, NOW, C.Params(), 'h')
        self.assertEqual((status, why), (C.ST_FEW, 'eval_samples'))

    def test_no_future_leak_bias_that_starts_on_last_day_is_not_credited(self):
        pairs = synth_temp(days=20, bias_day=0.0, bias_night=0.0, seed=11)
        last_day = T0 + 19 * 86400.0
        pairs = [C.Pair(p.t, p.lead, p.fc + (3.0 if p.t >= last_day else 0.0), p.ob, None) for p in pairs]
        v, s = self._run(pairs)
        last = max(v['days'])
        a = v['days'][last]
        self.assertLessEqual(a['ae_raw'] - a['ae_cal'], 0.05 * a['ae_raw'])        # 마지막 날의 새 편차는 아직 모른다

    def test_reduced_mode_uses_standard_error_and_is_stricter(self):
        p = C.Params().reduced()
        self.assertEqual((p.bootstrap, p.step_days, p.window_days), (0, 2, 30))
        _v, s = self._run(synth_temp(days=35), p)
        self.assertIsNotNone(s['ci_lo'])
        self.assertEqual(V.decide(s, None, None, NOW, p, 'h')[0], C.ST_ADOPTED)

    def test_deadline_raises_timeout(self):
        m = M.method_for('h', 'T')
        with self.assertRaises(V.Timeout):
            V.forward_validate(m, synth_temp(), NOW, C.Params(), ctx(), deadline=0.0)


class Decision(unittest.TestCase):
    def _summ(self, skill_recent, ci_lo=0.2, n=500, days=30):
        return {'n': n, 'days': days, 'is_rain': False, 'ci_lo': ci_lo, 'ci_hi': 0.4,
                'metrics': {'n': n, 'skill': 0.3}, 'recent': {'n': 300, 'days': 14, 'skill': skill_recent}}

    def test_adopted_is_reverted_when_recent_worse(self):
        st, why = V.decide(self._summ(-0.05), C.ST_ADOPTED, None, NOW, C.Params(), 'h')
        self.assertEqual((st, why), (C.ST_REVERTED, 'recent_worse'))

    def test_adopted_kept_when_evidence_thins_but_recent_ok(self):
        st, _ = V.decide(self._summ(0.1, ci_lo=-0.1), C.ST_ADOPTED, None, NOW, C.Params(), 'h')
        self.assertEqual(st, C.ST_ADOPTED)

    def test_cooldown_after_revert(self):
        meta = {'reverted_at': NOW - 2 * 86400.0}
        st, why = V.decide(self._summ(0.1), C.ST_REVERTED, meta, NOW, C.Params(), 'h')
        self.assertEqual((st, why), (C.ST_REVERTED, 'cooldown'))
        st, _ = V.decide(self._summ(0.1), C.ST_REVERTED, {'reverted_at': NOW - 9 * 86400.0}, NOW, C.Params(), 'h')
        self.assertEqual(st, C.ST_ADOPTED)

    def test_modes(self):
        self.assertEqual(V.decide(self._summ(0.1), None, None, NOW, C.Params(), 'h', mode='off')[0], C.ST_OFF)
        weak = self._summ(-0.2, ci_lo=-0.3)
        self.assertEqual(V.decide(weak, None, None, NOW, C.Params(), 'h', mode='on')[0], C.ST_FORCED)
        self.assertEqual(V.decide(weak, None, None, NOW, C.Params(), 'h', has_model=False)[0], C.ST_FEW)

    def test_rain_needs_events(self):
        s = self._summ(0.1)
        s['is_rain'] = True
        s['metrics'].update(wet=3, bias_raw=0.1, bias_cal=0.05)
        self.assertEqual(V.decide(s, None, None, NOW, C.Params(), 'h'), (C.ST_FEW, 'rain_events'))
        s['metrics']['wet'] = 40
        self.assertEqual(V.decide(s, None, None, NOW, C.Params(), 'h')[0], C.ST_ADOPTED)
        s['metrics']['bias_cal'] = 0.5                               # 부피가 더 틀어지면 안 쓴다
        self.assertEqual(V.decide(s, None, None, NOW, C.Params(), 'h')[0], C.ST_CANDIDATE)


class RainValidation(unittest.TestCase):
    def test_brier_improves_on_biased_rain(self):
        p = C.Params()
        m = M.method_for('h', 'RAIN')
        v = V.forward_validate(m, synth_rain(days=60), NOW, p, ctx())
        s = V.summarize(v, 'h', 'RAIN', p, seed=2)
        self.assertGreater(s['metrics']['wet'], 20)
        self.assertGreater(s['metrics']['skill'], 0.0)
        self.assertIn('pod', s['metrics'])


if __name__ == '__main__':
    unittest.main()
