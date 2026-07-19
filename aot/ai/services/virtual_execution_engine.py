# coding=utf-8
"""
VirtualExecutionEngine (VEE) — Phase 5 Simulation Layer.

Design constraints (005_EDGE_OPTIMIZED_SPECIFICATION.yaml / SEC-001):
  - VEE is ADVISORY ONLY. advisory_only=True is immutable on every SimulationResult.
  - SafetyService.validate() MUST be called by the caller AFTER VEE, regardless of
    SimulationResult.proceed_recommended. VEE never replaces the safety gate.
  - VEE never raises SafetyViolation. It returns SimulationResult in all cases.
  - Gated by CapabilityManager.is_enabled('VEE') at the call site (PhysicalControlResolver).
  - 500 ms hard timeout: on breach, fail-open (proceed_recommended=True) with WARNING log.
  - Flask app context is available in the main thread. Cache reads are performed
    BEFORE ThreadPoolExecutor submission to avoid context loss inside the worker.

Ref: 010_IMPLEMENTATION_PLAN.yaml  Phase B / B-2
"""
import concurrent.futures
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
SPATIAL_TTL: int = 1800       # 30 minutes in seconds
WEATHER_TTL: int = 1800       # 30 minutes in seconds
TIMEOUT_MS: int = 500         # Hard execution timeout

URGENCY_CRITICAL: str = "CRITICAL"
URGENCY_NORMAL: str = "NORMAL"


# ---------------------------------------------------------------------------
# Data transfer objects
# ---------------------------------------------------------------------------
@dataclass
class SimulationRequest:
    """Input payload for VEE.simulate()."""
    action_payload: Dict[str, Any]
    spatial_snapshot: Dict[str, Any]
    weather_forecast: Dict[str, Any]
    simulation_horizon_minutes: int = 30
    urgency_level: str = URGENCY_NORMAL   # "CRITICAL" | "NORMAL"
    device_profile: Optional[Any] = None
    # DeviceCapabilityProfile | None — typed as Any to avoid circular import.
    # Populated by PhysicalControlResolver when DeviceCapabilityRegistry.get_profile() succeeds.
    # VEE.simulate() merges this into effective_payload before _run_simulation() (Phase 5 M5_4).


