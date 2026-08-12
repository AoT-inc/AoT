# coding=utf-8
"""
Tests for the KMA 500m input's backfill freshness gate and observation
timestamping (aot/inputs/kma_weather_500.py).

Background — the bug these lock down:

  `Input.datetime` was written in exactly one place, inside get_new_data()
  (the backfill). The live 5-minute path never touched it, so the column
  recorded "when a backfill last ran", not "how far the stored data reaches".
  Once the gap between two daemon restarts exceeded 7 days, the next restart
  re-downloaded a full week that InfluxDB already held — 7 slow chunked
  requests per input, several of which 504'd, while the ones that succeeded
  wrote a *second* copy of every point (live points landed on the InfluxDB
  write time, backfill points on the KMA observation boundary, so the same
  observation became two distinct series entries).

  Observed on koat 2026-08-12: restarts on 08-04 and 08-12 (8 days apart)
  triggered a 7-day backfill over a window that had 288 points/day already.

All external I/O is mocked. No DB, no InfluxDB, no HTTP.
"""
import datetime
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(
    0,
    os.path.abspath(os.path.join(os.path.dirname(__file__), os.path.pardir, os.path.pardir))
)

os.environ.setdefault("ALEMBIC_RUNNING", "1")

from aot.inputs import kma_weather_500
from aot.inputs.kma_weather_500 import INPUT_INFORMATION, InputModule


def _bare_module(**attrs):
    """An InputModule with __init__ bypassed — no DB, no network, no options."""
    inst = InputModule.__new__(InputModule)
    inst.logger = MagicMock()
    inst.unique_id = 'test-kma-0001'
    inst.input_dev = MagicMock()
    inst.input_dev.longitude = 126.9
    inst.input_dev.latitude = 35.9
    inst.first_run = True
    inst.latest_datetime = None
    inst.is_enabled = lambda ch: True
    inst.api_key = 'SECRETKEY123'
    inst.lon, inst.lat = 126.9, 35.9
    inst.period = 300
    inst._backfill_retry_windows = []
    inst._probe_channel = (0, 'C', 'temperature')
    inst._empty_response_streak = 0
    for key, val in attrs.items():
        setattr(inst, key, val)
    return inst


def _response(text='', raises=None):
    resp = MagicMock()
    resp.text = text
    resp.raise_for_status = MagicMock(side_effect=raises)
    return resp


class TestSameTimestampContract(unittest.TestCase):
    """The live path must not let InfluxDB stamp the write time."""

    def test_declares_per_measurement_timestamps(self):
        # Absent or True, add_measurements_influxdb() discards the per-point
        # timestamp and InfluxDB stamps the write time instead — which is what
        # put live and backfill points on two different grids.
        self.assertIn('measurements_use_same_timestamp', INPUT_INFORMATION)
        self.assertFalse(INPUT_INFORMATION['measurements_use_same_timestamp'])


class TestObservationDatetime(unittest.TestCase):
    """KMA stamps are station-local 'YYYYMMDDHHMM'; storage is naive UTC."""

    def setUp(self):
        self.inst = _bare_module()
        self.tz_patch = patch.object(
            kma_weather_500, 'get_device_tz', return_value=__import__('pytz').timezone('Asia/Seoul'))
        self.tz_patch.start()
        self.addCleanup(self.tz_patch.stop)

    def test_converts_kst_to_naive_utc(self):
        # 2026-08-12 12:00 KST == 2026-08-12 03:00 UTC
        got = self.inst._observation_datetime('202608121200')
        self.assertEqual(got, datetime.datetime(2026, 8, 12, 3, 0))
        self.assertIsNone(got.tzinfo, "must be naive UTC for DB comparison")

    def test_lands_on_the_five_minute_grid(self):
        # The whole point: the live stamp must equal what the backfill would
        # write for the same observation, to the second.
        got = self.inst._observation_datetime('202608121205')
        self.assertEqual(got.second, 0)
        self.assertEqual(got.minute % 5, 0)

    def test_rejects_malformed_stamps(self):
        for bad in (None, '', '2026081212', 'notatimestamp', '20260812120000'):
            self.assertIsNone(self.inst._observation_datetime(bad), repr(bad))

    def test_clamps_future_stamps(self):
        future = datetime.datetime.utcnow() + datetime.timedelta(hours=12)
        # Express that UTC instant as a KST wall-clock string
        stamp = (future + datetime.timedelta(hours=9)).strftime('%Y%m%d%H%M')
        got = self.inst._observation_datetime(stamp)
        self.assertLess(got, datetime.datetime.utcnow())


