# coding=utf-8
"""
물 회로 지형 연결의 파생 저장·선계산 (계획서 15·16절 T3) — 네트워크 없음, 합성 표본기.

요청 경로는 fetch=False 만 쓴다 / 캐시 미스는 수평 폴백 + warming + 예약 1회 / 선계산 뒤 ready 와 경사 길이 /
키가 바뀌면(DEM 판·배관 이동) 낡음 / 손상 파일 / 정리 / 백그라운드 예외 격리 / DEM 없음은 예전 응답.
"""
import json
import os

import pytest
from flask import Flask

from aot.functions.utils.water_net import graph as G
from aot.functions.utils.water_net.adapters import LocalFrame
from aot.functions.utils.water_net.graph import Emitter, Network, Part, Pipe
from aot.utils import water_net_link, water_terrain as W
from aot.utils.dem_sampler import Sampler

H_M_PER_DEG = 111320.0
try:
    from aot.functions.utils.water_net.adapters import _M_PER_DEG as H_M_PER_DEG   # noqa: F811
except ImportError:                                                                # pragma: no cover
    pass


class _Frame(LocalFrame):
    def to_lnglat(self, p):
        return [self.lng0 + p[0] / self._kx, self.lat0 + p[2] / H_M_PER_DEG]


FRAME = _Frame(127.0, 35.0)


class FakeSampler(Sampler):
    """타일 없이 고도를 함수로 준다. fetch=True 로 불린 횟수를 센다(요청 경로는 0 이어야 한다)."""

    def __init__(self, fn, url='http://dem.invalid/{z}/{x}/{y}.png', known=lambda x, z: True):
        super().__init__(url, max_zoom=14, cache_root='/nonexistent-dem-cache')
        self._fn, self._known = fn, known
        self.fetch_calls = 0

    def elevation(self, lng, lat, fetch=True, _deadline=None):
        if fetch:
            self.fetch_calls += 1
        x, _y, z = FRAME.to_local(lng, lat)
        return self._fn(x, z) if self._known(x, z) else None


def _net(x_end=100.0):
    pipe = Pipe(id='main', line=[(0, 0.0, 0), (x_end, 0.0, 0)], sub_type='main', diameter_mm=50)
    pump = Part(id='pump', kind='pump', point=(0, 0.0, 0), name='pump', meta=dict(rated_lpm=285.0, head_m=36.0))
    well = Part(id='well', kind='source_well', point=(0, 0.0, 0), name='well', meta=dict(max_lpm=290.0))
    ems = [Emitter(id='n%d' % i, point=(x, 0.0, 0), flow_lph=70.0 * 60) for i, x in enumerate((30, 60, x_end))]
    net = Network(pipes=[pipe], parts=[well, pump], emitters=ems, gap_m=3.0, part_snap_m=3.0,
                  emitter_snap_m=G.DEVICE_SNAP_M)
    net.frame = FRAME
    return net


SLOPE = lambda x, z: 0.1 * x          # 10 % 경사 → 경사 길이 = 수평 × √1.01


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(W, 'cache_root', lambda: str(tmp_path / 'wtc'))
    monkeypatch.setattr(W, '_last_attempt', {})
    monkeypatch.setattr(W, '_inflight', set())
    jobs = []
    monkeypatch.setattr(W, '_submit', jobs.append)
    state = {'sampler': FakeSampler(SLOPE)}
    monkeypatch.setattr(W, '_sampler', lambda: state['sampler'])
    app = Flask('t')
    with app.app_context():
        yield state, jobs, tmp_path / 'wtc'


def test_miss_is_warming_horizontal_and_schedules_once_without_fetching(env):
    state, jobs, _root = env
    ref = W.terrain_ref('m1', _net())
    assert ref.state == 'warming' and ref.sampler is None and ref.version == state['sampler'].version
    for _ in range(3):                                   # 요청이 여러 번 와도 예약은 하나
        W.terrain_ref('m1', _net())
    assert len(jobs) == 1
    assert state['sampler'].fetch_calls == 0


def test_job_makes_ready_and_slant_is_used(env):
    state, jobs, _root = env
    net = _net()
    W.terrain_ref('m1', net)
    assert len(jobs) == 1                                # _job 은 DB 가 필요해 build 를 직접 부른다
    entry = W.build('m1', _net(), state['sampler'])
    assert entry['state'] == 'ready'
    assert entry['pipes']['main']['horizontal_m'] == pytest.approx(100.0)
    assert entry['pipes']['main']['slant_m'] == pytest.approx(100.0 * 1.01 ** 0.5, rel=1e-3)
    ref = W.terrain_ref('m1', _net())
    assert ref.state == 'ready' and ref.sampler is state['sampler']
    fetched = state['sampler'].fetch_calls
    W.terrain_ref('m1', _net())
    assert state['sampler'].fetch_calls == fetched       # 요청 경로는 더 받지 않는다


def test_unreadable_part_is_partial(env):
    state, _jobs, _root = env
    state['sampler'] = FakeSampler(SLOPE, known=lambda x, z: x < 50)
    entry = W.build('m1', _net(), state['sampler'])
    assert entry['state'] == 'partial' and entry['unknown_pipes'] == 1
    assert W.terrain_ref('m1', _net()).state == 'partial'


