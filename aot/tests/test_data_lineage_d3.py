# coding=utf-8
"""예보·트윈 데이터 관리 D3 — 계보 머리말 · 예보 계열의 L0 읽기.

지키는 계약
1. 머리말 채널 번호는 문서(digital-twin.md §6.3·§10.4)와 같고 겹치지 않는다. 시설 12~14, 노지 27~29·33~37.
2. 관측 출처 코드: 1 실측 2 미러 3 가상 0 미확인, 섞이면 가장 못 믿을 것. 관측이 없으면 칸이 없다.
3. 예보 계열은 L0(Influx)를 먼저 읽고, 없거나 낡거나 듬성하면 지금 길(파일·채널)로 물러난다. L0 읽기가 터져도 예외가
   밖으로 나가지 않는다.
4. `read()` 는 보정 전에는 `calibrated=false`, `cal_rev=0` 이고 `data_layer` 로 어디서 읽었는지 밝힌다.
Influx 는 없다 — fc_store 의 읽기를 대역으로 잡는다.
"""
import unittest
from unittest import mock

from aot.aot_flask.geo import forecast_series as fs
from aot.twin import lineage as LG, output as O
from aot.twin.types import ForecastSeries, Provenance, SeriesRef

H = 3600.0
T0 = 1_800_000_000.0 - (1_800_000_000.0 % H)


def _ref(p):
    return SeriesRef('u', 'percent', 0, p)


class TestChannels(unittest.TestCase):
    def test_lineage_channels_match_the_contract(self):
        self.assertEqual({k: O.FACILITY_META[k] for k in ('fc_issue_epoch', 'fc_cal_rev', 'obs_origin')},
                         {'fc_issue_epoch': 12, 'fc_cal_rev': 13, 'obs_origin': 14})
        self.assertEqual({k: O.FIELD_META[k] for k in ('fc_issue_epoch', 'fc_cal_rev', 'obs_origin')},
                         {'fc_issue_epoch': 27, 'fc_cal_rev': 28, 'obs_origin': 29})
        self.assertEqual([O.FIELD_META[k] for k in ('theta_fc', 'theta_wp', 'theta_thr', 'obs_a', 'obs_b')],
                         [33, 34, 35, 36, 37])

    def test_channel_numbers_are_unique_per_table(self):
        for table in (O.FACILITY_META, O.FIELD_META):
            self.assertEqual(len(set(table.values())), len(table))


class TestObsOrigin(unittest.TestCase):
    def test_codes(self):
        f = LG.obs_origin
        self.assertEqual(f([_ref(Provenance.MEASURED)]), 1.0)
        self.assertEqual(f([_ref(Provenance.MIRROR)]), 2.0)
        self.assertEqual(f([_ref(Provenance.VIRTUAL)]), 3.0)
        self.assertEqual(f([_ref(Provenance.UNKNOWN)]), 0.0)

    def test_mixed_follows_the_least_trustworthy(self):
        f = LG.obs_origin
        self.assertEqual(f([_ref(Provenance.MEASURED), _ref(Provenance.MIRROR)]), 2.0)
        self.assertEqual(f([_ref(Provenance.MEASURED), _ref(Provenance.VIRTUAL), _ref(Provenance.MIRROR)]), 3.0)
        self.assertEqual(f([_ref(Provenance.MEASURED), _ref(Provenance.UNKNOWN)]), 0.0)

    def test_no_observation_means_no_value(self):
        self.assertIsNone(LG.obs_origin([]))
        self.assertIsNone(LG.obs_origin([None, None]))
        self.assertEqual(LG.obs_origin([None, _ref(Provenance.MEASURED)]), 1.0)

    def test_forecast_meta(self):
        self.assertEqual(LG.forecast_meta(T0, 0), {'fc_issue_epoch': T0, 'fc_cal_rev': 0.0})
        self.assertEqual(LG.forecast_meta(T0, 3)['fc_cal_rev'], 3.0)
        self.assertEqual(LG.forecast_meta(None), {})

    def test_meta_points_are_written_only_when_present(self):
        meta = {'status': 0, 'fc_issue_epoch': T0, 'fc_cal_rev': 0.0, 'theta_fc': 31.5}
        pts = O._meta_points(O.M_FLD_META, 'd', {}, T0, meta, O.FIELD_META)
        self.assertEqual({p.channel: p.value for p in pts}, {0: 0.0, 27: T0, 28: 0.0, 33: 31.5})


