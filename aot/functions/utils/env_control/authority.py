# coding=utf-8
"""
env_control/authority.py — Automatic Control Authority derivation (P5-2).

Automatically determines the control authority (ACTIVE / PASSIVE / NATURAL)
for each environment variable based on the registered actuator kinds.

Level definitions:
  ACTIVE  — Active control possible (has an actuator that directly affects the variable)
  PASSIVE — Indirect/externally-dependent control (ventilation, shading, etc.; depends on outside conditions)
  NATURAL — Natural dependence, no control possible (no affecting actuator)

See: docs/env_control_enhancement_design.md §3.17
"""

from __future__ import annotations

from typing import Dict, List

# ─────────────────────────────────────────────────────────────────────────────
# Authority level ranking (higher = stronger control)
# ─────────────────────────────────────────────────────────────────────────────

LEVEL_NATURAL = 'NATURAL'
LEVEL_PASSIVE = 'PASSIVE'
LEVEL_ACTIVE  = 'ACTIVE'

_RANK: Dict[str, int] = {
    LEVEL_NATURAL: 0,
    LEVEL_PASSIVE:  1,
    LEVEL_ACTIVE:   2,
}

# Authority key set (varname_direction)
AUTHORITY_KEYS = (
    'T_up', 'T_down',
    'RH_up', 'RH_down',
    'CO2_up', 'CO2_down',
    'Light_up', 'Light_down',
)


def _upgrade(current: str, candidate: str) -> str:
    """Replace with the candidate if it has a higher level than the current, otherwise keep current."""
    return candidate if _RANK.get(candidate, 0) > _RANK.get(current, 0) else current


# ─────────────────────────────────────────────────────────────────────────────
# kind → authority impact mapping
# ─────────────────────────────────────────────────────────────────────────────

# The variable×direction authority that each actuator kind can raise.
# Value: ACTIVE or PASSIVE (NATURAL is the default — not listed = no impact)
_KIND_AUTHORITY: Dict[str, Dict[str, str]] = {
    'heater': {
        'T_up': LEVEL_ACTIVE,
    },
    'cooler': {
        'T_down': LEVEL_ACTIVE,
    },
    'fogger': {
        'RH_up':  LEVEL_ACTIVE,
        'T_down': LEVEL_PASSIVE,   # evaporative cooling side effect
    },
    'co2_injector': {
        'CO2_up': LEVEL_ACTIVE,
    },
    'shade': {
        'Light_down': LEVEL_PASSIVE,
        'T_down':     LEVEL_PASSIVE,   # shading → reduced radiant heat
    },
    'curtain': {
        'T_up': LEVEL_PASSIVE,         # thermal curtain → heat retention
    },
    'lighting': {
        'Light_up': LEVEL_ACTIVE,
    },
    'opening': {
        'T_down':   LEVEL_PASSIVE,
        'RH_down':  LEVEL_PASSIVE,
        'CO2_down': LEVEL_PASSIVE,
    },
    'circulation_fan': {
        'T_down':  LEVEL_PASSIVE,
        'RH_down': LEVEL_PASSIVE,
    },
    'exhaust_fan': {
        'T_down':   LEVEL_PASSIVE,
        'RH_down':  LEVEL_PASSIVE,
        'CO2_down': LEVEL_PASSIVE,
    },
    'intake_fan': {
        'T_down': LEVEL_PASSIVE,
    },
}


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

def derive_authority(profiles) -> Dict[str, str]:
    """Derive the per-variable control authority from the list of registered actuators.

    Args:
        profiles: List[ActuatorProfile] — list of registered actuator profiles

    Returns:
        {var_key: level} — e.g. {'T_up': 'ACTIVE', 'T_down': 'PASSIVE', ...}
        Unregistered kinds remain NATURAL.
    """
    result: Dict[str, str] = {k: LEVEL_NATURAL for k in AUTHORITY_KEYS}

    for p in profiles:
        kind_map = _KIND_AUTHORITY.get(p.kind, {})
        for var_key, level in kind_map.items():
            result[var_key] = _upgrade(result[var_key], level)

    return result


def authority_summary(authority: Dict[str, str]) -> str:
    """One-line summary string for logging."""
    parts = []
    for k in AUTHORITY_KEYS:
        v = authority.get(k, LEVEL_NATURAL)
        if v != LEVEL_NATURAL:
            parts.append(f'{k}={v[0]}')  # first letter only (A/P)
    return ', '.join(parts) if parts else 'all NATURAL'


