# coding=utf-8
"""Unit tests for facility_calc.py — capacity formulas (PRD/DESIGN-GEO-FACILITY-001).

Runs without Flask/DB. Tests the pure math/dict calculator only.
"""
import unittest
import sys
import os

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), os.path.pardir, os.path.pardir)))

from aot.aot_flask.geo.facility_calc import (
    compute_capacity,
    effective_u,
    effective_transmittance,
    arch_section_area,
    arch_section_perimeter,
    polygon_area_m2,
    polygon_perimeter_m,
    MATERIALS,
    DEFAULT_MATERIAL,
)


def _spec(layer_count=1, structure='single', bay_count=1,
          outer_mat='vinyl_double', inner_mat='non_woven_fabric',
          actuators=None, geometry=None):
    spec = {
        'structure': structure,
        'bay_count': bay_count,
        'geometry_3d': {
            'span_width_m': 7, 'eave_height_m': 2, 'ridge_height_m': 4,
            'length_m': 30, 'roof_type': 'arch'
        },
        'envelope': {
            'layer_count': layer_count,
            'outer': {'cover_material': outer_mat,
                      'side_vent': {'enabled': True},
                      'roof_vent': {'enabled': False}},
            'inner': {'cover_material': inner_mat, 'air_gap_m': 0.5,
                      'side_vent': {'enabled': True, 'control_mode': 'synced'},
                      'roof_vent': {'enabled': False, 'control_mode': 'synced'}}
                     if layer_count == 2 else None,
            'curtain': {'thermal': False, 'shade': False},
        },
        'actuators': actuators or {},
    }
    if geometry is not None:
        spec['outer_geometry'] = geometry
    return spec


class TestMaterialsTable(unittest.TestCase):
    """Materials table must contain all 8 materials specified in DESIGN §5-1."""

    def test_materials_table_contains_required_keys(self):
        required = ['vinyl_single', 'vinyl_double', 'po_film', 'polycarbonate',
                    'glass', 'non_woven_fabric', 'pe_film', 'air_cushion']
        for m in required:
            self.assertIn(m, MATERIALS)
            self.assertIn('u', MATERIALS[m])
            self.assertIn('transmittance', MATERIALS[m])
            self.assertGreater(MATERIALS[m]['u'], 0)
            self.assertGreater(MATERIALS[m]['transmittance'], 0)
            self.assertLessEqual(MATERIALS[m]['transmittance'], 1.0)

    def test_default_material_exists(self):
        self.assertIn(DEFAULT_MATERIAL, MATERIALS)


class TestEffectiveU(unittest.TestCase):
    """Single = U_outer; double = 1/(1/U_o + R_gap + 1/U_i)."""

    def test_single_layer_returns_outer_u(self):
        self.assertAlmostEqual(effective_u(1, 'vinyl_double'), 4.0, places=2)
        self.assertAlmostEqual(effective_u(1, 'glass'), 5.8, places=2)

    def test_double_layer_lowers_u(self):
        u_single = effective_u(1, 'vinyl_double')
        u_double = effective_u(2, 'vinyl_double', 'non_woven_fabric')
        self.assertLess(u_double, u_single,
                        f"Double layer U ({u_double}) must be lower than single ({u_single})")

    def test_double_layer_formula(self):
        # vinyl_double (4.0) + non_woven (3.5) + R_gap=0.18
        # R_total = 1/4 + 0.18 + 1/3.5 = 0.25 + 0.18 + 0.2857 = 0.7157
        # U_eff = 1/0.7157 ≈ 1.397
        u = effective_u(2, 'vinyl_double', 'non_woven_fabric')
        self.assertAlmostEqual(u, 1.397, places=2)

    def test_unknown_material_falls_back(self):
        u = effective_u(1, 'fake_material_xyz')
        self.assertEqual(u, MATERIALS[DEFAULT_MATERIAL]['u'])


class TestEffectiveTransmittance(unittest.TestCase):
    def test_single_returns_outer(self):
        self.assertAlmostEqual(effective_transmittance(1, 'vinyl_double'), 0.78, places=2)

    def test_double_multiplies(self):
        t = effective_transmittance(2, 'vinyl_double', 'non_woven_fabric')
        self.assertAlmostEqual(t, 0.78 * 0.50, places=3)


class TestArchGeometry(unittest.TestCase):
    def test_arch_section_area_positive(self):
        a = arch_section_area(7, 2)
        self.assertAlmostEqual(a, 3.14159 * 3.5 * 2 / 2, places=2)

    def test_arch_section_perimeter_finite(self):
        p = arch_section_perimeter(7, 2)
        self.assertGreater(p, 7)        # longer than the chord
        self.assertLess(p, 7 * 1.6)     # but bounded

    def test_zero_rise_returns_chord(self):
        p = arch_section_perimeter(7, 0)
        self.assertEqual(p, 7)


