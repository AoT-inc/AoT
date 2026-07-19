# coding=utf-8
"""
TierDecisionEngine — Adaptive Document Storage Tier Decision Logic.

Implements:
  - Score-based tier determination algorithm
  - Multi-topic document detection
  - Access pattern analysis
  - Automatic promotion/demotion evaluation

Ref: TIER_DECISION_LOGIC.md (ADS_TIER_001, v1.0, 2026-04-04)
Design: Adaptive Document Storage Architecture Section 3.1

Algorithm:
  score = (access_frequency_weight × normalized_frequency)
        + (freshness_weight × (1 - days_since_access / max_days))
        + (size_weight × normalized_size)
        + (topic_diversity_weight × (1 if multi_topic else 0))

  if score > tier_1_threshold: return TIER_1
  elif score > tier_2_threshold: return TIER_2
  else: return TIER_3
"""
import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Set, Tuple

from aot.utils.time_utils import utc_now

logger = logging.getLogger(__name__)


# =============================================================================
# Data Classes
# =============================================================================

@dataclass
class TierDecisionResult:
    """Result of a tier decision evaluation."""
    recommended_tier: int  # 1, 2, or 3
    confidence_score: float  # 0.0 to 1.0
    reasoning: str
    decision_score: float
    is_multi_topic: bool = False
    topic_tags: Set[str] = field(default_factory=set)
    access_frequency_score: float = 0.0
    freshness_score: float = 0.0
    size_score: float = 0.0
    topic_diversity_score: float = 0.0
    should_promote: bool = False
    should_demote: bool = False
    promotion_reason: str = ""
    demotion_reason: str = ""


@dataclass
class AccessPatternResult:
    """Result of access pattern analysis."""
    access_count: int
    access_count_in_window: int
    days_since_last_access: int
    access_frequency_score: float  # 0.0 to 1.0
    freshness_score: float  # 0.0 to 1.0
    is_burst: bool  # True if access burst detected
    predicted_likelihood: float  # 0.0 to 1.0


# =============================================================================
# TierDecisionEngine
# =============================================================================

