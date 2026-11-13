# coding=utf-8
"""
물 회로 그래프 — 배관 기하에서 세운 물길, 상류·하류, 점검 항목.

시설 쪽 임자 규칙은 `test_irrigation_topology.py` 가 고정한다. 여기서는 같은 그래프를
지도에서 부품·공급과 함께 읽는 쪽을 본다.

기본 배치 (로컬 미터, 지도는 원점 위경도에서 내린다):

      펌프(0,0) ── 주배관 ──▶ T(20,0) ──▶ 끝(40,0)
                              │
                         지관 A (20,0)→(20,30)   노즐 a1(20,10) a2(20,20)
                         밸브 V (20,5)
"""

import math

import pytest

from aot.functions.utils.water_net import adapters as A
from aot.functions.utils.water_net import checks as C
from aot.functions.utils.water_net import graph as G
from aot.functions.utils.water_net.graph import Emitter, Network, Part, Pipe

LAT0, LNG0 = 35.0, 128.0
FRAME = A.LocalFrame(LNG0, LAT0)


def _line(*xz):
    return [(x, 0.0, z) for x, z in xz]


def _pipe(pid, *xz, sub_type='branch'):
    return Pipe(id=pid, line=_line(*xz), sub_type=sub_type)


def _net(pipes, parts=(), emitters=(), **kw):
    kw.setdefault('gap_m', A.MAP_GAP_M)
    kw.setdefault('part_snap_m', A.MAP_PART_SNAP_M)
    kw.setdefault('emitter_snap_m', G.DEVICE_SNAP_M)
    return Network(pipes=pipes, parts=parts, emitters=emitters, **kw)


def _part(pid, kind, x, z):
    return Part(id=pid, kind=kind, point=(x, 0.0, z), name=pid)


def _em(eid, x, z, flow=100.0):
    return Emitter(id=eid, point=(x, 0.0, z), flow_lph=flow)


def _ids(path):
    return [s['id'] for s in path]


def _base():
    return _net([_pipe('main', (0, 0), (40, 0), sub_type='main'),
                 _pipe('branch', (20, 0), (20, 30))],
                [_part('pump', 'pump', 0, 0), _part('V', 'valve_inline', 20, 5)],
                [_em('a1', 20, 10), _em('a2', 20, 20), _em('m1', 30, 0)])


# ── 마디 ───────────────────────────────────────────────────────────────────

def test_t_joint_connects_two_pipes():
    net = _net([_pipe('m', (0, 0), (10, 0), sub_type='main'), _pipe('b', (5, 0), (5, 8))])
    assert len(net.components) == 1
    assert net.joined_pipes() == {'m', 'b'}


def test_cross_joint_connects_a_main_and_a_branch_that_only_cross():
    net = _net([_pipe('a', (0, 5), (10, 5), sub_type='main'), _pipe('b', (5, 0), (5, 10))])
    assert len(net.components) == 1
    assert net.joined_pipes() == {'a', 'b'}


def test_branches_are_never_joined_to_each_other():
    cross = _net([_pipe('a', (0, 5), (10, 5)), _pipe('b', (5, 0), (5, 10))], gap_m=0.0)
    assert cross.joined_pipes() == set()
    tee = _net([_pipe('a', (0, 5), (10, 5)), _pipe('b', (5, 5), (5, 10))], gap_m=0.0)
    assert 'a' not in tee.joined_pipes() or 'b' not in tee.joined_pipes()


def test_two_mains_join_as_a_tee_but_not_as_a_cross():
    cross = _net([_pipe('a', (0, 5), (10, 5), sub_type='main'),
                  _pipe('b', (5, 0), (5, 10), sub_type='main')], gap_m=0.0)
    assert cross.joined_pipes() == set()
    tee = _net([_pipe('a', (0, 5), (10, 5), sub_type='main'),
                _pipe('b', (5, 5), (5, 10), sub_type='main')], gap_m=0.0)
    assert tee.joined_pipes() == {'a', 'b'}


def test_elbow_joint_connects_pipes_end_to_end():
    net = _net([_pipe('a', (0, 0), (5, 0)), _pipe('b', (5, 0), (5, 5))])
    assert len(net.components) == 1
    assert net.joined_pipes() == {'a', 'b'}


