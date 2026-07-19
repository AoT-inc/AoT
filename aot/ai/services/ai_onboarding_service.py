# coding=utf-8
"""
AIOnboardingService - Phase 5 User Onboarding Flow

Implements the onboarding contract acknowledgment workflow per AoT_AI_PHILOSOPHY.yaml.
The onboarding contract is a formal mutual acknowledgment between the user and the system
that establishes shared expectations before AI-assisted operations begin.

Core responsibilities:
- start_onboarding(): Initiates onboarding for a facility/user pair
- acknowledge_contract(): Records contract acknowledgment and questionnaire data
- complete_onboarding(): Marks onboarding as finished
- get_onboarding_status(): Returns current onboarding state

Philosophy alignment:
- P5_Bounded_Expectations: Contract sets formal expectation about learning period
- P2_Co_Growth: Questionnaire initializes the learning record with user context
- P4_User_Agency: User must explicitly acknowledge contract; no passive acceptance
"""

import json
import logging
from datetime import datetime
from typing import Dict, Optional

from aot.databases.models import (
    db,
    AIOnboardingRecord,
    AIFacilityLearning,
    AIContextRecord,
)
from aot.ai.services.ai_facility_learning_service import AIFacilityLearningService
from aot.utils.time_utils import utc_now

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Onboarding Questionnaire Definition
# ---------------------------------------------------------------------------
ONBOARDING_QUESTIONNAIRE = {
    "questions": [
        {
            "id": "facility_type",
            "text": "What type of facility is this?",
            "options": ["greenhouse", "vertical_farm", "nursery", "other"],
            "required": True
        },
        {
            "id": "operator_experience",
            "text": "How long have you been managing this type of facility?",
            "options": ["less_than_1_year", "1_to_3_years", "3_to_10_years", "over_10_years"],
            "required": True
        },
        {
            "id": "critical_parameters",
            "text": "Which parameters matter most to your operation? (select all that apply)",
            "options": ["temperature", "humidity", "irrigation", "lighting", "co2", "nutrients", "pest_management"],
            "required": False,
            "multi_select": True
        }
    ],
    "contract_text": (
        "This AI advisor learns from your facility over time. During the initial learning period, "
        "advice is based on general agricultural knowledge and may not be specific to your conditions. "
        "Your feedback \u2014 confirming, adjusting, or rejecting suggestions \u2014 is what calibrates the "
        "system to your facility. The system will tell you when it is uncertain and what confirmation "
        "would help. You remain in control: no automated actions will be taken without your approval."
    )
}


