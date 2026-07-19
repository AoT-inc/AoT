# coding=utf-8
"""
reasoning_trace_builder.py -- AoT AI Reasoning Trace Builder

Builds a structured reasoning trace that accompanies every AI-generated action,
making each recommendation traceable to its data sources and expressing calibrated
confidence derived from facility learning state.

Authority : AGENT_CONSTITUTION law_8_philosophy_alignment
Philosophy: AoT_AI_PHILOSOPHY.yaml — P1_Honesty, P3_Transparency

Call Hierarchy
--------------
Parent  : AIDispatchService._dispatch_actions() — attaches trace to action dict
Children: (none — pure builder, no side effects)

@ANCHOR: REASONING_TRACE_BUILDER
"""

import logging

logger = logging.getLogger(__name__)


class ReasoningTraceBuilder:
    """
    Builds a reasoning trace dict for an AI-generated action.

    The trace makes explicit:
    - What data sources informed the action (based_on)
    - Overall confidence level (HIGH / MEDIUM / LOW)
    - Why confidence is at that level (confidence_reasoning)
    - What would improve confidence (confidence_would_increase_if)
    - Advisory framing reminder

    All inputs are optional-safe: missing context_metadata or
    facility_learning_state will degrade gracefully to LOW confidence
    with an appropriate explanation.

    @phase active
    @stability stable
    @dependency ContextMetadataBuilder, AIFacilityLearning
    """

    @staticmethod
    def build(action_dict, context_metadata, facility_learning_state):
        """
        Build a reasoning trace for a single action.

        Args:
            action_dict: The action dict produced by the AI engine.
                         Used to identify which parameters are relevant.
            context_metadata: The enriched context metadata dict from Phase 2
                              (ContextMetadataBuilder output). May be None.
            facility_learning_state: Dict with facility learning info:
                - learning_phase_active (bool)
                - feedback_count_total (int)
                - confirmations_json (dict: domain -> {confirmed: N, total: M})
                May be None.

        Returns:
            dict: Reasoning trace with keys:
                - based_on: list of source dicts
                - confidence_overall: HIGH | MEDIUM | LOW
                - confidence_reasoning: str
                - confidence_would_increase_if: str
                - framing: "advisory"

            Returns a valid LOW-confidence trace if inputs are missing.
        """
        try:
            based_on = ReasoningTraceBuilder._extract_sources(context_metadata)
            confidence_overall, confidence_reasoning, would_increase_if = (
                ReasoningTraceBuilder._derive_confidence(
                    based_on, facility_learning_state
                )
            )

            return {
                "based_on": based_on,
                "confidence_overall": confidence_overall,
                "confidence_reasoning": confidence_reasoning,
                "confidence_would_increase_if": would_increase_if,
                "framing": "advisory",
            }
        except Exception as exc:
            logger.warning(
                "[ReasoningTraceBuilder] Failed to build trace: %s", exc
            )
            return ReasoningTraceBuilder._fallback_trace(str(exc))

    @staticmethod
    def _extract_sources(context_metadata):
        """
        Extract based_on source list from Phase 2 context_metadata.

        Each entry in based_on:
        {
            "source": "<source_id>",
            "value": <value>,
            "state": "system_generated" | "user_confirmed",
            "confidence": "HIGH" | "MEDIUM" | "LOW"
        }
        """
        sources = []
        if not context_metadata:
            return sources

        # context_metadata follows ContextMetadataBuilder output schema:
        # { "per_parameter": { "<param>": { value, source, state, confidence, ... } }, ... }
        per_parameter = context_metadata.get("per_parameter")
        if not per_parameter or not isinstance(per_parameter, dict):
            return sources

        for param_name, meta in per_parameter.items():
            if not isinstance(meta, dict):
                continue
            sources.append({
                "source": meta.get("source", param_name),
                "value": meta.get("value"),
                "state": meta.get("state", "system_generated"),
                "confidence": meta.get("confidence", "LOW"),
            })

        return sources

    @staticmethod
    def _derive_confidence(based_on, facility_learning_state):
        """
        Derive overall confidence from source states and facility learning state.

        Rules:
        - If majority of based_on sources are "user_confirmed" -> HIGH
        - If mixed confirmed/unconfirmed or facility in learning_phase_active -> MEDIUM
        - If all sources are "system_generated" or facility has < 5 total confirmations -> LOW

        Returns:
            tuple: (confidence_overall, confidence_reasoning, would_increase_if)
        """
        # Handle missing facility learning state
        learning_active = True
        total_confirmations = 0
        if facility_learning_state and isinstance(facility_learning_state, dict):
            learning_active = facility_learning_state.get(
                "learning_phase_active", True
            )
            total_confirmations = facility_learning_state.get(
                "feedback_count_total", 0
            )

        # Count source states
        total_sources = len(based_on)
        confirmed_count = sum(
            1 for s in based_on if s.get("state") == "user_confirmed"
        )
        system_count = total_sources - confirmed_count

        # Rule: facility has < 5 total confirmations -> LOW
        if total_confirmations < 5:
            return (
                "LOW",
                "Facility has fewer than 5 total confirmations; "
                "recommendations are based on general domain baselines.",
                "Confirming key facility parameters (temperature setpoints, "
                "humidity thresholds, ventilation preferences) would help most.",
            )

        # Rule: all sources are system_generated -> LOW
        if total_sources > 0 and confirmed_count == 0:
            return (
                "LOW",
                "All data sources are system-generated defaults; "
                "no user-confirmed values are available for this context.",
                "Reviewing and confirming any of the current parameter values "
                "would immediately improve recommendation confidence.",
            )

        # Rule: mixed or learning_phase_active -> MEDIUM
        if learning_active or (confirmed_count > 0 and system_count > 0):
            unconfirmed_sources = [
                s.get("source", "unknown")
                for s in based_on
                if s.get("state") != "user_confirmed"
            ]
            hint = (
                f"Confirming values for: {', '.join(unconfirmed_sources[:3])}"
                if unconfirmed_sources
                else "Completing the facility learning phase"
            )
            return (
                "MEDIUM",
                "Some data sources are confirmed but the facility is still "
                "in the learning phase or has unconfirmed parameters.",
                hint + " would increase confidence.",
            )

        # Rule: majority confirmed -> HIGH
        if total_sources > 0 and confirmed_count > total_sources / 2:
            return (
                "HIGH",
                "Majority of data sources are user-confirmed and the facility "
                "learning phase is complete.",
                "Keeping parameter confirmations up to date as conditions change.",
            )

        # Default fallback
        return (
            "MEDIUM",
            "Confidence level could not be precisely determined from "
            "available data sources.",
            "Providing additional parameter confirmations would help.",
        )

    @staticmethod
    def _fallback_trace(error_msg=""):
        """
        Return a valid LOW-confidence trace when building fails.
        Ensures backward compatibility — consumers always get a valid dict.
        """
        return {
            "based_on": [],
            "confidence_overall": "LOW",
            "confidence_reasoning": (
                "Reasoning trace could not be fully constructed. "
                "Recommendations are based on general baselines."
            ),
            "confidence_would_increase_if": (
                "Providing facility-specific parameter confirmations "
                "would help improve future recommendations."
            ),
            "framing": "advisory",
        }
