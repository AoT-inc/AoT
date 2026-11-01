# coding=utf-8
"""예보 현장 보정 D4 — 러너·저장·채택/되돌림·알림·예약 작업 시험 (진짜 sqlite 모델 + 가짜 읽기).

가짜 `Sources` 가 알려진 편차를 심은 L0 예보와 관측을 준다. 판 번호·알림이 '쓰는 보정이 실제로 달라질 때만' 생기는지,
관측을 출처 표시로 거르지 않는지(미러 센서도 쓴다), 시간 제한·끔·항상 켬·마이그레이션을 본다.
"""
import importlib.util
import math
import os
import random
import unittest
from datetime import datetime, timezone
from unittest import mock

from flask import Flask

from aot.aot_flask.extensions import db
from aot.databases.models import FcCalEvent, FcCalibration, FcCalibrationSite
from aot.utils.fc_cal import common as C
from aot.utils.fc_cal import job, runner, store
from aot.utils.fc_cal.sources import classify_obs, standardize

T0 = datetime(2026, 9, 1, tzinfo=timezone.utc).timestamp()
DAY = 86400.0
SITE = 'site-1'


def truth_temp(t):
    return 18.0 + 7.0 * math.sin(((t % DAY) / 3600.0 - 9.0) / 24.0 * 2 * math.pi)


