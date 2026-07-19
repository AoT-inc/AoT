# coding=utf-8
import pytest

from aot.outputs.actuator_paired import (
    OUTPUT_INFORMATION,
    ACTUATOR_KIND_OPTIONS,
    KIND_TO_PROFILE_KIND,
)
from aot.functions.utils.env_control.types import ACTUATOR_KINDS


def test_output_name_unique():
    assert OUTPUT_INFORMATION['output_name_unique'] == 'actuator_paired'


def test_output_types_value():
    assert OUTPUT_INFORMATION['output_types'] == ['value']


def test_channel0_is_value_type():
    ch = OUTPUT_INFORMATION['channels_dict'][0]
    assert 'value' in ch['types']


def test_button_send_value():
    assert 'button_send_value' in OUTPUT_INFORMATION['options_enabled']


def test_required_options_present():
    ids = {o['id'] for o in OUTPUT_INFORMATION['custom_channel_options']}
    must = {
        'actuator_kind',
        'output_open_id', 'output_close_id',
        'travel_time_sec',
        'calib_direction',
    }
    assert must.issubset(ids), f"missing: {must - ids}"


def test_no_unidirectional_options():
    ids = {o['id'] for o in OUTPUT_INFORMATION['custom_channel_options']}
    assert 'output_relay_id' not in ids
    assert 'on_threshold_pct' not in ids


def test_all_kinds_map_to_known_actuator_kinds():
    for kind_id, _label in ACTUATOR_KIND_OPTIONS:
        target = KIND_TO_PROFILE_KIND.get(kind_id)
        assert target is not None, f"{kind_id} 매핑 없음"
        assert target in ACTUATOR_KINDS, f"{target} not in ACTUATOR_KINDS"


def test_actuator_kind_default_is_side_vent():
    opt = next(o for o in OUTPUT_INFORMATION['custom_channel_options']
               if o['id'] == 'actuator_kind')
    assert opt['default_value'] == 'side_vent'


def test_kind_to_profile_kind_complete():
    expected = {kind_id for kind_id, _ in ACTUATOR_KIND_OPTIONS}
    assert set(KIND_TO_PROFILE_KIND.keys()) == expected


def test_calibration_commands_present():
    ids = {c['id'] for c in OUTPUT_INFORMATION.get('custom_commands', [])}
    assert 'calib_run' in ids
    assert 'calib_stop' in ids
