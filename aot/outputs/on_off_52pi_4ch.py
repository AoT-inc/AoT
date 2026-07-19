# coding=utf-8
#
# on_off_52pi_4ch.py - Output for the EP-0099 (PCA9554) I2C 8-Channel Relay Board
# 2025-04-21

from flask_babel import lazy_gettext

from aot.config_translations import TRANSLATIONS
from aot.databases.models import OutputChannel
from aot.outputs.base_output import AbstractOutput
from aot.utils.database import db_retrieve_table_daemon

# Measurements
measurements_dict = {
    0: {
        'measurement': 'duration_time',
        'unit': 's',
    },
    1: {
        'measurement': 'duration_time',
        'unit': 's',
    },
    2: {
        'measurement': 'duration_time',
        'unit': 's',
    },
    3: {
        'measurement': 'duration_time',
        'unit': 's',
    }
}

channels_dict = {
    0: {
        'name': 'Relay 1',
        'types': ['on_off'],
        'measurements': [0]
    },
    1: {
        'name': 'Relay 2',
        'types': ['on_off'],
        'measurements': [1]
    },
    2: {
        'name': 'Relay 3',
        'types': ['on_off'],
        'measurements': [2]
    },
    3: {
        'name': 'Relay 4',
        'types': ['on_off'],
        'measurements': [3]
    }
}

# Output information
OUTPUT_INFORMATION = {
    'output_name_unique': '52pi_4channel_Relay',
    'output_name': "{}: 52pi EP-0099 4channel Relay (4-Channel board)".format(lazy_gettext('On/Off')),
    'output_manufacturer': '52Pi',
    'output_library': 'smbus2',
    'measurements_dict': measurements_dict,
    'channels_dict': channels_dict,
    'output_types': ['on_off'],

    'message': 'Controls the 4 channel multichannel relay board.',

    'options_enabled': [
        'i2c_location',
        'button_on',
    ],
    'options_disabled': ['interface'],

    'dependencies_module': [
        ('pip-pypi', 'smbus2', 'smbus2==0.4.1')
    ],

    'interfaces': ['I2C'],
    'i2c_location': [
        '0x11'
    ],
    'i2c_address_editable': True,
    'i2c_address_default': '0x10',

    'custom_channel_options': [
        {
            'id': 'name',
            'type': 'text',
            'default_value': '',
            'required': False,
            'name': TRANSLATIONS['name']['title'],
            'phrase': TRANSLATIONS['name']['phrase']
        },
        {
            'id': 'state_startup',
            'type': 'select',
            'default_value': 0,
            'options_select': [
                (0, 'Off'),
                (1, 'On')
            ],
            'name': lazy_gettext('Startup State'),
            'phrase': 'Set the state of the relay when aot starts'
        },
        {
            'id': 'state_shutdown',
            'type': 'select',
            'default_value': 0,
            'options_select': [
                (0, 'Off'),
                (1, 'On')
            ],
            'name': lazy_gettext('Shutdown State'),
            'phrase': 'Set the state of the relay when aot shuts down'
        },
        {
            'id': 'on_state',
            'type': 'select',
            'default_value': 1,
            'options_select': [
                (1, 'HIGH'),
                (0, 'LOW')
            ],
            'name': lazy_gettext('On State'),
            'phrase': 'The state of the GPIO that corresponds to an On state'
        },
        {
            'id': 'trigger_functions_startup',
            'type': 'bool',
            'default_value': False,
            'name': lazy_gettext('Trigger Functions at Startup'),
            'phrase': 'Whether to trigger functions when the output switches at startup'
        },
        {
            'id': 'amps',
            'type': 'float',
            'default_value': 0.0,
            'required': True,
            'name': "{} ({})".format(lazy_gettext('Current'), lazy_gettext('Amps')),
            'phrase': 'The current draw of the device being controlled'
        }
    ]
}