class TestForecastSeriesParsing(unittest.TestCase):
    def test_lineage_fields_round_trip(self):
        got = ForecastSeries.from_response({'available': True, 'rows': [{'time': T0, 'end': T0 + H, 'temp_c': 1.0}],
                                            'fetched_at': T0 + 10, 'issued_epoch': T0, 'calibrated': True,
                                            'cal_rev': 4})
        self.assertEqual((got.issued_epoch, got.calibrated, got.cal_rev), (T0, True, 4))

    def test_older_server_without_the_fields_is_raw(self):
        got = ForecastSeries.from_response({'available': True, 'rows': [{'time': T0, 'end': T0 + H}]})
        self.assertEqual((got.issued_epoch, got.calibrated, got.cal_rev), (None, False, 0))


def _issue(base=T0, hours=49, fetched=None, drop=()):
    series = {v: {base + k * H: float(k) for k in range(hours) if k not in drop}
              for v in ('T', 'RH', 'WS', 'WD', 'RAIN', 'SOL', 'CLD', 'POP')}
    return {'fetched': fetched if fetched is not None else base + 600.0, 'base': base, 'series': series,
            'meta': {'grid_latitude': 35.8, 'grid_longitude': 127.1, 'elevation': 12.0}}


class TestL0Hourly(unittest.TestCase):
    def _hourly(self, got, now=T0 + 1200):
        with mock.patch('aot.utils.fc_store.latest_hourly_issue', return_value=got):
            return fs._l0_hourly('in-1', now)

    def test_issue_becomes_file_shaped_rows(self):
        out = self._hourly(_issue())
        self.assertEqual(out['layer'], 'L0')
        self.assertEqual((out['issued_epoch'], out['fetched_epoch']), (T0, T0 + 600.0))
        ep, row = out['rows'][3]
        self.assertEqual(ep, T0 + 3 * H)
        self.assertEqual((row['TMP'], row['REH'], row['RN1'], row['epoch']), (3.0, 3.0, 3.0, T0 + 3 * H))
        self.assertEqual(len(out['rows']), 49)
        self.assertEqual(out['meta']['elevation'], 12.0)

    def test_thin_issue_falls_back_to_the_file_copy(self):
        # 저사양 thin 은 3시간 간격 — 칸을 못 닫으니 L0 로 읽지 않는다
        self.assertIsNone(self._hourly(_issue(drop=range(25, 48, 1))))

    def test_missing_or_old_issue_falls_back(self):
        self.assertIsNone(self._hourly(None))
        self.assertIsNone(self._hourly(_issue(fetched=T0 + 600), now=T0 + 600 + fs.L0_HOURLY_MAX_AGE_S + 5))
        self.assertIsNone(self._hourly(_issue(fetched=T0 + 5000), now=T0))         # 시계가 앞선 값


class TestLoadOrder(unittest.TestCase):
    def setUp(self):
        fs.clear_cache()
        self.addCleanup(fs.clear_cache)

    def _load(self, l0, enabled=True):
        patches = [mock.patch.object(fs, 'designated_ids', return_value=['in-1']),
                   mock.patch.object(fs, 'split_kinds', return_value=(['in-1'], [])),
                   mock.patch.object(fs, '_input_name', return_value='OM hourly'),
                   mock.patch.object(fs, '_l0_enabled', return_value=enabled),
                   mock.patch.object(fs, '_l0_hourly', **({'side_effect': l0} if isinstance(l0, Exception)
                                                          else {'return_value': l0}))]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        return fs._load('site-1', T0)

    def test_l0_wins_when_it_has_a_fresh_issue(self):
        series, reason = self._load({'rows': [(T0, {'epoch': T0, 'TMP': 1.0})], 'layer': 'L0',
                                     'fetched_epoch': T0, 'issued_epoch': T0, 'meta': {}})
        self.assertIsNone(reason)
        self.assertEqual((series['layer'], series['input_id'], series['model']), ('L0', 'in-1', 'open_meteo'))

    def test_a_crashing_l0_never_escapes_and_the_file_path_is_tried(self):
        with mock.patch('aot.inputs.open_meteo_hourly_forecast.forecast_file_path', side_effect=ValueError('bad id')):
            series, reason = self._load(RuntimeError('influx down'))
        self.assertIsNone(series)
        self.assertEqual(reason, 'stale_or_missing')                  # 지정은 있는데 읽을 게 없다

    def test_switched_off_never_asks_l0(self):
        with mock.patch('aot.inputs.open_meteo_hourly_forecast.forecast_file_path', side_effect=ValueError('x')):
            series, _r = self._load({'rows': [(T0, {})]}, enabled=False)
        self.assertIsNone(series)


