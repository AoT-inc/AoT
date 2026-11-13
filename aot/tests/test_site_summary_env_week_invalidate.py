# coding=utf-8
"""invalidate_plot_contents — 주간 환경 계열 캐시는 키가 `uuid|d7|…` 꼴이라 접두어로 지운다 (2026-11-10 버그).

예전에는 `pop(plot_uuid)` 가 키와 맞지 않아 아무것도 지우지 못했고, 구획을 저장한 뒤에도
최대 10분 옛 계열이 보였다.
"""
from aot.aot_flask.geo import site_summary as ss


def _fill(cache, keys):
    for k in keys:
        cache[k] = (0, {'k': k})


def test_invalidate_one_plot_drops_all_its_env_week_windows_only():
    mine = [ss.env_week_key('plot-a', 7), ss.env_week_key('plot-a', 14, unit='hour')]
    other = [ss.env_week_key('plot-b', 7), ss.env_week_key('plot-ab', 7)]
    ss._PLOT_ENV_WEEK_CACHE.clear()
    try:
        _fill(ss._PLOT_ENV_WEEK_CACHE, mine + other)
        ss.invalidate_plot_contents('plot-a')
        assert set(ss._PLOT_ENV_WEEK_CACHE) == set(other)   # 접두어가 같은 'plot-ab' 는 남는다
    finally:
        ss._PLOT_ENV_WEEK_CACHE.clear()


def test_invalidate_all_still_clears_env_week():
    ss._PLOT_ENV_WEEK_CACHE.clear()
    try:
        _fill(ss._PLOT_ENV_WEEK_CACHE, [ss.env_week_key('plot-a', 7)])
        ss.invalidate_plot_contents(None)
        assert not ss._PLOT_ENV_WEEK_CACHE
    finally:
        ss._PLOT_ENV_WEEK_CACHE.clear()
