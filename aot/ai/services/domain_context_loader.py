# coding=utf-8
"""
DomainContextLoader — Context Layer: facility-domain module loader.

Responsible for loading, caching, and resolving the operational state
of facility-specific domain modules (YAML-based configuration files).
"""
import os
import threading
import yaml
from datetime import datetime, timezone
from typing import Optional

from aot.config.mcp_config import CONTEXT_LAYER_ROOT

# ---------------------------------------------------------------------------
# @ANCHOR: DOMAIN_CONTEXT_LOADER
# ---------------------------------------------------------------------------


class DomainContextLoader:
    """
    Loads and caches domain module configurations per facility.
    File-level caching is implemented via class-level variables to avoid
    repeated disk I/O across requests within the same process lifetime.

    @phase active
    @stability stable
    """

    # Guards all class-level cache mutations against concurrent APScheduler threads
    _lock: threading.Lock = threading.Lock()
    # Class-level cache for the facility registry
    _registry_cache: dict = {}
    # Modification time of the registry file at last load
    _registry_mtime: float = 0.0
    # Per-facility module content cache
    _module_cache: dict = {}
    # Per-facility module file modification times
    _module_mtimes: dict = {}

    # -----------------------------------------------------------------------
    # Public API
    # -----------------------------------------------------------------------

    @classmethod
    def load_active_module(
        cls,
        facility_id: str,
        include_layer4: bool = False,
        resolve_growth_stage: bool = True,
    ) -> Optional[dict]:
        """
        Load and return the fully resolved domain module for a facility.

        Call Hierarchy
        --------------
        Parent  : External callers — _context_broadcast_job(),
                  AIContextService, MCP tool handlers
        Children: cls._get_registry()
                  cls._load_module_file()
                  cls._resolve_operational_state()
        """
        registry = cls._get_registry()
        facilities = registry.get('facilities', [])

        # Find the matching registry entry
        entry = None
        for f in facilities:
            if f.get('facility_id') == facility_id:
                entry = f
                break

        # Return None if not found or not active
        if entry is None or not entry.get('active', False):
            return None

        # Load the module file
        module = cls._load_module_file(entry)
        if module is None:
            return None

        # Resolve operational state (includes growth_stage when enabled)
        resolved = cls._resolve_operational_state(
            module,
            registry_entry=entry if resolve_growth_stage else None,
        )

        # Strip layer4 data (references) unless requested
        if not include_layer4:
            resolved = {k: v for k, v in resolved.items() if k != 'references'}

        return resolved

    @classmethod
    def get_all_active_facilities(cls) -> list:
        """
        Return a list of facility_id strings for all active entries in
        the domain registry.

        Call Hierarchy
        --------------
        Parent  : _context_broadcast_job() (step 1 of broadcast sequence)
        Children: cls._get_registry()
        """
        registry = cls._get_registry()
        facilities = registry.get('facilities', [])
        return [
            f['facility_id']
            for f in facilities
            if f.get('active', False)
        ]

    @classmethod
    def invalidate_cache(cls) -> None:
        """
        Clear all cached registry and module data, forcing a fresh reload
        on the next call to any loader method.

        Call Hierarchy
        --------------
        Parent  : Admin endpoints, configuration reload hooks
        Children: (none — cache reset only)
        """
        with cls._lock:
            cls._registry_cache = {}
            cls._registry_mtime = 0.0
            cls._module_cache = {}
            cls._module_mtimes = {}

    # -----------------------------------------------------------------------
    # Internal helpers
    # -----------------------------------------------------------------------

    @classmethod
    def _get_registry(cls) -> dict:
        """
        Load (or return from cache) the facility registry YAML file.
        Performs mtime-based cache invalidation.

        A missing registry file is a normal state, not a failure: the Context
        Layer is optional and a site that has registered no domain modules
        simply has no file. Raising here made _context_broadcast_job log
        "Step 1 failed: [Errno 2] No such file or directory" every cycle, which
        reads like a broken install. Return an empty registry instead — every
        caller already handles "no facilities".

        Call Hierarchy
        --------------
        Parent  : cls.load_active_module(), cls.get_all_active_facilities()
        Children: (none — direct file I/O via yaml.safe_load)
        """
        registry_path = os.path.join(CONTEXT_LAYER_ROOT, 'facility_registry.yaml')
        if not os.path.exists(registry_path):
            # Drop any cache from a previous ON state so a deleted registry
            # doesn't keep serving stale facilities.
            with cls._lock:
                cls._registry_cache = {}
                cls._registry_mtime = 0.0
            return {}
        current_mtime = os.path.getmtime(registry_path)

        with cls._lock:
            # Return cache if warm and file unchanged
            if cls._registry_cache and current_mtime == cls._registry_mtime:
                return cls._registry_cache

            # Load from disk. An empty file parses to None — `or {}` keeps the
            # contract "always a dict" so callers can .get() unconditionally.
            with open(registry_path, 'r') as f:
                data = yaml.safe_load(f) or {}

            cls._registry_cache = data
            cls._registry_mtime = current_mtime
            return cls._registry_cache

    @classmethod
    def _load_module_file(cls, registry_entry: dict) -> Optional[dict]:
        """
        Load the domain module YAML file referenced by a registry entry.
        Performs mtime-based cache invalidation per facility.

        Call Hierarchy
        --------------
        Parent  : cls.load_active_module()
        Children: (none — direct file I/O via yaml.safe_load)
        """
        facility_id = registry_entry.get('facility_id', '')
        module_file = registry_entry.get('module_file', '')
        module_path = os.path.join(CONTEXT_LAYER_ROOT, module_file)

        if not os.path.exists(module_path):
            return None

        try:
            current_mtime = os.path.getmtime(module_path)

            with cls._lock:
                # Return cache if warm and file unchanged
                if (facility_id in cls._module_cache
                        and cls._module_mtimes.get(facility_id) == current_mtime):
                    return cls._module_cache[facility_id]

                with open(module_path, 'r') as f:
                    data = yaml.safe_load(f)

                cls._module_cache[facility_id] = data
                cls._module_mtimes[facility_id] = current_mtime
                return data
        except Exception:
            return None

    @classmethod
    def _resolve_operational_state(
        cls,
        module: dict,
        registry_entry: Optional[dict] = None,
    ) -> dict:
        """
        Augment a raw module dict with a resolved 'operational_state' key
        derived from its configuration sections and EXT-KR-01 data.

        Call Hierarchy
        --------------
        Parent  : cls.load_active_module()
        Children: cls._calculate_state_value(), GrowthStageResolver.resolve()
        """
        result = dict(module)
        config = module.get('config', {})
        state_value = cls._calculate_state_value(config)
        timestamp = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')

        operational_state: dict = {
            'value':     state_value,
            'timestamp': timestamp,
            'value_meta': {'source': 'domain_kr', 'state': 'system_generated'},
        }

        # EXT-KR-01: inject growth_stage if planting_date + crop_type available
        if registry_entry:
            planting_date = registry_entry.get('planting_date')
            crop_type     = registry_entry.get('crop_type')
            if planting_date and crop_type:
                try:
                    from aot.ai.context.growth_stage_resolver import GrowthStageResolver
                    gs_data = GrowthStageResolver.resolve(crop_type, planting_date)
                    operational_state['growth_stage']        = gs_data.get('growth_stage')
                    operational_state['growth_stage_meta'] = {'source': 'domain_kr:growth_stage_resolver', 'state': 'system_generated'}
                    operational_state['days_after_planting'] = gs_data.get('days_after_planting')
                    operational_state['days_after_planting_meta'] = {'source': 'domain_kr:growth_stage_resolver', 'state': 'system_generated'}
                    operational_state['optimal_ranges']      = gs_data.get('optimal_ranges')
                    operational_state['optimal_ranges_meta'] = {'source': 'domain_kr:optimal_ranges', 'state': 'system_generated'}
                    operational_state['growth_stage_source'] = gs_data.get('growth_stage_source')
                except Exception as exc:
                    import logging
                    logging.getLogger(__name__).warning(
                        "DomainContextLoader: growth_stage resolution failed: %s", exc
                    )

        # EXT-KR-02: inject cultivation_context if crop_type available
        if registry_entry:
            crop_type = registry_entry.get('crop_type')
            if crop_type:
                try:
                    from aot.ai.context.ext.nongsaro_client import NongsaroClient
                    guides = NongsaroClient.get_guides(crop_type)
                    if guides:
                        cultivation = next(
                            (g for g in guides if g.get('guide_type') == 'cultivation'), None
                        )
                        weekly = next(
                            (g for g in guides if g.get('guide_type', '').startswith('calendar_')), None
                        )
                        operational_state['cultivation_context'] = {
                            'cultivation_guide': cultivation.get('content') if cultivation else None,
                            'weekly_advisory':   weekly.get('content') if weekly else None,
                            'source': 'EXT-KR-02',
                        }
                        operational_state['cultivation_context_meta'] = {'source': 'domain_kr:EXT-KR-02:nongsaro', 'state': 'system_generated'}
                except Exception as exc:
                    import logging
                    logging.getLogger(__name__).warning(
                        "DomainContextLoader: EXT-KR-02 cultivation_context failed: %s", exc
                    )

        # EXT-KR-03: inject pest_alerts_context if crop_type available
        if registry_entry:
            crop_type = registry_entry.get('crop_type')
            if crop_type:
                try:
                    from aot.ai.context.ext.pest_management_client import PestManagementClient
                    alerts = PestManagementClient.get_alerts(crop_type)
                    if alerts:
                        active = [a for a in alerts if a.get('severity') in ('high', 'critical')]
                        operational_state['pest_alerts_context'] = {
                            'active_alerts':   active,
                            'alert_count':     len(active),
                            'highest_severity': max(
                                (a.get('severity', 'low') for a in active),
                                key=lambda s: ['low', 'medium', 'high', 'critical'].index(s)
                                if s in ['low', 'medium', 'high', 'critical'] else 0,
                                default='none',
                            ) if active else 'none',
                            'source': 'EXT-KR-03',
                        }
                        operational_state['pest_alerts_context_meta'] = {'source': 'domain_kr:EXT-KR-03:pest_management', 'state': 'system_generated'}
                except Exception as exc:
                    import logging
                    logging.getLogger(__name__).warning(
                        "DomainContextLoader: EXT-KR-03 pest_alerts_context failed: %s", exc
                    )

        result['operational_state'] = operational_state
        return result

    @classmethod
    def _calculate_state_value(cls, config: dict) -> str:
        """
        Derive a scalar operational-state string (e.g., 'normal',
        'warning', 'critical') from a facility config sub-dict.

        Call Hierarchy
        --------------
        Parent  : cls._resolve_operational_state()
        Children: (none — pure computation)
        """
        if not config:
            return 'unknown'
        # Default to normal when config keys are present
        return 'normal'


