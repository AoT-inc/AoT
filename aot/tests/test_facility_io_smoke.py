# coding=utf-8
"""Smoke tests for facility_io.py and routes_geo facility routes.

These tests verify import structure and method signatures without Flask app
or DB context. Full integration tests require Docker environment.

PRD/DESIGN-GEO-FACILITY-001
"""
import unittest
import sys
import os
import inspect

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), os.path.pardir, os.path.pardir)))


class TestFacilityIOImport(unittest.TestCase):
    """FacilityManager class structure verification."""

    def test_import_facility_manager(self):
        from aot.aot_flask.geo.facility_io import FacilityManager
        self.assertTrue(callable(FacilityManager))

    def test_facility_manager_has_crud_methods(self):
        from aot.aot_flask.geo.facility_io import FacilityManager
        for method_name in ['list_facilities', 'get_facility',
                            'save_facility', 'delete_facility', '_to_dict']:
            self.assertTrue(hasattr(FacilityManager, method_name),
                            f"FacilityManager missing {method_name}")

    def test_save_signature(self):
        from aot.aot_flask.geo.facility_io import FacilityManager
        sig = inspect.signature(FacilityManager.save_facility)
        params = list(sig.parameters.keys())
        self.assertIn('data', params)
        self.assertIn('user_id', params)

    def test_delete_requires_confirm_name(self):
        from aot.aot_flask.geo.facility_io import FacilityManager
        sig = inspect.signature(FacilityManager.delete_facility)
        params = list(sig.parameters.keys())
        self.assertIn('confirm_name', params,
                      "Constitution Art.5 — delete must require confirm_name")


class TestGeoModuleExports(unittest.TestCase):
    def test_geo_init_exports_facility_manager(self):
        from aot.aot_flask.geo import FacilityManager
        self.assertTrue(callable(FacilityManager))


class TestFacilityCalcModule(unittest.TestCase):
    def test_compute_capacity_exists(self):
        from aot.aot_flask.geo.facility_calc import compute_capacity
        self.assertTrue(callable(compute_capacity))

    def test_materials_count(self):
        from aot.aot_flask.geo.facility_calc import MATERIALS
        # Outer 5 + inner 3 unique additions = 8 total
        self.assertEqual(len(MATERIALS), 8)


class TestWidgetModule(unittest.TestCase):
    def test_aot_facility_widget_info(self):
        from aot.widgets.AoT_facility import WIDGET_INFORMATION
        self.assertEqual(WIDGET_INFORMATION['widget_name_unique'], 'AoT_facility')
        self.assertIn('custom_options', WIDGET_INFORMATION)
        self.assertIn('generate_page_variables', WIDGET_INFORMATION)
        self.assertIn('execute_at_modification', WIDGET_INFORMATION)
        # Required option keys
        opt_ids = [o.get('id') for o in WIDGET_INFORMATION['custom_options'] if 'id' in o]
        for required in ['period', 'facility_uuid', 'show_ai_advice']:
            self.assertIn(required, opt_ids)


if __name__ == '__main__':
    unittest.main()
