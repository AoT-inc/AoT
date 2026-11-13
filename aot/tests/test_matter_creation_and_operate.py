# coding=utf-8
"""Matter children only come from Settings > Matter, and operate_device sends
each kind of Output a command it actually takes.

2026-10-09 (after the Matter merge): create_output / the Outputs page could make
MATTER_ON_OFF/LEVEL/COVERING and MATTER_NODE with node_id 0 — orphans bound to
nothing. And operate_device sent 'on' as a 'sec' command and set_value as a
'value' command to every Output; base_output silently answers success when a
module does not take that form, so 'on'/set_value on a dimmer and 'open' on a
covering or paired vent did nothing while the AI was told it worked.
"""
from types import SimpleNamespace

import pytest

from aot.devices import matter_onboarding


@pytest.fixture
def babel_app():
    try:
        from flask import Flask
        from flask_babel import Babel
    except ImportError:
        pytest.skip('flask not installed')
    app = Flask(__name__)
    Babel(app)
    with app.app_context():
        yield app


MATTER_OUTPUTS = ('MATTER_ON_OFF', 'MATTER_LEVEL', 'MATTER_COVERING')


@pytest.mark.parametrize('output_type', MATTER_OUTPUTS)
def test_matter_outputs_register_the_creation_guard(output_type):
    from aot.utils.outputs import parse_output_information
    info = parse_output_information()[output_type]
    assert callable(info.get('execute_at_creation'))


def test_matter_input_registers_the_creation_guard():
    from aot.utils.inputs import parse_input_information
    assert callable(parse_input_information()['MATTER_NODE'].get('execute_at_creation'))


def test_creation_refused_outside_settings(babel_app):
    row = SimpleNamespace()
    error, same = matter_onboarding.refuse_outside_settings([], row)
    assert same is row
    assert error and 'Settings > Matter' in error[0]


def test_creation_allowed_while_settings_commissions_a_node(babel_app):
    with matter_onboarding.pending_node({'node_id': 7}):
        error, _ = matter_onboarding.refuse_outside_settings([], SimpleNamespace())
    assert error == []


def test_creation_allowed_while_settings_refreshes_a_device(babel_app):
    with matter_onboarding.adding_children():
        error, _ = matter_onboarding.refuse_outside_settings([], SimpleNamespace())
    assert error == []
    # and the permission ends with the block
    error, _ = matter_onboarding.refuse_outside_settings([], SimpleNamespace())
    assert error


def test_refresh_creates_children_inside_the_permission(monkeypatch):
    """refresh_device adds children for new endpoints through _create_children —
    which must hold the permission, or the guard refuses Settings' own refresh."""
    from aot.aot_flask.utils import utils_matter
    seen = []

    def fake_members(error, device, blueprint):
        seen.append(getattr(matter_onboarding._local, 'children', False))
        return error, {'inputs': [], 'outputs': []}

    monkeypatch.setattr('aot.utils.device_blueprint.create_blueprint_members', fake_members)
    utils_matter._create_children(SimpleNamespace(), {'inputs': [], 'outputs': []},
                                  {'warnings': []})
    assert seen == [True]


# -- operate_device ---------------------------------------------------------

from aot.outputs.command_forms import plan_output_command  # noqa: E402


def _plan(state, output_type, value=None, duration=0.0):
    return plan_output_command(state, output_type, value, duration)


def test_relay_keeps_its_timed_on_and_off():
    assert _plan('on', 'MATTER_ON_OFF', duration=30.0) == \
        {'state': 'on', 'output_type': 'sec', 'amount': 30.0}
    assert _plan('off', 'MATTER_ON_OFF') == {'state': 'off', 'output_type': 'sec', 'amount': 0}


def test_relay_takes_no_value():
    assert 'error' in _plan('set_value', 'MATTER_ON_OFF', value=50)


