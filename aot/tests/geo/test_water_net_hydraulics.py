# coding=utf-8
"""
물 회로 L1 압력 계산 — 수식, 작동점, 근거가 빈 자리의 L0 복귀.

배치 (로컬 미터):

    펌프(0,0) ── 주배관 100 m ──▶ (100,0)
                  노즐 n1(30,0) n2(60,0) n3(100,0)     각 70 L/h @ 2 bar

EPANET 검산은 `wntr` 가 깔린 환경에서만 돈다(없으면 건너뛴다).
"""

import math

import pytest

from aot.functions.utils.water_net import graph as G
from aot.functions.utils.water_net import hydraulics as H
from aot.functions.utils.water_net.graph import Emitter, Network, Part, Pipe


def _pipe(pid, *xz, dia=None, material=None, sub='main'):
    return Pipe(id=pid, line=[(x, 0.0, z) for x, z in xz], sub_type=sub, diameter_mm=dia,
                material=material)


def _part(pid, kind, x, z, **meta):
    return Part(id=pid, kind=kind, point=(x, 0.0, z), name=pid, meta=meta)


def _em(eid, x, z, flow=70.0):
    return Emitter(id=eid, point=(x, 0.0, z), flow_lph=flow)


def _net(pipes, parts, emitters):
    return Network(pipes=pipes, parts=parts, emitters=emitters, gap_m=3.0, part_snap_m=3.0,
                   emitter_snap_m=G.DEVICE_SNAP_M)


PUMP = _part('pump', 'pump', 0, 0, rated_lpm=285.0, head_m=36.0)
WELL = _part('well', 'source_well', 0, 0, max_lpm=290.0)


def _line_net(dia=50, n=3, flow=70.0, pump=PUMP):
    xs = [30, 60, 100][:n]
    return _net([_pipe('main', (0, 0), (100, 0), dia=dia)], [WELL, pump] if pump else [WELL],
                [_em('n%d' % i, x, 0, flow) for i, x in enumerate(xs)])


def _evaluate(net, flow=70.0, bar=2.0, **kw):
    ems = net.emitters
    return H.evaluate(net, 0, ems, {e.id: flow for e in ems}, {e.id: bar for e in ems}, **kw)


# ── 수식 ────────────────────────────────────────────────────────────────────

def test_hazen_williams_matches_the_textbook_value():
    # 100 L/min, 50 mm, 100 m, C=150 → 0.0016667 m³/s: 10.67·100·Q^1.852/(150^1.852·0.05^4.87)
    q = 100 / 60000.0
    expect = 10.67 * 100 * q ** 1.852 / (150 ** 1.852 * 0.05 ** 4.87)
    assert H.hazen_williams_m(100, 50, 100) == pytest.approx(expect)
    assert H.hazen_williams_m(100, 50, 100) == pytest.approx(1.545, abs=0.005)


def test_loss_is_zero_without_flow_or_length():
    assert H.hazen_williams_m(0, 50, 100) == 0.0
    assert H.hazen_williams_m(100, 50, 0) == 0.0


def test_velocity():
    assert H.velocity_ms(60, 25.0) == pytest.approx(0.001 / (math.pi * 0.0125 ** 2), rel=1e-6)


def test_pump_curve_passes_through_the_rated_point():
    pump = H.Pump(285.0, 36.0)
    assert pump.head_m(285.0) == pytest.approx(36.0)
    assert pump.head_m(0.0) == pytest.approx(36.0 * 1.33)
    assert pump.head_m(10_000.0) == 0.0


def test_nozzle_follows_square_root_law():
    nz = H.Nozzle('a', 'n', 1.0, 2.0)
    assert nz.flow_lpm(2.0 * H.M_PER_BAR) == pytest.approx(1.0)
    assert nz.flow_lpm(0.5 * H.M_PER_BAR) == pytest.approx(0.5)      # 압력 1/4 → 유량 1/2
    assert nz.flow_lpm(0.0) == 0.0


# ── 작동점 ──────────────────────────────────────────────────────────────────