def test_a_polyline_bend_is_not_a_joint():
    net = _net([_pipe('a', (0, 0), (5, 0), (5, 5))])
    assert len(net.components) == 1
    assert net.joined_pipes() == set()


# ── 지도 틈 잇기 ────────────────────────────────────────────────────────────

def test_map_gap_joins_a_branch_that_stops_short_of_the_main():
    pipes = [_pipe('m', (0, 0), (10, 0), sub_type='main'), _pipe('b', (5, 2), (5, 9))]
    assert len(_net(pipes, gap_m=0.0).components) == 2
    net = _net(pipes)
    assert len(net.components) == 1
    assert net.gap_joins == [('b', 'm', 2.0)]


def test_map_gap_does_not_reach_parallel_branches():
    """양산처럼 주배관 없이 10m 간격으로 나란한 지관은 잇지 않는다."""
    net = _net([_pipe('b1', (0, 0), (0, 50)), _pipe('b2', (10, 0), (10, 50))])
    assert len(net.components) == 2


def test_gap_never_makes_a_loop_between_pipes_already_joined():
    """이미 이어진 두 배관을 틈으로 또 이으면 없는 고리가 생긴다(나주 틈 3m: 고리 0 → 10)."""
    net = _net([_pipe('m', (0, 0), (20, 0), sub_type='main'),
                _pipe('b', (5, 0), (5, 2), (18, 2))])
    assert len(net.components) == 1
    assert net.component_loops(0) == 0
    assert net.gap_joins == []


def test_gap_skips_a_second_join_to_the_same_circuit():
    net = _net([_pipe('m', (0, 0), (20, 0), sub_type='main'),
                _pipe('b', (5, 1), (15, 1))])
    assert len(net.components) == 1
    assert net.component_loops(0) == 0
    assert len(net.gap_joins) == 1


# ── 상류·하류 ───────────────────────────────────────────────────────────────

def test_upstream_path_runs_from_source_to_target():
    net = _base()
    assert _ids(net.upstream_path('a2')) == ['pump', 'main', 'branch', 'V', 'branch']
    assert _ids(net.upstream_path('m1')) == ['pump', 'main']


def test_upstream_of_a_valve_excludes_itself():
    net = _base()
    assert _ids(net.upstream_path('V')) == ['pump', 'main', 'branch']


def test_upstream_of_the_source_is_empty():
    assert _base().upstream_path('pump') == []


def test_upstream_of_a_pipe_starts_at_its_top():
    assert _ids(_base().upstream_path('branch')) == ['pump', 'main', 'branch']


def test_path_steps_carry_kind_and_name():
    step = _base().upstream_path('a1')[0]
    assert step == {'type': 'part', 'id': 'pump', 'kind': 'pump', 'name': 'pump'}


def test_downstream_emitters_of_a_valve_and_a_pump():
    net = _base()
    assert {e.id for e in net.downstream_emitters('V')} == {'a1', 'a2'}
    assert {e.id for e in net.downstream_emitters('pump')} == {'a1', 'a2', 'm1'}


def test_downstream_of_a_pipe_includes_what_hangs_on_it():
    assert {e.id for e in _base().downstream_emitters('branch')} == {'a1', 'a2'}


def test_sources_of_answers_for_every_target_kind():
    net = _base()
    for ref in ('a1', 'V', 'branch'):
        assert [p.id for p in net.sources_of(ref)] == ['pump']


def test_source_outranks_tank_and_pump_as_the_root():
    net = _net([_pipe('m', (0, 0), (30, 0), sub_type='main')],
               [_part('well', 'source_well', 0, 0), _part('tank', 'tank', 10, 0),
                _part('pump', 'pump', 20, 0)],
               [_em('e', 30, 0)])
    assert [p.id for p in net.sources_of('e')] == ['well', 'tank', 'pump']
    assert _ids(net.upstream_path('e')) == ['well', 'm', 'tank', 'm', 'pump', 'm']


