# coding=utf-8
"""값 배치 조회 — **빠른 길이 조용히 꺼지지 않게**.

필지 요약과 구획 창은 장치의 채널마다 Influx 를 한 번씩 쳤다. 채널이 곱해져
라즈베리파이 실측에서 왕복 142회 · 12초였고, 그것을 창(max_age)당 한 번으로
접은 것이 `query_last_values_bulk` 다.

이 최적화는 **깨져도 화면이 멀쩡하다** — 값은 그대로 나오고 느려질 뿐이라,
회귀가 성능으로만 드러난다. 그래서 여기서 지키는 것은 값이 아니라 **경로**다.

1. **"쿼리 실패" 와 "돌았는데 값이 없음" 을 가른다.** 둘을 못 가르면 측정이 아직
   하나도 없는 설치에서 전부 miss 로 잡혀 개별 조회로 되돌아간다 — 왕복이 가장
   많은 바로 그 경우에 최적화가 통째로 꺼진다.
2. **사전 조회에 답이 있으면 개별 조회를 하지 않는다.** 되돌아가면 접은 의미가 없다.
3. **사전 조회가 실패하면 값이 사라지지 않는다.** 느려질 뿐이어야 한다.
4. **배치는 장치 수에 비례하지 않는다.** 장치마다 한 번씩 치면 이름만 배치다.

Influx 는 이 테스트에 없다. 값이 아니라 어느 경로로 갔는지가 계약이므로 조회를
대역으로 잡고 호출을 센다.
"""
import unittest

from flask import Flask

from aot.aot_flask.extensions import db
from aot.aot_flask.geo import device_link_status as L
from aot.aot_flask.geo import site_summary as SS
from aot.databases.models import DeviceMeasurements, Input
from aot.utils import influx as I


def _make_app():
    app = Flask(__name__)
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite://'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    db.init_app(app)
    return app


class TestBulkStatusTellsFailureFromEmpty(unittest.TestCase):
    """`ok` 는 "돌았는가" 이지 "찾았는가" 가 아니다."""

    def test_nothing_to_ask_is_not_a_failure(self):
        self.assertEqual(I.query_last_values_bulk_status([]), ({}, True))
        # 반쪽짜리 spec 은 물어볼 수 없다 — 그래도 실패는 아니다.
        self.assertEqual(I.query_last_values_bulk_status([(None, 'dev', 0, None)]),
                         ({}, True))

    def test_no_connection_is_a_failure(self):
        orig = I._influx_connection_params
        I._influx_connection_params = lambda: None
        try:
            vals, ok = I.query_last_values_bulk_status([('C', 'dev', 0, None)])
        finally:
            I._influx_connection_params = orig
        self.assertEqual(vals, {})
        self.assertFalse(ok, '연결이 없는데 "돌았다" 고 답한다')

    def test_a_query_error_is_a_failure(self):
        orig_conn, orig_cli = I._influx_connection_params, I.InfluxDBClient
        I._influx_connection_params = lambda: ('http://x', 't', 'b', 2)

        class _Boom(object):
            def __init__(self, **kw):
                pass

            def __enter__(self):
                raise RuntimeError('influx down')

            def __exit__(self, *a):
                return False

        I.InfluxDBClient = _Boom
        try:
            vals, ok = I.query_last_values_bulk_status([('C', 'dev', 0, None)])
        finally:
            I._influx_connection_params, I.InfluxDBClient = orig_conn, orig_cli
        self.assertEqual(vals, {})
        self.assertFalse(ok)

    def test_ran_and_found_nothing_is_not_a_failure(self):
        """갓 만든 서버가 정확히 이 경우다 — 여기서 False 를 주면 최적화가
        가장 필요한 설치에서 통째로 꺼진다."""
        orig_conn, orig_cli = I._influx_connection_params, I.InfluxDBClient
        I._influx_connection_params = lambda: ('http://x', 't', 'b', 2)

        class _Empty(object):
            def __init__(self, **kw):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def query_api(self):
                return self

            def query(self, q):
                return []

        I.InfluxDBClient = _Empty
        try:
            vals, ok = I.query_last_values_bulk_status([('C', 'dev', 0, None)])
        finally:
            I._influx_connection_params, I.InfluxDBClient = orig_conn, orig_cli
        self.assertEqual(vals, {})
        self.assertTrue(ok, '돌았는데 값이 없는 것을 실패로 읽는다')

    def test_the_key_is_the_same_on_both_sides(self):
        """생산자(쿼리 결과)와 소비자(찾는 쪽)가 같은 키를 만들어야 한다 —
        갈리면 항상 miss 라 개별 조회로 되돌아간다."""
        bulk_key = I.bulk_key
        self.assertEqual(bulk_key('C', 'dev', 0, None),
                         ('C', 'dev', '0', None))
        # 채널 없음은 빈 문자열이다(None 이 아니다) — 결과 파싱 쪽과 같은 규약.
        self.assertEqual(bulk_key('C', 'dev', None, ''),
                         ('C', 'dev', '', None))