def test_operating_point_closes_the_energy_balance():
    net = _line_net()
    out = _evaluate(net)
    assert out['level'] == H.LEVEL_L1 and out['reasons'] == []
    s = out['summary']
    # 노즐 3개 210 L/h = 3.5 L/min. 펌프 양정이 노즐 기준(2 bar)보다 훨씬 높아 실제 유량은 기준을 넘는다.
    assert s['design_lpm'] == pytest.approx(3.5)
    assert s['pump_lpm'] > s['design_lpm']
    assert s['pump_lpm'] == pytest.approx(s['design_lpm'] * s['flow_ratio_mean'], rel=0.02)
    # 펌프 곡선이 가리키는 양정은 작동점 유량에서의 곡선값이다.
    pump = H.Pump(285.0, 36.0)
    assert s['pump_head_m'] == pytest.approx(pump.head_m(s['pump_lpm']), abs=0.1)
    # 노즐은 가동 압력이 기준 2 bar 보다 훨씬 높아(양정 약 47 m ≈ 4.6 bar) 유량이 기준을 넘는다.
    assert s['bar_min'] > 2.0
    assert s['flow_ratio_min'] > 1.0


def test_thin_pipe_drops_pressure_toward_the_end():
    net = _net([_pipe('main', (0, 0), (400, 0), dia=25)], [WELL, PUMP],
               [_em('n%d' % i, 40 * (i + 1), 0, 1_200.0) for i in range(10)])
    out = _evaluate(net, flow=1_200.0, bar=2.0)
    assert out['level'] == H.LEVEL_L1
    s = out['summary']
    assert s['bar_min'] < s['bar_max']
    assert s['worst_nozzle'] == 'n9'                          # 가장 먼 노즐이 가장 낮다
    assert s['max_velocity_ms'] > 1.0                          # 가는 관에 센 유량


def test_nozzles_are_split_along_the_pipe():
    """한 배관에 노즐이 여럿 달려도 노즐 사이 손실을 센다 — 끝으로 갈수록 압력이 내려간다."""
    net = _line_net(dia=25, n=3, flow=3_000.0)
    out = _evaluate(net, flow=3_000.0, bar=2.0)
    point = H.operating_point(*_tree(net, flow=3_000.0))
    bars = {n['id']: n['bar'] for n in point['nozzles']}
    assert bars['n0'] > bars['n1'] > bars['n2']
    assert out['level'] == H.LEVEL_L1


def _tree(net, flow=70.0, bar=2.0):
    ems = net.emitters
    specs = {e.id: (flow / 60.0, bar) for e in ems}
    pump = H.Pump(285.0, 36.0)
    tree, left = H.build_tree(net, 'pump', ems, specs)
    assert left == []
    return tree, pump


def test_series_loss_matches_hand_calculation():
    """노즐 하나, 배관 하나 — 작동점이 손계산과 맞는다."""
    net = _net([_pipe('main', (0, 0), (100, 0), dia=25)], [WELL, PUMP],
               [_em('n', 100, 0, 30_000.0)])
    tree, pump = _tree(net, flow=30_000.0)         # 일부러 센 유량 — 관 손실이 지배하는 자리
    point = H.operating_point(tree, pump)
    q = point['pump']['lpm']
    # 에너지 수지: 양정 = 관 손실 + 노즐 수두,  노즐 유량 = k√P
    loss = H.hazen_williams_m(q, 25.0, 100.0)
    nozzle = tree.nozzles[0]
    p_m = (q / nozzle.k) ** 2
    assert point['pump']['head_m'] == pytest.approx(loss + p_m, rel=1e-4)
    assert point['nozzles'][0]['lpm'] == pytest.approx(q, rel=1e-6)


# ── 근거가 빈 자리는 L0 ─────────────────────────────────────────────────────

def _two_pipes(tail_dia=None, head_dia=50, flow=1_200.0):
    return _net([_pipe('main', (0, 0), (50, 0), dia=head_dia), _pipe('tail', (50, 0), (100, 0), dia=tail_dia)],
                [WELL, PUMP], [_em('a', 30, 0, flow), _em('b', 90, 0, flow)])


