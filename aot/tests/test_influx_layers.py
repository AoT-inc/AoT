# coding=utf-8
"""데이터 계층 버킷 해석기 (예보·트윈 데이터 관리 D1).

지키는 계약:
1. 측정 이름 → 계층 → 버킷 이름 규칙이 설계(§2)와 같다. 모르는 이름은 센서 측정(`aot_db`)이다.
2. 하위 호환: v1·끔·버킷 준비 실패면 **모든 계층이 `aot_db` 한 곳**이고, 읽기도 그 한 곳이다.
3. 계층 모드: 쓰기는 계층 버킷, 읽기는 `[계층, aot_db]` 이고 같은 시각이면 앞 버킷이 이긴다.
4. 계층 버킷 쓰기가 실패해도 점은 사라지지 않고 `aot_db` 로 돌려 쓴다.
5. 버킷 생성은 멱등이고 보존을 초 단위로 건다. 보존 일수는 범위 안으로 묶는다.

Influx 는 이 테스트에 없다 — 클라이언트를 대역으로 잡고 어느 버킷에 무엇을 보냈는지를 본다.
"""
import unittest
from unittest import mock

from aot.utils import influx as I
from aot.utils import influx_layers as L


class _Rec:
    def __init__(self, t, v, **values):
        self._t, self._v, self.values = t, v, values

    def get_time(self):
        import datetime
        return datetime.datetime.fromtimestamp(self._t, datetime.timezone.utc)

    def get_value(self):
        return self._v


class _Table:
    def __init__(self, records):
        self.records = records


class _FakeClient:
    """버킷별로 준비한 응답을 돌려주고, 쓰기를 버킷별로 모은다."""

    def __init__(self, data=None, fail_write=()):
        self.data = data or {}
        self.writes = {}
        self.fail_write = set(fail_write)
        self.queries = []

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def close(self):
        pass

    def query_api(self):
        outer = self

        class Q:
            def query(self, q):
                bucket = q.split('from(bucket: "', 1)[1].split('"', 1)[0]
                outer.queries.append(bucket)
                return [_Table(outer.data.get(bucket, []))]
        return Q()

    def write_api(self, write_options=None):
        outer = self

        class W:
            def write(self, bucket, record, write_precision=None):
                if bucket in outer.fail_write:
                    raise RuntimeError('bucket gone')
                outer.writes.setdefault(bucket, []).extend(record)
        return W()


LAYERED = L.Layout('layered', {'obs': 'aot_db', 'fc': 'aot_fc', 'calc': 'aot_calc', 'hist': 'aot_hist'},
                   'aot_db', '')
LEGACY = L._legacy_layout('aot_db', '시험')


def _with_layout(lay):
    return mock.patch.object(L, 'layout', return_value=lay)


class TestNaming(unittest.TestCase):
    def test_measurements_map_to_design_layers(self):
        m = L.layer_of_measurement
        for name in ('fc_hourly', 'fc_daily', 'fc_hourly_meta', 'fc_daily_meta'):
            self.assertEqual(m(name), 'fc', name)
        for name in ('env_twin', 'env_twin_field', 'env_twin_field_h', 'env_twin_scn',
                     'env_twin_scn_field', 'env_twin_act', 'fc_hourly_cal', 'fc_daily_cal'):
            self.assertEqual(m(name), 'calc', name)
        for name in ('env_twin_lead', 'env_twin_meta', 'env_twin_field_lead', 'env_twin_field_meta',
                     'env_twin_post', 'env_twin_field_post', 'env_twin_field_post_h', 'fc_cal_score'):
            self.assertEqual(m(name), 'hist', name)

    def test_sensor_units_stay_in_the_observation_bucket(self):
        for name in ('C', 'mm', 'Pa', 'percent', 'duration_time', 'unknown_thing'):
            self.assertEqual(L.layer_of_measurement(name), 'obs')

    def test_bucket_names(self):
        self.assertEqual(L.bucket_name('aot_db', 'fc'), 'aot_fc')
        self.assertEqual(L.bucket_name('aot_db', 'obs'), 'aot_db')
        self.assertEqual(L.bucket_name('farm', 'hist'), 'farm_hist')


