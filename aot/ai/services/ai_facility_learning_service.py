# coding=utf-8
"""
AIFacilityLearningService - Phase 4 Learning Progress Tracking

Implements facility-level learning progress tracking, feedback event recording,
and stalled-learning detection per the philosophy alignment transformation.

Core responsibilities:
- record_feedback(): Creates FeedbackEvent and updates AIFacilityLearning state
- get_learning_progress(): Returns dashboard-ready learning summary
- check_stalled(): Detects if learning has stalled (no feedback >N days)
- get_or_create_learning_record(): Idempotent facility learning initialization

Philosophy alignment:
- P1_Honesty: Explicit stalled detection signals when learning has halted
- P2_CoGrowth: System tracks and surfaces feedback impact per facility
- P4_UserAgency: All feedback types (confirmed, rejected, dismissed) are tracked equally
"""

import json
import logging
from datetime import datetime, timedelta
from typing import Dict, Optional, List

from aot.databases.models import (
    db,
    AIFacilityLearning,
    AIFeedbackEvent,
    AIContextRecord,
)
from aot.utils.time_utils import utc_now

logger = logging.getLogger(__name__)


class AIFacilityLearningService:
    """
    Service layer for facility-level AI learning progress tracking.
    Manages the learning state machine: system_generated → pending → user_confirmed.
    Tracks feedback events as the append-only audit trail of facility calibration.

    @phase active
    @stability unstable
    @dependency AIFacilityLearning, AIFeedbackEvent, AIContextRecord
    """

    @staticmethod
    def record_feedback(
        facility_id: str,
        user_id: int,
        event_type: str,
        parameter_name: str,
        previous_value: Optional[str] = None,
        new_value: Optional[str] = None,
        reasoning: Optional[str] = None,
        context_record_id: Optional[str] = None,
    ) -> Dict:
        """
        Record user feedback event and update learning progress.

        Args:
            facility_id: Facility being calibrated
            user_id: User providing feedback
            event_type: 'confirmed', 'rejected', or 'dismissed'
            parameter_name: Which parameter was affected
            previous_value: Old value (if applicable)
            new_value: New value (if applicable)
            reasoning: Optional user-supplied explanation
            context_record_id: Links to AIContextRecord if updating context

        Returns:
            Dict with status and result metadata

        Side Effects:
            - Creates AIFeedbackEvent (append-only)
            - Increments AIFacilityLearning.feedback_count_total
            - Updates AIFacilityLearning.last_feedback_at
            - If context_record_id provided: updates AIContextRecord state
            - Clears stalled_since if feedback resumes
        """
        try:
            # Create feedback event (append-only)
            feedback_event = AIFeedbackEvent(
                facility_id=facility_id,
                user_id=user_id,
                event_type=event_type,
                parameter_name=parameter_name,
                previous_value=previous_value,
                new_value=new_value,
                reasoning=reasoning,
                context_record_id=context_record_id,
            )
            db.session.add(feedback_event)

            # Get or create learning record for this facility
            learning_record = (
                AIFacilityLearning.query.filter_by(facility_id=facility_id).first()
            )
            if not learning_record:
                learning_record = AIFacilityLearning(facility_id=facility_id)
                db.session.add(learning_record)
                db.session.flush()

            # Update learning progress
            learning_record.feedback_count_total = (
                learning_record.feedback_count_total + 1
            )
            learning_record.last_feedback_at = utc_now()

            # Clear stalled flag if learning resumes
            if learning_record.stalled_since is not None:
                learning_record.stalled_since = None

            # Update per-parameter confirmation counts (stored as JSON)
            try:
                confirmations_json = json.loads(
                    learning_record.confirmations_json or "{}"
                )
            except json.JSONDecodeError:
                confirmations_json = {}

            # Extract category from parameter_name (convention: "category_param" or "category.param")
            category = parameter_name.split("_")[0] if "_" in parameter_name else parameter_name.split(".")[0] if "." in parameter_name else "general"

            if category not in confirmations_json:
                confirmations_json[category] = {"confirmed": 0, "total": 0}

            # For 'confirmed' events, increment both confirmed and total
            if event_type == "confirmed":
                confirmations_json[category]["confirmed"] += 1
                confirmations_json[category]["total"] += 1
            else:
                # For rejected/dismissed, increment total only
                confirmations_json[category]["total"] += 1

            learning_record.confirmations_json = json.dumps(confirmations_json)

            # If context_record_id provided, update context record state
            if context_record_id:
                context_record = AIContextRecord.query.filter_by(
                    unique_id=context_record_id
                ).first()
                if context_record:
                    if event_type == "confirmed":
                        # User confirmed this context value
                        context_record.context_state = "user_confirmed"
                        context_record.confirmed_by = user_id
                        context_record.confirmed_at = utc_now()
                    elif event_type == "rejected":
                        # User rejected this context value, revert to pending
                        context_record.context_state = "pending"
                    # dismissed events don't change context state

            db.session.commit()

            # Phase 6: Check if facility should exit learning phase.
            # Uses AIConfidenceModelService conservative criteria.
            try:
                from aot.ai.services.ai_confidence_model_service import (
                    AIConfidenceModelService,
                )
                if AIConfidenceModelService.check_learning_phase_exit(
                    facility_id
                ):
                    logger.info(
                        f"Facility {facility_id} has exited learning phase."
                    )
            except Exception as _exit_exc:
                logger.debug(
                    "[record_feedback] learning phase exit check failed: %s",
                    _exit_exc,
                )

            return {
                "status": "success",
                "feedback_event_id": feedback_event.unique_id,
                "facility_id": facility_id,
                "event_type": event_type,
                "parameter": parameter_name,
                "new_total_feedback_count": learning_record.feedback_count_total,
            }

        except Exception as e:
            logger.exception(
                f"Error recording feedback for facility {facility_id}: {str(e)}"
            )
            db.session.rollback()
            return {"status": "error", "error": str(e)}

    @staticmethod
    def get_learning_progress(facility_id: str) -> Dict:
        """
        Get facility-level learning progress summary for dashboard display.

        Returns structure compatible with learning-progress frontend component:
        {
            "facility_id": <id>,
            "learning_phase_active": <bool>,
            "days_since_onboarding": <int>,
            "feedback_count_total": <int>,
            "confirmations_by_category": {
                "<category>": {"confirmed": <int>, "total": <int>}
            },
            "stalled": <bool>,
            "stalled_since_days": <int or None>,
            "last_feedback_at": <ISO timestamp or None>,
            "next_most_valuable_feedback": "<parameter name or None>"
        }
        """
        try:
            learning_record = AIFacilityLearning.query.filter_by(
                facility_id=facility_id
            ).first()

            if not learning_record:
                # Return default state for uninitialized facility
                return {
                    "facility_id": facility_id,
                    "learning_phase_active": True,
                    "days_since_onboarding": 0,
                    "feedback_count_total": 0,
                    "confirmations_by_category": {},
                    "stalled": False,
                    "stalled_since_days": None,
                    "last_feedback_at": None,
                    "next_most_valuable_feedback": None,
                }

            # Parse confirmations JSON
            try:
                confirmations_by_category = json.loads(
                    learning_record.confirmations_json or "{}"
                )
            except json.JSONDecodeError:
                confirmations_by_category = {}

            # Calculate days since onboarding
            days_since_onboarding = (
                utc_now() - learning_record.learning_started_at
            ).days

            # Calculate stalled status
            stalled = False
            stalled_since_days = None
            if learning_record.stalled_since is not None:
                stalled = True
                stalled_since_days = (
                    utc_now() - learning_record.stalled_since
                ).days

            # Determine next most valuable feedback (lowest confirmed/total ratio)
            next_most_valuable_feedback = None
            if confirmations_by_category:
                min_ratio = 1.0
                for category, counts in confirmations_by_category.items():
                    if counts.get("total", 0) > 0:
                        ratio = counts.get("confirmed", 0) / counts["total"]
                        if ratio < min_ratio:
                            min_ratio = ratio
                            # Use category as proxy; ideally would track specific parameter names
                            next_most_valuable_feedback = f"{category}_parameter"

            return {
                "facility_id": facility_id,
                "learning_phase_active": learning_record.learning_phase_active,
                "days_since_onboarding": days_since_onboarding,
                "feedback_count_total": learning_record.feedback_count_total,
                "confirmations_by_category": confirmations_by_category,
                "stalled": stalled,
                "stalled_since_days": stalled_since_days,
                "last_feedback_at": (
                    learning_record.last_feedback_at.isoformat()
                    if learning_record.last_feedback_at
                    else None
                ),
                "next_most_valuable_feedback": next_most_valuable_feedback,
            }

        except Exception as e:
            logger.exception(
                f"Error retrieving learning progress for facility {facility_id}: {str(e)}"
            )
            return {
                "facility_id": facility_id,
                "error": str(e),
            }

    @staticmethod
    def check_stalled(facility_id: str, threshold_days: int = 7) -> bool:
        """
        Check if facility learning has stalled (no feedback for >threshold_days).

        Updates AIFacilityLearning.stalled_since if not already set.

        Args:
            facility_id: Facility to check
            threshold_days: Days without feedback to trigger stalled status

        Returns:
            True if learning is stalled, False otherwise
        """
        try:
            learning_record = AIFacilityLearning.query.filter_by(
                facility_id=facility_id
            ).first()

            if not learning_record or not learning_record.last_feedback_at:
                # No feedback received yet; not stalled, just not started
                return False

            days_since_feedback = (
                utc_now() - learning_record.last_feedback_at
            ).days

            if days_since_feedback > threshold_days:
                # Learning is stalled
                if learning_record.stalled_since is None:
                    # First time detecting stall; record it
                    learning_record.stalled_since = utc_now()
                    db.session.commit()
                return True

            return False

        except Exception as e:
            logger.exception(
                f"Error checking stalled status for facility {facility_id}: {str(e)}"
            )
            return False

    @staticmethod
    def get_or_create_learning_record(facility_id: str) -> Optional[AIFacilityLearning]:
        """
        Idempotent: get existing learning record or create new one.

        Args:
            facility_id: Facility to initialize

        Returns:
            AIFacilityLearning record (new or existing)
        """
        try:
            learning_record = AIFacilityLearning.query.filter_by(
                facility_id=facility_id
            ).first()

            if not learning_record:
                learning_record = AIFacilityLearning(facility_id=facility_id)
                db.session.add(learning_record)
                db.session.commit()
                logger.info(
                    f"Created new learning record for facility {facility_id}"
                )

            return learning_record

        except Exception as e:
            logger.exception(
                f"Error creating learning record for facility {facility_id}: {str(e)}"
            )
            db.session.rollback()
            return None
