# coding=utf-8
"""
TDD tests for the Context Layer pipeline skeleton.

Covers:
  - domain_context_loader.py   — DomainContextLoader class (all public and private methods)
  - ai_scheduler_service.py    — _context_broadcast_job() 6-step sequence
  - mcp_config.py              — CONTEXT_LAYER_ROOT, CONTEXT_BROADCAST_INTERVAL_HOURS,
                                  CONTEXT_ACCUMULATION_DEPTH configuration variables

All external I/O (filesystem, DB, APScheduler, Flask app, LLM) is mocked.
No real file reads, sensor calls, or API requests are made.

These tests are written BEFORE business logic is implemented (TDD).
They document the expected final behavior and will initially FAIL.
"""
import os
import sys
import types
import unittest
from unittest.mock import ANY, MagicMock, patch, mock_open, call, PropertyMock

# ---------------------------------------------------------------------------
# Path bootstrap — mirrors every other test in this package
# ---------------------------------------------------------------------------
sys.path.insert(
    0,
    os.path.abspath(os.path.join(os.path.dirname(__file__), os.path.pardir, os.path.pardir))
)

# Prevent automatic Alembic migration during import
os.environ.setdefault("ALEMBIC_RUNNING", "1")

# ---------------------------------------------------------------------------
# Shared YAML fixtures used across test classes
# ---------------------------------------------------------------------------

# Minimal valid facility registry content (parsed dict form)
SAMPLE_REGISTRY = {
    'facilities': [
        {
            'facility_id': 'greenhouse_a',
            'active': True,
            'module_file': 'greenhouse_a/domain_module.yaml',
        },
        {
            'facility_id': 'greenhouse_b',
            'active': True,
            'module_file': 'greenhouse_b/domain_module.yaml',
        },
        {
            'facility_id': 'cold_room_c',
            'active': False,
            'module_file': 'cold_room_c/domain_module.yaml',
        },
    ]
}