class TestRetention(unittest.TestCase):
    def test_defaults_match_design(self):
        self.assertEqual(L.desired_retention_days({}), {'fc': 730, 'calc': 60, 'hist': 730})

    def test_saved_values_are_clamped_and_garbage_falls_back(self):
        got = L.desired_retention_days({'retention_days': {'fc': 1, 'calc': 99999, 'hist': 'x'}})
        self.assertEqual(got, {'fc': 30, 'calc': 365, 'hist': 730})

    def test_validate(self):
        self.assertEqual(L.validate_retention('calc', '90'), 90)
        with self.assertRaises(ValueError):
            L.validate_retention('calc', 3)
        with self.assertRaises(ValueError):
            L.validate_retention('obs', 100)       # 센서 관측 보존은 여기서 바꾸지 않는다
        with self.assertRaises(ValueError):
            L.validate_retention('fc', 'abc')


class TestEnsureBuckets(unittest.TestCase):
    def _client(self, existing=()):
        c = mock.MagicMock()
        api = c.buckets_api.return_value
        api.find_bucket_by_name.side_effect = lambda n: object() if n in existing else None
        c.organizations_api.return_value.find_organizations.return_value = [mock.Mock(id='org1')]
        return c, api

    def test_creates_only_missing_with_retention_seconds(self):
        c, api = self._client(existing={'aot_fc'})
        names = L.ensure_buckets(c, 'aot_db', {'fc': 730, 'calc': 60, 'hist': 400})
        self.assertEqual(names, {'obs': 'aot_db', 'fc': 'aot_fc', 'calc': 'aot_calc', 'hist': 'aot_hist'})
        made = {k['bucket_name']: k for _a, k in api.create_bucket.call_args_list}
        self.assertEqual(set(made), {'aot_calc', 'aot_hist'})
        self.assertEqual(made['aot_calc']['retention_rules'][0].every_seconds, 60 * 86400)
        self.assertEqual(made['aot_hist']['retention_rules'][0].every_seconds, 400 * 86400)

    def test_idempotent_when_all_exist(self):
        c, api = self._client(existing={'aot_fc', 'aot_calc', 'aot_hist'})
        L.ensure_buckets(c, 'aot_db', L.DEFAULT_RETENTION_DAYS)
        api.create_bucket.assert_not_called()

    def test_missing_org_is_an_error(self):
        c, _api = self._client()
        c.organizations_api.return_value.find_organizations.return_value = []
        with self.assertRaises(RuntimeError):
            L.ensure_buckets(c, 'aot_db', L.DEFAULT_RETENTION_DAYS)


class TestResolveFallsBackToLegacy(unittest.TestCase):
    def setUp(self):
        L.invalidate()
        self.addCleanup(L.invalidate)

    def _params(self, version='2'):
        return mock.patch('aot.utils.influx._influx_connection_params',
                          return_value=('http://x', 'tok', 'aot_db', version))

    def test_v1_is_legacy(self):
        with self._params('1'), mock.patch.object(L, '_settings_config', return_value={}):
            lay = L.layout(force=True)
        self.assertEqual(lay.mode, 'legacy')
        self.assertEqual(set(lay.buckets.values()), {'aot_db'})
        self.assertIn('v1', lay.reason)

    def test_user_switch_off_is_legacy(self):
        with self._params(), mock.patch.object(L, '_settings_config', return_value={'enabled': False}), \
                mock.patch.object(L, '_client_for_admin', return_value=(mock.MagicMock(), 'aot_db')):
            lay = L.layout(force=True)
        self.assertEqual(lay.mode, 'legacy')

    def test_bucket_creation_failure_is_legacy_not_an_exception(self):
        with self._params(), mock.patch.object(L, '_settings_config', return_value={}), \
                mock.patch.object(L, '_client_for_admin', return_value=(mock.MagicMock(), 'aot_db')), \
                mock.patch.object(L, 'ensure_buckets', side_effect=RuntimeError('no permission')):
            lay = L.layout(force=True)
        self.assertEqual(lay.mode, 'legacy')
        self.assertIn('no permission', lay.reason)

    def test_success_is_layered_and_cached(self):
        names = {'obs': 'aot_db', 'fc': 'aot_fc', 'calc': 'aot_calc', 'hist': 'aot_hist'}
        with self._params(), mock.patch.object(L, '_settings_config', return_value={}), \
                mock.patch.object(L, '_client_for_admin', return_value=(mock.MagicMock(), 'aot_db')), \
                mock.patch.object(L, 'ensure_buckets', return_value=names) as ens:
            a = L.layout(force=True)
            b = L.layout()
        self.assertEqual(a.mode, 'layered')
        self.assertIs(a, b)
        self.assertEqual(ens.call_count, 1)          # 쓰기마다 Influx 에 묻지 않는다


