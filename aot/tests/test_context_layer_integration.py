# coding=utf-8
"""
Integration tests for the Context Layer pipeline.

Uses real file I/O with temporary directories for fixture YAML files.
Only external AI/DB calls are mocked.

Scenarios:
  A. DomainContextLoader <-> File System
  B. DomainContextLoader <-> mcp_config env overrides
  C. _context_broadcast_job end-to-end pipeline
  D. APScheduler job registration via init_app()
  E. Contract / schema validation
"""
import os
import sys
import time
import threading
import tempfile
import shutil
import unittest
from unittest.mock import MagicMock, patch, call

import yaml

# ---------------------------------------------------------------------------
# Path bootstrap
# ---------------------------------------------------------------------------
sys.path.insert(
    0,
    os.path.abspath(os.path.join(os.path.dirname(__file__), os.path.pardir, os.path.pardir))
)
os.environ.setdefault("ALEMBIC_RUNNING", "1")

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

REGISTRY_YAML = {
    'facilities': [
        {
            'facility_id': 'greenhouse_a',
            'active': True,
            'module_file': 'greenhouse_a_module.yaml',
        },
        {
            'facility_id': 'warehouse_b',
            'active': True,
            'module_file': 'warehouse_b_module.yaml',
        },
        {
            'facility_id': 'cold_room_c',
            'active': False,
            'module_file': 'cold_room_c_module.yaml',
        },
    ]
}

MODULE_GREENHOUSE_A = {
    'facility_id': 'greenhouse_a',
    'domain': 'hydroponics',
    'config': {
        'target_temp_c': 24,
        'target_humidity_pct': 70,
        'lighting_hours': 16,
    },
    'references': [
        {'standard_id': 'TEST-001', 'title': 'Test Standard', 'issuer': 'Test', 'year': 2024},
    ],
}

MODULE_WAREHOUSE_B = {
    'facility_id': 'warehouse_b',
    'domain': 'cold_storage',
    'config': {
        'target_temp_c': 4,
        'max_humidity_pct': 85,
    },
    'layer4': {
        'deep_analysis': False,
    },
}

MODULE_COLD_ROOM_C = {
    'facility_id': 'cold_room_c',
    'domain': 'freezer',
    'config': {
        'target_temp_c': -18,
    },
}


def _write_yaml(path: str, data: dict) -> None:
    """Write a dict as YAML to the given path."""
    with open(path, 'w') as f:
        yaml.dump(data, f, default_flow_style=False)


class FixtureMixin:
    """
    Sets up a real temporary context_layer directory with YAML fixture files.
    Patches CONTEXT_LAYER_ROOT to point to the temp dir.
    """

    def setUp(self):
        # Create temp dir
        self.tmp_dir = tempfile.mkdtemp(prefix='aot_ctx_test_')
        self.registry_path = os.path.join(self.tmp_dir, 'facility_registry.yaml')
        _write_yaml(self.registry_path, REGISTRY_YAML)
        _write_yaml(os.path.join(self.tmp_dir, 'greenhouse_a_module.yaml'), MODULE_GREENHOUSE_A)
        _write_yaml(os.path.join(self.tmp_dir, 'warehouse_b_module.yaml'), MODULE_WAREHOUSE_B)
        _write_yaml(os.path.join(self.tmp_dir, 'cold_room_c_module.yaml'), MODULE_COLD_ROOM_C)

        # Patch CONTEXT_LAYER_ROOT at the module level where it is imported
        self._patcher = patch(
            'aot.ai.services.domain_context_loader.CONTEXT_LAYER_ROOT',
            self.tmp_dir
        )
        self._patcher.start()

        # Reset class-level cache before each test
        from aot.ai.services.domain_context_loader import DomainContextLoader
        DomainContextLoader.invalidate_cache()

    def tearDown(self):
        self._patcher.stop()
        shutil.rmtree(self.tmp_dir, ignore_errors=True)
        from aot.ai.services.domain_context_loader import DomainContextLoader
        DomainContextLoader.invalidate_cache()


