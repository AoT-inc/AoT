# coding=utf-8
"""시설 모형 F1 — 구역 슬라이스의 outline·level_id 와 귀속 공통 경로(locate).

기존 구역 귀속(x 범위 판정)과 결과가 정확히 같아야 한다. 아래 `_old_*` 는 F1 이전
`bay_id_for_position` 의 동결 사본이다.
"""
import unittest

from aot.space import facility_layout as FL
from aot.space.facility_bays import (
    bay_id_for_position, build_fitting_bay_map, compute_bay_slices,
    layout_from_slices, slice_x_range)


def _old_bay_id(slices, position):
    x = float(position[0])
    if x < slices[0]['x_min'] - 1.0 or x > slices[-1]['x_max'] + 1.0:
        return None
    for s in slices:
        if s['x_min'] <= x <= s['x_max']:
            return s['id']
    return min(slices, key=lambda s: abs(x - s['x_center']))['id']


def _fac(structure='connected', n=4, spacing=0.0, bays=None, length=30.0, span=7.0):
    return {'structure': structure, 'bay_count': n, 'bays': bays or [], 'name': 'F',
            'geometry_3d': {'span_width_m': span, 'spacing_m': spacing, 'length_m': length}}


class SliceKeysTest(unittest.TestCase):
    def test_new_keys_and_old_keys_kept(self):
        sl = compute_bay_slices(_fac(n=2, length=20.0))
        self.assertEqual(len(sl), 2)
        for s in sl:
            for k in ('id', 'index', 'name', 'crop', 'x_min', 'x_max', 'x_center', 'bay_start', 'bay_end'):
                self.assertIn(k, s)
            self.assertEqual(s['level_id'], 'L1')
        self.assertEqual(sl[1]['outline'], [[7.0, 0.0], [14.0, 0.0], [14.0, 20.0], [7.0, 20.0]])

    def test_zone_slice_covers_gap_between_detached_bays(self):
        sl = compute_bay_slices(_fac('single', 4, 3.0, [{'id': 'a', 'bay_start': 1, 'bay_end': 2}]))
        self.assertEqual((sl[0]['x_min'], sl[0]['x_max']), (0.0, 17.0))
        xs = [p[0] for p in sl[0]['outline']]
        self.assertEqual((min(xs), max(xs)), (0.0, 17.0))

    def test_missing_length_uses_default(self):
        fac = _fac()
        fac['geometry_3d'].pop('length_m')
        self.assertEqual(compute_bay_slices(fac)[0]['outline'][2], [7.0, 30.0])

    def test_no_slices_without_span(self):
        self.assertEqual(compute_bay_slices(_fac(span=0)), [])

    def test_slice_x_range(self):
        self.assertEqual(slice_x_range({'x_min': 1, 'x_max': 4}), (1.0, 4.0))
        self.assertEqual(slice_x_range({'x_min': 1, 'x_max': 4, 'outline': [[2, 0], [9, 0], [9, 5]]}), (2.0, 9.0))
        self.assertIsNone(slice_x_range({'x_min': 'a', 'x_max': 4}))
        self.assertIsNone(slice_x_range({}))