class _DbBase(unittest.TestCase):

    def setUp(self):
        self.app = _make_app()
        self.ctx = self.app.app_context()
        self.ctx.push()
        db.create_all()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.ctx.pop()

    def _device(self, uid, channels=2, period=30):
        Input(unique_id=uid, name=uid, period=period).save()
        out = []
        for ch in range(channels):
            m = DeviceMeasurements(device_id=uid, channel=ch,
                                   measurement='temperature', unit='C')
            m.save()
            out.append(m.unique_id)
        return out


class TestPrefetchKeepsTheFastPath(_DbBase):
    """사전 조회의 계약 — **키가 있으면 그것이 답이다.**"""

    def test_a_miss_is_recorded_when_the_query_ran(self):
        """값이 없다는 것도 답이다. 키를 안 남기면 호출부가 개별 조회로
        되돌아가, 값이 하나도 없는 설치에서 왕복이 최대가 된다."""

        mids = self._device('dev-1')
        orig = I.query_last_values_bulk_status
        I.query_last_values_bulk_status = lambda specs, past_sec=600: ({}, True)
        try:
            got = SS.prefetch_last_values(['dev-1'])
        finally:
            I.query_last_values_bulk_status = orig

        for mid in mids:
            self.assertIn(('dev-1', mid), got, '돌았는데 키를 안 남겼다')
            self.assertIsNone(got[('dev-1', mid)])

    def test_a_failed_query_leaves_no_key(self):
        """실패는 답이 아니다 — 키를 남기면 호출부가 "값 없음" 으로 읽어
        멀쩡한 값이 화면에서 사라진다."""

        mids = self._device('dev-2')
        orig = I.query_last_values_bulk_status
        I.query_last_values_bulk_status = lambda specs, past_sec=600: ({}, False)
        try:
            got = SS.prefetch_last_values(['dev-2'])
        finally:
            I.query_last_values_bulk_status = orig

        for mid in mids:
            self.assertNotIn(('dev-2', mid), got)

    def test_one_query_per_window_not_per_channel(self):
        """채널마다 치면 접은 의미가 없다. 주기가 같은 장치는 한 창으로 묶인다."""

        self._device('dev-3', channels=3, period=30)
        self._device('dev-4', channels=3, period=30)
        calls = []
        orig = I.query_last_values_bulk_status
        I.query_last_values_bulk_status = lambda specs, past_sec=600: (
            calls.append((len(specs), past_sec)) or ({}, True))
        try:
            SS.prefetch_last_values(['dev-3', 'dev-4'])
        finally:
            I.query_last_values_bulk_status = orig

        self.assertEqual(len(calls), 1,
                         '창이 같은데 여러 번 쳤다: %s' % (calls,))
        self.assertEqual(calls[0][0], 6, '채널 6개를 한 번에 안 물었다')

    def test_different_windows_are_not_merged(self):
        """창을 가장 긴 것으로 통일하면 하루짜리 장치 하나가 나머지 전부의
        스캔 범위를 하루로 넓힌다."""

        self._device('dev-5', channels=1, period=30)
        self._device('dev-6', channels=1, period=86400)
        seen = []
        orig = I.query_last_values_bulk_status
        I.query_last_values_bulk_status = lambda specs, past_sec=600: (
            seen.append(past_sec) or ({}, True))
        try:
            SS.prefetch_last_values(['dev-5', 'dev-6'])
        finally:
            I.query_last_values_bulk_status = orig

        self.assertEqual(len(seen), 2, '창이 다른데 한 번에 물었다: %s' % (seen,))
        self.assertNotEqual(seen[0], seen[1])


