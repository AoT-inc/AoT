# coding=utf-8
"""L0 유량 수지 — 값은 전부 손으로 셈했다. 식은 각 시험 주석에 적었다."""
import copy

import pytest

from aot.functions.utils.water_net import adapters as A
from aot.functions.utils.water_net import result as R
from aot.functions.utils.water_net.balance import (Circuit, Pump, Run, Source, Tank, energy_kwh,
                                                   pool_levels, solve)


def _solve(circuit, demands, runs, t0=0.0, t1=10000.0):
    return solve(circuit, demands, [Run(*r) for r in runs], t0, t1)


def _run_of(out, output_id):
    return next(r for r in out['runs'] if r['output_id'] == output_id)


# ── 완료 기준의 일곱 가지 ──────────────────────────────────────────────────

def test_demand_over_pump():
    # 수요 170 > 펌프 100, 600초. 설계 170×10=1700, 전달 100×10=1000, 비율 100/170.
    out = _solve(Circuit('c', [Pump('p', 100.0)]), {'v': 170.0}, [('v', 0, 600)])
    run = _run_of(out, 'v')
    assert run['design_l'] == pytest.approx(1700.0)
    assert run['delivered_l'] == pytest.approx(1000.0)
    assert run['ratio'] == pytest.approx(100.0 / 170.0)
    assert out['delivered_l'] == 1000.0 and out['demand_l'] == 1700.0
    assert R.PUMP_OVER_DEMAND in out['caveats'] and out['seconds'][R.PUMP_OVER_DEMAND] == 600


def test_two_valves_overlap_only_where_they_overlap():
    # A 60 L/min 0~600, B 60 L/min 300~900, 펌프 90.
    # 0~300: Q=60 → A 300 L.  300~600: Qd=120, Q=90, 각 45 → 225 L 씩.  600~900: B 300 L.
    # A = 300+225 = 525, B = 225+300 = 525. 일 합계 초로는 이 값이 안 나온다.
    out = _solve(Circuit('c', [Pump('p', 90.0)]), {'a': 60.0, 'b': 60.0},
                 [('a', 0, 600), ('b', 300, 900)])
    assert _run_of(out, 'a')['delivered_l'] == pytest.approx(525.0)
    assert _run_of(out, 'b')['delivered_l'] == pytest.approx(525.0)
    assert out['seconds'][R.PUMP_OVER_DEMAND] == 300


def test_shares_follow_demand_not_valve_count():
    # 수요 30·90, 펌프 60. Q=60 을 1:3 으로 → 15·45 L/min. 60초면 15·45 L.
    out = _solve(Circuit('c', [Pump('p', 60.0)]), {'a': 30.0, 'b': 90.0},
                 [('a', 0, 60), ('b', 0, 60)])
    assert _run_of(out, 'a')['delivered_l'] == pytest.approx(15.0)
    assert _run_of(out, 'b')['delivered_l'] == pytest.approx(45.0)


def test_source_smaller_than_pump():
    # 펌프 200, 수원 50, 수요 100. Qs=min(200,50)=50. 600초 → 500 L.
    out = _solve(Circuit('c', [Pump('p', 200.0)], [Source('s', 50.0)]), {'v': 100.0},
                 [('v', 0, 600)])
    assert _run_of(out, 'v')['delivered_l'] == pytest.approx(500.0)
    assert R.SOURCE_OVER_DEMAND in out['caveats'] and R.PUMP_OVER_DEMAND not in out['caveats']


def test_pump_off_delivers_nothing():
    # 밸브 0~600, 펌프 300~600 만 켜짐. 앞 300초는 0, 뒤 300초만 50 L/min → 250 L.
    out = _solve(Circuit('c', [Pump('p', 100.0, runs=[(300.0, 600.0)])]), {'v': 50.0},
                 [('v', 0, 600)])
    assert _run_of(out, 'v')['delivered_l'] == pytest.approx(250.0)
    assert out['seconds'][R.VALVE_WITHOUT_PUMP] == 300
    assert R.PUMP_DEAD_HEAD not in out['caveats']


def test_pump_running_with_no_valve_open():
    # 펌프 0~300 + 밸브 100~200. 나머지 200초가 공회전. 전력 2 kW × 300/3600 h = 0.1667 kWh.
    out = _solve(Circuit('c', [Pump('p', 100.0, power_kw=2.0, runs=[(0.0, 300.0)])]), {'v': 50.0},
                 [('v', 100, 200)])
    assert out['seconds'][R.PUMP_DEAD_HEAD] == 200
    assert out['pump']['kwh'] == pytest.approx(2.0 * 300 / 3600, abs=0.001)
    assert out['pump']['basis'] == R.BASIS_RATED


