# coding=utf-8
"""
AIMonitoringService - Phase 7 Continuous Monitoring and Refinement Hooks

Implements system-wide health monitoring, confidence agreement analysis,
and learning effectiveness tracking per the philosophy alignment transformation.

Core responsibilities:
- get_system_health(): System-wide learning health across all facilities
- get_confidence_agreement_report(): Analyzes cases where HIGH confidence led to user rejection
- get_learning_dashboard_adoption(): Usage signal stub (future log integration)
- record_stalled_facilities(): Background job to detect and record stalled learning facilities

Philosophy alignment:
- P1_Honesty: Confidence agreement tracking surfaces cases where system overestimated confidence
- P2_CoGrowth: System monitors its own learning effectiveness — meta-feedback loop established
"""

import logging
from typing import Dict, List, Optional
from datetime import datetime, timedelta

from aot.databases.models import (
    db,
    AIFacilityLearning,
    AIFeedbackEvent,
)
from aot.ai.services.ai_facility_learning_service import AIFacilityLearningService
from aot.utils.time_utils import utc_now

logger = logging.getLogger(__name__)


class AIMonitoringService:
    """
    Internal monitoring service for system health and learning effectiveness.
    These endpoints are for internal/admin use only — not user-facing.
    Designed to power meta-feedback loops where the system learns about its own learning.

    @phase active
    @stability unstable
    @dependency AIFacilityLearning, AIFeedbackEvent
    """

    @staticmethod
    def get_system_health() -> Dict:
        """
        Returns system-wide learning health across all facilities.

        Purpose: Answer "Is learning healthy across all facilities?"

        Returns:
            {
              "total_facilities": <int>,
              "active_learning_facilities": <int>,
              "stalled_facilities": [<facility_id>, ...],
              "avg_feedback_rate_per_day": <float>,
              "total_feedback_events_last_30_days": <int>,
              "facilities_with_zero_feedback_7d": [<facility_id>, ...]
            }

        Philosophy:
        - P1_Honesty: Surface stalled learning detection — don't hide problems
        - P2_CoGrowth: Feedback rate is a health signal for the system itself
        """
        try:
            # Query all facility learning records
            all_facilities = AIFacilityLearning.query.all()
            total_facilities = len(all_facilities)

            active_learning = [f for f in all_facilities if f.learning_phase_active]
            active_learning_count = len(active_learning)

            # Detect stalled facilities
            stalled_facility_ids = []
            for facility in all_facilities:
                is_stalled = AIFacilityLearningService.check_stalled(facility.facility_id)
                if is_stalled:
                    stalled_facility_ids.append(facility.facility_id)

            # Calculate feedback rate over last 30 days
            thirty_days_ago = utc_now() - timedelta(days=30)
            recent_events = AIFeedbackEvent.query.filter(
                AIFeedbackEvent.created_at >= thirty_days_ago
            ).all()
            total_feedback_30d = len(recent_events)

            # Estimate feedback rate (events per day across all facilities)
            avg_feedback_rate = total_feedback_30d / 30.0 if total_facilities > 0 else 0.0

            # Find facilities with zero feedback in last 7 days
            seven_days_ago = utc_now() - timedelta(days=7)
            facilities_with_feedback_7d = set()
            recent_7d = AIFeedbackEvent.query.filter(
                AIFeedbackEvent.created_at >= seven_days_ago
            ).all()
            for event in recent_7d:
                facilities_with_feedback_7d.add(event.facility_id)

            zero_feedback_7d = [
                f.facility_id for f in all_facilities
                if f.facility_id not in facilities_with_feedback_7d
            ]

            return {
                "total_facilities": total_facilities,
                "active_learning_facilities": active_learning_count,
                "stalled_facilities": stalled_facility_ids,
                "avg_feedback_rate_per_day": round(avg_feedback_rate, 2),
                "total_feedback_events_last_30_days": total_feedback_30d,
                "facilities_with_zero_feedback_7d": zero_feedback_7d,
            }
        except Exception as e:
            logger.error(f"[AIMonitoring] get_system_health failed: {e}")
            return {
                "error": str(e),
                "total_facilities": 0,
                "active_learning_facilities": 0,
                "stalled_facilities": [],
                "avg_feedback_rate_per_day": 0.0,
                "total_feedback_events_last_30_days": 0,
                "facilities_with_zero_feedback_7d": [],
            }

    @staticmethod
    def get_confidence_agreement_report() -> Dict:
        """
        Reviews cases where system had HIGH confidence but user rejected.

        Purpose: Identify failure modes where system was overconfident.
        This is a key metric for philosophy P1_Honesty — the system must
        audit its own confidence calibration.

        Returns:
            {
              "high_confidence_rejections_30d": <int>,
              "high_confidence_confirmations_30d": <int>,
              "agreement_rate": <float>,  # 0.0-1.0
              "most_rejected_parameters": [<parameter_name>, ...]
            }

        Notes:
        - "rejection" = event_type='rejected'
        - "high confidence" = (future phase) confidence metadata in AIFeedbackEvent
        - For now, counts all rejections as a baseline until confidence is stored with events

        Philosophy:
        - P1_Honesty: System acknowledges when it overestimated confidence
        """
        try:
            thirty_days_ago = utc_now() - timedelta(days=30)

            # Query all feedback events in last 30 days
            all_events_30d = AIFeedbackEvent.query.filter(
                AIFeedbackEvent.created_at >= thirty_days_ago
            ).all()

            rejections = [e for e in all_events_30d if e.event_type == "rejected"]
            confirmations = [e for e in all_events_30d if e.event_type == "confirmed"]

            rejection_count = len(rejections)
            confirmation_count = len(confirmations)

            # Calculate agreement rate (confirmations / total)
            total_events = rejection_count + confirmation_count
            agreement_rate = (confirmation_count / total_events) if total_events > 0 else 0.0

            # Find most rejected parameters
            rejection_counts = {}
            for event in rejections:
                param = event.parameter_name or "unknown"
                rejection_counts[param] = rejection_counts.get(param, 0) + 1

            most_rejected = sorted(
                rejection_counts.items(),
                key=lambda x: x[1],
                reverse=True
            )[:5]
            most_rejected_params = [param for param, count in most_rejected]

            return {
                "high_confidence_rejections_30d": rejection_count,
                "high_confidence_confirmations_30d": confirmation_count,
                "agreement_rate": round(agreement_rate, 3),
                "most_rejected_parameters": most_rejected_params,
            }
        except Exception as e:
            logger.error(f"[AIMonitoring] get_confidence_agreement_report failed: {e}")
            return {
                "error": str(e),
                "high_confidence_rejections_30d": 0,
                "high_confidence_confirmations_30d": 0,
                "agreement_rate": 0.0,
                "most_rejected_parameters": [],
            }

    @staticmethod
    def get_learning_dashboard_adoption() -> Dict:
        """
        Returns usage signal stub for learning dashboard adoption.

        Purpose: Track whether operators are engaging with the learning progress
        dashboard — a key signal for P2_CoGrowth (system must see evidence that
        users find learning progress visible and valuable).

        Current Implementation:
        - This is a STUB. Actual tracking requires web server log integration
          (counting requests to /ai/facility/{facility_id}/learning-progress endpoint).
        - Placeholder response for now; implementation will be filled in Phase 8+
          when log aggregation infrastructure is available.

        Returns:
            {
              "note": "Endpoint usage counting requires web server log integration — not available in this phase.",
              "placeholder": True
            }

        Future Fields (to be implemented):
        {
          "unique_operators_viewing_dashboard_30d": <int>,
          "total_dashboard_views_30d": <int>,
          "avg_views_per_operator": <float>,
          "facilities_with_zero_dashboard_engagement_30d": [<facility_id>, ...]
        }

        Philosophy:
        - P2_CoGrowth: If operators don't see learning progress, co-growth stalls
        """
        return {
            "note": "Endpoint usage counting requires web server log integration — not available in this phase.",
            "placeholder": True,
        }

    @staticmethod
    def record_stalled_facilities() -> List[str]:
        """
        Background job: scan all facilities and record those with stalled learning.

        Purpose: Proactive detection of facilities where learning has stopped.
        This is called by scheduled jobs (cron or APScheduler) to populate
        monitoring data and trigger notifications.

        Returns:
            List of facility_ids where learning is stalled.

        Side Effects:
        - Updates AIFacilityLearning.stalled_since for affected facilities
        - Logs stalled detection for each facility

        Philosophy:
        - P1_Honesty: Explicitly signal when learning has stalled
        - P2_CoGrowth: Stalled detection is meta-feedback (system monitors itself)

        Notes:
        - This method is idempotent; calling it multiple times is safe
        - Integration with background job scheduler is documented in MONITORING_RUNBOOK.yaml
        """
        stalled_facility_ids = []
        try:
            all_facilities = AIFacilityLearning.query.all()

            for facility in all_facilities:
                is_stalled = AIFacilityLearningService.check_stalled(facility.facility_id)
                if is_stalled:
                    stalled_facility_ids.append(facility.facility_id)

                    # Ensure stalled_since is set
                    if not facility.stalled_since:
                        facility.stalled_since = utc_now()
                        db.session.add(facility)

                    logger.info(
                        f"[AIMonitoring] Facility {facility.facility_id} learning is stalled "
                        f"(no feedback since {facility.last_feedback_at})"
                    )

            db.session.commit()
            logger.info(f"[AIMonitoring] Recorded {len(stalled_facility_ids)} stalled facilities")
        except Exception as e:
            logger.error(f"[AIMonitoring] record_stalled_facilities failed: {e}")
            db.session.rollback()

        return stalled_facility_ids