class FakeSources:
    """알려진 편차를 심은 합성 예보·관측. `bias(t)` 가 예보 기온의 편차(°C)."""
    LEADS = (1, 8, 15, 30)

    def __init__(self, bias, end, hourly_input='fc-h', daily_input=None, obs_vars=('T',), seed=1, mirror=True):
        self.bias, self.end = bias, end
        self.rng = random.Random(seed)
        self.info = {'site_id': SITE, 'name': '시험 대지', 'tz': 'UTC', 'lat': 35.8, 'lon': 127.1,
                     'hourly_input': hourly_input, 'daily_input': daily_input, 'obs_source': 'bound',
                     'obs': {k: {'key': k, 'device_id': 'wx-1', 'channel': i, 'unit': 'C', 'measure': 'temperature',
                                 'std_unit': 'C', 'name': 'x', 'driver': 'MQTT_PAHO_JSON' if mirror else None}
                             for i, k in enumerate(obs_vars)}}
        self._fc = None

    def sites(self):
        return [SITE]

    def has_forecast(self, site_id):
        return bool(self.info['hourly_input'])

    def site_tz(self, site_id):
        return 'UTC'

    def site_info(self, site_id):
        return self.info

    def fc_hourly(self, input_id, var, t0, t1):
        if var != 'T':
            return []
        if self._fc is None:
            rows = []
            start = int(T0 // 3600) * 3600
            for ts in range(start, int(self.end) + 1, 3600):
                for lead in self.LEADS:
                    rows.append((float(ts), lead, truth_temp(ts) + self.bias(ts) + self.rng.gauss(0, 1.0)))
            self._fc = rows
        return [r for r in self._fc if t0 <= r[0] <= t1]

    def fc_daily(self, input_id, var, t0, t1):
        return []

    def obs_hourly(self, spec, t0, t1, fn='mean'):
        return {float(e): truth_temp(e - 1800.0) for e in range(int(T0), int(min(t1, self.end + 7200)) + 1, 3600)
                if t0 <= e <= t1}


def _app():
    app = Flask(__name__)
    app.config.update(SQLALCHEMY_DATABASE_URI='sqlite://', SQLALCHEMY_TRACK_MODIFICATIONS=False)
    db.init_app(app)
    return app


class RunnerBase(unittest.TestCase):
    def setUp(self):
        self.app = _app()
        self.ctx = self.app.app_context()
        self.ctx.push()
        db.create_all()
        self.scores = []
        self.mails = mock.patch.object(store, '_email_admins', return_value=1).start()
        self.addCleanup(mock.patch.stopall)

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.ctx.pop()

    def run_at(self, io, day, **kw):
        now = T0 + day * DAY
        io.end = now
        return runner.calibrate_site(SITE, io, now=now, writer=lambda pts: self.scores.extend(pts) or len(pts), **kw)


class AdoptRevert(RunnerBase):
    def test_biased_temperature_is_adopted_with_one_rev_and_events(self):
        io = FakeSources(lambda t: 2.0, T0 + 40 * DAY)
        s = self.run_at(io, 40)
        self.assertEqual(s['rev'], 1)
        used = {(i['var'], i['band']): i['status'] for i in s['items'] if i['status'] == C.ST_ADOPTED}
        self.assertEqual(sorted(used), [('T', '0-6'), ('T', '12-24'), ('T', '24-48'), ('T', '6-12')])
        self.assertEqual(len(s['events']), 4)
        self.assertEqual(FcCalEvent.query.filter_by(event='adopted').count(), 4)
        self.assertEqual(self.mails.call_count, 4)
        row = FcCalibrationSite.query.filter_by(site_id=SITE).one()
        self.assertEqual((row.active_rev, row.last_run_at), (1, T0 + 40 * DAY))
        self.assertEqual(FcCalibration.query.filter_by(rev=1).count(), len(C.BANDS_H) * 5 + len(C.BANDS_D) * 3)
        # 관측이 없는 변수·예보가 없는 일별은 원본
        by = {(i['kind'], i['var']): i['status'] for i in s['items']}
        self.assertEqual(by[('h', 'RH')], C.ST_NO_OBS)
        self.assertEqual(by[('d', 'TMAX')], C.ST_NO_FC)

    def test_mirror_driver_observation_is_used_not_filtered(self):
        io = FakeSources(lambda t: 2.0, T0 + 40 * DAY, mirror=True)
        s = self.run_at(io, 40)
        self.assertTrue(any(i['status'] == C.ST_ADOPTED for i in s['items']))

    def test_unchanged_next_night_writes_no_new_rev_or_event(self):
        io = FakeSources(lambda t: 2.0, T0 + 41 * DAY)
        self.run_at(io, 40)
        s2 = self.run_at(io, 41)
        self.assertEqual((s2['rev'], s2['events']), (1, []))
        self.assertEqual(FcCalibration.query.filter_by(rev=2).count(), 0)
        self.assertEqual(FcCalEvent.query.count(), 4)
        self.assertEqual(FcCalibrationSite.query.one().last_run_at, T0 + 41 * DAY)

    def test_recent_worse_reverts_with_event_and_new_rev(self):
        bias = {'v': lambda t: 2.0}
        io = FakeSources(lambda t: bias['v'](t), T0 + 60 * DAY)
        self.run_at(io, 40)
        flip = T0 + 41 * DAY
        bias['v'] = lambda t: 2.0 if t < flip else 0.0          # 41일째부터 예보 편차가 사라진다(모델 개선) — 옛 계수가 오히려 해가 된다
        io._fc = None
        s = self.run_at(io, 58)
        self.assertEqual(s['rev'], 2)
        self.assertTrue(all(st == C.ST_REVERTED for (_k, v, _b), st in
                            {(i['kind'], i['var'], i['band']): i['status'] for i in s['items']}.items() if v == 'T'))
        self.assertEqual(FcCalEvent.query.filter_by(event='reverted').count(), 4)
        e = FcCalEvent.query.filter_by(event='reverted').first()
        self.assertEqual(e.detail_dict()['reason'], 'recent_worse')
        rows = store.entries_of_rev(SITE, 2)
        self.assertIn('reverted_at', rows[('h', 'T', '0-6')]['meta'])
        self.assertEqual(self.mails.call_count, 8)

    def test_dry_run_writes_nothing(self):
        io = FakeSources(lambda t: 2.0, T0 + 40 * DAY)
        s = self.run_at(io, 40, dry=True)
        self.assertTrue(s['dry'])
        self.assertEqual(len(s['events']), 4)                        # 무엇이 바뀔지는 보여 준다
        self.assertEqual((FcCalibration.query.count(), FcCalEvent.query.count(), FcCalibrationSite.query.count()),
                         (0, 0, 0))
        self.assertEqual((self.scores, self.mails.call_count), ([], 0))

    def test_unbiased_forecast_is_not_adopted_and_writes_no_rev(self):
        io = FakeSources(lambda t: 0.0, T0 + 40 * DAY, seed=9)
        s = self.run_at(io, 40)
        self.assertEqual((s['rev'], s['events']), (0, []))
        self.assertTrue(all(i['status'] != C.ST_ADOPTED for i in s['items']))
        self.assertEqual(FcCalibration.query.count(), 0)

    def test_short_history_few_samples(self):
        io = FakeSources(lambda t: 2.0, T0 + 9 * DAY)
        s = self.run_at(io, 9)
        t = [i for i in s['items'] if i['var'] == 'T' and i['kind'] == 'h']
        self.assertTrue(all(i['status'] == C.ST_FEW for i in t))


class Modes(RunnerBase):
    def test_off_reverts_used_and_skips(self):
        io = FakeSources(lambda t: 2.0, T0 + 40 * DAY)
        self.run_at(io, 40)
        store.set_site_mode(SITE, 'off')
        s = self.run_at(io, 41)
        self.assertEqual(s['mode'], 'off')
        self.assertTrue(all(i['status'] == C.ST_OFF for i in s['items']))
        self.assertEqual(s['rev'], 2)
        self.assertEqual(FcCalEvent.query.filter_by(event='reverted').count(), 4)

    def test_on_forces_even_when_not_better(self):
        io = FakeSources(lambda t: 0.0, T0 + 40 * DAY, seed=9)
        store.set_site_mode(SITE, 'on')
        s = self.run_at(io, 40)
        self.assertTrue(any(i['status'] == C.ST_FORCED and i['var'] == 'T' for i in s['items']))
        self.assertEqual(s['rev'], 1)

    def test_bad_mode_rejected(self):
        with self.assertRaises(ValueError):
            store.set_site_mode(SITE, 'sometimes')


class TimeBudget(RunnerBase):
    def test_timeout_defers_and_keeps_previous_state(self):
        io = FakeSources(lambda t: 2.0, T0 + 40 * DAY)
        self.run_at(io, 40)
        s = self.run_at(io, 41, params=C.Params(time_budget_s=0.0))
        self.assertIn('h/T', s['timed_out'])
        self.assertEqual(s['rev'], 1)                           # 이전 상태 유지 → 새 판 없음
        self.assertEqual(store.site_row(SITE).active_rev, 1)
        meta = store.entries_of_rev(SITE, 1)[('h', 'T', '0-6')]
        self.assertEqual(meta['status'], C.ST_ADOPTED)


class ScoresAndText(RunnerBase):
    def test_score_points_shape(self):
        io = FakeSources(lambda t: 2.0, T0 + 40 * DAY)
        self.run_at(io, 40)
        pts = [p for p in self.scores if p.tags['var'] == 'T' and p.tags['lead_band'] == '0-6']
        self.assertTrue(pts)
        self.assertTrue(all(p.measurement == 'fc_cal_score' and p.device_id == SITE for p in pts))
        self.assertEqual({p.tags['cal_rev'] for p in pts}, {'1'})
        by = {C.SCORE_CHANNELS[p.channel]: p.value for p in pts}
        self.assertGreater(by['n'], 100)
        self.assertLess(by['mae_cal'], by['mae_raw'])
        self.assertEqual(by['status'], float(C.STATUS_CODE[C.ST_ADOPTED]))

    def test_event_text_has_representativeness_note(self):
        io = FakeSources(lambda t: 2.0, T0 + 40 * DAY)
        self.run_at(io, 40)
        ev = FcCalEvent.query.first()
        subject, body = store.event_text('시험 대지', {'event': ev.event, 'kind': ev.kind, 'var': ev.var,
                                                       'band': ev.band, 'rev': ev.rev, 'detail': ev.detail_dict()})
        self.assertIn('채택', subject)
        self.assertIn('대표성', body)
        self.assertIn('보정 판: 1', body)


class ObsClassification(unittest.TestCase):
    def test_classify_and_standardize(self):
        self.assertEqual(classify_obs('temperature', 'C', '기온'), 'T')
        self.assertIsNone(classify_obs('temperature', 'C', '토양 온도'))
        self.assertIsNone(classify_obs('temperature', 'C', '기온', medium='soil'))
        self.assertEqual(classify_obs('humidity', 'percent', '습도'), 'RH')
        self.assertIsNone(classify_obs('humidity', 'percent', '토양 습도'))
        self.assertEqual(classify_obs('radiation', 'W_m2', '일사'), 'SOL')
        self.assertEqual(classify_obs('speed', 'm_s', '풍속'), 'WS')
        self.assertEqual(classify_obs('precipitation', 'mm_h', '강우'), 'RAIN')
        self.assertIsNone(classify_obs('light', 'lux', '조도'))
        self.assertAlmostEqual(standardize('T', 50.0, 'F'), 10.0)
        self.assertEqual(standardize('SOL', 2.0, 'kW_m2'), 2000.0)
        self.assertEqual(standardize('RH', 55.0, 'percent'), 55.0)
        self.assertIsNone(standardize('RAIN', 1.0, 'mm'))           # 누적 간격을 모르면 쓰지 않는다


class JobSchedule(RunnerBase):
    def setUp(self):
        super().setUp()
        mock.patch.object(job, 'is_low_profile', return_value=False).start()     # 개발 기본 프로필(LOW)과 무관하게
        mock.patch.object(store, 'write_scores', return_value=0).start()

    def test_site_due_rules(self):
        noon = T0 + 40 * DAY + 12 * 3600
        pre_dawn = T0 + 40 * DAY + 1 * 3600
        self.assertFalse(job.site_due(pre_dawn, 'UTC', None))
        self.assertTrue(job.site_due(noon, 'UTC', None))
        self.assertFalse(job.site_due(noon, 'UTC', noon - 3600))                  # 오늘 이미 했다
        self.assertTrue(job.site_due(noon, 'UTC', noon - DAY))
        self.assertFalse(job.site_due(noon, 'UTC', noon - DAY, low=True))         # 저사양은 이틀에 한 번
        self.assertTrue(job.site_due(noon, 'UTC', noon - 2 * DAY, low=True))
        # 대지 현지 시각: 서울 03시 = UTC 18시(전날)
        self.assertTrue(job.site_due(T0 + 40 * DAY - 6 * 3600 + 0, 'Asia/Seoul', None))

    def test_profile_params(self):
        self.assertTrue(job.params_for_profile(True).reduced_mode)
        self.assertFalse(job.params_for_profile(False).reduced_mode)

    def test_run_due_runs_due_site_once_and_skips_when_busy(self):
        now = T0 + 40 * DAY + 5 * 3600
        io = FakeSources(lambda t: 2.0, now)
        with mock.patch.object(job, 'busy', return_value=True):
            self.assertEqual(job.run_due(io=io, now=now, sleep_between=0), [])
        with mock.patch.object(job, 'busy', return_value=False), \
                mock.patch.object(runner, 'calibrate_site', wraps=runner.calibrate_site):
            out = job.run_due(io=io, now=now, sleep_between=0)
            self.assertEqual([s['site'] for s in out], [SITE])
            self.assertEqual(job.run_due(io=io, now=now + 60, sleep_between=0), [])      # 오늘 이미 했다

    def test_run_in_thread_uses_app_context_and_lower_priority(self):
        seen = {}

        def fake_run_due(**kw):
            from flask import current_app
            seen['app'] = current_app._get_current_object()
            seen['kw'] = kw
            return []
        with mock.patch.object(job, 'run_due', side_effect=fake_run_due), \
                mock.patch.object(job, 'lower_priority', return_value=True) as lp:
            t = job.run_in_thread(self.app, force=True)
            t.join(10)
        self.assertIs(seen['app'], self.app)
        self.assertEqual(seen['kw'], {'force': True})
        lp.assert_called_once()

    def test_env_switch_disables(self):
        with mock.patch.dict(os.environ, {'AOT_FC_CAL': '0'}):
            self.assertFalse(job.enabled())
            self.assertEqual(job.run_due(io=FakeSources(lambda t: 0, T0)), [])

    def test_off_site_with_used_calibration_is_run_once_to_revert(self):
        now = T0 + 40 * DAY + 5 * 3600
        io = FakeSources(lambda t: 2.0, now)
        with mock.patch.object(job, 'busy', return_value=False):
            job.run_due(io=io, now=now, sleep_between=0)
            self.assertTrue(store.has_used(SITE))
            store.set_site_mode(SITE, 'off')
            out = job.run_due(io=io, now=now + DAY, sleep_between=0)
        self.assertEqual(len(out), 1)
        self.assertFalse(store.has_used(SITE))
        self.assertEqual(FcCalEvent.query.filter_by(event='reverted').count(), 4)

    def test_failed_site_is_marked_so_it_does_not_retry_every_hour(self):
        now = T0 + 40 * DAY + 5 * 3600
        io = FakeSources(lambda t: 2.0, now)
        with mock.patch.object(job, 'busy', return_value=False), \
                mock.patch.object(runner, 'calibrate_site', side_effect=RuntimeError('boom')):
            self.assertEqual(job.run_due(io=io, now=now, sleep_between=0), [])
        self.assertEqual(store.site_row(SITE).last_run_at, now)
        with mock.patch.object(job, 'busy', return_value=False):
            self.assertEqual(job.run_due(io=io, now=now + 3600, sleep_between=0), [])

    def test_off_site_is_skipped(self):
        now = T0 + 40 * DAY + 5 * 3600
        store.set_site_mode(SITE, 'off')
        with mock.patch.object(job, 'busy', return_value=False):
            self.assertEqual(job.run_due(io=FakeSources(lambda t: 2.0, now), now=now, sleep_between=0), [])


def _load_migration():
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'alembic_db', 'alembic', 'versions',
                        'p6_98_fc_calibration_20261026.py')
    spec = importlib.util.spec_from_file_location('p6_98', path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class Migration(unittest.TestCase):
    def test_chain_and_idempotent(self):
        import sqlalchemy as sa
        from alembic.operations import Operations
        from alembic.runtime.migration import MigrationContext
        mod = _load_migration()
        self.assertEqual((mod.revision, mod.down_revision), ('p6_98_fc_calibration_20261026',
                                                             'p6_97_data_layers_20261025'))
        engine = sa.create_engine('sqlite://')

        def run(fn):
            with engine.begin() as conn:
                with Operations.context(MigrationContext.configure(conn)):
                    getattr(mod, fn)()
        run('upgrade')
        run('upgrade')
        names = set(sa.inspect(engine).get_table_names())
        self.assertTrue({'fc_calibration_site', 'fc_calibration', 'fc_cal_event'} <= names)
        run('downgrade')
        run('downgrade')
        self.assertFalse({'fc_calibration_site', 'fc_calibration', 'fc_cal_event'} & set(sa.inspect(engine).get_table_names()))


if __name__ == '__main__':
    unittest.main()