class TestL0Daily(unittest.TestCase):
    def test_latest_issue_per_target_day_and_units(self):
        tz = 9 * 3600
        now = 1_800_000_000.0
        today = int((now + tz) // 86400)
        got = {'fetched': now - 600, 'days': {today: {'RAIN': -0.2, 'TMAX': 20.0, 'ET0': 2.0},
                                               today + 1: {'RAIN': 4.0, 'POP': 70.0},
                                               today - 1: {'RAIN': 9.0}}}
        with mock.patch.object(fs, 'designated_ids', return_value=['d-1']), \
                mock.patch.object(fs, 'split_kinds', return_value=([], [('d-1', 'DRV')])), \
                mock.patch.object(fs, '_l0_enabled', return_value=True), \
                mock.patch.object(fs, '_input_name', return_value='OM daily'), \
                mock.patch.object(fs, '_tz_offset_s', return_value=tz), \
                mock.patch('aot.utils.inputs.daily_forecast_drivers', return_value={}), \
                mock.patch('aot.utils.fc_store.latest_daily_days', return_value=got) as q:
            out = fs._load_daily('site-1', now, 'Asia/Seoul')
        self.assertEqual(q.call_args[0][3], today * 86400.0)          # 오늘(현지) 자정 이후만 묻는다
        self.assertEqual(out['layer'], 'L0')
        self.assertEqual(out['days'][today], {'precip_mm': 0.0, 'temp_max_c': 20.0, 'et0_mm': 2.0})   # 음수 비는 0
        self.assertEqual(out['days'][today + 1], {'precip_mm': 4.0, 'pop_pct': 70.0})
        self.assertNotIn(today - 1, out['days'])                       # 지난 날은 뺀다
        self.assertEqual(out['fetched_epoch'], now - 600)


class TestReadLineage(unittest.TestCase):
    def _read(self, **kw):
        series = {'rows': [(T0 + k * H, {'epoch': T0 + k * H, 'TMP': 10.0 + k}) for k in range(5)],
                  'input_id': 'in-1', 'source': 'OM', 'model': 'open_meteo', 'layer': 'L0',
                  'fetched_epoch': T0 + 600.0, 'issued_epoch': T0, 'meta': {}}
        fs.clear_cache()
        with mock.patch.object(fs, 'designated_ids', return_value=['in-1']), \
                mock.patch.object(fs, '_load', return_value=(series, None)), \
                mock.patch.object(fs, '_load_daily', return_value=None), \
                mock.patch.object(fs, '_site_tz_name', return_value='UTC'):
            out = fs.read('site-1', now=T0, **kw)
        fs.clear_cache()
        return out

    def test_uncalibrated_lineage_is_reported(self):
        out = self._read()
        self.assertEqual((out['calibrated'], out['cal_rev'], out['layer']), (False, 0, 'auto'))
        self.assertEqual(out['issued_epoch'], T0)
        self.assertEqual(out['data_layer']['hourly'], 'L0')
        self.assertEqual(out['fetched_at'], T0 + 600.0)

    def test_layer_argument(self):
        for name in ('raw', 'corrected'):
            self.assertEqual(self._read(layer=name)['layer'], name)
        with self.assertRaises(ValueError):
            self._read(layer='nope')


if __name__ == '__main__':
    unittest.main()