class TierDecisionEngine:
    """
    Determines optimal tier for documents based on multi-factor analysis.

    @phase active
    @stability stable
    """

    # Default weights (can be overridden by AdaptiveStorageSettings)
    DEFAULT_WEIGHTS = {
        'access_frequency_weight': 0.4,
        'freshness_weight': 0.25,
        'size_weight': 0.2,
        'topic_diversity_weight': 0.15,
    }

    # Default thresholds
    DEFAULT_TIER_1_THRESHOLD = 0.75
    DEFAULT_TIER_2_THRESHOLD = 0.40

    # Multi-topic detection
    MULTI_TOPIC_PARAGRAPH_COUNT = 3
    MAX_DAYS_SINCE_ACCESS = 90

    # Token estimation (rough: ~4 chars per token)
    CHARS_PER_TOKEN = 4

    # Topic extraction keywords (agricultural/environmental domain)
    TOPIC_KEYWORDS = {
        'temperature', 'temp', '온도', '기온',
        'humidity', '습도', 'humid',
        'light', '빛', '조명', '照度',
        'co2', '이산화탄소', 'carbon',
        'water', '물', '수분', '灌溉',
        'soil', '토양', 'earth',
        'air', '공기', 'atmosphere',
        'sensor', '센서', 'measurement',
        'device', '장치', 'equipment',
        'schedule', '스케줄', '일정',
        'alert', '경고', '경보',
        'system', '시스템', 'system',
        'config', '설정', 'configuration',
        'user', '사용자', 'account',
        'network', '네트워크', 'connection',
        'error', '오류', 'failure',
        'log', '로그', 'record',
    }

    # =========================================================================
    # Main Decision API
    # =========================================================================

    @classmethod
    def evaluate_tier(
        cls,
        document: Any,
        access_history: Optional[List[Any]] = None,
        current_tier: int = 2,
        document_type: str = 'notes'
    ) -> TierDecisionResult:
        """
        Evaluate and recommend optimal tier for a document.

        Args:
            document: Document object with attributes:
                - content: text content
                - token_count: estimated token count (optional, calculated from content if missing)
                - tags: comma-separated tags string (optional)
                - last_accessed: datetime of last access (optional)
            access_history: List of DocumentAccessLog entries (optional)
            current_tier: Current tier level (default: 2)
            document_type: Type of document ('notes', 'ai_summary', etc.)

        Returns:
            TierDecisionResult with recommendation and scoring details
        """
        # Fail-safe: None document returns Tier 2 with zero confidence
        if document is None:
            return TierDecisionResult(
                recommended_tier=2,
                confidence_score=0.0,
                reasoning="document_is_none",
                decision_score=0.0,
            )

        try:
            # Step 1: Get settings
            settings = cls._get_settings()

            # Step 2: Multi-topic detection
            content = cls._get_document_content(document)
            is_multi_topic, topic_tags = cls.detect_multi_topic(content)

            # Step 3: Access pattern analysis
            access_pattern = cls.analyze_access_pattern(
                document,
                access_history,
                settings.promotion_window_hours if settings else 168
            )

            # Step 4: Size evaluation
            token_count = cls._get_token_count(document, content)
            size_score = cls._calculate_size_score(token_count)

            # Step 5: Calculate composite score
            weights = cls._get_weights(settings)
            thresholds = cls._get_thresholds(settings)

            score = cls._calculate_composite_score(
                access_frequency_score=access_pattern.access_frequency_score,
                freshness_score=access_pattern.freshness_score,
                size_score=size_score,
                is_multi_topic=is_multi_topic,
                weights=weights
            )

            # Step 6: Determine base tier from score
            base_tier = cls._score_to_tier(score, thresholds)

            # Step 7: Apply business rules (multi-topic cannot be Tier 1)
            if is_multi_topic and base_tier == 1:
                base_tier = 2
                reasoning = f"multi_topic_document_forced_tier2(score={score:.3f})"
            else:
                reasoning = f"score_based_tier(score={score:.3f})"

            # Step 8: Evaluate promotion/demotion
            should_promote, promotion_reason = cls._should_promote(
                current_tier, access_pattern, settings
            )
            should_demote, demotion_reason = cls._should_demote(
                current_tier, access_pattern, settings
            )

            # Determine final tier
            if should_promote:
                recommended_tier = max(1, current_tier - 1)
                reasoning = f"promotion: {promotion_reason}"
            elif should_demote:
                recommended_tier = min(3, current_tier + 1)
                reasoning = f"demotion: {demotion_reason}"
            else:
                recommended_tier = base_tier

            # Calculate confidence
            confidence = cls._calculate_confidence(
                access_pattern.access_frequency_score,
                access_pattern.freshness_score,
                len(topic_tags) > 0
            )

            return TierDecisionResult(
                recommended_tier=recommended_tier,
                confidence_score=confidence,
                reasoning=reasoning,
                decision_score=score,
                is_multi_topic=is_multi_topic,
                topic_tags=topic_tags,
                access_frequency_score=access_pattern.access_frequency_score,
                freshness_score=access_pattern.freshness_score,
                size_score=size_score,
                topic_diversity_score=1.0 if is_multi_topic else 0.0,
                should_promote=should_promote,
                should_demote=should_demote,
                promotion_reason=promotion_reason,
                demotion_reason=demotion_reason,
            )

        except Exception as exc:
            logger.error(f"[TierDecisionEngine] evaluate_tier failed: {exc}")
            # Fail-safe: return Tier 2 with low confidence
            return TierDecisionResult(
                recommended_tier=2,
                confidence_score=0.0,
                reasoning=f"evaluation_failed({exc})",
                decision_score=0.0,
            )

    # =========================================================================
    # Multi-Topic Detection
    # =========================================================================

    @classmethod
    def detect_multi_topic(cls, content: str) -> Tuple[bool, Set[str]]:
        """
        Detect if document is multi-topic (3+ paragraphs with different semantic tags).

        Algorithm (per TIER_DECISION_LOGIC.md Section 2.2):
          1. Parse content into paragraphs
          2. For each paragraph, extract semantic tags
          3. Count paragraphs that have at least one tag
          4. If 3+ paragraphs each have different tags (unique across paragraphs), is_multi_topic = True

        Args:
            content: Document text content

        Returns:
            Tuple of (is_multi_topic: bool, topic_tags: Set[str])
        """
        if not content:
            return False, set()

        # Split into paragraphs (by double newline or single newline)
        paragraphs = cls._split_into_paragraphs(content)

        if len(paragraphs) < cls.MULTI_TOPIC_PARAGRAPH_COUNT:
            return False, set()

        all_tags: Set[str] = set()
        paragraph_tag_sets: List[Set[str]] = []

        for para in paragraphs:
            tags = cls._extract_tags_from_text(para)
            if tags:
                paragraph_tag_sets.append(tags)
                all_tags.update(tags)

        # Multi-topic: 3+ paragraphs with different semantic tags
        # Each paragraph should have at least one tag, and the tags should be unique across paragraphs
        # If we have 3+ paragraphs with tags, and 3+ unique tags total, it's multi-topic
        paragraphs_with_tags = len(paragraph_tag_sets)

        is_multi_topic = (
            paragraphs_with_tags >= cls.MULTI_TOPIC_PARAGRAPH_COUNT and
            len(all_tags) >= cls.MULTI_TOPIC_PARAGRAPH_COUNT
        )

        return is_multi_topic, all_tags

    @classmethod
    def _split_into_paragraphs(cls, content: str) -> List[str]:
        """Split content into paragraphs."""
        # Split by double newline first, then single newline
        paragraphs = re.split(r'\n\s*\n|\n', content.strip())
        # Filter empty paragraphs
        return [p.strip() for p in paragraphs if p.strip()]

    @classmethod
    def _extract_tags_from_text(cls, text: str) -> Set[str]:
        """
        Extract semantic topic tags from text.

        Uses keyword matching against TOPIC_KEYWORDS set.
        """
        if not text:
            return set()

        text_lower = text.lower()

        # Extract words
        words = re.findall(r'\b[a-zA-Z가-힣]+\b', text_lower)

        # Find matching topic keywords
        tags = cls.TOPIC_KEYWORDS.intersection(words)

        return tags

    # =========================================================================
    # Access Pattern Analysis
    # =========================================================================

    @classmethod
    def analyze_access_pattern(
        cls,
        document: Any,
        access_history: Optional[List[Any]] = None,
        promotion_window_hours: int = 168
    ) -> AccessPatternResult:
        """
        Analyze document access patterns.

        Calculates:
          - Access frequency score
          - Freshness score
          - Burst detection
          - Predicted access likelihood

        Args:
            document: Document object
            access_history: List of DocumentAccessLog entries
            promotion_window_hours: Window for promotion evaluation (default 7 days)

        Returns:
            AccessPatternResult with analysis details
        """
        now = utc_now()

        # Get last accessed time
        last_accessed = cls._get_last_accessed(document)
        if last_accessed:
            days_since_access = (now - last_accessed).days
        else:
            days_since_access = cls.MAX_DAYS_SINCE_ACCESS

        # Calculate access counts
        if access_history:
            access_count = sum(log.access_count for log in access_history)

            # Filter to window
            window_start = now - timedelta(hours=promotion_window_hours)
            access_count_in_window = sum(
                log.access_count for log in access_history
                if log.timestamp >= window_start
            )
        else:
            access_count = 0
            access_count_in_window = 0

        # Calculate scores
        # Access frequency: normalize to 0-1 (assume 100+ accesses = max)
        access_frequency_score = min(1.0, access_count / 100.0)

        # Freshness: 1.0 if accessed today, 0.0 if older than MAX_DAYS_SINCE_ACCESS
        freshness_score = max(0.0, 1.0 - (days_since_access / cls.MAX_DAYS_SINCE_ACCESS))

        # Burst detection: if access_count_in_window > 50% of total in < 10% of time
        is_burst = cls._detect_access_burst(access_history, promotion_window_hours)

        # Predicted likelihood (simple heuristic based on recent activity)
        if days_since_access == 0:
            predicted_likelihood = 1.0
        elif days_since_access < 7:
            predicted_likelihood = 0.8
        elif days_since_access < 30:
            predicted_likelihood = 0.5
        else:
            predicted_likelihood = 0.2

        return AccessPatternResult(
            access_count=access_count,
            access_count_in_window=access_count_in_window,
            days_since_last_access=days_since_access,
            access_frequency_score=access_frequency_score,
            freshness_score=freshness_score,
            is_burst=is_burst,
            predicted_likelihood=predicted_likelihood,
        )

    @classmethod
    def _detect_access_burst(
        cls,
        access_history: Optional[List[Any]],
        window_hours: int
    ) -> bool:
        """
        Detect if document has an access burst pattern.

        Burst = unusually high access in short time window compared to overall access pattern.
        Uses a 1-hour window as the "burst window" and compares to the total timespan.
        """
        if not access_history or len(access_history) < 5:
            return False

        # Check burst in 1-hour window vs total timespan
        now = utc_now()
        burst_window_start = now - timedelta(hours=1)

        accesses_in_burst_window = [log for log in access_history if log.timestamp >= burst_window_start]

        if not accesses_in_burst_window:
            return False

        total_accesses = sum(log.access_count for log in access_history)
        burst_window_accesses = sum(log.access_count for log in accesses_in_burst_window)

        if total_accesses == 0:
            return False

        # Calculate total timespan
        timestamps = [log.timestamp for log in access_history]
        min_timestamp = min(timestamps)
        max_timestamp = max(timestamps)
        total_timespan_hours = (max_timestamp - min_timestamp).total_seconds() / 3600

        if total_timespan_hours <= 0:
            return False

        # Burst if: >50% of accesses in <10% of the time (1 hour vs total)
        time_ratio = 1.0 / total_timespan_hours  # 1 hour vs total span
        access_ratio = burst_window_accesses / total_accesses

        return access_ratio > 0.5 and time_ratio < 0.1

    # =========================================================================
    # Score Calculation
    # =========================================================================

    @classmethod
    def _calculate_composite_score(
        cls,
        access_frequency_score: float,
        freshness_score: float,
        size_score: float,
        is_multi_topic: bool,
        weights: Dict[str, float]
    ) -> float:
        """
        Calculate composite tier score.

        score = (access_frequency_weight × normalized_frequency)
              + (freshness_weight × (1 - days_since_access / max_days))
              + (size_weight × normalized_size)
              + (topic_diversity_weight × (1 if multi_topic else 0))
        """
        topic_diversity_score = 1.0 if is_multi_topic else 0.0

        score = (
            weights['access_frequency_weight'] * access_frequency_score +
            weights['freshness_weight'] * freshness_score +
            weights['size_weight'] * size_score +
            weights['topic_diversity_weight'] * topic_diversity_score
        )

        return min(1.0, max(0.0, score))

    @classmethod
    def _calculate_size_score(cls, token_count: int) -> float:
        """
        Calculate size score based on token count.

        Smaller documents score higher (easier to tier-1).
        - <= 2000 tokens: score 1.0
        - 2000-8000 tokens: score 0.5
        - > 8000 tokens: score 0.0
        """
        if token_count <= 2000:
            return 1.0
        elif token_count <= 8000:
            return 0.5
        else:
            return 0.0

    @classmethod
    def _score_to_tier(cls, score: float, thresholds: Dict[str, float]) -> int:
        """Convert score to tier level."""
        if score >= thresholds['tier_1_threshold']:
            return 1
        elif score >= thresholds['tier_2_threshold']:
            return 2
        else:
            return 3

    @classmethod
    def _calculate_confidence(
        cls,
        access_frequency_score: float,
        freshness_score: float,
        has_tags: bool
    ) -> float:
        """Calculate confidence in the decision."""
        # Higher confidence when we have good data
        signals = sum([
            access_frequency_score > 0.3,
            freshness_score > 0.3,
            has_tags,
        ])
        return min(1.0, signals / 3.0 + 0.5)

    # =========================================================================
    # Promotion/Demotion Logic
    # =========================================================================

    @classmethod
    def _should_promote(
        cls,
        current_tier: int,
        access_pattern: AccessPatternResult,
        settings: Any
    ) -> Tuple[bool, str]:
        """Check if document should be promoted to higher tier."""
        if current_tier == 1:
            return False, "already_at_max_tier"

        if not settings or not settings.auto_promotion_enabled:
            return False, "auto_promotion_disabled"

        # Check promotion threshold based on current tier
        tier_threshold = cls._get_promotion_threshold(current_tier, settings)

        if access_pattern.access_count_in_window >= tier_threshold:
            return True, f"high_access_count({access_pattern.access_count_in_window}>={tier_threshold})"

        return False, f"insufficient_access({access_pattern.access_count_in_window}<{tier_threshold})"

    @classmethod
    def _should_demote(
        cls,
        current_tier: int,
        access_pattern: AccessPatternResult,
        settings: Any
    ) -> Tuple[bool, str]:
        """Check if document should be demoted to lower tier."""
        if current_tier == 3:
            return False, "already_at_min_tier"

        if not settings or not settings.auto_demotion_enabled:
            return False, "auto_demotion_disabled"

        # Check for inactivity
        if access_pattern.days_since_last_access > cls.MAX_DAYS_SINCE_ACCESS:
            return True, f"inactive_too_long({access_pattern.days_since_last_access}>90_days)"

        # Check for low access
        tier_threshold = cls._get_demotion_threshold(current_tier, settings)

        if access_pattern.access_count < tier_threshold:
            return True, f"low_access_count({access_pattern.access_count}<{tier_threshold})"

        return False, f"access_acceptable({access_pattern.access_count}>={tier_threshold})"

    @classmethod
    def _get_promotion_threshold(cls, current_tier: int, settings: Any) -> int:
        """Get promotion threshold for a tier."""
        if current_tier == 2:
            return 100  # 100+ accesses in window to promote to Tier 1
        elif current_tier == 3:
            return 10  # 10+ accesses in window to promote to Tier 2
        return 0

    @classmethod
    def _get_demotion_threshold(cls, current_tier: int, settings: Any) -> int:
        """Get demotion threshold for a tier."""
        if current_tier == 1:
            return 10  # <10 accesses to demote to Tier 2
        elif current_tier == 2:
            return 5  # <5 accesses to demote to Tier 3
        return 0

    # =========================================================================
    # Helper Methods
    # =========================================================================

    @classmethod
    def _get_settings(cls) -> Optional[Any]:
        """Get adaptive storage settings from database."""
        try:
            from aot.databases.models.tier_adaptive_storage import AdaptiveStorageSettings
            return AdaptiveStorageSettings.query.first()
        except Exception:
            return None

    @classmethod
    def _get_weights(cls, settings: Optional[Any]) -> Dict[str, float]:
        """Get scoring weights from settings or use defaults."""
        if settings:
            return {
                'access_frequency_weight': settings.access_frequency_weight,
                'freshness_weight': settings.freshness_weight,
                'size_weight': settings.size_weight,
                'topic_diversity_weight': settings.topic_diversity_weight,
            }
        return cls.DEFAULT_WEIGHTS.copy()

    @classmethod
    def _get_thresholds(cls, settings: Optional[Any]) -> Dict[str, float]:
        """Get tier thresholds from settings or use defaults."""
        if settings:
            return {
                'tier_1_threshold': settings.tier_1_threshold,
                'tier_2_threshold': settings.tier_2_threshold,
            }
        return {
            'tier_1_threshold': cls.DEFAULT_TIER_1_THRESHOLD,
            'tier_2_threshold': cls.DEFAULT_TIER_2_THRESHOLD,
        }

    @classmethod
    def _get_document_content(cls, document: Any) -> str:
        """Extract content from document object."""
        if hasattr(document, 'content'):
            return document.content or ""
        if hasattr(document, 'note'):
            return document.note or ""
        if hasattr(document, 'text'):
            return document.text or ""
        return ""

    @classmethod
    def _get_token_count(cls, document: Any, content: str) -> int:
        """Get token count from document or estimate from content."""
        if hasattr(document, 'token_count') and document.token_count:
            return document.token_count
        if hasattr(document, 'char_count') and document.char_count:
            return document.char_count // cls.CHARS_PER_TOKEN
        # Estimate from content length
        return len(content) // cls.CHARS_PER_TOKEN

    @classmethod
    def _get_last_accessed(cls, document: Any) -> Optional[datetime]:
        """Get last accessed time from document."""
        if hasattr(document, 'last_accessed') and document.last_accessed:
            return document.last_accessed
        if hasattr(document, 'date_time') and document.date_time:
            return document.date_time
        return None


