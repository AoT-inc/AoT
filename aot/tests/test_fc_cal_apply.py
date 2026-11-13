# coding=utf-8
"""예보 현장 보정 D5 — 소비자 연결: 적용·`forecast_series` 읽기 계약·L2 곡선·화면 요약.

계수는 손으로 만든다(방법 자체는 `test_fc_cal_core`). 여기서 보는 것:
- 보정을 쓰는 (변수, 리드대)만 바뀌고 나머지는 원본이다. 습도는 보정한 기온으로 다시 계산한다.
- `read()` 의 보정 계약 — 행마다 `calibrated`·바뀐 변수만의 `raw`, 응답 `calibrated`·`cal_rev`. 층 `raw` 는 원본, 끈 대지는 원본.
- 시간열을 접은 일 행은 보정한 시간열에서 다시 나온다.
- L2 곡선은 같은 값을 쓰고, 같은 발표본·같은 판은 한 번만 쓴다.
"""
import unittest
from unittest import mock

from flask import Flask

from aot.aot_flask.extensions import db
from aot.space import forecast_series as fs
from aot.databases.models import FcCalEvent
from aot.tests.test_forecast_series_read import H, T0, patched
from aot.utils.fc_cal import apply as CA
from aot.utils.fc_cal import common as C
from aot.utils.fc_cal import l2, store, view

SITE = 'site-1'
DAY = 86400.0
NOW = T0 + 100.0


def additive(b):
    return {'method': 'additive', 'strata': {'': {'b': b, 'n': 99, 'ne': 99.0}}}


def dew(b):
    return {'method': 'dew_point', 'strata': {'': {'b': b, 'n': 99, 'ne': 99.0}}}


def logratio(g):
    return {'method': 'log_ratio', 'strata': {'': {'g': g, 'n': 99, 'ne': 99.0}}}


def entry(kind, var, band, coef, status=C.ST_ADOPTED, **meta):
    return {'kind': kind, 'var': var, 'band': band, 'status': status, 'reason': 'x', 'method': 'm', 'coef': coef,
            'meta': meta, 'window_start': None, 'window_end': None}


def all_bands(kind, var, coef, status=C.ST_ADOPTED, **meta):
    return [entry(kind, var, b, coef, status, **meta) for b in C.BANDS[kind]]


def cells(n=4, t0=T0, temp=20.0, rh=60.0, rain=0.0, pop=None):
    out = []
    for i in range(n):
        c = {'time': t0 + i * H, 'end': t0 + (i + 1) * H, 'temp_c': temp + i, 'rh_pct': rh, 'wind_ms': 2.0,
             'precip_mm_h': rain, 'solar_w_m2': 0.0}
        if pop is not None:
            c['pop_pct'] = pop
        out.append(c)
    return out