def test_shared_upstream_stops_where_targets_part():
    net = _net([_pipe('m', (0, 0), (40, 0), sub_type='main'),
                _pipe('b1', (10, 0), (10, 20)), _pipe('b2', (30, 0), (30, 20))],
               [_part('pump', 'pump', 0, 0)],
               [_em('e1', 10, 10), _em('e2', 30, 10)])
    rows = net.shared_upstream(['e1', 'e2'])
    assert len(rows) == 1
    assert _ids(rows[0]['path']) == ['pump', 'm']
    assert _ids(net.shared_upstream(['e1'])[0]['path']) == ['pump', 'm', 'b1']


# ── 끊긴 회로 ───────────────────────────────────────────────────────────────

def _codes(net, *a):
    return C.count_by_code(C.find_issues(net, *a))


def test_broken_circuit_is_reported_and_has_no_source():
    net = _net([_pipe('m', (0, 0), (20, 0), sub_type='main'), _pipe('b', (50, 0), (50, 20))],
               [_part('pump', 'pump', 0, 0)], [_em('on', 10, 0), _em('off', 50, 10)])
    assert net.sources_of('off') == []
    assert [p.id for p in net.sources_of('on')] == ['pump']
    rows = C.find_issues(net)
    assert _codes(net) == {'network-disconnected': 1, 'no-source': 1}
    row = next(r for r in rows if r['code'] == 'network-disconnected')
    assert row['pipes'] == 1 and row['emitters'] == 1


def test_a_map_without_parts_has_no_supplied_circuit():
    net = _net([_pipe('m', (0, 0), (20, 0), sub_type='main')], [], [_em('e', 10, 0)])
    assert 0 not in net.fed
    assert _codes(net) == {'no-source': 1}


def test_largest_circuit_counts_as_the_main_one_when_nothing_is_supplied():
    net = _net([_pipe('big', (0, 0), (20, 0)), _pipe('small', (50, 0), (50, 20))], [],
               [_em('e1', 5, 0), _em('e2', 10, 0), _em('e3', 50, 5)])
    rows = [r for r in C.find_issues(net) if r['code'] == 'network-disconnected']
    assert len(rows) == 1 and rows[0]['emitters'] == 1


def test_two_supplied_circuits_are_not_disconnected():
    net = _net([_pipe('a', (0, 0), (20, 0)), _pipe('b', (50, 0), (70, 0))],
               [_part('p1', 'pump', 0, 0), _part('p2', 'source_well', 50, 0)])
    assert _codes(net) == {}


def test_emitter_off_every_pipe_is_left_out_and_reported():
    net = _net([_pipe('m', (0, 0), (20, 0))], [_part('p', 'pump', 0, 0)],
               [_em('near', 10, 0.5), _em('far', 10, 30)])
    assert [e.id for e in net.loose_emitters] == ['far']
    assert net.component_id('far') is None
    assert net.upstream_path('far') == []
    assert _codes(net) == {'network-disconnected': 1}
    assert C.summarize(net)['emitter_attached_pct'] == 50.0


def test_no_supply_part_means_upstream_is_only_provisional():
    """공급 없는 덩어리의 뿌리는 임시다. 글루가 경로를 내세우지 않도록 sources 가 빈다."""
    net = _net([_pipe('m', (0, 0), (20, 0))], [], [_em('e', 10, 0)])
    assert net.sources_of('e') == []


# ── 고리 ───────────────────────────────────────────────────────────────────

def _square(parts=(), emitters=()):
    return _net([_pipe('n', (0, 0), (10, 0)), _pipe('e', (10, 0), (10, 10)),
                 _pipe('s', (10, 10), (0, 10)), _pipe('w', (0, 10), (0, 0))], parts, emitters)


def test_loop_is_reported():
    net = _square()
    assert net.component_loops(0) == 1
    rows = [r for r in C.find_issues(net) if r['code'] == 'network-loop']
    assert len(rows) == 1 and rows[0]['loops'] == 1


def test_loop_still_gives_a_finite_upstream_path():
    net = _square([_part('pump', 'pump', 0, 0)], [_em('far', 10, 5), _em('near', 5, 0)])
    assert _ids(net.upstream_path('near')) == ['pump', 'n']
    path = _ids(net.upstream_path('far'))
    assert path[0] == 'pump' and path[-1] == 'e' and len(path) == len(set(path))


