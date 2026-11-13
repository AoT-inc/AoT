# coding=utf-8
"""open_meteo_http.get_json — 재시도 1회, 429 대기, 사유 분류. 망 없음."""
import time
import types
import unittest
from unittest.mock import MagicMock, patch

import requests

from aot.utils import open_meteo_http as H

URL = 'https://api.open-meteo.com/v1/forecast'


def _resp(status=200, body=None, headers=None, json_error=False):
    r = MagicMock()
    r.status_code = status
    r.reason = 'X'
    r.headers = headers or {}
    if json_error:
        r.json.side_effect = ValueError('bad')
    else:
        r.json.return_value = body if body is not None else {'hourly': {}}
    return r


class TestGetJson(unittest.TestCase):

    def setUp(self):
        H._RATE_LIMITED_UNTIL.clear()
        # ⚠ `patch.object(H.time, 'sleep')` 는 모듈 H 가 아니라 **프로세스 전체의** time.sleep 을
        # 바꾼다. 같은 프로세스의 다른 스레드(데몬·폴러)가 부른 sleep 까지 세어져 CI 에서
        # "called once, Called 905 times" 로 간헐적으로 깨졌다(2026-11-13). H 가 보는 `time`
        # 이름만 대체해, 이 모듈의 sleep 호출만 센다.
        self.sleep = MagicMock()
        p = patch.object(H, 'time', types.SimpleNamespace(
            time=time.time, sleep=self.sleep))
        p.start()
        self.addCleanup(p.stop)
        self.addCleanup(H._RATE_LIMITED_UNTIL.clear)

    def _get(self, side_effect):
        return patch.object(H._SESSION, 'get', side_effect=side_effect)

    def test_success(self):
        with self._get([_resp(body={'a': 1})]) as g:
            payload, reason = H.get_json(URL, {'x': 1})
        self.assertEqual((payload, reason), ({'a': 1}, None))
        self.assertEqual(g.call_args.kwargs['timeout'], (5, 10))

    def test_connect_timeout_retries_once_then_succeeds(self):
        with self._get([requests.ConnectTimeout(), _resp(body={'a': 1})]) as g:
            payload, reason = H.get_json(URL)
        self.assertEqual(payload, {'a': 1})
        self.assertEqual(g.call_count, 2)
        self.sleep.assert_called_once_with(1.0)

    def test_connect_failure_twice_gives_reason(self):
        with self._get([requests.ConnectionError(), requests.ConnectionError()]) as g:
            payload, reason = H.get_json(URL)
        self.assertIsNone(payload)
        self.assertEqual(reason, 'connect_error')
        self.assertEqual(g.call_count, 2)

    def test_503_is_retried_but_500_is_not(self):
        with self._get([_resp(503), _resp(body={'a': 1})]) as g:
            self.assertEqual(H.get_json(URL)[0], {'a': 1})
        self.assertEqual(g.call_count, 2)
        with self._get([_resp(500)]) as g:
            self.assertEqual(H.get_json(URL), (None, 'http_5xx'))
        self.assertEqual(g.call_count, 1)

    def test_read_timeout_is_not_retried(self):
        with self._get([requests.ReadTimeout()]) as g:
            self.assertEqual(H.get_json(URL), (None, 'read_timeout'))
        self.assertEqual(g.call_count, 1)
        self.sleep.assert_not_called()

    def test_4xx_is_not_retried_and_carries_the_reason(self):
        with self._get([_resp(400, {'error': True, 'reason': 'bad lat'})]) as g:
            payload, reason = H.get_json(URL)
        self.assertIsNone(payload)
        self.assertEqual(reason, 'http_4xx:bad lat')
        self.assertEqual(g.call_count, 1)

    def test_429_blocks_further_calls_without_http(self):
        with self._get([_resp(429, headers={'Retry-After': '120'})]) as g:
            self.assertEqual(H.get_json(URL), (None, 'rate_limited'))
            self.assertEqual(H.get_json(URL), (None, 'rate_limited'))
        self.assertEqual(g.call_count, 1)
        self.assertGreater(H.rate_limited_for(URL), 100)

    def test_429_without_retry_after_waits_ten_minutes(self):
        with self._get([_resp(429)]):
            H.get_json(URL)
        self.assertGreater(H.rate_limited_for(URL), 590)

    def test_non_json_body(self):
        with self._get([_resp(json_error=True)]):
            self.assertEqual(H.get_json(URL), (None, 'bad_json'))


if __name__ == '__main__':
    unittest.main()
