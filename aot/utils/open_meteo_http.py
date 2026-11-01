# coding=utf-8
"""Open-Meteo HTTP 호출 — AI 예보 도구용 재시도·속도제한 기록.

입력 드라이버(`aot/inputs/open_meteo_weather.py`)의 429 대기 기록과는 **따로**
둔다(공유는 범위 밖). 여기서는 호스트별 `_RATE_LIMITED_UNTIL` 만 쓴다.

계약: `get_json(url, params) -> (payload, reason)`. 절대 raise 하지 않는다.
reason: connect_timeout | read_timeout | rate_limited | http_5xx |
        http_4xx:<사유> | bad_json | connect_error | request_error.
재시도는 1회(1초 뒤), 연결 오류·연결 시간 초과·502/503/504 에만 한다.
읽기 시간 초과와 4xx 는 재시도하지 않는다.
"""
import logging
import threading
import time
from urllib.parse import urlparse

import requests

logger = logging.getLogger(__name__)

TIMEOUT = (5, 10)            # (연결, 읽기) 초
RETRY_DELAY_S = 1.0
DEFAULT_BACKOFF_S = 600      # Retry-After 가 없을 때의 429 대기

_RETRY_STATUS = (502, 503, 504)
_SESSION = requests.Session()
_RATE_LIMITED_UNTIL = {}     # host -> epoch 초
_LOCK = threading.Lock()


def rate_limited_for(url):
    """그 호스트가 429 대기 중이면 남은 초, 아니면 0."""
    host = urlparse(url).netloc
    with _LOCK:
        until = _RATE_LIMITED_UNTIL.get(host, 0)
    return max(0.0, until - time.time())


def _mark_rate_limited(host, resp):
    wait = DEFAULT_BACKOFF_S
    try:
        wait = max(1, int(float(resp.headers.get('Retry-After'))))
    except (TypeError, ValueError):
        pass
    with _LOCK:
        _RATE_LIMITED_UNTIL[host] = time.time() + wait


def _reason_of(resp):
    try:
        body = resp.json()
        if isinstance(body, dict) and body.get('reason'):
            return str(body['reason'])[:120]
    except ValueError:
        pass
    return str(resp.reason or resp.status_code)


def get_json(url, params=None):
    """(payload, reason). 성공하면 reason 은 None."""
    host = urlparse(url).netloc
    if rate_limited_for(url) > 0:
        return None, 'rate_limited'
    last = 'request_error'
    for attempt in (0, 1):
        retry = False
        try:
            resp = _SESSION.get(url, params=params, timeout=TIMEOUT)
        except requests.ConnectTimeout:
            last, retry = 'connect_timeout', True
        except requests.ReadTimeout:
            return None, 'read_timeout'
        except requests.ConnectionError:
            last, retry = 'connect_error', True
        except requests.RequestException as e:
            logger.debug('open-meteo request failed: %s', e)
            return None, 'request_error'
        else:
            code = resp.status_code
            if code == 429:
                _mark_rate_limited(host, resp)
                return None, 'rate_limited'
            if code in _RETRY_STATUS:
                last, retry = 'http_5xx', True
            elif code >= 500:
                return None, 'http_5xx'
            elif code >= 400:
                return None, 'http_4xx:%s' % _reason_of(resp)
            else:
                try:
                    payload = resp.json()
                except ValueError:
                    return None, 'bad_json'
                if not isinstance(payload, dict):
                    return None, 'bad_json'
                if payload.get('error'):
                    return None, 'http_4xx:%s' % (payload.get('reason') or 'rejected')
                return payload, None
        if retry and attempt == 0:
            time.sleep(RETRY_DELAY_S)
            continue
        break
    return None, last
