# coding=utf-8
"""검토 단계의 시설 합계(`layout_totals`) — 모형이 있으면 표시 값은 `compile_layout` 의 `totals` 다.

표시 전용이다. `computed`(저장·제어가 읽는 `facility_calc`)는 이 키로 바뀌지 않는다.
"""
import copy
import os
import sys
import unittest

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), os.path.pardir, os.path.pardir)))

from aot.space import facility_layout as FL
from aot.space.facility_io import layout_preview, layout_totals
from aot.space.facility_calc import compute_capacity


def _legacy(bay_count=3):
    return {'structure': 'connected', 'bay_count': bay_count, 'name': '시험',
            'geometry_3d': {'span_width_m': 8, 'eave_height_m': 2, 'ridge_height_m': 4,
                            'length_m': 30, 'roof_type': 'arch', 'spacing_m': 0},
            'envelope': {'layers': [{'role': 'outer', 'cover': 'vinyl_double'}]}, 'bays': []}


def _layout_120_240_234():
    """구역 120·240·234 m²(합 594) — 옛 치수(8×30×3 = 720)와 다르다."""
    def rect(x0, x1, z0, z1):
        return [[x0, z0], [x1, z0], [x1, z1], [x0, z1]]
    lay = FL.layout_from_legacy(_legacy(3))
    return lay, rect


class LayoutTotalsTest(unittest.TestCase):
    def setUp(self):
        self.fac = _legacy(3)
        self.layout = FL.layout_from_legacy(self.fac)

    def test_none_without_layout(self):
        self.assertIsNone(layout_totals(None))
        self.assertIsNone(layout_totals({}))

    def test_equals_compile_totals(self):
        t = layout_totals(self.layout, self.fac['envelope'])
        self.assertEqual(t, FL.compile_layout(self.layout, self.fac['envelope'])['totals'])

    def test_zones_add_up_to_facility_floor(self):
        t = layout_totals(self.layout, self.fac['envelope'])
        zones = FL.layout_zones(self.layout, self.fac['envelope'])
        self.assertAlmostEqual(sum(z['floor_m2'] for z in zones), t['floor_m2'], places=1)

    def test_sample_zones_120_240_234(self):
        """표본 1: 구역 120·240·234, 합 594 m² — 구역 합계와 시설 합계가 같다."""
        def rect(x0, x1, z0, z1):
            return [[x0, z0], [x1, z0], [x1, z1], [x0, z1]]
        lay = {
            'schema': 1,
            'levels': [{'id': 'L1', 'name': '1층', 'elevation_m': 0, 'height_m': 3.0}],
            'blocks': [{'id': 'B1', 'level_id': 'L1', 'outline': rect(0, 59.4, 0, 10),
                        'roof': {'type': 'flat'}}],
            'spaces': [
                {'id': 'a', 'block_id': 'B1', 'name': 'A', 'outline': rect(0, 12, 0, 10)},
                {'id': 'b', 'block_id': 'B1', 'name': 'B', 'outline': rect(12, 36, 0, 10)},
                {'id': 'c', 'block_id': 'B1', 'name': 'C', 'outline': rect(36, 59.4, 0, 10)},
            ],
        }
        zones = FL.layout_zones(lay)
        self.assertEqual([round(z['floor_m2']) for z in zones], [120, 240, 234])
        t = layout_totals(lay)
        self.assertAlmostEqual(sum(z['floor_m2'] for z in zones), 594, places=1)
        self.assertAlmostEqual(t['floor_m2'], 594, places=1)

    def test_preview_has_totals_and_computed_untouched(self):
        data = dict(self.fac, layout=self.layout)
        before = copy.deepcopy(data)
        out = layout_preview(data)
        self.assertEqual(out['layout_totals'], out['layout_compiled']['totals'])
        self.assertEqual(data, before)               # 입력(=저장될 값)을 건드리지 않는다
        # computed 는 facility_calc 가 그대로 정한다 — 모형 합계로 덮지 않는다
        self.assertEqual(compute_capacity(data), compute_capacity(before))

    def test_preview_without_payload_layout_uses_stored(self):
        out = layout_preview(dict(self.fac), stored_layout=self.layout)
        self.assertIn('layout_draft', out)
        self.assertEqual(out['layout_totals'], FL.compile_layout(self.layout, self.fac['envelope'])['totals'])

    def test_preview_errors_no_totals(self):
        bad = {'schema': 1, 'levels': 'x'}
        out = layout_preview(dict(self.fac, layout=bad))
        self.assertTrue(out['layout_errors'])
        self.assertNotIn('layout_totals', out)

    def test_legacy_form_no_totals(self):
        out = layout_preview(dict(self.fac))
        self.assertIn('layout_draft', out)
        self.assertNotIn('layout_totals', out)


if __name__ == '__main__':
    unittest.main()
