# coding=utf-8
"""
EKGService — Experience Knowledge Graph ingestion and correlation engine.

Phase 5 / 005_EDGE_OPTIMIZED_SPECIFICATION.yaml

Design constraints:
  - Runs in a low-priority daemon thread; never blocks the request/response path.
  - Does NOT extend AIMemoryManager (Layer-3 user learning — separate concern).
  - Two ingestion triggers:
      1. DB post-commit signal listener on Notes (category='ai_semantic')
         → register_signal_listener() called once in create_app().
      2. Direct call from ai_scheduler_service._store_feedback_as_note() feedback wire.
  - CapabilityManager guard applied lazily (called at ingest time, not import time).

Ref: 010_IMPLEMENTATION_PLAN.yaml Phase B / B-3
"""
import logging
import threading
import time
from collections import deque
from datetime import datetime, timedelta
from typing import List, Union

from aot.utils.time_utils import utc_now
from aot.aot_flask.extensions import db

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level constants (overridable via CapabilityManager at runtime)
# ---------------------------------------------------------------------------
PRECEDES_THRESHOLD_SECONDS:  int   = 300    # Note within 5 min before DaemonEvent
CLUSTER_PROMOTION_THRESHOLD: float = 0.75   # Pearson |r| threshold
DECAY_RATE_PER_DAY:          float = 0.1    # PatternCluster.decay_score shrinkage
MAX_DRAFTS_PER_CLUSTER_HOUR: int   = 3      # SEC-002 rate limit
DEFAULT_WINDOW_SIZE:         int   = 50     # Fallback when CapabilityManager absent

# ---------------------------------------------------------------------------
# Thread-safe ingestion queue (module-level singleton)
# ---------------------------------------------------------------------------
_ingest_queue: deque = deque()
_queue_lock   = threading.Lock()
_worker_thread: threading.Thread = None  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _get_window_size() -> int:
    """Lazy-init: read CapabilityManager at ingest time to avoid circular imports."""
    try:
        from aot.config.feature_flags import capability_manager
        val = capability_manager.get_param('ekg_window_size')
        return int(val) if val else DEFAULT_WINDOW_SIZE
    except Exception:
        return DEFAULT_WINDOW_SIZE