class CalibratorPure(unittest.TestCase):
    def setUp(self):
        self.ctx = C.Ctx('UTC', 35.8, 127.1)

    def test_only_used_bands_change(self):
        # 0-6 시간대만 쓴다 — 리드 6 이상은 원본
        models = {('h', 'T', '0-6'): additive(-2.0)}
        cal = CA.Calibrator(models, self.ctx, 3)
        out, changed = cal.hourly_cells(cells(10), T0)
        self.assertEqual(changed, {'T'})
        self.assertAlmostEqual(out[0]['temp_c'], 18.0)
        self.assertEqual(out[0]['raw'], {'temp_c': 20.0})
        self.assertAlmostEqual(out[5]['temp_c'], 23.0)          # 리드 5 → 바뀜
        self.assertEqual(out[6]['temp_c'], 26.0)                # 리드 6 → 원본
        self.assertNotIn('raw', out[6])

    def test_humidity_uses_the_calibrated_temperature(self):
        models = {('h', 'T', '0-6'): additive(-3.0), ('h', 'RH', '0-6'): dew(0.0)}
        cal = CA.Calibrator(models, self.ctx, 1)
        out, changed = cal.hourly_cells(cells(1, temp=25.0, rh=50.0), T0)
        self.assertEqual(changed, {'T', 'RH'})
        # 이슬점은 그대로, 기온만 3°C 낮아졌으니 상대습도는 오른다
        self.assertGreater(out[0]['rh_pct'], 50.0)
        self.assertLessEqual(out[0]['rh_pct'], 100.0)
        self.assertEqual(out[0]['raw']['rh_pct'], 50.0)

    def test_values_keep_physical_limits(self):
        models = {('h', 'WS', '0-6'): logratio(-0.6931)}        # ×0.5
        cal = CA.Calibrator(models, self.ctx, 1)
        out, _ = cal.hourly_cells([dict(cells(1)[0], wind_ms=0.0)], T0)
        self.assertGreaterEqual(out[0].get('wind_ms', 0.0), 0.0)

    def test_nothing_in_force_is_a_noop(self):
        cal = CA.Calibrator({}, self.ctx, 0)
        self.assertFalse(cal)
        c = cells(3)
        out, changed = cal.hourly_cells(c, T0)
        self.assertEqual((out, changed), (c, set()))

    def test_daily_lead_and_min_max_order(self):
        models = {('d', 'TMAX', '0'): additive(-4.0), ('d', 'TMAX', '1'): additive(-4.0)}
        cal = CA.Calibrator(models, self.ctx, 2)
        issue = 20000
        days = {issue: {'temp_max_c': 10.0, 'temp_min_c': 8.0, 'precip_mm': 1.0},
                issue + 1: {'temp_max_c': 12.0, 'temp_min_c': 5.0},
                issue + 5: {'temp_max_c': 14.0, 'temp_min_c': 6.0}}
        out, raws, changed = cal.daily_days(days, issue)
        self.assertEqual(changed, {'TMAX'})
        # 오늘: 10 - 4 = 6 < 최저 8 → 서로 뒤집히지 않게 한 값으로 모은다
        self.assertEqual(out[issue]['temp_max_c'], out[issue]['temp_min_c'])
        self.assertAlmostEqual(out[issue + 1]['temp_max_c'], 8.0)
        self.assertEqual(out[issue + 5]['temp_max_c'], 14.0)     # 리드 5 → 이 대에는 보정 없음
        self.assertEqual(raws[issue + 1], {'temp_max_c': 12.0})
        self.assertNotIn(issue + 5, raws)

    def test_models_scope(self):
        entries = {('h', 'T', '0-6'): entry('h', 'T', '0-6', additive(1.0)),
                   ('h', 'T', '6-12'): entry('h', 'T', '6-12', additive(1.0), status=C.ST_CANDIDATE),
                   ('h', 'T', '12-24'): entry('h', 'T', '12-24', additive(1.0), status=C.ST_FORCED),
                   ('h', 'T', '24-48'): entry('h', 'T', '24-48', None, status=C.ST_NO_OBS),
                   ('h', 'RH', '0-6'): entry('h', 'RH', '0-6', dew(0.0), status=C.ST_OFF)}
        self.assertEqual(sorted(k[2] for k in CA.models_of(entries)), ['0-6', '12-24'])
        self.assertEqual(sorted(k[2] for k in CA.models_of(entries, 'all')), ['0-6', '12-24', '6-12'])


