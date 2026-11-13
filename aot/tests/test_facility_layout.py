# coding=utf-8
"""facility_layout.py — 시설 모형 `층 → 덩어리 → 공간` (단계 F0). Flask·DB 없이 돈다."""
import copy
import json
import math
import os
import sys
import unittest

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), os.path.pardir, os.path.pardir)))

from aot.space import facility_layout as FL
from aot.space.facility_bays import build_fitting_bay_map, compute_bay_slices
from aot.space.facility_calc import compute_capacity

LEGACY_KEYS = ('floor_m2', 'envelope_m2', 'sidewall_m2', 'roof_m2', 'gable_m2', 'volume_m3')


def _fac(structure='single', bay_count=1, roof='arch', span=7, eave=2, ridge=4,
         length=30, spacing=0, bays=None, cover='vinyl_double'):
    return {
        'structure': structure, 'bay_count': bay_count, 'name': '시험',
        'geometry_3d': {'span_width_m': span, 'eave_height_m': eave, 'ridge_height_m': ridge,
                        'length_m': length, 'roof_type': roof, 'spacing_m': spacing},
        'envelope': {'layers': [{'role': 'outer', 'cover': cover}]},
        'bays': bays or [],
    }


def _totals(fac):
    layout = FL.layout_from_legacy(fac)
    assert FL.validate_layout(layout) == [], FL.validate_layout(layout)
    return layout, FL.compile_layout(layout)


def _rect(x0, x1, z0, z1):
    return [[x0, z0], [x1, z0], [x1, z1], [x0, z1]]


def _two_level():
    return {
        'schema': 1,
        'levels': [{'id': 'L1', 'name': '1층', 'elevation_m': 0, 'height_m': 4.0},
                   {'id': 'L2', 'name': '2층', 'elevation_m': 4.2, 'height_m': 3.0}],
        'blocks': [
            {'id': 'B1', 'level_id': 'L1', 'outline': _rect(0, 20, 0, 10), 'roof': {'type': 'flat'}},
            {'id': 'B2', 'level_id': 'L2', 'outline': _rect(0, 10, 0, 10), 'roof': {'type': 'flat'}},
        ],
        'spaces': [
            {'id': 'a', 'block_id': 'B1', 'name': '왼쪽', 'outline': _rect(0, 10, 0, 10)},
            {'id': 'b', 'block_id': 'B1', 'name': '오른쪽', 'outline': _rect(10, 20, 0, 10)},
            {'id': 'up', 'block_id': 'B2', 'name': '위'},
        ],
        'boundaries': [{'between': ['a', 'b'], 'type': 'curtain'}],
    }


class LegacyMatchesCalcTest(unittest.TestCase):
    """layout_from_legacy + compile_layout 합계는 compute_capacity 와 같다(알려진 차이 제외)."""

    def _assert_same(self, fac, skip=()):
        _, comp = _totals(fac)
        old = compute_capacity(copy.deepcopy(fac))
        for k in LEGACY_KEYS:
            if k in skip:
                continue
            self.assertAlmostEqual(comp['totals'][k], old[k], places=1, msg=k)

    def test_single_each_roof(self):
        for roof, ridge in (('arch', 4), ('gable', 5), ('gable2', 5), ('flat', 2)):
            with self.subTest(roof=roof):
                self._assert_same(_fac(roof=roof, ridge=ridge))

    def test_single_n_with_spacing(self):
        for n in (2, 5, 9):
            with self.subTest(n=n):
                self._assert_same(_fac(bay_count=n, spacing=1.5))

    def test_connected_only_gable_differs(self):
        for n in (1, 3, 6):
            with self.subTest(n=n):
                fac = _fac(structure='connected', bay_count=n, roof='gable', ridge=5)
                _, comp = _totals(fac)
                old = compute_capacity(fac)
                self._assert_same(fac, skip=('envelope_m2', 'gable_m2'))
                self.assertAlmostEqual(comp['totals']['gable_m2'], old['gable_m2'] * n, places=1)
                self.assertAlmostEqual(comp['totals']['envelope_m2'],
                                       old['envelope_m2'] + old['gable_m2'] * (n - 1), places=1)

    def test_glazing_opaque_cover_is_zero(self):
        _, comp = _totals(_fac(cover='sandwich_panel'))
        self.assertEqual(comp['totals']['glazing_m2'], 0)
        _, comp = _totals(_fac(cover='glass'))
        self.assertAlmostEqual(comp['totals']['glazing_m2'], comp['totals']['envelope_m2'], places=2)

    def test_empty_values_use_calc_defaults(self):
        layout = FL.layout_from_legacy({})
        self.assertEqual(FL.validate_layout(layout), [])
        comp = FL.compile_layout(layout)
        old = compute_capacity({})
        for k in LEGACY_KEYS:
            self.assertAlmostEqual(comp['totals'][k], old[k], places=1, msg=k)
        self.assertEqual(len(layout['spaces']), 1)
        self.assertEqual(FL.layout_from_legacy(None)['levels'][0]['height_m'], 2.0)

    def test_curved_roof_dims(self):
        layout = FL.layout_from_legacy(_fac(structure='connected', bay_count=3))
        b = layout['blocks'][0]
        self.assertEqual(b['roof']['runs'], 3)
        self.assertEqual(b['roof']['type'], 'arch')
        self.assertAlmostEqual(b['roof']['rise_m'], 2.0)