def test_partial_diameters_give_a_partial_flow_upper_bound():
    out = _evaluate(_two_pipes(), flow=1_200.0)
    assert out['level'] == H.LEVEL_PARTIAL and out['reasons'] == []
    assert [m['pipe'] for m in out['missing']] == ['tail']
    assert out['excluded'] == out['missing']
    assert out['excluded_ratio'] == pytest.approx(0.444, abs=0.01)
    assert out['coverage']['ratio'] == pytest.approx(0.556, abs=0.01)
    assert {H.A_DIAMETER_EXCLUDED, H.A_FLOW_UPPER_BOUND} <= set(out['assumptions'])
    assert out['summary'] is not None


def test_partial_pump_flow_is_never_below_the_fully_sized_value():
    full = _evaluate(_two_pipes(tail_dia=16), flow=1_200.0)       # 가는 관을 채우면 손실이 생긴다
    part = _evaluate(_two_pipes(tail_dia=None), flow=1_200.0)
    assert full['level'] == H.LEVEL_L1 and part['level'] == H.LEVEL_PARTIAL
    # 압력은 노즐마다 방향이 다르다(유량이 늘면 펌프 양정이 내려간다) — 상한이 보장되는 것은 펌프 유량이다.
    assert part['summary']['pump_lpm'] >= full['summary']['pump_lpm']
    assert H.A_DIAMETER_EXCLUDED not in full['assumptions'] and 'excluded' not in full


def test_fully_sized_result_is_unchanged_by_the_partial_path():
    out = _evaluate(_two_pipes(tail_dia=25))
    assert out['level'] == H.LEVEL_L1 and out['missing'] == [] and 'excluded_ratio' not in out


def test_no_diameter_at_all_stays_l0():
    net = _net([_pipe('main', (0, 0), (100, 0))], [WELL, PUMP], [_em('a', 50, 0), _em('b', 90, 0)])
    out = _evaluate(net)
    assert out['level'] == H.LEVEL_L0 and H.PIPE_DIAMETER_UNKNOWN in out['reasons']
    assert out['summary'] is None and out['coverage']['ratio'] == 0.0


def test_only_pipes_on_the_path_of_the_open_nozzles_count():
    """같은 회로에서 열린 노즐이 다르면 경로 위 배관만 센다 — 빈 가지가 경로 밖이면 전부 L1."""
    net = _net([_pipe('main', (0, 0), (100, 0), dia=50), _pipe('br', (50, 0), (50, 40), sub='branch')],
               [WELL, PUMP], [_em('near', 30, 0), _em('far', 50, 30)])
    ems = {e.id: e for e in net.emitters}
    flows = {'near': 70.0, 'far': 70.0}
    bars = {'near': 2.0, 'far': 2.0}
    on_main = H.evaluate(net, 0, [ems['near']], flows, bars)
    both = H.evaluate(net, 0, list(ems.values()), flows, bars)
    assert on_main['level'] == H.LEVEL_L1 and on_main['missing'] == []
    assert both['level'] == H.LEVEL_PARTIAL and [m['pipe'] for m in both['missing']] == ['br']


def test_partial_still_warns_when_the_source_is_too_small():
    net = _net([_pipe('main', (0, 0), (300, 0), dia=50), _pipe('x', (300, 0), (320, 0))],
               [_well(290.0), PUMP],
               [_em('n%d' % i, 20 + i * 10, 0, 6_000.0) for i in range(25)] + [_em('e', 315, 0, 6_000.0)])
    out = _evaluate(net, flow=6_000.0)
    assert out['level'] == H.LEVEL_PARTIAL and out['warnings'] == [H.W_SOURCE_OVER_DEMAND]


def test_pipe_with_no_nozzle_below_does_not_need_a_diameter():
    net = _net([_pipe('main', (0, 0), (50, 0), dia=50), _pipe('dead', (50, 0), (100, 0))],
               [WELL, PUMP], [_em('a', 30, 0)])
    out = _evaluate(net)
    assert out['level'] == H.LEVEL_L1


def test_no_pump_is_l0():
    out = _evaluate(_line_net(pump=None))
    assert out['level'] == H.LEVEL_L0 and H.NO_PUMP in out['reasons']


