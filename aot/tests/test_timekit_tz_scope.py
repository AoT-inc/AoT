# coding=utf-8
"""`timekit.tz_scope` — 읽기 도구 한 번 동안만 시계 해석을 장소마다 한 번씩 (MCP 장소 개요 지연, 2026-11-07)."""
from unittest import mock

import pytz

from aot.utils import timekit


class _Row:
    def __init__(self, uid):
        self.unique_id = uid


def _place(calls):
    def fake(key):
        calls.append(key)
        return pytz.timezone('Asia/Seoul'), timekit.SOURCE_DEVICE
    return fake


def test_without_scope_every_call_resolves_again():
    calls = []
    with mock.patch.object(timekit, '_place_tz', _place(calls)):
        timekit.tz_of('plot-1')
        timekit.tz_of('plot-1')
    assert calls == ['plot-1', 'plot-1']


def test_scope_resolves_a_place_once_and_forgets_after():
    calls = []
    with mock.patch.object(timekit, '_place_tz', _place(calls)):
        with timekit.tz_scope():
            first = timekit.tz_of('plot-1')
            second = timekit.tz_of('plot-1')
            with timekit.tz_scope():            # 중첩은 바깥 캐시를 그대로 쓴다
                timekit.tz_of('plot-1')
        assert first is second
        assert calls == ['plot-1']
        timekit.tz_of('plot-1')                 # 블록이 끝나면 캐시도 사라진다
        assert calls == ['plot-1', 'plot-1']


def test_scope_caches_rows_by_class_and_id_only_inside_the_block():
    calls = []

    def fake_row(row):
        calls.append(row.unique_id)
        return pytz.timezone('America/Chicago'), timekit.SOURCE_DEVICE
    with mock.patch.object(timekit, '_row_tz', fake_row):
        a, b = _Row('p1'), _Row('p1')
        timekit.tz_of(a)
        timekit.tz_of(b)
        assert calls == ['p1', 'p1']
        calls.clear()
        with timekit.tz_scope():
            timekit.tz_of(a)
            timekit.tz_of(b)
            timekit.tz_of(_Row('p2'))
        assert calls == ['p1', 'p2']


def test_scope_caches_the_farm_clock_too():
    with mock.patch.object(timekit, '_farm_tz', return_value=(pytz.utc, timekit.SOURCE_UTC)) as farm:
        with timekit.tz_scope():
            timekit.tz_of()
            timekit.tz_of(timekit.FARM)
        assert farm.call_count == 1
        timekit.tz_of()
        assert farm.call_count == 2


def test_scope_is_released_when_the_block_raises():
    try:
        with timekit.tz_scope():
            raise RuntimeError('boom')
    except RuntimeError:
        pass
    assert timekit._SCOPE_TZ.get() is None
