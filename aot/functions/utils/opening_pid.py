# coding=utf-8
"""
opening_pid.py — Lightweight PID controller for facility opening control.

Design notes (from opening_control_design.md §5.4, §15.2):
  - Derivative-on-PV only (no derivative kick on setpoint change, C2)
  - Anti-windup via back-calculation (C3)
  - Bumpless transfer: reset() re-initialises integrator from current PV (C4)
  - Setpoint slew-rate limiting applied upstream in opening_brain.py (C5)
"""

import time


class LightPID:
    """Minimal PID controller optimised for slow actuator systems (opening control).

    @phase core
    @stability stable
    """

    # ── Type-specific default gains ───────────────────────────────────────────
    DEFAULT_GAINS = {
        'temperature':  {'kp': 6.0,  'ki': 0.08, 'kd': 0.0},
        'humidity':     {'kp': 5.0,  'ki': 0.06, 'kd': 0.0},
        'vpd':          {'kp': 8.0,  'ki': 0.10, 'kd': 0.0},
        'co2':          {'kp': 4.0,  'ki': 0.05, 'kd': 0.0},
        'default':      {'kp': 6.0,  'ki': 0.08, 'kd': 0.0},
    }

    def __init__(
        self,
        kp: float,
        ki: float,
        kd: float,
        out_min: float = 0.0,
        out_max: float = 100.0,
        integral_min: float = -50.0,
        integral_max: float = 50.0,
        reverse: bool = False,
    ):
        """
        Args:
            kp, ki, kd: PID gains.
            out_min/out_max: output clamp range.
            integral_min/max: anti-windup clamp for integrator.
            reverse: if True, negate error (raise_when_pv_low → lower_when_pv_high).
        """
        self.kp = kp
        self.ki = ki
        self.kd = kd
        self.out_min = out_min
        self.out_max = out_max
        self.integral_min = integral_min
        self.integral_max = integral_max
        self.reverse = reverse

        self._integral = 0.0
        self._prev_pv = None          # for D-on-PV
        self._prev_time = None
        self._output = 0.0

    # ── Public API ────────────────────────────────────────────────────────────

    def compute(self, pv: float, sp: float, now: float = None) -> float:
        """Compute PID output.

        Derivative is applied on PV change only (not setpoint change).
        Anti-windup uses back-calculation: integrator is wound back when output
        saturates.

        Args:
            pv: current process variable measurement.
            sp: current setpoint (already slew-rate-limited by caller).
            now: current timestamp (uses time.time() if None).

        Returns:
            Control output in [out_min, out_max].
        """
        now = now or time.time()

        if self._prev_time is None:
            # First call — initialise without derivative
            self._prev_pv = pv
            self._prev_time = now
            error = sp - pv
            if self.reverse:
                error = -error
            self._integral = max(self.integral_min, min(self.integral_max, 0.0))
            self._output = max(self.out_min, min(self.out_max, self.kp * error))
            return self._output

        dt = now - self._prev_time
        if dt <= 0:
            return self._output

        error = sp - pv
        if self.reverse:
            error = -error

        # ── Proportional ──────────────────────────────────────────────────────
        p_term = self.kp * error

        # ── Integral with conditional integration ─────────────────────────────
        # Only integrate when output is not saturated (conditional integration).
        raw_output_before = p_term + self.ki * self._integral
        if (raw_output_before < self.out_max or error < 0) and \
           (raw_output_before > self.out_min or error > 0):
            self._integral += error * dt
        self._integral = max(self.integral_min, min(self.integral_max, self._integral))

        i_term = self.ki * self._integral

        # ── Derivative on PV (not error) ──────────────────────────────────────
        # Negated: rising PV reduces output for a "lower_when_pv_high" action.
        d_pv = (pv - self._prev_pv) / dt if dt > 0 else 0.0
        d_term = -self.kd * d_pv  # negative: PV rise → decrease output

        raw_output = p_term + i_term + d_term
        self._output = max(self.out_min, min(self.out_max, raw_output))

        self._prev_pv = pv
        self._prev_time = now
        return self._output

    def reset(self, pv: float = None):
        """Bumpless reset — re-initialise integrator.

        Call on bumpless transfer (safety release, manual TTL expiry, etc.).
        Integrator is zeroed so next compute() starts from a clean state.

        Args:
            pv: current PV for derivative baseline; uses stored value if None.
        """
        self._integral = 0.0
        if pv is not None:
            self._prev_pv = pv
        self._prev_time = None   # forces re-init without derivative on next call

    @classmethod
    def from_target_type(
        cls,
        target_name: str,
        gains_override: dict = None,
        reverse: bool = False,
        out_min: float = 0.0,
        out_max: float = 100.0,
    ) -> 'LightPID':
        """Factory: build a LightPID from target name with optional gain override.

        Args:
            target_name: e.g. 'temperature', 'vpd', 'humidity'.
            gains_override: dict with any of kp/ki/kd to override defaults.
            reverse: negate error direction.
        """
        base = cls.DEFAULT_GAINS.get(target_name, cls.DEFAULT_GAINS['default']).copy()
        if gains_override:
            base.update({k: v for k, v in gains_override.items() if v is not None})
        return cls(
            kp=base['kp'], ki=base['ki'], kd=base['kd'],
            reverse=reverse,
            out_min=out_min, out_max=out_max,
        )
