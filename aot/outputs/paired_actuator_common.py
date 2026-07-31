# coding=utf-8
"""Shared definitions for paired-actuator outputs (open relay + close relay).

Two output modules implement the same "drive a position (0–100%) by running a
pair of relays for a calibrated travel time" contract:

  - ``actuator_paired``      — one actuator, its own dedicated open/close relays.
  - ``actuator_paired_bus``  — N actuators sharing one open/close relay pair,
                               each selected by its own selector relay.

Both expose ``output_types: ['value']`` and the same channel-option vocabulary
(``actuator_kind``, ``travel_time_open_sec``, ``move_step_pct``, …), so every
consumer — the environment coordinator's profile loader, the env-control
dispatch adapters, the geo 3-way actuator popup, the output form handler —
must treat them identically.

Those consumers used to test ``output_type == 'actuator_paired'`` as a bare
string literal in nine separate places. Adding a second module that way would
have meant nine more literals to keep in sync. They now test membership in
``PAIRED_ACTUATOR_OUTPUT_TYPES`` instead: a new paired-actuator module is
registered once, here.
"""
from flask_babel import lazy_gettext

# Output module unique names that implement the paired-actuator contract.
# Consumers must use this set rather than comparing against a single literal.
PAIRED_ACTUATOR_OUTPUT_TYPES = frozenset({
    'actuator_paired',
    'actuator_paired_bus',
})

ACTUATOR_KIND_OPTIONS = [
    ('side_vent',       lazy_gettext('Side Vent')),
    ('roof_vent',       lazy_gettext('Roof Vent')),
    ('thermal_curtain', lazy_gettext('Thermal Curtain')),
    ('shade_curtain',   lazy_gettext('Shade Curtain')),
    ('ball_valve',      lazy_gettext('Ball Valve')),
]

KIND_TO_PROFILE_KIND = {
    'side_vent':       'opening',
    'roof_vent':       'opening',
    'thermal_curtain': 'curtain',
    'shade_curtain':   'shade',
    'ball_valve':      'opening',
}


def is_paired_actuator(output_type):
    """True if the given Output.output_type implements the paired-actuator contract."""
    return output_type in PAIRED_ACTUATOR_OUTPUT_TYPES