class StructureTest(unittest.TestCase):
    def test_connected_one_block_open_boundaries(self):
        layout = FL.layout_from_legacy(_fac(structure='connected', bay_count=4, span=6, length=40))
        self.assertEqual(len(layout['blocks']), 1)
        self.assertEqual(len(layout['spaces']), 4)
        self.assertEqual([b['type'] for b in layout['boundaries']], ['open'] * 3)
        comp = FL.compile_layout(layout)
        self.assertEqual(len(comp['boundaries']), 3)
        for bd in comp['boundaries']:
            self.assertAlmostEqual(bd['length_m'], 40.0)
            self.assertEqual(bd['type'], 'open')
        self.assertAlmostEqual(comp['totals']['interior_boundary_m2']['open'], 3 * 40 * 2.0, places=1)
        # 공간 합 = 합계
        for k in ('floor_m2', 'volume_m3', 'sidewall_m2', 'roof_m2', 'gable_m2', 'envelope_m2'):
            self.assertAlmostEqual(sum(s[k] for s in comp['spaces'].values()), comp['totals'][k], places=1, msg=k)
        # 가운데 구역은 긴 변의 외벽이 없고 양 끝벽(6 m x 2)만 있다. 끝 구역은 긴 변이 하나 더.
        self.assertAlmostEqual(comp['spaces']['bay_2']['sidewall_m2'], 2 * 6 * 2.0)
        self.assertAlmostEqual(comp['spaces']['bay_1']['sidewall_m2'], (2 * 6 + 40) * 2.0)

    def test_single_n_separate_blocks(self):
        layout = FL.layout_from_legacy(_fac(bay_count=3, span=7, spacing=2, length=20))
        self.assertEqual([b['id'] for b in layout['blocks']], ['B1', 'B2', 'B3'])
        self.assertEqual(layout['blocks'][1]['outline'][0][0], 9.0)
        self.assertEqual(layout['boundaries'], [])
        comp = FL.compile_layout(layout)
        self.assertEqual(comp['boundaries'], [])
        self.assertEqual(len(comp['spaces']), 3)

    def test_zones_over_detached_buildings(self):
        bays = [{'id': 'z1', 'bay_start': 1, 'bay_end': 3}, {'id': 'z2', 'bay_start': 4, 'bay_end': 6}]
        layout = FL.layout_from_legacy(_fac(bay_count=6, spacing=2.8, bays=bays))
        self.assertEqual([s['id'] for s in layout['spaces']], ['z1', 'z2'])
        self.assertEqual(layout['spaces'][0]['block_ids'], ['B1', 'B2', 'B3'])
        comp = FL.compile_layout(layout)
        self.assertAlmostEqual(comp['spaces']['z1']['floor_m2'], 3 * 7 * 30, places=1)
        self.assertEqual(comp['spaces']['z1']['block_id'], 'B1')

    def test_connected_zone_ranges(self):
        bays = [{'id': 'A', 'bay_start': 1, 'bay_end': 2}, {'id': 'B', 'bay_start': 3, 'bay_end': 6}]
        layout = FL.layout_from_legacy(_fac(structure='connected', bay_count=6, bays=bays))
        comp = FL.compile_layout(layout)
        self.assertAlmostEqual(comp['spaces']['A']['floor_m2'], 2 * 7 * 30, places=1)
        self.assertAlmostEqual(comp['spaces']['B']['floor_m2'], 4 * 7 * 30, places=1)

    def test_json_roundtrip(self):
        layout, comp = _totals(_fac(structure='connected', bay_count=2))
        self.assertEqual(json.loads(json.dumps(layout)), layout)
        json.dumps(comp)
        json.dumps(FL.footprint_points(layout, 5))


