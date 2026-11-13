# coding=utf-8
"""
`/api/geo/water_net` 의 지형 확장 (T4) — `areas[].terrain` 과 `pressure[].segments`.

DEM 없음은 예전 응답 그대로(키 없음) / warming → ready 전환 / 구역 합계 = 배관 합 + unknown_pipes /
구간표 합 = 배관별 합 / 활성 DEM 이름·계산 시각이 실린다. 네트워크·DB 없음(합성 표본기).
"""
import pytest
from flask import Flask

from aot.utils import water_net_link, water_terrain as W
from aot.tests.geo.test_water_terrain_cache import SLOPE, FakeSampler, _net


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(W, 'cache_root', lambda: str(tmp_path / 'wtc'))
    monkeypatch.setattr(W, '_last_attempt', {})
    monkeypatch.setattr(W, '_inflight', set())
    monkeypatch.setattr(W, '_submit', lambda fn: None)
    monkeypatch.setattr(W, 'dem_name', lambda: 'Test DEM')
    monkeypatch.setattr(water_net_link, '_emitter_flows', lambda n, m, p: {e.id: e.flow_lph for e in n.emitters})
    monkeypatch.setattr(water_net_link, '_emitter_pressures', lambda n, m, p: {e.id: 2.0 for e in n.emitters})
    state = {'sampler': FakeSampler(SLOPE)}
    monkeypatch.setattr(W, '_sampler', lambda: state['sampler'])
    with Flask('t').app_context():
        yield state


IDS = ['n0', 'n1', 'n2']


def test_no_dem_adds_nothing(env):
    env['sampler'] = None
    net = _net()
    assert W.area_block(net, 'm1', IDS) is None
    rows = water_net_link._pressure_rows(net, 'm1', IDS)
    brief = water_net_link.pressure_brief(rows[0])
    assert 'terrain' not in brief and 'segments' not in brief


def test_warming_block_is_horizontal_only(env):
    net = _net()
    block = W.area_block(net, 'm1', IDS)
    assert block['state'] == 'warming' and block['dem_name'] == 'Test DEM'
    assert block['computed_at'] is None
    assert block['pipes']['main'] == {'horizontal_m': 100.0, 'slant_m': None}
    assert block['kinds'] == {'main': 'main'}
    assert block['totals'] == {'horizontal_m': 100.0, 'slant_m': 100.0, 'unknown_pipes': 1}
    brief = water_net_link.pressure_brief(water_net_link._pressure_rows(net, 'm1', IDS)[0])
    assert brief['terrain']['state'] == 'warming' and 'segments' not in brief


def test_warming_turns_ready_after_the_background_job(env):
    assert W.area_block(_net(), 'm1', IDS)['state'] == 'warming'
    W.build('m1', _net(), env['sampler'])
    block = W.area_block(_net(), 'm1', IDS)
    assert block['state'] == 'ready' and isinstance(block['computed_at'], str) and len(block['computed_at']) >= 10
    assert block['pipes']['main']['slant_m'] == pytest.approx(100.5, rel=1e-3)
    assert block['totals']['unknown_pipes'] == 0


def test_area_total_is_pipe_sum_plus_unknown_pipes(env):
    env['sampler'] = FakeSampler(SLOPE, known=lambda x, z: x < 50)
    W.build('m1', _net(), env['sampler'])
    block = W.area_block(_net(), 'm1', IDS)
    pipes = block['pipes'].values()
    assert block['state'] == 'partial'
    assert block['totals']['horizontal_m'] == pytest.approx(sum(p['horizontal_m'] for p in pipes))
    assert block['totals']['slant_m'] == pytest.approx(
        sum(p['horizontal_m'] if p['slant_m'] is None else p['slant_m'] for p in pipes))
    assert block['totals']['unknown_pipes'] == sum(1 for p in pipes if p['slant_m'] is None) == 1


def test_segments_sum_matches_pipe_lengths(env):
    W.build('m1', _net(), env['sampler'])
    rows = water_net_link._pressure_rows(_net(), 'm1', IDS)
    brief = water_net_link.pressure_brief(rows[0])
    assert brief['segments'] == rows[0]['segments'] and brief['terrain']['state'] == 'ready'
    for pipe, got in rows[0]['pipe_lengths'].items():
        mine = [s for s in brief['segments'] if s['pipe'] == pipe]
        assert sum(s['horizontal_m'] for s in mine) == pytest.approx(got['horizontal_m'], abs=1e-4)
        assert sum(s['slant_m'] for s in mine) == pytest.approx(got['slant_m'], abs=1e-4)