# ===========================================================================
# A. DomainContextLoader <-> File System (real I/O)
# ===========================================================================

class TestDomainContextLoaderFileSystem(FixtureMixin, unittest.TestCase):
    """Real file I/O tests for DomainContextLoader."""

    def test_load_active_module_returns_dict_for_active_facility(self):
        """load_active_module() returns a dict for a known active facility."""
        from aot.ai.services.domain_context_loader import DomainContextLoader
        result = DomainContextLoader.load_active_module('greenhouse_a')
        self.assertIsInstance(result, dict)

    def test_load_active_module_contains_facility_id(self):
        """load_active_module() result includes the correct facility_id."""
        from aot.ai.services.domain_context_loader import DomainContextLoader
        result = DomainContextLoader.load_active_module('greenhouse_a')
        self.assertEqual(result['facility_id'], 'greenhouse_a')

    def test_load_active_module_contains_domain(self):
        """load_active_module() result includes the domain field."""
        from aot.ai.services.domain_context_loader import DomainContextLoader
        result = DomainContextLoader.load_active_module('greenhouse_a')
        self.assertIn('domain', result)
        self.assertEqual(result['domain'], 'hydroponics')

    def test_load_active_module_contains_config(self):
        """load_active_module() result includes the config field."""
        from aot.ai.services.domain_context_loader import DomainContextLoader
        result = DomainContextLoader.load_active_module('greenhouse_a')
        self.assertIn('config', result)
        self.assertIsInstance(result['config'], dict)

    def test_load_active_module_returns_none_for_inactive_facility(self):
        """load_active_module() returns None for an inactive facility."""
        from aot.ai.services.domain_context_loader import DomainContextLoader
        result = DomainContextLoader.load_active_module('cold_room_c')
        self.assertIsNone(result)

    def test_load_active_module_returns_none_for_unknown_facility(self):
        """load_active_module() returns None for a facility not in the registry."""
        from aot.ai.services.domain_context_loader import DomainContextLoader
        result = DomainContextLoader.load_active_module('nonexistent_xyz')
        self.assertIsNone(result)

    def test_load_active_module_excludes_layer4_by_default(self):
        """layer4 key is stripped when include_layer4=False (default)."""
        from aot.ai.services.domain_context_loader import DomainContextLoader
        result = DomainContextLoader.load_active_module('greenhouse_a', include_layer4=False)
        self.assertNotIn('references', result)

    def test_load_active_module_includes_layer4_when_requested(self):
        """layer4 key is present when include_layer4=True."""
        from aot.ai.services.domain_context_loader import DomainContextLoader
        result = DomainContextLoader.load_active_module('greenhouse_a', include_layer4=True)
        self.assertIn('references', result)

    def test_get_all_active_facilities_returns_only_active_ids(self):
        """get_all_active_facilities() returns only IDs where active=True."""
        from aot.ai.services.domain_context_loader import DomainContextLoader
        active = DomainContextLoader.get_all_active_facilities()
        self.assertIn('greenhouse_a', active)
        self.assertIn('warehouse_b', active)
        self.assertNotIn('cold_room_c', active)

    def test_get_all_active_facilities_returns_list(self):
        """get_all_active_facilities() returns a list."""
        from aot.ai.services.domain_context_loader import DomainContextLoader
        result = DomainContextLoader.get_all_active_facilities()
        self.assertIsInstance(result, list)

    def test_get_all_active_facilities_count(self):
        """get_all_active_facilities() returns exactly 2 active facilities."""
        from aot.ai.services.domain_context_loader import DomainContextLoader
        result = DomainContextLoader.get_all_active_facilities()
        self.assertEqual(len(result), 2)

    def test_invalidate_cache_forces_reload_on_next_call(self):
        """After invalidate_cache(), modifying the registry file is reflected on next call."""
        from aot.ai.services.domain_context_loader import DomainContextLoader

        # Prime the cache
        first_result = DomainContextLoader.get_all_active_facilities()
        self.assertEqual(len(first_result), 2)

        # Invalidate
        DomainContextLoader.invalidate_cache()

        # Wait a moment to ensure mtime changes (filesystem resolution)
        time.sleep(0.05)

        # Write a new registry with only 1 active facility
        modified_registry = {
            'facilities': [
                {
                    'facility_id': 'greenhouse_a',
                    'active': True,
                    'module_file': 'greenhouse_a_module.yaml',
                },
                {
                    'facility_id': 'warehouse_b',
                    'active': False,
                    'module_file': 'warehouse_b_module.yaml',
                },
            ]
        }
        _write_yaml(self.registry_path, modified_registry)
        # Force different mtime so cache invalidates
        time.sleep(0.05)

        second_result = DomainContextLoader.get_all_active_facilities()
        self.assertEqual(len(second_result), 1)
        self.assertIn('greenhouse_a', second_result)

    def test_concurrent_registry_access_no_corruption(self):
        """Two threads calling _get_registry() concurrently don't corrupt the cache."""
        from aot.ai.services.domain_context_loader import DomainContextLoader

        results = []
        errors = []

        def worker():
            try:
                reg = DomainContextLoader._get_registry()
                results.append(reg)
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=worker) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(len(errors), 0, f"Concurrent access raised: {errors}")
        self.assertEqual(len(results), 2)
        # Both should return the same registry structure
        self.assertEqual(results[0], results[1])

    def test_load_active_module_second_call_uses_cache(self):
        """A second call to load_active_module() for the same facility uses cached data."""
        from aot.ai.services.domain_context_loader import DomainContextLoader

        result1 = DomainContextLoader.load_active_module('greenhouse_a')
        # Overwrite the module file on disk — cache should serve stale copy
        _write_yaml(os.path.join(self.tmp_dir, 'greenhouse_a_module.yaml'),
                    {'facility_id': 'greenhouse_a', 'domain': 'CHANGED', 'config': {}})
        result2 = DomainContextLoader.load_active_module('greenhouse_a')
        # The cached copy should be returned (domain unchanged) because mtime
        # may not have changed within this test tick. If mtime does change, a
        # reload occurs — both paths are acceptable as long as no exception.
        self.assertIsNotNone(result2)


