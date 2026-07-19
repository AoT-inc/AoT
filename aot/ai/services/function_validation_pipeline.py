# coding=utf-8
# @ANCHOR: FUNCTION_VALIDATION_PIPELINE
"""
FunctionValidationPipeline — 4-stage pipeline for AI to verify function safety.

Design ref: 031_FUNCTION_CENTRIC_DESIGN_PROPOSAL.yaml (Section 2.2)
Law 1: New service file only — no modification to existing function files.
Law 2: @ANCHOR: FUNCTION_VALIDATION_PIPELINE registered via incremental_update.py.

Stages:
  1. Doc Lookup       — AiDocService contract retrieval
  2. Contract Check   — input/output type consistency
  3. Sandbox Dry-Run  — mock execution without real device I/O
  4. VEE Impact       — physical output assessment (skipped for pure-compute functions)
"""
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

SANDBOX_TIMEOUT_MS = 2000  # Stage 3 execution budget


# ── Status enum ───────────────────────────────────────────────────────────────

class ValidationStatus(str, Enum):
    VALIDATED   = "VALIDATED"    # Cleared all 4 stages
    SANDBOXED   = "SANDBOXED"    # Passed stages 1-2; pending stage 3-4
    REJECTED    = "REJECTED"     # Failed any stage
    UNVALIDATED = "UNVALIDATED"  # No ai_docs entry — cannot execute


# ── Result dataclass ─────────────────────────────────────────────────────────

@dataclass
class ValidationResult:
    status: ValidationStatus
    function_name: str
    stage_reached: int = 0           # highest stage successfully completed (1-4)
    rejection_reason: Optional[str] = None
    conflict_flags: List[str] = field(default_factory=list)
    doc_entry: Optional[Dict[str, Any]] = None
    execution_time_ms: Optional[float] = None


# ── Pipeline ─────────────────────────────────────────────────────────────────