class DbCase(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.config.update(SQLALCHEMY_DATABASE_URI='sqlite://', SQLALCHEMY_TRACK_MODIFICATIONS=False)
        db.init_app(self.app)
        self.ctx = self.app.app_context()
        self.ctx.push()
        db.create_all()
        mock.patch.object(store, '_email_admins', return_value=0).start()
        self.addCleanup(mock.patch.stopall)
        fs.clear_cache()

    def tearDown(self):
        fs.clear_cache()
        db.session.remove()
        db.drop_all()
        self.ctx.pop()

    def adopt(self, entries, now=NOW):
        rev = store.write_rev(SITE, entries, now)
        db.session.commit()
        fs.clear_cache()
        return rev


def hourly_series(n=60, anchor=None):
    anchor = T0 if anchor is None else anchor
    rows = []
    for i in range(n):
        ep = anchor + i * H
        rows.append((ep, {'epoch': ep, 'TMP': 20.0, 'REH': 60, 'WSD': 2.0, 'VEC': 350, 'RN1': 0.0, 'POP': 10,
                          'CLD': 50, 'SOL': 0.0}))
    return {'rows': rows, 'input_id': 'in-1', 'source': 'OM hourly', 'model': 'open_meteo',
            'fetched_epoch': anchor + 600.0, 'issued_epoch': anchor,
            'meta': {'grid_latitude': 32.75, 'grid_longitude': 130.69, 'elevation': 4.0}}


class ReadContract(DbCase):
    def read(self, **kw):
        with patched(hourly_series()):
            return fs.read(SITE, now=NOW, **kw)

    def test_before_any_rev_everything_is_raw(self):
        out = self.read()
        self.assertEqual((out['calibrated'], out['cal_rev']), (False, 0))
        self.assertTrue(all(r['calibrated'] is False and 'raw' not in r for r in out['rows']))
        self.assertEqual(out['calibration']['variables'], [])

    def test_adopted_rev_is_applied_and_raw_is_kept(self):
        rev = self.adopt(all_bands('h', 'T', additive(-2.0)))
        out = self.read()
        self.assertEqual((out['calibrated'], out['cal_rev']), (True, rev))
        self.assertEqual(out['calibration']['variables'], ['T'])
        r0 = out['rows'][0]
        self.assertAlmostEqual(r0['temp_c'], 18.0)
        self.assertTrue(r0['calibrated'])
        self.assertEqual(r0['raw'], {'temp_c': 20.0})            # 바뀐 변수만
        self.assertEqual(r0['rh_pct'], 60.0)                     # 바뀌지 않은 변수는 원본 그대로

    def test_raw_layer_ignores_calibration(self):
        self.adopt(all_bands('h', 'T', additive(-2.0)))
        out = self.read(layer='raw')
        self.assertEqual((out['calibrated'], out['cal_rev']), (False, 0))
        self.assertEqual(out['rows'][0]['temp_c'], 20.0)
        self.assertNotIn('raw', out['rows'][0])

    def test_variable_subset_filters_raw(self):
        self.adopt(all_bands('h', 'T', additive(-2.0)))
        out = self.read(variables=['rh_pct'])
        self.assertFalse(out['rows'][0]['calibrated'])           # 요청한 변수는 안 바뀜
        self.assertNotIn('raw', out['rows'][0])

    def test_off_mode_is_raw_even_with_an_active_rev(self):
        self.adopt(all_bands('h', 'T', additive(-2.0)))
        store.set_site_mode(SITE, 'off')
        out = self.read()
        self.assertEqual((out['calibrated'], out['rows'][0]['temp_c']), (False, 20.0))
        self.assertEqual(out['calibration']['mode'], 'off')

    def test_corrected_layer_applies_candidates_auto_does_not(self):
        self.adopt(all_bands('h', 'T', additive(-2.0), status=C.ST_CANDIDATE))
        self.assertFalse(self.read()['calibrated'])
        out = self.read(layer='corrected')
        self.assertTrue(out['calibrated'])
        self.assertAlmostEqual(out['rows'][0]['temp_c'], 18.0)

    def test_hourly_without_issue_time_is_not_calibrated(self):
        self.adopt(all_bands('h', 'T', additive(-2.0)))
        s = hourly_series()
        s.pop('issued_epoch')
        with patched(s):
            out = fs.read(SITE, now=NOW)
        self.assertFalse(out['calibrated'])                      # 리드를 모르면 층을 못 고른다

    def test_folded_days_come_from_the_calibrated_series(self):
        self.adopt(all_bands('h', 'T', additive(-2.0)))
        with patched(hourly_series(n=72, anchor=T0 - (T0 % DAY))):
            raw = fs.read(SITE, now=T0 - (T0 % DAY) + 100.0, layer='raw')
            out = fs.read(SITE, now=T0 - (T0 % DAY) + 100.0)
        self.assertTrue(raw['daily'] and out['daily'])
        d_raw, d_cal = raw['daily'][0], out['daily'][0]
        self.assertAlmostEqual(d_cal['temp_max_c'], d_raw['temp_max_c'] - 2.0)
        self.assertEqual(d_cal['raw']['temp_max_c'], d_raw['temp_max_c'])
        self.assertTrue(d_cal['calibrated'])

    def test_daily_input_days_use_daily_entries(self):
        self.adopt(all_bands('d', 'TMAX', additive(-1.5)))
        base = T0 - (T0 % DAY)
        day = int(base // DAY)
        daily = {'input_id': 'in-2', 'source': 'OM daily', 'fetched_epoch': base + 3600.0, 'tz': 'UTC',
                 'tz_offset_s': 0.0, 'days': {day + k: {'temp_max_c': 20.0 + k, 'temp_min_c': 5.0} for k in range(5)}}
        with patched(hourly_series(n=12, anchor=base), daily=daily):
            out = fs.read(SITE, now=base + 100.0)
        d = {r['date']: r for r in out['daily']}
        first = out['daily'][-1]                                  # 시간열이 덮지 못한 뒤쪽 일 행
        self.assertTrue(first['calibrated'])
        self.assertAlmostEqual(first['temp_max_c'], first['raw']['temp_max_c'] - 1.5)
        self.assertEqual(out['calibration']['daily'], True)
        self.assertTrue(d)

    def test_source_info_reports_calibration(self):
        rev = self.adopt(all_bands('h', 'T', additive(-2.0)))
        with patched(hourly_series()):
            info = fs.source_info(fs.site_series(SITE, NOW, fallback=False))
            blk = fs.site_forecast_block(SITE, NOW)
        self.assertEqual((info['calibrated'], info['cal_rev']), (True, rev))
        self.assertEqual((blk['calibrated'], blk['cal_rev']), (True, rev))

    def test_slider_state_reads_the_calibrated_value(self):
        self.adopt(all_bands('h', 'T', additive(-2.0)))
        with patched(hourly_series()):
            got = fs.state_at(SITE, T0 + 2 * H, NOW)
        self.assertAlmostEqual(got['candidates']['temp'][0]['value'], 18.0)
        self.assertTrue(got['info']['calibrated'])

    def test_unknown_calibration_is_rejected(self):
        with self.assertRaises(ValueError):
            fs.site_series(SITE, NOW, calibration='both')


class L2Curves(DbCase):
    class IO:
        def site_info(self, site_id):
            return {'tz': 'UTC', 'lat': 35.8, 'lon': 127.1, 'hourly_input': 'in-1', 'daily_input': None}

    def issue(self, base=T0):
        series = {'T': {base + k * H: 20.0 for k in range(49)}, 'RH': {base + k * H: 60.0 for k in range(49)},
                  'POP': {base + k * H: 10.0 for k in range(49)}}
        return {'fetched': base + 600.0, 'base': base, 'series': series, 'meta': {}}

    def test_writes_only_the_used_bands_with_cal_rev(self):
        rev = self.adopt(all_bands('h', 'T', additive(-2.0))[:2])      # 0-6, 6-12 만
        got = []
        with mock.patch('aot.utils.fc_store.latest_hourly_issue', return_value=self.issue()):
            n = l2.refresh_site(SITE, self.IO(), now=NOW, writer=lambda pts: got.extend(pts) or len(pts), force=True)
        self.assertEqual(n, 12)
        self.assertEqual({p.measurement for p in got}, {'fc_hourly_cal'})
        self.assertEqual({p.tags['cal_rev'] for p in got}, {str(rev)})
        self.assertEqual({p.tags['var'] for p in got}, {'T'})
        self.assertEqual(sorted(int(p.tags['lead_h']) for p in got), list(range(12)))
        self.assertTrue(all(abs(p.value - 18.0) < 1e-9 for p in got))
        self.assertEqual({p.timestamp - int(p.tags['lead_h']) * H for p in got}, {T0})

    def test_same_issue_and_rev_is_written_once(self):
        self.adopt(all_bands('h', 'T', additive(-2.0)))
        got = []
        w = lambda pts: got.extend(pts) or len(pts)
        l2._done.clear()
        with mock.patch('aot.utils.fc_store.latest_hourly_issue', return_value=self.issue()):
            a = l2.refresh_site(SITE, self.IO(), now=NOW, writer=w)
            b = l2.refresh_site(SITE, self.IO(), now=NOW, writer=w)
        self.assertGreater(a, 0)
        self.assertEqual(b, 0)

    def test_nothing_in_force_writes_nothing(self):
        got = []
        with mock.patch('aot.utils.fc_store.latest_hourly_issue', return_value=self.issue()):
            self.assertEqual(l2.refresh_site(SITE, self.IO(), now=NOW, writer=got.extend), 0)
        self.adopt(all_bands('h', 'T', additive(-2.0)))
        store.set_site_mode(SITE, 'off')
        with mock.patch('aot.utils.fc_store.latest_hourly_issue', return_value=self.issue()):
            self.assertEqual(l2.refresh_site(SITE, self.IO(), now=NOW, writer=got.extend), 0)
        self.assertEqual(got, [])

    def test_curve_equals_what_the_reader_serves(self):
        """계수 한 곳(`Calibrator`) — L2 곡선과 소비자가 읽는 값이 같다."""
        self.adopt(all_bands('h', 'T', additive(-2.0)) + all_bands('h', 'RH', dew(0.5)))
        got = []
        l2._done.clear()
        with mock.patch('aot.utils.fc_store.latest_hourly_issue', return_value=self.issue()):
            l2.refresh_site(SITE, self.IO(), now=NOW, writer=lambda pts: got.extend(pts) or len(pts))
        with patched(hourly_series(n=60)):
            out = fs.read(SITE, now=NOW)
        by = {(p.tags['var'], p.timestamp): p.value for p in got}
        for r in out['rows'][:20]:
            # 시간 칸의 순간 값은 칸 시작 정시의 L2 점과 같다
            self.assertAlmostEqual(r['temp_c'], by[('T', r['time'])])
            self.assertAlmostEqual(r['rh_pct'], by[('RH', r['time'])], places=6)


class ScreenView(DbCase):
    def test_collecting_before_any_check(self):
        v = view.site_view(SITE)
        self.assertEqual((v['mode'], v['state'], v['rev'], v['applied']), ('auto', 'collecting', 0, False))
        self.assertTrue(all(x['state'] == view.V_WAITING for x in v['variables']))

    def test_applied_state_and_gain(self):
        ent = all_bands('h', 'T', additive(-2.0), metrics={'mae_raw': 2.1, 'mae_cal': 0.9, 'n': 300})
        ent += all_bands('h', 'RH', dew(0.0), status=C.ST_CANDIDATE)
        ent += all_bands('h', 'SOL', None, status=C.ST_NO_OBS)
        self.adopt([e for e in ent])
        v = view.site_view(SITE)
        by = {(x['kind'], x['var']): x for x in v['variables']}
        self.assertEqual((v['state'], v['rev']), ('applied', 1))
        self.assertEqual(by[('h', 'T')]['state'], view.V_APPLIED)
        self.assertEqual(by[('h', 'T')]['gain'], {'before': 2.1, 'after': 0.9})
        self.assertEqual(by[('h', 'RH')]['state'], view.V_COLLECTING)
        self.assertEqual(by[('h', 'SOL')]['state'], view.V_NO_OBS)

    def test_off_mode_shows_off(self):
        self.adopt(all_bands('h', 'T', additive(-2.0)))
        store.set_site_mode(SITE, 'off')
        v = view.site_view(SITE)
        self.assertEqual((v['state'], v['rev'], v['applied']), ('off', 0, False))

    def test_events_and_ack(self):
        store.add_events(SITE, '시험 대지', 1, [{'event': 'adopted', 'kind': 'h', 'var': 'T', 'band': '0-6',
                                                'detail': {'metrics': {'mae_raw': 2.0, 'mae_cal': 1.0}}}], NOW,
                         email=False)
        db.session.commit()
        v = view.site_view(SITE)
        self.assertEqual((v['unacked'], v['events'][0]['event'], v['events'][0]['unit']), (1, 'adopted', '°C'))
        self.assertEqual(view.ack_events(SITE), 1)
        v = view.site_view(SITE)
        self.assertEqual((v['unacked'], v['events'][0]['acked']), (0, True))
        self.assertEqual(FcCalEvent.query.filter_by(acked=False).count(), 0)

    def test_changing_mode_asks_for_a_new_check(self):
        store.save_run(SITE, NOW, {})
        store.set_site_mode(SITE, 'on')
        self.assertIsNone(store.site_row(SITE).last_run_at)


if __name__ == '__main__':
    unittest.main()