class MultiLevelTest(unittest.TestCase):
    def test_two_levels_totals(self):
        comp = FL.compile_layout(_two_level())
        t = comp['totals']
        self.assertAlmostEqual(t['floor_m2'], 300.0)
        self.assertAlmostEqual(t['sidewall_m2'], 60 * 4 + 40 * 3)       # 240 + 120
        self.assertAlmostEqual(t['roof_m2'], 100 + 100)                  # B1 은 B2 가 덮은 절반 제외
        self.assertAlmostEqual(t['envelope_m2'], 560.0)
        self.assertAlmostEqual(t['volume_m3'], 200 * 4 + 100 * 3)
        self.assertAlmostEqual(comp['blocks']['B1']['roof_exposed_fraction'], 0.5)
        self.assertEqual(comp['levels']['L2']['elevation_m'], 4.2)

    def test_declared_boundary_type_and_undeclared_wall(self):
        comp = FL.compile_layout(_two_level())
        self.assertEqual(len(comp['boundaries']), 1)
        self.assertEqual(comp['boundaries'][0]['type'], 'curtain')
        self.assertAlmostEqual(comp['boundaries'][0]['area_m2'], 10 * 4)
        lay = _two_level()
        lay['boundaries'] = []
        self.assertEqual(FL.compile_layout(lay)['boundaries'][0]['type'], 'wall')

    def test_void_reduces_floor_not_volume(self):
        lay = _two_level()
        lay['voids'] = [{'level_id': 'L2', 'outline': _rect(1, 3, 1, 4)}]
        comp = FL.compile_layout(lay)
        self.assertAlmostEqual(comp['totals']['floor_m2'], 300 - 6)
        self.assertAlmostEqual(comp['totals']['volume_m3'], 200 * 4 + 100 * 3)

    def test_l_shape_two_rects_share_wall(self):
        lay = {'schema': 1, 'levels': [{'id': 'L1', 'elevation_m': 0, 'height_m': 3}],
               'blocks': [{'id': 'B1', 'level_id': 'L1', 'outline': _rect(0, 10, 0, 20), 'roof': {'type': 'flat'}},
                          {'id': 'B2', 'level_id': 'L1', 'outline': _rect(10, 20, 0, 10), 'roof': {'type': 'flat'}}]}
        comp = FL.compile_layout(lay)
        self.assertAlmostEqual(comp['totals']['sidewall_m2'], (50 + 30) * 3)
        self.assertEqual(len(comp['spaces']), 2)                         # 암묵 공간
        self.assertEqual(comp['boundaries'][0]['type'], 'wall')

    def test_non_rect_flat_block(self):
        lay = {'schema': 1, 'levels': [{'id': 'L1', 'elevation_m': 0, 'height_m': 3}],
               'blocks': [{'id': 'B1', 'level_id': 'L1', 'roof': {'type': 'flat'},
                           'outline': [[0, 0], [24, 0], [24, 12], [12, 12], [12, 30], [0, 30]]}]}
        comp = FL.compile_layout(lay)
        area = 24 * 12 + 12 * 18
        self.assertAlmostEqual(comp['totals']['floor_m2'], area)
        self.assertAlmostEqual(comp['totals']['volume_m3'], area * 3)
        self.assertAlmostEqual(comp['totals']['sidewall_m2'], (24 + 12 + 12 + 18 + 12 + 30) * 3)

    def test_spans_double_height(self):
        lay = _two_level()
        lay['blocks'][0]['spans'] = 2
        comp = FL.compile_layout(lay)
        self.assertAlmostEqual(comp['blocks']['B1']['wall_height_m'], 7.2)
        self.assertEqual(FL.locate(lay, 5, 5.0, 5)['space_id'], 'a')