# Minimal valid domain module content (parsed dict form)
SAMPLE_MODULE = {
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


# ===========================================================================
# 1. DomainContextLoader — _get_registry()
# ===========================================================================

from aot.ai.services.domain_context_loader import DomainContextLoader


class TestGetRegistry(unittest.TestCase):
    """DomainContextLoader._get_registry() — cache + mtime invalidation.

    ⚠ `os.path.exists` must be patched in every test here. `_get_registry()`
    gained an early return for a missing registry file on 2026-08-10 (4384513d
    — "a missing registry file is a normal state, not a failure"), and the test
    environment has no `facility_registry.yaml`. Without the patch the method
    returns `{}` before it ever reaches the mocked open/safe_load, so the test
    measures nothing about caching. Six of these tests silently became that,
    and `test_returns_dict` still PASSED because `{}` is a dict — a test can go
    hollow without going red. The missing-file path has its own test below.
    """

    def setUp(self):
        # Reset all class-level cache state before each test
        DomainContextLoader._registry_cache = {}
        DomainContextLoader._registry_mtime = 0.0
        DomainContextLoader._module_cache = {}
        DomainContextLoader._module_mtimes = {}

    # --- Cache miss: file is loaded for the first time ----------------------

    @patch('aot.ai.services.domain_context_loader.yaml.safe_load', return_value=SAMPLE_REGISTRY)
    @patch('builtins.open', mock_open(read_data=''))
    @patch('os.path.getmtime', return_value=1000.0)
    @patch('os.path.exists', return_value=True)
    def test_cache_miss_loads_registry_from_disk(self, mock_exists, mock_mtime,
                                                 mock_yaml):
        """When cache is empty, _get_registry() reads and returns the YAML file."""
        result = DomainContextLoader._get_registry()
        self.assertEqual(result, SAMPLE_REGISTRY)

    @patch('aot.ai.services.domain_context_loader.yaml.safe_load', return_value=SAMPLE_REGISTRY)
    @patch('builtins.open', mock_open(read_data=''))
    @patch('os.path.getmtime', return_value=1000.0)
    @patch('os.path.exists', return_value=True)
    def test_cache_miss_populates_registry_cache(self, mock_exists, mock_mtime,
                                                 mock_yaml):
        """After a cache miss, _registry_cache must be populated."""
        DomainContextLoader._get_registry()
        self.assertEqual(DomainContextLoader._registry_cache, SAMPLE_REGISTRY)

    @patch('aot.ai.services.domain_context_loader.yaml.safe_load', return_value=SAMPLE_REGISTRY)
    @patch('builtins.open', mock_open(read_data=''))
    @patch('os.path.getmtime', return_value=1000.0)
    @patch('os.path.exists', return_value=True)
    def test_cache_miss_stores_mtime(self, mock_exists, mock_mtime, mock_yaml):
        """After a cache miss, _registry_mtime must be updated."""
        DomainContextLoader._get_registry()
        self.assertEqual(DomainContextLoader._registry_mtime, 1000.0)

    # --- Cache hit: file is NOT reloaded ------------------------------------

    @patch('os.path.getmtime', return_value=1000.0)
    @patch('builtins.open', mock_open(read_data=''))
    @patch('aot.ai.services.domain_context_loader.yaml.safe_load')
    @patch('os.path.exists', return_value=True)
    def test_cache_hit_returns_cached_without_reloading(self, mock_exists,
                                                        mock_yaml, mock_mtime):
        """When cache is warm and mtime unchanged, yaml.safe_load is NOT called again."""
        DomainContextLoader._registry_cache = SAMPLE_REGISTRY
        DomainContextLoader._registry_mtime = 1000.0  # same as mock_mtime

        result = DomainContextLoader._get_registry()

        mock_yaml.assert_not_called()
        self.assertEqual(result, SAMPLE_REGISTRY)

    # --- Stale cache: file changed on disk → must reload --------------------

    @patch('aot.ai.services.domain_context_loader.yaml.safe_load', return_value=SAMPLE_REGISTRY)
    @patch('builtins.open', mock_open(read_data=''))
    @patch('os.path.getmtime', return_value=2000.0)  # newer than cached 1000.0
    @patch('os.path.exists', return_value=True)
    def test_stale_mtime_triggers_reload(self, mock_exists, mock_mtime,
                                         mock_yaml):
        """When disk mtime > cached mtime, the registry file must be reloaded."""
        DomainContextLoader._registry_cache = {'facilities': []}
        DomainContextLoader._registry_mtime = 1000.0

        DomainContextLoader._get_registry()

        mock_yaml.assert_called_once()

    @patch('aot.ai.services.domain_context_loader.yaml.safe_load', return_value=SAMPLE_REGISTRY)
    @patch('builtins.open', mock_open(read_data=''))
    @patch('os.path.getmtime', return_value=2000.0)
    @patch('os.path.exists', return_value=True)
    def test_stale_mtime_updates_cached_mtime(self, mock_exists, mock_mtime,
                                              mock_yaml):
        """After a stale reload, _registry_mtime must be updated to the new mtime."""
        DomainContextLoader._registry_cache = {}
        DomainContextLoader._registry_mtime = 1000.0

        DomainContextLoader._get_registry()

        self.assertEqual(DomainContextLoader._registry_mtime, 2000.0)

    # --- Return type contract -----------------------------------------------

    @patch('aot.ai.services.domain_context_loader.yaml.safe_load', return_value=SAMPLE_REGISTRY)
    @patch('builtins.open', mock_open(read_data=''))
    @patch('os.path.getmtime', return_value=1000.0)
    @patch('os.path.exists', return_value=True)
    def test_returns_dict(self, mock_exists, mock_mtime, mock_yaml):
        result = DomainContextLoader._get_registry()
        self.assertIsInstance(result, dict)

    # --- Missing registry file: a normal state, not a failure ---------------

    @patch('os.path.exists', return_value=False)
    def test_missing_registry_file_returns_empty_and_drops_cache(self,
                                                                 mock_exists):
        """등록된 도메인 모듈이 없는 설치가 정상이다(4384513d).

        빈 dict 를 돌려주지 않고 예외를 던지면 `_context_broadcast_job` 이 매
        주기마다 "Step 1 failed: No such file or directory" 를 남겨, 멀쩡한
        설치가 고장난 것처럼 읽힌다.

        캐시까지 비우는 것이 핵심이다 — 파일이 지워진 뒤에도 예전 목록을 계속
        내주면 없어진 시설이 살아 있는 것처럼 보인다.
        """
        DomainContextLoader._registry_cache = SAMPLE_REGISTRY
        DomainContextLoader._registry_mtime = 1000.0

        self.assertEqual(DomainContextLoader._get_registry(), {})
        self.assertEqual(DomainContextLoader._registry_cache, {})
        self.assertEqual(DomainContextLoader._registry_mtime, 0.0)


# ===========================================================================
# 2. DomainContextLoader — _load_module_file()
# ===========================================================================

class TestLoadModuleFile(unittest.TestCase):
    """DomainContextLoader._load_module_file() — per-facility cache + error paths."""

    def setUp(self):
        DomainContextLoader._registry_cache = {}
        DomainContextLoader._registry_mtime = 0.0
        DomainContextLoader._module_cache = {}
        DomainContextLoader._module_mtimes = {}

    VALID_ENTRY = {
        'facility_id': 'greenhouse_a',
        'module_file': 'greenhouse_a/domain_module.yaml',
    }

    # --- Happy path: valid entry loads module --------------------------------

    @patch('aot.ai.services.domain_context_loader.yaml.safe_load', return_value=SAMPLE_MODULE)
    @patch('builtins.open', mock_open(read_data=''))
    @patch('os.path.getmtime', return_value=1000.0)
    @patch('os.path.exists', return_value=True)
    def test_valid_entry_returns_module_dict(self, mock_exists, mock_mtime,
                                             mock_yaml):
        result = DomainContextLoader._load_module_file(self.VALID_ENTRY)
        self.assertEqual(result, SAMPLE_MODULE)

    @patch('aot.ai.services.domain_context_loader.yaml.safe_load', return_value=SAMPLE_MODULE)
    @patch('builtins.open', mock_open(read_data=''))
    @patch('os.path.getmtime', return_value=1000.0)
    @patch('os.path.exists', return_value=True)
    def test_valid_entry_caches_result(self, mock_exists, mock_mtime,
                                       mock_yaml):
        DomainContextLoader._load_module_file(self.VALID_ENTRY)
        self.assertIn('greenhouse_a', DomainContextLoader._module_cache)
        self.assertEqual(DomainContextLoader._module_cache['greenhouse_a'], SAMPLE_MODULE)

    # --- Cache hit: module file not reloaded when mtime unchanged -----------

    @patch('os.path.getmtime', return_value=1000.0)
    @patch('os.path.exists', return_value=True)
    @patch('aot.ai.services.domain_context_loader.yaml.safe_load')
    def test_cache_hit_does_not_reload(self, mock_yaml, mock_exists, mock_mtime):
        DomainContextLoader._module_cache['greenhouse_a'] = SAMPLE_MODULE
        DomainContextLoader._module_mtimes['greenhouse_a'] = 1000.0

        DomainContextLoader._load_module_file(self.VALID_ENTRY)

        mock_yaml.assert_not_called()

    # --- Missing file returns None ------------------------------------------

    @patch('os.path.exists', return_value=False)
    def test_missing_file_returns_none(self, mock_exists):
        result = DomainContextLoader._load_module_file(self.VALID_ENTRY)
        self.assertIsNone(result)

    # --- Malformed YAML returns None ----------------------------------------

    @patch('aot.ai.services.domain_context_loader.yaml.safe_load',
           side_effect=Exception("YAML parse error"))
    @patch('builtins.open', mock_open(read_data='bad: yaml: !!!'))
    @patch('os.path.getmtime', return_value=1000.0)
    @patch('os.path.exists', return_value=True)
    def test_malformed_yaml_returns_none(self, mock_exists, mock_mtime,
                                         mock_yaml):
        result = DomainContextLoader._load_module_file(self.VALID_ENTRY)
        self.assertIsNone(result)

    # --- Stale per-facility cache reloads when mtime changed ----------------

    @patch('aot.ai.services.domain_context_loader.yaml.safe_load', return_value=SAMPLE_MODULE)
    @patch('builtins.open', mock_open(read_data=''))
    @patch('os.path.getmtime', return_value=9999.0)
    @patch('os.path.exists', return_value=True)
    def test_stale_module_cache_triggers_reload(self, mock_exists, mock_mtime,
                                                 mock_yaml):
        DomainContextLoader._module_cache['greenhouse_a'] = SAMPLE_MODULE
        DomainContextLoader._module_mtimes['greenhouse_a'] = 1000.0  # stale

        DomainContextLoader._load_module_file(self.VALID_ENTRY)

        mock_yaml.assert_called_once()


# ===========================================================================
# 3. DomainContextLoader — _resolve_operational_state()
# ===========================================================================

class TestResolveOperationalState(unittest.TestCase):
    """DomainContextLoader._resolve_operational_state() — output contract."""

    def setUp(self):
        DomainContextLoader._registry_cache = {}
        DomainContextLoader._registry_mtime = 0.0
        DomainContextLoader._module_cache = {}
        DomainContextLoader._module_mtimes = {}

    def test_returns_dict(self):
        result = DomainContextLoader._resolve_operational_state(SAMPLE_MODULE)
        self.assertIsInstance(result, dict)

    def test_result_contains_operational_state_key(self):
        """The resolved module must contain the 'operational_state' key."""
        result = DomainContextLoader._resolve_operational_state(SAMPLE_MODULE)
        self.assertIn('operational_state', result)

    def test_original_module_keys_are_preserved(self):
        """All original module fields must survive augmentation."""
        result = DomainContextLoader._resolve_operational_state(SAMPLE_MODULE)
        self.assertIn('facility_id', result)
        self.assertIn('domain', result)
        self.assertIn('config', result)

    def test_operational_state_is_dict(self):
        result = DomainContextLoader._resolve_operational_state(SAMPLE_MODULE)
        self.assertIsInstance(result['operational_state'], dict)

    def test_operational_state_has_value_key(self):
        """operational_state dict must expose a 'value' entry."""
        result = DomainContextLoader._resolve_operational_state(SAMPLE_MODULE)
        self.assertIn('value', result['operational_state'])

    def test_operational_state_has_timestamp_key(self):
        """operational_state dict must expose a 'timestamp' entry."""
        result = DomainContextLoader._resolve_operational_state(SAMPLE_MODULE)
        self.assertIn('timestamp', result['operational_state'])


# ===========================================================================
# 4. DomainContextLoader — _calculate_state_value()
# ===========================================================================

class TestCalculateStateValue(unittest.TestCase):
    """DomainContextLoader._calculate_state_value() — return type contract."""

    def setUp(self):
        DomainContextLoader._registry_cache = {}
        DomainContextLoader._registry_mtime = 0.0
        DomainContextLoader._module_cache = {}
        DomainContextLoader._module_mtimes = {}

    def test_returns_string(self):
        result = DomainContextLoader._calculate_state_value(SAMPLE_MODULE['config'])
        self.assertIsInstance(result, str)

    def test_result_is_non_empty_string(self):
        result = DomainContextLoader._calculate_state_value(SAMPLE_MODULE['config'])
        self.assertTrue(len(result) > 0)

    def test_empty_config_returns_string(self):
        """Even with an empty config dict the method must return a valid string."""
        result = DomainContextLoader._calculate_state_value({})
        self.assertIsInstance(result, str)

    def test_result_is_valid_state_label(self):
        """Return value must be one of the known operational state labels."""
        valid_states = {'normal', 'warning', 'critical', 'unknown'}
        result = DomainContextLoader._calculate_state_value(SAMPLE_MODULE['config'])
        self.assertIn(result, valid_states)


# ===========================================================================
# 5. DomainContextLoader — load_active_module()
# ===========================================================================

class TestLoadActiveModule(unittest.TestCase):
    """DomainContextLoader.load_active_module() — public API contract."""

    def setUp(self):
        DomainContextLoader._registry_cache = {}
        DomainContextLoader._registry_mtime = 0.0
        DomainContextLoader._module_cache = {}
        DomainContextLoader._module_mtimes = {}

    # --- Happy path: valid facility_id --------------------------------------

    def test_valid_facility_id_returns_dict(self):
        """load_active_module() with a known active facility_id returns a dict."""
        resolved_module = dict(SAMPLE_MODULE)
        resolved_module['operational_state'] = {'value': 'normal', 'timestamp': '2026-03-25T00:00:00Z'}

        with patch.object(DomainContextLoader, '_get_registry', return_value=SAMPLE_REGISTRY), \
             patch.object(DomainContextLoader, '_load_module_file', return_value=SAMPLE_MODULE), \
             patch.object(DomainContextLoader, '_resolve_operational_state',
                          return_value=resolved_module):
            result = DomainContextLoader.load_active_module('greenhouse_a')

        self.assertIsInstance(result, dict)

    def test_valid_facility_id_result_contains_operational_state(self):
        resolved_module = dict(SAMPLE_MODULE)
        resolved_module['operational_state'] = {'value': 'normal', 'timestamp': '2026-03-25T00:00:00Z'}

        with patch.object(DomainContextLoader, '_get_registry', return_value=SAMPLE_REGISTRY), \
             patch.object(DomainContextLoader, '_load_module_file', return_value=SAMPLE_MODULE), \
             patch.object(DomainContextLoader, '_resolve_operational_state',
                          return_value=resolved_module):
            result = DomainContextLoader.load_active_module('greenhouse_a')

        self.assertIn('operational_state', result)

    # --- Invalid / unknown facility_id returns None -------------------------

    def test_unknown_facility_id_returns_none(self):
        """An unregistered facility_id must return None."""
        with patch.object(DomainContextLoader, '_get_registry', return_value=SAMPLE_REGISTRY):
            result = DomainContextLoader.load_active_module('does_not_exist')
        self.assertIsNone(result)

    def test_inactive_facility_returns_none(self):
        """A registered but inactive facility (active=False) must return None."""
        with patch.object(DomainContextLoader, '_get_registry', return_value=SAMPLE_REGISTRY):
            result = DomainContextLoader.load_active_module('cold_room_c')
        self.assertIsNone(result)

    # --- include_layer4 flag behavior ---------------------------------------

    def test_include_layer4_false_strips_layer4_key(self):
        """When include_layer4=False, the 'layer4' key must not appear in the result."""
        resolved_module = dict(SAMPLE_MODULE)
        resolved_module['operational_state'] = {'value': 'normal', 'timestamp': '2026-03-25T00:00:00Z'}

        with patch.object(DomainContextLoader, '_get_registry', return_value=SAMPLE_REGISTRY), \
             patch.object(DomainContextLoader, '_load_module_file', return_value=dict(SAMPLE_MODULE)), \
             patch.object(DomainContextLoader, '_resolve_operational_state',
                          return_value=resolved_module):
            result = DomainContextLoader.load_active_module('greenhouse_a', include_layer4=False)

        if result is not None:
            self.assertNotIn('references', result)

    def test_include_layer4_true_preserves_layer4_key(self):
        """When include_layer4=True, the 'layer4' key must appear in the result."""
        module_with_layer4 = dict(SAMPLE_MODULE)
        module_with_layer4['operational_state'] = {'value': 'normal', 'timestamp': '2026-03-25T00:00:00Z'}

        with patch.object(DomainContextLoader, '_get_registry', return_value=SAMPLE_REGISTRY), \
             patch.object(DomainContextLoader, '_load_module_file',
                          return_value=dict(SAMPLE_MODULE)), \
             patch.object(DomainContextLoader, '_resolve_operational_state',
                          return_value=module_with_layer4):
            result = DomainContextLoader.load_active_module('greenhouse_a', include_layer4=True)

        if result is not None:
            self.assertIn('references', result)

    # --- Call hierarchy: internal helpers are invoked -----------------------

    def test_load_active_module_calls_get_registry(self):
        with patch.object(DomainContextLoader, '_get_registry', return_value=SAMPLE_REGISTRY) as mock_reg, \
             patch.object(DomainContextLoader, '_load_module_file', return_value=SAMPLE_MODULE), \
             patch.object(DomainContextLoader, '_resolve_operational_state',
                          return_value=SAMPLE_MODULE):
            DomainContextLoader.load_active_module('greenhouse_a')
        mock_reg.assert_called_once()

    def test_load_active_module_calls_load_module_file(self):
        with patch.object(DomainContextLoader, '_get_registry', return_value=SAMPLE_REGISTRY), \
             patch.object(DomainContextLoader, '_load_module_file',
                          return_value=SAMPLE_MODULE) as mock_load, \
             patch.object(DomainContextLoader, '_resolve_operational_state',
                          return_value=SAMPLE_MODULE):
            DomainContextLoader.load_active_module('greenhouse_a')
        mock_load.assert_called_once()

    def test_load_active_module_calls_resolve_operational_state(self):
        with patch.object(DomainContextLoader, '_get_registry', return_value=SAMPLE_REGISTRY), \
             patch.object(DomainContextLoader, '_load_module_file', return_value=SAMPLE_MODULE), \
             patch.object(DomainContextLoader, '_resolve_operational_state',
                          return_value=SAMPLE_MODULE) as mock_resolve:
            DomainContextLoader.load_active_module('greenhouse_a')
        mock_resolve.assert_called_once_with(SAMPLE_MODULE, registry_entry=ANY)

    # --- Module file missing returns None -----------------------------------

    def test_module_file_missing_returns_none(self):
        """If _load_module_file returns None the whole call must return None."""
        with patch.object(DomainContextLoader, '_get_registry', return_value=SAMPLE_REGISTRY), \
             patch.object(DomainContextLoader, '_load_module_file', return_value=None):
            result = DomainContextLoader.load_active_module('greenhouse_a')
        self.assertIsNone(result)


# ===========================================================================
# 6. DomainContextLoader — get_all_active_facilities()
# ===========================================================================

class TestGetAllActiveFacilities(unittest.TestCase):
    """DomainContextLoader.get_all_active_facilities() — list contract."""

    def setUp(self):
        DomainContextLoader._registry_cache = {}
        DomainContextLoader._registry_mtime = 0.0
        DomainContextLoader._module_cache = {}
        DomainContextLoader._module_mtimes = {}

    def test_returns_list(self):
        with patch.object(DomainContextLoader, '_get_registry', return_value=SAMPLE_REGISTRY):
            result = DomainContextLoader.get_all_active_facilities()
        self.assertIsInstance(result, list)

    def test_returns_only_active_facility_ids(self):
        """Only facilities with active=True must appear in the result."""
        with patch.object(DomainContextLoader, '_get_registry', return_value=SAMPLE_REGISTRY):
            result = DomainContextLoader.get_all_active_facilities()
        # greenhouse_a and greenhouse_b are active; cold_room_c is not
        self.assertIn('greenhouse_a', result)
        self.assertIn('greenhouse_b', result)
        self.assertNotIn('cold_room_c', result)

    def test_inactive_facilities_excluded(self):
        """cold_room_c (active=False) must never appear in the result."""
        with patch.object(DomainContextLoader, '_get_registry', return_value=SAMPLE_REGISTRY):
            result = DomainContextLoader.get_all_active_facilities()
        self.assertNotIn('cold_room_c', result)

    def test_returns_list_of_strings(self):
        """Every element in the returned list must be a str."""
        with patch.object(DomainContextLoader, '_get_registry', return_value=SAMPLE_REGISTRY):
            result = DomainContextLoader.get_all_active_facilities()
        for item in result:
            self.assertIsInstance(item, str)

    def test_empty_registry_returns_empty_list(self):
        empty_registry = {'facilities': []}
        with patch.object(DomainContextLoader, '_get_registry', return_value=empty_registry):
            result = DomainContextLoader.get_all_active_facilities()
        self.assertEqual(result, [])

    def test_calls_get_registry(self):
        """get_all_active_facilities() must delegate to _get_registry()."""
        with patch.object(DomainContextLoader, '_get_registry',
                          return_value=SAMPLE_REGISTRY) as mock_reg:
            DomainContextLoader.get_all_active_facilities()
        mock_reg.assert_called_once()

    def test_count_matches_active_count_in_registry(self):
        """The length of the result must equal the number of active entries."""
        with patch.object(DomainContextLoader, '_get_registry', return_value=SAMPLE_REGISTRY):
            result = DomainContextLoader.get_all_active_facilities()
        # SAMPLE_REGISTRY has 2 active, 1 inactive
        self.assertEqual(len(result), 2)


# ===========================================================================
# 7. DomainContextLoader — invalidate_cache()
# ===========================================================================

class TestInvalidateCache(unittest.TestCase):
    """DomainContextLoader.invalidate_cache() — clears all cache state."""

    def setUp(self):
        # Pre-populate caches with dummy data
        DomainContextLoader._registry_cache = SAMPLE_REGISTRY
        DomainContextLoader._registry_mtime = 9999.0
        DomainContextLoader._module_cache = {'greenhouse_a': SAMPLE_MODULE}
        DomainContextLoader._module_mtimes = {'greenhouse_a': 9999.0}

    def test_invalidate_clears_registry_cache(self):
        DomainContextLoader.invalidate_cache()
        self.assertEqual(DomainContextLoader._registry_cache, {})

    def test_invalidate_resets_registry_mtime(self):
        DomainContextLoader.invalidate_cache()
        self.assertEqual(DomainContextLoader._registry_mtime, 0.0)

    def test_invalidate_clears_module_cache(self):
        DomainContextLoader.invalidate_cache()
        self.assertEqual(DomainContextLoader._module_cache, {})

    def test_invalidate_clears_module_mtimes(self):
        DomainContextLoader.invalidate_cache()
        self.assertEqual(DomainContextLoader._module_mtimes, {})

    def test_invalidate_returns_none(self):
        result = DomainContextLoader.invalidate_cache()
        self.assertIsNone(result)

    def test_double_invalidate_is_idempotent(self):
        """Calling invalidate_cache() twice must not raise and state stays cleared."""
        DomainContextLoader.invalidate_cache()
        DomainContextLoader.invalidate_cache()
        self.assertEqual(DomainContextLoader._registry_cache, {})
        self.assertEqual(DomainContextLoader._module_cache, {})


# ===========================================================================
# 8. _context_broadcast_job() — 6-step sequence
# ===========================================================================

import aot.ai.services.ai_scheduler_service as _sched_mod
from aot.ai.services.ai_scheduler_service import _context_broadcast_job
from aot.tests.ai_scheduler_test_utils import ai_enabled, ai_scheduler_job_env


class TestContextBroadcastJobIsModuleLevel(unittest.TestCase):
    """_context_broadcast_job must be a picklable module-level callable."""

    def test_context_broadcast_job_is_callable(self):
        self.assertTrue(
            callable(getattr(_sched_mod, '_context_broadcast_job', None)),
            "_context_broadcast_job must be callable at module level"
        )

    def test_context_broadcast_job_has_no_locals_in_qualname(self):
        """APScheduler pickle requires no '<locals>' in __qualname__."""
        func = getattr(_sched_mod, '_context_broadcast_job')
        self.assertNotIn(
            '<locals>', func.__qualname__,
            "_context_broadcast_job appears to be a closure; APScheduler cannot serialize it"
        )


class TestContextBroadcastJobStepOrder(unittest.TestCase):
    """
    _context_broadcast_job() must call its 6 dependencies in documented order.

    Mocking strategy:
      - Each service call is mocked independently.
      - A call_order list is populated via side_effect to verify sequencing.
    """

    def _run_job_with_mocks(self, facilities=None, master_ctx=None,
                             domain_module=None, summary_history=None,
                             reasoning_result=None):
        """
        Run _context_broadcast_job() with all 6 external calls mocked.
        Returns (call_order, mock_objects) for assertion.
        """
        if facilities is None:
            facilities = ['greenhouse_a', 'greenhouse_b']
        if master_ctx is None:
            master_ctx = {'sensor_readings': [], 'events': [], 'notes': []}
        if domain_module is None:
            domain_module = dict(SAMPLE_MODULE)
            domain_module['operational_state'] = {'value': 'normal',
                                                   'timestamp': '2026-03-25T00:00:00Z'}
        if summary_history is None:
            summary_history = [{'summary': 'previous summary', 'timestamp': '2026-03-24'}]
        if reasoning_result is None:
            reasoning_result = {'insights': ['test insight'], 'actions': []}

        call_order = []

        def step1_side_effect():
            call_order.append('step1_get_all_active_facilities')
            return facilities

        def step2_side_effect(**kwargs):
            call_order.append('step2_get_master_context')
            return master_ctx

        def step3_side_effect(fid, **kwargs):
            call_order.append(f'step3_load_active_module:{fid}')
            return domain_module

        def step4_side_effect(*args, **kwargs):
            call_order.append('step4_get_summary_history')
            return summary_history

        def step5_side_effect(*args, **kwargs):
            call_order.append('step5_reasoning_engine')
            return reasoning_result

        def step6_side_effect(*args, **kwargs):
            call_order.append('step6_generate_system_summary')
            return MagicMock()

        # The job uses local imports inside its body; patch at source modules
        with patch('aot.ai.services.domain_context_loader.DomainContextLoader'
                   '.get_all_active_facilities',
                   side_effect=step1_side_effect), \
             patch('aot.ai.services.ai_context_service.AIContextService'
                   '.get_master_context',
                   side_effect=step2_side_effect, create=True), \
             patch('aot.ai.services.domain_context_loader.DomainContextLoader'
                   '.load_active_module',
                   side_effect=step3_side_effect), \
             patch('aot.ai.services.ai_summary_service.AISummaryService'
                   '.get_summary_history',
                   side_effect=step4_side_effect, create=True), \
             patch('aot.ai.services.ai_summary_service.AISummaryService'
                   '.generate_system_summary',
                   side_effect=step6_side_effect, create=True), \
             ai_scheduler_job_env():
            _context_broadcast_job()

        return call_order

    def test_step1_get_all_active_facilities_is_called(self):
        order = self._run_job_with_mocks()
        self.assertTrue(
            any('step1_get_all_active_facilities' in s for s in order),
            "Step 1: get_all_active_facilities() was not called"
        )

    def test_step2_get_master_context_is_called(self):
        order = self._run_job_with_mocks()
        self.assertTrue(
            any('step2_get_master_context' in s for s in order),
            "Step 2: get_master_context() was not called"
        )

    def test_step3_load_active_module_is_called_per_facility(self):
        facilities = ['greenhouse_a', 'greenhouse_b']
        order = self._run_job_with_mocks(facilities=facilities)
        step3_calls = [s for s in order if s.startswith('step3_load_active_module')]
        self.assertEqual(
            len(step3_calls), len(facilities),
            f"Expected {len(facilities)} load_active_module calls, got {len(step3_calls)}"
        )

    def test_step3_called_for_each_facility_id(self):
        facilities = ['greenhouse_a', 'greenhouse_b']
        order = self._run_job_with_mocks(facilities=facilities)
        self.assertIn('step3_load_active_module:greenhouse_a', order)
        self.assertIn('step3_load_active_module:greenhouse_b', order)

    def test_step4_get_summary_history_is_called(self):
        order = self._run_job_with_mocks()
        self.assertTrue(
            any('step4_get_summary_history' in s for s in order),
            "Step 4: get_summary_history() was not called"
        )

    def test_step6_generate_system_summary_is_called(self):
        order = self._run_job_with_mocks()
        self.assertTrue(
            any('step6_generate_system_summary' in s for s in order),
            "Step 6: generate_system_summary() was not called"
        )

    def test_step1_called_before_step2(self):
        order = self._run_job_with_mocks()
        step1_idx = next((i for i, s in enumerate(order)
                          if 'step1_get_all_active_facilities' in s), None)
        step2_idx = next((i for i, s in enumerate(order)
                          if 'step2_get_master_context' in s), None)
        self.assertIsNotNone(step1_idx, "step1 not found in call order")
        self.assertIsNotNone(step2_idx, "step2 not found in call order")
        self.assertLess(step1_idx, step2_idx,
                        "Step 1 must execute before Step 2")

    def test_step2_called_before_step3(self):
        order = self._run_job_with_mocks()
        step2_idx = next((i for i, s in enumerate(order)
                          if 'step2_get_master_context' in s), None)
        step3_idx = next((i for i, s in enumerate(order)
                          if 'step3_load_active_module' in s), None)
        if step2_idx is not None and step3_idx is not None:
            self.assertLess(step2_idx, step3_idx,
                            "Step 2 must execute before Step 3")

    def test_step4_called_before_step6(self):
        order = self._run_job_with_mocks()
        step4_idx = next((i for i, s in enumerate(order)
                          if 'step4_get_summary_history' in s), None)
        step6_idx = next((i for i, s in enumerate(order)
                          if 'step6_generate_system_summary' in s), None)
        if step4_idx is not None and step6_idx is not None:
            self.assertLess(step4_idx, step6_idx,
                            "Step 4 must execute before Step 6")


class TestContextBroadcastJobEdgeCases(unittest.TestCase):
    """_context_broadcast_job() — resilience and edge case behavior."""

    def setUp(self):
        # Without the gates open the job returns before its body runs, and
        # every "must not raise" assertion below would pass vacuously.
        env = ai_scheduler_job_env()
        env.__enter__()
        self.addCleanup(env.__exit__, None, None, None)

    def test_empty_facility_list_does_not_crash(self):
        """When no active facilities exist, the job must complete without error."""
        with patch('aot.ai.services.domain_context_loader.DomainContextLoader'
                   '.get_all_active_facilities', return_value=[]), \
             patch('aot.ai.services.ai_context_service.AIContextService'
                   '.get_master_context', return_value={}, create=True), \
             patch('aot.ai.services.ai_summary_service.AISummaryService'
                   '.get_summary_history', return_value=[], create=True), \
             patch('aot.ai.services.ai_summary_service.AISummaryService'
                   '.generate_system_summary', return_value=None, create=True):
            try:
                _context_broadcast_job()
            except Exception as exc:
                self.fail(
                    f"_context_broadcast_job() raised {type(exc).__name__} on empty "
                    f"facility list: {exc}"
                )

    def test_empty_facility_list_skips_step3(self):
        """When facilities list is empty, load_active_module must not be called."""
        with patch('aot.ai.services.domain_context_loader.DomainContextLoader'
                   '.get_all_active_facilities', return_value=[]), \
             patch('aot.ai.services.ai_context_service.AIContextService'
                   '.get_master_context', return_value={}, create=True), \
             patch('aot.ai.services.domain_context_loader.DomainContextLoader'
                   '.load_active_module') as mock_load, \
             patch('aot.ai.services.ai_summary_service.AISummaryService'
                   '.get_summary_history', return_value=[], create=True), \
             patch('aot.ai.services.ai_summary_service.AISummaryService'
                   '.generate_system_summary', return_value=None, create=True):
            _context_broadcast_job()
        mock_load.assert_not_called()

    def test_get_master_context_failure_does_not_propagate(self):
        """A service exception in Step 2 must not crash the scheduler job."""
        with patch('aot.ai.services.domain_context_loader.DomainContextLoader'
                   '.get_all_active_facilities', return_value=['greenhouse_a']), \
             patch('aot.ai.services.ai_context_service.AIContextService'
                   '.get_master_context',
                   side_effect=RuntimeError("DB connection failed"), create=True), \
             patch('aot.ai.services.ai_summary_service.AISummaryService'
                   '.get_summary_history', return_value=[], create=True), \
             patch('aot.ai.services.ai_summary_service.AISummaryService'
                   '.generate_system_summary', return_value=None, create=True):
            try:
                _context_broadcast_job()
            except RuntimeError:
                self.fail(
                    "_context_broadcast_job() must not propagate service exceptions"
                )

    def test_load_active_module_failure_does_not_propagate(self):
        """A failure in Step 3 for one facility must not abort the entire job."""
        with patch('aot.ai.services.domain_context_loader.DomainContextLoader'
                   '.get_all_active_facilities',
                   return_value=['greenhouse_a', 'greenhouse_b']), \
             patch('aot.ai.services.ai_context_service.AIContextService'
                   '.get_master_context', return_value={}, create=True), \
             patch('aot.ai.services.domain_context_loader.DomainContextLoader'
                   '.load_active_module',
                   side_effect=RuntimeError("module file corrupted")), \
             patch('aot.ai.services.ai_summary_service.AISummaryService'
                   '.get_summary_history', return_value=[], create=True), \
             patch('aot.ai.services.ai_summary_service.AISummaryService'
                   '.generate_system_summary', return_value=None, create=True):
            try:
                _context_broadcast_job()
            except RuntimeError:
                self.fail(
                    "_context_broadcast_job() must not propagate per-facility load errors"
                )

    def test_generate_system_summary_failure_does_not_propagate(self):
        """A failure in Step 6 must not crash the job."""
        with patch('aot.ai.services.domain_context_loader.DomainContextLoader'
                   '.get_all_active_facilities', return_value=['greenhouse_a']), \
             patch('aot.ai.services.ai_context_service.AIContextService'
                   '.get_master_context', return_value={}, create=True), \
             patch('aot.ai.services.domain_context_loader.DomainContextLoader'
                   '.load_active_module', return_value=SAMPLE_MODULE), \
             patch('aot.ai.services.ai_summary_service.AISummaryService'
                   '.get_summary_history', return_value=[], create=True), \
             patch('aot.ai.services.ai_summary_service.AISummaryService'
                   '.generate_system_summary',
                   side_effect=RuntimeError("write failed"), create=True):
            try:
                _context_broadcast_job()
            except RuntimeError:
                self.fail(
                    "_context_broadcast_job() must not propagate Step 6 exceptions"
                )

    def test_returns_none(self):
        """_context_broadcast_job() is a fire-and-forget job; return value must be None."""
        with patch('aot.ai.services.domain_context_loader.DomainContextLoader'
                   '.get_all_active_facilities', return_value=[]), \
             patch('aot.ai.services.ai_context_service.AIContextService'
                   '.get_master_context', return_value={}, create=True), \
             patch('aot.ai.services.ai_summary_service.AISummaryService'
                   '.get_summary_history', return_value=[], create=True), \
             patch('aot.ai.services.ai_summary_service.AISummaryService'
                   '.generate_system_summary', return_value=None, create=True):
            result = _context_broadcast_job()
        self.assertIsNone(result)


class TestContextBroadcastJobRegistration(unittest.TestCase):
    """
    AISchedulerService.init_app() must register _context_broadcast_job
    with interval trigger and the configured CONTEXT_BROADCAST_INTERVAL_HOURS.
    """

    def tearDown(self):
        # init_app() assigns the module-level _flask_app; leaving the mock in
        # place leaks into other test modules.
        _sched_mod._flask_app = None

    def _run_init_app_with_mock_scheduler(self):
        mock_scheduler = MagicMock()
        mock_scheduler.running = False
        mock_app = MagicMock()

        with patch('aot.ai.services.ai_scheduler_service.get_scheduler',
                   return_value=mock_scheduler), \
             patch('aot.utils.signals.trigger_fired', MagicMock()), \
             patch('aot.utils.signals.conditional_fired', MagicMock()), \
             patch('aot.ai.services.ai_scheduler_service._on_trigger_fired',
                   MagicMock(), create=True), \
             patch('aot.ai.services.ai_scheduler_service._on_conditional_fired',
                   MagicMock(), create=True), \
             ai_enabled():
            from aot.ai.services.ai_scheduler_service import AISchedulerService
            AISchedulerService.init_app(mock_app)

        return mock_scheduler.add_job.call_args_list

    def test_context_broadcast_job_is_registered_in_init_app(self):
        calls = self._run_init_app_with_mock_scheduler()
        job_ids = [c.kwargs.get('id') for c in calls]
        self.assertIn(
            'ai_scheduler_context_broadcast',
            job_ids,
            f"Expected 'ai_scheduler_context_broadcast' in add_job ids; got: {job_ids}"
        )

    def test_context_broadcast_job_uses_interval_trigger(self):
        calls = self._run_init_app_with_mock_scheduler()
        broadcast_calls = [c for c in calls
                           if c.kwargs.get('id') == 'ai_scheduler_context_broadcast']
        self.assertTrue(broadcast_calls,
                        "No add_job call found for ai_scheduler_context_broadcast")
        self.assertEqual(broadcast_calls[0].kwargs.get('trigger'), 'interval')

    def test_context_broadcast_job_interval_matches_config(self):
        from aot.config import mcp_config
        calls = self._run_init_app_with_mock_scheduler()
        broadcast_calls = [c for c in calls
                           if c.kwargs.get('id') == 'ai_scheduler_context_broadcast']
        self.assertTrue(broadcast_calls)
        self.assertEqual(
            broadcast_calls[0].kwargs.get('hours'),
            mcp_config.CONTEXT_BROADCAST_INTERVAL_HOURS
        )

    def test_context_broadcast_job_registered_with_correct_func(self):
        calls = self._run_init_app_with_mock_scheduler()
        broadcast_calls = [c for c in calls
                           if c.kwargs.get('id') == 'ai_scheduler_context_broadcast']
        self.assertTrue(broadcast_calls)
        registered_func = broadcast_calls[0].kwargs.get('func')
        self.assertIs(
            registered_func,
            _sched_mod._context_broadcast_job,
            "func kwarg must be the module-level _context_broadcast_job function"
        )

    def test_context_broadcast_job_has_replace_existing_true(self):
        calls = self._run_init_app_with_mock_scheduler()
        broadcast_calls = [c for c in calls
                           if c.kwargs.get('id') == 'ai_scheduler_context_broadcast']
        self.assertTrue(broadcast_calls)
        self.assertTrue(broadcast_calls[0].kwargs.get('replace_existing'))

    def test_context_broadcast_job_has_coalesce_true(self):
        calls = self._run_init_app_with_mock_scheduler()
        broadcast_calls = [c for c in calls
                           if c.kwargs.get('id') == 'ai_scheduler_context_broadcast']
        self.assertTrue(broadcast_calls)
        self.assertTrue(broadcast_calls[0].kwargs.get('coalesce'))

    def test_context_broadcast_job_max_instances_is_one(self):
        calls = self._run_init_app_with_mock_scheduler()
        broadcast_calls = [c for c in calls
                           if c.kwargs.get('id') == 'ai_scheduler_context_broadcast']
        self.assertTrue(broadcast_calls)
        self.assertEqual(broadcast_calls[0].kwargs.get('max_instances'), 1)


# ===========================================================================
# 9. mcp_config — configuration variable contracts
# ===========================================================================

class TestMcpConfigDefaults(unittest.TestCase):
    """mcp_config.py — default values and types."""

    def setUp(self):
        # Reload the module in a clean environment (without overrides)
        import importlib
        # Remove any lingering env overrides that might affect the values
        for key in ('CONTEXT_LAYER_ROOT', 'CONTEXT_BROADCAST_INTERVAL_HOURS',
                    'CONTEXT_ACCUMULATION_DEPTH', 'AOT_ROOT'):
            os.environ.pop(key, None)

        from aot.config import mcp_config
        importlib.reload(mcp_config)
        self.cfg = mcp_config

    # --- CONTEXT_LAYER_ROOT -------------------------------------------------

    def test_context_layer_root_is_string(self):
        self.assertIsInstance(self.cfg.CONTEXT_LAYER_ROOT, str)

    def test_context_layer_root_ends_with_context_layer(self):
        """Default path must end with 'context_layer' directory segment."""
        self.assertTrue(
            self.cfg.CONTEXT_LAYER_ROOT.endswith('context_layer'),
            f"Expected CONTEXT_LAYER_ROOT to end with 'context_layer', "
            f"got: {self.cfg.CONTEXT_LAYER_ROOT}"
        )

    def test_context_layer_root_is_absolute_path(self):
        self.assertTrue(os.path.isabs(self.cfg.CONTEXT_LAYER_ROOT))

    # --- CONTEXT_BROADCAST_INTERVAL_HOURS -----------------------------------

    def test_context_broadcast_interval_hours_is_int(self):
        self.assertIsInstance(self.cfg.CONTEXT_BROADCAST_INTERVAL_HOURS, int)

    def test_context_broadcast_interval_hours_default_is_one(self):
        self.assertEqual(self.cfg.CONTEXT_BROADCAST_INTERVAL_HOURS, 1)

    def test_context_broadcast_interval_hours_is_positive(self):
        self.assertGreater(self.cfg.CONTEXT_BROADCAST_INTERVAL_HOURS, 0)

    # --- CONTEXT_ACCUMULATION_DEPTH -----------------------------------------

    def test_context_accumulation_depth_is_int(self):
        self.assertIsInstance(self.cfg.CONTEXT_ACCUMULATION_DEPTH, int)

    def test_context_accumulation_depth_default_is_ten(self):
        self.assertEqual(self.cfg.CONTEXT_ACCUMULATION_DEPTH, 10)

    def test_context_accumulation_depth_is_positive(self):
        self.assertGreater(self.cfg.CONTEXT_ACCUMULATION_DEPTH, 0)


class TestMcpConfigEnvOverrides(unittest.TestCase):
    """mcp_config.py — os.getenv overrides take precedence over defaults."""

    def _reload_config(self):
        import importlib; from aot.config import mcp_config
        importlib.reload(mcp_config)
        return mcp_config

    def tearDown(self):
        # Restore a clean environment after each test
        for key in ('CONTEXT_LAYER_ROOT', 'CONTEXT_BROADCAST_INTERVAL_HOURS',
                    'CONTEXT_ACCUMULATION_DEPTH'):
            os.environ.pop(key, None)

    def test_context_layer_root_env_override(self):
        os.environ['CONTEXT_LAYER_ROOT'] = '/custom/context'
        cfg = self._reload_config()
        self.assertEqual(cfg.CONTEXT_LAYER_ROOT, '/custom/context')

    def test_context_broadcast_interval_hours_env_override(self):
        os.environ['CONTEXT_BROADCAST_INTERVAL_HOURS'] = '4'
        cfg = self._reload_config()
        self.assertEqual(cfg.CONTEXT_BROADCAST_INTERVAL_HOURS, 4)

    def test_context_broadcast_interval_hours_env_override_is_int(self):
        """The env override must be cast to int, not left as str."""
        os.environ['CONTEXT_BROADCAST_INTERVAL_HOURS'] = '6'
        cfg = self._reload_config()
        self.assertIsInstance(cfg.CONTEXT_BROADCAST_INTERVAL_HOURS, int)

    def test_context_accumulation_depth_env_override(self):
        os.environ['CONTEXT_ACCUMULATION_DEPTH'] = '25'
        cfg = self._reload_config()
        self.assertEqual(cfg.CONTEXT_ACCUMULATION_DEPTH, 25)

    def test_context_accumulation_depth_env_override_is_int(self):
        os.environ['CONTEXT_ACCUMULATION_DEPTH'] = '5'
        cfg = self._reload_config()
        self.assertIsInstance(cfg.CONTEXT_ACCUMULATION_DEPTH, int)

    def test_unset_env_falls_back_to_default_interval(self):
        """Without the env var, the default (1) must be used."""
        os.environ.pop('CONTEXT_BROADCAST_INTERVAL_HOURS', None)
        cfg = self._reload_config()
        self.assertEqual(cfg.CONTEXT_BROADCAST_INTERVAL_HOURS, 1)

    def test_unset_env_falls_back_to_default_depth(self):
        """Without the env var, the default (10) must be used."""
        os.environ.pop('CONTEXT_ACCUMULATION_DEPTH', None)
        cfg = self._reload_config()
        self.assertEqual(cfg.CONTEXT_ACCUMULATION_DEPTH, 10)


# ===========================================================================
# Contract tests — AI/MCP integration points
# ===========================================================================

class TestDomainContextLoaderContextContract(unittest.TestCase):
    """
    Contract tests: verify that load_active_module() returns a response
    that conforms to the schema expected by downstream consumers
    (_context_broadcast_job, AIContextService, MCP tool handlers).
    """

    def setUp(self):
        DomainContextLoader._registry_cache = {}
        DomainContextLoader._registry_mtime = 0.0
        DomainContextLoader._module_cache = {}
        DomainContextLoader._module_mtimes = {}

    def test_response_schema_has_facility_id(self):
        """Consumers expect 'facility_id' in the domain module dict."""
        resolved = dict(SAMPLE_MODULE)
        resolved['operational_state'] = {'value': 'normal', 'timestamp': '2026-03-25T00:00:00Z'}

        with patch.object(DomainContextLoader, '_get_registry', return_value=SAMPLE_REGISTRY), \
             patch.object(DomainContextLoader, '_load_module_file', return_value=SAMPLE_MODULE), \
             patch.object(DomainContextLoader, '_resolve_operational_state',
                          return_value=resolved):
            result = DomainContextLoader.load_active_module('greenhouse_a')

        self.assertIsNotNone(result)
        self.assertIn('facility_id', result)
        self.assertIsInstance(result['facility_id'], str)

    def test_response_schema_operational_state_value_is_string(self):
        """The operational_state.value field consumed by reasoning engine must be str."""
        resolved = dict(SAMPLE_MODULE)
        resolved['operational_state'] = {'value': 'normal', 'timestamp': '2026-03-25T00:00:00Z'}

        with patch.object(DomainContextLoader, '_get_registry', return_value=SAMPLE_REGISTRY), \
             patch.object(DomainContextLoader, '_load_module_file', return_value=SAMPLE_MODULE), \
             patch.object(DomainContextLoader, '_resolve_operational_state',
                          return_value=resolved):
            result = DomainContextLoader.load_active_module('greenhouse_a')

        self.assertIsNotNone(result)
        self.assertIsInstance(result['operational_state']['value'], str)

    def test_get_all_active_facilities_output_consumed_by_broadcast_job(self):
        """
        The list returned by get_all_active_facilities() is iterated in
        _context_broadcast_job Step 3. Each element must be a non-empty string.
        """
        with patch.object(DomainContextLoader, '_get_registry', return_value=SAMPLE_REGISTRY):
            facilities = DomainContextLoader.get_all_active_facilities()

        for fid in facilities:
            self.assertIsInstance(fid, str)
            self.assertTrue(len(fid) > 0,
                            "Facility IDs passed to load_active_module must be non-empty strings")


if __name__ == '__main__':
    unittest.main()