class TestRouting(unittest.TestCase):
    def test_layered_routes_by_measurement(self):
        with _with_layout(LAYERED):
            self.assertEqual(L.write_bucket('C'), 'aot_db')
            self.assertEqual(L.write_bucket('env_twin_field'), 'aot_calc')
            self.assertEqual(L.write_bucket('env_twin_field_meta'), 'aot_hist')
            self.assertEqual(L.write_bucket('fc_hourly'), 'aot_fc')
            self.assertEqual(L.read_buckets('env_twin_field'), ['aot_calc', 'aot_db'])
            self.assertEqual(L.read_buckets('C'), ['aot_db'])

    def test_legacy_is_one_bucket_everywhere(self):
        with _with_layout(LEGACY):
            for m in ('C', 'env_twin', 'fc_hourly', 'env_twin_meta'):
                self.assertEqual(L.write_bucket(m), 'aot_db')
                self.assertEqual(L.read_buckets(m), ['aot_db'])


class _P:
    def __init__(self, measurement, ts=1000.0, value=1.0):
        self.measurement, self.device_id, self.channel = measurement, 'dev', 1
        self.timestamp, self.value, self.tags = ts, value, {}


class TestWritePoints(unittest.TestCase):
    PARAMS = ('http://x', 'tok', 'aot_db', '2')

    def _write(self, points, lay, client):
        with mock.patch.object(I, '_influx_connection_params', return_value=self.PARAMS), \
                mock.patch.object(I, 'InfluxDBClient', return_value=client), \
                _with_layout(lay):
            return I.write_influxdb_points(points)

    def test_points_split_by_layer(self):
        c = _FakeClient()
        n = self._write([_P('env_twin_field'), _P('env_twin_field_meta'), _P('env_twin_field')], LAYERED, c)
        self.assertEqual(n, 3)
        self.assertEqual({k: len(v) for k, v in c.writes.items()}, {'aot_calc': 2, 'aot_hist': 1})

    def test_legacy_writes_everything_to_one_bucket(self):
        c = _FakeClient()
        self._write([_P('env_twin_field'), _P('env_twin_field_meta')], LEGACY, c)
        self.assertEqual({k: len(v) for k, v in c.writes.items()}, {'aot_db': 2})

    def test_layer_bucket_failure_falls_back_without_losing_points(self):
        c = _FakeClient(fail_write={'aot_calc'})
        with mock.patch.object(L, 'invalidate') as inv:
            n = self._write([_P('env_twin_field'), _P('env_twin_field')], LAYERED, c)
        self.assertEqual(n, 2)
        self.assertEqual({k: len(v) for k, v in c.writes.items()}, {'aot_db': 2})
        inv.assert_called()

    def test_legacy_bucket_failure_still_raises(self):
        c = _FakeClient(fail_write={'aot_db'})
        with self.assertRaises(RuntimeError):
            self._write([_P('env_twin_field')], LEGACY, c)

    def test_resolver_crash_does_not_stop_writes(self):
        c = _FakeClient()
        with mock.patch.object(I, '_influx_connection_params', return_value=self.PARAMS), \
                mock.patch.object(I, 'InfluxDBClient', return_value=c), \
                mock.patch.object(L, 'layout', side_effect=RuntimeError('boom')):
            I.write_influxdb_points([_P('env_twin_field')])
        self.assertEqual(list(c.writes), ['aot_db'])