def test_pump_without_head_is_l0():
    pump = _part('pump', 'pump', 0, 0, rated_lpm=285.0)
    out = _evaluate(_line_net(pump=pump))
    assert out['level'] == H.LEVEL_L0 and H.PUMP_CURVE_UNKNOWN in out['reasons']


def test_nozzle_without_reference_pressure_is_l0():
    out = _evaluate(_line_net(), bar=None)
    assert out['level'] == H.LEVEL_L0 and H.NOZZLE_PRESSURE_UNKNOWN in out['reasons']
    assert out['nozzle_pressure_unknown'] == 3


def test_nozzle_without_flow_is_l0():
    out = _evaluate(_line_net(), flow=None)
    assert out['level'] == H.LEVEL_L0 and H.NOZZLE_FLOW_UNKNOWN in out['reasons']


def test_loop_is_l0():
    pipes = [_pipe('a', (0, 0), (50, 0), dia=50), _pipe('b', (50, 0), (50, 50), dia=50),
             _pipe('c', (50, 50), (0, 50), dia=50), _pipe('d', (0, 50), (0, 0), dia=50)]
    net = _net(pipes, [WELL, PUMP], [_em('a', 25, 0)])
    out = _evaluate(net)
    assert H.NETWORK_LOOP in out['reasons'] and out['level'] == H.LEVEL_L0


def test_no_open_nozzle_is_l0():
    net = _line_net()
    out = H.evaluate(net, 0, [], {}, {})
    assert out['level'] == H.LEVEL_L0 and H.NO_OPEN_NOZZLE in out['reasons']


def test_assumptions_are_written_down():
    out = _evaluate(_line_net())
    assert {H.A_PUMP_SHUTOFF, H.A_ELEVATION_FLAT, H.A_HW_C_DEFAULT,
            H.A_SUCTION_IGNORED, H.A_MINOR_IGNORED} <= set(out['assumptions'])


def test_elevation_lowers_the_pressure_at_a_high_nozzle():
    net = _line_net(dia=50)
    flat = _evaluate(net)['summary']['bar_min']
    high = _evaluate(net, elevation=lambda node: 10.0 if node != ('pump',) and
                     isinstance(node[0], str) else 0.0)
    assert 'elevation-flat' not in high['assumptions']
    assert high['summary']['bar_min'] < flat


def test_material_sets_the_hw_coefficient():
    assert H._material_c('PE') == (150.0, False)
    assert H._material_c('steel') == (120.0, False)
    assert H._material_c(None) == (H.DEFAULT_C, True)
    assert H._material_c('unknown') == (H.DEFAULT_C, True)


def test_pipe_ratings_carry_the_diameter_into_the_graph():
    from aot.functions.utils.water_net import adapters
    feats = [{'type': 'Feature', 'geometry': {'type': 'LineString',
                                              'coordinates': [[128.0, 35.0], [128.001, 35.0]]},
              'properties': {'sub_type': 'pipe_main', 'node_id': 'p1', 'diameter_mm': 50}},
             {'type': 'Feature', 'geometry': {'type': 'LineString',
                                              'coordinates': [[128.001, 35.0], [128.002, 35.0]]},
              'properties': {'sub_type': 'pipe_main', 'node_id': 'p2'}}]
    net = adapters.from_map_features(feats)
    dia = {p.id: p.diameter_mm for p in net.pipes}
    assert dia == {'p1': 50.0, 'p2': None}


# ── EPANET 검산 ─────────────────────────────────────────────────────────────


