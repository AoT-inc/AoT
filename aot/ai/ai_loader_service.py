# coding=utf-8
# @ANCHOR: AI_LOADER_SERVICE
"""
AILoaderService — Layer 2 Hybrid Loader.

Loading strategy (SBS-002_V2_STRATEGY, layer_2_global_dynamic.loading_strategy):
  Step 1. Load defaults from YAML seed files (aot/config/).
  Step 2. Query DB for override records (AIRoleConfig, AIActionRegistry).
  Step 3. Merge: DB values take precedence over YAML defaults.
  Step 4. Cache merged result in _loader_cache (TTL: 300 s).

Fallback: If DB is unavailable at startup, YAML defaults are used. System remains operational.
"""
import logging
import os
import threading
from typing import Any, Dict, Optional
from aot.utils.time_utils import utc_now


def _is_cache_valid(namespace: str) -> bool:
    entry = _loader_cache.get(namespace)
    if not entry:
        return False
    return utc_now() < entry['expires_at']


def _set_cache(namespace: str, data: Any) -> None:
    with _cache_lock:
        _loader_cache[namespace] = {
            'data': data,
            'expires_at': utc_now() + timedelta(seconds=_CACHE_TTL_SECONDS)
        }


def _get_cache(namespace: str) -> Optional[Any]:
    entry = _loader_cache.get(namespace)
    return entry['data'] if entry else None


class AILoaderService:
    """
    Layer 2 Hybrid Loader for role configs and action registry.
    All methods are class-level (no Flask app-context dependency at import time).

    @phase active
    @stability stable
    @dependency AIRoleConfig, AIActionRegistry
    """

    # ── Public API ─────────────────────────────────────────────────────────

    @classmethod
    def get_all_roles(cls) -> Dict[str, Dict[str, Any]]:
        """
        Returns merged role config dict keyed by role_key.
        Uses TTL cache. Falls back to YAML-only if DB is unavailable.
        """
        if _is_cache_valid('roles'):
            return _get_cache('roles')
        data = cls._load_roles()
        _set_cache('roles', data)
        return data

    @classmethod
    def get_role(cls, role_key: str) -> Dict[str, Any]:
        """Returns config for a single role_key. Returns {} if not found."""
        return cls.get_all_roles().get(role_key, {})

    @classmethod
    def get_all_actions(cls) -> Dict[str, Dict[str, Any]]:
        """
        Returns merged action registry dict keyed by action_type.
        Uses TTL cache. Falls back to YAML-only if DB is unavailable.
        """
        if _is_cache_valid('actions'):
            return _get_cache('actions')
        data = cls._load_actions()
        _set_cache('actions', data)
        return data

    @classmethod
    def get_action(cls, action_type: str) -> Dict[str, Any]:
        """Returns config for a single action_type. Returns {} if not found."""
        return cls.get_all_actions().get(action_type, {})

    @classmethod
    def invalidate(cls, namespace: Optional[str] = None) -> None:
        """
        Invalidate cache for a specific namespace ('roles' or 'actions'),
        or all namespaces if namespace is None.
        Called by REF-004 Auto-Sync Trigger after MCPBridgeService reconnect.
        """
        with _cache_lock:
            if namespace:
                _loader_cache.pop(namespace, None)
                logger.info(f"[AILoaderService] Cache invalidated: {namespace}")
            else:
                _loader_cache.clear()
                logger.info("[AILoaderService] Full cache invalidated.")

    # ── Internal loaders ───────────────────────────────────────────────────

    @classmethod
    def _load_roles(cls) -> Dict[str, Dict[str, Any]]:
        """
        Hybrid load: YAML seed → DB overrides → merge.
        """
        # Step 1: YAML defaults
        merged: Dict[str, Dict[str, Any]] = {}
        try:
            with open(_ROLE_SEED_PATH, 'r', encoding='utf-8') as f:
                seed = yaml.safe_load(f)
            for row in seed.get('roles', []):
                key = row.get('role_key')
                if key:
                    merged[key] = dict(row)
        except Exception as e:
            logger.error(f"[AILoaderService] Failed to load YAML role seed: {e}")

        # Step 2: DB overrides
        try:
            from aot.databases.models import AIRoleConfig
            overrides = AIRoleConfig.query.filter_by(is_active=True).all()
            for row in overrides:
                if row.role_key not in merged:
                    merged[row.role_key] = {}
                if row.system_prompt is not None:
                    merged[row.role_key]['system_prompt'] = row.system_prompt
                if row.specialty is not None:
                    merged[row.role_key]['specialty'] = row.specialty
                merged[row.role_key]['_db_override'] = True
            logger.debug(f"[AILoaderService] Roles loaded — {len(merged)} entries ({len(overrides)} DB overrides).")
        except Exception as e:
            logger.warning(f"[AILoaderService] DB unavailable for role overrides, using YAML defaults: {e}")

        return merged

    @classmethod
    def _load_actions(cls) -> Dict[str, Dict[str, Any]]:
        """
        Hybrid load: YAML seed → DB overrides → merge.
        """
        # Step 1: YAML defaults
        merged: Dict[str, Dict[str, Any]] = {}
        try:
            with open(_ACTION_SEED_PATH, 'r', encoding='utf-8') as f:
                seed = yaml.safe_load(f)
            for row in seed.get('actions', []):
                key = row.get('action_type')
                if key:
                    merged[key] = dict(row)
        except Exception as e:
            logger.error(f"[AILoaderService] Failed to load YAML action seed: {e}")

        # Step 2: DB overrides
        try:
            from aot.databases.models import AIActionRegistry
            overrides = AIActionRegistry.query.filter_by(is_active=True).all()
            for row in overrides:
                if row.action_type not in merged:
                    merged[row.action_type] = {}
                merged[row.action_type]['is_rag_eligible'] = row.is_rag_eligible
                merged[row.action_type]['is_immediate'] = row.is_immediate
                if row.resolver_module:
                    merged[row.action_type]['resolver_module'] = row.resolver_module
                merged[row.action_type]['synced_from_mcp'] = row.synced_from_mcp
                merged[row.action_type]['_db_override'] = True
            logger.debug(f"[AILoaderService] Actions loaded — {len(merged)} entries ({len(overrides)} DB overrides).")
        except Exception as e:
            logger.warning(f"[AILoaderService] DB unavailable for action overrides, using YAML defaults: {e}")

        return merged