def test_tank_runs_dry_and_says_when():
    # 탱크 1000 L, 유입 0, Q=100 L/min → 600초에 바닥. 900초 실행해도 전달은 1000 L.
    out = _solve(Circuit('c', [Pump('p', 100.0)], [], [Tank('t', 5000.0, [(0.0, 1000.0)])]),
                 {'v': 100.0}, [('v', 0, 900)])
    assert _run_of(out, 'v')['delivered_l'] == pytest.approx(1000.0)
    assert out['tank']['empty_at'] == pytest.approx(600.0)
    assert out['tank']['start_l'] == 1000.0 and out['tank']['end_l'] == 0.0
    assert R.TANK_EMPTY in out['caveats']


def test_supply_equals_delivered_plus_tank_change():
    # 탱크 1000 L, 유입 30, Q=100: 순감 70 L/min → 857.14초에 바닥, 그 뒤 Q=30.
    # 1200초: 전달 = 100×857.14/60 + 30×342.86/60 = 1428.57 + 171.43 = 1600.
    # 유입 = 30×20 = 600.  600 = 1600 + (0 − 1000).
    out = _solve(Circuit('c', [Pump('p', 200.0)], [Source('s', 30.0)],
                         [Tank('t', 5000.0, [(0.0, 1000.0)])]), {'v': 100.0}, [('v', 0, 1200)])
    tank = out['tank']
    assert out['delivered_l'] == pytest.approx(1600.0, abs=0.01)
    assert tank['inflow_l'] == pytest.approx(600.0, abs=0.01)
    assert tank['inflow_l'] == pytest.approx(
        out['delivered_l'] + tank['end_l'] - tank['start_l'], abs=0.01)
    assert tank['empty_at'] == pytest.approx(1000.0 / 70.0 * 60.0)


# ── 탱크 ───────────────────────────────────────────────────────────────────

def test_balance_holds_when_the_tank_stops_at_full():
    # 990 L, 용량 1000, 유입 100, Q=50: 12초에 가득 → 그 뒤 유입은 Q 만큼만.
    # 60초 유입 = 100×0.2 + 50×0.8 = 60. 전달 50. 변화 +10. 60 = 50 + 10.
    out = _solve(Circuit('c', [Pump('p', 100.0)], [Source('s', 100.0)],
                         [Tank('t', 1000.0, [(0.0, 990.0)])]), {'v': 50.0}, [('v', 0, 60)])
    assert out['tank']['end_l'] == pytest.approx(1000.0)
    assert out['tank']['inflow_l'] == pytest.approx(60.0)
    assert out['delivered_l'] == pytest.approx(50.0)


def test_measured_level_corrects_the_tank():
    # 1000 L 시작, Q=60 → 60초 뒤 예측 940. 그 시각 측정 900 이면 맞춘다(보정 −40).
    # 다음 60초 뒤 840. 유입 0 = 전달 120 + (840 − 1000) − (−40).
    out = _solve(Circuit('c', [Pump('p', 100.0)], [],
                         [Tank('t', 5000.0, [(0.0, 1000.0), (60.0, 900.0)])]),
                 {'v': 60.0}, [('v', 0, 120)])
    tank = out['tank']
    assert tank['end_l'] == pytest.approx(840.0) and tank['adjust_l'] == pytest.approx(-40.0)
    assert tank['inflow_l'] == pytest.approx(
        out['delivered_l'] + tank['end_l'] - tank['start_l'] - tank['adjust_l'])


def test_tank_without_a_reading_is_not_assumed_full():
    # 수위가 없으면 수지를 생략한다. 수원 10 L/min 은 탱크 뒤라 한계가 아니다(펌프만 한계).
    out = _solve(Circuit('c', [Pump('p', 100.0)], [Source('s', 10.0)], [Tank('t', 5000.0)]),
                 {'v': 80.0}, [('v', 0, 60)])
    assert out['tank'] is None and R.TANK_LEVEL_UNKNOWN in out['caveats']
    assert _run_of(out, 'v')['delivered_l'] == pytest.approx(80.0)


def test_level_after_the_run_starts_opens_the_balance_late():
    # 첫 측정이 60초에 온다. 그 전은 모르니 수지에 넣지 않는다.
    out = _solve(Circuit('c', [Pump('p', 100.0)], [], [Tank('t', 5000.0, [(60.0, 500.0)])]),
                 {'v': 60.0}, [('v', 0, 120)])
    assert out['tank']['start_l'] == 500.0 and out['tank']['end_l'] == pytest.approx(440.0)
    assert out['delivered_l'] == pytest.approx(120.0)