# ---------------------------------------------------------------------------
# EKGService
# ---------------------------------------------------------------------------
# @ANCHOR: EXPERIENCE_KNOWLEDGE_GRAPH
class EKGService:
    """
    Stateless service. All mutable state lives in the module-level queue and DB.
    Thread-safe: EKGService.ingest() may be called from any thread.

    @phase active
    @stability unstable
    """

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    @classmethod
    def ingest(cls, batch: List) -> None:
        """
        Enqueue HumanNote / DaemonEvent items for background processing.
        Non-blocking: returns immediately. Worker thread started on demand.
        """
        if not batch:
            return
        with _queue_lock:
            _ingest_queue.extend(batch)
        cls._ensure_worker()

    # ------------------------------------------------------------------
    # Worker lifecycle
    # ------------------------------------------------------------------
    @classmethod
    def _ensure_worker(cls) -> None:
        global _worker_thread
        if _worker_thread is None or not _worker_thread.is_alive():
            _worker_thread = threading.Thread(
                target=cls._worker_loop,
                name='ekg-ingest-worker',
                daemon=True,
            )
            _worker_thread.start()
            logger.debug("[EKGService] Background worker started.")

    @classmethod
    def _worker_loop(cls) -> None:
        """
        Drains the ingest queue in window-sized batches.
        Exits when queue is empty; thread is re-created on next ingest() call.
        Yields CPU between batches (low-priority background work).
        """
        window = _get_window_size()
        while True:
            batch = []
            with _queue_lock:
                for _ in range(min(window, len(_ingest_queue))):
                    batch.append(_ingest_queue.popleft())
            if not batch:
                break
            try:
                cls._process_batch(batch)
            except Exception as exc:
                logger.warning("[EKGService] Batch processing error: %s", exc)
            time.sleep(0.05)   # yield CPU

    # ------------------------------------------------------------------
    # Batch processing
    # ------------------------------------------------------------------
    @classmethod
    def _process_batch(cls, batch: list) -> None:
        """
        For each item in batch:
          1. Persist HumanNote or DaemonEvent (if new).
          2. Detect PRECEDES edges (HumanNote within threshold of recent DaemonEvents).
          3. Detect CORRELATES edges (Pearson r on DaemonEvent pairs).
          4. Apply PatternCluster decay + promote new clusters.
        Single db.session.commit() per batch.
        """
        from aot.databases.models.ekg import (
            HumanNote, DaemonEvent, PatternCluster, EdgeRecord, EdgeType
        )
        try:
            # 1. Persist new items
            for item in batch:
                if getattr(item, 'id', None) is None:
                    db.session.add(item)
            db.session.flush()   # assign IDs; do not commit yet

            # 2. PRECEDES edges
            cutoff = utc_now() - timedelta(seconds=PRECEDES_THRESHOLD_SECONDS)
            for item in batch:
                if isinstance(item, HumanNote):
                    recent_events = (
                        DaemonEvent.query
                        .filter(DaemonEvent.timestamp >= cutoff)
                        .filter(DaemonEvent.timestamp < item.created_at)
                        .order_by(DaemonEvent.timestamp.desc())
                        .limit(10)
                        .all()
                    )
                    for ev in recent_events:
                        edge = EdgeRecord(
                            edge_type=EdgeType.PRECEDES,
                            source_id=ev.unique_id,
                            target_id=item.unique_id,
                            weight=1.0,
                            created_at=utc_now(),
                        )
                        db.session.add(edge)

            # 3. CORRELATES edges (Pearson)
            daemon_items = [i for i in batch if isinstance(i, DaemonEvent)]
            if len(daemon_items) >= 2:
                cls._correlate_events(daemon_items)

            # 4. Cluster decay + promotion
            cls._promote_clusters()

            db.session.commit()

        except Exception:
            db.session.rollback()
            raise

    @classmethod
    def _correlate_events(cls, events: list) -> None:
        """
        Compute pairwise Pearson r between DaemonEvent series grouped by metric.
        Creates CORRELATES edges for |r| >= CLUSTER_PROMOTION_THRESHOLD.
        Falls back gracefully if scipy is absent.
        """
        from aot.databases.models.ekg import DaemonEvent, EdgeRecord, EdgeType
        from itertools import combinations

        try:
            from scipy.stats import pearsonr
        except ImportError:
            logger.debug("[EKGService] scipy unavailable — CORRELATES skipped.")
            return

        # Group by metric
        by_metric: dict = {}
        for ev in events:
            by_metric.setdefault(ev.metric, []).append(ev)

        for m1, m2 in combinations(by_metric.keys(), 2):
            vals1 = [e.value for e in by_metric[m1]]
            vals2 = [e.value for e in by_metric[m2]]
            n = min(len(vals1), len(vals2))
            if n < 2:
                continue
            try:
                r, _ = pearsonr(vals1[:n], vals2[:n])
                if abs(r) >= CLUSTER_PROMOTION_THRESHOLD:
                    edge = EdgeRecord(
                        edge_type=EdgeType.CORRELATES,
                        source_id=by_metric[m1][-1].unique_id,
                        target_id=by_metric[m2][-1].unique_id,
                        weight=float(abs(r)),
                        created_at=utc_now(),
                    )
                    db.session.add(edge)
            except Exception as exc:
                logger.debug("[EKGService] Pearson error for %s/%s: %s", m1, m2, exc)

    @classmethod
    def _promote_clusters(cls) -> None:
        """
        Decay existing PatternClusters and promote new clusters from
        high-weight CORRELATES edges.
        Enforces MAX_DRAFTS_PER_CLUSTER_HOUR rate limit.

        TODO Phase 6: replace PatternCluster.query.all() full-table scan
                      with a targeted filtered query for performance.
        """
        from aot.databases.models.ekg import PatternCluster, EdgeRecord, EdgeType

        now = utc_now()

        # Decay existing clusters
        # [PHASE 1.2] Apply 30-day filter to avoid full-table scans
        thirty_days_ago = now - timedelta(days=30)
        clusters = PatternCluster.query.filter(PatternCluster.last_seen_at >= thirty_days_ago).all()
        for cluster in clusters:
            if cluster.last_seen_at:
                days_elapsed = (now - cluster.last_seen_at).total_seconds() / 86400.0
                cluster.decay_score = max(
                    0.0,
                    cluster.decay_score * ((1.0 - DECAY_RATE_PER_DAY) ** days_elapsed),
                )
                db.session.add(cluster)

        # Rate limit: count clusters created in the last hour
        one_hour_ago = now - timedelta(hours=1)
        recent_count = PatternCluster.query.filter(
            PatternCluster.created_at >= one_hour_ago
        ).count()
        if recent_count >= MAX_DRAFTS_PER_CLUSTER_HOUR:
            return

        # Promote: find high-weight CORRELATES edges
        high_weight_edges = (
            EdgeRecord.query
            .filter(EdgeRecord.edge_type == EdgeType.CORRELATES)
            .filter(EdgeRecord.weight >= CLUSTER_PROMOTION_THRESHOLD)
            .limit(10)
            .all()
        )
        if len(high_weight_edges) >= 2:
            event_ids = list(
                {e.source_id for e in high_weight_edges}
                | {e.target_id for e in high_weight_edges}
            )
            avg_score = sum(e.weight for e in high_weight_edges) / len(high_weight_edges)
            cluster = PatternCluster(
                note_ids=[],
                event_ids=event_ids,
                correlation_score=round(avg_score, 4),
                predictive_trigger={},
                created_at=now,
                last_seen_at=now,
                decay_score=1.0,
            )
            db.session.add(cluster)

    # ------------------------------------------------------------------
    # Signal listener registration (called once in create_app)
    # ------------------------------------------------------------------
    @staticmethod
    def register_signal_listener() -> None:
        """
        Register a SQLAlchemy session after_commit listener that triggers
        EKG ingestion whenever a Notes row with category='ai_semantic' is committed.

        Uses after_commit (not after_insert) to guarantee the row is visible
        to the background EKG thread when it performs DB reads.

        Call once after db.init_app(app) in register_extensions().
        Idempotent — SQLAlchemy deduplicates identical listeners.
        """
        from sqlalchemy import event as sa_event

        def _after_commit(session):
            """Scan session's new objects for ai_semantic Notes after commit."""
            try:
                from aot.databases.models.notes import Notes
                from aot.databases.models.ekg import HumanNote
                for obj in session.new:
                    if isinstance(obj, Notes) and getattr(obj, 'category', None) == 'ai_semantic':
                        hn = HumanNote.from_notes_row(obj)
                        EKGService.ingest([hn])
            except Exception as exc:
                logger.warning("[EKGService] Signal listener error: %s", exc)

        sa_event.listen(db.session, 'after_commit', _after_commit)
        logger.info("[EKGService] Notes after_commit signal listener registered.")