class AirZoneTest(unittest.TestCase):
    """F4 — 공기 구획과 덮개별 외피. 시설 표본 대신 손으로 셀 수 있는 합성 표본 3종.

    계산 근거(모두 m 단위, 평면 [x, z]):
      · 외벽 = 덩어리 둘레 중 같은 층의 다른 덩어리와 맞닿지 않은 길이 × 벽 높이.
      · 평지붕 노출 = 윗면 − 바로 위층 덩어리가 덮은 면적(공간별로 덮인 자리를 따진다).
      · 박공 지붕 둘레 = 2·√((폭/2)²+상승²)·용마루 길이, 단면 = 폭·상승/2, 체적 = 단면·길이.
      · 구획 = open 경계로 맞닿은 공간 + 슬래브 구멍으로 이어진 위·아래 공간.
      · UA = 외피 면적 × 덮개 U (샌드위치 0.45, 폴리카보네이트 3.0, 유리 5.8, 콘크리트 3.1).
    """

    def _zones(self, comp):
        return {frozenset(z['space_ids']): z for z in comp['air_zones']}

    # ── 표본 1: 2층 육묘동 ──
    # L1 높이 4 (0~4), L2 높이 3 (4.2~7.2). B1(L1) 0..20 × 0..10 샌드위치 패널, B2(L2) 0..10 × 0..10
    # 폴리카보네이트. 공간 a(B1 서쪽 10×10), b(B1 동쪽 10×10), up(B2 전체). a–b 는 open.
    def _nursery(self, void=True):
        lay = _two_level()
        lay['blocks'][0]['walls'] = {'cover': 'sandwich_panel'}
        lay['blocks'][1]['walls'] = {'cover': 'polycarbonate'}
        lay['boundaries'] = [{'between': ['a', 'b'], 'type': 'open'}]
        lay['voids'] = [{'level_id': 'L2', 'outline': _rect(1, 3, 1, 4)}] if void else []   # 6 m², a 와 up 위
        return lay

    def test_nursery_void_joins_all_three(self):
        comp = FL.compile_layout(self._nursery())
        self.assertEqual(len(comp['air_zones']), 1)
        z = comp['air_zones'][0]
        self.assertEqual(z['space_ids'], ['a', 'b', 'up'])
        self.assertEqual(z['level_ids'], ['L1', 'L2'])
        self.assertEqual(z['joined_by'], ['open', 'void'])
        self.assertAlmostEqual(z['floor_m2'], 100 + 100 + (100 - 6))        # 294
        self.assertAlmostEqual(z['volume_m3'], 100 * 4 + 100 * 4 + 100 * 3)  # 1100
        # a: 서·남·북 30 m × 4 = 120, b: 120, up: 둘레 40 × 3 = 120
        self.assertAlmostEqual(z['sidewall_m2'], 360)
        # a 위는 B2 가 덮어 0, b 100, up 100
        self.assertAlmostEqual(comp['spaces']['a']['roof_m2'], 0)
        self.assertAlmostEqual(comp['spaces']['b']['roof_m2'], 100)
        self.assertAlmostEqual(z['roof_m2'], 200)
        self.assertAlmostEqual(z['envelope_m2'], 560)
        self.assertAlmostEqual(z['glazing_m2'], 120 + 100)                   # up 만 투광
        self.assertAlmostEqual(z['ua_w_k'], 0.45 * (120 + 220) + 3.0 * 220)  # 153 + 660 = 813
        self.assertAlmostEqual(z['envelope_by_cover']['sandwich_panel'], 340)
        self.assertAlmostEqual(z['envelope_by_cover']['polycarbonate'], 220)
        self.assertEqual(z['to_other_zones'], [])
        # 합계 키는 덩어리 합 그대로
        self.assertAlmostEqual(comp['totals']['floor_m2'], 294)
        self.assertAlmostEqual(comp['totals']['envelope_m2'], 560)

    def test_nursery_without_void_upper_floor_is_own_zone(self):
        comp = FL.compile_layout(self._nursery(void=False))
        zs = self._zones(comp)
        self.assertEqual(set(zs), {frozenset(['a', 'b']), frozenset(['up'])})
        low, up = zs[frozenset(['a', 'b'])], zs[frozenset(['up'])]
        self.assertAlmostEqual(low['floor_m2'], 200)
        self.assertAlmostEqual(low['volume_m3'], 800)
        self.assertAlmostEqual(low['sidewall_m2'], 240)
        self.assertAlmostEqual(low['roof_m2'], 100)
        self.assertAlmostEqual(low['glazing_m2'], 0)
        self.assertAlmostEqual(low['ua_w_k'], 0.45 * 340)
        self.assertAlmostEqual(up['floor_m2'], 100)
        self.assertAlmostEqual(up['envelope_m2'], 220)
        self.assertAlmostEqual(up['glazing_m2'], 220)
        self.assertAlmostEqual(up['ua_w_k'], 660)
        self.assertEqual(low['joined_by'], ['open'])

    def test_void_on_ground_level_has_nothing_below(self):
        lay = self._nursery(void=False)
        lay['voids'] = [{'level_id': 'L1', 'outline': _rect(1, 3, 1, 4)}]
        comp = FL.compile_layout(lay)
        self.assertEqual(len(comp['air_zones']), 2)
        self.assertIn('void_without_space_below', [w['code'] for w in comp['warnings']])

    def test_void_not_over_a_space_joins_nothing(self):
        lay = self._nursery(void=False)
        lay['voids'] = [{'level_id': 'L2', 'outline': _rect(12, 14, 1, 4)}]   # B2 밖
        self.assertEqual(len(FL.compile_layout(lay)['air_zones']), 2)

    # ── 표본 2: ㄱ자 연동 온실 ──
    # 처마 3, 박공 상승 2. B1 0..10 × 0..20(유리 상속), B2 10..20 × 0..10(폴리카보네이트).
    # 두 덩어리는 x=10 에서 z 0..10 (10 m) 맞닿는다.
    def _lshape(self, between='open'):
        roof = {'type': 'gable', 'rise_m': 2, 'ridge_axis': 'z'}
        return {
            'schema': 1,
            'levels': [{'id': 'L1', 'elevation_m': 0, 'height_m': 3}],
            'blocks': [
                {'id': 'B1', 'level_id': 'L1', 'outline': _rect(0, 10, 0, 20), 'roof': dict(roof)},
                {'id': 'B2', 'level_id': 'L1', 'outline': _rect(10, 20, 0, 10), 'roof': dict(roof),
                 'walls': {'cover': 'polycarbonate'}},
            ],
            'boundaries': [{'between': ['space_B1', 'space_B2'], 'type': between}],
        }

    def test_l_shape_open_is_one_zone_with_inherited_cover(self):
        env = {'layers': [{'role': 'outer', 'cover': 'glass'}]}
        comp = FL.compile_layout(self._lshape('open'), envelope=env)
        self.assertEqual(len(comp['air_zones']), 1)
        z = comp['air_zones'][0]
        slope = 2 * math.sqrt(5 ** 2 + 2 ** 2)           # 박공 한 쌍의 경사 둘레(폭 10, 상승 2)
        b1 = 50 * 3 + slope * 20 + 2 * (10 * 2 / 2)      # 외벽 50(60−공유 10), 지붕, 박공 2개
        b2 = 30 * 3 + slope * 10 + 2 * (10 * 2 / 2)
        self.assertAlmostEqual(z['floor_m2'], 300)
        self.assertAlmostEqual(z['volume_m3'], (200 * 3 + 10 * 2 / 2 * 20) + (100 * 3 + 10 * 2 / 2 * 10))  # 1200
        self.assertAlmostEqual(z['sidewall_m2'], 240)
        self.assertAlmostEqual(z['roof_m2'], slope * 30, places=2)
        self.assertAlmostEqual(z['gable_m2'], 40)
        self.assertAlmostEqual(z['envelope_m2'], b1 + b2, places=2)
        self.assertAlmostEqual(z['envelope_by_cover']['glass'], b1, places=2)          # B1 은 시설 envelope 상속
        self.assertAlmostEqual(z['envelope_by_cover']['polycarbonate'], b2, places=2)  # B2 는 자기 덮개
        self.assertAlmostEqual(z['glazing_m2'], b1 + b2, places=2)
        self.assertAlmostEqual(z['ua_w_k'], 5.8 * b1 + 3.0 * b2, places=2)
        self.assertAlmostEqual(comp['totals']['volume_m3'], 1200, places=1)

    def test_l_shape_wall_boundary_splits_zones(self):
        comp = FL.compile_layout(self._lshape('wall'))
        self.assertEqual(len(comp['air_zones']), 2)
        z1, z2 = comp['air_zones']
        self.assertEqual([z1['space_ids'], z2['space_ids']], [['space_B1'], ['space_B2']])
        # 공유 벽 10 m × 처마 3 = 30 m² 가 두 구획 사이 벽
        self.assertEqual(z1['to_other_zones'], [{'zone': 'zone_2', 'type': 'wall', 'area_m2': 30.0}])
        self.assertEqual(z2['to_other_zones'], [{'zone': 'zone_1', 'type': 'wall', 'area_m2': 30.0}])
        # 덮개를 상속하지 않으면 기본(vinyl_double)
        self.assertEqual(comp['blocks']['B1']['cover'], 'vinyl_double')

    def test_envelope_inheritance_opaque_cover_has_no_glazing(self):
        env = {'layers': [{'role': 'outer', 'cover': 'sandwich_panel'}]}
        comp = FL.compile_layout(self._lshape('open'), envelope=env)
        b1 = comp['blocks']['B1']
        self.assertEqual(b1['cover'], 'sandwich_panel')
        self.assertAlmostEqual(b1['glazing_m2'], 0)
        self.assertAlmostEqual(comp['spaces']['space_B1']['glazing_m2'], 0)
        self.assertGreater(comp['spaces']['space_B2']['glazing_m2'], 0)

    def test_declared_open_without_contact_does_not_join(self):
        lay = self._lshape('open')
        lay['blocks'][1]['outline'] = _rect(12, 22, 0, 10)       # 2 m 떨어짐
        comp = FL.compile_layout(lay)
        self.assertEqual(len(comp['air_zones']), 2)
        self.assertIn('boundary_without_contact', [w['code'] for w in comp['warnings']])

    # ── 표본 3: 층별 평면이 다른 건물 ──
    # L1(높이 4) 은 ㄱ자 평면 B1 = 24×12 + 12×18 = 504 m², 콘크리트. L2(4.2~7.2) 는 B2 = 0..12 × 0..30
    # (서쪽 날개 위만) 360 m², 유리. 공간: east(12..24 × 0..12), west(0..12 × 0..30), up(B2).
    def _stepped(self, void=False):
        lay = {
            'schema': 1,
            'levels': [{'id': 'L1', 'elevation_m': 0, 'height_m': 4.0},
                       {'id': 'L2', 'elevation_m': 4.2, 'height_m': 3.0}],
            'blocks': [
                {'id': 'B1', 'level_id': 'L1', 'roof': {'type': 'flat'}, 'walls': {'cover': 'concrete'},
                 'outline': [[0, 0], [24, 0], [24, 12], [12, 12], [12, 30], [0, 30]]},
                {'id': 'B2', 'level_id': 'L2', 'roof': {'type': 'flat'}, 'walls': {'cover': 'glass'},
                 'outline': _rect(0, 12, 0, 30)},
            ],
            'spaces': [
                {'id': 'east', 'block_id': 'B1', 'outline': _rect(12, 24, 0, 12)},
                {'id': 'west', 'block_id': 'B1', 'outline': _rect(0, 12, 0, 30)},
                {'id': 'up', 'block_id': 'B2'},
            ],
            'boundaries': [{'between': ['east', 'west'], 'type': 'curtain'}],
        }
        if void:
            lay['voids'] = [{'level_id': 'L2', 'outline': _rect(2, 4, 2, 4)}]     # 4 m², west·up 위
        return lay

    def test_stepped_three_zones(self):
        comp = FL.compile_layout(self._stepped())
        zs = self._zones(comp)
        self.assertEqual(len(zs), 3)
        east, west, up = (zs[frozenset([k])] for k in ('east', 'west', 'up'))
        # east: 외벽 12(남)+12(동)+12(북) = 36 × 4, 지붕은 덮이지 않아 144
        self.assertAlmostEqual(east['floor_m2'], 144)
        self.assertAlmostEqual(east['volume_m3'], 576)
        self.assertAlmostEqual(east['sidewall_m2'], 144)
        self.assertAlmostEqual(east['roof_m2'], 144)
        # west: 외벽 12(남)+18(동, z 12..30)+12(북)+30(서) = 72 × 4, 지붕은 B2 가 전부 덮음
        self.assertAlmostEqual(west['floor_m2'], 360)
        self.assertAlmostEqual(west['volume_m3'], 1440)
        self.assertAlmostEqual(west['sidewall_m2'], 288)
        self.assertAlmostEqual(west['roof_m2'], 0)
        self.assertAlmostEqual(west['glazing_m2'], 0)
        # up: 둘레 84 × 3 = 252, 지붕 360, 유리
        self.assertAlmostEqual(up['volume_m3'], 1080)
        self.assertAlmostEqual(up['envelope_m2'], 252 + 360)
        self.assertAlmostEqual(up['glazing_m2'], 612)
        self.assertAlmostEqual(up['ua_w_k'], 5.8 * 612)
        self.assertAlmostEqual(east['ua_w_k'], 3.1 * 288)
        # east–west 는 커튼 경계 12 m × 4 = 48 m²
        self.assertEqual(east['to_other_zones'], [{'zone': west['id'], 'type': 'curtain', 'area_m2': 48.0}])
        # 덩어리 합 = 구획 합
        self.assertAlmostEqual(sum(z['envelope_m2'] for z in comp['air_zones']), comp['totals']['envelope_m2'])
        self.assertAlmostEqual(comp['totals']['roof_m2'], 144 + 360)

    def test_stepped_void_joins_west_and_up(self):
        comp = FL.compile_layout(self._stepped(void=True))
        zs = self._zones(comp)
        self.assertEqual(set(zs), {frozenset(['east']), frozenset(['west', 'up'])})
        z = zs[frozenset(['west', 'up'])]
        self.assertAlmostEqual(z['floor_m2'], 360 + 360 - 4)
        self.assertAlmostEqual(z['volume_m3'], 1440 + 1080)
        self.assertAlmostEqual(z['sidewall_m2'], 288 + 252)
        self.assertAlmostEqual(z['roof_m2'], 360)
        self.assertAlmostEqual(z['glazing_m2'], 612)
        self.assertEqual(z['to_other_zones'], [{'zone': zs[frozenset(['east'])]['id'], 'type': 'curtain', 'area_m2': 48.0}])
        self.assertEqual(comp['spaces']['up']['zone_id'], z['id'])

    def test_legacy_connected_is_one_zone_and_single_n_is_n_zones(self):
        _, comp = _totals(_fac('connected', 3))
        self.assertEqual(len(comp['air_zones']), 1)
        z = comp['air_zones'][0]
        for k in ('floor_m2', 'envelope_m2', 'volume_m3', 'glazing_m2'):
            self.assertAlmostEqual(z[k], comp['totals'][k], places=1, msg=k)
        _, comp = _totals(_fac('single', 4, spacing=1.5))
        self.assertEqual(len(comp['air_zones']), 4)

    def test_zones_do_not_change_totals(self):
        lay = self._nursery()
        a = FL.compile_layout(lay)['totals']
        lay['voids'] = []
        self.assertEqual(a['envelope_m2'], FL.compile_layout(lay)['totals']['envelope_m2'])


