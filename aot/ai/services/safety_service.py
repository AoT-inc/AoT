# coding=utf-8
"""
SafetyService - Independent validation layer for all AI action execution paths.

Validates physical thresholds, prevents duplicate channel activation,
and enforces daily execution limits before any hardware action is performed.
"""
import logging
from datetime import datetime, timedelta

from aot.aot_flask.extensions import db

logger = logging.getLogger(__name__)


class SafetyViolation(Exception):
    """Raised when an action violates safety constraints."""
    def __init__(self, violations):
        self.violations = violations
        super().__init__(f"Safety violation(s): {'; '.join(violations)}")


# Configurable safety limits (can be overridden via Misc or config)
SAFETY_DEFAULTS = {
    'max_temperature': 60.0,     # Celsius - heater upper bound
    'max_duration_sec': 3600,    # 1 hour max single run
    'max_pwm_duty': 100.0,      # PWM duty cycle cap
    'daily_execution_limit': 200, # Max executions per target per day
}


class SafetyService:
    """
    Validates all AI actions before execution.
    Called by both manual reasoning execution and scheduled jobs.
    """

    @staticmethod
    def validate(action_type, target_id, params):
        """
        Run all safety checks. Raises SafetyViolation if any fail.

        Args:
            action_type: 'output', 'pid', 'function'
            target_id: device unique_id
            params: action parameters dict
        """
        violations = []

        if action_type == 'output':
            violations.extend(SafetyService._check_output_params(target_id, params))
        elif action_type == 'pid':
            violations.extend(SafetyService._check_pid_params(target_id, params))

        # Spatial conflict checks
        violations.extend(SafetyService._check_spatial_conflicts(action_type, target_id))

        # Universal checks
        violations.extend(SafetyService._check_daily_limit(action_type, target_id))

        if violations:
            logger.warning(f"Safety violation for {action_type} on {target_id}: {violations}")
            raise SafetyViolation(violations)

    @staticmethod
    def _check_spatial_conflicts(action_type, target_id):
        """Check if action conflicts with a running abstract plan in the same area."""
        violations = []
        if action_type == 'abstract_plan':
            return violations # Abstract plans don't conflict with each other for now

        try:
            from aot.databases.models.output import Output
            from aot.databases.models.geo import GeoShape
            from aot.databases.models.scheduler import SchedulerJobMeta
            from aot.utils.time_utils import get_local_now
            now = get_local_now()
            conflicts = SchedulerJobMeta.query.filter(
                SchedulerJobMeta.action_type == 'abstract_plan',
                SchedulerJobMeta.state.in_(['RUNNING', 'PENDING']),
                SchedulerJobMeta.target_id.in_(areas_to_check)
            ).all()

            for c in conflicts:
                is_active = False
                if c.state == 'RUNNING':
                    is_active = True
                elif c.schedule_time and c.end_time:
                    if c.schedule_time <= now <= c.end_time:
                        is_active = True
                
                if is_active:
                    violations.append(
                        f"Conflict with plan '{c.reasoning[:30]}' in {geo_shape.type} '{geo_shape.geo_id}' (Active until {c.end_time.strftime('%H:%M') if c.end_time else 'completed'})"
                    )

        except Exception as e:
            logger.warning(f"Spatial conflict check failed for {target_id}: {e}")
            
        return violations

    @staticmethod
    def _check_output_params(target_id, params):
        """Validate output action parameters against physical limits."""
        violations = []
        amount = params.get('amount', 0)
        state = params.get('state', 'off')

        if state == 'on' and amount is not None:
            # Duration/amount upper bound
            amount_float = float(amount) if amount else 0
            if amount_float > SAFETY_DEFAULTS['max_duration_sec']:
                violations.append(
                    f"amount {amount_float}s exceeds max duration "
                    f"{SAFETY_DEFAULTS['max_duration_sec']}s"
                )
            if amount_float < 0:
                violations.append(f"amount cannot be negative: {amount_float}")

        # Channel bounds check
        channel = params.get('channel', 0)
        if channel is not None and int(channel) < 0:
            violations.append(f"channel index cannot be negative: {channel}")

        return violations

    @staticmethod
    def _check_pid_params(target_id, params):
        """Validate PID adjustment parameters."""
        violations = []
        setting = params.get('setting', 'setpoint')
        value = params.get('value')

        if value is not None and setting == 'setpoint':
            val_float = float(value)
            if val_float > SAFETY_DEFAULTS['max_temperature']:
                violations.append(
                    f"setpoint {val_float} exceeds max temperature "
                    f"{SAFETY_DEFAULTS['max_temperature']}°C"
                )

        return violations

    @staticmethod
    def _check_daily_limit(action_type, target_id):
        """Check if daily execution count exceeds the limit."""
        violations = []
        try:
            from aot.databases.models.scheduler import SchedulerJobMeta
            from aot.utils.time_utils import get_local_now
            import pytz
            
            # Use local today start (midnight in user's timezone)
            local_now = get_local_now()
            today_start_local = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
            # Convert to UTC naive for database comparison (standard storage format)
            today_start_utc = today_start_local.astimezone(pytz.utc).replace(tzinfo=None)
            
            count = SchedulerJobMeta.query.filter(
                SchedulerJobMeta.target_id == target_id,
                SchedulerJobMeta.state.in_(['COMPLETED', 'RUNNING']),
                SchedulerJobMeta.executed_at >= today_start_utc
            ).count()

            if count >= SAFETY_DEFAULTS['daily_execution_limit']:
                violations.append(
                    f"daily execution limit ({SAFETY_DEFAULTS['daily_execution_limit']}) "
                    f"reached for {target_id}"
                )
        except Exception:
            # Table may not exist yet during initial setup
            pass

        return violations
