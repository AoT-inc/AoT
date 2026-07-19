# coding=utf-8
# @ANCHOR: ACTION_REGISTRY_SYNC
"""
ActionRegistrySync — Auto-Sync Trigger between MCPBridgeService and AIActionRegistry.

Triggered by MCPBridgeService after a successful server tool fetch (post-connect).
Upserts newly discovered MCP tool names into AIActionRegistry with synced_from_mcp=True.
Invalidates AILoaderService cache so the next load picks up the new entries.

Law 3 compliance: sync is read-only from hardware perspective.
  No physical state is changed. Registry reflects discovered truth, not commanded state.

Ref: SBS-002_V2_STRATEGY (pluggable_resolver.auto_sync_trigger, REF-004)
"""
import logging
from aot.utils.time_utils import utc_now
from typing import List

logger = logging.getLogger(__name__)


class ActionRegistrySync:
    """
    Auto-Sync trigger between MCPBridgeService and AIActionRegistry.
    Upserts newly discovered MCP tool names into AIActionRegistry.

    @phase active
    @stability stable
    @dependency MCPBridgeService, AIActionRegistry, AILoaderService
    """

    @classmethod
    def sync(cls, server_id: str) -> None:
        """
        Query MCPBridgeService for the current tool list of server_id,
        upsert each tool into AIActionRegistry with synced_from_mcp=True,
        then invalidate the AILoaderService 'actions' cache.

        Non-fatal: all exceptions are caught and logged as warnings.
        """
        try:
            from aot.ai.services.mcp_bridge_service import MCPBridgeService
            tools: List[dict] = MCPBridgeService._tools_cache.get(server_id, [])
            if not tools:
                return

            from aot.databases.models import AIActionRegistry
            from aot.aot_flask.extensions import db

            now = utc_now()
            synced_count = 0
            created_count = 0

            for tool in tools:
                tool_name = tool.get('name')
                if not tool_name:
                    continue

                existing = AIActionRegistry.query.filter_by(action_type=tool_name).first()
                if existing:
                    existing.synced_from_mcp = True
                    existing.last_synced_at = now
                    synced_count += 1
                else:
                    new_entry = AIActionRegistry(
                        action_type=tool_name,
                        is_rag_eligible=False,   # default; operator can override via DB
                        is_immediate=True,        # MCP tools are generally immediate
                        resolver_module="aot.ai.services.resolvers.registry.ActionResolverRegistry",
                        is_active=True,
                        synced_from_mcp=True,
                        last_synced_at=now,
                    )
                    db.session.add(new_entry)
                    created_count += 1

            db.session.commit()

            # Invalidate AILoaderService action cache so next load includes new entries
            from aot.ai.services.ai_loader_service import AILoaderService
            AILoaderService.invalidate('actions')

            logger.info(
                f"[ActionRegistrySync] server={server_id} — "
                f"synced={synced_count}, created={created_count} tool entries."
            )

        except Exception as e:
            logger.warning(f"[ActionRegistrySync] sync failed for '{server_id}' (non-fatal): {e}")
