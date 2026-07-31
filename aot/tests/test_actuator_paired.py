# coding=utf-8
from types import SimpleNamespace

import pytest

from aot.outputs.actuator_paired import (
    OUTPUT_INFORMATION,
    OutputModule,
    ACTUATOR_KIND_OPTIONS,
    KIND_TO_PROFILE_KIND,
)
from aot.functions.utils.env_control.types import ACTUATOR_KINDS


class _EmptyQuery:
    """Stands in for the OutputChannel query so construction stays off the DB."""

    def filter(self, *args, **kwargs):
        return self

    def all(self):
        return []


@pytest.fixture
def module(monkeypatch):
    monkeypatch.setattr(
        'aot.outputs.actuator_paired.db_retrieve_table_daemon',
        lambda *args, **kwargs: _EmptyQuery())

    def _plain_logger(self, testing=False, name=None, output_dev=None):
        import logging
        self.logger = logging.getLogger('test.actuator_paired')

    # The real one reads the log level out of the AoT database.
    monkeypatch.setattr(
        'aot.outputs.base_output.AbstractOutput.setup_logger', _plain_logger)

    output = SimpleNamespace(
        unique_id='paired-1', name='paired-1', output_type='actuator_paired',
        latitude=None, longitude=None, location_source='manual',
        log_level_debug=False)
    return OutputModule(output, testing=True)


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
        'travel_time_open_sec', 'travel_time_close_sec',
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


def test_calibrated_travel_time_takes_effect_without_a_reload(module):
    """A freshly calibrated travel time must be visible to the running module.

    set_custom_channel_option() only writes the database, while options_channels
    is built once in __init__. Before _save_option() existed, calibrating stored a
    travel time the module could not see: _get_travel_time() fell back to its 60 s
    default and the next move drove the motor for that duration instead of the
    measured one, into the end stop. Saving the output form happened to reload the
    module and hide it — which is what the calibration message's "Reload page to
    confirm" hint was really working around.
    """
    saved = {}
    module.set_custom_channel_option = lambda ch, key, value: saved.__setitem__(key, value)

    assert module._get_travel_time('open') == 60.0  # uncalibrated fallback

    module._save_option('travel_time_open_sec', 12.0)  # what calib_stop does

    assert saved['travel_time_open_sec'] == 12.0  # persisted
    assert module._get_travel_time('open') == 12.0  # and visible in-memory


def test_saved_position_is_visible_in_memory(module):
    saved = {}
    module.set_custom_channel_option = lambda ch, key, value: saved.__setitem__(key, value)

    module._save_position(42.0)

    assert saved['last_position_pct'] == 42.0
    assert module._opt('last_position_pct') == 42.0