class LocateTest(unittest.TestCase):
    def test_height_picks_level(self):
        lay = _two_level()
        self.assertEqual(FL.locate(lay, 5, 1.0, 5), {'level_id': 'L1', 'block_id': 'B1', 'space_id': 'a'})
        self.assertEqual(FL.locate(lay, 15, 1.0, 5)['space_id'], 'b')
        self.assertEqual(FL.locate(lay, 5, 4.1, 5)['level_id'], 'L1')    # 슬래브 사이는 아래층
        self.assertEqual(FL.locate(lay, 5, 5.0, 5), {'level_id': 'L2', 'block_id': 'B2', 'space_id': 'up'})
        self.assertEqual(FL.locate(lay, 5, -1.0, 5)['level_id'], 'L1')
        self.assertEqual(FL.locate(lay, 5, None, 5)['level_id'], 'L1')
        # 2층은 x 0..10 만 있다 — 그 밖은 가장 가까운 2층 공간(범위 ±1 안)이거나 없음
        self.assertEqual(FL.locate(lay, 10.5, 5.0, 5)['space_id'], 'up')
        self.assertIsNone(FL.locate(lay, 15, 5.0, 5))

    def test_matches_legacy_bay_map(self):
        cases = [
            _fac(structure='connected', bay_count=4),
            _fac(structure='connected', bay_count=6, bays=[{'id': 'A', 'bay_start': 1, 'bay_end': 2},
                                                           {'id': 'B', 'bay_start': 4, 'bay_end': 5}]),
            _fac(bay_count=5, spacing=2.8),
            _fac(bay_count=6, spacing=2.8, bays=[{'id': 'z1', 'bay_start': 1, 'bay_end': 3},
                                                 {'id': 'z2', 'bay_start': 4, 'bay_end': 6}]),
            _fac(bay_count=1),
        ]
        for fac in cases:
            layout = FL.layout_from_legacy(fac)
            slices = compute_bay_slices(fac)
            total = slices[-1]['x_max']
            fits, x = [], -3.0
            while x <= total + 3.0:
                for z in (-5.0, 0.0, 15.0, 30.0, 45.0):
                    fits.append({'id': 'f%d_%d' % (round(x * 100), z), 'position': [round(x, 2), 1.0, z]})
                x += 0.37
            legacy = build_fitting_bay_map(slices, fits)
            for f in fits:
                r = FL.locate(layout, f['position'][0], f['position'][1], f['position'][2])
                self.assertEqual(r['space_id'] if r else None, legacy.get(f['id']), (fac['structure'], f['position']))

    def test_invalid_input_returns_none(self):
        self.assertIsNone(FL.locate({}, 1, 1, 1))
        self.assertIsNone(FL.locate(_two_level(), 'a', 1, 1))