class TestLatestStoredDatetime(unittest.TestCase):
    """Freshness comes from the measurement store, not a DB column."""

    def test_returns_newest_point_as_naive_utc(self):
        inst = _bare_module()
        epoch = datetime.datetime(2026, 8, 12, 3, 0, tzinfo=datetime.timezone.utc).timestamp()
        with patch.object(kma_weather_500, 'read_influxdb_single',
                          return_value=[epoch, 24.1]) as reader:
            got = inst._latest_stored_datetime(duration_sec=600)
        self.assertEqual(got, datetime.datetime(2026, 8, 12, 3, 0))
        # The window must be passed through — an unbounded last() would scan
        # the entire retention on every daemon start.
        self.assertEqual(reader.call_args.kwargs['duration_sec'], 600)

    def test_falls_through_to_the_next_enabled_channel(self):
        inst = _bare_module()
        inst.is_enabled = lambda ch: ch != 0  # temperature disabled
        with patch.object(kma_weather_500, 'read_influxdb_single',
                          return_value=[1000.0, 55.0]) as reader:
            inst._latest_stored_datetime()
        self.assertEqual(reader.call_args.kwargs['measure'], 'humidity')

    def test_empty_store_returns_none(self):
        inst = _bare_module()
        with patch.object(kma_weather_500, 'read_influxdb_single',
                          return_value=[None, None]):
            self.assertIsNone(inst._latest_stored_datetime())

    def test_query_failure_returns_none_rather_than_raising(self):
        inst = _bare_module()
        with patch.object(kma_weather_500, 'read_influxdb_single',
                          side_effect=RuntimeError("influx down")):
            self.assertIsNone(inst._latest_stored_datetime())