def test_matches_epanet_on_a_lateral():
    """같은 관·노즐·펌프를 EPANET 으로 풀어 작동점을 맞춘다. 노즐은 EPANET 방출계수(q = C·√P)로 옮긴다."""
    wntr = pytest.importorskip('wntr', reason='EPANET 검산은 wntr 가 있을 때만')
    flow_lph, bar, dia = 6_000.0, 2.0, 40.0
    net = _net([_pipe('main', (0, 0), (300, 0), dia=dia)], [WELL, PUMP],
               [_em('n%d' % i, 100 * (i + 1), 0, flow_lph) for i in range(3)])
    tree, pump = _tree(net, flow=flow_lph, bar=bar)
    mine = H.operating_point(tree, pump)
    k_lpm = tree.nozzles[0].k                                   # L/min per √m

    wn = wntr.network.WaterNetworkModel()
    wn.options.hydraulic.headloss = 'H-W'
    wn.add_reservoir('R', base_head=0.0)
    wn.add_junction('J0', base_demand=0.0, elevation=0.0)
    for i in range(3):
        wn.add_junction('J%d' % (i + 1), base_demand=0.0, elevation=0.0)
        wn.get_node('J%d' % (i + 1)).emitter_coefficient = k_lpm / 60000.0
    qr = 285 / 60000.0
    wn.add_curve('pc', 'HEAD', [(0.0, 36 * 1.33), (qr, 36.0), (qr * math.sqrt(1.33 / 0.33), 0.0)])
    wn.add_pump('P', 'R', 'J0', pump_type='HEAD', pump_parameter='pc')
    for i in range(3):
        wn.add_pipe('L%d' % i, 'J%d' % i, 'J%d' % (i + 1), length=100.0, diameter=dia / 1000.0,
                    roughness=150.0, minor_loss=0.0)
    res = wntr.sim.EpanetSimulator(wn).run_sim()
    epanet_lpm = abs(float(res.link['flowrate']['P'].iloc[-1])) * 60000.0
    epanet_end_m = float(res.node['pressure']['J3'].iloc[-1])
    ours_end_m = [n['bar'] for n in mine['nozzles'] if n['id'] == 'n2'][0] * H.M_PER_BAR
    assert mine['pump']['lpm'] == pytest.approx(epanet_lpm, rel=0.02)
    assert ours_end_m == pytest.approx(epanet_end_m, rel=0.02)


# ── 수원 용량 ───────────────────────────────────────────────────────────────

def _well(cap):
    meta = {} if cap is None else {'max_lpm': cap}
    return _part('well', 'source_well', 0, 0, **meta)


def _many(well):
    return _net([_pipe('main', (0, 0), (300, 0), dia=50)], [well, PUMP],
                [_em('n%d' % i, 20 + i * 10, 0, 6_000.0) for i in range(25)])


def test_pump_flow_above_the_source_limit_is_warned_not_resolved():
    out = _evaluate(_many(_well(290.0)), flow=6_000.0)
    assert out['level'] == H.LEVEL_L1 and out['summary']['pump_lpm'] > 290.0
    assert out['warnings'] == [H.W_SOURCE_OVER_DEMAND]
    assert out['source']['max_lpm'] == 290.0
    assert out['source']['ratio'] == pytest.approx(290.0 / out['summary']['pump_lpm'], abs=0.001)


def test_reservoir_is_a_source_like_the_well():
    res = _part('res', 'source_reservoir', 0, 0, max_lpm=290.0, base_height_m=12.0)
    out = _evaluate(_many(res), flow=6_000.0)
    assert out['level'] == H.LEVEL_L1
    assert out['warnings'] == [H.W_SOURCE_OVER_DEMAND]
    assert out['source']['max_lpm'] == 290.0


def test_flow_within_the_source_limit_has_no_warning():
    out = _evaluate(_many(_well(1000.0)), flow=6_000.0)
    assert out['warnings'] == [] and out['source']['over'] is False


def test_unknown_source_limit_is_not_invented():
    out = _evaluate(_many(_well(None)), flow=6_000.0)
    assert out['warnings'] == [] and out['source']['max_lpm'] is None


def test_tank_makes_the_source_limit_moot():
    net = _net([_pipe('main', (0, 0), (300, 0), dia=50)],
               [_well(10.0), _part('tank', 'tank', 0, 0, capacity_l=5000), PUMP],
               [_em('n%d' % i, 20 + i * 10, 0, 6_000.0) for i in range(25)])
    out = _evaluate(net, flow=6_000.0)
    assert out['warnings'] == [] and out['source']['max_lpm'] is None


def test_l0_has_no_source_verdict():
    out = _evaluate(_line_net(dia=None))
    assert out['level'] == H.LEVEL_L0 and out['source'] is None and out['warnings'] == []
