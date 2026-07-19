# coding=utf-8
#
# on_off_virtual.py - Virtual output for testing with no hardware dependencies
#
from flask_babel import lazy_gettext

from aot.outputs.base_output import AbstractOutput
from aot.config_translations import TRANSLATIONS

# Measurements (one for each of 8 channels)
measurements_dict = {
    0: {'measurement': 'duration_time', 'unit': 's'},
    1: {'measurement': 'duration_time', 'unit': 's'},
    2: {'measurement': 'duration_time', 'unit': 's'},
    3: {'measurement': 'duration_time', 'unit': 's'},
    4: {'measurement': 'duration_time', 'unit': 's'},
    5: {'measurement': 'duration_time', 'unit': 's'},
    6: {'measurement': 'duration_time', 'unit': 's'},
    7: {'measurement': 'duration_time', 'unit': 's'},
}

# 8 Virtual Channels
channels_dict = {
    0: {'types': ['on_off'], 'measurements': [0]},
    1: {'types': ['on_off'], 'measurements': [1]},
    2: {'types': ['on_off'], 'measurements': [2]},
    3: {'types': ['on_off'], 'measurements': [3]},
    4: {'types': ['on_off'], 'measurements': [4]},
    5: {'types': ['on_off'], 'measurements': [5]},
    6: {'types': ['on_off'], 'measurements': [6]},
    7: {'types': ['on_off'], 'measurements': [7]},
}

# Output information
OUTPUT_INFORMATION = {
    'output_name_unique': 'virtual_on_off_multi',
    'output_name': "{} (Virtual Multi-Channel)".format(lazy_gettext('On/Off')),
    'output_library': 'Internal',
    'measurements_dict': measurements_dict,
    'channels_dict': channels_dict,
    'output_types': ['on_off'],

    'message': 'A virtual output device for testing. States are stored in memory and have no effect on hardware.',

    'options_enabled': [
        'button_on',
        'button_send_duration'
    ],

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
            'id': 'amps',
            'type': 'float',
            'default_value': 0.0,
            'required': True,
            'name': "{} ({})".format(lazy_gettext('Current'), lazy_gettext('Amps')),
            'phrase': 'The current draw of the virtual device'
        }
    ]
}


class OutputModule(AbstractOutput):
    """Simulate an 8-channel on/off output in memory for testing.

    @phase active
    @stability stable
    @dependency AbstractOutput
    """
    def __init__(self, output, testing=False):
        super().__init__(output, testing=testing, name=__name__)

    def initialize(self):
        self.setup_output_variables(OUTPUT_INFORMATION)
        # Initialize channels to False (Off) instead of None
        for chan in range(8):
            self.output_states[chan] = False
        self.output_setup = True
        self.logger.info("Virtual Output Initialized (8 Channels)")

    def output_switch(self, state, output_type=None, amount=None, output_channel=0):
        if not self.is_setup():
            self.logger.error('Output not set up')
            return

        chan = 0
        try:
            if output_channel is not None:
                chan = int(output_channel)
        except (ValueError, TypeError):
            pass

        if state == 'on':
            self.output_states[chan] = True
            self.logger.debug(f"Virtual Channel {chan} turned ON")
        elif state == 'off':
            self.output_states[chan] = False
            self.logger.debug(f"Virtual Channel {chan} turned OFF")

    def is_on(self, output_channel=0):
        if self.is_setup():
            chan = 0
            try:
                if output_channel is not None:
                    chan = int(output_channel)
            except (ValueError, TypeError):
                pass
            return self.output_states.get(chan, False)
        return False

    def is_setup(self):
        return self.output_setup

    def stop_output(self):
        self.running = False