class FootprintTest(unittest.TestCase):
    def test_vertices_and_center(self):
        lay = FL.layout_from_legacy(_fac(span=10, length=20))
        pts = FL.footprint_points(lay)
        self.assertEqual(sorted(map(tuple, pts)), sorted([(0.0, 0.0), (10.0, 0.0), (10.0, 20.0), (0.0, 20.0), (5.0, 10.0)]))

    def test_step_divides_long_edges(self):
        lay = FL.layout_from_legacy(_fac(span=10, length=20))
        pts = FL.footprint_points(lay, step_m=5)
        self.assertIn([0.0, 5.0], pts)
        self.assertIn([0.0, 15.0], pts)
        self.assertIn([5.0, 0.0], pts)
        self.assertEqual(len(pts), 4 + 2 * 3 + 2 * 1 + 1)               # 꼭짓점 4, 긴 변 3점x2, 짧은 변 1점x2, 중심
        self.assertEqual(len(pts), len(set(map(tuple, pts))))

    def test_multi_block_and_levels_deduped(self):
        pts = FL.footprint_points(_two_level())
        self.assertEqual(len(pts), len(set(map(tuple, pts))))
        self.assertIn([20.0, 10.0], pts)
        self.assertIn([5.0, 5.0], pts)

    def test_bad_step_and_invalid_layout(self):
        with self.assertRaises(ValueError):
            FL.footprint_points(_two_level(), step_m=0)
        self.assertEqual(FL.footprint_points({}), [])


