# coding=utf-8
"""Open-Meteo 예보 묶음(시간별+일별) 캐시 — AI 예보 도구용.

같은 좌표(소수 2자리)·시간대면 `hours` 가 달라도 한 번만 부른다.
- 30분 이내 캐시는 그대로 쓴다(from='cache').
- 조회가 실패하거나 429 대기 중이면 6시간 이내 캐시를 낡은 채로 쓴다(stale).
- 그보다 오래면 오류 사유를 돌려준다.
파일은 `dirname(DATABASE_PATH)/openmeteo_cache/<key>.json` 에 임시파일→replace 로 쓴다.
"""
import json
import logging
import os
import threading
import time

logger = logging.getLogger(__name__)

FRESH_S = 30 * 60
STALE_MAX_S = 6 * 3600

CACHE_DIR = None             # 테스트가 덮어쓴다. None 이면 설정 경로.
_MEM = {}                    # key -> (fetched_at, bundle)
_LOCKS = {}
_LOCKS_GUARD = threading.Lock()


def _cache_dir():
    if CACHE_DIR:
        return CACHE_DIR
    from aot.config import DATABASE_PATH
    return os.path.join(os.path.dirname(DATABASE_PATH), 'openmeteo_cache')


def _key(lat, lon, tz, api_key):
    # 'h1' = 칸 값을 칸의 시작 시각에 붙인 행(openmeteo_client.cells_to_interval_start).
    # 키를 바꿔 옛 캐시 파일(칸 끝 기준)을 다시 읽지 않는다.
    return '%.2f_%.2f_%s_%s_h1' % (float(lat), float(lon),
                                   str(tz or 'auto').replace('/', '-'),
                                   'c' if api_key else 'f')


def _lock_for(key):
    with _LOCKS_GUARD:
        return _LOCKS.setdefault(key, threading.Lock())


def _read(key):
    hit = _MEM.get(key)
    if hit:
        return hit
    try:
        with open(os.path.join(_cache_dir(), key + '.json'), encoding='utf-8') as f:
            doc = json.load(f)
        hit = (float(doc['fetched_at']), doc['bundle'])
        _MEM[key] = hit
        return hit
    except (OSError, ValueError, KeyError, TypeError):
        return None


def _write(key, fetched_at, bundle):
    _MEM[key] = (fetched_at, bundle)
    try:
        d = _cache_dir()
        os.makedirs(d, exist_ok=True)
        tmp = os.path.join(d, '%s.%d.%d.tmp' % (key, os.getpid(), threading.get_ident()))
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump({'fetched_at': fetched_at, 'bundle': bundle}, f)
        os.replace(tmp, os.path.join(d, key + '.json'))
    except OSError as e:
        logger.debug('openmeteo cache write failed: %s', e)


def _info(src, fetched_at, now, stale):
    return {'from': src, 'fetched_at': fetched_at,
            'age_min': int((now - fetched_at) // 60), 'stale': stale}


def get_bundle(lat, lon, tz, api_key=None):
    """(bundle, info, err). 성공이면 err 는 None."""
    from aot.ai.context.ext import openmeteo_client
    key = _key(lat, lon, tz, api_key)
    with _lock_for(key):
        now = time.time()
        cached = _read(key)
        if cached and now - cached[0] <= FRESH_S:
            return cached[1], _info('cache', cached[0], now, False), None
        bundle, reason = openmeteo_client.fetch_forecast_bundle(lat, lon, tz, api_key)
        now = time.time()
        if bundle is not None:
            _write(key, now, bundle)
            return bundle, _info('live', now, now, False), None
        if cached and now - cached[0] <= STALE_MAX_S:
            return cached[1], _info('cache', cached[0], now, True), None
        return None, None, reason or 'unavailable'