@dataclass
class SimulationResult:
    """
    Advisory output of VEE.simulate().

    advisory_only is always True — callers MUST NOT skip SafetyService.validate()
    based on this result (SEC-001).
    """
    predicted_state_delta: Dict[str, Any] = field(default_factory=dict)
    conflict_flags: List[str] = field(default_factory=list)
    confidence_score: float = 0.0
    proceed_recommended: bool = True
    advisory_only: bool = True        # Immutable — always True

    def __post_init__(self) -> None:
        # Enforce immutability of advisory_only (SEC-001)
        object.__setattr__(self, "advisory_only", True)


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------
# @ANCHOR: VIRTUAL_EXECUTION_ENGINE
class VirtualExecutionEngine:
    """
    Simulates the expected outcome of a physical action before execution.

    Usage (PhysicalControlResolver):
        vee = VirtualExecutionEngine()
        result = vee.simulate(sim_request)
        # result is advisory — SafetyService.validate() still runs after this
    """

    # ------------------------------------------------------------------
    # Cache helpers (lazy Flask-Caching import — deferred to call time)
    # ------------------------------------------------------------------
    @staticmethod
    def _build_cache_key(prefix: str, target_id: Optional[str]) -> str:
        safe_id = target_id or "global"
        return f"vee:{prefix}:{safe_id}"

    @staticmethod
    def _get_cached(key: str) -> Optional[Dict]:
        try:
            from aot.aot_flask.extensions import cache
            return cache.get(key)
        except Exception as exc:
            logger.debug("[VEE][CACHE_READ_ERROR] key=%s err=%s", key, exc)
            return None

    @staticmethod
    def _set_cached(key: str, data: Dict, ttl: int) -> None:
        try:
            from aot.aot_flask.extensions import cache
            cache.set(key, data, timeout=ttl)
        except Exception as exc:
            logger.debug("[VEE][CACHE_WRITE_ERROR] key=%s err=%s", key, exc)

    # ------------------------------------------------------------------
    # Internal simulation (runs inside ThreadPoolExecutor worker)
    # NOTE: No Flask context available here — do NOT access cache or DB.
    # Receive all data as plain Python objects from the caller.
    # ------------------------------------------------------------------
    @staticmethod
    def _run_simulation(
        action_payload: Dict[str, Any],
        spatial_snapshot: Dict[str, Any],
        weather_forecast: Dict[str, Any],
        horizon_minutes: int,
    ) -> SimulationResult:
        """
        Phase 5 stub — deterministic rule-based prediction.
        Produces an advisory SimulationResult from pre-fetched data.
        No external I/O; safe to run inside a ThreadPoolExecutor worker.

        TODO Phase 6: replace with ML-based simulation model.
        """
        conflict_flags: List[str] = []
        predicted_delta: Dict[str, Any] = {}
        confidence: float = 0.8

        action_type: str = action_payload.get("action_type", "")
        tool_name: str = action_payload.get("tool_name", "")

        # --- Spatial conflict check ---
        active_zones: List[str] = spatial_snapshot.get("active_zones", [])
        target_zone: Optional[str] = spatial_snapshot.get("target_zone")
        if target_zone and target_zone in active_zones:
            conflict_flags.append(f"ZONE_ACTIVE:{target_zone}")
            confidence = max(0.0, confidence - 0.3)

        # --- Device profile risk check (Phase 5 — M5_4 device_profile) ---
        # action_payload['_device_profile'] may be a DeviceCapabilityProfile or a dict
        # (injected by PhysicalControlResolver M4_4 or merged from SimulationRequest.device_profile).
        device_profile = action_payload.get('_device_profile')
        if device_profile is not None:
            # Support both DeviceCapabilityProfile dataclass and dict (backward compat)
            risk = getattr(device_profile, 'risk_level', None)
            if risk is None and isinstance(device_profile, dict):
                risk = device_profile.get('risk_level')
            if risk is not None and str(risk) in ('HIGH', 'CRITICAL'):
                conflict_flags.append(f"DEVICE_RISK:{risk}")
                confidence = max(0.0, confidence - 0.2)
            # Additional constraint checks (control_modes, safety_constraints) — Phase 6

        # --- Weather threshold check ---
        temp_c: Optional[float] = weather_forecast.get("temperature_c")
        wind_ms: Optional[float] = weather_forecast.get("wind_speed_ms")
        if temp_c is not None and temp_c < -10:
            conflict_flags.append("WEATHER_EXTREME_COLD")
            confidence = max(0.0, confidence - 0.2)
        if wind_ms is not None and wind_ms > 20:
            conflict_flags.append("WEATHER_HIGH_WIND")
            confidence = max(0.0, confidence - 0.1)

        # --- Predicted state delta ---
        if action_type or tool_name:
            predicted_delta["action"] = action_type or tool_name
            predicted_delta["estimated_duration_min"] = horizon_minutes
            predicted_delta["expected_outcome"] = "nominal" if not conflict_flags else "degraded"

        proceed: bool = len(conflict_flags) == 0

        return SimulationResult(
            predicted_state_delta=predicted_delta,
            conflict_flags=conflict_flags,
            confidence_score=round(confidence, 3),
            proceed_recommended=proceed,
            advisory_only=True,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def simulate(self, request: SimulationRequest) -> SimulationResult:
        """
        Evaluate the expected impact of request.action_payload.

        Returns SimulationResult (always advisory_only=True).
        Caller MUST invoke SafetyService.validate() after this method (SEC-001).
        """
        # ── URGENCY BYPASS ────────────────────────────────────────────
        if request.urgency_level == URGENCY_CRITICAL:
            logger.warning(
                "[VEE][URGENCY_BYPASS] CRITICAL urgency — VEE skipped. "
                "SafetyService.validate() will run."
            )
            return SimulationResult(
                predicted_state_delta={},
                conflict_flags=[],
                confidence_score=1.0,
                proceed_recommended=True,
                advisory_only=True,
            )

        # ── CACHE LOOKUP (main thread — Flask context available) ──────
        target_id: Optional[str] = (
            request.action_payload.get("target_id")
            or request.action_payload.get("arguments", {}).get("device_id")
        )
        spatial_key = self._build_cache_key("spatial", target_id)
        weather_key = self._build_cache_key("weather", target_id)

        cached_spatial = self._get_cached(spatial_key)
        cached_weather = self._get_cached(weather_key)

        effective_spatial = cached_spatial if cached_spatial is not None else request.spatial_snapshot
        effective_weather = cached_weather if cached_weather is not None else request.weather_forecast

        # ── M5_4: Merge device_profile into payload for _run_simulation ─
        # _run_simulation() runs inside ThreadPoolExecutor (no Flask context).
        # device_profile must be passed as plain Python object via action_payload.
        effective_payload = dict(request.action_payload)
        if getattr(request, 'device_profile', None) is not None:
            if '_device_profile' not in effective_payload:
                effective_payload['_device_profile'] = request.device_profile

        # ── SIMULATION (ThreadPoolExecutor — no Flask context inside) ─
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(
                self._run_simulation,
                effective_payload,
                effective_spatial,
                effective_weather,
                request.simulation_horizon_minutes,
            )
            try:
                result: SimulationResult = future.result(
                    timeout=TIMEOUT_MS / 1000.0
                )
            except concurrent.futures.TimeoutError:
                logger.warning(
                    "[VEE][TIMEOUT] Simulation exceeded %dms — fail-open. "
                    "SafetyService.validate() will run.",
                    TIMEOUT_MS,
                )
                return SimulationResult(
                    predicted_state_delta={},
                    conflict_flags=[],
                    confidence_score=0.0,
                    proceed_recommended=True,
                    advisory_only=True,
                )

        # ── CACHE WRITE (main thread — Flask context available) ───────
        if cached_spatial is None:
            self._set_cached(spatial_key, request.spatial_snapshot, SPATIAL_TTL)
        if cached_weather is None:
            self._set_cached(weather_key, request.weather_forecast, WEATHER_TTL)

        logger.info(
            "[VEE] target=%s confidence=%.3f proceed=%s conflicts=%s",
            target_id,
            result.confidence_score,
            result.proceed_recommended,
            result.conflict_flags,
        )
        return result