def test_tanks_pool_only_after_every_tank_has_a_reading():
    levels = pool_levels([Tank('a', 100.0, [(0.0, 10.0), (20.0, 12.0)]), Tank('b', 100.0, [(10.0, 5.0)])])
    assert levels == [(10.0, 15.0), (20.0, 17.0)]
    assert pool_levels([Tank('a', 100.0, [(0.0, 10.0)]), Tank('b', 100.0)]) is None


# ── 빈 칸을 지어내지 않는다 ────────────────────────────────────────────────

def test_blank_pump_rating_means_no_limit():
    out = _solve(Circuit('c', [Pump('p')]), {'v': 170.0}, [('v', 0, 600)])
    assert _run_of(out, 'v')['ratio'] == 1.0
    assert R.SUPPLY_UNKNOWN in out['caveats'] and R.PUMP_OVER_DEMAND not in out['caveats']


def test_blank_source_is_unlimited_and_the_pump_still_limits():
    out = _solve(Circuit('c', [Pump('p', 100.0)], [Source('s')]), {'v': 200.0}, [('v', 0, 60)])
    assert out['delivered_l'] == pytest.approx(100.0)
    assert R.SUPPLY_UNKNOWN not in out['caveats']


def test_tap_with_a_known_limit_needs_no_pump():
    # 펌프 없는 상수도. 수원 허용이 있으면 공급을 아는 것이다.
    out = _solve(Circuit('c', [], [Source('tap', 40.0)]), {'v': 100.0}, [('v', 0, 60)])
    assert out['delivered_l'] == pytest.approx(40.0) and out['pump'] is None
    assert R.SUPPLY_UNKNOWN not in out['caveats']


def test_no_limit_at_all_is_supply_unknown():
    out = _solve(Circuit('c', [], [Source('tap')]), {'v': 100.0}, [('v', 0, 60)])
    assert out['delivered_l'] == pytest.approx(100.0) and R.SUPPLY_UNKNOWN in out['caveats']


def test_unlinked_pump_gives_no_state_verdict():
    # 켜짐·꺼짐을 모르면 밸브가 열린 동안 돈다고 친다. 전력도 그 시간으로 센다.
    out = _solve(Circuit('c', [Pump('p', 100.0, power_kw=3.6)]), {'v': 50.0},
                 [('v', 100, 200)])
    assert out['caveats'] == [R.PUMP_STATE_UNKNOWN]
    assert out['pump']['kwh'] == pytest.approx(0.1)
    assert out['pump']['hours'] == pytest.approx(100 / 3600, abs=0.001)


def test_quiet_circuit_says_nothing():
    out = _solve(Circuit('c', [Pump('p', power_kw=1.0)], [], [Tank('t')]), {'v': 50.0}, [])
    assert out['caveats'] == [] and out['runs'] == [] and out['delivered_ratio'] is None


# ── 회로 ───────────────────────────────────────────────────────────────────

def test_valve_without_a_polygon_still_counts_as_open():
    # 담당 폴리곤이 없는 밸브 — 수요는 0 이지만 열렸으니 공회전이 아니다.
    out = _solve(Circuit('c', [Pump('p', 100.0, runs=[(0.0, 100.0)])]), {'v': 0.0}, [('v', 0, 100)])
    assert R.PUMP_DEAD_HEAD not in out['caveats']


def test_two_pumps_are_parallel_while_both_run():
    # 50 + 70 = 120. 뒤 60초는 한 대만 돌아 50.
    out = _solve(Circuit('c', [Pump('a', 50.0, runs=[(0.0, 120.0)]),
                               Pump('b', 70.0, runs=[(0.0, 60.0)])]),
                 {'v': 200.0}, [('v', 0, 120)])
    assert out['delivered_l'] == pytest.approx(120.0 + 50.0)


def test_run_from_before_the_window_shares_the_pump_but_is_not_booked():
    # 앞 실행 −60~60 이 겹쳐 0~60 은 Qd=100, Q=50 → v 는 25 L/min.  60~120 은 50 L/min.
    # v 전달 = 25 + 50 = 75.
    out = _solve(Circuit('c', [Pump('p', 50.0)]), {'old': 50.0, 'v': 50.0},
                 [('old', -60, 60), ('v', 0, 120)])
    assert [r['output_id'] for r in out['runs']] == ['v']
    assert _run_of(out, 'v')['delivered_l'] == pytest.approx(75.0)


def test_run_crossing_the_window_end_is_solved_to_its_end():
    # 일지는 사건을 켠 시각에 싣는다. 구간을 넘겨 돌아도 그 실행은 끝까지 센다.
    out = _solve(Circuit('c', [Pump('p', 30.0)]), {'v': 60.0}, [('v', 0, 120)], t1=60.0)
    assert _run_of(out, 'v')['delivered_l'] == pytest.approx(60.0)


