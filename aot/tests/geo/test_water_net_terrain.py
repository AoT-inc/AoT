# coding=utf-8
"""
물 회로 ↔ 지형(DEM) 연결 (계획서 15·16절 T2) — 마디 표고, 구간별 경사 길이, 정수두, 가정 표지.

네트워크 없이 도는 합성 표본기를 쓴다: `dem_sampler.Sampler` 를 잇되 ``elevation`` 만 로컬 좌표의 함수로 바꿨다
(profile 은 진짜 것이라 표본 간격·200점 상한·구면 거리까지 그대로 탄다).

배치 (로컬 미터): 펌프(0,0) ── 주배관 100 m ──▶ (100,0), 노즐 n0(30,0) n1(60,0) n2(100,0)
"""

import math

import pytest

from aot.functions.utils.water_net import graph as G
from aot.functions.utils.water_net import hydraulics as H
from aot.functions.utils.water_net import terrain as T
from aot.functions.utils.water_net.adapters import LocalFrame
from aot.functions.utils.water_net.graph import Emitter, Network, Part, Pipe
from aot.utils.dem_sampler import Sampler


class _ExactFrame(LocalFrame):
    """표본 좌표 반올림(1e-7°≈1cm)을 뺀 틀 — 합성 지형의 검산을 1e-6 으로 하려는 것."""

    def to_lnglat(self, p):
        return [self.lng0 + p[0] / self._kx, self.lat0 + p[2] / H_M_PER_DEG]


H_M_PER_DEG = 111320.0
try:
    from aot.functions.utils.water_net.adapters import _M_PER_DEG as H_M_PER_DEG   # noqa: F811
except ImportError:                                                                # pragma: no cover
    pass

FRAME = _ExactFrame(127.0, 35.0)


class FakeSampler(Sampler):
    def __init__(self, fn):
        super().__init__('http://dem.invalid/{z}/{x}/{y}.png', max_zoom=14, cache_root='/nonexistent-dem-cache')
        self._fn = fn

    def elevation(self, lng, lat, fetch=True, _deadline=None):
        x, _y, z = FRAME.to_local(lng, lat)
        return self._fn(x, z)


def _pipe(pid, *xz, dia=50, sub='main'):
    return Pipe(id=pid, line=[(x, 0.0, z) for x, z in xz], sub_type=sub, diameter_mm=dia)


PUMP = Part(id='pump', kind='pump', point=(0, 0.0, 0), name='pump', meta=dict(rated_lpm=285.0, head_m=36.0))
WELL = Part(id='well', kind='source_well', point=(0, 0.0, 0), name='well', meta=dict(max_lpm=290.0))


def _net(xs=(30, 60, 100), pipes=None):
    pipes = pipes or [_pipe('main', (0, 0), (100, 0))]
    ems = [Emitter(id='n%d' % i, point=(x, 0.0, 0), flow_lph=70.0 * 60) for i, x in enumerate(xs)]
    net = Network(pipes=pipes, parts=[WELL, PUMP], emitters=ems, gap_m=3.0, part_snap_m=3.0,
                  emitter_snap_m=G.DEVICE_SNAP_M)
    net.frame = FRAME
    return net


def _eval(net, fn=None, **kw):
    ems = net.emitters
    terrain = T.Terrain(net, FRAME, FakeSampler(fn)) if fn is not None else None
    return H.evaluate(net, 0, ems, {e.id: e.flow_lph for e in ems}, {e.id: 2.0 for e in ems}, terrain=terrain, **kw)


def test_nodes_remember_their_real_position():
    net = _net()
    assert (100.0, 0.0, 0.0) in net.node_pos.values()
    assert all(n in net.node_pos for n in net.adj)


def test_nodata_and_ocean_are_none():
    net = _net()
    for bad in (-32768.0, -9999.0, 9500.0, float('nan')):
        ez = T.elevation_for(net, FRAME, FakeSampler(lambda x, z, b=bad: b))
        assert all(ez(n) is None for n in net.node_pos)
    ez = T.elevation_for(net, FRAME, FakeSampler(lambda x, z: -9999.0))
    assert all(ez(n) is None for n in net.node_pos)
    ez = T.elevation_for(net, FRAME, FakeSampler(lambda x, z: 12.5))
    assert all(ez(n) == pytest.approx(12.5) for n in net.node_pos)


def test_without_terrain_nothing_changes_and_no_new_keys():
    row = _eval(_net())
    assert row['level'] == 'L1'
    assert 'segments' not in row and 'pipe_lengths' not in row and 'terrain' not in row
    assert H.A_ELEVATION_FLAT in row['assumptions']


def test_flat_terrain_equals_no_terrain():
    base = _eval(_net())
    flat = _eval(_net(), lambda x, z: 0.0)
    for k in ('pump_lpm', 'pump_head_m', 'bar_min', 'bar_mean', 'bar_max', 'flow_ratio_min'):
        assert flat['summary'][k] == base['summary'][k]
    assert H.A_ELEVATION_FLAT not in flat['assumptions']
    assert H.A_ELEVATION_PARTIAL not in flat['assumptions'] and H.A_LENGTH_HORIZONTAL not in flat['assumptions']
    assert flat['terrain']['version'].startswith('v') or flat['terrain']['version']
    for seg in flat['segments']:
        assert seg['slant_m'] == pytest.approx(seg['horizontal_m'], abs=1e-9)
        assert seg['grade_pct'] == 0