class ValidateTest(unittest.TestCase):
    def _codes(self, mutate):
        lay = _two_level()
        mutate(lay)
        return {e['code'] for e in FL.validate_layout(lay)}

    def test_valid(self):
        self.assertEqual(FL.validate_layout(_two_level()), [])
        self.assertEqual(FL.validate_layout(FL.layout_from_legacy(_fac(structure='connected', bay_count=3))), [])

    def test_not_object_and_schema(self):
        self.assertEqual(FL.validate_layout(None)[0]['code'], 'not_object')
        self.assertIn('bad_schema', self._codes(lambda l: l.update(schema=2)))

    def test_levels(self):
        self.assertIn('levels_required', self._codes(lambda l: l.update(levels=[])))
        self.assertIn('duplicate_id', self._codes(lambda l: l['levels'][1].update(id='L1')))
        self.assertIn('bad_number', self._codes(lambda l: l['levels'][0].update(height_m=0)))
        self.assertIn('level_overlap', self._codes(lambda l: l['levels'][1].update(elevation_m=3.0)))

    def test_blocks(self):
        self.assertIn('blocks_required', self._codes(lambda l: l.update(blocks=[])))
        self.assertIn('unknown_level', self._codes(lambda l: l['blocks'][0].update(level_id='X')))
        self.assertIn('bad_outline', self._codes(lambda l: l['blocks'][0].update(outline=[[0, 0], [1, 1]])))
        self.assertIn('degenerate_outline', self._codes(lambda l: l['blocks'][0].update(outline=[[0, 0], [1, 0], [2, 0]])))
        self.assertIn('self_intersecting_outline', self._codes(
            lambda l: l['blocks'][0].update(outline=[[0, 0], [10, 0], [10, 10], [5, -5]])))
        self.assertIn('bad_roof_type', self._codes(lambda l: l['blocks'][0].update(roof={'type': 'dome'})))
        self.assertIn('curved_roof_needs_rect', self._codes(
            lambda l: l['blocks'][0].update(outline=[[0, 0], [10, 0], [10, 10], [5, 12], [0, 10]],
                                            roof={'type': 'gable'})))
        self.assertIn('unknown_cover', self._codes(lambda l: l['blocks'][0].update(walls={'cover': 'gold'})))
        self.assertIn('spans_out_of_levels', self._codes(lambda l: l['blocks'][1].update(spans=2)))
        self.assertIn('bad_number', self._codes(lambda l: l['blocks'][0].update(roof={'type': 'arch', 'runs': 0})))

    def test_spaces(self):
        self.assertIn('unknown_block', self._codes(lambda l: l['spaces'][0].update(block_id='Z')))
        self.assertIn('duplicate_id', self._codes(lambda l: l['spaces'][1].update(id='a')))
        self.assertIn('space_outside_block', self._codes(lambda l: l['spaces'][0].update(outline=_rect(0, 30, 0, 10))))
        self.assertIn('outline_required', self._codes(lambda l: l['spaces'][0].pop('outline')))
        self.assertIn('spaces_overlap', self._codes(lambda l: l['spaces'][1].update(outline=_rect(0, 20, 0, 10))))
        self.assertIn('outline_with_block_ids', self._codes(lambda l: l['spaces'][0].update(block_ids=['B1'])))

    def test_boundaries_and_voids(self):
        self.assertIn('bad_boundary', self._codes(lambda l: l['boundaries'].append({'between': ['a', 'zz'], 'type': 'wall'})))
        self.assertIn('bad_boundary_type', self._codes(lambda l: l['boundaries'][0].update(type='door')))
        self.assertIn('duplicate_boundary', self._codes(
            lambda l: l['boundaries'].append({'between': ['b', 'a'], 'type': 'wall'})))
        self.assertIn('unknown_level', self._codes(lambda l: l.update(voids=[{'level_id': 'Q', 'outline': _rect(0, 1, 0, 1)}])))
        self.assertIn('bad_outline', self._codes(lambda l: l.update(voids=[{'level_id': 'L2', 'outline': [[0, 0]]}])))

    def test_compile_rejects_invalid(self):
        with self.assertRaises(ValueError):
            FL.compile_layout({'schema': 1})

    def test_boundary_without_contact_warns(self):
        lay = _two_level()
        lay['boundaries'].append({'between': ['a', 'up'], 'type': 'wall'})
        comp = FL.compile_layout(lay)
        self.assertTrue(any(w['code'] == 'boundary_without_contact' for w in comp['warnings']))


if __name__ == '__main__':
    unittest.main()
