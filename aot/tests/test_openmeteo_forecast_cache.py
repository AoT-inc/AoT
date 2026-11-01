# coding=utf-8
"""openmeteo_forecast_cache.get_bundle — 30분 캐시, 6시간 낡음, 429. 망 없음."""
import tempfile
import time
import unittest
from unittest.mock import patch

from aot.ai.context.ext import openmeteo_client as C
from aot.ai.context.ext import openmeteo_forecast_cache as K
from aot.utils import open_meteo_http as H

_B = {'meta': {'grid_latitude': 1.0}, 'hourly': [{'time': 't'}], 'daily': []}


class TestCache(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        K._MEM.clear()
        K.CACHE_DIR = self._tmp.name
        self.addCleanup(setattr, K, 'CACHE_DIR', None)
        self.addCleanup(K._MEM.clear)
        H._RATE_LIMITED_UNTIL.clear()
        self.addCleanup(H._RATE_LIMITED_UNTIL.clear)
        p = patch.object(H.time, 'sleep')
        p.start()
        self.addCleanup(p.stop)

    def _http(self, results):
        """HTTP 층(get_json)을 가짜로 — results 를 차례로 돌려준다."""
        return patch.object(H, 'get_json', side_effect=list(results))

    def _age(self, seconds):
        """캐시 파일·메모리를 seconds 전에 받은 것으로 만든다."""
        key = K._key(35.8, 126.88, 'Asia/Seoul', None)
        K._write(key, time.time() - seconds, _B)

    def test_same_coordinates_twice_is_one_http_call(self):
        raw = {'latitude': 1.0, 'hourly': {'time': ['t']}, 'daily': {'time': []}}
        with self._http([(raw, None)]) as g:
            a = K.get_bundle(35.8, 126.88, 'Asia/Seoul')
            b = K.get_bundle(35.8, 126.88, 'Asia/Seoul')
        self.assertEqual(g.call_count, 1)
        self.assertEqual(a[1]['from'], 'live')
        self.assertEqual(b[1]['from'], 'cache')
        self.assertIsNone(b[2])

    def test_nearby_coordinates_share_the_key_regardless_of_hours(self):
        # 키에 hours 가 없다 — 소수 2자리 같은 좌표는 한 파일.
        self.assertEqual(K._key(35.801, 126.882, 'Asia/Seoul', None),
                         K._key(35.804, 126.879, 'Asia/Seoul', None))
        self.assertNotEqual(K._key(35.8, 126.88, 'Asia/Seoul', None),
                            K._key(35.8, 126.88, 'Asia/Tokyo', None))
        self.assertNotEqual(K._key(35.8, 126.88, 'Asia/Seoul', None),
                            K._key(35.8, 126.88, 'Asia/Seoul', 'k'))

    def test_after_ttl_it_fetches_again(self):
        self._age(31 * 60)
        raw = {'latitude': 2.0, 'hourly': {'time': ['t']}, 'daily': {'time': []}}
        with self._http([(raw, None)]) as g:
            b, info, err = K.get_bundle(35.8, 126.88, 'Asia/Seoul')
        self.assertEqual(g.call_count, 1)
        self.assertEqual(info['from'], 'live')
        self.assertEqual(b['meta']['grid_latitude'], 2.0)

    def test_file_survives_a_restart(self):
        self._age(5 * 60)
        K._MEM.clear()
        with self._http([]) as g:
            b, info, err = K.get_bundle(35.8, 126.88, 'Asia/Seoul')
        self.assertEqual(g.call_count, 0)
        self.assertEqual(info['from'], 'cache')

    def test_connect_timeout_once_then_success(self):
        raw = {'latitude': 1.0, 'hourly': {'time': ['t']}, 'daily': {'time': []}}
        import requests
        with patch.object(H._SESSION, 'get') as g:
            ok = unittest.mock.MagicMock(status_code=200)
            ok.json.return_value = raw
            g.side_effect = [requests.ConnectTimeout(), ok]
            b, info, err = K.get_bundle(35.8, 126.88, 'Asia/Seoul')
        self.assertIsNone(err)
        self.assertEqual(g.call_count, 2)

    def test_failure_with_3h_cache_is_stale(self):
        self._age(3 * 3600)
        with self._http([(None, 'connect_error')]):
            b, info, err = K.get_bundle(35.8, 126.88, 'Asia/Seoul')
        self.assertIsNone(err)
        self.assertTrue(info['stale'])
        self.assertEqual(info['age_min'], 180)

    def test_failure_with_7h_cache_is_unavailable(self):
        self._age(7 * 3600)
        with self._http([(None, 'connect_error')]):
            b, info, err = K.get_bundle(35.8, 126.88, 'Asia/Seoul')
        self.assertIsNone(b)
        self.assertEqual(err, 'connect_error')

    def test_read_timeout_has_no_retry(self):
        import requests
        with patch.object(H._SESSION, 'get', side_effect=[requests.ReadTimeout()]) as g:
            b, info, err = K.get_bundle(35.8, 126.88, 'Asia/Seoul')
        self.assertEqual(err, 'read_timeout')
        self.assertEqual(g.call_count, 1)

    def test_after_429_serves_cache_without_http(self):
        self._age(2 * 3600)
        H._RATE_LIMITED_UNTIL['api.open-meteo.com'] = time.time() + 300
        with patch.object(H._SESSION, 'get') as g:
            b, info, err = K.get_bundle(35.8, 126.88, 'Asia/Seoul')
        g.assert_not_called()
        self.assertTrue(info['stale'])

    def test_commercial_key_uses_the_commercial_host(self):
        seen = {}

        def fake(url, params=None):
            seen['url'], seen['params'] = url, params
            return {'latitude': 1, 'hourly': {'time': []}, 'daily': {'time': []}}, None
        with patch.object(H, 'get_json', side_effect=fake):
            C.fetch_forecast_bundle(35.8, 126.88, 'Asia/Seoul', 'KEY')
        self.assertIn('customer-api.open-meteo.com', seen['url'])
        self.assertEqual(seen['params']['timezone'], 'Asia/Seoul')
        self.assertEqual(seen['params']['forecast_days'], '14')
        self.assertEqual(seen['params']['apikey'], 'KEY')


if __name__ == '__main__':
    unittest.main()