def test_key_changes_make_the_stored_value_stale(env):
    state, _jobs, _root = env
    W.build('m1', _net(), state['sampler'])
    assert W.terrain_ref('m1', _net()).state == 'ready'
    assert W.terrain_ref('m1', _net(x_end=120.0)).state == 'warming'          # 배관 이동
    state['sampler'] = FakeSampler(SLOPE, url='http://other.invalid/{z}/{x}/{y}.png')
    assert W.terrain_ref('m1', _net()).state == 'warming'                      # DEM 판 변경
    assert W.terrain_ref('m2', _net()).state == 'warming'                      # 다른 지도


def test_corrupt_or_partial_file_is_stale_and_removed(env):
    state, _jobs, root = env
    net = _net()
    key = W.cache_key('m1', net, state['sampler'])
    path = root / 'm1' / (key + '.json')
    path.parent.mkdir(parents=True)
    path.write_text('{"key": "x", "pip')                 # 쓰다 만 파일
    assert W.terrain_ref('m1', _net()).state == 'warming'
    assert not path.exists()
    path.write_text(json.dumps({'key': 'other', 'rules': W.RULES_VERSION, 'state': 'ready', 'pipes': {}}))
    assert W.terrain_ref('m1', _net()).state == 'warming'


def test_write_is_atomic_rename(env):
    state, _jobs, root = env
    W.build('m1', _net(), state['sampler'])
    names = os.listdir(root / 'm1')
    assert len(names) == 1 and names[0].endswith('.json')


def test_prune_keeps_three_per_map_and_total_cap(env):
    state, _jobs, root = env
    for i in range(5):
        W.build('m1', _net(x_end=100.0 + i * 7), state['sampler'])
        names = sorted(os.listdir(root / 'm1'))
        for n in names:
            os.utime(root / 'm1' / n, (1000 + i, 1000 + i)) if i == 0 else None
    assert len(os.listdir(root / 'm1')) == W.KEEP_PER_MAP
    W.prune(root=str(root), max_bytes=1)
    assert not [n for n in os.listdir(root / 'm1')]


def test_background_exception_never_reaches_the_request(env, monkeypatch):
    state, jobs, _root = env
    monkeypatch.setattr(W, '_submit', lambda fn: fn())
    monkeypatch.setattr(W, '_job', lambda key: (_ for _ in ()).throw(RuntimeError('boom')))
    assert W.schedule('m1') is True                      # 예외는 삼켜지고 단일 비행 표시는 풀린다
    assert 'm1' not in W._inflight


def test_budget_exhausted_does_not_store(env):
    state, _jobs, root = env
    assert W.build('m1', _net(), state['sampler'], budget_s=-1) is None
    assert not (root / 'm1').exists()


def test_no_dem_means_no_ref_and_unchanged_rows(env, monkeypatch):
    state, jobs, _root = env
    state['sampler'] = None
    net = _net()
    assert W.terrain_ref('m1', net) is None and not jobs
    monkeypatch.setattr(water_net_link, '_emitter_flows', lambda n, m, p: {e.id: e.flow_lph for e in n.emitters})
    monkeypatch.setattr(water_net_link, '_emitter_pressures', lambda n, m, p: {e.id: 2.0 for e in n.emitters})
    auto = water_net_link._pressure_rows(net, 'm1', [e.id for e in net.emitters])
    none = water_net_link._pressure_rows(_net(), 'm1', [e.id for e in net.emitters], terrain=None)
    assert auto == none and all('terrain' not in r for r in auto)


def test_pressure_rows_carry_state_and_use_stored_slant(env, monkeypatch):
    state, jobs, _root = env
    monkeypatch.setattr(water_net_link, '_emitter_flows', lambda n, m, p: {e.id: e.flow_lph for e in n.emitters})
    monkeypatch.setattr(water_net_link, '_emitter_pressures', lambda n, m, p: {e.id: 2.0 for e in n.emitters})
    ids = ['n0', 'n1', 'n2']
    warm = water_net_link._pressure_rows(_net(), 'm1', ids)
    assert warm[0]['terrain']['state'] == 'warming' and 'segments' not in warm[0]
    W.build('m1', _net(), state['sampler'])
    ready = water_net_link._pressure_rows(_net(), 'm1', ids)
    assert ready[0]['terrain']['state'] == 'ready' and ready[0]['segments']
    assert water_net_link.pressure_brief(ready[0])['terrain']['state'] == 'ready'
    # 요청 경로는 fetch=True 로 표본을 읽지 않았다(build 가 센 횟수 이후 증가 없음)
    before = state['sampler'].fetch_calls
    water_net_link._pressure_rows(_net(), 'm1', ids)
    assert state['sampler'].fetch_calls == before


def test_pipe_lengths_for_states(env, monkeypatch):
    state, _jobs, _root = env
    monkeypatch.setattr(water_net_link, 'network_for_map', lambda m: _net())
    monkeypatch.setattr(water_net_link, 'emitters_in_shape', lambda n, s: ['n0'] if s == 'z1' else None)
    warm = W.pipe_lengths_for('m1')
    assert warm['state'] == 'warming' and warm['pipes']['main'] == {'horizontal_m': 100.0, 'slant_m': None}
    assert warm['totals'] == {'horizontal_m': 100.0, 'slant_m': 100.0, 'unknown_pipes': 1}
    W.build('m1', _net(), state['sampler'])
    got = W.pipe_lengths_for('m1', 'z1')
    assert got['state'] == 'ready' and got['version'] == state['sampler'].version
    assert got['pipes']['main']['slant_m'] == pytest.approx(100.5, rel=1e-3)
    assert got['totals']['unknown_pipes'] == 0
    assert W.pipe_lengths_for('m1', 'nope') is None
    state['sampler'] = None
    assert W.pipe_lengths_for('m1')['state'] == 'none'