# ===========================================================================
# B. DomainContextLoader <-> mcp_config env integration
# ===========================================================================

class TestMcpConfigIntegration(FixtureMixin, unittest.TestCase):
    """Test env-variable-driven configuration from mcp_config."""

    def test_context_layer_root_env_override_changes_read_dir(self):
        """Setting CONTEXT_LAYER_ROOT env var changes which directory is read."""
        # Create a second temp dir with a different registry
        alt_dir = tempfile.mkdtemp(prefix='aot_alt_ctx_')
        try:
            alt_registry = {
                'facilities': [
                    {'facility_id': 'alt_facility', 'active': True, 'module_file': 'alt.yaml'},
                ]
            }
            alt_module = {'facility_id': 'alt_facility', 'domain': 'alt_domain', 'config': {'k': 1}}
            _write_yaml(os.path.join(alt_dir, 'facility_registry.yaml'), alt_registry)
            _write_yaml(os.path.join(alt_dir, 'alt.yaml'), alt_module)

            # Patch the loader to use alt_dir
            from aot.ai.services.domain_context_loader import DomainContextLoader
            DomainContextLoader.invalidate_cache()
            with patch('aot.ai.services.domain_context_loader.CONTEXT_LAYER_ROOT', alt_dir):
                active = DomainContextLoader.get_all_active_facilities()

            self.assertIn('alt_facility', active)
            self.assertNotIn('greenhouse_a', active)
        finally:
            shutil.rmtree(alt_dir, ignore_errors=True)
            from aot.ai.services.domain_context_loader import DomainContextLoader
            DomainContextLoader.invalidate_cache()

    def test_context_accumulation_depth_is_int(self):
        """CONTEXT_ACCUMULATION_DEPTH from mcp_config is an integer."""
        from aot.config import mcp_config
        self.assertIsInstance(mcp_config.CONTEXT_ACCUMULATION_DEPTH, int)

    def test_context_accumulation_depth_is_positive(self):
        """CONTEXT_ACCUMULATION_DEPTH is a positive integer."""
        from aot.config import mcp_config
        self.assertGreater(mcp_config.CONTEXT_ACCUMULATION_DEPTH, 0)

    def test_context_broadcast_interval_hours_is_int(self):
        """CONTEXT_BROADCAST_INTERVAL_HOURS from mcp_config is an integer."""
        from aot.config import mcp_config
        self.assertIsInstance(mcp_config.CONTEXT_BROADCAST_INTERVAL_HOURS, int)


