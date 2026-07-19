# coding=utf-8
"""
Unit tests for TierDecisionEngine.

Tests:
  - Multi-topic detection (≥95% accuracy target)
  - Score calculation algorithm
  - Promotion/demotion logic
  - Edge cases

Run: python -m pytest aot/tests/test_tier_decision_engine.py -v
"""
import unittest
from unittest.mock import MagicMock, patch
from datetime import datetime, timedelta

import sys
import os
import logging

# Set up logging
logging.basicConfig(level=logging.INFO)

# Add parent directory to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), os.path.pardir, os.path.pardir)))

# Mock time_utils to avoid pytz dependency
sys.modules['aot.utils.time_utils'] = MagicMock()
sys.modules['aot.utils.time_utils'].utc_now = datetime.utcnow

# Now import the module under test
from aot.ai.services.tier_decision_engine import TierDecisionEngine, TierDecisionResult, AccessPatternResult


class TestTierDecisionEngine(unittest.TestCase):
    """Test cases for TierDecisionEngine."""

    # =========================================================================
    # Multi-Topic Detection Tests
    # =========================================================================

    def test_multi_topic_detection_single_topic(self):
        """Single topic document should not be flagged as multi-topic."""
        content = """
        Temperature sensor reading is 25 degrees.
        Temperature sensor reading is 26 degrees.
        Temperature sensor reading is 27 degrees.
        """
        is_multi, tags = TierDecisionEngine.detect_multi_topic(content)

        self.assertFalse(is_multi)
        logging.info("PASS: Single topic document correctly identified as not multi-topic")

    def test_multi_topic_detection_multiple_topics(self):
        """Document with 3+ different semantic topics should be flagged as multi-topic."""
        content = """
        Temperature sensor reading is 25 degrees.
        Humidity level is at 65 percent.
        Light conditions are optimal for growth.
        """
        is_multi, tags = TierDecisionEngine.detect_multi_topic(content)

        self.assertTrue(is_multi)
        self.assertGreaterEqual(len(tags), 3)
        logging.info(f"PASS: Multi-topic document correctly identified. Tags: {tags}")

    def test_multi_topic_detection_empty_content(self):
        """Empty content should not be flagged as multi-topic."""
        is_multi, tags = TierDecisionEngine.detect_multi_topic("")

        self.assertFalse(is_multi)
        self.assertEqual(len(tags), 0)
        logging.info("PASS: Empty content correctly handled")

    def test_multi_topic_detection_short_content(self):
        """Content with fewer than 3 paragraphs should not be multi-topic."""
        content = """
        Temperature is 25.
        Humidity is 65.
        """
        is_multi, tags = TierDecisionEngine.detect_multi_topic(content)

        self.assertFalse(is_multi)
        logging.info("PASS: Short content correctly handled")

    def test_multi_topic_detection_korean_keywords(self):
        """Korean keywords should be detected for topic classification."""
        content = """
        온도 센서 readings are at 25 degrees.
        습도 수준은 65 percent.
        조명 조건이 충분합니다.
        """
        is_multi, tags = TierDecisionEngine.detect_multi_topic(content)

        self.assertTrue(is_multi)
        logging.info(f"PASS: Korean keywords detected. Tags: {tags}")

    def test_multi_topic_detection_mixed_language(self):
        """Mixed language content should work correctly."""
        content = """
        Temperature sensor reading is 25C. 온도 센서.
        Humidity level is at 65%. 습도.
        Light conditions are optimal. 조명.
        """
        is_multi, tags = TierDecisionEngine.detect_multi_topic(content)

        self.assertTrue(is_multi)
        self.assertGreaterEqual(len(tags), 3)
        logging.info(f"PASS: Mixed language content. Tags: {tags}")

    def test_topic_extraction_keywords(self):
        """Verify topic keywords are properly extracted."""
        text = "Temperature sensor reading shows 25 degrees with humidity at 65 percent."
        tags = TierDecisionEngine._extract_tags_from_text(text)

        self.assertIn('temperature', tags)
        self.assertIn('humidity', tags)
        self.assertIn('sensor', tags)
        logging.info(f"PASS: Topic keywords extracted: {tags}")

    # =========================================================================
    # Score Calculation Tests
    # =========================================================================

    def test_score_calculation_basic(self):
        """Test basic score calculation."""
        weights = TierDecisionEngine.DEFAULT_WEIGHTS.copy()

        score = TierDecisionEngine._calculate_composite_score(
            access_frequency_score=0.8,
            freshness_score=0.7,
            size_score=1.0,
            is_multi_topic=False,
            weights=weights
        )

        expected = (
            0.4 * 0.8 +
            0.25 * 0.7 +
            0.2 * 1.0 +
            0.15 * 0.0
        )
        self.assertAlmostEqual(score, expected, places=3)
        logging.info(f"PASS: Score calculation correct. Score: {score}")

    def test_score_calculation_multi_topic(self):
        """Multi-topic documents get topic diversity bonus."""
        weights = TierDecisionEngine.DEFAULT_WEIGHTS.copy()

        # With multi-topic
        score_multi = TierDecisionEngine._calculate_composite_score(
            access_frequency_score=0.5,
            freshness_score=0.5,
            size_score=0.5,
            is_multi_topic=True,
            weights=weights
        )

        # Without multi-topic
        score_single = TierDecisionEngine._calculate_composite_score(
            access_frequency_score=0.5,
            freshness_score=0.5,
            size_score=0.5,
            is_multi_topic=False,
            weights=weights
        )

        # Multi-topic should have higher score due to topic diversity weight
        self.assertGreater(score_multi, score_single)
        self.assertAlmostEqual(score_multi - score_single, weights['topic_diversity_weight'], places=3)
        logging.info(f"PASS: Multi-topic scoring correct. Multi: {score_multi}, Single: {score_single}")

    def test_size_score_small_document(self):
        """Small documents (<2000 tokens) should get max size score."""
        score = TierDecisionEngine._calculate_size_score(1500)
        self.assertEqual(score, 1.0)
        logging.info("PASS: Small document size score correct")

    def test_size_score_medium_document(self):
        """Medium documents (2000-8000 tokens) should get 0.5 size score."""
        score = TierDecisionEngine._calculate_size_score(5000)
        self.assertEqual(score, 0.5)
        logging.info("PASS: Medium document size score correct")

    def test_size_score_large_document(self):
        """Large documents (>8000 tokens) should get 0.0 size score."""
        score = TierDecisionEngine._calculate_size_score(10000)
        self.assertEqual(score, 0.0)
        logging.info("PASS: Large document size score correct")

    def test_score_to_tier_thresholds(self):
        """Test score to tier conversion."""
        thresholds = {
            'tier_1_threshold': 0.75,
            'tier_2_threshold': 0.40,
        }

        # Tier 1: score >= 0.75
        self.assertEqual(TierDecisionEngine._score_to_tier(0.8, thresholds), 1)
        self.assertEqual(TierDecisionEngine._score_to_tier(0.75, thresholds), 1)

        # Tier 2: 0.40 <= score < 0.75
        self.assertEqual(TierDecisionEngine._score_to_tier(0.60, thresholds), 2)
        self.assertEqual(TierDecisionEngine._score_to_tier(0.40, thresholds), 2)

        # Tier 3: score < 0.40
        self.assertEqual(TierDecisionEngine._score_to_tier(0.30, thresholds), 3)
        self.assertEqual(TierDecisionEngine._score_to_tier(0.0, thresholds), 3)
        logging.info("PASS: Score to tier conversion correct")

    # =========================================================================
    # Access Pattern Analysis Tests
    # =========================================================================

    def test_access_pattern_no_history(self):
        """Document with no access history should have low scores."""
        # Use a proper mock that doesn't have unexpected attributes
        mock_doc = MagicMock(spec=['last_accessed', 'date_time'])
        mock_doc.last_accessed = None
        mock_doc.date_time = None

        result = TierDecisionEngine.analyze_access_pattern(
            document=mock_doc,
            access_history=None
        )

        self.assertEqual(result.access_count, 0)
        self.assertEqual(result.access_count_in_window, 0)
        # Freshness score for document with no last_accessed should be 0
        self.assertEqual(result.freshness_score, 0.0)
        logging.info(f"PASS: No history pattern analyzed. Freshness: {result.freshness_score}")

    def test_access_pattern_high_frequency(self):
        """High frequency accessed document should have high access score."""
        mock_doc = MagicMock()
        mock_doc.last_accessed = datetime.utcnow() - timedelta(hours=1)

        # Create mock access history with 100+ accesses
        mock_history = []
        for i in range(100):
            log = MagicMock()
            log.access_count = 1
            log.timestamp = datetime.utcnow() - timedelta(hours=i)
            mock_history.append(log)

        result = TierDecisionEngine.analyze_access_pattern(
            document=mock_doc,
            access_history=mock_history,
            promotion_window_hours=168
        )

        self.assertGreater(result.access_frequency_score, 0.9)
        self.assertGreater(result.freshness_score, 0.9)
        logging.info(f"PASS: High frequency pattern correct. Access freq: {result.access_frequency_score}")

    def test_access_pattern_burst_detection(self):
        """Detect access bursts (unusually high access in short time)."""
        mock_doc = MagicMock()
        mock_doc.last_accessed = datetime.utcnow() - timedelta(hours=1)

        # Create burst pattern: 50 accesses in last hour, 10 accesses over 30 days
        mock_history = []

        # Recent burst - concentrated in last 10 minutes
        for i in range(50):
            log = MagicMock()
            log.access_count = 1
            log.timestamp = datetime.utcnow() - timedelta(minutes=i)
            mock_history.append(log)

        # Old accesses - spread over long period
        for i in range(10):
            log = MagicMock()
            log.access_count = 1
            log.timestamp = datetime.utcnow() - timedelta(days=i+5)
            mock_history.append(log)

        result = TierDecisionEngine.analyze_access_pattern(
            document=mock_doc,
            access_history=mock_history,
            promotion_window_hours=168  # 7 days
        )

        # Burst detection checks if >50% of accesses happened in <10% of the time
        # In this case: 50 in 10 minutes vs 10 in 30 days = burst
        self.assertTrue(result.is_burst)
        logging.info(f"PASS: Burst detection correct. Is burst: {result.is_burst}")

    # =========================================================================
    # Promotion/Demotion Logic Tests
    # =========================================================================

    def test_promotion_already_max_tier(self):
        """Document already at Tier 1 should not promote."""
        mock_settings = MagicMock()
        mock_settings.auto_promotion_enabled = True

        mock_pattern = MagicMock()
        mock_pattern.access_count_in_window = 100

        should_promote, reason = TierDecisionEngine._should_promote(
            current_tier=1,
            access_pattern=mock_pattern,
            settings=mock_settings
        )

        self.assertFalse(should_promote)
        self.assertIn("already_at_max_tier", reason)
        logging.info("PASS: Already max tier cannot promote")

    def test_promotion_threshold_tier2_to_tier1(self):
        """Tier 2 document needs 100+ accesses in window to promote to Tier 1."""
        mock_settings = MagicMock()
        mock_settings.auto_promotion_enabled = True

        # Below threshold
        mock_pattern_low = MagicMock()
        mock_pattern_low.access_count_in_window = 50

        should_promote, reason = TierDecisionEngine._should_promote(
            current_tier=2,
            access_pattern=mock_pattern_low,
            settings=mock_settings
        )

        self.assertFalse(should_promote)

        # Above threshold
        mock_pattern_high = MagicMock()
        mock_pattern_high.access_count_in_window = 100

        should_promote, reason = TierDecisionEngine._should_promote(
            current_tier=2,
            access_pattern=mock_pattern_high,
            settings=mock_settings
        )

        self.assertTrue(should_promote)
        logging.info("PASS: Promotion threshold correct")

    def test_demotion_already_min_tier(self):
        """Document already at Tier 3 should not demote."""
        mock_settings = MagicMock()
        mock_settings.auto_demotion_enabled = True

        mock_pattern = MagicMock()
        mock_pattern.days_since_last_access = 100
        mock_pattern.access_count = 0

        should_demote, reason = TierDecisionEngine._should_demote(
            current_tier=3,
            access_pattern=mock_pattern,
            settings=mock_settings
        )

        self.assertFalse(should_demote)
        self.assertIn("already_at_min_tier", reason)
        logging.info("PASS: Already min tier cannot demote")

    def test_demotion_inactivity(self):
        """Document inactive for >90 days should demote."""
        mock_settings = MagicMock()
        mock_settings.auto_demotion_enabled = True

        mock_pattern = MagicMock()
        mock_pattern.days_since_last_access = 100
        mock_pattern.access_count = 50

        should_demote, reason = TierDecisionEngine._should_demote(
            current_tier=1,
            access_pattern=mock_pattern,
            settings=mock_settings
        )

        self.assertTrue(should_demote)
        self.assertIn("inactive_too_long", reason)
        logging.info("PASS: Inactivity demotion correct")

    # =========================================================================
    # Integration Tests
    # =========================================================================

    def test_evaluate_tier_basic(self):
        """Test full tier evaluation."""
        mock_doc = MagicMock()
        mock_doc.content = "Temperature sensor reading is 25 degrees."
        mock_doc.token_count = 1000
        mock_doc.last_accessed = datetime.utcnow() - timedelta(hours=1)

        result = TierDecisionEngine.evaluate_tier(
            document=mock_doc,
            access_history=None,
            current_tier=2
        )

        self.assertIsInstance(result, TierDecisionResult)
        self.assertIn(result.recommended_tier, [1, 2, 3])
        self.assertGreaterEqual(result.confidence_score, 0.0)
        self.assertLessEqual(result.confidence_score, 1.0)
        self.assertGreater(result.decision_score, 0.0)
        logging.info(f"PASS: Full evaluation works. Tier: {result.recommended_tier}, Score: {result.decision_score}")

    def test_evaluate_tier_multi_topic_forces_tier2(self):
        """Multi-topic documents cannot be Tier 1."""
        mock_doc = MagicMock()
        mock_doc.content = """
        Temperature is 25 degrees.
        Humidity is 65 percent.
        Light is optimal.
        CO2 levels are normal.
        """
        mock_doc.token_count = 1000
        mock_doc.last_accessed = datetime.utcnow() - timedelta(hours=1)

        result = TierDecisionEngine.evaluate_tier(
            document=mock_doc,
            access_history=None,
            current_tier=2
        )

        # Multi-topic document should not be Tier 1
        self.assertNotEqual(result.recommended_tier, 1)
        self.assertTrue(result.is_multi_topic)
        logging.info(f"PASS: Multi-topic forces tier 2. Result: {result.recommended_tier}")

    def test_evaluate_tier_fail_safe(self):
        """Failed evaluation should return Tier 2 with low confidence."""
        # Pass None as document to trigger fail-safe
        result = TierDecisionEngine.evaluate_tier(
            document=None,
            access_history=None,
            current_tier=2
        )

        self.assertEqual(result.recommended_tier, 2)
        self.assertEqual(result.confidence_score, 0.0)
        self.assertIn("document_is_none", result.reasoning)
        logging.info("PASS: Fail-safe returns Tier 2")

    # =========================================================================
    # Performance Tests
    # =========================================================================

    def test_performance_1000_documents(self):
        """Test performance: 1000+ documents should evaluate in <5 seconds."""
        import time

        mock_doc = MagicMock()
        mock_doc.content = "Temperature sensor reading is 25 degrees. Humidity is 65 percent. Light is optimal."
        mock_doc.token_count = 1000
        mock_doc.last_accessed = datetime.utcnow() - timedelta(hours=1)

        start_time = time.time()

        for i in range(1000):
            TierDecisionEngine.evaluate_tier(
                document=mock_doc,
                access_history=None,
                current_tier=2
            )

        elapsed = time.time() - start_time

        self.assertLess(elapsed, 5.0)
        logging.info(f"PASS: 1000 documents evaluated in {elapsed:.2f}s (<5s requirement)")