def test_slope_gives_slant_length_and_proportional_loss():
    row = _eval(_net(), lambda x, z: 0.1 * x)
    pl = row['pipe_lengths']['main']
    assert pl['horizontal_m'] == pytest.approx(G.line_length(_net().lines['main']), abs=1e-3)
    assert pl['slant_m'] == pytest.approx(100.0 * math.sqrt(1.01), rel=1e-6)
    for seg in row['segments']:
        assert seg['slant_m'] == pytest.approx(seg['horizontal_m'] * math.sqrt(1.01), rel=1e-6)
        assert seg['grade_pct'] == pytest.approx(10.0, abs=0.01)
        want = H.hazen_williams_m(seg['flow_lpm'], 50, seg['slant_m'], H.DEFAULT_C)
        assert seg['loss_m'] == pytest.approx(want, rel=1e-3, abs=1e-4)


def test_segments_sum_to_pipe_lengths_even_when_split_at_nozzles():
    net = _net()
    row = _eval(net, lambda x, z: 0.1 * x)
    assert len(row['segments']) == 3                       # 노즐 셋이 앉은 자리마다 나뉜다
    assert sum(s['horizontal_m'] for s in row['segments']) == pytest.approx(row['pipe_lengths']['main']['horizontal_m'], abs=1e-9)
    assert sum(s['slant_m'] for s in row['segments']) == pytest.approx(row['pipe_lengths']['main']['slant_m'], abs=1e-9)
    whole = T.Terrain(net, FRAME, FakeSampler(lambda x, z: 0.1 * x)).slant('main', 0.0, 100.0)
    assert whole[1] == pytest.approx(row['pipe_lengths']['main']['slant_m'], rel=1e-6)


def _one_nozzle_tree(dz_fn):
    net = _net(xs=(100,))
    ems = net.emitters
    terrain = T.Terrain(net, FRAME, FakeSampler(dz_fn))
    specs = {e.id: (e.flow_lph / 60.0, 2.0) for e in ems}
    tree, _left = H.build_tree(net, 'pump', ems, specs, terrain)
    return net, tree


@pytest.mark.parametrize('slope', [0.1, -0.1])
def test_static_head_is_the_nozzle_height_over_the_source(slope):
    net, tree = _one_nozzle_tree(lambda x, z: slope * x)
    point = H.operating_point(tree, H.Pump(285.0, 36.0))
    nz = point['nozzles'][0]
    loss = sum(l['loss_m'] for l in point['links'])
    dz = slope * 100.0
    # 노즐 압력수두 = 펌프 출구 수두 − 관 손실 − 노즐이 펌프보다 높은 만큼
    assert nz['bar'] * H.M_PER_BAR == pytest.approx(point['pump']['delivered_head_m'] - loss - dz, abs=1e-6)
    # 같은 나무를 평지로 풀면 같은 식에서 dz 만 빠진다
    flat_net, flat_tree = _one_nozzle_tree(lambda x, z: 0.0)
    flat = H.operating_point(flat_tree, H.Pump(285.0, 36.0))
    assert flat['nozzles'][0]['bar'] * H.M_PER_BAR == pytest.approx(
        flat['pump']['delivered_head_m'] - sum(l['loss_m'] for l in flat['links']), abs=1e-6)
    assert (nz['bar'] < flat['nozzles'][0]['bar']) == (slope > 0)


def test_partial_nodata_keeps_other_links_sloped_and_flags_it():
    def terrain_fn(x, z):
        return -32768.0 if x > 80 else 0.1 * x        # 마지막 구간(60→100)에 nodata
    row = _eval(_net(), terrain_fn)
    segs = sorted(row['segments'], key=lambda s: s['s_a'])
    assert [s['slant_m'] is None for s in segs] == [False, False, True]
    assert segs[2]['grade_pct'] == 0                       # 표고를 모르는 구간의 낙차는 평지
    assert H.A_LENGTH_HORIZONTAL in row['assumptions']
    assert H.A_ELEVATION_PARTIAL in row['assumptions']
    assert H.A_ELEVATION_FLAT not in row['assumptions']
    # 아는 구간은 여전히 경사 길이다
    assert segs[0]['slant_m'] == pytest.approx(segs[0]['horizontal_m'] * math.sqrt(1.01), rel=1e-6)
    assert row['pipe_lengths']['main']['slant_m'] < 100.0 * math.sqrt(1.01)


def test_everything_unreadable_falls_back_to_flat_numbers():
    base = _eval(_net())
    row = _eval(_net(), lambda x, z: -9999.0)
    assert H.A_ELEVATION_FLAT in row['assumptions'] and H.A_LENGTH_HORIZONTAL in row['assumptions']
    for k in ('pump_lpm', 'pump_head_m', 'bar_min', 'bar_mean', 'bar_max'):
        assert row['summary'][k] == base['summary'][k]
    assert all(s['slant_m'] is None for s in row['segments'])


def test_legacy_elevation_argument_still_works_without_terrain():
    row = _eval(_net(), elevation=lambda n: 0.0)
    assert H.A_ELEVATION_FLAT not in row['assumptions']
    assert 'segments' not in row