# ---------------------------------------------------------------------------
# @ANCHOR: GET_GEO_SETTING_KEY
# ---------------------------------------------------------------------------
def get_geo_setting_key(key_name: str) -> str:
    """
    Retrieve a named API key from the global GeoSetting key store (DB).

    This is the single access point for all external API keys in the
    context layer. Keys are managed centrally via the GeoSetting.keys
    JSON field — the same store used by GIS input modules.

    Usage (Phase 2a external data clients):
        rda_key = get_geo_setting_key('RDA_API_KEY')

    Registered key names (see 013_DATA_SOURCES.yaml OI-DS-03):
        RDA_API_KEY        — EXT-KR-01 SmartFarm Productivity Model
        NONGSARO_API_KEY   — EXT-KR-02 Nongsaro Cultivation Guides
        NCPMS_API_KEY      — EXT-KR-03 National Pest Management System
        PERENUAL_API_KEY   — EXT-GL-01 Perenual Plant API
        EPPO_API_TOKEN     — EXT-GL-02 EPPO Global Database

    Returns:
        str: The key value, or '' if not found / DB unavailable.
    """
    try:
        import json
        from aot.databases.models import GeoSetting
        from aot.databases.utils import session_scope
        from aot.config import AOT_DB_PATH
        with session_scope(AOT_DB_PATH) as session:
            settings = session.query(GeoSetting).first()
            if settings and settings.keys:
                keys = json.loads(settings.keys) or {}
                return keys.get(key_name, '')
    except Exception:
        pass
    return ''