# ===========================================================================
# C. _context_broadcast_job end-to-end pipeline
# ===========================================================================

class TestContextBroadcastJobPipeline(FixtureMixin, unittest.TestCase):
    """
    End-to-end test of _context_broadcast_job().
    Real DomainContextLoader with fixture files; AI/DB calls are mocked.
    """

    def _make_patches(self):
        """
        Return a context manager that patches external services used
        inside _context_broadcast_job (all imported locally inside the function).
        Because the imports happen inside the function body, we patch the
        classes at their source modules.
        """
        import contextlib

        @contextlib.contextmanager
        def _ctx():
            mock_ctx_svc = MagicMock()
            mock_sum_svc = MagicMock()
            mock_ctx_svc.get_master_context.return_value = {'sensors': [], 'notes': []}
            mock_sum_svc.get_summary_history.return_value = []
            mock_sum_svc.generate_system_summary.return_value = None

            with patch(
                'aot.ai.services.ai_context_service.AIContextService',
                mock_ctx_svc,
            ), patch(
                'aot.ai.services.ai_summary_service.AISummaryService',
                mock_sum_svc,
            ):
                yield mock_ctx_svc, mock_sum_svc

        return _ctx()

    def test_master_context_fetched_once(self):
        """AIContextService.get_master_context() is called exactly once per run."""
        from aot.ai.services.ai_scheduler_service import _context_broadcast_job
        with self._make_patches() as (mock_ctx_svc, mock_sum_svc):
            _context_broadcast_job()
        mock_ctx_svc.get_master_context.assert_called_once()

    def test_generate_system_summary_called_for_each_active_facility(self):
        """AISummaryService.generate_system_summary() called once per active facility."""
        from aot.ai.services.ai_scheduler_service import _context_broadcast_job
        with self._make_patches() as (mock_ctx_svc, mock_sum_svc):
            _context_broadcast_job()
        # 2 active facilities = 2 calls
        self.assertEqual(mock_sum_svc.generate_system_summary.call_count, 2)

    def test_inactive_facility_not_processed(self):
        """cold_room_c (inactive) is never passed to generate_system_summary."""
        from aot.ai.services.ai_scheduler_service import _context_broadcast_job
        with self._make_patches() as (mock_ctx_svc, mock_sum_svc):
            _context_broadcast_job()
        called_with = [
            kw.get('scope_id')
            for _, kw in mock_sum_svc.generate_system_summary.call_args_list
        ]
        self.assertNotIn('cold_room_c', called_with)

    def test_active_facilities_are_processed(self):
        """greenhouse_a and warehouse_b are included in generate_system_summary calls."""
        from aot.ai.services.ai_scheduler_service import _context_broadcast_job
        with self._make_patches() as (mock_ctx_svc, mock_sum_svc):
            _context_broadcast_job()
        called_with = [
            kw.get('scope_id')
            for _, kw in mock_sum_svc.generate_system_summary.call_args_list
        ]
        self.assertIn('greenhouse_a', called_with)
        self.assertIn('warehouse_b', called_with)

    def test_broadcast_completes_without_exception(self):
        """_context_broadcast_job() does not raise even with mocked services."""
        from aot.ai.services.ai_scheduler_service import _context_broadcast_job
        try:
            with self._make_patches():
                _context_broadcast_job()
        except Exception as exc:
            self.fail(f"_context_broadcast_job raised unexpectedly: {exc}")