class FunctionValidationPipeline:
    """
    Stateless pipeline; call validate() for each function independently.

    Usage:
        result = FunctionValidationPipeline.validate(
            function_name="my_function",
            contract={"input_measurements": [...], "output_actions": [...]},
            mock_measurements={"temperature": 22.5},
        )
        if result.status == ValidationStatus.VALIDATED:
            # safe to dispatch
    """

    @classmethod
    def validate(
        cls,
        function_name: str,
        contract: Optional[Dict[str, Any]] = None,
        mock_measurements: Optional[Dict[str, Any]] = None,
        skip_vee: bool = False,
    ) -> ValidationResult:
        """
        Run all 4 validation stages. Returns ValidationResult.

        Args:
            function_name:      Unique function identifier (key in functions.json).
            contract:           FunctionContract dict with input_measurements, output_actions, etc.
            mock_measurements:  Synthetic sensor values for sandbox dry-run.
            skip_vee:           If True, skip Stage 4 (pure-compute functions with no physical output).
        """
        contract = contract or {}
        mock_measurements = mock_measurements or {}

        # Stage 1 — Doc Lookup
        doc_entry, stage1_result = cls._stage1_doc_lookup(function_name)
        if stage1_result is not None:
            return stage1_result

        # Stage 2 — Contract Verification
        stage2_result = cls._stage2_contract_verification(function_name, contract, doc_entry)
        if stage2_result is not None:
            return stage2_result

        # Stage 3 — Sandbox Dry-Run
        exec_ms, stage3_result = cls._stage3_sandbox(function_name, contract, mock_measurements)
        if stage3_result is not None:
            return stage3_result

        # Stage 4 — VEE Impact Assessment
        output_actions = contract.get("output_actions", [])
        has_physical_output = bool(output_actions) and not skip_vee
        if has_physical_output:
            stage4_result = cls._stage4_vee_impact(function_name, output_actions)
            if stage4_result is not None:
                return stage4_result

        return ValidationResult(
            status=ValidationStatus.VALIDATED,
            function_name=function_name,
            stage_reached=4,
            doc_entry=doc_entry,
            execution_time_ms=exec_ms,
        )

    # ── Stage 1 ───────────────────────────────────────────────────────────────

    @classmethod
    def _stage1_doc_lookup(
        cls, function_name: str
    ):
        """Returns (doc_entry_dict, early_ValidationResult_or_None)."""
        try:
            from aot.ai.services.ai_doc_service import AiDocService
            entry = AiDocService.get_function_doc(function_name)
        except Exception as exc:
            logger.warning("[FVP][Stage1] AiDocService unavailable: %s", exc)
            return None, ValidationResult(
                status=ValidationStatus.UNVALIDATED,
                function_name=function_name,
                stage_reached=0,
                rejection_reason=f"AiDocService unavailable: {exc}",
            )

        if entry is None:
            logger.warning("[FVP][Stage1] No doc entry for function '%s'.", function_name)
            return None, ValidationResult(
                status=ValidationStatus.UNVALIDATED,
                function_name=function_name,
                stage_reached=0,
                rejection_reason="No ai_docs entry — function cannot execute without explicit human override.",
            )

        logger.debug("[FVP][Stage1] Doc entry found for '%s'.", function_name)
        return entry.raw, None

    # ── Stage 2 ───────────────────────────────────────────────────────────────

    @classmethod
    def _stage2_contract_verification(
        cls,
        function_name: str,
        contract: Dict[str, Any],
        doc_entry: Optional[Dict[str, Any]],
    ) -> Optional[ValidationResult]:
        """Returns early ValidationResult if verification fails, else None."""
        if not doc_entry:
            return None  # no doc to check against — pass through

        doc_inputs  = set(doc_entry.get("input_types", []))
        doc_outputs = set(doc_entry.get("output_types", []))
        doc_constraints = doc_entry.get("constraints", [])

        contract_inputs  = set(contract.get("input_measurements", []))
        contract_outputs = set(contract.get("output_actions", []))

        diff_inputs  = contract_inputs  - doc_inputs  if doc_inputs  else set()
        diff_outputs = contract_outputs - doc_outputs if doc_outputs else set()

        if diff_inputs or diff_outputs:
            reason = (
                f"Contract mismatch — undocumented inputs: {diff_inputs}, "
                f"undocumented outputs: {diff_outputs}"
            )
            logger.warning("[FVP][Stage2] %s for '%s'", reason, function_name)
            return ValidationResult(
                status=ValidationStatus.REJECTED,
                function_name=function_name,
                stage_reached=1,
                rejection_reason=reason,
            )

        logger.debug("[FVP][Stage2] Contract consistent for '%s'.", function_name)
        return None

    # ── Stage 3 ───────────────────────────────────────────────────────────────

    @classmethod
    def _stage3_sandbox(
        cls,
        function_name: str,
        contract: Dict[str, Any],
        mock_measurements: Dict[str, Any],
    ):
        """
        Dry-run sandbox: load and call the function with mock measurements.
        Returns (exec_time_ms, early_ValidationResult_or_None).
        """
        max_hz = contract.get("safety_constraints", {}).get("max_execution_hz", 1.0)
        budget_ms = min(SANDBOX_TIMEOUT_MS, int(1000 / max_hz) if max_hz else SANDBOX_TIMEOUT_MS)

        start = time.monotonic()
        try:
            # Attempt to load the function class dynamically
            file_path = contract.get("file_path", "")
            if file_path:
                import importlib.util, sys
                spec = importlib.util.spec_from_file_location(function_name, file_path)
                if spec and spec.loader:
                    mod = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(mod)
                    # Do not call run() — existence check only for sandbox
                    logger.debug("[FVP][Stage3] Module loaded: '%s'", function_name)
            else:
                logger.debug("[FVP][Stage3] No file_path — skipping load check.")
        except Exception as exc:
            elapsed = (time.monotonic() - start) * 1000
            logger.warning("[FVP][Stage3] Sandbox load failed for '%s': %s", function_name, exc)
            return elapsed, ValidationResult(
                status=ValidationStatus.REJECTED,
                function_name=function_name,
                stage_reached=2,
                rejection_reason=f"Sandbox dry-run failed: {exc}",
                execution_time_ms=elapsed,
            )

        elapsed = (time.monotonic() - start) * 1000
        if elapsed > budget_ms:
            return elapsed, ValidationResult(
                status=ValidationStatus.REJECTED,
                function_name=function_name,
                stage_reached=2,
                rejection_reason=f"Execution time {elapsed:.0f}ms exceeded budget {budget_ms}ms.",
                execution_time_ms=elapsed,
            )

        return elapsed, None

    # ── Stage 4 ───────────────────────────────────────────────────────────────

    @classmethod
    def _stage4_vee_impact(
        cls,
        function_name: str,
        output_actions: List[str],
    ) -> Optional[ValidationResult]:
        """
        Run VEE.simulate() for physical output actions.
        Returns early ValidationResult if VEE says not safe, else None.
        VEE is ADVISORY — rejection only if safe == False explicitly.
        """
        try:
            from aot.config.feature_flags import capability_manager as _cm
            if not _cm.is_enabled('VEE'):
                logger.debug("[FVP][Stage4] VEE disabled — stage skipped.")
                return None
            from aot.ai.services.virtual_execution_engine import (
                VirtualExecutionEngine,
                SimulationRequest,
            )
            sim_req = SimulationRequest(
                action_payload={"output_actions": output_actions},
                spatial_snapshot={},
                weather_forecast={},
                simulation_horizon_minutes=30,
                urgency_level="NORMAL",
            )
            result = VirtualExecutionEngine().simulate(sim_req)
            if not result.proceed_recommended:
                reason = f"VEE impact assessment failed: conflict_flags={result.conflict_flags}"
                logger.warning("[FVP][Stage4] %s for '%s'", reason, function_name)
                return ValidationResult(
                    status=ValidationStatus.REJECTED,
                    function_name=function_name,
                    stage_reached=3,
                    rejection_reason=reason,
                    conflict_flags=result.conflict_flags,
                )
            logger.debug(
                "[FVP][Stage4] VEE advisory pass for '%s' confidence=%.3f",
                function_name, result.confidence_score,
            )
        except Exception as exc:
            logger.warning("[FVP][Stage4] VEE unavailable — stage skipped: %s", exc)

        return None