class OutputModule(AbstractOutput):
    """Control 4 relays on the 52Pi EP-0099 board via I2C.

    @phase active
    @stability stable
    @dependency AbstractOutput, GroveMultiRelay, smbus2
    """
    def __init__(self, output, testing=False):
        super().__init__(output, testing=testing, name=__name__)

        self.sensor = None

        output_channels = db_retrieve_table_daemon(
            OutputChannel).filter(OutputChannel.output_id == output.unique_id).all()
        self.options_channels = self.setup_custom_channel_options_json(
            OUTPUT_INFORMATION['custom_channel_options'], output_channels)

    def initialize(self):
        """Set up the 52Pi EP-0099 relay board over I2C and apply startup states."""
        import smbus2

        self.setup_output_variables(OUTPUT_INFORMATION)

        try:
            self.logger.debug("I2C: Address: {}, Bus: {}".format(self.output.i2c_location, self.output.i2c_bus))
            if self.output.i2c_location:
                self.sensor = GroveMultiRelay(smbus2, self.output.i2c_bus, int(str(self.output.i2c_location), 16))
                self.output_setup = True
        except:
            self.logger.exception("Could not set up output")
            return

        dict_states = {}
        for channel in channels_dict:
            if self.options_channels['state_startup'][channel] == 1:
                dict_states[channel] = bool(self.options_channels['on_state'][channel])
            elif self.options_channels['state_startup'][channel] == 0:
                dict_states[channel] = bool(not self.options_channels['on_state'][channel])
            else:
                # Default state: Off
                dict_states[channel] = bool(not self.options_channels['on_state'][channel])

        self.logger.debug("List sent to device: {}".format(self.dict_to_list_states(dict_states)))
        try:
            self.sensor.port(self.dict_to_list_states(dict_states))
        except OSError as err:
            self.logger.error(
                "OSError: {}. Check that the device is connected properly, the correct "
                "address is selected, and you can communicate with the device.".format(err))
        self.output_states = dict_states

        for channel in channels_dict:
            if self.options_channels['trigger_functions_startup'][channel]:
                try:
                    self.check_triggers(self.unique_id, output_channel=channel)
                except Exception as err:
                    self.logger.error(
                        "Could not check Trigger for channel {} of output {}: {}".format(
                            channel, self.unique_id, err))

    def output_switch(self,
                      state,
                      output_type=None,
                      amount=None,
                      duty_cycle=None,
                      output_channel=None):
        """Set the specified relay channel on or off, preserving other channels."""
        if not self.is_setup():
            msg = "Error 101: Device not set up. See https://aot-inc.github.io/aot/Error-Codes#error-101 for more info."
            self.logger.error(msg)
            return msg

        if output_channel is None:
            msg = "Output channel needs to be specified"
            self.logger.error(msg)
            return msg

        try:
            dict_states = {}
            for channel in channels_dict:
                if output_channel == channel:
                    if state == 'on':
                        dict_states[channel] = bool(self.options_channels['on_state'][channel])
                    elif state == 'off':
                        dict_states[channel] = bool(not self.options_channels['on_state'][channel])
                else:
                    dict_states[channel] = self.output_states[channel]

            self.logger.debug("List sent to device: {}".format(self.dict_to_list_states(dict_states)))
            self.sensor.port(self.dict_to_list_states(dict_states))
            self.output_states[output_channel] = dict_states[output_channel]
            msg = "success"
        except Exception as e:
            msg = "CH{} state change error: {}".format(output_channel, e)
            self.logger.error(msg)
        return msg

    def is_on(self, output_channel=None):
        if self.is_setup():
            if output_channel is not None and output_channel in self.output_states:
                return self.output_states[output_channel] == self.options_channels['on_state'][output_channel]

    def is_setup(self):
        return self.output_setup

    @staticmethod
    def dict_to_list_states(dict_states):
        list_states = []
        for i in range(4):
            list_states.append(dict_states.get(i, False))
        return list_states

    def stop_output(self):
        """Called when Output is stopped."""
        dict_states = {}
        if self.is_setup():
            for channel in channels_dict:
                if self.options_channels['state_shutdown'][channel] == 1:
                    dict_states[channel] = bool(self.options_channels['on_state'][channel])
                elif self.options_channels['state_shutdown'][channel] == 0:
                    dict_states[channel] = bool(not self.options_channels['on_state'][channel])
            self.logger.debug("List sent to device: {}".format(self.dict_to_list_states(dict_states)))
            self.sensor.port(self.dict_to_list_states(dict_states))
        self.running = False


class GroveMultiRelay(object):
    """Drive the 52Pi EP-0099 4-channel relay via per-channel I2C registers.

    @phase active
    @stability stable
    @dependency smbus2
    """
    def __init__(self, smbus, i2c_bus, i2c_address):
        self.bus_no = i2c_bus
        self.bus = smbus.SMBus(i2c_bus)
        self.address = i2c_address
        self.current_state = [False, False, False, False]

    def __repr__(self):
        return "RelayBoard(i2c_bus_no=%r, address=0x%02x)" % (self.bus_no, self.address)

    def port(self, states):
        """Writes on/off to each channel's unique I2C register."""
        if not isinstance(states, list) or len(states) != 4:
            raise AssertionError("States must be a list of 4 boolean values.")
        for i, state in enumerate(states):
            reg = 0x01 + i  # Each relay controlled by register 0x01, 0x02, etc.
            self.bus.write_byte_data(self.address, reg, 0xFF if state else 0x00)
            self.current_state[i] = state