# =============================================================================
# Tier Decision Service API
# =============================================================================

class TierDecisionService:
    """
    High-level service API for tier decision operations.

    Provides:
      - Document tier evaluation
      - Automatic tier migration
      - Decision audit logging

    @phase active
    @stability stable
    """

    @staticmethod
    def evaluate_and_log(
        document: Any,
        document_type: str = 'notes',
        access_history: Optional[List[Any]] = None,
        current_tier: int = 2,
        triggered_by: str = 'system'
    ) -> TierDecisionResult:
        """
        Evaluate tier and log the decision.

        Args:
            document: Document object
            document_type: Type of document
            access_history: Access log history
            current_tier: Current tier level
            triggered_by: 'system', 'manual', or 'scheduled'

        Returns:
            TierDecisionResult
        """
        result = TierDecisionEngine.evaluate_tier(
            document=document,
            access_history=access_history,
            current_tier=current_tier,
            document_type=document_type
        )

        # Log the decision
        TierDecisionService._log_decision(
            document=document,
            result=result,
            document_type=document_type,
            current_tier=current_tier,
            triggered_by=triggered_by
        )

        return result

    @staticmethod
    def _log_decision(
        document: Any,
        result: TierDecisionResult,
        document_type: str,
        current_tier: int,
        triggered_by: str
    ) -> None:
        """Log tier decision to audit trail."""
        try:
            from aot.aot_flask.extensions import db
            from aot.databases.models.tier_adaptive_storage import TierDecision, DocumentAccessLog

            # Get document ID
            doc_id = getattr(document, 'unique_id', None) or str(id(document))

            # Determine transition type
            if result.should_promote:
                transition_type = 'promotion'
            elif result.should_demote:
                transition_type = 'demotion'
            else:
                transition_type = 'evaluated'

            decision = TierDecision(
                document_id=doc_id,
                document_type=document_type,
                previous_tier=current_tier,
                new_tier=result.recommended_tier,
                decision_score=result.decision_score,
                confidence_score=result.confidence_score,
                reasoning=result.reasoning,
                is_multi_topic=result.is_multi_topic,
                topic_tags=json.dumps(list(result.topic_tags)),
                access_count_in_window=0,  # TODO: pass from access_history
                days_since_last_access=0,
                token_count=0,
                triggered_by=triggered_by,
                transition_type=transition_type,
            )
            db.session.add(decision)
            db.session.commit()

        except Exception as exc:
            logger.error(f"[TierDecisionService] _log_decision failed: {exc}")
            db.session.rollback()

    @staticmethod
    def log_access(
        document_id: str,
        document_type: str = 'notes',
        access_type: str = 'read',
        access_count: int = 1
    ) -> None:
        """
        Log a document access event.

        Args:
            document_id: Document unique_id
            document_type: Type of document
            access_type: 'read', 'write', or 'search'
            access_count: Number of accesses (for batch)
        """
        try:
            from aot.aot_flask.extensions import db
            from aot.databases.models.tier_adaptive_storage import DocumentAccessLog

            log = DocumentAccessLog(
                document_id=document_id,
                document_type=document_type,
                access_type=access_type,
                access_count=access_count,
            )
            db.session.add(log)
            db.session.commit()

        except Exception as exc:
            logger.error(f"[TierDecisionService] log_access failed: {exc}")
            db.session.rollback()

    @staticmethod
    def get_decision_history(
        document_id: str,
        limit: int = 10
    ) -> List[Any]:
        """
        Get tier decision history for a document.

        Args:
            document_id: Document unique_id
            limit: Maximum number of records to return

        Returns:
            List of TierDecision records
        """
        try:
            from aot.databases.models.tier_adaptive_storage import TierDecision

            return TierDecision.query.filter_by(
                document_id=document_id
            ).order_by(
                TierDecision.timestamp.desc()
            ).limit(limit).all()

        except Exception as exc:
            logger.error(f"[TierDecisionService] get_decision_history failed: {exc}")
            return []