class TestTierDecisionAlgorithm(unittest.TestCase):
    """Test the scoring algorithm from the design document."""

    def test_algorithm_exact_calculation(self):
        """Verify algorithm matches design document exactly."""
        weights = TierDecisionEngine.DEFAULT_WEIGHTS.copy()

        # Test case: high scores to achieve Tier 1 threshold
        access_frequency_score = 1.0
        freshness_score = 1.0
        size_score = 1.0
        is_multi_topic = False

        score = TierDecisionEngine._calculate_composite_score(
            access_frequency_score=access_frequency_score,
            freshness_score=freshness_score,
            size_score=size_score,
            is_multi_topic=is_multi_topic,
            weights=weights
        )

        expected = (
            weights['access_frequency_weight'] * access_frequency_score +
            weights['freshness_weight'] * freshness_score +
            weights['size_weight'] * size_score +
            weights['topic_diversity_weight'] * 0  # multi-topic = False
        )

        self.assertAlmostEqual(score, expected, places=4)
        # With max scores, should exceed Tier 1 threshold (0.75)
        self.assertGreaterEqual(score, TierDecisionEngine.DEFAULT_TIER_1_THRESHOLD)
        logging.info(f"PASS: Algorithm matches design. Score: {score}")


if __name__ == '__main__':
    unittest.main(verbosity=2)
