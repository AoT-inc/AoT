# coding=utf-8
import logging
import json
from typing import Optional, Any, Dict
from aot.aot_flask.extensions import cache

logger = logging.getLogger(__name__)

class CacheManager:
    """
    v26.0: Central cache manager for AI services.
    Uses Flask-Caching (Redis-backable) for rapid data retrieval.

    @phase active
    @stability stable
    """

    @staticmethod
    def get_latest_summary(scope_type: str, scope_id: Optional[str]) -> Optional[Dict[str, Any]]:
        """Retrieve the latest summary from cache."""
        key = f"ai_summary:{scope_type}:{scope_id if scope_id else 'all'}"
        return cache.get(key)

    @staticmethod
    def set_latest_summary(scope_type: str, scope_id: Optional[str], summary_data: Any, timeout: int = 3600):
        """Cache the latest summary (default 1 hour)."""
        key = f"ai_summary:{scope_type}:{scope_id if scope_id else 'all'}"
        
        # If it's a model instance, convert to dict for caching
        if hasattr(summary_data, 'summary_text'):
             summary_data = {
                 'unique_id': summary_data.unique_id,
                 'summary_text': summary_data.summary_text,
                 'timestamp': summary_data.timestamp.isoformat(),
                 'scope_type': summary_data.scope_type,
                 'scope_id': summary_data.scope_id,
                 'version': summary_data.version,
                 'anomaly_detected': summary_data.anomaly_detected,
                 'alert_level': summary_data.alert_level
             }
        
        cache.set(key, summary_data, timeout=timeout)
        logger.debug(f"Cached summary for {key}")

    @staticmethod
    def invalidate_summary(scope_type: str, scope_id: Optional[str]):
        """Clear cached summary."""
        key = f"ai_summary:{scope_type}:{scope_id if scope_id else 'all'}"
        cache.delete(key)

    @staticmethod
    def get_system_metrics_baseline() -> Optional[Dict[str, Any]]:
        """Retrieve cached system baseline metrics."""
        return cache.get("ai_system_metrics_baseline")

    @staticmethod
    def set_system_metrics_baseline(metrics: Dict[str, Any], timeout: int = 86400):
        """Set system baseline metrics (default 24 hours)."""
        cache.set("ai_system_metrics_baseline", metrics, timeout=timeout)