# ── 부품 투영 ───────────────────────────────────────────────────────────────

def test_part_off_the_pipe_projects_onto_the_nearest_one():
    net = _net([_pipe('m', (0, 0), (20, 0))], [_part('pump', 'pump', 0, 0),
                                               _part('V', 'valve_inline', 10, 2.5)],
               [_em('before', 5, 0), _em('after', 15, 0)])
    assert net.loose_parts == []
    assert {e.id for e in net.downstream_emitters('V')} == {'after'}
    assert 'V' in _ids(net.upstream_path('after'))


def test_part_outside_the_snap_is_unattached():
    far = _part('V', 'valve_inline', 10, A.MAP_PART_SNAP_M + 1)
    net = _net([_pipe('m', (0, 0), (20, 0))], [_part('p', 'pump', 0, 0), far], [_em('e', 15, 0)])
    assert [p.id for p in net.loose_parts] == ['V']
    assert net.upstream_path('V') == []
    assert net.downstream_emitters('V') == []
    rows = [r for r in C.find_issues(net) if r['code'] == 'part-unattached']
    assert len(rows) == 1 and rows[0]['part'] == 'V'


def test_part_at_a_tee_sits_on_the_junction():
    net = _net([_pipe('m', (0, 0), (40, 0), sub_type='main'), _pipe('b', (20, 0), (20, 30))],
               [_part('p', 'pump', 0, 0), _part('V', 'valve_inline', 20, 0)],
               [_em('e', 20, 10), _em('tail', 30, 0)])
    assert {e.id for e in net.downstream_emitters('V')} == {'e', 'tail'}


def test_part_keeps_its_pipe_uncut_in_the_stored_data():
    """배관을 저장하지도 나누지도 않는다 — 부품 때문에 잘린 구간은 그래프 안에서만 생긴다."""
    line = _line((0, 0), (20, 0))
    net = _net([Pipe(id='m', line=line)], [_part('V', 'valve_inline', 10, 0)])
    assert net.lines['m'] == line
    assert len(net.edges) == 2


# ── 장치 연결 ───────────────────────────────────────────────────────────────

def _lnglat(x, z):
    return FRAME.to_lnglat((x, 0.0, z))


def _map_net(features):
    return A.from_map_features(features, frame=FRAME)


def _feature_line(pid, *xz, sub='pipe_branch', **props):
    return {'type': 'Feature',
            'geometry': {'type': 'LineString', 'coordinates': [_lnglat(x, z) for x, z in xz]},
            'properties': dict({'sub_type': sub, 'node_id': pid}, **props)}


def _feature_part(pid, kind, x, z, **props):
    return {'type': 'Feature',
            'geometry': {'type': 'Point', 'coordinates': _lnglat(x, z)},
            'properties': dict({'sub_type': kind, 'node_id': pid, 'name': pid}, **props)}


def _feature_cov(pid, x, z, flow=850):
    lng, lat = _lnglat(x, z)
    return {'type': 'Feature',
            'geometry': {'type': 'Polygon', 'coordinates': [[[lng, lat], [lng, lat], [lng, lat]]]},
            'properties': {'sub_type': 'sprinkler_coverage', 'node_id': pid, 'flow': flow,
                           'center_lat': lat, 'center_lng': lng}}


def _marker(device_id, x, z, kind='output', name=None):
    lng, lat = _lnglat(x, z)
    return {'device_id': device_id, 'device_kind': kind, 'lng': lng, 'lat': lat,
            'name': name or device_id}


def test_one_marker_in_radius_links_the_part():
    net = _map_net([_feature_line('m', (0, 0), (20, 0)), _feature_part('V', 'valve_inline', 10, 0)])
    A.link_part_devices(net, [_marker('out-1', 12, 1)])
    assert net.part_devices['V']['device']['device_id'] == 'out-1'
    assert C.count_by_code(C.find_issues(net)) == {'no-source': 1}