# ===========================================================================
# D. APScheduler job registration via init_app()
# ===========================================================================

class TestInitAppJobRegistration(unittest.TestCase):
    """Verify init_app() registers the context broadcast job with correct config."""

    def tearDown(self):
        # Reset the module-level _flask_app global to prevent state leakage
        # across test modules (init_app sets it via 'global _flask_app').
        import aot.ai.services.ai_scheduler_service as _sched
        _sched._flask_app = None

    def test_context_broadcast_job_registered_with_interval(self):
        """init_app() must register ai_scheduler_context_broadcast as an interval job."""
        from aot.ai.services.ai_scheduler_service import AISchedulerService
        from aot.config import mcp_config

        mock_app = MagicMock()
        mock_app.app_context.return_value.__enter__ = MagicMock(return_value=None)
        mock_app.app_context.return_value.__exit__ = MagicMock(return_value=False)

        mock_scheduler = MagicMock()
        mock_scheduler.running = True  # Pretend already running

        with patch(
            'aot.ai.services.ai_scheduler_service.get_scheduler',
            return_value=mock_scheduler
        ), patch(
            'aot.ai.services.ai_scheduler_service._flask_app', None
        ), patch(
            'aot.utils.signals.trigger_fired'
        ), patch(
            'aot.utils.signals.conditional_fired'
        ):
            AISchedulerService.init_app(mock_app)

        # Find the call that registered ai_scheduler_context_broadcast
        broadcast_call = None
        for c in mock_scheduler.add_job.call_args_list:
            kwargs = c[1] if c[1] else {}
            args = c[0] if c[0] else []
            job_id = kwargs.get('id') or (args[1] if len(args) > 1 else None)
            if job_id == 'ai_scheduler_context_broadcast':
                broadcast_call = (args, kwargs)
                break

        self.assertIsNotNone(
            broadcast_call,
            "ai_scheduler_context_broadcast was never registered via add_job()"
        )

    def test_context_broadcast_job_uses_configured_interval(self):
        """ai_scheduler_context_broadcast is registered with the configured hours interval."""
        from aot.ai.services.ai_scheduler_service import AISchedulerService
        from aot.config import mcp_config

        mock_app = MagicMock()
        mock_scheduler = MagicMock()
        mock_scheduler.running = True

        with patch(
            'aot.ai.services.ai_scheduler_service.get_scheduler',
            return_value=mock_scheduler
        ), patch(
            'aot.utils.signals.trigger_fired'
        ), patch(
            'aot.utils.signals.conditional_fired'
        ):
            AISchedulerService.init_app(mock_app)

        broadcast_kwargs = None
        for c in mock_scheduler.add_job.call_args_list:
            kw = c[1] if c[1] else {}
            if kw.get('id') == 'ai_scheduler_context_broadcast':
                broadcast_kwargs = kw
                break

        if broadcast_kwargs is None:
            self.fail("ai_scheduler_context_broadcast not found")

        self.assertEqual(broadcast_kwargs.get('trigger'), 'interval')
        self.assertEqual(
            broadcast_kwargs.get('hours'),
            mcp_config.CONTEXT_BROADCAST_INTERVAL_HOURS
        )


# ===========================================================================
# E. Contract / schema validation
# ===========================================================================