class TestPolygonHelpers(unittest.TestCase):
    """Local meter-projection area / perimeter."""

    def test_unit_polygon_in_seoul_returns_meter_scale(self):
        # ~10m × 10m square near Seoul (37.5665, 126.9780)
        # 10m ≈ 9e-5 deg lat ; 11.4e-5 deg lng (cos(37.5°)≈0.793)
        d_lat = 10 / 111320.0
        d_lng = 10 / (111320.0 * 0.793)
        coords = [
            [126.9780, 37.5665],
            [126.9780 + d_lng, 37.5665],
            [126.9780 + d_lng, 37.5665 + d_lat],
            [126.9780, 37.5665 + d_lat],
            [126.9780, 37.5665],
        ]
        geom = {'type': 'Polygon', 'coordinates': [coords]}
        area = polygon_area_m2(geom)
        peri = polygon_perimeter_m(geom)
        self.assertAlmostEqual(area, 100.0, delta=2.0)   # ~100 m²
        self.assertAlmostEqual(peri, 40.0, delta=2.0)    # ~40 m

    def test_empty_geometry_returns_zero(self):
        self.assertEqual(polygon_area_m2(None), 0.0)
        self.assertEqual(polygon_area_m2({'type': 'Point'}), 0.0)
        self.assertEqual(polygon_perimeter_m(None), 0.0)


class TestComputeCapacity(unittest.TestCase):
    """End-to-end compute_capacity() outputs sanity checks."""

    def test_standard_single_layer(self):
        r = compute_capacity(_spec(layer_count=1))
        # Floor ≈ span × length = 7 × 30 = 210
        self.assertAlmostEqual(r['floor_m2'], 210.0, delta=1.0)
        # Volume between floor*eave (420) and floor*ridge (840)
        self.assertGreater(r['volume_m3'], 420)
        self.assertLess(r['volume_m3'], 840)
        # U_eff = 4.0 for single vinyl_double
        self.assertAlmostEqual(r['u_effective'], 4.0, places=2)
        # Heating must be positive
        self.assertGreater(r['heating_kw'], 0)
        # Note label present
        self.assertIn('±5~10%', r['_note'])

    def test_double_layer_reduces_heating(self):
        r1 = compute_capacity(_spec(layer_count=1))
        r2 = compute_capacity(_spec(layer_count=2))
        self.assertLess(r2['heating_kw'], r1['heating_kw'],
                        "Double layer must reduce heating load")
        self.assertLess(r2['u_effective'], r1['u_effective'])
        self.assertLess(r2['transmittance'], r1['transmittance'])

    def test_connected_scales_with_bay_count(self):
        single_bay = compute_capacity(_spec(structure='connected', bay_count=1))
        three_bay = compute_capacity(_spec(structure='connected', bay_count=3))
        # Floor scales ~3x
        self.assertAlmostEqual(three_bay['floor_m2'] / single_bay['floor_m2'], 3.0, delta=0.1)
        # Volume scales ~3x
        self.assertAlmostEqual(three_bay['volume_m3'] / single_bay['volume_m3'], 3.0, delta=0.1)

    def test_fallback_when_no_polygon(self):
        # No outer_geometry → falls back to span × length
        r = compute_capacity(_spec())
        self.assertGreater(r['floor_m2'], 0)
        self.assertGreater(r['envelope_m2'], 0)

    def test_required_output_keys(self):
        r = compute_capacity(_spec())
        required = ['floor_m2', 'envelope_m2', 'volume_m3', 'glazing_m2',
                    'vent_open_m2', 'u_effective', 'transmittance',
                    'heating_kw', 'cooling_kw', 'ach_natural', 'ach_forced',
                    'ach_total', '_note']
        for k in required:
            self.assertIn(k, r)

    def test_fan_actuator_increases_ach(self):
        r_no_fan = compute_capacity(_spec(actuators={}))
        r_fan = compute_capacity(_spec(actuators={'circulation_fan': 'fake-uuid',
                                                   'exhaust_fan': 'fake-uuid-2'}))
        self.assertGreater(r_fan['ach_forced'], r_no_fan['ach_forced'])
        self.assertGreater(r_fan['ach_total'], r_no_fan['ach_total'])

    def test_independent_inner_vent_increases_open_area(self):
        # synced — only outer counts
        spec_synced = _spec(layer_count=2)
        # independent — outer + inner
        spec_indep = _spec(layer_count=2)
        spec_indep['envelope']['inner']['side_vent']['control_mode'] = 'independent'

        r_synced = compute_capacity(spec_synced)
        r_indep = compute_capacity(spec_indep)
        self.assertGreater(r_indep['vent_open_m2'], r_synced['vent_open_m2'])


if __name__ == '__main__':
    unittest.main()
