# coding=utf-8
# @ANCHOR: AI_CALLER_INTERFACE
"""
AICallerInterface — Abstract Base Class for AI call delegation.

Decouples orchestration services (AIAnomalyDetector, AIErrorCorrectionService,
AISummaryService) from direct AIAgentService coupling.

Ref: SBS-002_V2_STRATEGY (IMP-003/007/011), 009_TASK_3_PLAN_STEP_2_INTERFACE
"""
from abc import ABC, abstractmethod
from typing import Any, Dict


class AICallerInterface(ABC):
    """
    Abstract interface for executing AI reasoning calls.
    Concrete implementation: AIAgentService (injected at application startup).
    Services must depend on this interface, not on AIAgentService directly.

    @phase active
    @stability stable
    @dependency AIAgentService
    """

    @abstractmethod
    def call(self, agent_id: str, goal: str, context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute a single AI reasoning call.

        Args:
            agent_id: Unique identifier of the AI agent to invoke.
            goal:     The goal / prompt string passed to the AI engine.
            context:  Contextual data dictionary passed to engine.run_reasoning().

        Returns:
            Standard result dict, e.g. {'insight': str, ...}
        """
        ...