def test_two_markers_in_radius_are_ambiguous_and_stay_unlinked():
    net = _map_net([_feature_line('m', (0, 0), (20, 0)), _feature_part('V', 'valve_inline', 10, 0)])
    A.link_part_devices(net, [_marker('out-1', 12, 1), _marker('in-1', 8, 1, kind='input')])
    assert net.part_devices['V']['device'] is None
    rows = [r for r in C.find_issues(net) if r['code'] == 'part-device-ambiguous']
    assert len(rows) == 1 and sorted(rows[0]['candidates']) == ['in-1', 'out-1']


def test_marker_outside_the_radius_or_of_another_kind_is_ignored():
    net = _map_net([_feature_line('m', (0, 0), (20, 0)), _feature_part('V', 'valve_inline', 10, 0)])
    A.link_part_devices(net, [_marker('far', 10 + A.PART_DEVICE_RADIUS_M + 1, 0),
                              _marker('fn', 10, 0, kind='function')])
    assert 'V' not in net.part_devices


def test_same_device_marked_twice_is_not_ambiguous():
    net = _map_net([_feature_line('m', (0, 0), (20, 0)), _feature_part('V', 'valve_inline', 10, 0)])
    A.link_part_devices(net, [_marker('out-1', 11, 0), _marker('out-1', 9, 0)])
    assert net.part_devices['V']['device']['device_id'] == 'out-1'


# ── 담당 폴리곤과 배관 ──────────────────────────────────────────────────────

def test_cover_over_two_circuits_is_a_mismatch():
    net = _net([_pipe('a', (0, 0), (20, 0)), _pipe('b', (50, 0), (70, 0))], [],
               [_em('e1', 5, 0), _em('e2', 55, 0)])
    rows = [r for r in C.find_issues(net, [C.Cover('out', 'v1', ['e1', 'e2'])])
            if r['code'] == 'area-pipe-mismatch']
    assert len(rows) == 1 and rows[0]['reason'] == 'split' and rows[0]['networks'] == 2


def test_cover_nozzle_outside_the_linked_valve_is_a_mismatch():
    net = _base()
    net.part_devices['V'] = {'device': {'device_id': 'out'}, 'candidates': []}
    rows = [r for r in C.find_issues(net, [C.Cover('out', 'v1', ['a1', 'm1'])])
            if r['code'] == 'area-pipe-mismatch']
    assert len(rows) == 1 and rows[0]['reason'] == 'valve' and rows[0]['emitters'] == 1


def test_cover_matching_the_valve_is_silent():
    net = _base()
    net.part_devices['V'] = {'device': {'device_id': 'out'}, 'candidates': []}
    assert not [r for r in C.find_issues(net, [C.Cover('out', 'v1', ['a1', 'a2'])])
                if r['code'] == 'area-pipe-mismatch']


# ── 유량 없는 노즐 ──────────────────────────────────────────────────────────

def test_emitter_without_flow_counts_zone_defaults_apart():
    net = _net([_pipe('m', (0, 0), (20, 0))], [_part('p', 'pump', 0, 0)],
               [_em('a', 1, 0, None), _em('b', 2, 0, 0.0), _em('c', 3, 0, 100.0)])
    rows = [r for r in C.find_issues(net, (), ['a']) if r['code'] == 'emitter-no-flow']
    assert len(rows) == 1 and rows[0]['emitters'] == 2 and rows[0]['zone_default'] == 1


# ── 지도 어댑터 ─────────────────────────────────────────────────────────────

def test_map_adapter_reads_pipes_emitters_and_parts():
    net = _map_net([_feature_line('m', (0, 0), (40, 0), sub='pipe_main', name='Main Pipe'),
                    _feature_line('b', (20, 0), (20, 30)),
                    _feature_cov('c1', 20, 10),
                    _feature_part('pump', 'pump', 0, 0)])
    assert {p.id: p.sub_type for p in net.pipes} == {'m': 'main', 'b': 'branch'}
    assert [e.id for e in net.emitters] == ['c1']
    assert net.emitters[0].flow_lph == 850
    assert [p.id for p in net.parts] == ['pump']
    assert _ids(net.upstream_path('c1')) == ['pump', 'm', 'b']