def is_all_natural(authority: Dict[str, str]) -> bool:
    """True if all variables are NATURAL (outside-air tracking-only mode)."""
    return all(v == LEVEL_NATURAL for v in authority.values())


def is_natural_var(authority: Dict[str, str], var: str) -> bool:
    """True if both the up and down directions of a given variable are NATURAL."""
    up_key   = f'{_VAR_TO_KEY.get(var, var)}_up'
    down_key = f'{_VAR_TO_KEY.get(var, var)}_down'
    return (authority.get(up_key, LEVEL_NATURAL) == LEVEL_NATURAL and
            authority.get(down_key, LEVEL_NATURAL) == LEVEL_NATURAL)


# Internal: EnvTarget variable name → authority key prefix
_VAR_TO_KEY: Dict[str, str] = {
    'temperature': 'T',
    'humidity':    'RH',
    'co2':         'CO2',
    'light':       'Light',
    'vpd':         'T',    # VPD is a T/RH composite — approximated by T authority
}


def needed_direction_authority(
    authority: Dict[str, str], var: str, deviation: float,
) -> str:
    """Return the control authority level for the direction matching the deviation sign.

    authority is keyed by direction keys like 'T_up'/'CO2_down', so looking it
    up with a bare variable name ('temperature'/'co2'…) always misses → NATURAL.
    Determine the required direction from the deviation and look up the correct
    direction key.

    deviation = current - target:
      dev < 0 (current < target) → needs raising (up)
      dev >= 0 (current >= target) → needs lowering (down)

    Returns:
        LEVEL_ACTIVE / LEVEL_PASSIVE / LEVEL_NATURAL.
        NATURAL means there is no actuator to control that direction.
    """
    prefix  = _VAR_TO_KEY.get(var, var)
    dir_key = f'{prefix}_up' if deviation < 0 else f'{prefix}_down'
    return authority.get(dir_key, LEVEL_NATURAL)


# ─────────────────────────────────────────────────────────────────────────────
# P5-3: Automatic target relaxation (degrade_target)
# ─────────────────────────────────────────────────────────────────────────────

def degrade_target(env_target, authority: Dict[str, str], external: Dict) -> None:
    """Relax the targets of NATURAL-authority variables to match outside-air conditions (in-place).

    Relaxation policy:
      - If a variable is NATURAL (in both directions), replace its target with the outside-air measurement.
      - If there is no outside-air measurement, skip relaxation (keep the original target).
      - A relaxed TargetVar is marked with degraded=True.

    Args:
        env_target: EnvTarget dict (modified in-place)
        authority:  result of derive_authority()
        external:   external sensor dict {'T_ext', 'RH_ext', 'CO2_ext', ...}
    """
    _VAR_EXT_KEY = {
        'temperature': 'T_ext',
        'humidity':    'RH_ext',
        'co2':         'CO2_ext',
    }

    for var, tv in env_target.items():
        if var.startswith('_'):
            continue
        if not is_natural_var(authority, var):
            continue

        ext_key = _VAR_EXT_KEY.get(var)
        ext_val = external.get(ext_key) if ext_key else None
        if ext_val is None:
            continue

        tv.value    = float(ext_val)
        tv.degraded = True


def detect_unattainable(
    env_target,
    deviation_native: Dict[str, float],
    authority: Dict[str, str],
    unattainable_state: Dict[str, int],
    threshold_cycles: int = 5,
) -> List[str]:
    """Return the list of unattainable-target variables and update the counters.

    Condition: a variable is judged unattainable if it is ACTIVE while its
    deviation exceeds tolerance × 2 for at least threshold_cycles consecutive cycles.

    Args:
        env_target:           EnvTarget
        deviation_native:     deviation dict (situation.deviation_native)
        authority:            result of derive_authority()
        unattainable_state:   {var: consecutive exceedance cycle count} (updated in-place)
        threshold_cycles:     cycle count threshold for the judgment

    Returns:
        List of variable names currently judged unattainable
    """
    unattainable_vars: List[str] = []

    for var, tv in env_target.items():
        if var.startswith('_'):
            continue
        dev = deviation_native.get(var, 0.0)
        # Count only when ACTIVE and deviation is at least 2×tolerance
        if (not is_natural_var(authority, var) and
                abs(dev) > tv.tolerance * 2.0):
            unattainable_state[var] = unattainable_state.get(var, 0) + 1
        else:
            unattainable_state[var] = 0

        if unattainable_state.get(var, 0) >= threshold_cycles:
            unattainable_vars.append(var)

    return unattainable_vars
