# coding=utf-8
"""
관수 물길 해석 — 노즐의 임자를 정하는 규칙 테스트.

레이어와 밸브가 둘 다 Output 을 가질 수 있다. 규칙은 하나다: 밸브는 자기가
선 자리에서 하류로 뻗은 구간을 맡고, 어떤 밸브도 맡지 않은 노즐만 레이어
Output(회로 공급) 몫이다. 노즐 하나는 정확히 한 액추에이터에만 속한다.

2026-08-25 이전에는 레이어에 레이어 노즐 전체를, 밸브에도 (붙은 배관에
노즐이 없으면) 레이어 노즐 전체를 붙여서 같은 물이 두 번 등록됐다.

배치도 (xz 평면, y=2):

      z=0   라이저(바닥→2m) ── 주배관 ────────────────────────────▶ x
             x=0            V_main(x=1)      T(x=5)        T(x=9)
                              │                │             │
      주배관 위 노즐:      n_main(x=3)         │             │
                                          지관A(z+)      지관B(z+)
                                          V_zone(z=1)    (밸브 없음)
                                          n_a1(z=3)      n_b1(z=3)
                                          n_a2(z=5)

  기대:
    n_main  → V_main (주배관 상류에 V_main 만 있다)
    n_a1/a2 → V_zone (더 가까운 상류 밸브가 V_zone. V_main 이 더 위에 있어도
                      가장 가까운 하나만 임자다 = 중첩)
    n_b1    → V_main (지관B 에는 밸브가 없으니 상류의 V_main 까지 올라간다)
  레이어 몫: 없음 (모든 노즐이 V_main 아래에 있다)
"""

from aot.aot_flask.geo.irrigation_nozzles import nozzles_by_actuator
from aot.aot_flask.geo.irrigation_topology import resolve_nozzle_owners

H = 2.0


def _pipe(pid, pts, sub_type='branch', vertical=False):
    segs = [{'from': list(pts[i]), 'to': list(pts[i + 1])}
            for i in range(len(pts) - 1)]
    return {'kind': 'irrigation_pipe', 'id': pid, 'layer_id': 'L1',
            'sub_type': sub_type, 'is_vertical': vertical, 'segments': segs}


def _dev(did, pipe_id, x, z, sub_type='sprinkler'):
    return {'kind': 'irrigation_device', 'id': did, 'layer_id': 'L1',
            'pipe_id': pipe_id, 'sub_type': sub_type,
            'orientation': 'down', 'flow_lph': 850.0, 'radius_m': 2.0,
            'position': {'x': x, 'y': H, 'z': z}}


def _valve(vid, pipe_id, x, z, actuator_id=None):
    return {'kind': 'irrigation_valve', 'id': vid, 'layer_id': 'L1',
            'pipe_id': pipe_id, 'valve_type': 'on_off',
            'actuator_id': actuator_id,
            'position': {'x': x, 'y': H, 'z': z}}


def _layout(layer_actuator=None, main_actuator=None, zone_actuator=None):
    return [
        {'kind': 'irrigation_layer', 'id': 'L1', 'height_m': H,
         'actuator_id': layer_actuator, 'position': {'x': 5, 'y': H, 'z': 5}},
        _pipe('riser', [(0, 0, 0), (0, H, 0)], vertical=True),
        _pipe('main', [(0, H, 0), (12, H, 0)], sub_type='main'),
        _pipe('branchA', [(5, H, 0), (5, H, 6)]),
        _pipe('branchB', [(9, H, 0), (9, H, 6)]),
        _valve('V_main', 'main', 1, 0, main_actuator),
        _valve('V_zone', 'branchA', 5, 1, zone_actuator),
        _dev('n_main', 'main', 3, 0),
        _dev('n_a1', 'branchA', 5, 3),
        _dev('n_a2', 'branchA', 5, 5),
        _dev('n_b1', 'branchB', 9, 3),
    ]


def _owner_names(fittings):
    by_valve, by_layer = resolve_nozzle_owners(fittings)
    out = {}
    for vid, devs in by_valve.items():
        for d in devs:
            out[d['id']] = vid
    for lid, devs in by_layer.items():
        for d in devs:
            out[d['id']] = lid
    return out