class TestEnvUsesThePrefetch(_DbBase):
    """접어 둔 답이 있으면 **다시 묻지 않는다.**"""

    def test_a_prefetched_key_skips_the_single_read(self):

        mids = self._device('dev-7', channels=2)
        singles = []
        orig = SS._last_value
        SS._last_value = lambda *a, **k: singles.append(a) or None
        try:
            SS.env_for_devices(['dev-7'],
                               prefetched={('dev-7', m): 21.5 for m in mids})
        finally:
            SS._last_value = orig
        self.assertEqual(singles, [], '접어 둔 답이 있는데 다시 물었다')

    def test_a_missing_key_falls_back_so_no_value_disappears(self):
        """사전 조회를 못 한 장치가 섞여도 값이 비면 안 된다 — 느려질 뿐이어야
        한다."""

        mids = self._device('dev-8', channels=2)
        singles = []
        orig = SS._last_value

        def _stub(device_id, measurement_id, *a, **k):
            singles.append(measurement_id)
            return 19.0

        SS._last_value = _stub
        try:
            # 첫 채널만 접어 둔다.
            SS.env_for_devices(['dev-8'], prefetched={('dev-8', mids[0]): 21.5})
        finally:
            SS._last_value = orig
        self.assertEqual(singles, [mids[1]],
                         '되돌아갈 채널만 개별로 물어야 한다: %s' % (singles,))


class TestLinkStatusBatchIsReallyBatched(_DbBase):
    """이름만 배치가 되지 않게 — 장치 수에 비례하면 안 된다."""

    def test_one_bulk_call_for_many_devices(self):

        specs = set()
        for i in range(4):
            uid = 'node-%d' % i
            mids = self._device(uid, channels=1)
            specs.add((uid, mids[0]))

        calls = []
        orig = I.query_last_values_bulk_status
        I.query_last_values_bulk_status = lambda s, past_sec=600: (
            calls.append(len(s)) or ({}, True))
        stale = []
        orig_stale = L._stale_value
        L._stale_value = lambda d, m: stale.append((d, m)) or (None, None, True)
        try:
            out = L._prefetch_channels(specs, 600)
        finally:
            I.query_last_values_bulk_status = orig
            L._stale_value = orig_stale

        self.assertEqual(len(calls), 1, '장치마다 쳤다: %s' % (calls,))
        self.assertEqual(calls[0], 4)
        # 신선한 값이 없는 채널도 **결과에 적는다** — 비워 두면 호출부가
        # `_read_channel` 로 되돌아가 신선 조회부터 다시 한다.
        self.assertEqual(len(out), 4, '못 찾은 채널을 비워 뒀다')
        self.assertEqual(len(stale), 4)

    def test_a_failed_bulk_leaves_the_fallback_open(self):
        """실패는 "값 없음" 이 아니다 — 비워 둬야 호출부가 개별로 읽는다."""

        mids = self._device('node-x', channels=1)
        orig = I.query_last_values_bulk_status
        I.query_last_values_bulk_status = lambda s, past_sec=600: ({}, False)
        try:
            out = L._prefetch_channels({('node-x', mids[0])}, 600)
        finally:
            I.query_last_values_bulk_status = orig
        self.assertEqual(out, {}, '실패인데 답이 있는 척한다')