class TestFirstRunGate(unittest.TestCase):
    """The regression itself: a restart must not re-download existing data."""

    WEEK = 7 * 86400

    def _run_gate(self, stored_dt, column_dt):
        """Drive get_measurement() far enough to observe the gate's decision."""
        inst = _bare_module(latest_datetime=column_dt)
        inst.api_key = 'dummy'
        inst.lon, inst.lat = 126.9, 35.9
        inst.period = 300

        def fake_opt(_self, key, default=None):
            return {
                'api_key': 'dummy',
                'period': 300,
                'backfill_request': False,
                'backfill_minutes': 1440,
            }.get(key, default)

        seoul = __import__('pytz').timezone('Asia/Seoul')
        with patch.object(kma_weather_500, '_get_opt', fake_opt), \
             patch.object(kma_weather_500, 'get_device_tz', return_value=seoul), \
             patch.object(InputModule, '_latest_stored_datetime', return_value=stored_dt), \
             patch.object(InputModule, 'get_new_data') as backfill, \
             patch.object(InputModule, 'pre_fetch_data', return_value=None):
            inst.get_measurement()
        return backfill

    def test_skips_when_the_store_is_fresh_even_if_the_column_is_stale(self):
        # koat's exact shape: continuous 5-minute data, but Input.datetime
        # frozen at the last backfill 8 days ago.
        now = datetime.datetime.utcnow()
        backfill = self._run_gate(
            stored_dt=now - datetime.timedelta(minutes=5),
            column_dt=now - datetime.timedelta(days=8))
        backfill.assert_not_called()

    def test_backfills_when_the_store_is_empty_and_no_column(self):
        backfill = self._run_gate(stored_dt=None, column_dt=None)
        backfill.assert_called_once()
        minutes = backfill.call_args.args[0]
        self.assertEqual(minutes, self.WEEK // 60)

    def test_backfills_only_the_gap_when_the_store_is_stale(self):
        now = datetime.datetime.utcnow()
        backfill = self._run_gate(
            stored_dt=now - datetime.timedelta(days=9), column_dt=None)
        backfill.assert_called_once()
        # Capped at a week even though the gap is 9 days
        self.assertEqual(backfill.call_args.args[0], self.WEEK // 60)

    def test_falls_back_to_the_column_when_the_store_cannot_answer(self):
        now = datetime.datetime.utcnow()
        backfill = self._run_gate(
            stored_dt=None, column_dt=now - datetime.timedelta(hours=2))
        backfill.assert_not_called()


class TestPersistLatestDatetime(unittest.TestCase):
    """Input.datetime must advance from the live path, not the backfill alone."""

    def test_advances_when_newer(self):
        inst = _bare_module()
        row = MagicMock()
        row.datetime = datetime.datetime(2026, 8, 12, 2, 0)
        session = MagicMock()
        session.query.return_value.filter.return_value.first.return_value = row

        with patch.object(kma_weather_500, 'session_scope') as scope:
            scope.return_value.__enter__.return_value = session
            inst._persist_latest_datetime(datetime.datetime(2026, 8, 12, 3, 0))

        self.assertEqual(row.datetime, datetime.datetime(2026, 8, 12, 3, 0))
        session.commit.assert_called_once()
        self.assertEqual(inst.latest_datetime, datetime.datetime(2026, 8, 12, 3, 0))

    def test_does_not_move_backwards(self):
        inst = _bare_module()
        row = MagicMock()
        row.datetime = datetime.datetime(2026, 8, 12, 3, 0)
        session = MagicMock()
        session.query.return_value.filter.return_value.first.return_value = row

        with patch.object(kma_weather_500, 'session_scope') as scope:
            scope.return_value.__enter__.return_value = session
            inst._persist_latest_datetime(datetime.datetime(2026, 8, 12, 1, 0))

        self.assertEqual(row.datetime, datetime.datetime(2026, 8, 12, 3, 0))
        session.commit.assert_not_called()

    def test_normalizes_aware_timestamps(self):
        # The backfill hands over tz-aware UTC; the column stores naive UTC.
        # Mixing the two raises TypeError on comparison.
        inst = _bare_module()
        row = MagicMock()
        row.datetime = None
        session = MagicMock()
        session.query.return_value.filter.return_value.first.return_value = row

        aware = datetime.datetime(2026, 8, 12, 3, 0, tzinfo=datetime.timezone.utc)
        with patch.object(kma_weather_500, 'session_scope') as scope:
            scope.return_value.__enter__.return_value = session
            inst._persist_latest_datetime(aware)

        self.assertEqual(row.datetime, datetime.datetime(2026, 8, 12, 3, 0))
        self.assertIsNone(row.datetime.tzinfo)

    def test_none_is_a_no_op(self):
        inst = _bare_module()
        with patch.object(kma_weather_500, 'session_scope') as scope:
            inst._persist_latest_datetime(None)
        scope.assert_not_called()


class TestKeyMasking(unittest.TestCase):
    """The API key must not reach the log by any path."""

    URL = ('https://apihub.kma.go.kr/api/typ01/url/sfc_nc_var.php'
           '?tm1=202608051203&tm2=202608061203&lon=126.8&lat=35.8'
           '&obs=ta,hm&itv=5&help=0&authKey=FAKE0TEST0KEY0NOT0REAL')

    def test_redacts_the_key_but_keeps_the_rest(self):
        masked = kma_weather_500._mask_key(self.URL)
        self.assertNotIn('FAKE0TEST0KEY0NOT0REAL', masked)
        self.assertIn('authKey=***', masked)
        # The diagnostic parts must survive — the window is the useful bit.
        self.assertIn('tm1=202608051203', masked)
        self.assertIn('tm2=202608061203', masked)

    def test_redacts_inside_exception_text(self):
        # This is how it actually leaked: requests embeds the full URL in the
        # message, and the handler logged the exception directly.
        exc = Exception(f"504 Server Error: Gateway Timeout for url: {self.URL}")
        masked = kma_weather_500._mask_key(exc)
        self.assertNotIn('FAKE0TEST0KEY0NOT0REAL', masked)
        self.assertIn('504 Server Error', masked)

    def test_survives_unprintable_input(self):
        class Boom:
            def __str__(self):
                raise RuntimeError("nope")
        self.assertEqual(kma_weather_500._mask_key(Boom()), '<unprintable>')

    def test_no_log_call_can_carry_a_raw_key(self):
        """Every logger call reachable from a request path is masked."""
        inst = _bare_module()
        exc = Exception(f"504 for url: {self.URL}")
        with patch.object(kma_weather_500.requests, 'get', side_effect=exc), \
             patch.object(kma_weather_500.time, 'sleep'):
            inst._fetch_window('202608051203', '202608061203')

        emitted = []
        for level in ('debug', 'info', 'warning', 'error', 'exception'):
            for call in getattr(inst.logger, level).call_args_list:
                emitted.append(' '.join(str(a) for a in call.args))
        self.assertTrue(emitted, "expected the failure to be logged at all")
        for line in emitted:
            self.assertNotIn('FAKE0TEST0KEY0NOT0REAL', line, line)


class TestChunkPlanning(unittest.TestCase):
    """Fetch the gap, not the span."""

    def setUp(self):
        self.seoul = __import__('pytz').timezone('Asia/Seoul')
        self.now = datetime.datetime(2026, 8, 12, 12, 0)

    def test_chunks_are_smaller_than_the_size_that_timed_out(self):
        # koat's 504s were on 1440-minute (288-row) windows.
        self.assertLess(kma_weather_500.BACKFILL_CHUNK_MINUTES, 1440)

    def test_splits_the_span_into_chunks(self):
        inst = _bare_module()
        with patch.object(InputModule, '_chunk_is_covered', return_value=False):
            windows = inst._plan_backfill_windows(self.now, 1440, self.seoul)
        self.assertEqual(len(windows), 1440 // kma_weather_500.BACKFILL_CHUNK_MINUTES)
        # Contiguous and ordered, covering exactly [now-1440min, now]
        self.assertEqual(windows[0][0], '202608111200')
        for earlier, later in zip(windows, windows[1:]):
            self.assertEqual(earlier[1], later[0])
        self.assertEqual(windows[-1][1], '202608121200')

    def test_drops_windows_the_store_already_holds(self):
        inst = _bare_module()
        with patch.object(InputModule, '_chunk_is_covered', return_value=True):
            windows = inst._plan_backfill_windows(self.now, 1440, self.seoul)
        self.assertEqual(windows, [])

    def test_keeps_only_the_uncovered_windows(self):
        inst = _bare_module()
        calls = {'n': 0}

        def covered(*_a, **_k):
            calls['n'] += 1
            return calls['n'] != 2   # everything stored except the 2nd chunk

        with patch.object(InputModule, '_chunk_is_covered', side_effect=covered):
            windows = inst._plan_backfill_windows(self.now, 1440, self.seoul)
        self.assertEqual(len(windows), 1)

    def test_full_span_is_skipped_when_everything_is_stored(self):
        inst = _bare_module()
        with patch.object(InputModule, '_chunk_is_covered', return_value=True), \
             patch.object(kma_weather_500, 'get_device_tz', return_value=self.seoul), \
             patch.object(InputModule, '_fetch_window') as fetch:
            inst.get_new_data(7 * 1440)
        fetch.assert_not_called()


class TestChunkCoverage(unittest.TestCase):
    """Coverage is measured against the 5-minute slot count."""

    def setUp(self):
        self.seoul = __import__('pytz').timezone('Asia/Seoul')
        self.start = datetime.datetime(2026, 8, 12, 0, 0)
        self.end = datetime.datetime(2026, 8, 12, 6, 0)      # 72 slots

    def _covered_with(self, point_count):
        inst = _bare_module()
        with patch.object(kma_weather_500, 'read_influxdb_list',
                          return_value=[(0, 0)] * point_count):
            return inst._chunk_is_covered(self.start, self.end, self.seoul)

    def test_full_density_counts_as_covered(self):
        self.assertTrue(self._covered_with(72))

    def test_duplicated_series_still_counts_as_covered(self):
        # koat's already-doubled days must not trigger another fetch.
        self.assertTrue(self._covered_with(144))

    def test_empty_window_is_not_covered(self):
        self.assertFalse(self._covered_with(0))

    def test_half_filled_window_is_not_covered(self):
        self.assertFalse(self._covered_with(36))

    def test_small_upstream_gaps_still_count_as_covered(self):
        # KMA itself drops observations; demanding 100% would re-request the
        # same window on every restart forever.
        self.assertTrue(self._covered_with(70))

    def test_no_probe_channel_means_not_covered(self):
        inst = _bare_module(_probe_channel=None)
        self.assertFalse(inst._chunk_is_covered(self.start, self.end, self.seoul))

    def test_store_error_falls_back_to_fetching(self):
        inst = _bare_module()
        with patch.object(kma_weather_500, 'read_influxdb_list',
                          side_effect=RuntimeError("influx down")):
            self.assertFalse(inst._chunk_is_covered(self.start, self.end, self.seoul))


class TestFetchWindowRetries(unittest.TestCase):
    """A 504 used to cost a whole chunk of history with one ERROR line."""

    def test_retries_then_reports_the_window_as_retryable(self):
        inst = _bare_module()
        with patch.object(kma_weather_500.requests, 'get',
                          side_effect=Exception("504 Gateway Timeout")) as get, \
             patch.object(kma_weather_500.time, 'sleep') as sleep:
            rows, ok = inst._fetch_window('202608051203', '202608061203')
        self.assertEqual(rows, [])
        self.assertFalse(ok, "a timeout must be queued for a later attempt")
        self.assertEqual(get.call_count, kma_weather_500.BACKFILL_RETRY_COUNT)
        # Backs off rather than hammering
        self.assertEqual([c.args[0] for c in sleep.call_args_list], [5, 10])

    def test_succeeds_on_a_later_attempt(self):
        inst = _bare_module()
        body = "202608051205,24.1,71,180,1.2,1004.3,0,0,20,0"
        with patch.object(kma_weather_500.requests, 'get',
                          side_effect=[Exception("504"), _response(body)]), \
             patch.object(kma_weather_500.time, 'sleep'):
            rows, ok = inst._fetch_window('202608051200', '202608051210')
        self.assertTrue(ok)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['ta'], 24.1)

    def test_api_error_is_permanent_and_not_queued(self):
        # A bad key or bad coordinates will fail identically forever; queueing
        # it would retry it every cycle for the life of the process.
        inst = _bare_module()
        with patch.object(kma_weather_500.requests, 'get',
                          return_value=_response('#error : -9')), \
             patch.object(kma_weather_500.time, 'sleep'):
            rows, ok = inst._fetch_window('202608051200', '202608051210')
        self.assertEqual(rows, [])
        self.assertTrue(ok, "a permanent API error must not be retried forever")

    def test_only_the_final_failure_is_an_error(self):
        inst = _bare_module()
        with patch.object(kma_weather_500.requests, 'get',
                          side_effect=Exception("504")), \
             patch.object(kma_weather_500.time, 'sleep'):
            inst._fetch_window('202608051200', '202608051210')
        self.assertEqual(inst.logger.warning.call_count,
                         kma_weather_500.BACKFILL_RETRY_COUNT - 1)
        self.assertEqual(inst.logger.error.call_count, 1)


class TestRetryQueue(unittest.TestCase):
    """Failed windows come back on later cycles instead of vanishing."""

    def test_failed_windows_are_queued_once(self):
        inst = _bare_module()
        inst._queue_failed_window('a', 'b')
        inst._queue_failed_window('a', 'b')
        self.assertEqual(len(inst._backfill_retry_windows), 1)

    def test_drain_writes_recovered_rows_and_clears_the_entry(self):
        inst = _bare_module()
        inst._queue_failed_window('202608051200', '202608051210')
        rows = [{'pub_timestamp': '202608051205'}]
        with patch.object(kma_weather_500, 'get_device_tz'), \
             patch.object(InputModule, '_fetch_window', return_value=(rows, True)), \
             patch.object(InputModule, '_write_backfill_rows') as write:
            inst.drain_backfill_retries()
        write.assert_called_once()
        self.assertEqual(inst._backfill_retry_windows, [])

    def test_still_failing_windows_stay_queued(self):
        inst = _bare_module()
        inst._queue_failed_window('202608051200', '202608051210')
        with patch.object(kma_weather_500, 'get_device_tz'), \
             patch.object(InputModule, '_fetch_window', return_value=([], False)):
            inst.drain_backfill_retries()
        self.assertEqual(len(inst._backfill_retry_windows), 1)
        self.assertEqual(inst._backfill_retry_windows[0]['rounds'], 1)

    def test_a_window_is_abandoned_rather_than_retried_forever(self):
        inst = _bare_module()
        inst._queue_failed_window('202608051200', '202608051210')
        with patch.object(kma_weather_500, 'get_device_tz'), \
             patch.object(InputModule, '_fetch_window', return_value=([], False)):
            for _ in range(kma_weather_500.BACKFILL_RETRY_ROUNDS):
                inst.drain_backfill_retries()
        self.assertEqual(inst._backfill_retry_windows, [])
        self.assertTrue(inst.logger.error.called)

    def test_drain_is_bounded_per_cycle(self):
        inst = _bare_module()
        for i in range(10):
            inst._queue_failed_window(f'w{i}', f'w{i}e')
        with patch.object(kma_weather_500, 'get_device_tz'), \
             patch.object(InputModule, '_fetch_window',
                          return_value=([], False)) as fetch:
            inst.drain_backfill_retries()
        self.assertEqual(fetch.call_count, kma_weather_500.BACKFILL_RETRIES_PER_CYCLE)

    def test_empty_queue_does_no_work(self):
        inst = _bare_module()
        with patch.object(InputModule, '_fetch_window') as fetch:
            inst.drain_backfill_retries()
        fetch.assert_not_called()


class TestStagger(unittest.TestCase):
    """Concurrent inputs are what tip apihub into 504."""

    def test_offset_is_bounded(self):
        for uid in ('a023b596', '45b66eed', '2dbcdb95', ''):
            inst = _bare_module(unique_id=uid)
            self.assertTrue(0 <= inst._stagger_delay() <= kma_weather_500.BACKFILL_STAGGER_MAX_SEC)

    def test_offset_is_stable_across_restarts(self):
        a = _bare_module(unique_id='a023b596')._stagger_delay()
        b = _bare_module(unique_id='a023b596')._stagger_delay()
        self.assertEqual(a, b)

    def test_different_inputs_are_spread(self):
        # The two koat inputs that fired 1.4s apart must not collide.
        a = _bare_module(unique_id='a023b596-4f71-4fb7-ab1e-4fb9a2783236')._stagger_delay()
        b = _bare_module(unique_id='45b66eed-76e4-44df-b040-3ba0701e17f4')._stagger_delay()
        self.assertNotEqual(a, b)


class TestEmptyResponseLogLevel(unittest.TestCase):
    """27 ERROR lines in one day for an ordinary condition is not a signal.

    But an input logger sits at ERROR unless the user enables debug logging
    for it (base_input.py), so the escalation has to be ERROR too — a WARNING
    would make a genuine sustained outage invisible.
    """

    def _drive(self, times):
        inst = _bare_module()
        inst.api_url = 'https://apihub.kma.go.kr/x?authKey=SECRETKEY123'
        with patch.object(kma_weather_500.requests, 'get',
                          return_value=_response('# no rows here')):
            for _ in range(times):
                self.assertIsNone(inst.pre_fetch_data())
        return inst

    def test_isolated_empty_responses_are_not_errors(self):
        inst = self._drive(5)
        inst.logger.error.assert_not_called()
        inst.logger.warning.assert_not_called()

    def test_a_sustained_run_surfaces_once(self):
        inst = self._drive(6)
        self.assertEqual(inst.logger.error.call_count, 1)

    def test_the_escalation_is_visible_at_the_default_log_level(self):
        # ERROR, not WARNING: anything below ERROR is dropped for an input
        # that has not had debug logging turned on.
        inst = self._drive(6)
        inst.logger.warning.assert_not_called()
        self.assertTrue(inst.logger.error.called)

    def test_it_does_not_repeat_every_cycle(self):
        inst = self._drive(17)
        self.assertEqual(inst.logger.error.call_count, 2)  # at 6 and at 12

    def test_a_good_response_resets_the_streak(self):
        inst = _bare_module()
        inst.api_url = 'https://apihub.kma.go.kr/x?authKey=SECRETKEY123'
        body = "202608051205,24.1,71,180,1.2,1004.3,0,0,20,0"
        with patch.object(kma_weather_500.requests, 'get',
                          side_effect=[_response('#'), _response(body)]):
            inst.pre_fetch_data()
            inst.pre_fetch_data()
        self.assertEqual(inst._empty_response_streak, 0)


if __name__ == '__main__':
    unittest.main()