class TestNozzleOwnership:
    def test_nearest_upstream_valve_wins(self):
        owners = _owner_names(_layout())
        assert owners['n_main'] == 'V_main'
        assert owners['n_a1'] == 'V_zone'
        assert owners['n_a2'] == 'V_zone'
        assert owners['n_b1'] == 'V_main'

    def test_every_nozzle_has_exactly_one_owner(self):
        by_valve, by_layer = resolve_nozzle_owners(_layout())
        seen = [d['id'] for devs in by_valve.values() for d in devs]
        seen += [d['id'] for devs in by_layer.values() for d in devs]
        assert sorted(seen) == ['n_a1', 'n_a2', 'n_b1', 'n_main']
        assert len(seen) == len(set(seen))

    def test_nozzle_above_every_valve_falls_to_the_layer(self):
        # 주배관 x=0.5 는 V_main(x=1) 보다 상류다 — 어떤 밸브도 맡지 않으므로
        # 회로 공급(레이어) 몫이 된다.
        fittings = _layout()
        fittings.append(_dev('n_supply', 'main', 0.5, 0))
        owners = _owner_names(fittings)
        assert owners['n_supply'] == 'L1'

    def test_layer_owns_everything_when_no_valve(self):
        fittings = [f for f in _layout() if f.get('kind') != 'irrigation_valve']
        by_valve, by_layer = resolve_nozzle_owners(fittings)
        assert by_valve == {}
        assert len(by_layer['L1']) == 4


class TestNozzlesByActuator:
    def test_layer_and_valve_outputs_do_not_double_count(self):
        fittings = _layout(layer_actuator='out_pump',
                           main_actuator='out_main',
                           zone_actuator='out_zone')
        # 공급 몫이 될 노즐 하나를 둔다 (V_main 상류)
        fittings.append(_dev('n_supply', 'main', 0.5, 0))
        by_actuator = nozzles_by_actuator(fittings)
        counts = {aid: s['count'] for aid, s in by_actuator.items()}
        assert counts == {'out_pump': 1, 'out_main': 2, 'out_zone': 2}
        assert sum(counts.values()) == 5   # 노즐 총수와 일치 = 중복 없음

    def test_valve_without_output_leaves_its_nozzles_unregistered(self):
        # 밸브가 맡은 구간에 Output 이 없으면 그 노즐은 어느 액추에이터에도
        # 잡히지 않는다. 공급(레이어)이 대신 삼키지 않는다 — 실제로 그 물을
        # 여는 장치가 등록돼 있지 않다는 사실이 드러나야 한다.
        fittings = _layout(layer_actuator='out_pump', main_actuator=None,
                           zone_actuator='out_zone')
        by_actuator = nozzles_by_actuator(fittings)
        assert 'out_pump' not in by_actuator      # 공급 몫 노즐이 없다
        assert by_actuator['out_zone']['count'] == 2


class TestPipeJunctions:
    """배관끼리 닿는 자리를 물길로 인정하는가.

    디자이너는 배관이 가로지르면 그 자리에 티를 꽂는다(mbT/bT/mT). 해석기가
    끝점이 얹힌 자리만 마디로 보면, 가로지르기만 한 주배관은 물길에서 섬으로
    남아 그 위의 구역밸브가 아무것도 못 맡는다.
    """

    def _crossed_mains(self, zone_actuator=None):
        # 주배관 A(동서) 와 주배관 B(남북) 가 (6, 0..) 에서 가로지른다.
        # B 위에는 교차점보다 하류에 구역밸브가 있다.
        return [
            {'kind': 'irrigation_layer', 'id': 'L1', 'height_m': H,
             'actuator_id': 'out_pump'},
            _pipe('riser', [(0, 0, 0), (0, H, 0)], vertical=True),
            _pipe('mainA', [(0, H, 0), (12, H, 0)], sub_type='main'),
            _pipe('mainB', [(6, H, -3), (6, H, 9)], sub_type='main'),
            _valve('V_zone', 'mainB', 6, 2, zone_actuator),
            _dev('n_far', 'mainB', 6, 6),
        ]

    def test_crossing_mains_are_one_network(self):
        owners = _owner_names(self._crossed_mains())
        # 교차가 마디로 잡히지 않으면 mainB 는 섬이 되고, n_far 는 상류 밸브를
        # 못 찾아 공급(L1) 몫으로 떨어진다.
        assert owners['n_far'] == 'V_zone'

    def test_crossing_mains_register_on_the_zone_output(self):
        by_actuator = nozzles_by_actuator(self._crossed_mains(zone_actuator='out_zone'))
        assert by_actuator['out_zone']['count'] == 1
        assert 'out_pump' not in by_actuator

    def test_island_network_still_orders_its_own_valves(self):
        # 아직 본관에 안 물린 배관 뭉치. 공급에서 닿지 않아도 그 안의 밸브는
        # 제 하류를 맡아야 한다 — 통째로 공급 몫이 되면 안 된다.
        fittings = [
            {'kind': 'irrigation_layer', 'id': 'L1', 'height_m': H,
             'actuator_id': 'out_pump'},
            _pipe('riser', [(0, 0, 0), (0, H, 0)], vertical=True),
            _pipe('mainA', [(0, H, 0), (5, H, 0)], sub_type='main'),
            _pipe('island', [(20, H, 20), (28, H, 20)], sub_type='main'),
            _valve('V_island', 'island', 21, 20, 'out_island'),
            _dev('n_island', 'island', 25, 20),
        ]
        owners = _owner_names(fittings)
        assert owners['n_island'] == 'V_island'