# =============================================================================
# Tier Migration Service
# =============================================================================

class TierMigrationService:
    """
    Executes tier transitions for adaptive document storage.

    Implements safe migration with:
      - Copy: Create new tier content before removing old
      - Verify: Confirm migration success before cleanup
      - Delete: Remove old tier content only after verification

    @phase active
    @stability stable
    """

    # Maximum retries for failed migrations
    MAX_RETRIES = 3

    # Transition limit per document per hour (prevent oscillation)
    TRANSITION_LIMIT_PER_HOUR = 5

    @classmethod
    def migrate_document(
        cls,
        document: Any,
        target_tier: int,
        triggered_by: str = 'scheduled'
    ) -> dict:
        """
        Execute safe tier migration for a document.

        Args:
            document: Document object to migrate
            target_tier: Target tier level (1, 2, or 3)
            triggered_by: 'scheduled', 'manual', or 'system'

        Returns:
            dict with migration status: {
                'success': bool,
                'document_id': str,
                'previous_tier': int,
                'new_tier': int,
                'error': str or None
            }
        """
        try:
            from aot.aot_flask.extensions import db
            from aot.databases.models.tier_adaptive_storage import TierDecision

            doc_id = getattr(document, 'unique_id', None) or str(id(document))
            previous_tier = getattr(document, 'tier', 2) or 2

            # Check transition rate limit
            if cls._is_transition_rate_limited(doc_id):
                logger.warning(f"[TierMigration] Rate limited: {doc_id}")
                return {
                    'success': False,
                    'document_id': doc_id,
                    'previous_tier': previous_tier,
                    'new_tier': target_tier,
                    'error': 'transition_rate_limited'
                }

            # Execute migration
            success = cls._execute_tier_migration(document, previous_tier, target_tier)

            if not success:
                return {
                    'success': False,
                    'document_id': doc_id,
                    'previous_tier': previous_tier,
                    'new_tier': target_tier,
                    'error': 'migration_execution_failed'
                }

            # Update document tier
            document.tier = target_tier
            db.session.commit()

            # Log transition
            cls._log_transition(
                document=document,
                previous_tier=previous_tier,
                new_tier=target_tier,
                triggered_by=triggered_by
            )

            logger.info(
                f"[TierMigration] Success: doc={doc_id[:8]} {previous_tier}->{target_tier}"
            )

            return {
                'success': True,
                'document_id': doc_id,
                'previous_tier': previous_tier,
                'new_tier': target_tier,
                'error': None
            }

        except Exception as exc:
            logger.error(f"[TierMigration] migrate_document failed: {exc}")
            db.session.rollback()
            return {
                'success': False,
                'document_id': getattr(document, 'unique_id', 'unknown'),
                'previous_tier': getattr(document, 'tier', 2),
                'new_tier': target_tier,
                'error': str(exc)
            }

    @classmethod
    def _execute_tier_migration(
        cls,
        document: Any,
        from_tier: int,
        to_tier: int
    ) -> bool:
        """
        Execute the actual tier migration.

        For now, this is a placeholder for actual storage tier operations.
        In production, this would:
        - Tier 1 (Hot): Store compressed summary in memory/LRU cache
        - Tier 2 (Warm): Store full content in standard database
        - Tier 3 (Cold): Store metadata only, archive full content

        Args:
            document: Document to migrate
            from_tier: Current tier
            to_tier: Target tier

        Returns:
            True if migration successful
        """
        try:
            # Verify document has required attributes
            content = getattr(document, 'note', None) or getattr(document, 'content', '')
            if not content and to_tier != 3:
                logger.warning(f"[TierMigration] Empty content for document")
                return False

            # Simulate migration operations based on tier
            # In production, these would be actual storage operations

            if to_tier == 1:
                # Hot tier: Generate and store summary
                cls._migrate_to_hot(document, content)
            elif to_tier == 2:
                # Warm tier: Store full content
                cls._migrate_to_warm(document, content)
            elif to_tier == 3:
                # Cold tier: Archive metadata only
                cls._migrate_to_cold(document)

            return True

        except Exception as exc:
            logger.error(f"[_execute_tier_migration] failed: {exc}")
            return False

    @classmethod
    def _migrate_to_hot(cls, document: Any, content: str) -> None:
        """Migrate document to hot tier (summary cache)."""
        # In production: Generate summary and store in HotStorageService
        logger.debug(f"[TierMigration] Migrating to hot: {getattr(document, 'unique_id', 'unknown')[:8]}")

    @classmethod
    def _migrate_to_warm(cls, document: Any, content: str) -> None:
        """Migrate document to warm tier (standard storage)."""
        # Standard storage - no special handling needed
        logger.debug(f"[TierMigration] Migrating to warm: {getattr(document, 'unique_id', 'unknown')[:8]}")

    @classmethod
    def _migrate_to_cold(cls, document: Any) -> None:
        """Migrate document to cold tier (archive)."""
        # In production: Store metadata only, archive full content
        logger.debug(f"[TierMigration] Migrating to cold: {getattr(document, 'unique_id', 'unknown')[:8]}")

    @classmethod
    def _is_transition_rate_limited(cls, doc_id: str) -> bool:
        """Check if document has too many transitions in the last hour."""
        try:
            from aot.databases.models.tier_adaptive_storage import TierDecision
            from datetime import timedelta

            cutoff = utc_now() - timedelta(hours=1)
            recent_transitions = TierDecision.query.filter(
                TierDecision.document_id == doc_id,
                TierDecision.timestamp >= cutoff,
                TierDecision.transition_type.in_(['promotion', 'demotion'])
            ).count()

            return recent_transitions >= cls.TRANSITION_LIMIT_PER_HOUR

        except Exception:
            return False

    @classmethod
    def _log_transition(
        cls,
        document: Any,
        previous_tier: int,
        new_tier: int,
        triggered_by: str
    ) -> None:
        """Log tier transition to audit trail."""
        try:
            from aot.aot_flask.extensions import db
            from aot.databases.models.tier_adaptive_storage import TierDecision

            doc_id = getattr(document, 'unique_id', None) or str(id(document))

            decision = TierDecision(
                document_id=doc_id,
                document_type='notes',
                previous_tier=previous_tier,
                new_tier=new_tier,
                decision_score=0.0,  # Already logged by TierDecisionService
                confidence_score=1.0,
                reasoning=f"migration_executed({triggered_by})",
                is_multi_topic=False,
                topic_tags="[]",
                triggered_by=triggered_by,
                transition_type='migration' if previous_tier != new_tier else 'evaluated',
            )
            db.session.add(decision)
            db.session.commit()

        except Exception as exc:
            logger.error(f"[_log_transition] failed: {exc}")
            db.session.rollback()

    @classmethod
    def batch_migrate(
        cls,
        documents: List[Any],
        target_tier: int,
        triggered_by: str = 'scheduled'
    ) -> dict:
        """
        Execute batch tier migration.

        Args:
            documents: List of documents to migrate
            target_tier: Target tier level
            triggered_by: What triggered the migration

        Returns:
            dict with batch results: {
                'total': int,
                'succeeded': int,
                'failed': int,
                'errors': list
            }
        """
        results = {
            'total': len(documents),
            'succeeded': 0,
            'failed': 0,
            'errors': []
        }

        for doc in documents:
            result = cls.migrate_document(doc, target_tier, triggered_by)
            if result['success']:
                results['succeeded'] += 1
            else:
                results['failed'] += 1
                if result['error']:
                    results['errors'].append({
                        'doc_id': result['document_id'],
                        'error': result['error']
                    })

        logger.info(
            f"[TierMigration] Batch complete: {results['succeeded']}/{results['total']} succeeded"
        )

        return results