class AIOnboardingService:
    """
    Service layer for the onboarding contract acknowledgment workflow.
    Manages the onboarding lifecycle:
      start -> acknowledge_contract -> complete_onboarding
    Each step is idempotent: calling start twice for the same facility/user
    returns the existing record rather than creating a duplicate.

    @phase active
    @stability stable
    @dependency AIOnboardingRecord, AIFacilityLearning, AIContextRecord
    """

    @staticmethod
    def start_onboarding(facility_id: str, user_id: int) -> Optional[AIOnboardingRecord]:
        """
        Initiate onboarding for a facility/user pair.

        Creates an AIOnboardingRecord with onboarding_started_at = now.
        Also ensures an AIFacilityLearning record exists for the facility.

        Args:
            facility_id: Target facility identifier
            user_id: Operator's user ID

        Returns:
            AIOnboardingRecord (new or existing)
        """
        try:
            # Check for existing onboarding record (idempotent)
            existing = AIOnboardingRecord.query.filter_by(
                facility_id=facility_id,
                user_id=user_id
            ).first()

            if existing:
                logger.info(
                    f"Onboarding already started for facility {facility_id}, user {user_id}"
                )
                return existing

            # Create new onboarding record
            record = AIOnboardingRecord(
                facility_id=facility_id,
                user_id=user_id,
                onboarding_started_at=utc_now()
            )
            db.session.add(record)

            # Ensure facility learning record exists
            AIFacilityLearningService.get_or_create_learning_record(facility_id)

            db.session.commit()
            logger.info(
                f"Onboarding started for facility {facility_id}, user {user_id}"
            )
            return record

        except Exception as e:
            db.session.rollback()
            logger.exception(
                f"Error starting onboarding for facility {facility_id}, user {user_id}: {str(e)}"
            )
            return None

    @staticmethod
    def acknowledge_contract(
        facility_id: str,
        user_id: int,
        questionnaire_responses: Dict
    ) -> Dict:
        """
        Record the user's contract acknowledgment and questionnaire data.

        Sets AIOnboardingRecord.contract_acknowledged_at = now.
        Stores questionnaire data in the appropriate fields.
        Creates initial AIContextRecord entries for critical parameters.
        Activates learning phase on AIFacilityLearning.

        Args:
            facility_id: Target facility identifier
            user_id: Operator's user ID
            questionnaire_responses: Dict with keys:
                - facility_type: str
                - operator_experience: str
                - critical_parameters: list of str (optional)

        Returns:
            Dict with status and next_steps guidance
        """
        try:
            record = AIOnboardingRecord.query.filter_by(
                facility_id=facility_id,
                user_id=user_id
            ).first()

            if not record:
                return {
                    "status": "error",
                    "message": "No onboarding record found. Call start_onboarding first."
                }

            if record.contract_acknowledged_at is not None:
                return {
                    "status": "already_acknowledged",
                    "message": "Contract was already acknowledged for this facility/user pair."
                }

            # Store questionnaire data
            facility_type = questionnaire_responses.get("facility_type")
            operator_experience = questionnaire_responses.get("operator_experience")
            critical_parameters = questionnaire_responses.get("critical_parameters", [])

            record.contract_acknowledged_at = utc_now()
            record.facility_type = facility_type
            record.operator_experience = operator_experience
            record.critical_parameters_json = json.dumps({
                "facility_type": facility_type,
                "critical_parameters": critical_parameters
            })

            # Create initial AIContextRecord entries for critical parameters
            for param in critical_parameters:
                ctx_record = AIContextRecord(
                    facility_id=facility_id,
                    parameter_name=param,
                    value=json.dumps({"status": "awaiting_first_reading"}),
                    source="onboarding_questionnaire",
                    context_state="pending",
                    created_by="onboarding"
                )
                db.session.add(ctx_record)

            # Activate learning phase on facility learning record
            learning_record = AIFacilityLearning.query.filter_by(
                facility_id=facility_id
            ).first()
            if learning_record:
                learning_record.learning_phase_active = True

            db.session.commit()

            logger.info(
                f"Contract acknowledged for facility {facility_id}, user {user_id}. "
                f"Type: {facility_type}, Experience: {operator_experience}, "
                f"Critical params: {critical_parameters}"
            )

            return {
                "status": "acknowledged",
                "next_steps": (
                    "Your onboarding preferences have been recorded. The AI system will now "
                    "begin learning from your facility data. During this initial period, "
                    "advice is based on general baselines. Your feedback on suggestions will "
                    "calibrate the system to your specific conditions over time."
                )
            }

        except Exception as e:
            db.session.rollback()
            logger.exception(
                f"Error acknowledging contract for facility {facility_id}, user {user_id}: {str(e)}"
            )
            return {"status": "error", "message": str(e)}

    @staticmethod
    def complete_onboarding(facility_id: str, user_id: int) -> Dict:
        """
        Mark onboarding as complete for this facility/user pair.

        Sets AIOnboardingRecord.onboarding_completed_at = now.
        Sets AIFacilityLearning.onboarding_complete = True.

        Note: Completion does NOT claim the system is calibrated.
        Learning continues and the system remains in learning_phase_active.

        Args:
            facility_id: Target facility identifier
            user_id: Operator's user ID

        Returns:
            Dict with completion status
        """
        try:
            record = AIOnboardingRecord.query.filter_by(
                facility_id=facility_id,
                user_id=user_id
            ).first()

            if not record:
                return {
                    "status": "error",
                    "message": "No onboarding record found."
                }

            if record.onboarding_completed_at is not None:
                return {
                    "status": "already_completed",
                    "message": "Onboarding was already completed."
                }

            record.onboarding_completed_at = utc_now()

            # Mark facility learning as onboarding-complete
            learning_record = AIFacilityLearning.query.filter_by(
                facility_id=facility_id
            ).first()
            if learning_record:
                learning_record.onboarding_complete = True

            db.session.commit()

            logger.info(
                f"Onboarding completed for facility {facility_id}, user {user_id}"
            )

            return {"status": "completed"}

        except Exception as e:
            db.session.rollback()
            logger.exception(
                f"Error completing onboarding for facility {facility_id}, user {user_id}: {str(e)}"
            )
            return {"status": "error", "message": str(e)}

    @staticmethod
    def get_onboarding_status(facility_id: str, user_id: int) -> Dict:
        """
        Return current onboarding state for a facility/user pair.

        Indicates:
        - Whether onboarding has been started
        - Whether the contract has been acknowledged
        - Whether onboarding is complete
        - Questionnaire data if available

        Args:
            facility_id: Target facility identifier
            user_id: Operator's user ID

        Returns:
            Dict describing the current onboarding state
        """
        try:
            record = AIOnboardingRecord.query.filter_by(
                facility_id=facility_id,
                user_id=user_id
            ).first()

            if not record:
                return {
                    "onboarding_started": False,
                    "contract_acknowledged": False,
                    "onboarding_complete": False,
                    "questionnaire": ONBOARDING_QUESTIONNAIRE
                }

            # Parse critical_parameters_json if present
            critical_params = None
            if record.critical_parameters_json:
                try:
                    critical_params = json.loads(record.critical_parameters_json)
                except (json.JSONDecodeError, TypeError):
                    critical_params = None

            return {
                "onboarding_started": True,
                "onboarding_started_at": record.onboarding_started_at.isoformat() if record.onboarding_started_at else None,
                "contract_acknowledged": record.contract_acknowledged_at is not None,
                "contract_acknowledged_at": record.contract_acknowledged_at.isoformat() if record.contract_acknowledged_at else None,
                "onboarding_complete": record.onboarding_completed_at is not None,
                "onboarding_completed_at": record.onboarding_completed_at.isoformat() if record.onboarding_completed_at else None,
                "facility_type": record.facility_type,
                "operator_experience": record.operator_experience,
                "critical_parameters": critical_params,
                "questionnaire": ONBOARDING_QUESTIONNAIRE
            }

        except Exception as e:
            logger.exception(
                f"Error getting onboarding status for facility {facility_id}, user {user_id}: {str(e)}"
            )
            return {
                "onboarding_started": False,
                "contract_acknowledged": False,
                "onboarding_complete": False,
                "error": str(e)
            }
