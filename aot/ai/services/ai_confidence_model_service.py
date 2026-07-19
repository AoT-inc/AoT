# coding=utf-8
"""
AIConfidenceModelService - Phase 6 Parameter-Level Confidence Models

Provides parameter-level confidence calculations across facilities,
learning-phase exit evaluation, and expansion readiness assessment.

Core responsibilities:
- get_parameter_confidence(): Cross-facility parameter confidence with median
- check_learning_phase_exit(): Conservative criteria for graduating from learning phase
- get_expansion_readiness(): Facility calibration maturity assessment

Philosophy alignment:
- P1_Honesty: Confidence is explicitly modeled and queryable, never assumed
- P2_CoGrowth: Graduation is earned through genuine calibration, not time-based
- P4_UserAgency: Learning phase exit never claims autonomous readiness

@ANCHOR: AI_CONFIDENCE_MODEL_SERVICE
"""

import json
import logging
import statistics
from datetime import timedelta
from typing import Dict, Optional

from aot.databases.models import (
    db,
    AIContextRecord,
    AIFeedbackEvent,
    AIFacilityLearning,
)
from aot.utils.time_utils import utc_now

logger = logging.getLogger(__name__)


class AIConfidenceModelService:
    """
    Service for parameter-level confidence modeling across facilities.
    Queries AIContextRecord and AIFeedbackEvent to compute:
    - Per-parameter confirmation counts and median values
    - Confidence levels (HIGH / MEDIUM / LOW) based on cross-facility evidence
    - Learning-phase exit eligibility
    - Expansion readiness staging.

    @phase active
    @stability unstable
    @dependency AIContextRecord, AIFeedbackEvent, AIFacilityLearning
    """

    # Confidence thresholds
    HIGH_CONFIRMATION_THRESHOLD = 10
    HIGH_FACILITY_THRESHOLD = 3
    MEDIUM_CONFIRMATION_THRESHOLD = 3

    # Learning phase exit criteria (conservative)
    EXIT_TOTAL_CONFIRMATIONS = 20
    EXIT_CATEGORY_COUNT = 3
    EXIT_CATEGORY_MIN_CONFIRMATIONS = 3
    EXIT_STALL_WINDOW_DAYS = 14

    @staticmethod
    def get_parameter_confidence(
        parameter_name: str,
        facility_id: Optional[str] = None,
    ) -> Dict:
        """
        Compute cross-facility confidence for a specific parameter.

        Queries AIContextRecord (user_confirmed state) and AIFeedbackEvent
        (confirmed events) to build a confidence profile.

        Args:
            parameter_name: The parameter to analyze
            facility_id: Optional filter for facility-specific counts

        Returns:
            Dict with global and facility-level confidence metrics
        """
        try:
            # Count global confirmed feedback events for this parameter
            global_events = AIFeedbackEvent.query.filter_by(
                event_type='confirmed',
                parameter_name=parameter_name,
            ).all()

            global_confirmations = len(global_events)

            # Count distinct facilities that have confirmed this parameter
            facility_ids = set()
            for event in global_events:
                if event.facility_id:
                    facility_ids.add(event.facility_id)
            global_facilities = len(facility_ids)

            # Compute global median value from confirmed context records
            confirmed_records = AIContextRecord.query.filter_by(
                parameter_name=parameter_name,
                context_state='user_confirmed',
            ).all()

            global_median_value = None
            if confirmed_records:
                numeric_values = []
                for record in confirmed_records:
                    try:
                        numeric_values.append(float(record.value))
                    except (ValueError, TypeError):
                        pass
                if numeric_values:
                    global_median_value = statistics.median(numeric_values)

            # Facility-specific confirmations (if requested)
            facility_confirmations = None
            if facility_id is not None:
                facility_confirmations = AIFeedbackEvent.query.filter_by(
                    event_type='confirmed',
                    parameter_name=parameter_name,
                    facility_id=facility_id,
                ).count()

            # Determine confidence level
            if (
                global_confirmations
                >= AIConfidenceModelService.HIGH_CONFIRMATION_THRESHOLD
                and global_facilities
                >= AIConfidenceModelService.HIGH_FACILITY_THRESHOLD
            ):
                confidence_level = "HIGH"
                confidence_reasoning = (
                    f"Parameter confirmed {global_confirmations} times "
                    f"across {global_facilities} facilities."
                )
            elif (
                global_confirmations
                >= AIConfidenceModelService.MEDIUM_CONFIRMATION_THRESHOLD
            ):
                confidence_level = "MEDIUM"
                confidence_reasoning = (
                    f"Parameter confirmed {global_confirmations} times "
                    f"but across only {global_facilities} facility(ies). "
                    f"More cross-facility validation needed for HIGH."
                )
            else:
                confidence_level = "LOW"
                confidence_reasoning = (
                    f"Only {global_confirmations} confirmation(s). "
                    f"Advice for this parameter is based on general baselines."
                )

            result = {
                "parameter_name": parameter_name,
                "global_confirmations": global_confirmations,
                "global_facilities": global_facilities,
                "global_median_value": global_median_value,
                "confidence_level": confidence_level,
                "confidence_reasoning": confidence_reasoning,
            }
            if facility_id is not None:
                result["facility_confirmations"] = facility_confirmations

            return result

        except Exception as e:
            logger.exception(
                f"Error computing confidence for parameter "
                f"{parameter_name}: {str(e)}"
            )
            return {
                "parameter_name": parameter_name,
                "confidence_level": "LOW",
                "confidence_reasoning": f"Error computing confidence: {str(e)}",
                "error": str(e),
            }

    @staticmethod
    def check_learning_phase_exit(facility_id: str) -> bool:
        """
        Evaluate whether a facility should exit the learning phase.

        Exit criteria (conservative):
        1. >= 20 total confirmations
        2. At least 3 categories have >= 3 confirmations each
        3. No stalled_since set within the last 14 days

        If criteria are met, sets learning_phase_active = False on the
        AIFacilityLearning record.

        Args:
            facility_id: Facility to evaluate

        Returns:
            True if facility has exited learning phase (criteria met),
            False otherwise
        """
        try:
            learning_record = AIFacilityLearning.query.filter_by(
                facility_id=facility_id
            ).first()

            if not learning_record:
                return False

            # Already graduated
            if not learning_record.learning_phase_active:
                return False

            # Criterion 1: Total confirmations
            total_confirmations = learning_record.feedback_count_total or 0
            if total_confirmations < AIConfidenceModelService.EXIT_TOTAL_CONFIRMATIONS:
                return False

            # Criterion 2: Category breadth
            try:
                confirmations = json.loads(
                    learning_record.confirmations_json or '{}'
                )
            except (json.JSONDecodeError, TypeError):
                confirmations = {}

            categories_with_enough = 0
            for category, counts in confirmations.items():
                if isinstance(counts, dict):
                    confirmed = counts.get('confirmed', 0)
                    if (
                        confirmed
                        >= AIConfidenceModelService.EXIT_CATEGORY_MIN_CONFIRMATIONS
                    ):
                        categories_with_enough += 1

            if (
                categories_with_enough
                < AIConfidenceModelService.EXIT_CATEGORY_COUNT
            ):
                return False

            # Criterion 3: No recent stall
            if learning_record.stalled_since is not None:
                stall_age = utc_now() - learning_record.stalled_since
                if stall_age < timedelta(
                    days=AIConfidenceModelService.EXIT_STALL_WINDOW_DAYS
                ):
                    return False

            # All criteria met — graduate
            learning_record.learning_phase_active = False
            db.session.commit()
            logger.info(
                f"Facility {facility_id} has exited learning phase."
            )
            return True

        except Exception as e:
            logger.exception(
                f"Error checking learning phase exit for "
                f"facility {facility_id}: {str(e)}"
            )
            db.session.rollback()
            return False

    @staticmethod
    def get_expansion_readiness(facility_id: str) -> Dict:
        """
        Assess facility calibration maturity and expansion readiness.

        Stages:
        - "learning": learning_phase_active is True, still accumulating feedback
        - "calibrating": learning phase exited but not all categories at HIGH
        - "calibrated": all tracked categories have HIGH confidence

        Args:
            facility_id: Facility to assess

        Returns:
            Dict with current_stage, expansion_blocked_reason, and
            confirmations_needed_for_next_stage
        """
        try:
            learning_record = AIFacilityLearning.query.filter_by(
                facility_id=facility_id
            ).first()

            if not learning_record:
                return {
                    "current_stage": "learning",
                    "expansion_blocked_reason": "No learning record exists for this facility.",
                    "confirmations_needed_for_next_stage": (
                        AIConfidenceModelService.EXIT_TOTAL_CONFIRMATIONS
                    ),
                }

            if learning_record.learning_phase_active:
                # Still in learning phase — compute how many more needed
                total = learning_record.feedback_count_total or 0
                needed = max(
                    0,
                    AIConfidenceModelService.EXIT_TOTAL_CONFIRMATIONS - total,
                )

                # Check category breadth gap
                try:
                    confirmations = json.loads(
                        learning_record.confirmations_json or '{}'
                    )
                except (json.JSONDecodeError, TypeError):
                    confirmations = {}

                categories_ok = 0
                for category, counts in confirmations.items():
                    if isinstance(counts, dict):
                        if (
                            counts.get('confirmed', 0)
                            >= AIConfidenceModelService.EXIT_CATEGORY_MIN_CONFIRMATIONS
                        ):
                            categories_ok += 1

                categories_gap = max(
                    0,
                    AIConfidenceModelService.EXIT_CATEGORY_COUNT
                    - categories_ok,
                )

                blocked_reason = None
                if needed > 0:
                    blocked_reason = (
                        f"Need {needed} more total confirmations."
                    )
                elif categories_gap > 0:
                    blocked_reason = (
                        f"Need confirmations in {categories_gap} more "
                        f"category(ies) (minimum "
                        f"{AIConfidenceModelService.EXIT_CATEGORY_MIN_CONFIRMATIONS} each)."
                    )
                elif learning_record.stalled_since is not None:
                    stall_age = utc_now() - learning_record.stalled_since
                    if stall_age < timedelta(
                        days=AIConfidenceModelService.EXIT_STALL_WINDOW_DAYS
                    ):
                        blocked_reason = (
                            "Learning was recently stalled. "
                            "Sustained engagement required before exit."
                        )

                return {
                    "current_stage": "learning",
                    "expansion_blocked_reason": blocked_reason,
                    "confirmations_needed_for_next_stage": needed,
                }

            # Learning phase exited — check if fully calibrated
            # A facility is "calibrated" when all tracked categories have
            # a confirmation ratio >= 0.7 (HIGH confidence).
            try:
                confirmations = json.loads(
                    learning_record.confirmations_json or '{}'
                )
            except (json.JSONDecodeError, TypeError):
                confirmations = {}

            all_high = True
            lowest_gap = 0
            for category, counts in confirmations.items():
                if isinstance(counts, dict):
                    confirmed = counts.get('confirmed', 0)
                    total = counts.get('total', 1)
                    ratio = confirmed / max(total, 1)
                    if ratio < 0.7:
                        all_high = False
                        # Estimate confirmations needed to reach 0.7
                        # ratio = confirmed / total => need confirmed/total >= 0.7
                        # So need confirmed >= 0.7 * total
                        needed_confirmed = int(0.7 * total) - confirmed + 1
                        lowest_gap = max(lowest_gap, needed_confirmed)

            if all_high and confirmations:
                return {
                    "current_stage": "calibrated",
                    "expansion_blocked_reason": None,
                    "confirmations_needed_for_next_stage": 0,
                }
            else:
                return {
                    "current_stage": "calibrating",
                    "expansion_blocked_reason": (
                        "Not all parameter categories have reached HIGH confidence."
                    ),
                    "confirmations_needed_for_next_stage": max(lowest_gap, 0),
                }

        except Exception as e:
            logger.exception(
                f"Error assessing expansion readiness for "
                f"facility {facility_id}: {str(e)}"
            )
            return {
                "current_stage": "learning",
                "expansion_blocked_reason": f"Error: {str(e)}",
                "confirmations_needed_for_next_stage": 0,
            }
