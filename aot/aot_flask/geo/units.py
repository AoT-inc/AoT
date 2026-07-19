# coding=utf-8
"""Unit conversion helpers for Geo/Facility 3D asset dimensions.

DB storage rule: all length values are in metres (SI).
These helpers convert between metres and UI display units.
"""

SUPPORTED_UNITS = ('mm', 'cm', 'm', 'in', 'ft')

_TO_METRES = {
    'mm': 0.001,
    'cm': 0.01,
    'm':  1.0,
    'in': 0.0254,
    'ft': 0.3048,
}

_UNIT_LABELS = {
    'mm': 'mm',
    'cm': 'cm',
    'm':  'm',
    'in': 'in',
    'ft': 'ft',
}


def to_meters(value, unit='m'):
    """Convert *value* (in *unit*) to metres. Returns float."""
    factor = _TO_METRES.get(unit)
    if factor is None:
        raise ValueError(f"Unsupported unit '{unit}'. Use one of {SUPPORTED_UNITS}.")
    return float(value) * factor


def from_meters(value_m, unit='m'):
    """Convert *value_m* (metres) to *unit*. Returns float."""
    factor = _TO_METRES.get(unit)
    if factor is None:
        raise ValueError(f"Unsupported unit '{unit}'. Use one of {SUPPORTED_UNITS}.")
    return float(value_m) / factor


def unit_label(unit='m'):
    return _UNIT_LABELS.get(unit, unit)