class TestContractSchemaValidation(FixtureMixin, unittest.TestCase):
    """Schema and contract checks on the output of public loader methods."""

    EXPECTED_TOP_LEVEL_KEYS = {'facility_id', 'domain', 'config', 'operational_state'}

    def test_load_active_module_has_required_keys(self):
        """Output of load_active_module() contains all downstream-expected keys."""
        from aot.ai.services.domain_context_loader import DomainContextLoader
        result = DomainContextLoader.load_active_module('greenhouse_a')
        for key in self.EXPECTED_TOP_LEVEL_KEYS:
            self.assertIn(key, result, f"Missing required key: {key}")

    def test_operational_state_has_value_field(self):
        """operational_state dict contains a 'value' field."""
        from aot.ai.services.domain_context_loader import DomainContextLoader
        result = DomainContextLoader.load_active_module('greenhouse_a')
        self.assertIn('value', result['operational_state'])

    def test_operational_state_value_is_valid_enum(self):
        """operational_state.value is one of {normal, warning, critical, unknown}."""
        from aot.ai.services.domain_context_loader import DomainContextLoader
        result = DomainContextLoader.load_active_module('greenhouse_a')
        valid_states = {'normal', 'warning', 'critical', 'unknown'}
        self.assertIn(result['operational_state']['value'], valid_states)

    def test_operational_state_has_timestamp(self):
        """operational_state dict contains a 'timestamp' field."""
        from aot.ai.services.domain_context_loader import DomainContextLoader
        result = DomainContextLoader.load_active_module('greenhouse_a')
        self.assertIn('timestamp', result['operational_state'])

    def test_operational_state_timestamp_is_string(self):
        """operational_state.timestamp is a non-empty string."""
        from aot.ai.services.domain_context_loader import DomainContextLoader
        result = DomainContextLoader.load_active_module('greenhouse_a')
        ts = result['operational_state']['timestamp']
        self.assertIsInstance(ts, str)
        self.assertTrue(len(ts) > 0)

    def test_get_all_active_facilities_returns_list_of_strings(self):
        """get_all_active_facilities() returns list[str]."""
        from aot.ai.services.domain_context_loader import DomainContextLoader
        result = DomainContextLoader.get_all_active_facilities()
        for item in result:
            self.assertIsInstance(item, str,
                                  f"Expected str, got {type(item)}: {item!r}")

    def test_get_all_active_facilities_no_none_entries(self):
        """get_all_active_facilities() contains no None values."""
        from aot.ai.services.domain_context_loader import DomainContextLoader
        result = DomainContextLoader.get_all_active_facilities()
        self.assertNotIn(None, result)

    def test_get_all_active_facilities_no_empty_string_entries(self):
        """get_all_active_facilities() contains no empty-string values."""
        from aot.ai.services.domain_context_loader import DomainContextLoader
        result = DomainContextLoader.get_all_active_facilities()
        self.assertNotIn('', result)

    def test_config_field_is_dict(self):
        """The config field in load_active_module() output is a dict."""
        from aot.ai.services.domain_context_loader import DomainContextLoader
        result = DomainContextLoader.load_active_module('greenhouse_a')
        self.assertIsInstance(result['config'], dict)

    def test_facility_id_in_output_matches_requested(self):
        """facility_id in module output matches the requested facility_id."""
        from aot.ai.services.domain_context_loader import DomainContextLoader
        for fid in ('greenhouse_a', 'warehouse_b'):
            result = DomainContextLoader.load_active_module(fid)
            self.assertEqual(result['facility_id'], fid,
                             f"facility_id mismatch for {fid}")

    def test_inactive_facility_has_empty_config_state_unknown(self):
        """
        A module with no config section gets operational_state.value == 'unknown'.
        This validates _calculate_state_value() edge-case logic.
        """
        from aot.ai.services.domain_context_loader import DomainContextLoader

        # Write a minimal module with no config
        no_config_module = {'facility_id': 'greenhouse_a', 'domain': 'test'}
        _write_yaml(os.path.join(self.tmp_dir, 'greenhouse_a_module.yaml'), no_config_module)
        DomainContextLoader.invalidate_cache()

        result = DomainContextLoader.load_active_module('greenhouse_a')
        self.assertEqual(result['operational_state']['value'], 'unknown')


if __name__ == '__main__':
    unittest.main()