class TestReadMerge(unittest.TestCase):
    PARAMS = ('http://x', 'tok', 'aot_db', '2')

    def test_new_bucket_wins_on_the_same_timestamp(self):
        c = _FakeClient(data={
            'aot_calc': [_Rec(100, 2.0, device_id='d', channel='1'), _Rec(200, 3.0, device_id='d', channel='1')],
            'aot_db': [_Rec(100, 9.0, device_id='d', channel='1'), _Rec(50, 1.0, device_id='d', channel='1')],
        })
        with mock.patch.object(I, '_influx_connection_params', return_value=self.PARAMS), \
                mock.patch.object(I, 'InfluxDBClient', return_value=c), _with_layout(LAYERED):
            rows = I.read_twin_series('d', 'env_twin_field', 1, 0, 300)
        self.assertEqual(rows, [(50.0, 1.0), (100.0, 2.0), (200.0, 3.0)])
        self.assertEqual(c.queries, ['aot_calc', 'aot_db'])

    def test_many_merges_per_series(self):
        c = _FakeClient(data={
            'aot_hist': [_Rec(10, 5.0, device_id='d', channel='4')],
            'aot_db': [_Rec(10, 6.0, device_id='d', channel='4'), _Rec(5, 7.0, device_id='d', channel='4')],
        })
        with mock.patch.object(I, '_influx_connection_params', return_value=self.PARAMS), \
                mock.patch.object(I, 'InfluxDBClient', return_value=c), _with_layout(LAYERED):
            out = I.read_twin_many('env_twin_field_meta', ['d'], [4], 0, 100)
        self.assertEqual(out, {('d', 4): [(5.0, 7.0), (10.0, 5.0)]})

    def test_legacy_reads_only_the_one_bucket(self):
        c = _FakeClient(data={'aot_db': [_Rec(1, 1.0, device_id='d', channel='1')]})
        with mock.patch.object(I, '_influx_connection_params', return_value=self.PARAMS), \
                mock.patch.object(I, 'InfluxDBClient', return_value=c), _with_layout(LEGACY):
            I.read_twin_series('d', 'env_twin_field', 1, 0, 10)
        self.assertEqual(c.queries, ['aot_db'])

    def test_a_broken_new_bucket_is_skipped_but_the_old_one_still_answers(self):
        c = _FakeClient(data={'aot_db': [_Rec(1, 1.0, device_id='d', channel='1')]})
        orig = c.query_api

        def q():
            api = orig()
            real = api.query

            def query(text):
                if 'aot_calc' in text:
                    raise RuntimeError('bucket not found')
                return real(text)
            api.query = query
            return api
        c.query_api = q
        with mock.patch.object(I, '_influx_connection_params', return_value=self.PARAMS), \
                mock.patch.object(I, 'InfluxDBClient', return_value=c), _with_layout(LAYERED):
            rows = I.read_twin_series('d', 'env_twin_field', 1, 0, 10)
        self.assertEqual(rows, [(1.0, 1.0)])


class TestMigration(unittest.TestCase):
    def test_head_and_model_column(self):
        from aot.config import ALEMBIC_VERSION
        from aot.databases.models import Misc
        self.assertEqual(ALEMBIC_VERSION, 'p7_00_target_alias_20261028')
        self.assertIn('data_layers', Misc.__table__.c)
        self.assertTrue(Misc.__table__.c.data_layers.nullable)


if __name__ == '__main__':
    unittest.main()