class AttributionTest(unittest.TestCase):
    CASES = [
        _fac('connected', 4),
        _fac('connected', 6, bays=[{'id': 'A', 'bay_start': 1, 'bay_end': 1}, {'id': 'B', 'bay_start': 3, 'bay_end': 6}]),
        _fac('single', 5, 2.8),
        _fac('single', 6, 2.8, [{'id': 'z1', 'bay_start': 1, 'bay_end': 2}, {'id': 'z2', 'bay_start': 4, 'bay_end': 6}]),
        _fac('single', 1),
    ]

    def test_same_as_old_x_rule(self):
        for fac in self.CASES:
            sl = compute_bay_slices(fac)
            total = sl[-1]['x_max']
            fits, x, i = [], -3.0, 0
            while x <= total + 3.0:
                for z in (-5.0, 0.0, 15.0, 45.0):
                    fits.append({'id': 'f%d' % i, 'position': [round(x, 3), 1.0, z]})
                    i += 1
                x += 0.13
            got = build_fitting_bay_map(sl, fits)
            for f in fits:
                self.assertEqual(got.get(f['id']), _old_bay_id(sl, f['position']), (fac['structure'], f['position']))
                self.assertEqual(bay_id_for_position(sl, f['position']), _old_bay_id(sl, f['position']))

    def test_unequal_gap_uses_center_not_edge(self):
        # 구역 A(1동, 폭 7)와 B(3~6동, 폭 28) 사이 틈 x 7..14: 중심 거리로 가른다.
        fac = _fac('connected', 6, bays=[{'id': 'A', 'bay_start': 1, 'bay_end': 1}, {'id': 'B', 'bay_start': 3, 'bay_end': 6}])
        sl = compute_bay_slices(fac)
        self.assertEqual(bay_id_for_position(sl, [11.0, 1, 5]), _old_bay_id(sl, [11.0, 1, 5]))
        self.assertEqual(bay_id_for_position(sl, [11.0, 1, 5]), 'A')   # 중심 3.5 와 28 → A 가 가깝다(7.5 < 17)

    def test_position_forms_and_missing(self):
        sl = compute_bay_slices(_fac('connected', 2))
        self.assertEqual(bay_id_for_position(sl, {'x': 10.0, 'y': 1, 'z': 5}), 'bay_2')
        self.assertIsNone(bay_id_for_position(sl, None))
        self.assertIsNone(bay_id_for_position(sl, [100.0, 1, 5]))
        self.assertIsNone(bay_id_for_position(sl, [-1.5, 1, 5]))
        self.assertEqual(bay_id_for_position(sl, [-0.5, 1, 5]), 'bay_1')
        self.assertIsNone(bay_id_for_position([], [1, 1, 1]))
        self.assertEqual(build_fitting_bay_map([], [{'id': 'a', 'position': [1, 1, 1]}]), {})

    def test_fitting_without_id_or_position_skipped(self):
        sl = compute_bay_slices(_fac('connected', 2))
        m = build_fitting_bay_map(sl, [{'position': [1, 1, 1]}, {'id': 'n'}, {'id': 'ok', 'position': [1, 1, 1]}])
        self.assertEqual(m, {'ok': 'bay_1'})

    def test_duplicate_zone_ids_do_not_break(self):
        fac = _fac('connected', 4, bays=[{'id': 'same', 'bay_start': 1, 'bay_end': 2}, {'id': 'same', 'bay_start': 3, 'bay_end': 4}])
        sl = compute_bay_slices(fac)
        self.assertEqual(bay_id_for_position(sl, [20.0, 1, 5]), 'same')

    def test_old_slices_without_outline(self):
        sl = [{'id': 'a', 'x_min': 0.0, 'x_max': 7.0, 'x_center': 3.5},
              {'id': 'b', 'x_min': 7.0, 'x_max': 14.0, 'x_center': 10.5}]
        self.assertEqual(bay_id_for_position(sl, [9.0, 1, 1]), 'b')


class LocateXBandTest(unittest.TestCase):
    def test_layout_from_slices_is_valid(self):
        lay = layout_from_slices(compute_bay_slices(_fac('single', 3, 2.0)))
        self.assertEqual(FL.validate_layout(lay), [])
        self.assertIsNone(layout_from_slices([]))

    def test_default_mode_unchanged(self):
        lay = FL.layout_from_legacy(_fac('connected', 2))
        self.assertEqual(FL.locate(lay, 3.0, 1.0, 5.0)['space_id'], 'bay_1')

    def test_x_band_ignores_z(self):
        lay = FL.layout_from_legacy(_fac('connected', 2))
        self.assertEqual(FL.locate(lay, 10.0, 1.0, -9.0, x_band=True)['space_id'], 'bay_2')
        self.assertEqual(FL.locate(lay, 10.0, None, None, x_band=True)['space_id'], 'bay_2')
        self.assertIsNone(FL.locate(lay, 99.0, 1.0, 5.0, x_band=True))

    def test_locate_points_matches_locate(self):
        lay = FL.layout_from_legacy(_fac('single', 3, 2.0))
        pts = [(1.0, 1.0, 5.0), (9.5, 1.0, 5.0), (30.0, 1.0, 5.0)]
        self.assertEqual(FL.locate_points(lay, pts), [FL.locate(lay, *p) for p in pts])
        self.assertEqual(FL.locate_points({}, pts), [])


if __name__ == '__main__':
    unittest.main()
