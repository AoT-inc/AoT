"""디자인 정보와 같은 규칙으로 토출 수를 센다 — 지도 설비 요약(_extract_map_equipment).

실제 김제 3포장 모양: 대지(3포장) 아래 구역 3-1·3-2, 노즐은 구역에 속하고
대지 소유(parent_node_id=대지)로 적힌 노즐이 구역 안에 하나 있다."""
from types import SimpleNamespace as NS
import unittest

from aot.tools.aot_data_tool_service import AoTDataToolService as S


def _poly(nid, name, typ, x0):
    ring = [[x0, 0], [x0, 1], [x0 + 1, 1], [x0 + 1, 0], [x0, 0]]
    return NS(type=typ, geo_id='m', feature={
        'type': 'Feature', 'geometry': {'type': 'Polygon', 'coordinates': [ring]},
        'properties': {'node_id': nid, 'name': name, 'aot_type': typ}})


def _spr(i, parent, zone):
    return {'type': 'Feature', 'geometry': {'type': 'Point', 'coordinates': [0.5, 0.5]},
            'properties': {'sub_type': 'sprinkler_coverage', 'node_id': 'c%s' % i,
                           'parent_node_id': parent, 'zone_id': zone, 'flow': 850,
                           'is_circle': True}}


def _drip(parent, length_deg, interval):
    return {'type': 'Feature', 'geometry': {'type': 'LineString',
            'coordinates': [[0, 0], [length_deg, 0]]},
            'properties': {'sub_type': 'pipe_branch', 'parent_node_id': parent,
                           'is_drip': True, 'drip_config': {'interval': interval, 'flow': 2}}}


def _shapes(feats):
    return [_poly('S', '3포장', 'site', 0), _poly('Z1', '3-1', 'zone', 0),
            _poly('Z2', '3-2', 'zone', 1),
            NS(type='equipment_collection', geo_id='m',
               feature={'type': 'FeatureCollection', 'features': feats})]


class DesignInfoEmitters(unittest.TestCase):
    def _rows(self, feats):
        res = S._extract_map_equipment(_shapes(feats))
        return {r['area']: r for r in res['irrigation']}

    def test_site_owned_nozzle_inside_zone_counts_in_the_zone(self):
        feats = [_spr(i, 'Z1', 'Z1') for i in range(52)] + \
                [_spr(100 + i, 'Z2', 'Z2') for i in range(59)] + [_spr(999, 'S', 'Z1')]
        rows = self._rows(feats)
        self.assertEqual(rows['3-1']['sprinklers'], 53)
        self.assertEqual(rows['3-2']['sprinklers'], 59)
        self.assertNotIn('3포장', rows)

    def test_zone_sum_equals_site_total_with_descendants(self):
        feats = [_spr(i, 'Z1', 'Z1') for i in range(52)] + \
                [_spr(100 + i, 'Z2', 'Z2') for i in range(59)] + [_spr(999, 'S', 'Z1')]
        res = S._extract_map_equipment(_shapes(feats), area_name='3포장',
                                       extra_area_node_ids={'Z1', 'Z2'})
        self.assertEqual(sum(r['sprinklers'] for r in res['irrigation']), 112)
        self.assertEqual(sum(r['sprinkler_flow_lph'] for r in res['irrigation']), 112 * 850)

    def test_site_row_keeps_nozzle_without_zone(self):
        rows = self._rows([_spr(1, 'S', None)])
        self.assertEqual(rows['3포장']['sprinklers'], 1)

    def test_drip_counted_apart_from_sprinklers(self):
        rows = self._rows([_spr(1, 'Z1', 'Z1'), _drip('Z1', 0.0009, 1.0)])  # ≈100 m
        r = rows['3-1']
        self.assertEqual(r['sprinklers'], 1)
        self.assertGreater(r['drip_emitters'], 90)
        self.assertEqual(r['method'], 'mixed')