def test_map_adapter_ignores_connected_main_id():
    """비어 있는 지관이 66% 다. 값이 있어도 기하가 이긴다."""
    net = _map_net([_feature_line('m', (0, 0), (20, 0), sub='pipe_main'),
                    _feature_line('far', (100, 0), (100, 20), connected_main_id='m')])
    assert len(net.components) == 2


def test_map_adapter_ignores_markers_and_unknown_features():
    net = _map_net([_feature_line('m', (0, 0), (20, 0)),
                    {'type': 'Feature', 'geometry': {'type': 'Point', 'coordinates': _lnglat(1, 0)},
                     'properties': {'sub_type': 'sprinkler'}},
                    {'type': 'Feature', 'geometry': {'type': 'Point', 'coordinates': _lnglat(2, 0)},
                     'properties': {'drawType': 'marker'}}])
    assert net.emitters == [] and net.parts == []


def test_map_adapter_uses_the_coverage_center_not_the_ring():
    feat = _feature_cov('c', 10, 0)
    lng, lat = _lnglat(10, 15)
    feat['geometry']['coordinates'] = [[[lng, lat], [lng + 1e-4, lat], [lng, lat + 1e-4]]]
    net = _map_net([_feature_line('m', (0, 0), (20, 0)), feat])
    assert net.loose_emitters == []


def test_map_adapter_drip_pipe_is_a_line_of_emitters():
    net = _map_net([_feature_line('d', (0, 0), (100, 0), is_drip=True,
                                  drip_config={'interval': 0.5, 'flow': 2.0})])
    em = net.emitters[0]
    assert em.kind == 'drip' and em.pipe_id == 'd'
    assert em.count == pytest.approx(200, abs=1)
    assert em.flow_lph == pytest.approx(400, abs=2)
    assert net.loose_emitters == []


def test_map_adapter_handles_pipes_without_node_id():
    feats = [_feature_line('x', (0, 0), (10, 0)), _feature_line('y', (0, 5), (10, 5))]
    for f in feats:
        del f['properties']['node_id']
    net = _map_net(feats)
    assert len(net.pipes) == 2


def test_map_adapter_with_nothing_to_read():
    assert A.from_map_features([]) is None
    assert A.from_map_features([{'type': 'Feature', 'properties': {}}]) is None


def test_local_frame_round_trip_and_scale():
    frame = A.LocalFrame(128.0, 35.0)
    p = frame.to_local(128.001, 35.001)
    assert p[2] == pytest.approx(111.32, abs=0.01)
    assert p[0] == pytest.approx(111.32 * math.cos(math.radians(35.0)), abs=0.01)
    assert frame.to_lnglat(p) == [128.001, 35.001]


# ── 지도·시설 어댑터 동등성 ─────────────────────────────────────────────────

H = 2.0


def _fac_pipe(pid, *xz, sub='branch'):
    segs = [{'from': [xz[i][0], H, xz[i][1]], 'to': [xz[i + 1][0], H, xz[i + 1][1]]}
            for i in range(len(xz) - 1)]
    return {'kind': 'irrigation_pipe', 'id': pid, 'layer_id': 'L', 'sub_type': sub,
            'is_vertical': False, 'segments': segs}


def _fac_point(kind, fid, pipe_id, x, z):
    return {'kind': kind, 'id': fid, 'layer_id': 'L', 'pipe_id': pipe_id,
            'position': {'x': x, 'y': H, 'z': z}}


def _both():
    """같은 배치를 두 어댑터로. 공급은 시설이 주배관 시작점, 지도가 그 자리의 펌프다."""
    fittings = [{'kind': 'irrigation_layer', 'id': 'L', 'height_m': H},
                _fac_pipe('main', (0, 0), (40, 0), sub='main'),
                _fac_pipe('b1', (10, 0), (10, 30)),
                _fac_pipe('b2', (30, 0), (30, 30)),
                _fac_point('irrigation_valve', 'V1', 'b1', 10, 5),
                _fac_point('irrigation_device', 'n1', 'b1', 10, 10),
                _fac_point('irrigation_device', 'n2', 'b1', 10, 20),
                _fac_point('irrigation_device', 'n3', 'b2', 30, 10),
                _fac_point('irrigation_device', 'n4', 'main', 20, 0)]
    fac = A.from_facility_fittings(fittings)['L']
    site = _map_net([_feature_line('main', (0, 0), (40, 0), sub='pipe_main'),
                     _feature_line('b1', (10, 0), (10, 30)),
                     _feature_line('b2', (30, 0), (30, 30)),
                     _feature_part('supply', 'pump', 0, 0),
                     _feature_part('V1', 'valve_inline', 10, 5),
                     _feature_cov('n1', 10, 10), _feature_cov('n2', 10, 20),
                     _feature_cov('n3', 30, 10), _feature_cov('n4', 20, 0)])
    return fac, site