def test_dimmer_on_and_set_value_go_out_as_pwm():
    assert _plan('on', 'MATTER_LEVEL') == {'state': 'on', 'output_type': 'pwm', 'amount': 100.0}
    assert _plan('on', 'MATTER_LEVEL', value=40) == \
        {'state': 'on', 'output_type': 'pwm', 'amount': 40.0}
    assert _plan('set_value', 'MATTER_LEVEL', value=25) == \
        {'state': 'on', 'output_type': 'pwm', 'amount': 25.0}
    assert _plan('off', 'MATTER_LEVEL')['state'] == 'off'


@pytest.mark.parametrize('output_type', ['MATTER_COVERING', 'actuator_paired'])
def test_position_outputs_open_and_close_are_positions(output_type):
    assert _plan('open', output_type) == {'state': 'on', 'output_type': 'value', 'amount': 100.0}
    assert _plan('on', output_type) == {'state': 'on', 'output_type': 'value', 'amount': 100.0}
    assert _plan('close', output_type) == {'state': 'on', 'output_type': 'value', 'amount': 0.0}
    # off is Stop — it must not be turned into a close
    assert _plan('off', output_type) == {'state': 'off', 'output_type': 'sec', 'amount': 0}
    assert _plan('set_value', output_type, value=30) == \
        {'state': 'on', 'output_type': 'value', 'amount': 30.0}


def test_plain_value_output_refuses_on_instead_of_doing_nothing():
    assert 'error' in _plan('on', 'MQTT_PAHO_VALUE')
    assert _plan('set_value', 'MQTT_PAHO_VALUE', value=3)['output_type'] == 'value'


def test_manifest_capabilities_match_the_plan():
    from aot.ai.services.ai_action_service import _output_capabilities
    assert _output_capabilities('MATTER_ON_OFF') == ['on', 'off']
    assert set(_output_capabilities('MATTER_LEVEL')) == {'on', 'off', 'set_value'}
    assert set(_output_capabilities('MATTER_COVERING')) == {'open', 'close', 'off', 'set_value'}
    assert set(_output_capabilities('MQTT_PAHO_VALUE')) == {'set_value', 'off'}
    for output_type in ('MATTER_ON_OFF', 'MATTER_LEVEL', 'MATTER_COVERING', 'MQTT_PAHO_VALUE'):
        for state in _output_capabilities(output_type):
            assert 'error' not in _plan(state, output_type, value=50), (output_type, state)


# -- PWM / position level (2026-11-12: MCP AI said actuators only did on/off) --

def test_pwm_module_takes_a_level():
    assert _plan('set_value', 'python_pwm', value=40) == \
        {'state': 'on', 'output_type': 'pwm', 'amount': 40.0}
    assert _plan('set_value', 'python_pwm', value='40%')['amount'] == 40.0
    assert _plan('on', 'python_pwm', value=55) == \
        {'state': 'on', 'output_type': 'pwm', 'amount': 55.0}


@pytest.mark.parametrize('value', [-1, 100.5, 150])
def test_pwm_level_out_of_range_is_refused_not_dropped(value):
    # pwm_python.output_switch returns without switching outside 0-100 and the daemon
    # still answers success — refuse before sending.
    assert 'error' in _plan('set_value', 'python_pwm', value=value)
    if value > 100:
        assert 'error' in _plan('on', 'python_pwm', value=value)


def test_position_level_out_of_range_is_refused():
    assert 'error' in _plan('set_value', 'MATTER_COVERING', value=120)


def test_set_value_without_a_value_is_refused():
    assert 'error' in _plan('set_value', 'python_pwm')
    assert 'error' in _plan('set_value', 'python_pwm', value='abc')


def test_plain_value_output_is_not_bounded():
    assert _plan('set_value', 'MQTT_PAHO_VALUE', value=1500)['amount'] == 1500.0


def test_value_range_is_shown_only_for_levels():
    from aot.outputs.command_forms import value_range
    assert value_range('python_pwm') == '0-100 %'
    assert value_range('MATTER_COVERING') == '0-100 %'
    assert value_range('MATTER_ON_OFF') is None
    assert value_range('MQTT_PAHO_VALUE') is None