def test_same_output_twice_is_not_double_demand():
    # 같은 Output 의 겹친 사건 — 수요는 한 번만 든다.
    out = _solve(Circuit('c', [Pump('p', 100.0)]), {'v': 80.0}, [('v', 0, 60), ('v', 30, 90)])
    assert all(r['ratio'] == 1.0 for r in out['runs'])


# ── 전력 ───────────────────────────────────────────────────────────────────

def test_measured_power_wins_and_says_so():
    out = _solve(Circuit('c', [Pump('p', 100.0, power_kw=9.0, runs=[(0.0, 3600.0)],
                                    measured_kwh=4.5)]), {'v': 50.0}, [('v', 0, 3600)])
    assert out['pump']['kwh'] == 4.5 and out['pump']['basis'] == R.BASIS_MEASURED


def test_energy_from_watts_and_from_a_meter():
    # 1000 W 로 1시간 → 1 kWh. 누적계는 나중 − 처음.
    assert energy_kwh([(0, 1000.0), (1800, 1000.0), (3600, 1000.0)], 'W') == pytest.approx(1.0)
    assert energy_kwh([(0, 10.0), (3600, 12.5)], 'kWh') == pytest.approx(2.5)


def test_energy_does_not_invent_a_value():
    assert energy_kwh([(0, 12.5), (3600, 1.0)], 'kWh') is None   # 계량기 리셋
    assert energy_kwh([(0, 1.0)], 'W') is None


# ── 회로 해시 ──────────────────────────────────────────────────────────────

def _f(sub, coords, **props):
    props.update(sub_type=sub)
    kind = 'Point' if isinstance(coords[0], float) else 'LineString'
    return {'type': 'Feature', 'geometry': {'type': kind, 'coordinates': coords}, 'properties': props}


FEATURES = [
    _f('pipe_main', [[128.0, 35.0], [128.001, 35.0]], node_id='m'),
    _f('pipe_branch', [[128.0005, 35.0], [128.0005, 35.001]], node_id='b'),
    _f('pump', [128.0, 35.0], node_id='p', rated_lpm=100),
    _f('sprinkler_coverage', [128.0005, 35.0005], node_id='e', flow=600),
]


def _rev(features):
    return R.network_rev(A.from_map_features(features))


def test_rev_ignores_storage_order_and_line_direction():
    base = _rev(FEATURES)
    assert _rev(list(reversed(FEATURES))) == base
    flipped = copy.deepcopy(FEATURES)
    flipped[1]['geometry']['coordinates'].reverse()
    assert _rev(flipped) == base


def test_rev_ignores_generated_ids():
    # node_id 가 없는 배관은 저장 순번으로 이름을 얻는다. 해시는 그 영향을 받지 않는다.
    bare = copy.deepcopy(FEATURES)
    del bare[0]['properties']['node_id'], bare[1]['properties']['node_id']
    assert _rev(bare) == _rev(list(reversed(bare)))


@pytest.mark.parametrize('index, path, value', [
    (2, ('properties', 'rated_lpm'), 90),
    (3, ('properties', 'flow'), 500),
])
def test_rev_changes_with_ratings(index, path, value):
    changed = copy.deepcopy(FEATURES)
    changed[index][path[0]][path[1]] = value
    assert _rev(changed) != _rev(FEATURES)


def test_rev_changes_with_geometry():
    moved = copy.deepcopy(FEATURES)
    moved[1]['geometry']['coordinates'][1] = [128.0005, 35.002]
    assert _rev(moved) != _rev(FEATURES)


def test_rev_covers_only_the_circuits_asked_for():
    far = [_f('pipe_branch', [[129.0, 36.0], [129.001, 36.0]], node_id='far')]
    net = A.from_map_features(FEATURES + far)
    other = A.from_map_features(FEATURES + [_f('pipe_branch', [[129.0, 36.0], [129.002, 36.0]],
                                               node_id='far')])
    comp = net.component_id('p')
    assert R.network_rev(net, [comp]) == R.network_rev(other, [other.component_id('p')])


def test_every_verdict_is_in_the_contract():
    out = _solve(Circuit('c', [Pump('p', 10.0)]), {'v': 20.0}, [('v', 0, 60)])
    assert set(out['caveats']) <= set(R.CAVEATS)


def test_run_row_carries_design_and_delivered():
    # 170 L/min, 비율 0.5, 600초 설계 1700 L, 면적 100 m² → 8.5 mm.
    row = R.run_row('v', 0, 600, 170.0, 1700.0, 0.5, area_m2=100.0)
    assert row['delivered_lpm'] == 85.0 and row['litres'] == 850.0
    assert row['design_litres'] == 1700.0 and row['mm'] == 8.5 and row['basis'] == R.BASIS_DESIGN