def _pipes_and_valves(path):
    return [s['id'] for s in path if s['id'] != 'supply']


@pytest.mark.parametrize('ref', ['n1', 'n2', 'n3', 'n4', 'V1'])
def test_both_adapters_give_the_same_upstream(ref):
    fac, site = _both()
    assert _pipes_and_valves(fac.upstream_path(ref)) == _pipes_and_valves(site.upstream_path(ref))


def test_both_adapters_give_the_same_downstream():
    fac, site = _both()
    assert {e.id for e in fac.downstream_emitters('V1')} == {'n1', 'n2'}
    assert {e.id for e in site.downstream_emitters('V1')} == {'n1', 'n2'}


def test_both_adapters_give_the_same_nearest_valve():
    fac, site = _both()
    for em_f, em_m in zip(sorted(fac.emitters, key=lambda e: e.id),
                          sorted(site.emitters, key=lambda e: e.id)):
        owner_f, owner_m = fac.owner_of(em_f), site.owner_of(em_m)
        id_f = owner_f.id if owner_f else None
        id_m = owner_m.id if owner_m else None
        assert id_f == (None if id_m == 'supply' else id_m)


def test_facility_layer_counts_its_feed_as_supply():
    fac, _site = _both()
    assert fac.fed == {0}
    assert 'no-source' not in C.count_by_code(C.find_issues(fac))


def test_from_facility_fittings_keeps_layers_apart():
    fittings = [{'kind': 'irrigation_layer', 'id': 'L'}, {'kind': 'irrigation_layer', 'id': 'L2'},
                _fac_pipe('a', (0, 0), (10, 0)),
                dict(_fac_pipe('b', (0, 0), (10, 0)), layer_id='L2')]
    nets = A.from_facility_fittings(fittings)
    assert set(nets) == {'L', 'L2'}
    assert [p.id for p in nets['L'].pipes] == ['a']
    assert [p.id for p in nets['L2'].pipes] == ['b']


# ── 크기 ───────────────────────────────────────────────────────────────────

def test_a_map_of_nazu_size_resolves_within_a_second():
    """지관 40개에 노즐 878개 규모(나주). 1초 안, 저장 없이."""
    import time
    feats = [_feature_line('main', (0, 0), (0, 400), sub='pipe_main')]
    for i in range(40):
        z = 10 * i
        feats.append(_feature_line('b%d' % i, (0, z), (220, z)))
        for j in range(22):
            feats.append(_feature_cov('c%d-%d' % (i, j), 10 * j, z))
    started = time.perf_counter()
    net = _map_net(feats)
    issues = C.find_issues(net)
    elapsed = time.perf_counter() - started
    assert len(net.emitters) == 880 and net.loose_emitters == []
    assert elapsed < 1.0, elapsed
    assert C.count_by_code(issues) == {'no-source': 1}


def test_a_branch_that_overshoots_the_main_does_not_make_a_tiny_loop():
    """지관 끝이 주관을 0.2 m 넘어가면 십자와 틈 잇기가 둘 다 서서 작은 고리가 생겼다."""
    main = _pipe('m', (-10, 0), (10, 0), sub_type='main')
    net = _net([main, _pipe('b', (0, -0.2), (0, 20))])
    assert len(net.components) == 1
    edges = len(net.edges)
    nodes = len(net.adj)
    assert edges == nodes - 1          # 고리 없음(나무)


def test_branches_are_not_gap_joined_to_each_other():
    net = _net([_pipe('a', (0, 0), (10, 0)), _pipe('b', (5, 0.5), (5, 9))])
    assert len(net.components) == 2
