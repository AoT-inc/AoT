# coding=utf-8
"""Which command form each kind of Output takes.

base_output.output_on_off() answers success without doing anything when a
module gets a form it does not take ('sec' on a pwm-only dimmer, 'on' on a
value output). Callers that speak in plain states — operate_device and the
in-app AI manifest — pick the form here instead of guessing.
"""


def _output_module_traits(output_type):
    """(output_types, is_position) of an Output module.

    is_position: a paired open/close actuator or a self-positioning value
    output (Matter window covering) — the map's 3-way control, where Open and
    Close are positions 100 and 0 and Off is Stop.
    """
    from aot.outputs.paired_actuator_common import (
        is_paired_actuator, is_self_positioning_output)
    from aot.utils.outputs import parse_output_information
    info = (parse_output_information() or {}).get(output_type) or {}
    types = list(info.get('output_types') or [])
    return types, is_paired_actuator(output_type) or is_self_positioning_output(output_type)


def plan_output_command(state, output_type, value, duration):
    """The daemon command for operate_device's `state` on this kind of Output.

    Returns {'state', 'output_type', 'amount'} or {'error'}. The daemon's
    output_on_off() answers success without doing anything when a module gets
    a command form it does not take (2026-10-09: 'on' and 'set_value' on a
    dimmer, 'open' on a covering) — so pick the form the module takes, or
    refuse before sending.
    """
    types, is_position = _output_module_traits(output_type)
    level = None if value is None else float(value)

    if state == 'set_value':
        amount = level if level is not None else duration
        if 'value' in types:
            return {'state': 'on', 'output_type': 'value', 'amount': amount}
        if 'pwm' in types:
            return {'state': 'on', 'output_type': 'pwm', 'amount': amount}
        return {'error': f"This output ({output_type}) takes no value; use on/off."}

    if state in ('off', 'close'):
        if state == 'close' and is_position:
            # Close is position 0; off is Stop (it would leave it half open).
            return {'state': 'on', 'output_type': 'value', 'amount': 0.0}
        return {'state': 'off', 'output_type': 'sec', 'amount': 0}

    # on / open
    if is_position:
        return {'state': 'on', 'output_type': 'value', 'amount': 100.0}
    if 'on_off' in types or not types:
        return {'state': 'on', 'output_type': 'sec', 'amount': duration}
    if 'pwm' in types:
        return {'state': 'on', 'output_type': 'pwm',
                'amount': level if level is not None and level > 0 else 100.0}
    return {'error': f"This output ({output_type}) is set by value; "
                     f"use state='set_value' with value."}


def parse_run_seconds(duration_seconds=None, duration_minutes=None):
    """A timed run asked in seconds or in minutes -> (whole seconds, None) or (None, error).

    (None, None) when neither is given. Never truncates: 0.5 minutes is 30 seconds,
    and anything that would round to under one second is refused instead of
    becoming 0 (which meant "no timer" - the output stayed on, 2026-10-30).
    """
    if duration_seconds is not None and duration_minutes is not None:
        return None, "Give the run time once: duration_seconds or duration_minutes, not both."
    name, raw, unit = (('duration_seconds', duration_seconds, 1.0)
                       if duration_seconds is not None
                       else ('duration_minutes', duration_minutes, 60.0))
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return None, None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None, f"{name} must be a number, got {raw!r}."
    if value != value or value in (float('inf'), float('-inf')) or value <= 0:
        return None, f"{name} must be greater than 0, got {raw!r}."
    seconds = int(round(value * unit))
    if seconds < 1:
        return None, f"{name}={raw!r} is under one second; the shortest run is 1 second."
    return seconds, None


def run_time_text(seconds):
    """30 -> '30 s', 300 -> '5 min', 90 -> '1 min 30 s'."""
    seconds = int(seconds)
    minutes, rest = divmod(seconds, 60)
    if not minutes:
        return f"{rest} s"
    return f"{minutes} min" + (f" {rest} s" if rest else "")


def timed_run_refusal(state, output_type):
    """Why this state/output cannot take a timed run, or None.

    A run time means "on, then off by itself". Off, set_value and the position or
    PWM outputs have no timer; the daemon would drop the number and the output would
    stay as commanded. Checked before approval, for direct requests only - the
    scheduler replays old jobs that carry a default duration for any output.
    """
    if str(state or '').lower() != 'on':
        return "A run time only applies to state 'on' (it switches itself off afterwards)."
    plan = plan_output_command('on', output_type, None, 1)
    if 'error' in plan or plan['output_type'] != 'sec':
        return (f"This output ({output_type}) has no timed run; switch it with on/off or "
                "set_value, and switch it off yourself.")
    return None


def output_capabilities(output_type):
    """operate_device states this Output module takes — the same rule as
    plan_output_command(), so the AI manifest cannot offer a state the tool
    would refuse (2026-10-09: every non-'pwm' module, dimmers and coverings
    included, was listed as on_off)."""
    types, is_position = _output_module_traits(output_type)
    if is_position:
        return ["open", "close", "off", "set_value"]
    caps = []
    if 'on_off' in types or not types:
        caps += ["on", "off"]
    if 'pwm' in types:
        caps += ["on", "off", "set_value"]
    if 'value' in types:
        caps += ["set_value", "off"]
    return list(dict.fromkeys(caps))
